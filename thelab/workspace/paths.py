from pathlib import Path

RUNS_DIR = "runs"


def ensure_run_dir(workspace_root: Path, run_id: str) -> Path:
    """Create and return the run directory under ``<workspace_root>/runs/<run_id>``."""
    run_path = Path(workspace_root) / RUNS_DIR / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    return run_path


def artifact_path(workspace_root: Path, run_id: str, relative_path: str | Path) -> Path:
    """Return an absolute artifact path guaranteed to live inside the run directory.

    Raises ``ValueError`` if ``relative_path`` attempts to escape ``runs/<run_id>/``.
    """
    run_path = ensure_run_dir(workspace_root, run_id)
    target = run_path / relative_path
    try:
        target.resolve().relative_to(run_path.resolve())
    except ValueError as exc:
        raise ValueError(f"artifact path escapes run directory: {relative_path}") from exc
    return target
