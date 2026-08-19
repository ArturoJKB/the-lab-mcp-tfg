import hashlib
from pathlib import Path

import pytest

from thelab.workspace import artifact_path, ensure_run_dir, hash_bytes, hash_file


@pytest.fixture
def fixture_path() -> Path:
    return Path("data/fixtures/iris.csv").resolve()


def test_hash_bytes_known():
    assert hash_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()


def test_hash_file(fixture_path: Path):
    expected = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert hash_file(fixture_path) == expected


def test_run_dir_creation(tmp_path: Path):
    run_path = ensure_run_dir(tmp_path, "run-xyz")
    assert run_path.exists()
    assert run_path == tmp_path / "runs" / "run-xyz"


def test_artifact_path_within_run(tmp_path: Path):
    path = artifact_path(tmp_path, "run-1", "model.joblib")
    assert path == tmp_path / "runs" / "run-1" / "model.joblib"


def test_artifact_path_rejects_escape(tmp_path: Path):
    with pytest.raises(ValueError):
        artifact_path(tmp_path, "run-1", "../../etc/passwd")


def test_fixture_exists_and_hash_stable(fixture_path: Path):
    assert fixture_path.exists()
    first = hash_file(fixture_path)
    second = hash_file(fixture_path)
    assert first == second
    assert len(first) == 64
