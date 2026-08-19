import hashlib
import json
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    hasher = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_json(obj: object) -> str:
    """Return a deterministic SHA-256 hex digest for a JSON-serializable object."""
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hash_bytes(payload)
