"""Dataset upload and discovery helpers for the IDE.

Uploaded files are stored under ``data/uploads/`` (configurable via
``THELAB_UPLOADS_DIR``). Fixtures under ``data/fixtures/`` are also listed.
All external IDs use the form ``uploads/<basename>`` or ``fixtures/<basename>``
so that no absolute paths leak through the API.
"""

from __future__ import annotations

import os
from io import BufferedReader
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

_DEFAULT_UPLOADS_DIR = Path("data") / "uploads"
_DEFAULT_FIXTURES_DIR = Path("data") / "fixtures"
_DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


class UploadError(ValueError):
    """Raised when an upload fails validation."""


class DatasetNotFoundError(ValueError):
    """Raised when a requested dataset does not exist or is unsafe."""


def _workspace_root() -> Path:
    """Return the workspace root (current working directory by default)."""
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))


def get_uploads_root() -> Path:
    """Return the directory where uploaded datasets are stored."""
    root = Path(os.environ.get("THELAB_UPLOADS_DIR", _DEFAULT_UPLOADS_DIR))
    if root.is_absolute():
        return root
    return _workspace_root() / root


def get_fixtures_root() -> Path:
    """Return the directory where fixture datasets are stored."""
    root = Path(os.environ.get("THELAB_FIXTURES_DIR", _DEFAULT_FIXTURES_DIR))
    if root.is_absolute():
        return root
    return _workspace_root() / root


def _max_upload_bytes() -> int:
    raw = os.environ.get("THELAB_MAX_UPLOAD_BYTES")
    if raw is None:
        return _DEFAULT_MAX_UPLOAD_BYTES
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_MAX_UPLOAD_BYTES


def _is_safe_basename(name: str) -> bool:
    """Reject names that could escape a directory or hide entries."""
    if not name or "/" in name or "\\" in name or name == ".." or ".." in Path(name).parts:
        return False
    if name.startswith("."):
        return False
    return True


def sanitize_filename(name: str) -> str:
    """Return a safe basename for an uploaded file.

    Preserves the ``.csv`` extension when present. Rejects unsafe or hidden
    names rather than silently mangling them.
    """
    name = name.strip()
    if not name:
        raise UploadError("filename is empty")
    # Reject traversal or separator characters in the original name before
    # normalization so that ``../etc/passwd.csv`` is caught, not normalized
    # to ``passwd.csv``.
    if "/" in name or "\\" in name or ".." in Path(name).parts:
        raise UploadError(f"unsafe filename: {name}")
    # Normalize path separators and take basename.
    basename = Path(name).name
    if not _is_safe_basename(basename):
        raise UploadError(f"unsafe filename: {name}")
    if not basename.lower().endswith(".csv"):
        raise UploadError("only CSV files are supported")
    return basename


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _count_rows_columns(path: Path) -> tuple[int, int]:
    """Return (rows, columns) for a CSV without loading the full frame twice."""
    df = pd.read_csv(path)
    return len(df), len(df.columns)


def validate_csv(path: Path) -> None:
    """Validate that ``path`` is a readable non-empty CSV."""
    if not path.is_file():
        raise UploadError("file not found")
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise UploadError(f"cannot parse CSV: {exc}") from exc
    if len(df) == 0:
        raise UploadError("dataset is empty (no rows)")
    if len(df.columns) == 0:
        raise UploadError("dataset has no columns")


def save_upload(file: BufferedReader | BinaryIO, filename: str) -> dict[str, Any]:
    """Save an uploaded CSV under ``data/uploads/`` and return metadata.

    ``file`` is a file-like object opened in binary mode. The file is read
    once, validated, and persisted.
    """
    basename = sanitize_filename(filename)
    uploads_root = get_uploads_root()
    _ensure_dir(uploads_root)

    max_bytes = _max_upload_bytes()
    data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadError(f"file exceeds maximum size of {max_bytes} bytes")
    if len(data) == 0:
        raise UploadError("uploaded file is empty")

    dest = uploads_root / basename
    # If a file with the same name exists, append a numeric suffix.
    if dest.exists():
        stem = Path(basename).stem
        suffix = Path(basename).suffix
        counter = 1
        while True:
            candidate = uploads_root / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                dest = candidate
                break
            counter += 1

    try:
        dest.write_bytes(data)
    except OSError as exc:
        raise UploadError(f"failed to write upload: {exc}") from exc

    validate_csv(dest)
    rows, columns = _count_rows_columns(dest)
    dataset_id = f"uploads/{dest.name}"
    return {
        "dataset_id": dataset_id,
        "filename": dest.name,
        "source": "upload",
        "rows": rows,
        "columns": columns,
    }


def _list_csv_files(root: Path, source: str) -> list[dict[str, Any]]:
    """List CSV files under ``root`` and return stable metadata."""
    if not root.exists() or not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        try:
            rows, columns = _count_rows_columns(path)
        except Exception:
            continue
        items.append(
            {
                "dataset_id": f"{source}/{path.name}",
                "filename": path.name,
                "source": source,
                "rows": rows,
                "columns": columns,
            }
        )
    return items


def list_datasets() -> list[dict[str, Any]]:
    """Return all upload and fixture datasets."""
    uploads = _list_csv_files(get_uploads_root(), "uploads")
    fixtures = _list_csv_files(get_fixtures_root(), "fixtures")
    return uploads + fixtures


def resolve_dataset_path(dataset_id: str) -> Path:
    """Resolve a dataset ID to a contained filesystem path.

    IDs are ``uploads/<basename>`` or ``fixtures/<basename>``. Raises
    ``DatasetNotFoundError`` for unsafe or missing IDs.
    """
    if not isinstance(dataset_id, str) or not dataset_id:
        raise DatasetNotFoundError("dataset_id is empty")
    parts = dataset_id.split("/", 1)
    if len(parts) != 2 or parts[0] not in {"uploads", "fixtures"}:
        raise DatasetNotFoundError(f"invalid dataset_id: {dataset_id}")
    source, basename = parts
    if not _is_safe_basename(basename):
        raise DatasetNotFoundError(f"unsafe dataset_id: {dataset_id}")

    if source == "uploads":
        root = get_uploads_root()
    else:
        root = get_fixtures_root()

    candidate = (root / basename).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise DatasetNotFoundError(f"dataset escapes root: {dataset_id}") from exc

    if not candidate.is_file():
        raise DatasetNotFoundError(f"dataset not found: {dataset_id}")
    return candidate
