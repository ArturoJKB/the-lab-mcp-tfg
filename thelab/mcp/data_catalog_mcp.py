"""Local stdio MCP server exposing dataset catalog capabilities.

Tools:
- list_datasets
- get_data_profile(run_id)
- get_dataset_contract(run_id)
"""

from __future__ import annotations

import json
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .common import discover_run_ids, get_runs_root, load_json_artifact

TOOLS = [
    types.Tool(
        name="list_datasets",
        description="List local datasets discovered from run manifests.",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_data_profile",
        description="Return the persisted data_profile.json for a run.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    ),
    types.Tool(
        name="get_dataset_contract",
        description="Return the persisted dataset_contract.json for a run.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
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

    if name == "list_datasets":
        datasets = []
        for run_id in discover_run_ids(runs_root):
            manifest = load_json_artifact(runs_root, run_id, "manifest.json")
            if manifest is None:
                continue
            inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
            profile = load_json_artifact(runs_root, run_id, "data_profile.json") or {}
            datasets.append({
                "run_id": run_id,
                "dataset": inputs.get("dataset"),
                "input_hash": manifest.get("input_hash"),
                "target": inputs.get("target"),
                "validation_status": manifest.get("validation_status"),
                "row_count": profile.get("row_count"),
                "column_count": profile.get("column_count"),
            })
        return _ok(datasets)

    if name == "get_data_profile":
        run_id = arguments.get("run_id", "")
        profile_data = load_json_artifact(runs_root, run_id, "data_profile.json")
        if profile_data is None:
            return _error(f"data_profile not found for run_id: {run_id}")
        return _ok(profile_data)

    if name == "get_dataset_contract":
        run_id = arguments.get("run_id", "")
        contract = load_json_artifact(runs_root, run_id, "dataset_contract.json")
        if contract is None:
            return _error(f"dataset_contract not found for run_id: {run_id}")
        return _ok(contract)

    return _error(f"unknown tool: {name}")


server = Server(
    "thelab-data-catalog",
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
