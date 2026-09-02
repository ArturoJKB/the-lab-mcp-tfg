"""FastAPI app serving predictions from approved local runs.

This service only exposes models that are both completed and approved. It is
intended for local human/UI consumption; agentic clients should prefer the
``predict`` tool on ``model_registry_mcp``.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Any

import joblib
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from thelab.agents.chat import chat as agent_chat
from thelab.context.reader import ContextReader, ContextReaderError
from thelab.ide.cleaning import clean_dataset
from thelab.ide.datasets import DatasetNotFoundError, UploadError, list_datasets, save_upload
from thelab.ide.eda_api import EdaError, run_eda
from thelab.ide.experiment_api import (
    add_experiment_feedback,
    get_experiment_events,
    get_experiment_results,
    get_experiment_status,
    list_experiments,
    start_experiment,
)
from thelab.ide.iterate_api import iterate_on_run
from thelab.ide.jobs import JobError, get_job_manager
from thelab.ide.proposals_api import (
    approve_and_run_proposal,
    approve_proposal,
    reject_proposal,
    run_proposal,
)
from thelab.ide.train_api import train_model
from thelab.ide.viewer_api import compare_runs, preview_dataset
from thelab.ide.worker_api import generate_proposal
from thelab.mcp.common import discover_run_ids, get_runs_root, load_json_artifact, safe_run_dir
from thelab.run.inference import feature_columns, normalize_features
from thelab.run.model_registry import MODEL_REGISTRY
from thelab.sandbox import run_in_sandbox
from thelab.sandbox.runner import SandboxError


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a repo-root .env into os.environ (setdefault)."""
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            os.environ.setdefault(key, value.strip().strip("'").strip('"'))


_load_dotenv()

_DEFAULT_CONTEXT_DB = Path(".thelab") / "context" / "context.db"

app = FastAPI(title="The Lab Model Service")


class PredictRequest(BaseModel):
    run_id: str
    features: list[Any] = Field(
        ...,
        description=(
            "Feature rows as a list of records (dicts) or rows (lists). "
            "A single record/row is also accepted and treated as one row."
        ),
    )

    @field_validator("features", mode="before")
    @classmethod
    def _wrap_single_row(cls, value: Any) -> Any:
        """Accept a single feature record or row and wrap it into a one-row list."""
        if isinstance(value, dict):
            return [value]
        if (
            isinstance(value, list)
            and value
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        ):
            return [value]
        return value


# Artifacts the UI is allowed to list and render.  Binary or unsafe files are
# excluded; `model.joblib` is never served over HTTP.
_ARTIFACT_ALLOWLIST: dict[str, str] = {
    "manifest.json": "json",
    "metrics.json": "json",
    "data_profile.json": "json",
    "inputs.json": "json",
    "validation_report.json": "json",
    "training_config.json": "json",
    "dataset_contract.json": "json",
    "model_card.md": "text",
    "task_spec.json": "json",
}


def _dataset_basename(dataset_value: Any) -> str | None:
    """Return the basename of a dataset path; never leak absolute paths."""
    if dataset_value is None:
        return None
    if isinstance(dataset_value, str):
        return Path(dataset_value).name
    return str(dataset_value)


def _is_safe_basename(name: str) -> bool:
    """Reject names that could escape a directory or reference derived files."""
    if not name or "/" in name or "\\" in name or name == ".." or ".." in Path(name).parts:
        return False
    if name.startswith("."):
        return False
    return True


def _proposals_dir() -> Path:
    return Path(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))


def _agent_events_path() -> Path:
    return Path(os.environ.get("THELAB_AGENT_EVENTS", ".thelab/local-logs/agent-events.jsonl"))


def _proposal_status(proposal_id: str, proposals_dir: Path) -> tuple[str, str | None]:
    """Return (status, batch_config_basename) for a proposal id."""
    approved_path = proposals_dir / f"{proposal_id}.approved.json"
    rejected_path = proposals_dir / f"{proposal_id}.rejected.json"
    batch_path = proposals_dir / f"{proposal_id}.batch.json"
    if approved_path.is_file():
        batch_config = batch_path.name if batch_path.is_file() else None
        return "approved", batch_config
    if rejected_path.is_file():
        return "rejected", None
    return "pending", None


def _list_proposals() -> list[dict[str, Any]]:
    proposals_dir = _proposals_dir()
    if not proposals_dir.exists() or not proposals_dir.is_dir():
        return []

    proposals = []
    for path in proposals_dir.iterdir():
        if not path.is_file() or path.suffix != ".json":
            continue
        name = path.name
        # Skip derived state files.
        if name.endswith(".approved.json") or name.endswith(".rejected.json") or name.endswith(".batch.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        proposal_id = data.get("proposal_id") or path.stem
        status, batch_config = _proposal_status(proposal_id, proposals_dir)
        proposals.append(
            {
                "proposal_id": proposal_id,
                "status": status,
                "goal": data.get("goal"),
                "dataset": data.get("dataset"),
                "target": data.get("target"),
                "model_grid": data.get("model_grid", []),
                "seeds": data.get("seeds", []),
                "rationale": data.get("rationale"),
                "batch_config": batch_config,
            }
        )
    return proposals


def _load_proposal(proposal_id: str) -> dict[str, Any] | None:
    if not _is_safe_basename(proposal_id):
        return None
    proposals_dir = _proposals_dir()
    path = proposals_dir / f"{proposal_id}.json"
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status, batch_config = _proposal_status(proposal_id, proposals_dir)
    return {
        "proposal_id": proposal_id,
        "status": status,
        "goal": data.get("goal"),
        "dataset": data.get("dataset"),
        "target": data.get("target"),
        "model_grid": data.get("model_grid", []),
        "seeds": data.get("seeds", []),
        "rationale": data.get("rationale"),
        "batch_config": batch_config,
        "created_at": data.get("created_at"),
    }


def _agent_session_source(data: dict[str, Any]) -> str:
    """Infer a human-readable source label from session metadata."""
    agent = data.get("agent") or {}
    for tag in data.get("tags", []):
        if isinstance(tag, str) and tag.startswith("agent_mode:"):
            return f"agent_{tag.split(':', 1)[1]}"
    if agent.get("source"):
        return str(agent["source"])
    if agent.get("platform"):
        return str(agent["platform"])
    event_type = data.get("event_type")
    return str(event_type) if event_type is not None else "agent"


def _list_agent_sessions(limit: int = 50) -> list[dict[str, Any]]:
    path = _agent_events_path()
    if not path.is_file():
        return []
    sessions: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("event_type") != "agent_session_summary":
            continue
        sessions.append(
            {
                "event_id": data.get("event_id"),
                "timestamp": data.get("timestamp"),
                "source": _agent_session_source(data),
                "outcome": data.get("outcome", {}),
                "tags": data.get("tags", []),
            }
        )
        if len(sessions) >= limit:
            break
    return sessions


def _context_db_path() -> Path:
    env_path = os.environ.get("THELAB_CONTEXT_DB")
    if env_path:
        return Path(env_path)
    return _DEFAULT_CONTEXT_DB


def _context_entry_to_dict(entry: Any) -> dict[str, Any]:
    """Public DTO for context entries (matches context_mcp)."""
    data: dict[str, Any] = entry.model_dump(
        mode="json",
        include={
            "event_id",
            "event_type",
            "session_id",
            "run_id",
            "tags",
            "redacted_summary",
            "related_artifact_refs",
            "privacy_level",
            "timestamp",
        },
    )
    return data


def _agent_coding_overview() -> dict[str, Any]:
    runs_root = get_runs_root()
    run_ids = discover_run_ids(runs_root)
    approved_completed = 0
    for run_id in run_ids:
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            continue
        if (
            manifest.get("final_status") == "completed"
            and manifest.get("validation_status") == "approved"
        ):
            approved_completed += 1

    return {
        "total_runs": len(run_ids),
        "approved_completed_runs": approved_completed,
        "recent_run_ids": run_ids[-10:],
    }


def _agent_coding_runs() -> list[dict[str, Any]]:
    runs_root = get_runs_root()
    runs = []
    for run_id in discover_run_ids(runs_root):
        manifest = load_json_artifact(runs_root, run_id, "manifest.json") or {}
        inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
        runs.append(
            {
                "run_id": run_id,
                "final_status": manifest.get("final_status"),
                "validation_status": manifest.get("validation_status"),
                "model": inputs.get("model"),
                "target": inputs.get("target"),
                "dataset": _dataset_basename(inputs.get("dataset")),
            }
        )
    return runs


def _agent_coding_run_detail(run_id: str) -> dict[str, Any]:
    runs_root = get_runs_root()
    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        raise HTTPException(status_code=404, detail=f"run not found or unsafe: {run_id}")

    manifest = load_json_artifact(runs_root, run_id, "manifest.json")
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"manifest not found for run_id: {run_id}")

    inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
    data_profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
    metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
    target = inputs.get("target")
    cols = feature_columns(data_profile, target) if target else []
    task_type = manifest.get("task_type") or inputs.get("task_type") or "classification"

    artifacts = []
    for name in sorted(_ARTIFACT_ALLOWLIST):
        if (run_path / name).is_file():
            artifacts.append({"name": name, "kind": _ARTIFACT_ALLOWLIST[name]})

    return {
        "run_id": run_id,
        "final_status": manifest.get("final_status"),
        "validation_status": manifest.get("validation_status"),
        "model": inputs.get("model"),
        "target": target,
        "dataset": _dataset_basename(inputs.get("dataset")),
        "feature_columns": cols,
        "task_type": task_type,
        "metrics": {
            "test_accuracy": metrics.get("test_accuracy"),
            "test_f1_macro": metrics.get("test_f1_macro"),
            "test_rmse": metrics.get("test_rmse"),
            "test_mae": metrics.get("test_mae"),
            "test_r2": metrics.get("test_r2"),
        },
        "seed": inputs.get("seed"),
        "artifacts": artifacts,
    }


def _list_approved_models() -> list[dict[str, Any]]:
    runs_root = get_runs_root()
    models = []
    for run_id in discover_run_ids(runs_root):
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            continue
        if manifest.get("final_status") != "completed":
            continue
        if manifest.get("validation_status") != "approved":
            continue
        inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
        metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
        task_type = manifest.get("task_type") or inputs.get("task_type") or "classification"
        models.append(
            {
                "run_id": run_id,
                "model": inputs.get("model"),
                "target": inputs.get("target"),
                "task_type": task_type,
                "metrics": {
                    "test_accuracy": metrics.get("test_accuracy"),
                    "test_f1_macro": metrics.get("test_f1_macro"),
                    "test_rmse": metrics.get("test_rmse"),
                    "test_mae": metrics.get("test_mae"),
                    "test_r2": metrics.get("test_r2"),
                },
            }
        )
    return models


def _run_summary(run_id: str) -> dict[str, Any]:
    """Return a read-only, path-safe summary of an approved completed run."""
    runs_root = get_runs_root()
    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        raise HTTPException(status_code=404, detail=f"run not found or unsafe: {run_id}")

    manifest = load_json_artifact(runs_root, run_id, "manifest.json")
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"manifest not found for run_id: {run_id}")
    if manifest.get("final_status") != "completed":
        raise HTTPException(status_code=400, detail=f"run {run_id} is not completed")
    if manifest.get("validation_status") != "approved":
        raise HTTPException(status_code=400, detail=f"run {run_id} is not approved")

    inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
    data_profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
    metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
    target = inputs.get("target")
    cols = feature_columns(data_profile, target) if target else []
    task_type = manifest.get("task_type") or inputs.get("task_type") or "classification"

    return {
        "run_id": run_id,
        "final_status": manifest.get("final_status"),
        "validation_status": manifest.get("validation_status"),
        "model": inputs.get("model"),
        "target": target,
        "feature_columns": cols,
        "task_type": task_type,
        "metrics": {
            "test_accuracy": metrics.get("test_accuracy"),
            "test_f1_macro": metrics.get("test_f1_macro"),
            "test_rmse": metrics.get("test_rmse"),
            "test_mae": metrics.get("test_mae"),
            "test_r2": metrics.get("test_r2"),
        },
        "seed": inputs.get("seed"),
        "dataset": _dataset_basename(inputs.get("dataset")),
    }


def _predict(run_id: str, features: list[Any]) -> dict[str, Any]:
    runs_root = get_runs_root()
    manifest = load_json_artifact(runs_root, run_id, "manifest.json")
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"manifest not found for run_id: {run_id}")
    if manifest.get("final_status") != "completed":
        raise HTTPException(status_code=400, detail=f"run {run_id} is not completed")
    if manifest.get("validation_status") != "approved":
        raise HTTPException(status_code=400, detail=f"run {run_id} is not approved")

    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        raise HTTPException(status_code=404, detail=f"run not found or unsafe: {run_id}")

    model_path = run_path / "model.joblib"
    if not model_path.is_file():
        raise HTTPException(status_code=404, detail=f"model.joblib not found for run_id: {run_id}")

    inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
    target = inputs.get("target")
    if not target:
        raise HTTPException(status_code=400, detail=f"target column not found for run_id: {run_id}")

    data_profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
    cols = feature_columns(data_profile, target)
    if not cols:
        raise HTTPException(
            status_code=400, detail=f"could not determine feature columns for run_id: {run_id}"
        )

    try:
        normalized = normalize_features(features, cols)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        model = joblib.load(model_path)
        predictions = model.predict(normalized)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="prediction failed") from exc

    return {
        "run_id": run_id,
        "model": inputs.get("model"),
        "target": target,
        "feature_columns": cols,
        "predictions": predictions.tolist() if hasattr(predictions, "tolist") else list(predictions),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models")
def list_models() -> dict[str, Any]:
    return {"ok": True, "data": _list_approved_models()}


@app.get("/models/available")
def list_available_models() -> dict[str, Any]:
    return {"ok": True, "data": MODEL_REGISTRY.list_models()}


@app.post("/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    return {"ok": True, "data": _predict(request.run_id, request.features)}


@app.get("/runs/comparison")
def get_runs_comparison() -> dict[str, Any]:
    return {"ok": True, "data": compare_runs()}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return {"ok": True, "data": _run_summary(run_id)}


@app.get("/runs/{run_id}/artifacts")
def list_artifacts(run_id: str) -> dict[str, Any]:
    runs_root = get_runs_root()
    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        raise HTTPException(status_code=404, detail=f"run not found or unsafe: {run_id}")

    items = []
    for name in sorted(_ARTIFACT_ALLOWLIST):
        artifact_path = run_path / name
        if artifact_path.is_file():
            items.append({"name": name, "kind": _ARTIFACT_ALLOWLIST[name]})
    return {"ok": True, "data": items}


@app.get("/runs/{run_id}/artifacts/{artifact_name}")
def get_artifact(run_id: str, artifact_name: str) -> dict[str, Any]:
    runs_root = get_runs_root()
    run_path = safe_run_dir(runs_root, run_id)
    if run_path is None:
        raise HTTPException(status_code=404, detail=f"run not found or unsafe: {run_id}")

    if artifact_name not in _ARTIFACT_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"artifact not allowed: {artifact_name}")

    kind = _ARTIFACT_ALLOWLIST[artifact_name]
    artifact_path = run_path / artifact_name
    try:
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail=f"artifact not found: {artifact_name}")
        if kind == "json":
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        else:
            data = artifact_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to read artifact: {exc}") from exc

    return {"ok": True, "data": data}


@app.get("/runs/{run_id}/notebook")
def get_run_notebook(run_id: str) -> dict[str, Any]:
    """Generate the reproducible research notebook for a run on demand."""
    from thelab.run.notebook import generate_run_notebook

    try:
        notebook = generate_run_notebook(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": notebook}


@app.get("/agent/coding/overview")
def agent_coding_overview() -> dict[str, Any]:
    return {"ok": True, "data": _agent_coding_overview()}


@app.get("/agent/coding/runs")
def agent_coding_runs() -> dict[str, Any]:
    return {"ok": True, "data": _agent_coding_runs()}


@app.get("/agent/coding/runs/{run_id}")
def agent_coding_run(run_id: str) -> dict[str, Any]:
    return {"ok": True, "data": _agent_coding_run_detail(run_id)}


@app.get("/agent/research/context/status")
def agent_research_context_status() -> dict[str, Any]:
    reader = ContextReader(_context_db_path())
    return {"ok": True, "data": reader.status()}


@app.get("/agent/research/context/search")
def agent_research_context_search(query: str | None = None, limit: int = 50) -> dict[str, Any]:
    reader = ContextReader(_context_db_path())
    try:
        entries = reader.search(query=query, limit=limit)
    except ContextReaderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": [_context_entry_to_dict(entry) for entry in entries]}


@app.get("/agent/research/context/entries/{event_id}")
def agent_research_context_entry(event_id: str) -> dict[str, Any]:
    reader = ContextReader(_context_db_path())
    entry = reader.get(event_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"entry not found: {event_id}")
    return {"ok": True, "data": _context_entry_to_dict(entry)}


@app.get("/benchmarks")
def list_benchmarks() -> dict[str, Any]:
    manifest_path = Path("benchmarks/b1/benchmark_manifest.json")
    if not manifest_path.is_file():
        return {"ok": True, "data": None, "message": "No benchmark manifest found"}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to read benchmark manifest: {exc}") from exc
    return {"ok": True, "data": data}


@app.get("/proposals")
def list_proposals() -> dict[str, Any]:
    return {"ok": True, "data": _list_proposals()}


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str) -> dict[str, Any]:
    proposal = _load_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal not found: {proposal_id}")
    return {"ok": True, "data": proposal}


@app.get("/agent-sessions")
def list_agent_sessions(limit: int = 50) -> dict[str, Any]:
    return {"ok": True, "data": _list_agent_sessions(limit=limit)}


@app.post("/datasets/upload")
def upload_dataset(file: Annotated[UploadFile, File(...)]) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is empty")
    try:
        metadata = save_upload(file.file, file.filename)
    except UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": metadata}


@app.get("/datasets")
def get_datasets() -> dict[str, Any]:
    return {"ok": True, "data": list_datasets()}


@app.get("/eda/{dataset_id:path}")
def get_eda(dataset_id: str, target: str | None = None) -> dict[str, Any]:
    try:
        data = run_eda(dataset_id, target=target)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EdaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@app.get("/datasets/{dataset_id:path}/preview")
def get_dataset_preview(dataset_id: str, limit: int = 100) -> dict[str, Any]:
    try:
        data = preview_dataset(dataset_id, limit=limit)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@app.post("/agent/worker")
async def post_agent_worker(payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = payload.get("dataset_id")
    target = payload.get("target")
    goal = payload.get("goal", "")
    if not dataset_id or not target or not goal:
        raise HTTPException(status_code=400, detail="dataset_id, target, and goal are required")
    try:
        proposal = await generate_proposal(
            dataset_id=dataset_id,
            target=target,
            goal=goal,
            model_grid=payload.get("model_grid"),
            seeds=payload.get("seeds"),
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": proposal}


@app.post("/agent/iterate")
async def post_agent_iterate(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = payload.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    try:
        proposal = await iterate_on_run(run_id, goal=payload.get("goal"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": proposal}


_SANDBOX_MAX_TIMEOUT_S = 120
_SANDBOX_MIN_MEMORY_MB = 64
_SANDBOX_MAX_MEMORY_MB = 2048
_SANDBOX_MAX_OUTPUT_BYTES = 1024 * 1024


@app.post("/datasets/ingest-kaggle")
def post_ingest_kaggle(payload: dict[str, Any]) -> dict[str, Any]:
    slug = payload.get("slug")
    if not slug or "/" not in str(slug):
        raise HTTPException(status_code=400, detail="slug must be a Kaggle dataset slug like 'owner/dataset'")
    from thelab.ide.kaggle_api import (
        KaggleIngestError,
        build_context_pack,
        fetch_kaggle_page_context,
        ingest_kaggle_dataset,
    )

    try:
        ingestion = ingest_kaggle_dataset(str(slug), payload.get("file_path"))
    except KaggleIngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - network/auth failures from kagglehub
        raise HTTPException(status_code=502, detail=f"kaggle ingestion failed: {exc}") from exc

    page_context = fetch_kaggle_page_context(str(slug))
    pack = build_context_pack(str(slug), ingestion, page_context)
    return {
        "ok": True,
        "data": {
            "dataset_id": ingestion["dataset_id"],
            "profile": ingestion["profile"],
            "context_pack": pack,
        },
    }


@app.get("/agent/providers")
async def get_agent_providers() -> dict[str, Any]:
    from thelab.agents.chat import ollama_models, openrouter_models, provider_status

    providers = provider_status()
    ollama = await asyncio.to_thread(ollama_models)
    openrouter = await asyncio.to_thread(openrouter_models)
    for entry in providers:
        if entry["name"] == "ollama":
            entry["reachable"] = ollama["reachable"]
            entry["models"] = [{"id": n, "name": n} for n in ollama["models"]]
        if entry["name"] == "openrouter":
            entry["models"] = openrouter.get("models", [])
    return {"ok": True, "data": providers}


_CHAT_PROVIDERS = {"mock", "openai_compat", "ollama", "openrouter"}
_chat_stream_tasks: set[asyncio.Task[None]] = set()


def _validate_chat_payload(payload: dict[str, Any]) -> None:
    message = payload.get("message")
    if not message or not str(message).strip():
        raise HTTPException(status_code=400, detail="message is required")
    provider_name = payload.get("provider", "mock")
    if provider_name not in _CHAT_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unsupported provider: {provider_name}")
    if not isinstance(payload.get("history") or [], list):
        raise HTTPException(status_code=400, detail="history must be a list")


@app.post("/agent/chat")
async def post_agent_chat(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_chat_payload(payload)
    try:
        result = await agent_chat(
            message=str(payload["message"]),
            history=payload.get("history") or [],
            provider_name=str(payload.get("provider", "mock")),
            model=payload.get("model"),
            dataset_id=payload.get("dataset_id"),
            style=payload.get("style"),
            role_hint=payload.get("role_hint"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"agent failed: {exc}") from exc
    return {"ok": True, "data": result}


@app.post("/agent/chat/stream")
async def post_agent_chat_stream(payload: dict[str, Any]) -> StreamingResponse:
    _validate_chat_payload(payload)

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def runner() -> None:
        try:
            result = await agent_chat(
                message=str(payload["message"]),
                history=payload.get("history") or [],
                provider_name=str(payload.get("provider", "mock")),
                model=payload.get("model"),
                dataset_id=payload.get("dataset_id"),
                style=payload.get("style"),
                role_hint=payload.get("role_hint"),
                on_event=lambda e: queue.put_nowait({"type": "event", **e}),
            )
            queue.put_nowait({"type": "result", **result})
        except Exception as exc:  # noqa: BLE001
            queue.put_nowait({"type": "result", "status": "failed", "error": str(exc)})
        queue.put_nowait(None)

    task = asyncio.create_task(runner())
    _chat_stream_tasks.add(task)
    task.add_done_callback(_chat_stream_tasks.discard)

    async def gen() -> Any:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/sandbox/run")
def post_sandbox_run(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code", "")
    if not code or not isinstance(code, str):
        raise HTTPException(status_code=400, detail="code is required")
    try:
        # Clamp client-supplied resource knobs so a single request can neither
        # pin a worker thread for hours nor disable output truncation.
        timeout = min(max(int(payload.get("timeout", 30)), 1), _SANDBOX_MAX_TIMEOUT_S)
        memory_limit_mb = min(
            max(int(payload.get("memory_limit_mb", 512)), _SANDBOX_MIN_MEMORY_MB),
            _SANDBOX_MAX_MEMORY_MB,
        )
        max_output_bytes = min(
            int(payload.get("max_output_bytes", 64 * 1024)), _SANDBOX_MAX_OUTPUT_BYTES
        )
        result = run_in_sandbox(
            code=code,
            timeout=timeout,
            memory_limit_mb=memory_limit_mb,
            max_output_bytes=max_output_bytes,
        )
    except (SandboxError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": result.status in {"completed"},
        "data": {
            "status": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_value": result.return_value,
            "artifacts": result.artifacts or [],
            "error": result.error,
        },
    }


@app.post("/proposals/{proposal_id}/approve")
def post_proposal_approve(proposal_id: str) -> dict[str, Any]:
    try:
        result = approve_proposal(proposal_id, principal="ui")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": result}


@app.post("/proposals/{proposal_id}/reject")
def post_proposal_reject(proposal_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = (payload or {}).get("reason", "")
    try:
        result = reject_proposal(proposal_id, principal="ui", reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": result}


@app.post("/proposals/{proposal_id}/run")
def post_proposal_run(proposal_id: str) -> dict[str, Any]:
    try:
        result = run_proposal(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": result}


@app.post("/proposals/{proposal_id}/run-as-experiment")
async def post_proposal_run_as_experiment(proposal_id: str) -> dict[str, Any]:
    """Approve a proposal and execute it as a first-class experiment (SSE-visible)."""
    from thelab.ide.experiment_api import run_proposal_as_experiment

    try:
        data = await run_proposal_as_experiment(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"failed to start: {exc}") from exc
    return {"ok": True, "data": data}


@app.post("/proposals/{proposal_id}/approve-and-run")
def post_proposal_approve_and_run(proposal_id: str) -> dict[str, Any]:
    try:
        result = approve_and_run_proposal(proposal_id, principal="ui")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": result}


@app.post("/datasets/{dataset_id:path}/clean")
def post_clean_dataset(dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    target = payload.get("target")
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    try:
        metadata = clean_dataset(
            dataset_id,
            target,
            drop_missing_target=payload.get("drop_missing_target", True),
            drop_empty_columns=payload.get("drop_empty_columns", True),
            one_hot_encode=payload.get("one_hot_encode", True),
            numeric_impute_strategy=payload.get("numeric_impute_strategy", "median"),
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": metadata}


@app.post("/train")
def post_train(payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = payload.get("dataset_id")
    target = payload.get("target")
    model = payload.get("model")
    if not dataset_id or not target or not model:
        raise HTTPException(status_code=400, detail="dataset_id, target, and model are required")
    try:
        outcome = train_model(
            dataset_id=dataset_id,
            target=target,
            model=model,
            seed=int(payload.get("seed", 42)),
            task_type=payload.get("task_type", "auto"),
            hyperparameters=payload.get("hyperparameters"),
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": outcome}


@app.post("/jobs")
async def post_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    job_type = payload.get("type")
    job_payload = payload.get("payload")
    if not job_type or not isinstance(job_payload, dict):
        raise HTTPException(status_code=400, detail="type and payload are required")
    manager = get_job_manager()
    try:
        job = await manager.submit(job_type, job_payload)
    except JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": {"job_id": job.job_id, "status": job.status}}


@app.get("/jobs")
async def get_jobs(limit: int = 50) -> dict[str, Any]:
    manager = get_job_manager()
    jobs = await manager.list_jobs(limit=limit)
    return {"ok": True, "data": jobs}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    manager = get_job_manager()
    job = await manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return {"ok": True, "data": job.to_dict()}


@app.post("/jobs/{job_id}/cancel")
async def post_job_cancel(job_id: str) -> dict[str, Any]:
    manager = get_job_manager()
    job = await manager.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return {"ok": True, "data": {"job_id": job_id, "status": job.status, "cancel_requested": job.cancel_requested}}


@app.get("/jobs/{job_id}/events")
async def get_job_events(job_id: str) -> StreamingResponse:
    manager = get_job_manager()
    job = await manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")

    async def event_stream() -> Any:
        async for event in manager.events(job_id):
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/experiment/run")
async def post_experiment_run(payload: dict[str, Any]) -> dict[str, Any]:
    goal = payload.get("goal")
    dataset_id = payload.get("dataset_id")
    target = payload.get("target")
    if not goal or not dataset_id or not target:
        raise HTTPException(status_code=400, detail="goal, dataset_id, and target are required")
    try:
        data = await start_experiment(
            goal=str(goal),
            dataset_id=str(dataset_id),
            target=str(target),
            feedback=payload.get("feedback"),
            provider_name=str(payload.get("provider", "mock")),
            model=payload.get("model"),
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@app.get("/experiment/{experiment_id}/status")
async def get_experiment_status_endpoint(experiment_id: str) -> dict[str, Any]:
    try:
        data = await get_experiment_status(experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@app.get("/experiment/{experiment_id}/events")
async def get_experiment_events_endpoint(experiment_id: str) -> StreamingResponse:
    try:
        job_id = await get_experiment_events(experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not job_id:
        raise HTTPException(status_code=404, detail=f"experiment has no job: {experiment_id}")
    manager = get_job_manager()
    job = await manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")

    async def event_stream() -> Any:
        async for event in manager.events(job_id):
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/experiment/{experiment_id}/feedback")
async def post_experiment_feedback(experiment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    feedback = payload.get("feedback")
    if not feedback or not str(feedback).strip():
        raise HTTPException(status_code=400, detail="feedback is required")
    try:
        data = await add_experiment_feedback(experiment_id, str(feedback))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@app.get("/experiment/{experiment_id}/results")
async def get_experiment_results_endpoint(experiment_id: str) -> dict[str, Any]:
    try:
        data = await get_experiment_results(experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "data": data}


@app.get("/experiments")
async def get_experiments(limit: int = 50) -> dict[str, Any]:
    return {"ok": True, "data": await list_experiments(limit=limit)}


_static_dir = Path(__file__).parent / "static"
_fallback_path = Path(__file__).parent / "fallback.html"


@app.get("/")
def root() -> HTMLResponse:
    """Serve the built UI (web/ dist); fall back to a plain info page."""
    index = _static_dir / "index.html"
    if index.is_file():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse(content=_fallback_path.read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=_static_dir), name="static")
