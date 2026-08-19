"""Tests for the Slice 5 minimal UI and read-only run/artifact APIs."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


def test_root_serves_dashboard_html(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert 'id="panel-status"' in body
    assert 'id="panel-models"' in body
    assert 'id="panel-metrics"' in body
    assert 'id="panel-artifacts"' in body
    assert 'id="panel-predict"' in body
    assert 'src="/static/app.js"' in body
    assert 'href="/static/styles.css"' in body


def test_static_assets_reachable(client: TestClient):
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert "css" in css.headers["content-type"]


def test_get_run_summary_for_approved_run(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["run_id"] == run_id
    assert data["final_status"] == "completed"
    assert data["validation_status"] == "approved"
    assert data["model"] == "logistic_regression"
    assert data["target"] == "species"
    assert set(data["feature_columns"]) == {
        "sepal_length",
        "sepal_width",
        "petal_length",
        "petal_width",
    }
    assert "test_accuracy" in data["metrics"]
    assert "test_f1_macro" in data["metrics"]
    assert "run_dir" not in data
    assert "path" not in data


def test_get_run_rejects_unknown_run(client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))
    (tmp_path / "runs").mkdir()

    response = client.get("/runs/does-not-exist")
    assert response.status_code == 404


def test_get_run_rejects_rejected_run(client: TestClient, tmp_path: Path, monkeypatch):
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
    )
    result = run_model(
        dataset=csv,
        target="missing",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get(f"/runs/{result['run_id']}")
    assert response.status_code == 400


def test_list_artifacts_includes_allowlisted_files_only(
    client: TestClient, tmp_path: Path, monkeypatch
):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get(f"/runs/{run_id}/artifacts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    names = {item["name"] for item in payload["data"]}
    assert "metrics.json" in names
    assert "model_card.md" in names
    assert "manifest.json" in names
    assert "model.joblib" not in names


def test_get_artifact_json_and_text(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    metrics_response = client.get(f"/runs/{run_id}/artifacts/metrics.json")
    assert metrics_response.status_code == 200
    payload = metrics_response.json()
    assert payload["ok"] is True
    assert "test_accuracy" in payload["data"]

    card_response = client.get(f"/runs/{run_id}/artifacts/model_card.md")
    assert card_response.status_code == 200
    payload = card_response.json()
    assert payload["ok"] is True
    assert isinstance(payload["data"], str)


def test_artifact_path_traversal_rejected(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    # Literal ".." is normalized away by the HTTP client/server path resolution,
    # so we test the equivalent encoded form and other unsafe names.
    for bad_name in ["%2e%2e", "a/b.json", "/etc/passwd", ".hidden"]:
        response = client.get(f"/runs/{run_id}/artifacts/{bad_name}")
        assert response.status_code in (400, 404), f"{bad_name} returned {response.status_code}"


def test_non_allowlisted_artifact_rejected(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get(f"/runs/{run_id}/artifacts/model.joblib")
    assert response.status_code == 400

    response = client.get(f"/runs/{run_id}/artifacts/random.txt")
    assert response.status_code == 400
