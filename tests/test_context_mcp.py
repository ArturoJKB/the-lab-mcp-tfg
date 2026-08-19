import asyncio
import hashlib
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.context.indexer import index_source_file
from thelab.context.repository import ContextRepository


def _index_demo_db(db_path: Path) -> None:
    """Create a small indexed context database for MCP tests."""
    source = db_path.parent / "agent-events.jsonl"
    source.write_text(
        json.dumps(
            {
                "event_id": "evt-public",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Run started",
                "privacy_level": "public",
                "timestamp": "2026-08-09T12:00:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-internal",
                "event_type": "validation",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Validation passed",
                "privacy_level": "internal",
                "timestamp": "2026-08-09T12:01:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-restricted",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Restricted event",
                "privacy_level": "restricted",
                "timestamp": "2026-08-09T12:02:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-secret",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Secret event",
                "privacy_level": "secret",
                "timestamp": "2026-08-09T12:03:00+00:00",
            }
        )
        + "\n"
    )
    repo = ContextRepository(db_path)
    index_source_file(source, repo)


async def _call_tool(session: ClientSession, name: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(name, arguments or {})
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return json.loads(text)


async def _with_context_server(db_path: Path, coro):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.context_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={"THELAB_CONTEXT_DB": str(db_path), **dict(**__import__("os").environ)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


def test_context_server_exposes_only_read_only_tools(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {"get_context_status", "get_context_entry", "search_context"}
        return names

    asyncio.run(_with_context_server(db, check))


def test_context_status_returns_logical_fields(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_context_status")
        assert result["ok"] is True
        status = result["data"]
        assert status["indexed"] is True
        assert status["entry_count"] == 2
        assert "last_indexed_at" in status
        assert "fts5_available" in status
        assert "db_path" not in status
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_search_returns_entries(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "search_context", {"query": "Validation", "limit": 10})
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["event_id"] == "evt-internal"
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_search_filters_by_run_id_and_tag(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "search_context",
            {"run_id": "run-abc", "tags": ["demo"], "limit": 10},
        )
        assert result["ok"] is True
        assert len(result["data"]) == 2  # public + internal, restricted excluded
        event_ids = {e["event_id"] for e in result["data"]}
        assert event_ids == {"evt-public", "evt-internal"}
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_get_entry_returns_single_entry(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_context_entry", {"event_id": "evt-public"})
        assert result["ok"] is True
        assert result["data"]["event_id"] == "evt-public"
        assert result["data"]["privacy_level"] == "public"
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_get_restricted_entry_is_excluded_by_default(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_context_entry", {"event_id": "evt-restricted"})
        assert result["ok"] is False
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_search_malformed_query_returns_empty(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "search_context", {"query": '"unmatched'})
        assert result["ok"] is True
        assert result["data"] == []
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_queries_do_not_modify_database(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    before = hashlib.sha256(db.read_bytes()).hexdigest()

    async def check(session: ClientSession):
        await _call_tool(session, "get_context_status")
        await _call_tool(session, "search_context", {"query": "Run"})
        await _call_tool(session, "get_context_entry", {"event_id": "evt-public"})
        return None

    asyncio.run(_with_context_server(db, check))

    after = hashlib.sha256(db.read_bytes()).hexdigest()
    assert before == after


def test_context_server_reports_uninitialized_index(tmp_path: Path):
    missing_db = tmp_path / "missing" / "context.db"

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_context_status")
        assert result["ok"] is True
        status = result["data"]
        assert status["indexed"] is False
        assert status["entry_count"] == 0

        search = await _call_tool(session, "search_context", {"query": "Run"})
        assert search["ok"] is True
        assert search["data"] == []
        return result

    asyncio.run(_with_context_server(missing_db, check))
    assert not missing_db.exists()
    assert not missing_db.parent.exists()


def test_context_mcp_public_dto_excludes_internal_fields(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_context_entry", {"event_id": "evt-public"})
        assert result["ok"] is True
        entry = result["data"]
        assert "event_id" in entry
        assert "content_hash" not in entry
        assert "indexed_at" not in entry
        assert "privacy_level" in entry

        search = await _call_tool(session, "search_context", {"query": "Run", "limit": 10})
        assert result["ok"] is True
        for e in search["data"]:
            assert "content_hash" not in e
            assert "indexed_at" not in e
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_mcp_schema_constraints(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        tools = await session.list_tools()
        by_name = {t.name: t for t in tools.tools}

        status_schema = by_name["get_context_status"].input_schema
        assert status_schema.get("additionalProperties") is False

        entry_schema = by_name["get_context_entry"].input_schema
        assert entry_schema.get("additionalProperties") is False
        assert entry_schema["properties"]["event_id"].get("minLength") == 1

        search_schema = by_name["search_context"].input_schema
        assert search_schema.get("additionalProperties") is False
        assert search_schema["properties"]["query"].get("maxLength") == 200
        assert search_schema["properties"]["tags"].get("maxItems") == 10
        assert search_schema["properties"]["tags"]["items"].get("maxLength") == 64
        assert search_schema["properties"]["limit"].get("minimum") == 1
        assert search_schema["properties"]["limit"].get("maximum") == 1000
        return by_name

    asyncio.run(_with_context_server(db, check))


def test_context_search_invalid_limit_returns_error(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "search_context", {"limit": 0})
        assert result["ok"] is False
        result = await _call_tool(session, "search_context", {"limit": 1001})
        assert result["ok"] is False
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_search_invalid_timestamp_returns_error(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(
            session, "search_context", {"since": "not-an-iso-timestamp"}
        )
        assert result["ok"] is False
        return result

    asyncio.run(_with_context_server(db, check))


def test_context_get_entry_empty_event_id_rejected(tmp_path: Path):
    db = tmp_path / "context.db"
    _index_demo_db(db)

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_context_entry", {"event_id": ""})
        assert result["ok"] is False
        return result

    asyncio.run(_with_context_server(db, check))
