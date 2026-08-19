"""Interactive/headless MCP demo client for The Lab.

Usage:
    thelab-mcp-demo data_catalog --run-id <run_id>
    thelab-mcp-demo model_registry [--run-id <run_id>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="thelab-mcp-demo",
        description="Demo client for The Lab MCP servers.",
    )
    parser.add_argument(
        "server",
        choices=["data_catalog", "model_registry", "workspace", "context"],
        help="Which MCP server to exercise.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run ID to query (required for data_catalog and workspace, optional for model_registry).",
    )
    parser.add_argument(
        "--predict",
        action="store_true",
        help="Also exercise the predict tool (model_registry only).",
    )
    parser.add_argument(
        "--context-db",
        default=None,
        help="Path to the context database (context server only). Propagated via THELAB_CONTEXT_DB.",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="Optional: server command override (defaults to thelab-<server>-mcp).",
    )
    return parser.parse_args(argv)


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    result = await session.call_tool(name, arguments=arguments)
    text = "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))
    return json.loads(text)


async def _run_data_catalog(run_id: str, command: str | None) -> None:
    cmd = command or sys.executable
    args = [] if command else ["-m", "thelab.mcp.data_catalog_mcp"]
    params = StdioServerParameters(command=cmd, args=args, env=dict(os.environ))
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Connected to data catalog server. Tools: {[t.name for t in tools.tools]}")

            datasets = await _call_tool(session, "list_datasets", {})
            print(f"\nlist_datasets:\n{json.dumps(datasets, indent=2)}")

            profile = await _call_tool(session, "get_data_profile", {"run_id": run_id})
            print(f"\nget_data_profile({run_id}):\n{json.dumps(profile, indent=2)}")

            contract = await _call_tool(session, "get_dataset_contract", {"run_id": run_id})
            print(f"\nget_dataset_contract({run_id}):\n{json.dumps(contract, indent=2)}")


async def _run_model_registry(run_id: str | None, command: str | None, exercise_predict: bool) -> None:
    cmd = command or sys.executable
    args = [] if command else ["-m", "thelab.mcp.model_registry_mcp"]
    params = StdioServerParameters(command=cmd, args=args, env=dict(os.environ))
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Connected to model registry server. Tools: {[t.name for t in tools.tools]}")

            models = await _call_tool(session, "list_models", {})
            print(f"\nlist_models:\n{json.dumps(models, indent=2)}")

            if run_id is None and models.get("ok") and models.get("data"):
                run_id = models["data"][0]["run_id"]
                print(f"\nAuto-selected run_id: {run_id}")

            if run_id:
                manifest = await _call_tool(session, "get_model_manifest", {"run_id": run_id})
                print(f"\nget_model_manifest({run_id}):\n{json.dumps(manifest, indent=2)}")

                metrics = await _call_tool(session, "get_model_metrics", {"run_id": run_id})
                print(f"\nget_model_metrics({run_id}):\n{json.dumps(metrics, indent=2)}")

                card = await _call_tool(session, "get_model_card", {"run_id": run_id})
                print(f"\nget_model_card({run_id}):\n{json.dumps(card, indent=2)}")

                if exercise_predict:
                    prediction = await _call_tool(
                        session,
                        "predict",
                        {
                            "run_id": run_id,
                            "features": [
                                {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
                            ],
                        },
                    )
                    print(f"\npredict({run_id}):\n{json.dumps(prediction, indent=2)}")


async def _run_workspace(run_id: str, command: str | None) -> None:
    cmd = command or sys.executable
    args = [] if command else ["-m", "thelab.mcp.workspace_mcp"]
    params = StdioServerParameters(command=cmd, args=args, env=dict(os.environ))
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Connected to workspace server. Tools: {[t.name for t in tools.tools]}")

            runs = await _call_tool(session, "list_runs", {})
            print(f"\nlist_runs:\n{json.dumps(runs, indent=2)}")

            manifest = await _call_tool(session, "get_run_manifest", {"run_id": run_id})
            print(f"\nget_run_manifest({run_id}):\n{json.dumps(manifest, indent=2)}")

            artifacts = await _call_tool(session, "list_run_artifacts", {"run_id": run_id})
            print(f"\nlist_run_artifacts({run_id}):\n{json.dumps(artifacts, indent=2)}")

            card = await _call_tool(session, "read_model_card", {"run_id": run_id})
            print(f"\nread_model_card({run_id}):\n{json.dumps(card, indent=2)}")


async def _run_context(command: str | None, context_db: str | None) -> None:
    cmd = command or sys.executable
    args = [] if command else ["-m", "thelab.mcp.context_mcp"]
    env = dict(os.environ)
    if context_db:
        env["THELAB_CONTEXT_DB"] = context_db
    params = StdioServerParameters(command=cmd, args=args, env=env)
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Connected to context server. Tools: {[t.name for t in tools.tools]}")

            status = await _call_tool(session, "get_context_status", {})
            print(f"\nget_context_status:\n{json.dumps(status, indent=2)}")

            search = await _call_tool(session, "search_context", {"query": "Demo", "limit": 5})
            print(f"\nsearch_context('Demo'):\n{json.dumps(search, indent=2)}")

            if search.get("ok") and search.get("data"):
                event_id = search["data"][0]["event_id"]
                entry = await _call_tool(session, "get_context_entry", {"event_id": event_id})
                print(f"\nget_context_entry({event_id}):\n{json.dumps(entry, indent=2)}")


async def main() -> None:
    args = _parse_args()
    if args.server in {"data_catalog", "workspace"} and not args.run_id:
        print(f"error: --run-id is required for {args.server}", file=sys.stderr)
        sys.exit(2)
    if args.server == "data_catalog":
        await _run_data_catalog(args.run_id, args.command)
    elif args.server == "workspace":
        await _run_workspace(args.run_id, args.command)
    elif args.server == "context":
        await _run_context(args.command, args.context_db)
    else:
        await _run_model_registry(args.run_id, args.command, args.predict)


def main_sync() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
