"""Artifact helpers for the sandbox workspace.

These utilities are used by the child process to extract approved files from
its temporary workspace. They are kept in a separate module so the policy and
collection logic can be tested independently of the subprocess runner.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from .policy import DEFAULT_POLICY

# Artifacts above this size are replaced by a placeholder marker so one large
# output cannot blow up the HTTP response (hex/base64 inflation is 1.3x-2x).
MAX_ARTIFACT_BYTES = 1024 * 1024


def list_artifacts(workspace: Path) -> list[Path]:
    """Return allowed artifact paths found directly in *workspace*."""
    artifacts: list[Path] = []
    if not workspace.exists() or not workspace.is_dir():
        return artifacts
    for path in sorted(workspace.iterdir()):
        if not path.is_file():
            continue
        if DEFAULT_POLICY.is_artifact_extension_allowed(path.suffix.lower()):
            artifacts.append(path)
    return artifacts


def read_artifact(path: Path) -> dict[str, Any]:
    """Read an artifact and return a JSON-safe description."""
    content = path.read_bytes()
    ext = path.suffix.lower()
    kind = "image" if ext in {".png", ".jpg", ".jpeg", ".svg"} else "text"
    if len(content) > MAX_ARTIFACT_BYTES:
        return {
            "name": path.name,
            "kind": kind,
            "size": len(content),
            "content": f"[artifact too large: {len(content)} bytes]",
            "base64": None,
        }
    text: str | None = None
    encoded: str | None = None
    if kind == "text":
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = "[binary]"
    else:
        encoded = base64.b64encode(content).decode("ascii")
    return {
        "name": path.name,
        "kind": kind,
        "size": len(content),
        "content": text,
        "base64": encoded,
    }
