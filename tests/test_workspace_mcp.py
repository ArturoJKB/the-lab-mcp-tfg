import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.run.runner import run_model


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


async def _call_tool(session: ClientSession, name: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(name, arguments or {})
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return json.loads(text)


async def _with_workspace_server(runs_root: Path, coro):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.workspace_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={"THELAB_RUNS_ROOT": str(runs_root), **dict(**__import__("os").environ)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


def test_workspace_lists_runs(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "list_runs")
        assert result["ok"] is True
        assert run_id in result["data"]
        return result

    asyncio.run(_with_workspace_server(runs_root, check))


def test_workspace_get_run_manifest(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_run_manifest", {"run_id": run_id})
        assert result["ok"] is True
        assert result["data"]["run_id"] == run_id
        assert result["data"]["final_status"] == "completed"
        return result

    asyncio.run(_with_workspace_server(runs_root, check))


def test_workspace_list_run_artifacts(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "list_run_artifacts", {"run_id": run_id})
        assert result["ok"] is True
        artifact_types = {ref["artifact_type"] for ref in result["data"]}
        assert "model" in artifact_types
        assert "metrics" in artifact_types
        assert "model_card" in artifact_types
        return result

    asyncio.run(_with_workspace_server(runs_root, check))


def test_workspace_get_artifact(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_artifact", {"run_id": run_id, "artifact_type": "metrics"})
        assert result["ok"] is True
        assert "test_accuracy" in result["data"]
        return result

    asyncio.run(_with_workspace_server(runs_root, check))


def test_workspace_read_model_card(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "read_model_card", {"run_id": run_id})
        assert result["ok"] is True
        assert "Model Card" in result["data"]["model_card"]
        return result

    asyncio.run(_with_workspace_server(runs_root, check))


def test_workspace_unknown_run_id(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_run_manifest", {"run_id": "does-not-exist"})
        assert result["ok"] is False
        return result

    asyncio.run(_with_workspace_server(runs_root, check))


def test_workspace_unknown_artifact_type(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_artifact", {"run_id": run_id, "artifact_type": "nope"})
        assert result["ok"] is False
        return result

    asyncio.run(_with_workspace_server(runs_root, check))
