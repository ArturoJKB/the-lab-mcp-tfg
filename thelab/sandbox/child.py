"""Subprocess entry point for sandboxed code execution.

This module is executed by ``thelab/sandbox/runner.py`` in a fresh Python
interpreter. It reads user code from stdin, enforces the sandbox policy, and
writes a JSON result to stdout.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import resource
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

from thelab.sandbox.artifacts import list_artifacts, read_artifact
from thelab.sandbox.ast_check import check_code
from thelab.sandbox.policy import DEFAULT_POLICY

# The real __import__, captured before any builtins filtering: _safe_import
# delegates to it after whitelist validation so the full import semantics
# (fromlist, submodule-as-binding) are preserved inside the sandbox.
_REAL_IMPORT = __import__


def _set_memory_limit(max_bytes: int) -> None:
    """Set a hard memory limit for this process when resource limits exist."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    except (AttributeError, OSError, ValueError):
        pass


def _safe_import(name: str, globals_: dict[str, Any] | None = None, locals_: dict[str, Any] | None = None, fromlist: tuple[str, ...] = (), level: int = 0) -> ModuleType:  # noqa: ARG001
    """Import hook that enforces the sandbox whitelist.

    Validates *name* against the whitelist, then delegates to the real
    ``__import__`` (captured before builtins filtering). Delegating preserves
    the full import semantics — submodule binding, fromlist handling,
    ``import a.b as t`` — which ``importlib.import_module`` does not
    replicate (matplotlib 3.11's ``import matplotlib.pyplot as plt`` fails
    under an ``import_module`` hook).
    """
    if level != 0:
        raise ImportError("relative imports are not allowed in the sandbox")
    if not DEFAULT_POLICY.is_import_allowed(name):
        raise ImportError(f"import not allowed: {name}")
    return _REAL_IMPORT(name, globals_, locals_, fromlist, level)


def _scrub_sandbox_module_refs() -> None:
    """Remove the sandbox machinery from the ``thelab`` package namespace.

    Importing ``thelab.eda`` initializes the parent ``thelab`` package and, as
    a side effect of this module's own imports, binds ``thelab.sandbox`` (and
    therefore ``os``/``sys``/... as plain attributes of ``child``). Plain
    attribute access is not blocked by the dunder guard, so user code could
    otherwise reach the real ``os`` module without violating policy. The
    functions this module needs were already imported directly at startup.
    """
    package = sys.modules.get("thelab")
    if package is not None and hasattr(package, "sandbox"):
        try:
            delattr(package, "sandbox")
        except AttributeError:
            pass


def _build_builtins() -> dict[str, Any]:
    """Return a filtered builtins dict for the sandbox namespace."""
    builtin_items: dict[str, Any]
    if isinstance(__builtins__, dict):
        builtin_items = __builtins__
    else:
        builtin_items = {name: getattr(__builtins__, name) for name in dir(__builtins__)}
    safe = {
        name: value
        for name, value in builtin_items.items()
        if name not in DEFAULT_POLICY.blocked_builtins
    }
    safe["__import__"] = _safe_import
    return safe


def _run_code(code: str, workspace: Path, max_output_bytes: int) -> dict[str, Any]:
    """Execute *code* in a restricted namespace inside *workspace*."""
    check = check_code(code)
    if not check.ok:
        return {"status": "rejected", "error": check.reason}

    # Close the thelab.sandbox attribute path before user code runs.
    _scrub_sandbox_module_refs()

    os.chdir(workspace)

    namespace: dict[str, Any] = {
        "__builtins__": _build_builtins(),
        "__name__": "__sandbox__",
        "__file__": str(workspace / "script.py"),
    }

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            exec(compile(code, "<sandbox>", "exec"), namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        stderr_capture.write(f"{type(exc).__name__}: {exc}\n")
        return {
            "status": "failed",
            "stdout": _truncate(stdout_capture.getvalue(), max_output_bytes),
            "stderr": _truncate(stderr_capture.getvalue(), max_output_bytes),
            "return_value": None,
        }
    except BaseException as exc:
        # SystemExit and friends would otherwise escape before the result JSON
        # is written, letting a script end the protocol mid-stream.
        stderr_capture.write(f"{type(exc).__name__}: {exc}\n")
        return {
            "status": "failed",
            "stdout": _truncate(stdout_capture.getvalue(), max_output_bytes),
            "stderr": _truncate(stderr_capture.getvalue(), max_output_bytes),
            "return_value": None,
        }

    return_value = namespace.get("__return__")
    return {
        "status": "completed",
        "stdout": _truncate(stdout_capture.getvalue(), max_output_bytes),
        "stderr": _truncate(stderr_capture.getvalue(), max_output_bytes),
        "return_value": return_value if _is_json_safe(return_value) else repr(return_value),
    }


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate *text* so its UTF-8 encoding is at most *max_bytes* long."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    # Drop a potential trailing partial codepoint.
    while truncated and (truncated[-1] & 0xC0) == 0x80:
        truncated = truncated[:-1]
    return truncated.decode("utf-8", errors="ignore") + "\n[output truncated]"


def _is_json_safe(value: Any) -> bool:
    """Return True if *value* is JSON-serializable by the default encoder."""
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def main() -> None:
    """Read sandbox request from stdin and write JSON result to stdout."""
    # Force a headless matplotlib backend before user code can import it.
    os.environ.setdefault("MPLBACKEND", "Agg")

    request = json.load(sys.stdin)
    code = request.get("code", "")
    memory_limit = request.get("memory_limit_bytes")
    max_output_bytes = request.get("max_output_bytes", 64 * 1024)
    files = request.get("files") or {}
    # Trusted parent-provided directories (never agent input):
    # - input_dir: pre-placed input files copied into the workspace.
    # - artifact_dir: outputs are copied here after execution so callers can
    #   read large artifacts from disk (inline artifacts stay capped at 1 MiB).
    input_dir = request.get("input_dir")
    artifact_dir = request.get("artifact_dir")

    if memory_limit:
        _set_memory_limit(memory_limit)

    with tempfile.TemporaryDirectory(prefix="thelab-sandbox-") as tmp:
        workspace = Path(tmp)
        # Pre-place trusted files (dataset copies) into the workspace before
        # restricted execution. Keys are basenames; content is plain text.
        for name, content in files.items():
            safe_name = Path(str(name)).name
            if not safe_name or safe_name.startswith("."):
                continue
            (workspace / safe_name).write_text(str(content), encoding="utf-8", errors="replace")
        if input_dir:
            _copy_inputs(Path(input_dir), workspace)
        result = _run_code(code, workspace, max_output_bytes)
        if result["status"] in {"completed", "failed"}:
            collected = list_artifacts(workspace)
            result["artifacts"] = [read_artifact(path) for path in collected]
            if artifact_dir:
                result["spilled"] = _spill_artifacts(collected, Path(artifact_dir))
        json.dump(result, sys.stdout)


def _copy_inputs(input_dir: Path, workspace: Path) -> None:
    """Copy caller-provided input files into the workspace (trusted code)."""
    import shutil

    if not input_dir.is_dir():
        return
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        safe_name = path.name
        if not safe_name or safe_name.startswith("."):
            continue
        shutil.copyfile(path, workspace / safe_name)


def _spill_artifacts(collected: list[Path], artifact_dir: Path) -> list[dict[str, Any]]:
    """Copy collected artifacts into *artifact_dir* (trusted code).

    Returns JSON-safe records with the on-disk destination paths.
    """
    import shutil

    if not artifact_dir.is_absolute():
        return []
    artifact_dir.mkdir(parents=True, exist_ok=True)
    spilled: list[dict[str, Any]] = []
    for path in collected:
        dest = artifact_dir / path.name
        counter = 1
        while dest.exists():
            dest = artifact_dir / f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        shutil.copyfile(path, dest)
        spilled.append({"name": path.name, "path": str(dest), "size": dest.stat().st_size})
    return spilled


if __name__ == "__main__":
    main()
