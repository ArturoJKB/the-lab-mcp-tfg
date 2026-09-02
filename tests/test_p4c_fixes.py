"""Tests for the P4.C feedback fixes: fast listing, fail-fast providers,
experiment failure states, provider status, and propose fallback."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.agents.chat import provider_status
from thelab.ide.experiment import ExperimentState
from thelab.ide.orchestrator import ExperimentOrchestrator
from thelab.model_service.app import app

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


def test_provider_status_reports_configuration():
    status = {p["name"]: p for p in provider_status()}
    assert status["mock"]["configured"] is True
    assert status["openrouter"]["configured"] == bool(__import__("os").environ.get("THELAB_LLM_API_KEY"))
    assert any("THELAB_LLM_API_KEY" in e for e in status["openrouter"]["env"])


def test_agent_providers_endpoint():
    client = TestClient(app)
    r = client.get("/agent/providers")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["data"]}
    assert {"mock", "ollama", "openrouter", "openai_compat"} <= names


def test_experiment_start_rejects_unsupported_provider(tmp_path: Path, monkeypatch):
    for d in ("uploads", "fixtures", "runs", "proposals", "jobs", "experiments"):
        (tmp_path / d).mkdir()
    (tmp_path / "uploads" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    for d in ("uploads", "fixtures", "runs", "proposals", "jobs", "experiments"):
        (tmp_path / d).mkdir(exist_ok=True)
    for key, val in {
        "THELAB_UPLOADS_DIR": tmp_path / "uploads",
        "THELAB_FIXTURES_DIR": tmp_path / "fixtures",
        "THELAB_RUNS_ROOT": tmp_path / "runs",
        "THELAB_PROPOSALS_DIR": tmp_path / "proposals",
        "THELAB_JOBS_DIR": tmp_path / "jobs",
        "THELAB_EXPERIMENTS_DIR": tmp_path / "experiments",
        "THELAB_WORKSPACE_ROOT": tmp_path,
    }.items():
        monkeypatch.setenv(key, str(val))

    client = TestClient(app)
    r = client.post(
        "/experiment/run",
        json={"goal": "g", "dataset_id": "uploads/iris.csv", "target": "species", "provider": "nope"},
    )
    assert r.status_code == 400


def test_experiment_fails_fast_on_unconfigured_provider(tmp_path: Path, monkeypatch):
    """An unconfigured live provider -> experiment marked failed, not stuck pending."""
    from thelab.ide.experiment_api import start_experiment
    from thelab.ide.jobs import reset_job_manager

    for d in ("uploads", "fixtures", "runs", "proposals", "jobs", "experiments"):
        (tmp_path / d).mkdir()
    (tmp_path / "uploads" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    for key, val in {
        "THELAB_UPLOADS_DIR": tmp_path / "uploads",
        "THELAB_FIXTURES_DIR": tmp_path / "fixtures",
        "THELAB_RUNS_ROOT": tmp_path / "runs",
        "THELAB_PROPOSALS_DIR": tmp_path / "proposals",
        "THELAB_JOBS_DIR": tmp_path / "jobs",
        "THELAB_EXPERIMENTS_DIR": tmp_path / "experiments",
        "THELAB_WORKSPACE_ROOT": tmp_path,
    }.items():
        monkeypatch.setenv(key, str(val))
    monkeypatch.delenv("THELAB_LLM_API_KEY", raising=False)
    reset_job_manager()

    async def flow():
        with pytest.raises(ValueError, match="openrouter"):
            await start_experiment("g", "uploads/iris.csv", "species", provider_name="openrouter")

    asyncio.run(flow())


def test_orchestrator_fails_loudly_when_provider_dies(tmp_path: Path, monkeypatch):
    """A provider that dies mid-orchestration fails the experiment loudly (no silent fallback)."""
    (tmp_path / "uploads").mkdir()
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "proposals").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "uploads" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))

    class DyingProvider:
        """Works for the first three interpretation calls, dies on propose."""

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools):  # noqa: ARG002
            self.calls += 1
            if self.calls > 3:
                raise ConnectionError("Ollama stopped responding")
            from thelab.agents.provider import AgentTurn

            return AgentTurn(text=f"interpretation {self.calls}")

    orchestrator = ExperimentOrchestrator(
        runs_root=tmp_path / "runs",
        proposals_dir=tmp_path / "proposals",
    )
    with pytest.raises(ConnectionError, match="Ollama stopped responding"):
        asyncio.run(
            orchestrator.orchestrate(
                goal="Predict species",
                dataset_id="uploads/iris.csv",
                target="species",
                provider=DyingProvider(),
            )
        )


def test_failed_experiment_marks_state(tmp_path: Path, monkeypatch):
    """An experiment whose orchestrate raises ends FAILED, not stuck pending."""
    from thelab.ide.experiment import ExperimentStore
    from thelab.ide.experiment_api import start_experiment

    for d in ("uploads", "fixtures", "runs", "proposals", "jobs", "experiments"):
        (tmp_path / d).mkdir()
    (tmp_path / "uploads" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    for key, val in {
        "THELAB_UPLOADS_DIR": tmp_path / "uploads",
        "THELAB_FIXTURES_DIR": tmp_path / "fixtures",
        "THELAB_RUNS_ROOT": tmp_path / "runs",
        "THELAB_PROPOSALS_DIR": tmp_path / "proposals",
        "THELAB_JOBS_DIR": tmp_path / "jobs",
        "THELAB_EXPERIMENTS_DIR": tmp_path / "experiments",
        "THELAB_WORKSPACE_ROOT": tmp_path,
    }.items():
        monkeypatch.setenv(key, str(val))

    import time

    started = asyncio.run(start_experiment("g", "uploads/iris.csv", "column_that_does_not_exist"))
    deadline = time.time() + 60
    from thelab.ide.jobs import get_job_manager

    async def wait():
        while True:
            job = await get_job_manager().get(started["job_id"])
            if job is not None and job.status in {"completed", "failed"}:
                return job
            await asyncio.sleep(0.2)
            if time.time() > deadline:
                raise AssertionError("job never finished")

    job = asyncio.run(wait())
    assert job.status == "failed"
    store = ExperimentStore()
    experiment = store.load(started["experiment_id"])
    assert experiment is not None and experiment.state == ExperimentState.FAILED
