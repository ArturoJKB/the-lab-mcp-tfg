"""Structured filter helpers for context search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SearchFilters:
    """Structured filters supported by the context search command."""

    run_id: str | None = None
    tags: list[str] | None = None
    event_type: str | None = None
    since: datetime | None = None
    until: datetime | None = None

    def with_defaults(self) -> SearchFilters:
        """Return a copy with tags normalized to a list."""
        return SearchFilters(
            run_id=self.run_id,
            tags=list(self.tags) if self.tags else [],
            event_type=self.event_type,
            since=self.since,
            until=self.until,
        )
