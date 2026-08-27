"""Tests for Phase 1 EDA endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def dataset_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    uploads.mkdir()
    fixtures.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    return uploads, fixtures


def test_eda_returns_all_skills(client: TestClient, dataset_dirs):
    uploads, _ = dataset_dirs
    (uploads / "iris.csv").write_text(
        "sepal_length,sepal_width,species\n5.1,3.5,setosa\n4.9,3.0,setosa\n6.3,3.3,virginica\n",
        encoding="utf-8",
    )

    response = client.get("/eda/uploads%2Firis.csv")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["dataset_id"] == "uploads/iris.csv"
    assert data["rows"] == 3
    assert data["columns"] == 3
    assert "feature_types" in data
    assert "missing_profile" in data
    assert "class_balance" in data
    assert "correlation_hints" in data
    assert "outlier_scan" in data
    assert "leakage_suspects" in data


def test_eda_with_target_returns_class_balance(client: TestClient, dataset_dirs):
    uploads, _ = dataset_dirs
    (uploads / "iris.csv").write_text(
        "sepal_length,sepal_width,species\n5.1,3.5,setosa\n4.9,3.0,setosa\n6.3,3.3,virginica\n",
        encoding="utf-8",
    )

    response = client.get("/eda/uploads%2Firis.csv?target=species")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["class_balance"]["classes"]
    assert data["leakage_suspects"]


def test_eda_rejects_unknown_dataset(client: TestClient, dataset_dirs):
    response = client.get("/eda/uploads%2Fmissing.csv")
    assert response.status_code == 404


def test_eda_rejects_unsafe_dataset_id(client: TestClient, dataset_dirs):
    response = client.get("/eda/..%2Fetc%2Fpasswd")
    assert response.status_code == 404


def test_eda_rejects_invalid_target(client: TestClient, dataset_dirs):
    uploads, _ = dataset_dirs
    (uploads / "iris.csv").write_text(
        "sepal_length,sepal_width,species\n5.1,3.5,setosa\n4.9,3.0,setosa\n",
        encoding="utf-8",
    )

    response = client.get("/eda/uploads%2Firis.csv?target=missing")
    assert response.status_code == 400
    assert "target column" in response.json()["detail"].lower()
