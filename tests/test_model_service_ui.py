"""Tests for Slice U1 UI v2 dashboard endpoints and hooks."""

import json
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


def _write_benchmark_manifest(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "benchmarks" / "b1"
    manifest_dir.mkdir(parents=True)
    manifest_dir.joinpath("benchmark_manifest.json").write_text(
        json.dumps(
            {
                "benchmark_id": "b1",
                "providers": [
                    {
                        "provider": "test",
                        "model": "dummy",
                        "datasets": [
                            {
                                "domain": "medical",
                                "name": "iris",
                                "target": "species",
                                "task_type": "classification",
                                "deterministic_status": "completed",
                                "metrics": {
                                    "deterministic": {"test_accuracy": 0.95},
                                    "agent": {"test_accuracy": 0.94},
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_proposals(proposals_dir: Path) -> tuple[str, str, str]:
    proposals_dir.mkdir(parents=True, exist_ok=True)
    pending_id = "prop-pending-001"
    approved_id = "prop-approved-001"
    rejected_id = "prop-rejected-001"

    proposals_dir.joinpath(f"{pending_id}.json").write_text(
        json.dumps(
            {
                "proposal_id": pending_id,
                "goal": "Pending goal",
                "dataset": "data/fixtures/iris.csv",
                "target": "species",
                "model_grid": ["logistic_regression"],
                "seeds": [42],
                "rationale": "Pending rationale.",
            }
        ),
        encoding="utf-8",
    )

    proposals_dir.joinpath(f"{approved_id}.json").write_text(
        json.dumps(
            {
                "proposal_id": approved_id,
                "goal": "Approved goal",
                "dataset": "data/fixtures/iris.csv",
                "target": "species",
                "model_grid": ["random_forest"],
                "seeds": [42],
                "rationale": "Approved rationale.",
            }
        ),
        encoding="utf-8",
    )
    proposals_dir.joinpath(f"{approved_id}.approved.json").write_text(
        json.dumps({"proposal_id": approved_id, "principal": "test", "approved_at": "2026-08-24T00:00:00+00:00"}),
        encoding="utf-8",
    )
    proposals_dir.joinpath(f"{approved_id}.batch.json").write_text(
        json.dumps([{"dataset": "data/fixtures/iris.csv", "target": "species", "model": "random_forest", "seed": 42}]),
        encoding="utf-8",
    )

    proposals_dir.joinpath(f"{rejected_id}.json").write_text(
        json.dumps(
            {
                "proposal_id": rejected_id,
                "goal": "Rejected goal",
                "dataset": "data/fixtures/iris.csv",
                "target": "species",
                "model_grid": ["svc"],
                "seeds": [42],
                "rationale": "Rejected rationale.",
            }
        ),
        encoding="utf-8",
    )
    proposals_dir.joinpath(f"{rejected_id}.rejected.json").write_text(
        json.dumps({"proposal_id": rejected_id, "principal": "test", "rejected_at": "2026-08-24T00:00:00+00:00"}),
        encoding="utf-8",
    )

    return pending_id, approved_id, rejected_id


def _write_agent_events(events_path: Path) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        json.dumps(
            {
                "event_id": "evt-old",
                "event_type": "agent_session_summary",
                "timestamp": "2026-08-24T10:00:00+00:00",
                "agent": {"source": "agent_worker"},
                "outcome": {"status": "completed", "summary": "Old session"},
                "tags": ["agent_mode:worker"],
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-recent",
                "event_type": "agent_session_summary",
                "timestamp": "2026-08-24T12:00:00+00:00",
                "agent": {"platform": "opencode"},
                "outcome": {"status": "completed", "summary": "Recent session"},
                "tags": ["agent_mode:worker"],
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "evt-system",
                "event_type": "system",
                "timestamp": "2026-08-24T13:00:00+00:00",
                "outcome": {"status": "completed", "summary": "System event"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_root_serves_built_ui_or_fallback(client: TestClient):
    """GET / serves the built web/ dist when present, else the fallback page."""
    response = client.get("/")
    assert response.status_code == 200
    assert "The Lab" in response.text


def test_static_mount_serves_built_assets(client: TestClient):
    """The /static mount serves the dist (built) or at least the kept dir marker."""
    keep = client.get("/static/.gitkeep")
    assets = client.get("/static/")
    assert keep.status_code == 200 or assets.status_code in {200, 404}
    index = client.get("/static/index.html")
    if index.status_code == 200:
        assert 'id="root"' in index.text


def test_web_source_structure():
    """The React source tree is committed and references the API client."""
    web = Path(__file__).resolve().parents[1] / "web"
    assert (web / "package.json").is_file()
    assert (web / "src" / "App.tsx").is_file()
    assert (web / "src" / "theme" / "breeze.css").is_file()
    package = json.loads((web / "package.json").read_text(encoding="utf-8"))
    assert "react" in package["dependencies"]
    vite_config = (web / "vite.config.ts").read_text(encoding="utf-8")
    assert "/static/" in vite_config  # built assets land under /static


def test_built_css_layout_contract():
    """When built, the served CSS must carry the shell grid, drawer and
    utility classes — guards against stale/missing bundle layouts."""
    import re

    static_dir = (
        Path(__file__).resolve().parents[1] / "thelab" / "model_service" / "static"
    )
    css_files = list(static_dir.glob("assets/*.css"))
    if not css_files:
        pytest.skip("UI not built")
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    ref = re.findall(r"/static/assets/([a-zA-Z0-9._-]+\.css)", index)
    assert ref, "index.html must reference the built css"
    flat = re.sub(r"\s+", "", (static_dir / "assets" / ref[0]).read_text(encoding="utf-8"))
    assert "grid-template-columns:56px232px1fr" in flat
    assert ".hidden{display:none!important}" in flat
    assert ".chat-overlay{position:fixed" in flat


def test_app_shell_has_exactly_three_grid_children():
    """Regression: the chat drawer must not be a .app-shell grid child
    (it stole the 1fr column and squeezed the main view)."""
    app_tsx = (
        Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx"
    ).read_text(encoding="utf-8")
    shell_start = app_tsx.index('<div className="app-shell">')
    shell_end = app_tsx.index("</div>", app_tsx.index('<main className="app-main">'))
    shell = app_tsx[shell_start:shell_end]
    assert shell.count("<ChatDrawer") == 0, "ChatDrawer must render outside .app-shell"
    for child in ("<Dock", "<Sidebar", '<main className="app-main">'):
        assert child in shell


def test_fallback_page_present():
    fallback = Path(__file__).resolve().parents[1] / "thelab" / "model_service" / "fallback.html"
    assert fallback.is_file()
    assert "build_ui.sh" in fallback.read_text(encoding="utf-8")


def test_benchmarks_returns_manifest(client: TestClient, tmp_path: Path, monkeypatch):
    _write_benchmark_manifest(tmp_path)
    monkeypatch.chdir(tmp_path)

    response = client.get("/benchmarks")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["benchmark_id"] == "b1"
    assert payload["data"]["providers"][0]["provider"] == "test"


def test_benchmarks_returns_null_when_missing(client: TestClient, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    response = client.get("/benchmarks")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"] is None
    assert "No benchmark manifest found" in payload["message"]


def test_proposals_lists_with_status(
    client: TestClient, tmp_path: Path, monkeypatch
):
    proposals_dir = tmp_path / "proposals"
    pending_id, approved_id, rejected_id = _write_proposals(proposals_dir)
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals_dir))

    response = client.get("/proposals")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    proposals = {p["proposal_id"]: p for p in payload["data"]}
    assert len(proposals) == 3
    assert proposals[pending_id]["status"] == "pending"
    assert proposals[approved_id]["status"] == "approved"
    assert proposals[approved_id]["batch_config"] == f"{approved_id}.batch.json"
    assert proposals[rejected_id]["status"] == "rejected"

    # Derived files should not appear as standalone proposals.
    names = {p["proposal_id"] for p in payload["data"]}
    assert f"{approved_id}.approved" not in names
    assert f"{approved_id}.batch" not in names


def test_proposals_detail_returns_full_data(
    client: TestClient, tmp_path: Path, monkeypatch
):
    proposals_dir = tmp_path / "proposals"
    pending_id, approved_id, _ = _write_proposals(proposals_dir)
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals_dir))

    response = client.get(f"/proposals/{approved_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["proposal_id"] == approved_id
    assert data["status"] == "approved"
    assert data["batch_config"] == f"{approved_id}.batch.json"
    assert data["goal"] == "Approved goal"

    response = client.get(f"/proposals/{pending_id}")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"


def test_proposals_detail_rejects_unsafe_id(
    client: TestClient, tmp_path: Path, monkeypatch
):
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir(parents=True)
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals_dir))

    response = client.get("/proposals/../etc/passwd")
    assert response.status_code == 404

    response = client.get("/proposals/.hidden")
    assert response.status_code == 404


def test_agent_sessions_returns_recent_summaries(
    client: TestClient, tmp_path: Path, monkeypatch
):
    events_path = tmp_path / "agent-events.jsonl"
    _write_agent_events(events_path)
    monkeypatch.setenv("THELAB_AGENT_EVENTS", str(events_path))

    response = client.get("/agent-sessions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    sessions = payload["data"]
    assert len(sessions) == 2
    # Newest first.
    assert sessions[0]["event_id"] == "evt-recent"
    assert sessions[0]["source"] == "agent_worker"
    assert sessions[0]["outcome"]["summary"] == "Recent session"
    assert sessions[1]["event_id"] == "evt-old"
    assert sessions[1]["source"] == "agent_worker"

    # System events should be excluded.
    event_ids = {s["event_id"] for s in sessions}
    assert "evt-system" not in event_ids


def test_agent_sessions_empty_when_missing(client: TestClient, tmp_path: Path, monkeypatch):
    events_path = tmp_path / "agent-events.jsonl"
    monkeypatch.setenv("THELAB_AGENT_EVENTS", str(events_path))

    response = client.get("/agent-sessions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"] == []


def test_existing_endpoints_still_work(
    client: TestClient, tmp_path: Path, monkeypatch
):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    response = client.get("/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["data"]) == 1
    assert payload["data"][0]["run_id"] == run_id

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == run_id

    response = client.get(f"/runs/{run_id}/artifacts")
    assert response.status_code == 200
    artifact_names = {a["name"] for a in response.json()["data"]}
    assert "manifest.json" in artifact_names
    assert "model.joblib" not in artifact_names


def test_predict_form_feature_inputs_return_predictions(
    client: TestClient, tmp_path: Path, monkeypatch
):
    run_id = _completed_iris_run(tmp_path)
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    feature_columns = response.json()["data"]["feature_columns"]
    assert "sepal_length" in feature_columns

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
    assert len(payload["data"]["predictions"]) == 1
