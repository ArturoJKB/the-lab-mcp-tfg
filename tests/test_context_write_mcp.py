"""Tests for the L2 context writer MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.context.indexer import index_source_file
from thelab.context.repository import ContextRepository


async def _with_write_server(log_source: Path, coro):
    env = dict(os.environ)
    env["THELAB_CONTEXT_LOG_SOURCE"] = str(log_source)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.context_write_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


async def _call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return json.loads(text)


@pytest.fixture
def valid_event() -> dict:
    return {
        "schema_version": "1.0",
        "event_id": "demo_001",
        "timestamp": "2026-08-24T12:00:00+00:00",
        "event_type": "agent_session_summary",
        "project": "the-lab-mcp-tfg",
        "context": {"slice": "L2", "run_id": None},
        "outcome": {"status": "completed", "summary": "Session completed successfully."},
        "learning": {"topics": ["context", "MCP"]},
        "evidence": {"artifacts": [], "source_refs": []},
        "privacy": {"level": "internal"},
    }


def test_write_mcp_appends_valid_event(tmp_path: Path, valid_event: dict):
    log_source = tmp_path / "events.jsonl"
    db_path = tmp_path / "context.db"

    async def check(session: ClientSession):
        result = await _call_tool(session, "append_session_summary", {"event": valid_event})
        assert result["ok"] is True
        assert result["data"]["event_id"] == "demo_001"

        # Verify the event was appended and is indexable.
        repo = ContextRepository(db_path)
        index_source_file(log_source, repo)
        entry = repo.get("demo_001")
        assert entry is not None
        assert entry.event_type.value == "agent_session_summary"
        assert "Session completed successfully" in entry.redacted_summary

    asyncio.run(_with_write_server(log_source, check))


def test_write_mcp_redacts_secrets_before_storage(tmp_path: Path, valid_event: dict):
    log_source = tmp_path / "events.jsonl"

    async def check(session: ClientSession):
        event = dict(valid_event)
        event["event_id"] = "demo_002"
        event["outcome"]["summary"] = "Used token sk-1234567890abcdef"
        result = await _call_tool(session, "append_session_summary", {"event": event})
        assert result["ok"] is True
        assert result["data"]["redacted"] is True

        lines = log_source.read_text(encoding="utf-8").strip().splitlines()
        last_line = json.loads(lines[-1])
        assert "[REDACTED]" in last_line["outcome"]["summary"]
        assert "sk-1234567890abcdef" not in last_line["outcome"]["summary"]

    asyncio.run(_with_write_server(log_source, check))


def test_write_mcp_rejects_missing_event_id(tmp_path: Path, valid_event: dict):
    log_source = tmp_path / "events.jsonl"

    async def check(session: ClientSession):
        event = dict(valid_event)
        del event["event_id"]
        result = await _call_tool(session, "append_session_summary", {"event": event})
        assert result["ok"] is False
        assert "event_id" in result["error"]

    asyncio.run(_with_write_server(log_source, check))


def test_write_mcp_rejects_invalid_event_type(tmp_path: Path, valid_event: dict):
    log_source = tmp_path / "events.jsonl"

    async def check(session: ClientSession):
        event = dict(valid_event)
        event["event_type"] = "nonexistent_type"
        result = await _call_tool(session, "append_session_summary", {"event": event})
        assert result["ok"] is False
        assert "event_type" in result["error"]

    asyncio.run(_with_write_server(log_source, check))


def test_write_mcp_rejects_naive_timestamp(tmp_path: Path, valid_event: dict):
    log_source = tmp_path / "events.jsonl"

    async def check(session: ClientSession):
        event = dict(valid_event)
        event["timestamp"] = "2026-08-24T12:00:00"
        result = await _call_tool(session, "append_session_summary", {"event": event})
        assert result["ok"] is False
        assert "timezone" in result["error"]

    asyncio.run(_with_write_server(log_source, check))


def test_write_mcp_does_not_modify_read_only_context_server(tmp_path: Path, valid_event: dict):
    """Appending via the write server must not alter the existing read-only context_mcp behavior."""
    log_source = tmp_path / "events.jsonl"
    db_path = tmp_path / "context.db"

    async def check(session: ClientSession):
        result = await _call_tool(session, "append_session_summary", {"event": valid_event})
        assert result["ok"] is True

    asyncio.run(_with_write_server(log_source, check))

    # Index into a fresh DB and verify the entry is readable.
    repo = ContextRepository(db_path)
    index_source_file(log_source, repo)
    assert repo.get("demo_001") is not None
