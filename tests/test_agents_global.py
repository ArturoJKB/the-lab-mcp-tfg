"""Tests for A3 global agents (Researcher and Diagnosis)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.agents import (
    DiagnosisAgent,
    MockProvider,
    ProposalStore,
    Researcher,
    ServerConnection,
    WorkerAgent,
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


def test_researcher_answer_cites_existing_run(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    researcher = Researcher(runs_root=tmp_path / "runs")
    result = researcher.answer("What is the test accuracy?", run_id=run_id)
    assert run_id in result["answer"]
    assert result["citations"]
    assert any(run_id in key for key in result["citations"])


def test_researcher_drops_uncitable_claim(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    metrics_path = tmp_path / "runs" / run_id / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    accuracy = metrics["test_accuracy"]

    researcher = Researcher(runs_root=tmp_path / "runs")
    draft = (
        f"Run {run_id} has test_accuracy {accuracy}. "
        f"Run {run_id} has test_accuracy 9.999."
    )
    result = researcher.answer("What is the accuracy?", run_id=run_id, draft=draft)
    # Only the first sentence is citable; the second should be dropped.
    assert str(accuracy) in result["answer"]
    assert "9.999" not in result["answer"]


def test_researcher_missing_run(tmp_path: Path):
    researcher = Researcher(runs_root=tmp_path / "runs")
    result = researcher.answer("What happened?", run_id="run-does-not-exist")
    assert "No workspace evidence" in result["answer"]
    assert result["citations"] == {}


def test_diagnosis_agent_approves_recoverable_goal(tmp_path: Path):
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
                "rationale": "baseline",
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
        store = ProposalStore(proposals_dir)
        diagnosis = DiagnosisAgent(worker=worker, proposal_store=store, principal="diagnosis_agent")
        result = await diagnosis.handle(
            dataset="iris.csv",
            target="species",
            error_summary="prior run had low accuracy",
            model_grid=["logistic_regression"],
            seeds=[42],
        )
        assert result["status"] == "approved"
        assert store.is_approved(result["proposal_id"])

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_diagnosis_agent_rejects_unrecoverable_error(tmp_path: Path):
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
                "model_grid": ["logistic_regression"],
                "seeds": [42],
                "task_type": "classification",
                "rationale": "baseline",
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
        store = ProposalStore(proposals_dir)
        diagnosis = DiagnosisAgent(worker=worker, proposal_store=store, principal="diagnosis_agent")
        result = await diagnosis.handle(
            dataset="iris.csv",
            target="species",
            error_summary="target column not found in dataset",
            model_grid=["logistic_regression"],
            seeds=[42],
        )
        assert result["status"] == "rejected"
        assert store.is_rejected(result["proposal_id"])

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_diagnosis_approves_recoverable_validation_report(tmp_path: Path):
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
                "rationale": "baseline",
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
        store = ProposalStore(proposals_dir)
        diagnosis = DiagnosisAgent(worker=worker, proposal_store=store, principal="diagnosis_agent")
        result = await diagnosis.handle(
            dataset="iris.csv",
            target="species",
            validation_report={
                "valid": True,
                "checks": [
                    {"check": "class_imbalance", "passed": False, "message": "minority class < 5%"},
                ],
            },
            model_grid=["logistic_regression"],
            seeds=[42],
        )
        assert result["status"] == "approved"
        assert store.is_approved(result["proposal_id"])

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_diagnosis_rejects_unrecoverable_validation_report(tmp_path: Path):
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
                "model_grid": ["logistic_regression"],
                "seeds": [42],
                "task_type": "classification",
                "rationale": "baseline",
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
        store = ProposalStore(proposals_dir)
        diagnosis = DiagnosisAgent(worker=worker, proposal_store=store, principal="diagnosis_agent")
        result = await diagnosis.handle(
            dataset="iris.csv",
            target="species",
            validation_report={
                "valid": False,
                "checks": [
                    {"check": "target_column_exists", "passed": False, "message": "target missing"},
                ],
            },
            model_grid=["logistic_regression"],
            seeds=[42],
        )
        assert result["status"] == "rejected"
        assert store.is_rejected(result["proposal_id"])

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))


def test_diagnosis_adds_class_weight_for_imbalanced_data(tmp_path: Path):
    # Highly imbalanced dataset.
    rows = (["1.0,2.0,majority"] * 100) + (["3.0,4.0,minority"] * 2)
    csv = tmp_path / "imbalanced.csv"
    csv.write_text("a,b,target\n" + "\n".join(rows))
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
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
        store = ProposalStore(proposals_dir)
        diagnosis = DiagnosisAgent(
            worker=worker,
            proposal_store=store,
            principal="diagnosis_agent",
            runs_root=runs_root,
        )
        result = await diagnosis.handle(
            dataset="imbalanced.csv",
            target="target",
            model_grid=["logistic_regression"],
            seeds=[42],
        )
        assert result["status"] == "approved"
        proposal = store.load(result["proposal_id"])
        assert "class_weight" in proposal.hyperparameter_grid

    asyncio.run(_with_servers({
        "eda": "thelab.mcp.eda_mcp",
        "workspace": "thelab.mcp.workspace_mcp",
    }, runs_root, check))
