"""Tests for Slice 6 read-only agent panels (HTTP API + UI hooks)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.context.indexer import index_source_file
from thelab.context.repository import ContextRepository
from thelab.model_service.app import app
from thelab.run.runner import run_model


@pytest.fixture
def client():
    return TestClient(app)


def _completed_iris_run(tmp_path: Path) -> str:
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


def _index_demo_context(db_path: Path) -> None:
    source = db_path.parent / "agent-events.jsonl"
    source.write_text(
        json.dumps(
            {
                "event_id": "evt-public",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Public event",
                "privacy_level": "public",
                "timestamp": "2026-08-09T12:00:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-internal",
                "event_type": "validation",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Internal event",
                "privacy_level": "internal",
                "timestamp": "2026-08-09T12:01:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-restricted",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Restricted event",
                "privacy_level": "restricted",
                "timestamp": "2026-08-09T12:02:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-secret",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["demo"],
                "redacted_summary": "Secret event",
                "privacy_level": "secret",
                "timestamp": "2026-08-09T12:03:00+00:00",
            }
        )
        + "\n"
    )
    repo = ContextRepository(db_path)
    index_source_file(source, repo)


def test_dashboard_html_contains_panel_hooks_and_banners(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'id="panel-coding"' in body
    assert 'id="panel-research"' in body
    assert 'id="panel-models"' in body
    assert "Read-only" in body
    assert "no autonomous writes" in body
    assert "Approval required before any modification or destructive action" in body
    assert "Grounded in local runs and context only" in body
    assert "No external RAG or generative model" in body


def test_agent_coding_overview_has_counts_no_absolute_paths(
    client: TestClient, tmp_path: Path, monkeypatch
):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get("/agent/coding/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["total_runs"] == 1
    assert data["approved_completed_runs"] == 1
    assert run_id in data["recent_run_ids"]
    assert "run_dir" not in data
    assert "path" not in data


def test_agent_coding_runs_exposes_basename_dataset(
    client: TestClient, tmp_path: Path, monkeypatch
):
    _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get("/agent/coding/runs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    runs = payload["data"]
    assert len(runs) == 1
    assert runs[0]["dataset"] == "iris.csv"
    assert runs[0]["final_status"] == "completed"
    assert runs[0]["validation_status"] == "approved"


def test_agent_coding_run_detail_returns_artifacts(
    client: TestClient, tmp_path: Path, monkeypatch
):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get(f"/agent/coding/runs/{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["run_id"] == run_id
    assert data["dataset"] == "iris.csv"
    assert set(data["feature_columns"]) == {
        "sepal_length",
        "sepal_width",
        "petal_length",
        "petal_width",
    }
    artifact_names = {a["name"] for a in data["artifacts"]}
    assert "manifest.json" in artifact_names
    assert "model.joblib" not in artifact_names


def test_agent_coding_run_rejects_bad_run_id(
    client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))
    (tmp_path / "runs").mkdir()

    response = client.get("/agent/coding/runs/../etc/passwd")
    assert response.status_code == 404

    response = client.get("/agent/coding/runs/.hidden")
    assert response.status_code == 404


def test_agent_research_context_status_no_db_path(
    client: TestClient, tmp_path: Path, monkeypatch
):
    db = tmp_path / "context.db"
    _index_demo_context(db)
    monkeypatch.setenv("THELAB_CONTEXT_DB", str(db))

    response = client.get("/agent/research/context/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["indexed"] is True
    assert data["entry_count"] == 2  # public + internal only
    assert "db_path" not in data


def test_agent_research_context_search_returns_public_dto_and_filters_privacy(
    client: TestClient, tmp_path: Path, monkeypatch
):
    db = tmp_path / "context.db"
    _index_demo_context(db)
    monkeypatch.setenv("THELAB_CONTEXT_DB", str(db))

    response = client.get("/agent/research/context/search?query=event&limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    entries = payload["data"]
    event_ids = {e["event_id"] for e in entries}
    assert event_ids == {"evt-public", "evt-internal"}
    for entry in entries:
        assert "content_hash" not in entry
        assert "indexed_at" not in entry
        assert "event_id" in entry


def test_agent_research_context_entry_returns_public_dto(
    client: TestClient, tmp_path: Path, monkeypatch
):
    db = tmp_path / "context.db"
    _index_demo_context(db)
    monkeypatch.setenv("THELAB_CONTEXT_DB", str(db))

    response = client.get("/agent/research/context/entries/evt-public")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    entry = payload["data"]
    assert entry["event_id"] == "evt-public"
    assert "content_hash" not in entry
    assert "indexed_at" not in entry

    response = client.get("/agent/research/context/entries/evt-restricted")
    assert response.status_code == 404
