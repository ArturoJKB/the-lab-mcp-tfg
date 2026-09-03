"""Repro tests for the full-app audit findings (scratch/app_audit/FINDINGS.md)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.agents import MockProvider, WorkerAgent
from thelab.agents.worker import ExperimentProposal, ProposalStore
from thelab.ide.experiment import ExperimentState
from thelab.ide.jobs import reset_job_manager
from thelab.model_service.app import app
from thelab.run.batch import BatchResult

IRIS_ROWS = [
    "sepal_length,sepal_width,petal_length,petal_width,species",
    *[
        f"{sl},{sw},{pl},{pw},{sp}"
        for sp, samples in {
            "setosa": [(5.1, 3.5, 1.4, 0.2), (4.9, 3.0, 1.4, 0.2), (4.7, 3.2, 1.3, 0.2),
                       (5.0, 3.6, 1.4, 0.2), (4.6, 3.1, 1.5, 0.2)],
            "versicolor": [(7.0, 3.2, 4.7, 1.4), (6.4, 3.2, 4.5, 1.5), (6.9, 3.1, 4.9, 1.5),
                           (5.5, 2.3, 4.0, 1.3), (6.5, 2.8, 4.6, 1.5)],
            "virginica": [(6.3, 3.3, 6.0, 2.5), (5.8, 2.7, 5.1, 1.9), (7.1, 3.0, 5.9, 2.1),
                          (6.3, 2.9, 5.6, 1.8), (6.5, 3.0, 5.8, 2.2)],
        }.items()
        for sl, sw, pl, pw in samples
    ],
]


@pytest.fixture
def audit_env(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    jobs = tmp_path / "jobs"
    experiments = tmp_path / "experiments"
    for d in (uploads, fixtures, runs, proposals, jobs, experiments):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_JOBS_DIR", str(jobs))
    monkeypatch.setenv("THELAB_EXPERIMENTS_DIR", str(experiments))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    reset_job_manager()
    (fixtures / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    (uploads / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    return tmp_path, uploads, fixtures, runs, proposals


@pytest.fixture
def client(audit_env):
    """Context-managed TestClient: one persistent portal loop so background
    jobs survive across requests (plain TestClient tears down the loop after
    every request, orphaning job tasks mid-flight)."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# BUG 1a — model-keyed hyperparameter grids are rejected, not laundered
# ---------------------------------------------------------------------------


def test_model_keyed_grid_rejected_by_contract():
    with pytest.raises(Exception, match="model-keyed"):
        ExperimentProposal(
            proposal_id="p1",
            goal="g",
            dataset="uploads/iris.csv",
            target="species",
            model_grid=["logistic_regression", "random_forest"],
            seeds=[42],
            hyperparameter_grid={
                "logistic_regression": [{"C": 1.0, "max_iter": 100}],
                "random_forest": [{"n_estimators": 50}],
            },
        )


def test_worker_falls_back_on_model_keyed_grid(audit_env):
    """A live LLM emitting the audit's schema-A grid degrades to the working
    deterministic proposal instead of producing zero trained models."""
    tmp_path, uploads, fixtures, runs, proposals = audit_env
    schema_a = json.dumps(
        {
            "goal": "classify iris",
            "dataset": "uploads/iris.csv",
            "target": "species",
            "model_grid": ["logistic_regression", "random_forest"],
            "seeds": [42],
            "hyperparameter_grid": {
                "logistic_regression": [{"C": [1.0, 10.0]}],
                "random_forest": [{"n_estimators": [50]}],
            },
            "rationale": "llm pick",
        }
    )
    worker = WorkerAgent(
        provider=MockProvider([schema_a]),
        servers=[],
        proposals_dir=proposals,
        runs_root=runs,
    )
    proposal = asyncio.run(
        worker.propose(goal="classify iris", dataset="uploads/iris.csv", target="species")
    )
    # Deterministic fallback: a param-keyed (possibly empty) grid, valid schema.
    for model_key in proposal.hyperparameter_grid:
        assert model_key not in {"logistic_regression", "random_forest"}
    # And the batch config it produces trains without constructor errors.
    store = ProposalStore(proposals)
    store.approve(proposal.proposal_id, principal="test")
    batch_path = store.write_batch_config(proposal.proposal_id)
    entries = json.loads(batch_path.read_text(encoding="utf-8"))
    for entry in entries:
        for param in (entry.get("hyperparameters") or {}):
            assert param not in {"logistic_regression", "random_forest"}


# ---------------------------------------------------------------------------
# BUG 1b — all-failing batch is a FAILED experiment, not a green one
# ---------------------------------------------------------------------------


def _wait_job(client: TestClient, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/jobs/{job_id}").json()["data"]
        if data["status"] in {"completed", "failed", "cancelled"}:
            return data
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish")


def test_all_failed_batch_fails_the_experiment(client, audit_env, monkeypatch):
    """The orchestrator flow: every candidate fails -> experiment FAILED."""
    from thelab.run.batch import BatchRunner

    tmp_path, uploads, fixtures, runs, proposals = audit_env

    def _all_fail(self, entries, **kwargs):
        return [
            BatchResult(entry=e, run_id=None, status="failed", error="simulated constructor failure")
            for e in entries
        ]

    monkeypatch.setattr(BatchRunner, "run", _all_fail)
    response = client.post(
        "/experiment/run",
        json={
            "goal": "audit all-fail",
            "dataset_id": "fixtures/iris.csv",
            "target": "species",
            "provider": "mock",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    _wait_job(client, data["job_id"])
    final = client.get(f"/experiment/{data['experiment_id']}/status").json()["data"]
    assert final["state"] == ExperimentState.FAILED.value, final
    assert "failed" in (final.get("error") or "").lower(), final
    assert not final.get("best_run_id")


# ---------------------------------------------------------------------------
# BUG 2 — fixtures experiments work and deterministic failures don't blame providers
# ---------------------------------------------------------------------------


def test_fixture_dataset_experiment_completes(client):
    response = client.post(
        "/experiment/run",
        json={
            "goal": "Predict iris from the fixture",
            "dataset_id": "fixtures/iris.csv",
            "target": "species",
            "provider": "mock",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    job = _wait_job(client, data["job_id"])
    assert job["status"] == "completed", job.get("error")
    final = client.get(f"/experiment/{data['experiment_id']}/status").json()["data"]
    assert final["state"] == "completed"
    fe = final["sub_agent_results"]["FeatureEngineer"]
    assert fe["clean_metadata"].get("skipped") is True


# ---------------------------------------------------------------------------
# BUG 3 — SSE survives Path objects in the terminal result event
# ---------------------------------------------------------------------------


def test_job_events_stream_survives_result_paths(client):
    response = client.post(
        "/jobs",
        json={
            "type": "train",
            "payload": {
                "dataset_id": "fixtures/iris.csv",
                "target": "species",
                "model": "logistic_regression",
            },
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["data"]["job_id"]
    _wait_job(client, job_id)

    # Re-open the stream: the replay includes the result event carrying
    # run_dir (a PosixPath) — the old code crashed here.
    with client.stream("GET", f"/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        lines = list(stream.iter_lines())
    payloads = [json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: ")]
    levels = [p.get("level") for p in payloads]
    assert "done" in levels, levels
    result_events = [p for p in payloads if p.get("data", {}).get("result")]
    assert result_events, "result event must be delivered"


# ---------------------------------------------------------------------------
# BUG 4 — approval principal references the real experiment id
# ---------------------------------------------------------------------------


def test_approval_principal_uses_store_experiment_id(client, audit_env):
    tmp_path, uploads, fixtures, runs, proposals = audit_env
    response = client.post(
        "/experiment/run",
        json={
            "goal": "Predict iris",
            "dataset_id": "fixtures/iris.csv",
            "target": "species",
            "provider": "mock",
        },
    )
    data = response.json()["data"]
    experiment_id = data["experiment_id"]
    _wait_job(client, data["job_id"])
    approvals = list(proposals.glob("*.approved.json"))
    assert approvals
    matched = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in approvals
        if f"experiment:{experiment_id}" in json.loads(p.read_text(encoding="utf-8")).get("principal", "")
    ]
    assert matched, f"no approval principal references {experiment_id}"


# ---------------------------------------------------------------------------
# BUG 5 — registry predict no longer triggers the sklearn feature-name warning
# ---------------------------------------------------------------------------


def test_predict_has_no_feature_name_warning(client):
    import warnings

    response = client.post(
        "/jobs",
        json={
            "type": "train",
            "payload": {
                "dataset_id": "fixtures/iris.csv",
                "target": "species",
                "model": "logistic_regression",
            },
        },
    )
    job = _wait_job(client, response.json()["data"]["job_id"])
    run_id = (job.get("result") or {}).get("run_id")
    assert run_id
    # Predict through the HTTP service (same inference path as the registry).
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        result = client.post("/predict", json={"run_id": run_id, "features": [[5.1, 3.5, 1.4, 0.2]]})
    assert result.status_code == 200, result.text
    assert result.json()["data"]["predictions"], result.text
    feature_name_warnings = [
        str(r.message) for r in records if "feature names" in str(r.message)
    ]
    assert not feature_name_warnings, feature_name_warnings


# ---------------------------------------------------------------------------
# Audit F2/F3 — per-model hyperparameter filtering + grid caps
# ---------------------------------------------------------------------------


def test_shared_grid_params_filtered_per_model(audit_env):
    """F2: a shared grid with foreign params is filtered per estimator, so
    every batch entry constructs cleanly (live LLM failure mode)."""
    tmp_path, uploads, fixtures, runs, proposals = audit_env
    proposal = ExperimentProposal(
        proposal_id="prop-f2",
        goal="audit",
        dataset="uploads/iris.csv",
        target="species",
        model_grid=["logistic_regression", "random_forest"],
        seeds=[42],
        hyperparameter_grid={"C": [1.0], "n_estimators": [50]},
    )
    store = ProposalStore(proposals)
    store.save(proposal)
    store.approve("prop-f2", principal="test")
    batch_path = store.write_batch_config("prop-f2")
    entries = json.loads(batch_path.read_text(encoding="utf-8"))
    by_model = {e["model"]: e for e in entries}
    assert by_model["logistic_regression"]["hyperparameters"] == {"C": 1.0}
    assert by_model["random_forest"]["hyperparameters"] == {"n_estimators": 50}
    notes = json.loads((proposals / "prop-f2.batch.notes.json").read_text(encoding="utf-8"))
    assert "C" in notes["per_model_filter"]["random_forest"]["dropped_params"]
    assert "n_estimators" in notes["per_model_filter"]["logistic_regression"]["dropped_params"]


def test_grid_caps_reject_explosions():
    """F3: proposal validators bound models/seeds/hp product."""
    base = {"goal": "g", "dataset": "uploads/iris.csv", "target": "species"}
    with pytest.raises(Exception, match="model_grid too large"):
        ExperimentProposal(
            proposal_id="p",
            model_grid=["logistic_regression", "random_forest", "sgd_classifier",
                        "hist_gradient_boosting", "svc"],
            seeds=[42],
            **base,
        )
    with pytest.raises(Exception, match="too many seeds"):
        ExperimentProposal(
            proposal_id="p",
            model_grid=["logistic_regression"],
            seeds=[42, 43, 44, 45],
            **base,
        )
    with pytest.raises(Exception, match="combination count too large"):
        ExperimentProposal(
            proposal_id="p",
            model_grid=["logistic_regression"],
            seeds=[42],
            hyperparameter_grid={"C": [0.1, 1.0, 10.0, 100.0, 1000.0]},
            **base,
        )
