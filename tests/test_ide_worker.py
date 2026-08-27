"""Tests for Phase 2 worker proposal endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def worker_dirs(tmp_path: Path, monkeypatch):
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
    return uploads, fixtures, runs, proposals


def test_worker_proposal_creates_proposal(client: TestClient, worker_dirs):
    uploads, _, _, proposals = worker_dirs
    (uploads / "iris.csv").write_text(
        "sepal_length,sepal_width,species\n5.1,3.5,setosa\n4.9,3.0,setosa\n6.3,3.3,virginica\n",
        encoding="utf-8",
    )

    response = client.post(
        "/agent/worker",
        json={"dataset_id": "uploads/iris.csv", "target": "species", "goal": "classify species"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["dataset"] == "uploads/iris.csv"
    assert data["target"] == "species"
    assert data["goal"] == "classify species"
    assert data["proposal_id"]
    assert data["model_grid"]
    assert data["seeds"]
    assert (proposals / f"{data['proposal_id']}.json").is_file()


def test_worker_proposal_requires_fields(client: TestClient, worker_dirs):
    response = client.post("/agent/worker", json={"dataset_id": "uploads/iris.csv", "target": "species"})
    assert response.status_code == 400


def test_worker_proposal_rejects_unknown_dataset(client: TestClient, worker_dirs):
    response = client.post(
        "/agent/worker",
        json={"dataset_id": "uploads/missing.csv", "target": "species", "goal": "classify"},
    )
    assert response.status_code == 404
