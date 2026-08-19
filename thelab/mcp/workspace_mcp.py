"""Local stdio MCP server exposing read-only workspace/artifact access.

Tools:
- list_runs
- get_run_manifest(run_id)
- list_run_artifacts(run_id)
- get_artifact(run_id, artifact_type)
- read_model_card(run_id)

This server intentionally does not expose logs; log access belongs to
``context_mcp``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .common import (
    discover_run_ids,
    get_runs_root,
    load_json_artifact,
    load_text_artifact,
    safe_run_dir,
)

TOOLS = [
    types.Tool(
        name="list_runs",
        description="List safe run directories in the workspace.",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_run_manifest",
        description="Return the persisted manifest.json for a run.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    ),
    types.Tool(
        name="list_run_artifacts",
        description="List artifact references stored in a run manifest.",
        input_schema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    ),
    types.Tool(
        name="get_artifact",
        description="Return a JSON artifact from a run directory by artifact type.",
        input_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "artifact_type": {"type": "string"},
            },
            "required": ["run_id", "artifact_type"],
        },
    ),
    types.Tool(
        name="read_model_card",
        description="Return the persisted model_card.md for a run.",
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

    if name == "list_runs":
        return _ok(discover_run_ids(runs_root))

    if name == "get_run_manifest":
        run_id = arguments.get("run_id", "")
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            return _error(f"manifest not found for run_id: {run_id}")
        return _ok(manifest)

    if name == "list_run_artifacts":
        run_id = arguments.get("run_id", "")
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            return _error(f"manifest not found for run_id: {run_id}")
        artifact_refs = manifest.get("artifact_refs") or []
        return _ok(
            [
                {
                    "artifact_id": ref.get("artifact_id"),
                    "artifact_type": ref.get("artifact_type"),
                    "relative_path": ref.get("relative_path"),
                    "content_hash": ref.get("content_hash"),
                    "origin": ref.get("origin"),
                }
                for ref in artifact_refs
            ]
        )

    if name == "get_artifact":
        run_id = arguments.get("run_id", "")
        artifact_type = arguments.get("artifact_type", "")
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            return _error(f"manifest not found for run_id: {run_id}")

        artifact_refs = manifest.get("artifact_refs") or []
        matching = [ref for ref in artifact_refs if ref.get("artifact_type") == artifact_type]
        if not matching:
            return _error(f"artifact_type '{artifact_type}' not found for run_id: {run_id}")

        filename = matching[0].get("relative_path")
        if not isinstance(filename, str):
            return _error(f"invalid relative_path for artifact_type '{artifact_type}'")

        run_path = safe_run_dir(runs_root, run_id)
        if run_path is None:
            return _error(f"run not found or unsafe: {run_id}")

        artifact_path = run_path / filename
        try:
            if not artifact_path.is_file():
                return _error(f"artifact file not found: {filename}")
            return _ok(json.loads(artifact_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            return _error(f"cannot read artifact {filename}: {exc}")

    if name == "read_model_card":
        run_id = arguments.get("run_id", "")
        card = load_text_artifact(runs_root, run_id, "model_card.md")
        if card is None:
            return _error(f"model_card not found for run_id: {run_id}")
        return _ok({"run_id": run_id, "model_card": card})

    return _error(f"unknown tool: {name}")


server = Server(
    "thelab-workspace",
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
