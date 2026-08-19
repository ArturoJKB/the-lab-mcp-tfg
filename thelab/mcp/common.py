"""Shared helpers for The Lab MCP servers.

Provides safe run discovery, manifest loading, and path validation.
All paths are resolved relative to a configurable runs root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _is_safe_run_id(run_id: str) -> bool:
    """Reject run IDs that could escape the runs directory or hide entries."""
    if not run_id:
        return False
    if "/" in run_id or "\\" in run_id or run_id == ".." or ".." in Path(run_id).parts:
        return False
    if run_id.startswith("."):
        return False
    return True


def safe_run_dir(runs_root: Path, run_id: str) -> Path | None:
    """Return the absolute run directory if run_id is safe and exists.

    Returns None for unsafe or missing run IDs.
    """
    if not _is_safe_run_id(run_id):
        return None
    candidate = Path(runs_root) / run_id
    try:
        resolved = candidate.resolve()
        root_resolved = Path(runs_root).resolve()
        if root_resolved not in resolved.parents and resolved != root_resolved:
            return None
    except (OSError, ValueError):
        return None
    if not resolved.is_dir():
        return None
    return resolved


def discover_run_ids(runs_root: Path) -> list[str]:
    """List safe run directory names under runs_root."""
    root = Path(runs_root)
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and _is_safe_run_id(p.name)
    )


def load_json_artifact(runs_root: Path, run_id: str, filename: str) -> dict[str, Any] | None:
    """Load a JSON artifact from a run directory.

    Returns None if the run is unsafe, missing, or the file cannot be parsed.
    """
    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        return None
    artifact_path = run_path / filename
    try:
        if not artifact_path.is_file():
            return None
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, ValueError):
        return None


def load_text_artifact(runs_root: Path, run_id: str, filename: str) -> str | None:
    """Load a text artifact from a run directory.

    Returns None if the run is unsafe, missing, or the file cannot be read.
    """
    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        return None
    artifact_path = run_path / filename
    try:
        if not artifact_path.is_file():
            return None
        return artifact_path.read_text(encoding="utf-8")
    except OSError:
        return None


def get_runs_root() -> Path:
    """Return the default runs root, configurable via THELAB_RUNS_ROOT env var."""
    import os
    return Path(os.environ.get("THELAB_RUNS_ROOT", "runs"))
