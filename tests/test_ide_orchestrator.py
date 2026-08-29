"""Tests for the experiment orchestrator (P2 Phase 6)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from thelab.ide.orchestrator import ExperimentOrchestrator


@pytest.fixture
def orch_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    for d in (uploads, fixtures, runs, proposals):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    return uploads, runs, proposals


@pytest.fixture
def iris_csv(orch_dirs):
    uploads, _, _ = orch_dirs
    rows = [
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
    path = uploads / "iris.csv"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def _orchestrator() -> ExperimentOrchestrator:
    return ExperimentOrchestrator()


def test_run_eda_analysis_returns_context(orch_dirs, iris_csv):
    orchestrator = _orchestrator()
    result = asyncio.run(orchestrator.run_eda_analysis("uploads/iris.csv", "species", "goal"))
    assert result["eda_result"]
    assert isinstance(result["eda_context"], str)
    assert result["eda_context"]


def test_orchestrate_completes_and_trains(orch_dirs, iris_csv):
    uploads, runs, proposals = orch_dirs
    orchestrator = _orchestrator()
    result = asyncio.run(
        orchestrator.orchestrate(
            goal="Predict the species",
            dataset_id="uploads/iris.csv",
            target="species",
        )
    )
    assert result["status"] == "completed"
    assert result["experiment_id"].startswith("exp-")
    assert result["training_results"], "expected training entries"
    assert any(r["status"] == "completed" for r in result["training_results"])
    # Best model recommendation came from try-all.
    assert result["model_selection"]["recommendation"]["best_model"]
    # Approved proposal + batch config persisted.
    assert list(proposals.glob("*.approved.json"))
    # Training runs were persisted under the runs root.
    assert any(runs.iterdir())


def test_orchestrate_emits_stage_events(orch_dirs, iris_csv):
    orchestrator = _orchestrator()
    stages: list[str] = []

    def on_event(stage: str, message: str) -> None:
        stages.append(stage)
        assert message

    asyncio.run(
        orchestrator.orchestrate(
            goal="Predict the species",
            dataset_id="uploads/iris.csv",
            target="species",
            on_event=on_event,
        )
    )
    assert set(stages) >= {"planning", "cleaning", "training", "evaluating"}


def test_orchestrate_unknown_dataset_fails(orch_dirs):
    from thelab.ide.datasets import DatasetNotFoundError

    orchestrator = _orchestrator()
    with pytest.raises(DatasetNotFoundError):
        asyncio.run(
            orchestrator.orchestrate(
                goal="g",
                dataset_id="uploads/missing.csv",
                target="species",
            )
        )


def test_create_orchestrator_factory(orch_dirs):
    from thelab.ide.orchestrator import create_orchestrator

    orchestrator = create_orchestrator(
        runs_root=os.environ["THELAB_RUNS_ROOT"],
        proposals_dir=os.environ["THELAB_PROPOSALS_DIR"],
    )
    assert isinstance(orchestrator, ExperimentOrchestrator)
    assert orchestrator.proposals_dir == Path(os.environ["THELAB_PROPOSALS_DIR"])
