"""Local stdio MCP server exposing read-only context retrieval.

Tools:
- get_context_status
- get_context_entry(event_id)
- search_context(query?, run_id?, tags?, event_type?, since?, until?, limit?)

The server never writes to the context database. It opens the database with
SQLite ``mode=ro`` and ``PRAGMA query_only=ON`` via ``ContextReader``.

The database path is read from ``THELAB_CONTEXT_DB``; no tool accepts a path
argument.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from thelab.context.reader import ContextReader, ContextReaderError

DEFAULT_CONTEXT_DB = Path(".thelab") / "context" / "context.db"


def _get_context_db_path() -> Path:
    """Return the context DB path from the environment or the default."""
    env_path = os.environ.get("THELAB_CONTEXT_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONTEXT_DB


def _ok(data: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": True, "data": data}))]
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": False, "error": message}))]
    )


TOOLS = [
    types.Tool(
        name="get_context_status",
        description="Return the status of the local context index.",
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
    ),
    types.Tool(
        name="get_context_entry",
        description="Return a single context entry by event_id.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "event_id": {"type": "string", "minLength": 1},
            },
            "required": ["event_id"],
        },
    ),
    types.Tool(
        name="search_context",
        description="Search context entries using FTS5 and structured filters.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "FTS5 keyword query",
                    "maxLength": 200,
                },
                "run_id": {"type": "string"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 64},
                    "maxItems": 10,
                },
                "event_type": {"type": "string"},
                "since": {
                    "type": "string",
                    "description": "ISO-8601 timestamp lower bound",
                },
                "until": {
                    "type": "string",
                    "description": "ISO-8601 timestamp upper bound",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
        },
    ),
]


def _entry_to_dict(entry: Any) -> dict[str, Any]:
    """Serialize an IndexedEntry to a public, JSON-safe dict.

    This deliberately excludes internal/indexing metadata (content_hash and
    indexed_at) so the MCP response surface stays stable and does not leak
    implementation details.
    """
    data = entry.model_dump(
        mode="json",
        include={
            "event_id",
            "event_type",
            "session_id",
            "run_id",
            "tags",
            "redacted_summary",
            "related_artifact_refs",
            "privacy_level",
            "timestamp",
        },
    )
    return data if isinstance(data, dict) else dict(data)


class _ContextService:
    def __init__(self) -> None:
        self.reader = ContextReader(_get_context_db_path())

    def get_status(self) -> types.CallToolResult:
        return _ok(self.reader.status())

    def get_entry(self, arguments: dict[str, Any]) -> types.CallToolResult:
        event_id = arguments.get("event_id", "")
        if not isinstance(event_id, str) or not event_id:
            return _error("event_id is required")
        entry = self.reader.get(event_id)
        if entry is None:
            return _error(f"entry not found: {event_id}")
        return _ok(_entry_to_dict(entry))

    def search(self, arguments: dict[str, Any]) -> types.CallToolResult:
        query = arguments.get("query") or None
        run_id = arguments.get("run_id") or None
        tags = arguments.get("tags") or None
        event_type = arguments.get("event_type") or None
        since = arguments.get("since") or None
        until = arguments.get("until") or None
        limit = arguments.get("limit", 50)

        try:
            entries = self.reader.search(
                query=query,
                run_id=run_id,
                tags=tags,
                event_type=event_type,
                since=since,
                until=until,
                limit=limit,
            )
        except ContextReaderError as exc:
            return _error(str(exc))

        return _ok([_entry_to_dict(entry) for entry in entries])


async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    service = _ContextService()
    name = params.name
    arguments = params.arguments or {}

    if name == "get_context_status":
        return service.get_status()
    if name == "get_context_entry":
        return service.get_entry(arguments)
    if name == "search_context":
        return service.search(arguments)

    return _error(f"unknown tool: {name}")


server = Server(
    "thelab-context",
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync() -> None:
    import asyncio

    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
