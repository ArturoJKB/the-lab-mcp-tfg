"""Integration tests for the EDA MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _with_eda_server(runs_root: Path, coro):
    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.eda_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


async def _call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return json.loads(text)


@pytest.fixture
def iris_csv(tmp_path: Path) -> Path:
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
    return csv


def test_eda_mcp_discovers_tools(tmp_path: Path):
    runs_root = tmp_path

    async def check(session: ClientSession):
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {
            "missing_profile",
            "correlation_hints",
            "class_balance",
            "outlier_scan",
            "leakage_suspects",
            "feature_types",
        }

    asyncio.run(_with_eda_server(runs_root, check))


def test_eda_mcp_missing_profile(tmp_path: Path, iris_csv: Path):
    runs_root = tmp_path

    async def check(session: ClientSession):
        result = await _call_tool(session, "missing_profile", {"dataset": "iris.csv"})
        assert result["ok"] is True
        assert result["data"]["total_rows"] == 11

    asyncio.run(_with_eda_server(runs_root, check))


def test_eda_mcp_class_balance(tmp_path: Path, iris_csv: Path):
    runs_root = tmp_path

    async def check(session: ClientSession):
        result = await _call_tool(
            session, "class_balance", {"dataset": "iris.csv", "target": "species"}
        )
        assert result["ok"] is True
        classes = {c["class"]: c["count"] for c in result["data"]["classes"]}
        assert classes["virginica"] == 5

    asyncio.run(_with_eda_server(runs_root, check))


def test_eda_mcp_correlation_hints(tmp_path: Path, iris_csv: Path):
    runs_root = tmp_path

    async def check(session: ClientSession):
        result = await _call_tool(
            session, "correlation_hints", {"dataset": "iris.csv", "target": "petal_width"}
        )
        assert result["ok"] is True
        assert result["data"]["top_correlations"]

    asyncio.run(_with_eda_server(runs_root, check))


def test_eda_mcp_rejects_absolute_path(tmp_path: Path, iris_csv: Path):
    runs_root = tmp_path

    async def check(session: ClientSession):
        result = await _call_tool(session, "missing_profile", {"dataset": str(iris_csv.resolve())})
        assert result["ok"] is False

    asyncio.run(_with_eda_server(runs_root, check))


def test_eda_mcp_rejects_parent_traversal(tmp_path: Path, iris_csv: Path):
    runs_root = tmp_path

    async def check(session: ClientSession):
        result = await _call_tool(session, "missing_profile", {"dataset": "../iris.csv"})
        assert result["ok"] is False

    asyncio.run(_with_eda_server(runs_root, check))
