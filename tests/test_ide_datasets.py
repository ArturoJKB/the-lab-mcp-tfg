"""Tests for Phase 1 dataset upload and discovery endpoints."""

from io import BytesIO
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


def _csv_file(name: str, content: str) -> tuple[BytesIO, str]:
    return BytesIO(content.encode("utf-8")), name


def test_upload_valid_csv(client: TestClient, dataset_dirs):
    uploads, _ = dataset_dirs
    data, filename = _csv_file(
        "iris.csv",
        "sepal_length,sepal_width,species\n5.1,3.5,setosa\n4.9,3.0,setosa\n",
    )

    response = client.post("/datasets/upload", files={"file": (filename, data, "text/csv")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["dataset_id"] == "uploads/iris.csv"
    assert payload["data"]["filename"] == "iris.csv"
    assert payload["data"]["rows"] == 2
    assert payload["data"]["columns"] == 3
    assert (uploads / "iris.csv").is_file()


def test_upload_rejects_missing_file(client: TestClient, dataset_dirs):
    response = client.post("/datasets/upload")
    assert response.status_code == 422


def test_upload_rejects_unsafe_filename(client: TestClient, dataset_dirs):
    data, filename = _csv_file("../etc/passwd.csv", "a,b\n1,2\n")
    response = client.post("/datasets/upload", files={"file": (filename, data, "text/csv")})
    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"].lower()


def test_upload_rejects_non_csv_extension(client: TestClient, dataset_dirs):
    data, filename = _csv_file("report.txt", "a,b\n1,2\n")
    response = client.post("/datasets/upload", files={"file": (filename, data, "text/plain")})
    assert response.status_code == 400


def test_upload_rejects_empty_csv(client: TestClient, dataset_dirs):
    data, filename = _csv_file("empty.csv", "")
    response = client.post("/datasets/upload", files={"file": (filename, data, "text/csv")})
    assert response.status_code == 400


def test_upload_rejects_csv_with_no_rows(client: TestClient, dataset_dirs):
    data, filename = _csv_file("no_rows.csv", "a,b\n")
    response = client.post("/datasets/upload", files={"file": (filename, data, "text/csv")})
    assert response.status_code == 400


def test_upload_rejects_oversized_file(client: TestClient, dataset_dirs, monkeypatch):
    monkeypatch.setenv("THELAB_MAX_UPLOAD_BYTES", "20")
    content = "a,b\n" + "\n".join(f"{i},{i}" for i in range(100))
    data, filename = _csv_file("big.csv", content)
    response = client.post("/datasets/upload", files={"file": (filename, data, "text/csv")})
    assert response.status_code == 400
    assert "maximum size" in response.json()["detail"].lower()


def test_upload_avoids_name_collision(client: TestClient, dataset_dirs):
    uploads, _ = dataset_dirs
    content = "a,b\n1,2\n"
    for _ in range(2):
        data, filename = _csv_file("same.csv", content)
        response = client.post("/datasets/upload", files={"file": (filename, data, "text/csv")})
        assert response.status_code == 200

    assert (uploads / "same.csv").is_file()
    assert (uploads / "same_1.csv").is_file()


def test_list_datasets_includes_uploads_and_fixtures(client: TestClient, dataset_dirs):
    uploads, fixtures = dataset_dirs
    (uploads / "uploaded.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    (fixtures / "fixture.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    response = client.get("/datasets")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    ids = {d["dataset_id"] for d in payload["data"]}
    assert "uploads/uploaded.csv" in ids
    assert "fixtures/fixture.csv" in ids


def test_list_datasets_has_no_absolute_paths(client: TestClient, dataset_dirs):
    uploads, _ = dataset_dirs
    (uploads / "uploaded.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    response = client.get("/datasets")
    payload = response.json()
    for d in payload["data"]:
        assert not Path(d["dataset_id"]).is_absolute()
        assert "/" not in d["dataset_id"] or d["dataset_id"].count("/") == 1
