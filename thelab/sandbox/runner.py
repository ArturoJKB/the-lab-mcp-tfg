"""Parent-process wrapper for the restricted subprocess sandbox."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
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


def run_in_sandbox(
    code: str,
    timeout: int = 30,
    memory_limit_mb: int = 512,
    max_output_bytes: int = 64 * 1024,
) -> SandboxResult:
    """Run *code* in a restricted subprocess and return the result.

    The child process is executed via ``python -m thelab.sandbox.child`` so
    that it runs in a fresh interpreter with no access to the parent's
    memory or file descriptors.
    """
    if not code or not isinstance(code, str):
        raise SandboxError("code must be a non-empty string")

    request = {
        "code": code,
        "memory_limit_bytes": memory_limit_mb * 1024 * 1024,
        "max_output_bytes": max_output_bytes,
    }

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
    )
