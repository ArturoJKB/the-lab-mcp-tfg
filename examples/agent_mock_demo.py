"""Offline L1 demo: train a run, then run the mock agent harness over MCP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thelab.agents import AgentHarness, MockProvider, ServerConnection
from thelab.run.runner import run_model


def _train_run(workspace: Path) -> str:
    csv = workspace / "iris.csv"
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
        workspace_root=workspace,
    )
    assert result["status"] == "completed", result.get("error")
    return result["run_id"]


async def _connect_server(stack: AsyncExitStack, name: str, module: str, runs_root: Path):
    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return ServerConnection(name=name, session=session)


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        runs_root = workspace / "runs"
        run_id = _train_run(workspace)
        metrics = json.loads((runs_root / run_id / "metrics.json").read_text())

        script = [
            {"tool_calls": [{"tool": "list_models", "arguments": {}}]},
            {"tool_calls": [{"tool": "get_model_metrics", "arguments": {"run_id": run_id}}]},
            f"Run {run_id} has test_accuracy {metrics['test_accuracy']}.",
        ]

        async with AsyncExitStack() as stack:
            servers = [
                await _connect_server(stack, "model_registry", "thelab.mcp.model_registry_mcp", runs_root),
                await _connect_server(stack, "workspace", "thelab.mcp.workspace_mcp", runs_root),
            ]
            harness = AgentHarness(
                provider=MockProvider(script),
                servers=servers,
                runs_root=runs_root,
                max_steps=5,
            )
            result = await harness.run("summarize the latest model")

        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
