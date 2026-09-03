"""Local stdio MCP server for append-only context writes.

Tools:
- append_session_summary(event)

Validates the full canonical ``/log`` JSONL schema, applies server-side
redaction, and appends to ``THELAB_CONTEXT_LOG_SOURCE`` (default:
``.thelab/local-logs/agent-events.jsonl``). The read-only ``context_mcp``
server is intentionally untouched; indexing still happens through
``thelab context index``.

No tool accepts a client filesystem-path argument.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from thelab.contracts import EventType

from ..context.privacy import normalize_log_privacy
from ..context.redaction import redact

DEFAULT_LOG_SOURCE = Path(".thelab") / "local-logs" / "agent-events.jsonl"

# Defensive size limits for the incoming event payload.
_MAX_EVENT_BYTES = 64 * 1024
_MAX_SUMMARY_LEN = 4000


def _get_log_source_path() -> Path:
    """Return the context log source path from the environment or default."""
    env_path = os.environ.get("THELAB_CONTEXT_LOG_SOURCE")
    if env_path:
        return Path(env_path)
    return DEFAULT_LOG_SOURCE


def validate_event(event: Any) -> tuple[dict[str, Any], str | None]:
    """Validate a ``/log`` event and return (normalized_event, error_message).

    Required fields:
    - event_id: non-empty string
    - timestamp: timezone-aware ISO-8601 string
    - event_type: valid EventType string
    - outcome: dict with non-empty string ``summary``
    """
    if not isinstance(event, dict):
        return {}, "event must be a JSON object"

    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        return {}, "event_id is required and must be a non-empty string"

    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        return {}, "timestamp is required and must be an ISO-8601 string"
    try:
        parsed_ts = datetime.fromisoformat(timestamp)
    except ValueError:
        return {}, "timestamp is not a valid ISO-8601 datetime"
    if parsed_ts.tzinfo is None:
        return {}, "timestamp must be timezone-aware"

    event_type_value = event.get("event_type")
    if not isinstance(event_type_value, str):
        return {}, "event_type is required and must be a string"
    try:
        EventType(event_type_value)
    except ValueError:
        return {}, f"unsupported event_type: {event_type_value}"

    outcome = event.get("outcome")
    if not isinstance(outcome, dict):
        return {}, "outcome is required and must be an object"
    summary = outcome.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return {}, "outcome.summary is required and must be a non-empty string"

    # Apply server-side redaction to the summary.
    redacted_summary = redact(summary)
    normalized = dict(event)
    normalized["outcome"] = {**outcome, "summary": redacted_summary}

    # Map privacy object to canonical privacy level.
    privacy = event.get("privacy")
    privacy_level = normalize_log_privacy(privacy)
    normalized["privacy_level"] = privacy_level.value

    return normalized, None


def append_event(event: dict[str, Any]) -> Path:
    """Append a normalized event to the log source file.

    Returns the path written to.
    """
    log_path = _get_log_source_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, default=str) + "\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return log_path


TOOLS = [
    types.Tool(
        name="append_session_summary",
        description="Append a validated, redacted /log session summary to the local context log.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "event": {
                    "type": "object",
                    "description": "Canonical /log event object",
                }
            },
            "required": ["event"],
        },
    ),
]


def _ok(data: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": True, "data": data}))]
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": False, "error": message}))]
    )


async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    arguments = params.arguments or {}

    if name != "append_session_summary":
        return _error(f"unknown tool: {name}")

    event = arguments.get("event")
    if not isinstance(event, dict):
        return _error("event is required and must be a JSON object")

    raw_bytes = json.dumps(event).encode("utf-8")
    if len(raw_bytes) > _MAX_EVENT_BYTES:
        return _error(f"event payload exceeds {_MAX_EVENT_BYTES} bytes")

    normalized, error = validate_event(event)
    if error:
        return _error(error)

    summary = normalized.get("outcome", {}).get("summary", "")
    if len(summary) > _MAX_SUMMARY_LEN:
        return _error(f"outcome.summary exceeds {_MAX_SUMMARY_LEN} characters")

    log_path = append_event(normalized)
    return _ok({
        "event_id": normalized.get("event_id"),
        "log_path": str(log_path),
        "redacted": summary != event.get("outcome", {}).get("summary", ""),
    })


server = Server(
    "thelab-context-write",
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
