"""Local stdio MCP server exposing deterministic EDA skills.

Tools:
- missing_profile(dataset, target?)
- correlation_hints(dataset, target?)
- class_balance(dataset, target)
- outlier_scan(dataset, target?)
- leakage_suspects(dataset, target)
- feature_types(dataset, target?)

All *dataset* arguments are project-relative CSV paths. Absolute paths and
parent-directory traversal are rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from thelab.eda import (
    class_balance,
    correlation_hints,
    feature_types,
    leakage_suspects,
    missing_profile,
    outlier_scan,
)
from thelab.run.profile import read_csv

TOOLS = [
    types.Tool(
        name="missing_profile",
        description="Return per-column and co-occurrence missingness statistics.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dataset": {"type": "string", "description": "Relative path to a CSV file"},
                "target": {"type": "string"},
            },
            "required": ["dataset"],
        },
    ),
    types.Tool(
        name="correlation_hints",
        description="Return top Pearson correlations among numeric features and with target.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dataset": {"type": "string", "description": "Relative path to a CSV file"},
                "target": {"type": "string"},
            },
            "required": ["dataset"],
        },
    ),
    types.Tool(
        name="class_balance",
        description="Return class distribution and imbalance diagnostics for a target column.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dataset": {"type": "string", "description": "Relative path to a CSV file"},
                "target": {"type": "string"},
            },
            "required": ["dataset", "target"],
        },
    ),
    types.Tool(
        name="outlier_scan",
        description="Return IQR and z-score outlier flags per numeric column.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dataset": {"type": "string", "description": "Relative path to a CSV file"},
                "target": {"type": "string"},
            },
            "required": ["dataset"],
        },
    ),
    types.Tool(
        name="leakage_suspects",
        description="Return features suspiciously correlated with or predictive of the target.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dataset": {"type": "string", "description": "Relative path to a CSV file"},
                "target": {"type": "string"},
            },
            "required": ["dataset", "target"],
        },
    ),
    types.Tool(
        name="feature_types",
        description="Return a dtype/coercion report for each column.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dataset": {"type": "string", "description": "Relative path to a CSV file"},
                "target": {"type": "string"},
            },
            "required": ["dataset"],
        },
    ),
]

_TOOL_TO_FUNCTION = {
    "missing_profile": missing_profile,
    "correlation_hints": correlation_hints,
    "class_balance": class_balance,
    "outlier_scan": outlier_scan,
    "leakage_suspects": leakage_suspects,
    "feature_types": feature_types,
}


def _ok(data: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": True, "data": data}))]
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": False, "error": message}))]
    )


def _resolve_dataset(value: str, runs_root: Path) -> Path | None:
    """Resolve a project-relative dataset path safely.

    Rejects absolute paths and any path containing ``..`` or leading to a
    location outside the workspace.
    """
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return None
    if ".." in path.parts:
        return None
    resolved = (runs_root / path).resolve()
    root_resolved = runs_root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    from .common import get_runs_root

    runs_root = get_runs_root()
    name = params.name
    arguments = params.arguments or {}

    if name not in _TOOL_TO_FUNCTION:
        return _error(f"unknown tool: {name}")

    dataset_arg = arguments.get("dataset", "")
    dataset_path = _resolve_dataset(dataset_arg, runs_root)
    if dataset_path is None:
        return _error(f"invalid or unsafe dataset path: {dataset_arg}")
    if not dataset_path.is_file():
        return _error(f"dataset not found: {dataset_arg}")

    try:
        df = read_csv(dataset_path)
    except Exception as exc:
        return _error(f"cannot read dataset: {exc}")

    raw_target = arguments.get("target")
    if name in {"class_balance", "leakage_suspects"} and not isinstance(raw_target, str):
        return _error(f"target is required for {name}")
    target: str | None = raw_target if isinstance(raw_target, str) else None
    func = _TOOL_TO_FUNCTION[name]
    try:
        result = func(df, target=target)
    except Exception as exc:
        return _error(f"eda computation failed: {exc}")

    return _ok(result)


server = Server(
    "thelab-eda",
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
