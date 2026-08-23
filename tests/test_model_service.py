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


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_models_returns_approved_models(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get("/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["data"]) == 1
    assert payload["data"][0]["run_id"] == run_id


def test_predict_returns_predictions(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={
            "run_id": run_id,
            "features": [
                {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["run_id"] == run_id
    assert len(payload["data"]["predictions"]) == 1


def test_predict_accepts_single_feature_dict(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={
            "run_id": run_id,
            "features": {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["data"]["predictions"]) == 1


def test_predict_accepts_single_feature_row(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={"run_id": run_id, "features": [5.1, 3.5, 1.4, 0.2]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["data"]["predictions"]) == 1


def test_predict_single_dict_matches_list_of_dicts(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    record = {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
    single = client.post("/predict", json={"run_id": run_id, "features": record})
    wrapped = client.post("/predict", json={"run_id": run_id, "features": [record]})
    assert single.status_code == wrapped.status_code == 200
    assert single.json()["data"]["predictions"] == wrapped.json()["data"]["predictions"]


def test_predict_rejects_unknown_run(client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))
    (tmp_path / "runs").mkdir()

    response = client.post(
        "/predict",
        json={"run_id": "does-not-exist", "features": [[5.1, 3.5, 1.4, 0.2]]},
    )
    assert response.status_code == 404


def test_predict_rejects_rejected_run(client: TestClient, tmp_path: Path, monkeypatch):
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

    response = client.post(
        "/predict",
        json={"run_id": result["run_id"], "features": [[5.1, 3.5, 1.4, 0.2]]},
    )
    assert response.status_code == 400


def test_predict_rejects_missing_feature_column(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={
            "run_id": run_id,
            "features": [{"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4}],
        },
    )
    assert response.status_code == 422
    assert "missing feature column" in response.json()["detail"].lower()


def test_predict_rejects_non_numeric_feature(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={
            "run_id": run_id,
            "features": [
                {"sepal_length": "x", "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
            ],
        },
    )
    assert response.status_code == 422
    assert "not numeric" in response.json()["detail"].lower()


def test_predict_rejects_non_finite_feature(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={
            "run_id": run_id,
            "features": [
                {"sepal_length": "inf", "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
            ],
        },
    )
    assert response.status_code == 422
    assert "not finite" in response.json()["detail"].lower()


def test_predict_rejects_wrong_row_length(client: TestClient, tmp_path: Path, monkeypatch):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.post(
        "/predict",
        json={"run_id": run_id, "features": [[5.1, 3.5, 1.4]]},
    )
    assert response.status_code == 422
    assert "length" in response.json()["detail"].lower()
