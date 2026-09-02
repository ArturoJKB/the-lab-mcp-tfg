"""Tests for Phase 3 background job manager and endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.ide.jobs import reset_job_manager
from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def job_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    jobs = tmp_path / "jobs"
    for d in (uploads, fixtures, runs, proposals, jobs):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_JOBS_DIR", str(jobs))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    reset_job_manager()
    return uploads, fixtures, runs, proposals, jobs


def _write_iris(uploads: Path) -> None:
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


def test_submit_train_job(client: TestClient, job_dirs):
    uploads, _, _, _, jobs = job_dirs
    _write_iris(uploads)

    response = client.post(
        "/jobs",
        json={
            "type": "train",
            "payload": {
                "dataset_id": "uploads/iris.csv",
                "target": "species",
                "model": "logistic_regression",
                "seed": 42,
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["job_id"]
    assert data["status"] == "pending"
    assert (jobs / f"{data['job_id']}.json").is_file()


def test_job_status_lifecycle(client: TestClient, job_dirs):
    uploads, _, _, _, _ = job_dirs
    _write_iris(uploads)

    response = client.post(
        "/jobs",
        json={
            "type": "train",
            "payload": {
                "dataset_id": "uploads/iris.csv",
                "target": "species",
                "model": "logistic_regression",
                "seed": 42,
            },
        },
    )
    job_id = response.json()["data"]["job_id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    status_data = status_response.json()["data"]
    assert status_data["job_id"] == job_id
    assert status_data["job_type"] == "train"


def test_job_events_stream(client: TestClient, job_dirs):
    uploads, _, _, _, _ = job_dirs
    _write_iris(uploads)

    response = client.post(
        "/jobs",
        json={
            "type": "train",
            "payload": {
                "dataset_id": "uploads/iris.csv",
                "target": "species",
                "model": "logistic_regression",
                "seed": 42,
            },
        },
    )
    job_id = response.json()["data"]["job_id"]

    with client.stream("GET", f"/jobs/{job_id}/events") as stream:
        lines = []
        for line in stream.iter_lines():
            lines.append(line)
            if len(lines) >= 3:
                break
    assert any("data:" in line for line in lines)


def test_try_all_job_completes_with_progress(job_dirs):
    uploads, fixtures, _, _, _ = job_dirs
    _write_iris(uploads)
    (fixtures / "iris.csv").write_text((uploads / "iris.csv").read_text(encoding="utf-8"), encoding="utf-8")

    # A context-managed client keeps the event loop alive so the suspended
    # to_thread work can finish (see test_real_data_hardening).
    with TestClient(app) as client:
        _run_try_all_flow(client, uploads)


def _run_try_all_flow(client: TestClient, uploads: Path) -> None:
    import time

    response = client.post(
        "/jobs",
        json={
            "type": "try_all",
            "payload": {"dataset_id": "fixtures/iris.csv", "target": "species", "seed": 42},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]

    deadline = time.time() + 120
    payload = {}
    while time.time() < deadline:
        payload = client.get(f"/jobs/{job_id}").json()["data"]
        if payload["status"] in {"completed", "failed"}:
            break
        time.sleep(0.2)
    assert payload["status"] == "completed", payload.get("error")

    result = payload["result"]
    models = {r["model"]: r["status"] for r in result["results"]}
    assert models["logistic_regression"] == "completed"
    assert result["best"] is not None
    # Per-model progress events streamed
    model_events = [e for e in payload["events"] if e["message"].startswith("model ")]
    assert len(model_events) >= 1


def test_reject_unknown_job_type(client: TestClient, job_dirs):
    response = client.post("/jobs", json={"type": "unknown", "payload": {}})
    assert response.status_code == 400


def test_reject_missing_job_payload(client: TestClient, job_dirs):
    response = client.post("/jobs", json={"type": "train"})
    assert response.status_code == 400


def test_unknown_job_returns_404(client: TestClient, job_dirs):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404
