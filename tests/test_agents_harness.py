"""Tests for L1 agent harness against real MCP servers."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.agents import (
    AgentHarness,
    ApprovalRequiredError,
    MockProvider,
    ServerConnection,
)
from thelab.run.runner import run_model


def _completed_iris_run(tmp_path: Path) -> str:
    """Create a small completed run and return its run_id."""
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
        "4.9,3.0,1.4,0.2,setosa\n"
        "4.7,3.2,1.3,0.2,setosa\n"
        "7.0,3.2,4.7,1.4,versicolor\n"
        "6.4,3.2,4.5,1.5,versicolor\n"
        "6.9,3.1,4.9,1.5,versicolor\n"
        "6.3,3.3,6.0,2.5,virginica\n"
        "5.8,2.7,5.1,1.9,virginica\n"
        "7.1,3.0,5.9,2.1,virginica\n"
        "7.6,3.0,6.6,2.1,virginica\n"
        "4.9,2.5,4.5,1.7,virginica\n"
    )
    result = run_model(
        dataset=csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    return result["run_id"]


async def _with_server(
    module: str,
    runs_root: Path,
    coro,
):
    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


async def _with_servers(
    modules: dict[str, str],
    runs_root: Path,
    coro,
):
    """Connect multiple MCP servers and pass a dict of named sessions."""
    from contextlib import AsyncExitStack

    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    sessions: dict[str, ClientSession] = {}
    async with AsyncExitStack() as stack:
        for name, module in modules.items():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", module],
                cwd=str(Path(__file__).resolve().parents[1]),
                env=env,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[name] = session
        return await coro(sessions)


def test_harness_discovers_tools_from_one_server(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    async def check(session: ClientSession):
        harness = AgentHarness(
            provider=MockProvider(["done"]),
            servers=[ServerConnection(name="model_registry", session=session)],
            runs_root=runs_root,
        )
        await harness._discover_tools()
        names = {t.name for t in harness._tools}
        assert names == {"list_models", "get_model_manifest", "get_model_card", "get_model_metrics", "predict"}
        assert harness._allowlist == names

    asyncio.run(_with_server("thelab.mcp.model_registry_mcp", runs_root, check))


def test_harness_executes_tool_call_and_returns_answer(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(sessions: dict[str, ClientSession]):
        harness = AgentHarness(
            provider=MockProvider([
                {"tool_calls": [{"tool": "get_model_manifest", "arguments": {"run_id": run_id}}]},
                f"Run {run_id} is completed.",
            ]),
            servers=[
                ServerConnection(name="model_registry", session=sessions["model_registry"]),
                ServerConnection(name="workspace", session=sessions["workspace"]),
            ],
            runs_root=runs_root,
        )
        result = await harness.run("describe the run")
        assert result["status"] == "success"
        assert run_id in result["answer"]

    asyncio.run(_with_servers({
        "model_registry": "thelab.mcp.model_registry_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_harness_grounds_answer_against_workspace(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        harness = AgentHarness(
            provider=MockProvider([
                f"Run {run_id} has test_accuracy 0.999.",
            ]),
            servers=[ServerConnection(name="workspace", session=session)],
            runs_root=runs_root,
        )
        result = await harness.run("what is the accuracy?")
        assert result["status"] == "refused"
        assert result["reason"] == "grounding_failure"
        assert run_id in result["message"]

    asyncio.run(_with_server("thelab.mcp.workspace_mcp", runs_root, check))


def test_harness_accepts_grounded_metric_claim(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"
    metrics_path = runs_root / run_id / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    accuracy = metrics["test_accuracy"]

    async def check(session: ClientSession):
        harness = AgentHarness(
            provider=MockProvider([
                f"Run {run_id} has test_accuracy {accuracy}.",
            ]),
            servers=[ServerConnection(name="workspace", session=session)],
            runs_root=runs_root,
        )
        result = await harness.run("what is the accuracy?")
        assert result["status"] == "success"

    asyncio.run(_with_server("thelab.mcp.workspace_mcp", runs_root, check))


def test_harness_approval_gate_persists_request_and_exits(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    async def check(session: ClientSession):
        harness = AgentHarness(
            provider=MockProvider([
                {"tool_calls": [{"tool": "delete_run", "arguments": {"run_id": "run-123"}}]},
            ]),
            servers=[ServerConnection(name="workspace", session=session)],
            runs_root=runs_root,
            session_id="test-approval",
        )
        with pytest.raises(ApprovalRequiredError) as exc_info:
            await harness.run("delete a run")
        assert exc_info.value.tool == "delete_run"
        assert exc_info.value.request_path.exists()
        payload = json.loads(exc_info.value.request_path.read_text())
        assert payload["tool"] == "delete_run"
        assert payload["session_id"] == "test-approval"

    asyncio.run(_with_server("thelab.mcp.workspace_mcp", runs_root, check))


def test_harness_bound_on_steps(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    async def check(session: ClientSession):
        harness = AgentHarness(
            provider=MockProvider([
                {"tool_calls": [{"tool": "list_runs", "arguments": {}}]},
            ] * 10),
            servers=[ServerConnection(name="workspace", session=session)],
            runs_root=runs_root,
            max_steps=3,
        )
        result = await harness.run("loop forever")
        assert result["status"] == "refused"
        assert result["reason"] == "max_steps_exceeded"

    asyncio.run(_with_server("thelab.mcp.workspace_mcp", runs_root, check))
