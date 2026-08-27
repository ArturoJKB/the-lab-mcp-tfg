"""Tests for Phase 2 proposal approve/reject/run endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def action_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    for d in (uploads, runs, proposals):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    return uploads, runs, proposals


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


def _create_proposal(client: TestClient, uploads: Path) -> str:
    _write_iris(uploads)
    response = client.post(
        "/agent/worker",
        json={
            "dataset_id": "uploads/iris.csv",
            "target": "species",
            "goal": "classify species",
            "model_grid": ["logistic_regression"],
            "seeds": [42],
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["proposal_id"]


def test_approve_proposal_writes_approval_record(client: TestClient, action_dirs):
    uploads, _, proposals = action_dirs
    proposal_id = _create_proposal(client, uploads)

    response = client.post(f"/proposals/{proposal_id}/approve")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"
    assert (proposals / f"{proposal_id}.approved.json").is_file()


def test_reject_proposal_writes_rejection_record(client: TestClient, action_dirs):
    uploads, _, proposals = action_dirs
    proposal_id = _create_proposal(client, uploads)

    response = client.post(f"/proposals/{proposal_id}/reject", json={"reason": "not useful"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "rejected"
    assert (proposals / f"{proposal_id}.rejected.json").is_file()


def test_run_proposal_requires_approval(client: TestClient, action_dirs):
    uploads, _, _ = action_dirs
    proposal_id = _create_proposal(client, uploads)

    response = client.post(f"/proposals/{proposal_id}/run")
    assert response.status_code == 400


def test_run_proposal_executes_batch(client: TestClient, action_dirs):
    uploads, runs, proposals = action_dirs
    proposal_id = _create_proposal(client, uploads)

    client.post(f"/proposals/{proposal_id}/approve")
    response = client.post(f"/proposals/{proposal_id}/run")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["proposal_id"] == proposal_id
    assert data["total"] >= 1
    assert data["completed"] >= 1
    assert (proposals / f"{proposal_id}.batch.json").is_file()
    assert any(runs.iterdir())


def test_actions_reject_unknown_proposal(client: TestClient, action_dirs):
    response = client.post("/proposals/does-not-exist/approve")
    assert response.status_code == 404
