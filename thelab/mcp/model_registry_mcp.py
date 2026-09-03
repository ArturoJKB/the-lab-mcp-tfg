"""Local stdio MCP server exposing approved-model registry capabilities.

Tools:
- list_models
- get_model_manifest(run_id)
- get_model_card(run_id)
- get_model_metrics(run_id)
"""

from __future__ import annotations

import json
from typing import Any

import joblib
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from thelab.run.inference import feature_columns, normalize_features, predict_features

from .common import (
    discover_run_ids,
    get_runs_root,
    load_json_artifact,
    load_text_artifact,
    safe_run_dir,
)

TOOLS = [
    types.Tool(
        name="list_models",
        description="List approved models discovered from completed run manifests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="get_model_manifest",
        description="Return the persisted manifest.json for a run.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="get_model_card",
        description="Return the persisted model_card.md for a run.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="get_model_metrics",
        description="Return the persisted metrics.json for a run.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="predict",
        description="Run inference with the approved model.joblib for a run.",
        input_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "features": {
                    "type": "array",
                    "description": "List of feature records (dicts) or rows (lists).",
                    "items": {"type": ["object", "array"]},
                },
            },
            "required": ["run_id", "features"],
            "additionalProperties": False,
        },
    ),
]


def _ok(data: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": True, "data": data}))]
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": False, "error": message}))]
    )


async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    runs_root = get_runs_root()
    name = params.name
    arguments = params.arguments or {}

    if name == "list_models":
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
            models.append({
                "run_id": run_id,
                "model": inputs.get("model"),
                "task_type": task_type,
                "seed": manifest.get("random_seed"),
                "metrics": {
                    "test_accuracy": metrics.get("test_accuracy"),
                    "test_f1_macro": metrics.get("test_f1_macro"),
                    "train_samples": metrics.get("train_samples"),
                    "test_samples": metrics.get("test_samples"),
                },
                "artifact_paths": {
                    "manifest": f"{run_id}/manifest.json",
                    "model_card": f"{run_id}/model_card.md",
                    "metrics": f"{run_id}/metrics.json",
                    "model": f"{run_id}/model.joblib",
                },
                "input_hash": manifest.get("input_hash"),
            })
        return _ok(models)

    if name == "get_model_manifest":
        run_id = arguments.get("run_id", "")
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            return _error(f"manifest not found for run_id: {run_id}")
        return _ok(manifest)

    if name == "get_model_card":
        run_id = arguments.get("run_id", "")
        card = load_text_artifact(runs_root, run_id, "model_card.md")
        if card is None:
            return _error(f"model_card not found for run_id: {run_id}")
        return _ok({"run_id": run_id, "model_card": card})

    if name == "get_model_metrics":
        run_id = arguments.get("run_id", "")
        metrics_data = load_json_artifact(runs_root, run_id, "metrics.json")
        if metrics_data is None:
            return _error(f"metrics not found for run_id: {run_id}")
        return _ok(metrics_data)

    if name == "predict":
        run_id = arguments.get("run_id", "")
        features = arguments.get("features", [])

        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            return _error(f"manifest not found for run_id: {run_id}")
        if manifest.get("final_status") != "completed":
            return _error(f"run {run_id} is not completed")
        if manifest.get("validation_status") != "approved":
            return _error(f"run {run_id} is not approved")

        run_path = safe_run_dir(runs_root, run_id)
        if run_path is None:
            return _error(f"run not found or unsafe: {run_id}")

        model_path = run_path / "model.joblib"
        if not model_path.is_file():
            return _error(f"model.joblib not found for run_id: {run_id}")

        inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
        target = inputs.get("target")
        if not target:
            return _error(f"target column not found for run_id: {run_id}")

        data_profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
        cols = feature_columns(data_profile, target)
        if not cols:
            return _error(f"could not determine feature columns for run_id: {run_id}")

        try:
            normalized = normalize_features(features, cols)
            model = joblib.load(model_path)
            predictions = predict_features(model, normalized, cols)
            return _ok(
                {
                    "run_id": run_id,
                    "model": inputs.get("model"),
                    "target": target,
                    "feature_columns": cols,
                    "predictions": predictions.tolist() if hasattr(predictions, "tolist") else list(predictions),
                }
            )
        except Exception:
            return _error("prediction failed")

    return _error(f"unknown tool: {name}")


server = Server(
    "thelab-model-registry",
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync() -> None:
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
