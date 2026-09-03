"""Parent-process wrapper for the restricted subprocess sandbox."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SandboxError(ValueError):
    """Raised when the sandbox cannot execute code."""


@dataclass
class SandboxResult:
    """Outcome of a sandbox execution."""

    status: str
    stdout: str
    stderr: str
    return_value: Any = None
    artifacts: list[dict[str, Any]] | None = None
    error: str | None = None
    # Files copied to a caller-provided artifact_dir (see run_in_sandbox).
    spilled: list[dict[str, Any]] | None = None


def run_in_sandbox(
    code: str,
    timeout: int = 30,
    memory_limit_mb: int = 2048,
    max_output_bytes: int = 64 * 1024,
    files: dict[str, str] | None = None,
    artifact_dir: str | Path | None = None,
    input_dir: str | Path | None = None,
) -> SandboxResult:
    """Run *code* in a restricted subprocess and return the result.

    The child process is executed via ``python -m thelab.sandbox.child`` so
    that it runs in a fresh interpreter with no access to the parent's
    memory or file descriptors. Optional *files* are written into the
    per-run temp workspace (basename keys only) before execution, giving
    the code read-only access to e.g. a dataset copy.

    ``input_dir`` is an alternative to *files* for large inputs: the parent
    pre-places files there and the child copies them into the workspace,
    avoiding a large stdin JSON round-trip.

    ``artifact_dir`` is a caller-provided directory (trusted parent config,
    never agent input) into which the child copies every whitelisted artifact
    after execution. Inline ``artifacts`` stay capped at 1 MiB for the JSON
    response; ``spilled`` records the on-disk copies for callers that need
    large outputs (e.g. the agentic round's feature-engineering transforms).
    """
    if not code or not isinstance(code, str):
        raise SandboxError("code must be a non-empty string")

    # Defense in depth: both directories are trusted parent config and must be
    # explicit absolute paths — never derived from agent-influenced values.
    for label, value in (("artifact_dir", artifact_dir), ("input_dir", input_dir)):
        if value is not None and not Path(value).is_absolute():
            raise SandboxError(f"{label} must be an absolute path")

    request: dict[str, Any] = {
        "code": code,
        "memory_limit_bytes": memory_limit_mb * 1024 * 1024,
        "max_output_bytes": max_output_bytes,
    }
    if files:
        request["files"] = files
    if artifact_dir is not None:
        request["artifact_dir"] = str(Path(artifact_dir).resolve())
    if input_dir is not None:
        request["input_dir"] = str(Path(input_dir).resolve())

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "thelab.sandbox.child"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            status="timeout",
            stdout="",
            stderr="",
            error=f"sandbox exceeded timeout of {timeout}s",
        )
    except OSError as exc:
        return SandboxResult(
            status="error",
            stdout="",
            stderr="",
            error=f"sandbox process failed: {exc}",
        )

    if proc.returncode != 0:
        return SandboxResult(
            status="error",
            stdout=proc.stdout,
            stderr=proc.stderr,
            error=f"sandbox process exited with code {proc.returncode}",
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return SandboxResult(
            status="error",
            stdout=proc.stdout,
            stderr=proc.stderr,
            error=f"invalid sandbox output: {exc}",
        )

    return SandboxResult(
        status=data.get("status", "unknown"),
        stdout=data.get("stdout", ""),
        stderr=data.get("stderr", ""),
        return_value=data.get("return_value"),
        artifacts=data.get("artifacts"),
        error=data.get("error"),
        spilled=data.get("spilled"),
    )
