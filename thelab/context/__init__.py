"""Local context store: SQLite + FTS5 indexing of JSONL agent logs."""

from .contracts import IndexedEntry
from .privacy import AGENT_SAFE_PRIVACY_LEVELS, normalize_log_privacy
from .reader import ContextReader, ContextReaderError
from .repository import ContextRepository

__all__ = [
    "AGENT_SAFE_PRIVACY_LEVELS",
    "ContextReader",
    "ContextReaderError",
    "ContextRepository",
    "IndexedEntry",
    "normalize_log_privacy",
]
