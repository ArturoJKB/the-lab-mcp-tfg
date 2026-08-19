"""CLI for the local context store.

Commands:
    thelab context index [--source PATH] [--db PATH]
    thelab context search "<query>" [--run-id] [--tag] [--event-type]
                          [--since] [--until] [--db PATH]
    thelab context show <event_id> [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .filters import SearchFilters
from .indexer import index_source_file
from .reader import ContextReader, ContextReaderError
from .repository import ContextRepository

DEFAULT_SOURCE_PATH = Path(".thelab") / "local-logs" / "agent-events.jsonl"
DEFAULT_DB_PATH = Path(".thelab") / "context" / "context.db"


def _get_db_path(args: argparse.Namespace) -> Path:
    if getattr(args, "db", None):
        return Path(args.db)
    env_path = os.environ.get("THELAB_CONTEXT_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def _entry_to_dict(entry: Any) -> dict[str, Any]:
    """Serialize an IndexedEntry to a plain dict for JSON output."""
    return {
        "event_id": entry.event_id,
        "event_type": entry.event_type,
        "session_id": entry.session_id,
        "run_id": entry.run_id,
        "tags": entry.tags,
        "redacted_summary": entry.redacted_summary,
        "related_artifact_refs": [
            ref.model_dump(mode="json") for ref in entry.related_artifact_refs
        ],
        "privacy_level": entry.privacy_level,
        "timestamp": entry.timestamp.isoformat(),
        "content_hash": entry.content_hash,
        "indexed_at": entry.indexed_at.isoformat(),
    }


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _cmd_index(args: argparse.Namespace) -> int:
    source = Path(args.source) if args.source else DEFAULT_SOURCE_PATH
    db_path = _get_db_path(args)
    repo = ContextRepository(db_path)

    result = index_source_file(source, repo)

    ok = len(result.errors) == 0
    print(
        json.dumps(
            {
                "ok": ok,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "errors": result.errors,
                "source": str(source),
                "db": str(db_path),
            },
            indent=2,
        )
    )
    return 0 if ok else 1


def _cmd_search(args: argparse.Namespace) -> int:
    db_path = _get_db_path(args)
    reader = ContextReader(db_path)

    tags = list(args.tag) if args.tag else None
    filters = SearchFilters(
        run_id=args.run_id,
        tags=tags,
        event_type=args.event_type,
        since=_parse_iso(args.since),
        until=_parse_iso(args.until),
    )

    try:
        entries = reader.search(
            query=args.query,
            run_id=filters.run_id,
            tags=filters.tags,
            event_type=filters.event_type,
            since=filters.since,
            until=filters.until,
            limit=args.limit,
        )
    except ContextReaderError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    print(json.dumps({"ok": True, "count": len(entries), "data": [_entry_to_dict(e) for e in entries]}, indent=2))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    db_path = _get_db_path(args)
    reader = ContextReader(db_path)

    try:
        entry = reader.get(args.event_id)
    except ContextReaderError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    if entry is None:
        print(json.dumps({"ok": False, "error": f"event not found: {args.event_id}"}, indent=2))
        return 1

    print(json.dumps({"ok": True, "data": _entry_to_dict(entry)}, indent=2))
    return 0


def _add_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register context subcommands on a parent subparser."""
    index_parser = subparsers.add_parser("index", help="Index local logs into SQLite")
    index_parser.add_argument(
        "--source",
        default=None,
        help="Source JSONL file. Defaults to .thelab/local-logs/agent-events.jsonl.",
    )
    index_parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite context database. Overrides THELAB_CONTEXT_DB.",
    )
    index_parser.set_defaults(func=_cmd_index)

    search_parser = subparsers.add_parser("search", help="Search indexed context")
    search_parser.add_argument("query", nargs="?", default=None, help="FTS5 keyword query")
    search_parser.add_argument("--run-id", default=None, help="Filter by run_id")
    search_parser.add_argument("--tag", action="append", default=None, help="Filter by tag (repeatable)")
    search_parser.add_argument("--event-type", default=None, help="Filter by event type")
    search_parser.add_argument("--since", default=None, help="ISO timestamp lower bound")
    search_parser.add_argument("--until", default=None, help="ISO timestamp upper bound")
    search_parser.add_argument("--limit", type=int, default=50, help="Maximum results")
    search_parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite context database. Overrides THELAB_CONTEXT_DB.",
    )
    search_parser.set_defaults(func=_cmd_search)

    show_parser = subparsers.add_parser("show", help="Show a single context entry")
    show_parser.add_argument("event_id", help="Event identifier")
    show_parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite context database. Overrides THELAB_CONTEXT_DB.",
    )
    show_parser.set_defaults(func=_cmd_show)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thelab context",
        description="Local context store: index and search agent logs.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    _add_subparsers(subparsers)
    return parser


def build_parser_with_parent(parent: argparse.ArgumentParser) -> None:
    """Wire context commands into a parent argparse parser (used by ``thelab`` top-level CLI)."""
    subparsers = parent.add_subparsers(dest="context_subcommand", required=True)
    _add_subparsers(subparsers)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[Any], int] = args.func
    try:
        return func(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
