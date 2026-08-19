#!/usr/bin/env python3
"""Thesis evaluation script for The Lab P0.

Runs automated checks for the three PRD research questions and prints a
structured pass/fail report. Exit code 0 means all required checks passed.

Usage:
    python scripts/evaluate_thesis.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.context.indexer import index_source_file
from thelab.context.reader import ContextReader
from thelab.context.repository import ContextRepository
from thelab.run.runner import run_model

_TOLERANCE = 1e-12


def _iris_csv(path: Path) -> Path:
    csv = path / "iris.csv"
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


def _metrics_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    for key in ("test_accuracy", "test_f1_macro"):
        if a.get(key) is None or b.get(key) is None:
            return False
        if abs(float(a[key]) - float(b[key])) > _TOLERANCE:
            return False
    return True


def _check_rq1_reproducibility(workspace: Path) -> dict[str, Any]:
    """RQ1: same dataset + config + seed -> comparable metrics."""
    csv = _iris_csv(workspace)
    runs_dir = workspace / "runs"

    result1 = run_model(
        dataset=csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=workspace,
    )
    result2 = run_model(
        dataset=csv,
        target="species",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=workspace,
    )

    if result1["status"] != "completed" or result2["status"] != "completed":
        return {
            "rq": "RQ1",
            "status": "FAIL",
            "reason": f"run statuses: {result1['status']}, {result2['status']}",
        }

    metrics1 = result1.get("metrics", {})
    metrics2 = result2.get("metrics", {})
    if not _metrics_equal(metrics1, metrics2):
        return {
            "rq": "RQ1",
            "status": "FAIL",
            "reason": f"metrics differ: {metrics1} vs {metrics2}",
        }

    manifest_path = runs_dir / result1["run_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("random_seed") != 42:
        return {"rq": "RQ1", "status": "FAIL", "reason": "manifest missing seed"}

    dep_versions = manifest.get("dependency_versions")
    if not isinstance(dep_versions, dict) or not dep_versions:
        return {
            "rq": "RQ1",
            "status": "FAIL",
            "reason": "manifest missing non-empty dependency_versions",
        }

    return {
        "rq": "RQ1",
        "status": "PASS",
        "run_ids": [result1["run_id"], result2["run_id"]],
        "metrics": {
            "test_accuracy": metrics1.get("test_accuracy"),
            "test_f1_macro": metrics1.get("test_f1_macro"),
        },
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


async def _with_model_registry(runs_root: Path, coro):
    repo_root = _repo_root()
    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    # Ensure the subprocess can import ``thelab`` even when the script is run
    # without an editable install.
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.model_registry_mcp"],
        cwd=str(repo_root),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


async def _check_rq2_mcp_interop(run_id: str, runs_root: Path) -> dict[str, Any]:
    """RQ2: independent MCP client discovers and predicts."""

    async def exercise(session: ClientSession) -> dict[str, Any]:
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        if "list_models" not in tool_names or "predict" not in tool_names:
            return {
                "rq": "RQ2",
                "status": "FAIL",
                "reason": f"missing tools: {tool_names}",
            }

        result = await session.call_tool("list_models", {})
        text = "".join(c.text for c in result.content if hasattr(c, "text"))
        payload = json.loads(text)
        if not payload.get("ok"):
            return {"rq": "RQ2", "status": "FAIL", "reason": "list_models returned ok=false"}
        models = payload.get("data", [])
        matching = [m for m in models if m.get("run_id") == run_id]
        if not matching:
            return {"rq": "RQ2", "status": "FAIL", "reason": "run_id not in list_models"}

        result = await session.call_tool(
            "predict",
            {
                "run_id": run_id,
                "features": [
                    {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
                ],
            },
        )
        text = "".join(c.text for c in result.content if hasattr(c, "text"))
        payload = json.loads(text)
        if not payload.get("ok"):
            return {"rq": "RQ2", "status": "FAIL", "reason": f"predict returned ok=false: {payload.get('error')}"}
        predictions = payload.get("data", {}).get("predictions")
        if not predictions or not isinstance(predictions, list):
            return {"rq": "RQ2", "status": "FAIL", "reason": "predict returned no predictions"}

        return {"rq": "RQ2", "status": "PASS", "predictions": predictions}

    return await _with_model_registry(runs_root, exercise)


def _check_rq3_context_retrieval(workspace: Path) -> dict[str, Any]:
    """RQ3: local context retrieval recovers useful run info."""
    db_path = workspace / "context.db"
    source = workspace / "agent-events.jsonl"
    source.write_text(
        json.dumps(
            {
                "event_id": "evt-repro",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-abc",
                "tags": ["repro", "decision"],
                "redacted_summary": "Reproducibility decision recorded",
                "privacy_level": "internal",
                "timestamp": "2026-08-09T12:00:00+00:00",
            }
        )
        + "\n"
    )
    repo = ContextRepository(db_path)
    index_source_file(source, repo)

    reader = ContextReader(db_path)
    if not reader.initialized:
        return {"rq": "RQ3", "status": "FAIL", "reason": "context reader not initialized"}

    before = db_path.read_bytes()
    results = reader.search("reproducibility", limit=10)
    after = db_path.read_bytes()
    if before != after:
        return {"rq": "RQ3", "status": "FAIL", "reason": "search modified the database"}

    if not results:
        return {"rq": "RQ3", "status": "FAIL", "reason": "search returned no results"}

    entry = results[0]
    if not entry.redacted_summary or "Reproducibility" not in entry.redacted_summary:
        return {"rq": "RQ3", "status": "FAIL", "reason": "unexpected summary in search result"}

    return {
        "rq": "RQ3",
        "status": "PASS",
        "hits": len(results),
        "event_id": entry.event_id,
    }


def _print_report(report: dict[str, Any]) -> None:
    print("=" * 60)
    print("The Lab P0 — Thesis Evaluation Report")
    print("=" * 60)
    overall = "PASS" if all(r["status"] == "PASS" for r in report["results"]) else "FAIL"
    print(f"Overall: {overall}")
    print()
    for result in report["results"]:
        print(f"{result['rq']}: {result['status']}")
        if result["status"] != "PASS":
            print(f"  Reason: {result.get('reason', 'unknown')}")
        else:
            for key, value in result.items():
                if key in ("rq", "status"):
                    continue
                print(f"  {key}: {value}")
    print()
    print(json.dumps(report, indent=2))


async def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="thelab-eval-"))
    try:
        rq1 = _check_rq1_reproducibility(workspace)
        runs_root = workspace / "runs"

        # Use the first completed run from RQ1 for the MCP interoperability check.
        run_id = rq1.get("run_ids", [None])[0]
        if run_id is None:
            rq2 = {"rq": "RQ2", "status": "FAIL", "reason": "no run available from RQ1"}
        else:
            rq2 = await _check_rq2_mcp_interop(run_id, runs_root)

        rq3 = _check_rq3_context_retrieval(workspace)

        report = {"results": [rq1, rq2, rq3]}
        _print_report(report)
        return 0 if all(r["status"] == "PASS" for r in report["results"]) else 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
