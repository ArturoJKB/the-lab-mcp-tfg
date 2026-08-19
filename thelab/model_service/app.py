"""FastAPI app serving predictions from approved local runs.

This service only exposes models that are both completed and approved. It is
intended for local human/UI consumption; agentic clients should prefer the
``predict`` tool on ``model_registry_mcp``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import joblib
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from thelab.context.reader import ContextReader, ContextReaderError
from thelab.mcp.common import discover_run_ids, get_runs_root, load_json_artifact, safe_run_dir
from thelab.run.inference import feature_columns, normalize_features

_DEFAULT_CONTEXT_DB = Path(".thelab") / "context" / "context.db"

app = FastAPI(title="The Lab Model Service")


class PredictRequest(BaseModel):
    run_id: str
    features: list[Any] = Field(..., description="List of feature records (dicts) or rows (lists).")


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
        "metrics": {
            "test_accuracy": metrics.get("test_accuracy"),
            "test_f1_macro": metrics.get("test_f1_macro"),
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
        models.append(
            {
                "run_id": run_id,
                "model": inputs.get("model"),
                "target": inputs.get("target"),
                "metrics": {
                    "test_accuracy": metrics.get("test_accuracy"),
                    "test_f1_macro": metrics.get("test_f1_macro"),
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

    return {
        "run_id": run_id,
        "final_status": manifest.get("final_status"),
        "validation_status": manifest.get("validation_status"),
        "model": inputs.get("model"),
        "target": target,
        "feature_columns": cols,
        "metrics": {
            "test_accuracy": metrics.get("test_accuracy"),
            "test_f1_macro": metrics.get("test_f1_macro"),
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


@app.post("/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    return {"ok": True, "data": _predict(request.run_id, request.features)}


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


_static_dir = Path(__file__).parent / "static"


@app.get("/")
def root() -> HTMLResponse:
    return HTMLResponse(content=(_static_dir / "index.html").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=_static_dir), name="static")
