"""Tests for dataset cleaning endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thelab.model_service.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def cleaning_dirs(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    for d in (uploads, fixtures):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    return uploads, fixtures


def test_clean_dataset_drops_missing_target(client: TestClient, cleaning_dirs):
    uploads, _ = cleaning_dirs
    (uploads / "data.csv").write_text(
        "a,b,target\n1,2,x\n3,4,\n5,6,y\n",
        encoding="utf-8",
    )

    response = client.post("/datasets/uploads%2Fdata.csv/clean", json={"target": "target"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dataset_id"] == "uploads/data_cleaned_target.csv"
    assert data["rows"] == 2
    assert data["dropped_rows"] == 1
    assert (uploads / "data_cleaned_target.csv").is_file()


def test_clean_dataset_encodes_categoricals(client: TestClient, cleaning_dirs):
    uploads, _ = cleaning_dirs
    (uploads / "data.csv").write_text(
        "num,cat,target\n1,red,x\n2,blue,y\n3,red,x\n",
        encoding="utf-8",
    )

    response = client.post("/datasets/uploads%2Fdata.csv/clean", json={"target": "target"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["columns"] == 4  # num, cat_blue, cat_red, target


def test_clean_dataset_imputes_categorical_nan_before_encoding(client: TestClient, cleaning_dirs):
    """Categorical NaN must be imputed before one-hot encoding (P2 Phase 6 fix)."""
    uploads, _ = cleaning_dirs
    (uploads / "data.csv").write_text(
        "num,cat,target\n1,red,x\n2,blue,y\n3,,x\n",
        encoding="utf-8",
    )

    response = client.post("/datasets/uploads%2Fdata.csv/clean", json={"target": "target"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rows"] == 3
    assert data["columns"] == 4  # num, cat_blue, cat_red, target

    cleaned = (uploads / "data_cleaned_target.csv").read_text(encoding="utf-8")
    assert "cat_blue" in cleaned and "cat_red" in cleaned
    # No missing values may remain after cleaning.
    for line in cleaned.splitlines()[1:]:
        assert ",," not in line and not line.endswith(",")


def test_clean_dataset_drops_constant_columns(client: TestClient, cleaning_dirs):
    """Constant feature columns (e.g. IBM HR 'EmployeeCount') carry zero information."""
    uploads, _ = cleaning_dirs
    (uploads / "const.csv").write_text(
        "num,const,cat,target\n1,7,red,x\n2,7,blue,y\n3,7,red,x\n",
        encoding="utf-8",
    )

    response = client.post("/datasets/uploads%2Fconst.csv/clean", json={"target": "target"})
    assert response.status_code == 200
    data = response.json()["data"]
    # const (and its one-hot if any) is dropped; cat varies so it stays encoded.
    assert data["columns"] == 4  # num, cat_blue, cat_red, target
    cleaned_text = (uploads / "const_cleaned_target.csv").read_text(encoding="utf-8")
    assert "const" not in cleaned_text.splitlines()[0]
    assert any("constant columns" in a for a in data["cleaning_report"]["actions"])


def test_clean_rejects_recleaning_cleaned_dataset(client: TestClient, cleaning_dirs):
    uploads, _ = cleaning_dirs
    (uploads / "raw.csv").write_text("a,target\n1,x\n2,y\n", encoding="utf-8")
    first = client.post("/datasets/uploads%2Fraw.csv/clean", json={"target": "target"})
    assert first.status_code == 200

    second = client.post(
        "/datasets/uploads%2Fraw_cleaned_target.csv/clean", json={"target": "target"}
    )
    assert second.status_code == 400
    assert "already cleaned" in second.json()["detail"]


def test_clean_requires_target(client: TestClient, cleaning_dirs):
    response = client.post("/datasets/uploads%2Fdata.csv/clean", json={})
    assert response.status_code == 400


def test_clean_rejects_missing_dataset(client: TestClient, cleaning_dirs):
    response = client.post("/datasets/uploads%2Fmissing.csv/clean", json={"target": "target"})
    assert response.status_code == 404


def test_clean_rejects_fixture(client: TestClient, cleaning_dirs):
    _, fixtures = cleaning_dirs
    (fixtures / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    response = client.post("/datasets/fixtures%2Fdata.csv/clean", json={"target": "b"})
    assert response.status_code == 400
