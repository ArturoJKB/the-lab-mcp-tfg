import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.mcp.common import discover_run_ids, safe_run_dir
from thelab.run.runner import run_model
from thelab.workspace import hash_file


def _completed_iris_run(tmp_path: Path) -> str:
    """Create a small completed Slice 1 run and return its run_id."""
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


def _rejected_run(tmp_path: Path) -> str:
    """Create a rejected run (missing target) and return its run_id."""
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
        "4.9,3.0,1.4,0.2,setosa\n"
    )
    result = run_model(
        dataset=csv,
        target="missing",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    return result["run_id"]


async def _call_tool(session: ClientSession, name: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(name, arguments or {})
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return json.loads(text)


async def _with_data_catalog_server(runs_root: Path, coro):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.data_catalog_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={"THELAB_RUNS_ROOT": str(runs_root), **dict(**__import__("os").environ)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


async def _with_model_registry_server(runs_root: Path, coro):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thelab.mcp.model_registry_mcp"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={"THELAB_RUNS_ROOT": str(runs_root), **dict(**__import__("os").environ)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await coro(session)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def test_safe_run_dir_rejects_traversal(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-good").mkdir()
    assert safe_run_dir(runs, "run-good") is not None
    assert safe_run_dir(runs, "../etc") is None
    assert safe_run_dir(runs, "run-good/..") is None
    assert safe_run_dir(runs, "missing") is None


def test_discover_run_ids_skips_unsafe_names(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-1").mkdir()
    (runs / "..escape").mkdir()
    ids = discover_run_ids(runs)
    assert ids == ["run-1"]


# ---------------------------------------------------------------------------
# Data catalog integration
# ---------------------------------------------------------------------------

def test_data_catalog_lists_dataset(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "list_datasets")
        assert result["ok"] is True
        datasets = result["data"]
        assert len(datasets) == 1
        assert datasets[0]["run_id"] == run_id
        assert datasets[0]["target"] == "species"
        assert datasets[0]["row_count"] == 11
        assert datasets[0]["column_count"] == 5
        return result

    asyncio.run(_with_data_catalog_server(runs_root, check))


def test_data_catalog_get_profile_and_contract(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        profile = await _call_tool(session, "get_data_profile", {"run_id": run_id})
        assert profile["ok"] is True
        assert profile["data"]["row_count"] == 11

        contract = await _call_tool(session, "get_dataset_contract", {"run_id": run_id})
        assert contract["ok"] is True
        assert contract["data"]["target_column"] == "species"
        return profile, contract

    asyncio.run(_with_data_catalog_server(runs_root, check))


def test_data_catalog_unknown_run_id(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    async def check(session: ClientSession):
        profile = await _call_tool(session, "get_data_profile", {"run_id": "does-not-exist"})
        assert profile["ok"] is False
        return profile

    asyncio.run(_with_data_catalog_server(runs_root, check))


# ---------------------------------------------------------------------------
# Model registry integration
# ---------------------------------------------------------------------------

def test_model_registry_lists_approved_models(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "list_models")
        assert result["ok"] is True
        models = result["data"]
        assert len(models) == 1
        assert models[0]["run_id"] == run_id
        assert models[0]["model"] == "logistic_regression"
        assert models[0]["metrics"]["test_accuracy"] is not None
        return result

    asyncio.run(_with_model_registry_server(runs_root, check))


def test_model_registry_excludes_rejected_runs(tmp_path: Path):
    _completed_iris_run(tmp_path)
    _rejected_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "list_models")
        assert result["ok"] is True
        models = result["data"]
        assert len(models) == 1
        return result

    asyncio.run(_with_model_registry_server(runs_root, check))


def test_model_registry_get_manifest_card_metrics(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        manifest = await _call_tool(session, "get_model_manifest", {"run_id": run_id})
        assert manifest["ok"] is True
        assert manifest["data"]["final_status"] == "completed"

        card = await _call_tool(session, "get_model_card", {"run_id": run_id})
        assert card["ok"] is True
        assert "Model Card" in card["data"]["model_card"]

        metrics = await _call_tool(session, "get_model_metrics", {"run_id": run_id})
        assert metrics["ok"] is True
        assert "test_accuracy" in metrics["data"]
        return manifest, card, metrics

    asyncio.run(_with_model_registry_server(runs_root, check))


def test_model_registry_unknown_run_id(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    async def check(session: ClientSession):
        manifest = await _call_tool(session, "get_model_manifest", {"run_id": "does-not-exist"})
        assert manifest["ok"] is False
        return manifest

    asyncio.run(_with_model_registry_server(runs_root, check))


def test_model_registry_predict_completed_run(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "predict",
            {
                "run_id": run_id,
                "features": [
                    {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
                ],
            },
        )
        assert result["ok"] is True
        assert result["data"]["run_id"] == run_id
        assert len(result["data"]["predictions"]) == 1
        assert result["data"]["predictions"][0] in {"setosa", "versicolor", "virginica"}
        return result

    asyncio.run(_with_model_registry_server(runs_root, check))


def test_model_registry_predict_rejects_rejected_run(tmp_path: Path):
    run_id = _rejected_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(
            session,
            "predict",
            {
                "run_id": run_id,
                "features": [[5.1, 3.5, 1.4, 0.2]],
            },
        )
        assert result["ok"] is False
        return result

    asyncio.run(_with_model_registry_server(runs_root, check))


def test_model_registry_path_traversal_attempt(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        result = await _call_tool(session, "get_model_manifest", {"run_id": f"{run_id}/../../etc"})
        assert result["ok"] is False
        return result

    asyncio.run(_with_model_registry_server(runs_root, check))


# ---------------------------------------------------------------------------
# Artifact hash integrity across MCP-exposed runs
# ---------------------------------------------------------------------------

def test_manifest_artifact_hashes_match_persisted_bytes_via_mcp(tmp_path: Path):
    run_id = _completed_iris_run(tmp_path)
    runs_root = tmp_path / "runs"

    async def check(session: ClientSession):
        manifest = await _call_tool(session, "get_model_manifest", {"run_id": run_id})
        assert manifest["ok"] is True
        run_dir = runs_root / run_id
        for ref in manifest["data"]["artifact_refs"]:
            rel_path = str(ref["relative_path"])
            artifact_path = run_dir / rel_path
            expected = ref["content_hash"]
            actual = hash_file(artifact_path)
            assert actual == expected, f"hash mismatch for {rel_path}"
        return manifest

    asyncio.run(_with_model_registry_server(runs_root, check))


# ---------------------------------------------------------------------------
# Demo client environment propagation
# ---------------------------------------------------------------------------

def _parse_demo_output(stdout: str) -> dict[str, dict]:
    """Extract JSON blocks printed by thelab-mcp-demo.

    Each block has the form ``label:\n{...}``.
    """
    blocks: dict[str, dict] = {}
    # Split on blank lines, then look for "label:\n{json}"
    for block in stdout.split("\n\n"):
        match = re.search(r"^(?P<label>[\w_]+(?:\([^)]*\))?):\n(?P<json>\{.*\})$", block, re.DOTALL)
        if match:
            blocks[match.group("label")] = json.loads(match.group("json"))
    return blocks


def test_demo_client_propagates_thelab_runs_root_to_child_server(tmp_path: Path):
    """Regression test: THELAB_RUNS_ROOT set on the demo client reaches the MCP server."""
    # Use a non-default runs root so we can prove the server did not fall back to runs/.
    custom_runs = tmp_path / "alternate-runs"
    default_runs = tmp_path / "runs"
    default_runs.mkdir()

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
        output="alternate-runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "completed"
    run_id = result["run_id"]

    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(custom_runs)

    proc = subprocess.run(
        [sys.executable, "-m", "thelab.mcp.demo_client", "data_catalog", "--run-id", run_id],
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=True,
    )

    blocks = _parse_demo_output(proc.stdout)

    list_datasets = blocks.get("list_datasets")
    assert list_datasets is not None, f"missing list_datasets output:\n{proc.stdout}"
    assert list_datasets["ok"] is True
    assert len(list_datasets["data"]) == 1
    assert list_datasets["data"][0]["run_id"] == run_id

    profile_label = f"get_data_profile({run_id})"
    profile = blocks.get(profile_label)
    assert profile is not None, f"missing profile output:\n{proc.stdout}"
    assert profile["ok"] is True
    assert profile["data"]["row_count"] == 11

    # Verify the server did not accidentally read the default runs/ directory.
    # The default directory is empty, so a fallback would have produced zero datasets.
    assert len(list_datasets["data"]) == 1
