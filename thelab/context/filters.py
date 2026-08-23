"""Structured filter helpers for context search."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_FTS_SYNTAX_PATTERN = re.compile(r'"|\*|\(|\)|\b(?:AND|OR|NOT|NEAR)\b')
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


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


def build_match_query(query: str) -> tuple[str, str]:
    """Build an FTS5 MATCH expression from a user query.

    Returns ``(expression, mode)`` where mode is:

    - ``"fts"``: the query already contains explicit FTS5 syntax and is
      passed through unchanged.
    - ``"expanded"``: plain keywords were expanded into a prefix OR-query
      (``token* OR token* ...``) to improve recall.
    """
    if not query or _FTS_SYNTAX_PATTERN.search(query):
        return query, "fts"
    tokens = _TOKEN_PATTERN.findall(query)
    if not tokens:
        return query, "fts"
    expanded = " OR ".join(f"{token}*" for token in tokens)
    return expanded, "expanded"


def like_fallback_pattern(query: str) -> tuple[str, list[str]] | None:
    """Return a LIKE clause and parameters for substring fallback.

    The clause matches any query token as a substring of
    ``e.redacted_summary``. Returns ``None`` when the query has no usable
    tokens.
    """
    tokens = _TOKEN_PATTERN.findall(query) if query else []
    if not tokens:
        return None
    clauses = []
    params: list[str] = []
    for token in tokens:
        escaped = (
            token.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        )
        clauses.append(r"e.redacted_summary LIKE ? ESCAPE '\'")
        params.append(f"%{escaped}%")
    return " OR ".join(f"({clause})" for clause in clauses), params
