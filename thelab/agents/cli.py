"""Entry point: ``thelab-agent "goal" --provider mock``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .harness import AgentHarness, ApprovalRequiredError, ServerConnection
from .mock import MockProvider, load_script
from .provider import LLMProvider
from .providers import OpenAICompatProvider

_SERVER_MODULES = {
    "data_catalog": "thelab.mcp.data_catalog_mcp",
    "model_registry": "thelab.mcp.model_registry_mcp",
    "workspace": "thelab.mcp.workspace_mcp",
    "context": "thelab.mcp.context_mcp",
}


async def _connect_server(
    stack: AsyncExitStack,
    name: str,
    runs_root: Path,
) -> ServerConnection:
    """Spawn one stdio MCP server and return a named connection."""
    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", _SERVER_MODULES[name]],
        env=env,
    )
    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()
    return ServerConnection(name=name, session=session)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thelab-agent",
        description="The Lab — local agent harness over read-only MCP servers.",
    )
    parser.add_argument("goal", help="User goal for the agent")
    parser.add_argument(
        "--provider",
        choices=["mock", "openai_compat"],
        default="mock",
        help="LLM provider backend (default: mock)",
    )
    parser.add_argument(
        "--mock-script",
        help="JSON script for the mock provider (required for non-trivial mock runs)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum provider turns (default: 8)",
    )
    parser.add_argument(
        "--runs-root",
        default=None,
        help="Workspace runs directory (default: THELAB_RUNS_ROOT or ./runs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON outcome instead of human-readable text",
    )
    return parser


def _create_provider(args: argparse.Namespace) -> LLMProvider:
    """Instantiate the selected provider from CLI arguments."""
    if args.provider == "mock":
        script: list[str | dict[str, Any]] = []
        if args.mock_script:
            script = load_script(args.mock_script)
        return MockProvider(script)
    if args.provider == "openai_compat":
        return OpenAICompatProvider()
    raise ValueError(
        f"unsupported provider: {args.provider}. Supported: mock, openai_compat"
    )


async def _run(args: argparse.Namespace) -> int:
    """Run the harness and return a process exit code."""
    runs_root = (
        Path(args.runs_root)
        if args.runs_root
        else Path(os.environ.get("THELAB_RUNS_ROOT", "runs"))
    )
    provider = _create_provider(args)

    async with AsyncExitStack() as stack:
        connections: list[ServerConnection] = []
        for name in _SERVER_MODULES:
            connections.append(await _connect_server(stack, name, runs_root))

        harness = AgentHarness(
            provider=provider,
            servers=connections,
            runs_root=runs_root,
            max_steps=args.max_steps,
        )
        result = await harness.run(args.goal)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if result.get("status") == "success":
            print(result["answer"])
        else:
            print(
                f"Refused: {result.get('reason')} — {result.get('message')}",
                file=sys.stderr,
            )

    return 0 if result.get("status") == "success" else 1


def _emit_approval(exc: ApprovalRequiredError, json_output: bool) -> int:
    if json_output:
        print(
            json.dumps(
                {
                    "status": "approval_required",
                    "tool": exc.tool,
                    "arguments": exc.arguments,
                    "request_path": str(exc.request_path),
                },
                indent=2,
                default=str,
            )
        )
    else:
        print(f"Approval required: {exc}", file=sys.stderr)
    return 2


def _find_approval_error(exc: BaseException) -> ApprovalRequiredError | None:
    """Recursively search nested exception groups for ApprovalRequiredError."""
    if isinstance(exc, ApprovalRequiredError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = _find_approval_error(child)
            if found is not None:
                return found
    return None


def _print_exception_group(eg: BaseExceptionGroup) -> None:
    """Flatten and print every leaf exception in a group."""
    for exc in eg.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            _print_exception_group(exc)
        else:
            print(f"Error: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except ApprovalRequiredError as exc:
        return _emit_approval(exc, args.json)
    except BaseExceptionGroup as eg:
        approval = _find_approval_error(eg)
        if approval is not None:
            return _emit_approval(approval, args.json)
        _print_exception_group(eg)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
