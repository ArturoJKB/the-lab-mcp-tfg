"""Tests for the A2 worker agent and proposal store."""

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
    ApprovalRequiredError,
    ExperimentProposal,
    MockProvider,
    ProposalStore,
    ServerConnection,
    WorkerAgent,
)
from thelab.run.batch import BatchRunner


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


def test_proposal_store_save_and_load(tmp_path: Path):
    store = ProposalStore(proposals_dir=tmp_path)
    proposal = ExperimentProposal(
        proposal_id="prop-test-1",
        goal="classify iris",
        dataset="data/fixtures/iris.csv",
        target="species",
        model_grid=["logistic_regression"],
        seeds=[42],
        task_type="classification",
        rationale="test",
    )
    path = store.save(proposal)
    assert path.exists()

    loaded = store.load("prop-test-1")
    assert loaded.proposal_id == "prop-test-1"
    assert loaded.model_grid == ["logistic_regression"]


def test_proposal_store_approve_and_reject(tmp_path: Path):
    store = ProposalStore(proposals_dir=tmp_path)
    proposal = ExperimentProposal(
        proposal_id="prop-test-2",
        goal="classify iris",
        dataset="data/fixtures/iris.csv",
        target="species",
        model_grid=["logistic_regression"],
        seeds=[42],
        task_type="classification",
    )
    store.save(proposal)

    store.approve("prop-test-2", principal="human")
    assert store.is_approved("prop-test-2")

    store.reject("prop-test-2", principal="auditor", reason="baseline test")
    assert store.is_rejected("prop-test-2")


def test_proposal_store_batch_config_translation(tmp_path: Path):
    store = ProposalStore(proposals_dir=tmp_path)
    proposal = ExperimentProposal(
        proposal_id="prop-test-3",
        goal="classify iris",
        dataset="data/fixtures/iris.csv",
        target="species",
        model_grid=["logistic_regression", "random_forest"],
        seeds=[42, 43],
        task_type="classification",
    )
    store.save(proposal)
    batch_path = store.write_batch_config("prop-test-3")

    entries = BatchRunner(workspace_root=tmp_path).load_config(batch_path)
    assert len(entries) == 4
    models = {e.model for e in entries}
    assert models == {"logistic_regression", "random_forest"}
    seeds = {e.seed for e in entries}
    assert seeds == {42, 43}


def test_worker_creates_proposal_with_mock_provider(tmp_path: Path):
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

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    proposals_dir = tmp_path / "proposals"

    async def check(sessions: dict[str, ClientSession]):
        provider = MockProvider([
            json.dumps({
                "dataset": "iris.csv",
                "target": "species",
                "model_grid": ["logistic_regression"],
                "seeds": [42],
                "task_type": "classification",
                "rationale": "mock rationale",
            })
        ])
        worker = WorkerAgent(
            provider=provider,
            servers=[
                ServerConnection(name="eda", session=sessions["eda"]),
                ServerConnection(name="workspace", session=sessions["workspace"]),
            ],
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        proposal = await worker.propose(
            goal="classify iris",
            dataset="iris.csv",
            target="species",
        )
        assert proposal.model_grid == ["logistic_regression"]
        assert proposal.seeds == [42]
        assert proposals_dir.joinpath(f"{proposal.proposal_id}.json").is_file()

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_worker_fallback_when_provider_returns_no_json(tmp_path: Path):
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

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    proposals_dir = tmp_path / "proposals"

    async def check(sessions: dict[str, ClientSession]):
        provider = MockProvider(["not valid json"])
        worker = WorkerAgent(
            provider=provider,
            servers=[
                ServerConnection(name="eda", session=sessions["eda"]),
                ServerConnection(name="workspace", session=sessions["workspace"]),
            ],
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        proposal = await worker.propose(
            goal="classify iris",
            dataset="iris.csv",
            target="species",
        )
        assert proposal.dataset == "iris.csv"
        assert proposal.target == "species"
        assert proposal.model_grid
        assert proposal.seeds
        assert proposals_dir.joinpath(f"{proposal.proposal_id}.json").is_file()

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_worker_approval_gate_on_disallowed_tool(tmp_path: Path):
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
    )
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    proposals_dir = tmp_path / "proposals"

    async def check(sessions: dict[str, ClientSession]):
        # The worker may call the provider directly before delegating to the
        # harness, so the script needs a tool-call turn for both stages.
        provider = MockProvider([
            {"tool_calls": [{"tool": "delete_proposal", "arguments": {"proposal_id": "x"}}]},
            {"tool_calls": [{"tool": "delete_proposal", "arguments": {"proposal_id": "x"}}]},
        ])
        worker = WorkerAgent(
            provider=provider,
            servers=[ServerConnection(name="workspace", session=sessions["workspace"])],
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        with pytest.raises(ApprovalRequiredError) as exc_info:
            await worker.propose(goal="test", dataset="iris.csv", target="species")
        assert exc_info.value.tool == "delete_proposal"

    asyncio.run(_with_servers({
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_worker_cites_prior_runs(tmp_path: Path):
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

    from thelab.run.runner import run_model

    run_model(
        dataset=csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )

    runs_root = tmp_path / "runs"
    proposals_dir = tmp_path / "proposals"

    async def check(sessions: dict[str, ClientSession]):
        provider = MockProvider(["not json"])
        worker = WorkerAgent(
            provider=provider,
            servers=[
                ServerConnection(name="eda", session=sessions["eda"]),
                ServerConnection(name="workspace", session=sessions["workspace"]),
            ],
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        proposal = await worker.propose(
            goal="classify iris",
            dataset="iris.csv",
            target="species",
        )
        assert proposal.prior_runs
        assert proposal.prior_runs[0]["model"] == "logistic_regression"
        assert "prior runs on this dataset" in proposal.rationale.lower()

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_worker_hyperparameter_grid_in_batch_config(tmp_path: Path):
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

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    proposals_dir = tmp_path / "proposals"

    async def check(sessions: dict[str, ClientSession]):
        provider = MockProvider([
            json.dumps({
                "dataset": "iris.csv",
                "target": "species",
                "model_grid": ["logistic_regression"],
                "seeds": [42],
                "hyperparameter_grid": {"C": [0.1, 1.0]},
                "task_type": "classification",
            })
        ])
        worker = WorkerAgent(
            provider=provider,
            servers=[
                ServerConnection(name="eda", session=sessions["eda"]),
                ServerConnection(name="workspace", session=sessions["workspace"]),
            ],
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        proposal = await worker.propose(
            goal="classify iris",
            dataset="iris.csv",
            target="species",
        )
        assert proposal.hyperparameter_grid == {"C": [0.1, 1.0]}
        batch_path = ProposalStore(proposals_dir).write_batch_config(proposal.proposal_id)
        entries = BatchRunner(workspace_root=tmp_path).load_config(batch_path)
        assert len(entries) == 2
        assert entries[0].hyperparameters == {"C": 0.1}
        assert entries[1].hyperparameters == {"C": 1.0}

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_worker_filters_unsupported_models_from_provider_json(tmp_path: Path):
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
    )
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    proposals_dir = tmp_path / "proposals"

    async def check(sessions: dict[str, ClientSession]):
        provider = MockProvider([
            json.dumps({
                "dataset": "iris.csv",
                "target": "species",
                "model_grid": ["logistic_regression", "not_a_real_model"],
                "seeds": [42],
                "task_type": "classification",
            })
        ])
        worker = WorkerAgent(
            provider=provider,
            servers=[
                ServerConnection(name="eda", session=sessions["eda"]),
                ServerConnection(name="workspace", session=sessions["workspace"]),
            ],
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        proposal = await worker.propose(
            goal="classify iris",
            dataset="iris.csv",
            target="species",
        )
        assert proposal.model_grid == ["logistic_regression"]

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))
