"""Tests for experiment endpoints: run, status, SSE events, feedback, results."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.ide.jobs import reset_job_manager
from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def experiment_dirs(tmp_path: Path, monkeypatch):
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
    return uploads, experiments


@pytest.fixture
def iris_csv(experiment_dirs):
    uploads, _ = experiment_dirs
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
    (uploads / "iris.csv").write_text("\n".join(rows), encoding="utf-8")


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()["data"]
        if data["status"] in {"completed", "failed"}:
            return data
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in time")


def _start_experiment(client: TestClient) -> dict:
    response = client.post(
        "/experiment/run",
        json={
            "goal": "Predict the iris species",
            "dataset_id": "uploads/iris.csv",
            "target": "species",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_experiment_run_completes(client: TestClient, experiment_dirs, iris_csv):
    _, experiments = experiment_dirs
    data = _start_experiment(client)
    assert data["experiment_id"].startswith("exp-")
    assert data["job_id"]
    assert data["state"] == "pending"
    assert (experiments / f"{data['experiment_id']}.json").is_file()

    job = _wait_for_job(client, data["job_id"])
    assert job["status"] == "completed"

    status = client.get(f"/experiment/{data['experiment_id']}/status")
    assert status.status_code == 200
    status_data = status.json()["data"]
    assert status_data["state"] == "completed"
    assert status_data["sub_agent_results"]["EDAAnalyst"]
    assert status_data["sub_agent_results"]["ModelSelector"]["recommendation"]["best_model"]


def test_experiment_results_include_best_run(client: TestClient, experiment_dirs, iris_csv):
    data = _start_experiment(client)
    _wait_for_job(client, data["job_id"])

    results = client.get(f"/experiment/{data['experiment_id']}/results")
    assert results.status_code == 200
    results_data = results.json()["data"]
    assert results_data["best_run_id"]
    assert results_data["best_metrics"]
    assert results_data["training_results"]


def test_experiment_events_stream(client: TestClient, experiment_dirs, iris_csv):
    data = _start_experiment(client)
    _wait_for_job(client, data["job_id"])

    with client.stream("GET", f"/experiment/{data['experiment_id']}/events") as stream:
        lines = []
        for line in stream.iter_lines():
            lines.append(line)
            if "done" in line:
                break
    data_lines = [line for line in lines if line.startswith("data: ")]
    assert data_lines
    events = [json.loads(line[len("data: ") :]) for line in data_lines]
    stages = {e.get("data", {}).get("stage") for e in events}
    assert "planning" in stages


def test_experiment_feedback_triggers_iteration(client: TestClient, experiment_dirs, iris_csv):
    data = _start_experiment(client)
    _wait_for_job(client, data["job_id"])

    response = client.post(
        f"/experiment/{data['experiment_id']}/feedback",
        json={"feedback": "Focus on logistic_regression only"},
    )
    assert response.status_code == 200
    feedback_data = response.json()["data"]
    assert feedback_data["job_id"] != data["job_id"]

    _wait_for_job(client, feedback_data["job_id"])
    status = client.get(f"/experiment/{data['experiment_id']}/status")
    status_data = status.json()["data"]
    assert status_data["state"] == "completed"
    assert status_data["feedback"] == "Focus on logistic_regression only"
    assert data["job_id"] in status_data["plan"]["previous_job_ids"]


def test_experiment_run_requires_fields(client: TestClient, experiment_dirs):
    response = client.post("/experiment/run", json={"goal": "g"})
    assert response.status_code == 400


def test_experiment_run_unknown_dataset(client: TestClient, experiment_dirs):
    response = client.post(
        "/experiment/run",
        json={"goal": "g", "dataset_id": "uploads/missing.csv", "target": "t"},
    )
    assert response.status_code == 404


def test_experiment_status_unknown_id(client: TestClient, experiment_dirs):
    assert client.get("/experiment/does-not-exist/status").status_code == 404


def test_experiment_results_unknown_id(client: TestClient, experiment_dirs):
    assert client.get("/experiment/does-not-exist/results").status_code == 404


def test_experiment_feedback_requires_body(client: TestClient, experiment_dirs):
    response = client.post("/experiment/does-not-exist/feedback", json={"feedback": ""})
    assert response.status_code == 400


def test_list_experiments(client: TestClient, experiment_dirs, iris_csv):
    data = _start_experiment(client)
    response = client.get("/experiments")
    assert response.status_code == 200
    experiments = response.json()["data"]
    assert any(e["experiment_id"] == data["experiment_id"] for e in experiments)
