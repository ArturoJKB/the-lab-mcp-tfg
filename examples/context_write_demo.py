"""Demo: append a session summary via the context writer MCP server.

Usage:
    .venv/bin/python examples/context_write_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


event = {
    "schema_version": "1.0",
    "event_id": "demo_session_001",
    "timestamp": "2026-08-24T12:00:00+00:00",
    "event_type": "agent_session_summary",
    "project": "the-lab-mcp-tfg",
    "context": {"slice": "L2", "run_id": None},
    "outcome": {"status": "completed", "summary": "Context writer MCP demo completed."},
    "learning": {"topics": ["MCP", "context", "redaction"]},
    "evidence": {"artifacts": [], "source_refs": []},
    "privacy": {"level": "internal"},
}


async def main() -> int:
    log_source = repo_root / ".thelab" / "local-logs" / "agent-events.jsonl"
    log_source.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["THELAB_CONTEXT_LOG_SOURCE"] = str(log_source)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.context_write_mcp"],
        cwd=str(repo_root),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Tools: {[t.name for t in tools.tools]}")

            result = await session.call_tool("append_session_summary", {"event": event})
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            print(json.dumps(json.loads(text), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
