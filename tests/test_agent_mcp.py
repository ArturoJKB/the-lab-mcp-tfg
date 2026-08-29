"""Integration tests for the agent orchestration MCP server (P2 Phase 6)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "orchestrate_experiment",
    "spawn_subagent",
    "run_deterministic_skill",
    "run_training_job",
    "get_job_status",
    "log_agent_activity",
}

IRIS_ROWS = [
    "sepal_length,sepal_width,species",
    *[
        f"{sl},{sw},{sp}"
        for sp, samples in {
            "setosa": [(5.1, 3.5), (4.9, 3.0), (4.7, 3.2), (4.6, 3.1), (5.0, 3.6)],
            "versicolor": [(7.0, 3.2), (6.4, 3.2), (6.9, 3.1), (5.5, 2.3), (6.5, 2.8)],
            "virginica": [(6.3, 3.3), (5.8, 2.7), (7.1, 3.0), (6.3, 2.9), (6.5, 3.0)],
        }.items()
        for sl, sw in samples
    ],
]


@pytest.fixture
def agent_env(tmp_path: Path, monkeypatch):
    """Workspace layout for the agent MCP server subprocess."""
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    jobs = tmp_path / "jobs"
    for d in (uploads, fixtures, runs, proposals, jobs):
        d.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "THELAB_UPLOADS_DIR": str(uploads),
            "THELAB_FIXTURES_DIR": str(fixtures),
            "THELAB_RUNS_ROOT": str(runs),
            "THELAB_PROPOSALS_DIR": str(proposals),
            "THELAB_WORKSPACE_ROOT": str(tmp_path),
            "THELAB_JOBS_DIR": str(jobs),
            "THELAB_CONTEXT_LOG_SOURCE": str(tmp_path / "logs" / "agent-events.jsonl"),
        }
    )
    monkeypatch.delenv("THELAB_CONTEXT_DB", raising=False)
    (uploads / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    return env, tmp_path


async def _with_agent_server(env: dict, coro):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.agent_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


async def _call_tool(session: ClientSession, name: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(name, arguments or {})
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return json.loads(text)


def test_agent_mcp_discovers_tools(agent_env):
    env, _ = agent_env

    async def check(session: ClientSession):
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert names == EXPECTED_TOOLS

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_run_deterministic_skill_eda(agent_env):
    env, _ = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "run_deterministic_skill",
            {"skill": "eda", "dataset_id": "uploads/iris.csv", "target": "species"},
        )
        assert result["ok"] is True
        assert result["data"]["skill"] == "eda"
        assert result["data"]["data"]["rows"] == 15

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_run_deterministic_skill_cleaning(agent_env):
    env, tmp_path = agent_env
    (tmp_path / "uploads" / "messy.csv").write_text(
        "num,cat,target\n1,red,x\n2,,y\n3,red,x\n",
        encoding="utf-8",
    )

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "run_deterministic_skill",
            {"skill": "cleaning", "dataset_id": "uploads/messy.csv", "target": "target"},
        )
        assert result["ok"] is True
        metadata = result["data"]["metadata"]
        assert metadata["dataset_id"] == "uploads/messy_cleaned.csv"
        assert (tmp_path / "uploads" / "messy_cleaned.csv").is_file()

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_rejects_unknown_skill(agent_env):
    env, _ = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "run_deterministic_skill",
            {"skill": "nope", "dataset_id": "uploads/iris.csv", "target": "species"},
        )
        assert result["ok"] is False

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_spawn_subagent(agent_env):
    env, _ = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "spawn_subagent",
            {
                "agent_type": "EDAAnalyst",
                "goal": "Check class balance",
                "dataset_id": "uploads/iris.csv",
                "target": "species",
            },
        )
        assert result["ok"] is True
        assert result["data"]["agent_type"] == "EDAAnalyst"
        assert result["data"]["proposal"]["proposal_id"]

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_spawn_subagent_rejects_unknown_type(agent_env):
    env, _ = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "spawn_subagent",
            {
                "agent_type": "Hacker",
                "goal": "g",
                "dataset_id": "uploads/iris.csv",
                "target": "species",
            },
        )
        assert result["ok"] is False

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_orchestrate_experiment(agent_env):
    env, tmp_path = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "orchestrate_experiment",
            {
                "goal": "Predict the iris species",
                "dataset_id": "uploads/iris.csv",
                "target": "species",
            },
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["status"] in {"completed", "partial"}
        assert data["proposal"]["proposal_id"]
        assert data["results"], "expected batch results"
        # Approved proposal recorded with the agent principal.
        approved = list((tmp_path / "proposals").glob("*.approved.json"))
        assert approved

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_get_job_status_unknown(agent_env):
    env, _ = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_job_status", {"job_id": "missing"})
        assert result["ok"] is False

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_run_training_job_lifecycle(agent_env):
    """run_training_job + get_job_status must round-trip over stdio.

    Regression: pipeline prints used to corrupt the JSON-RPC transport, and
    job results containing Path objects crashed get_job_status serialization.
    """
    env, tmp_path = agent_env
    (tmp_path / "jobs").mkdir(exist_ok=True)
    (tmp_path / "fixtures" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")

    async def check(session: ClientSession):
        result = await _call_tool(session, "run_training_job", {
            "dataset_id": "fixtures/iris.csv", "target": "species",
            "model": "logistic_regression", "seed": 42,
        })
        assert result["ok"] is True
        job_id = result["data"]["job_id"]

        status = {"status": "pending"}
        for _ in range(150):
            status = await _call_tool(session, "get_job_status", {"job_id": job_id})
            assert status["ok"] is True, status
            if status["data"]["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.1)
        assert status["data"]["status"] == "completed"
        run_info = status["data"].get("result") or {}
        assert run_info.get("run_id")

    asyncio.run(_with_agent_server(env, check))


def test_agent_mcp_log_agent_activity(agent_env):
    env, tmp_path = agent_env

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "log_agent_activity",
            {
                "event_type": "subagent_spawned",
                "summary": "spawned EDAAnalyst with token sk-secret123",
                "run_id": "run-test",
                "tags": ["phase6"],
            },
        )
        assert result["ok"] is True
        log_source = tmp_path / "logs" / "agent-events.jsonl"
        assert log_source.is_file()
        line = json.loads(log_source.read_text(encoding="utf-8").splitlines()[0])
        assert line["event_type"] == "agent_session_summary"
        assert "run-test" in line.get("run_id", "") or line.get("run_id") == "run-test"
        # Secret redaction applied before storage.
        assert "sk-secret123" not in json.dumps(line)

    asyncio.run(_with_agent_server(env, check))
