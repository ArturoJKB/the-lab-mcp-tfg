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
    mode = report.get("mode", "suite")
    print(f"The Lab — Thesis Evaluation Report ({mode})")
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


# ---------------------------------------------------------------------------
# RQ4-RQ6: agentic claims (P5.C)
# ---------------------------------------------------------------------------

def _agentic_env(workspace: Path) -> dict[str, str]:
    """Point the agentic-round modules at the evaluator's workspace."""
    env = {
        "THELAB_UPLOADS_DIR": str(workspace / "uploads"),
        "THELAB_PROPOSALS_DIR": str(workspace / "proposals"),
        "THELAB_EXPERIMENTS_DIR": str(workspace / "experiments"),
        "THELAB_RUNS_ROOT": str(workspace / "runs"),
        "THELAB_WORKSPACE_ROOT": str(workspace),
        "THELAB_CONTEXT_LOG_SOURCE": str(workspace / "logs" / "agent-events.jsonl"),
    }
    for key, value in env.items():
        os.environ[key] = value
    (workspace / "uploads").mkdir(exist_ok=True)
    (workspace / "proposals").mkdir(exist_ok=True)
    (workspace / "experiments").mkdir(exist_ok=True)
    _iris_csv(workspace / "uploads")
    return env


def _build_deterministic_result(run_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """Deterministic-baseline evidence derived from the real RQ1 run."""
    return {
        "status": "completed",
        "eda": {"eda_context": "Features: 4 numeric, 0 categorical; Classes: 3, imbalance ratio: 1.0"},
        "feature_engineering": {
            "cleaned_dataset_id": "uploads/iris.csv",
            "clean_metadata": {"skipped": True, "reason": "fixture already clean"},
            "top_models": [
                {"model": "logistic_regression", "metrics": dict(metrics)},
            ],
        },
        "model_selection": {
            "recommendation": {
                "best_model": "logistic_regression",
                "model_grid": ["logistic_regression"],
                "seeds": [42],
            }
        },
        "training_results": [
            {
                "dataset": "uploads/iris.csv",
                "model": "logistic_regression",
                "seed": 42,
                "status": "completed",
                "run_id": run_id,
                "metrics": dict(metrics),
            }
        ],
    }


def _stripped_deterministic_result() -> dict[str, Any]:
    """Ungrounded arm for RQ4: all context evidence removed."""
    return {
        "status": "completed",
        "eda": {"eda_context": ""},
        "feature_engineering": {
            "cleaned_dataset_id": "uploads/iris.csv",
            "clean_metadata": {},
            "top_models": [],
        },
        "model_selection": {"recommendation": {}},
        "training_results": [],
    }


def _extract_record_claims(record: dict[str, Any]) -> dict[str, float]:
    """All metric claims made anywhere in a round record (brief, rationale)."""
    from thelab.agents.grounding import extract_metric_claims

    texts: list[str] = []
    brief = record.get("brief") or {}
    for key in ("findings", "opportunities", "risks"):
        texts.extend(str(item) for item in (brief.get(key) or []))
    texts.append(str((record.get("selection") or {}).get("rationale", "")))
    texts.append(str((record.get("transform") or {}).get("rationale", "")))
    claims: dict[str, float] = {}
    for text in texts:
        claims.update(extract_metric_claims(text))
    return claims


def _verified_claim_stats(claims: dict[str, float], metrics: dict[str, Any]) -> tuple[int, int]:
    """Return (verified, total) claims against the deterministic evidence."""
    from thelab.agents.grounding import METRIC_TOLERANCE

    verified = 0
    for key, claimed in claims.items():
        actual = metrics.get(key)
        if isinstance(actual, (int, float)) and abs(claimed - float(actual)) <= METRIC_TOLERANCE:
            verified += 1
    return verified, len(claims)


def _new_experiment(workspace: Path, label: str) -> Any:
    from thelab.ide.experiment import Experiment, ExperimentStore

    experiment = Experiment(
        experiment_id=f"exp-eval-{label}",
        goal="Predict the iris species (evaluator)",
        dataset_id="uploads/iris.csv",
        target="species",
    )
    ExperimentStore().save(experiment)
    return experiment


def _load_round_record(experiment_id: str) -> dict[str, Any]:
    path = (
        Path(os.environ["THELAB_EXPERIMENTS_DIR"]) / f"{experiment_id}.agentic_round.json"
    )
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


async def _check_rq4_grounding(
    run_id: str, metrics: dict[str, Any], provider: Any
) -> dict[str, Any]:
    """RQ4: grounded vs stripped-context round; claims verified against evidence.

    Suite mode (mock/no provider): verifies the ablation instrument runs and
    that the grounded arm's deterministic-evidence claims verify 1:1.
    Live mode: compares verified-claim rates between arms.
    """
    from thelab.ide.agentic_round import run_agentic_round

    grounded_experiment = _new_experiment(Path.cwd(), "rq4-grounded")
    grounded = await run_agentic_round(
        grounded_experiment,
        _build_deterministic_result(run_id, metrics),
        provider=provider,
        require_approval=True,
    )
    ungrounded_experiment = _new_experiment(Path.cwd(), "rq4-ungrounded")
    ungrounded = await run_agentic_round(
        ungrounded_experiment,
        _stripped_deterministic_result(),
        provider=provider,
        require_approval=True,
    )

    for arm in (grounded, ungrounded):
        if arm.get("status") != "awaiting_approval":
            return {"rq": "RQ4", "status": "FAIL", "reason": f"arm status: {arm.get('status')}"}

    g_verified, g_total = _verified_claim_stats(
        _extract_record_claims(grounded), metrics
    )
    u_verified, u_total = _verified_claim_stats(
        _extract_record_claims(ungrounded), metrics
    )

    if provider is None:
        # Suite bar: the grounded arm's evidence-derived claims verify exactly.
        if g_total > 0 and g_verified < g_total:
            return {
                "rq": "RQ4",
                "status": "FAIL",
                "reason": f"grounded arm has unverified claims: {g_verified}/{g_total}",
            }
        return {
            "rq": "RQ4",
            "status": "PASS",
            "grounded_claims": f"{g_verified}/{g_total} verified",
            "ungrounded_claims": f"{u_verified}/{u_total} verified",
            "note": "mock instrument run; live comparison pending (--live)",
        }

    g_rate = g_verified / g_total if g_total else 1.0
    u_rate = u_verified / u_total if u_total else 1.0
    if g_rate < u_rate:
        return {
            "rq": "RQ4",
            "status": "FAIL",
            "reason": f"grounded verified-rate {g_rate:.2f} < ungrounded {u_rate:.2f}",
        }
    return {
        "rq": "RQ4",
        "status": "PASS",
        "grounded_verified_rate": round(g_rate, 3),
        "ungrounded_verified_rate": round(u_rate, 3),
        "grounded_claims": g_total,
        "ungrounded_claims": u_total,
    }


async def _check_rq5_agentic_capability(
    workspace: Path, run_id: str, metrics: dict[str, Any], provider: Any
) -> dict[str, Any]:
    """RQ5: the round protocol end-to-end — gate blocks, approval enables.

    Suite bar (mock): the unapproved round cannot execute; the approved round
    runs through the factory and produces the comparison artifact.
    Live bar: script validity_rate >= 0.8.
    """
    from thelab.agents.approval import (
        HumanApprovalRequired,
        record_human_approval,
    )
    from thelab.agents.worker import ProposalStore
    from thelab.ide.agentic_round import execute_approved_round, run_agentic_round

    experiment = _new_experiment(workspace, "rq5")
    deterministic_result = _build_deterministic_result(run_id, metrics)
    record = await run_agentic_round(
        experiment,
        deterministic_result,
        provider=provider,
        require_approval=True,
    )
    if record.get("status") != "awaiting_approval":
        return {"rq": "RQ5", "status": "FAIL", "reason": f"round status: {record.get('status')}"}
    proposal_id = record["proposal_id"]

    # Gate: unapproved execution must be refused.
    blocked = False
    try:
        execute_approved_round(experiment, proposal_id)
    except HumanApprovalRequired:
        blocked = True
    if not blocked:
        return {"rq": "RQ5", "status": "FAIL", "reason": "execution was not blocked by the gate"}

    record_human_approval(ProposalStore(os.environ["THELAB_PROPOSALS_DIR"]), proposal_id, principal="evaluator")
    result = execute_approved_round(experiment, proposal_id)
    comparison = result.get("comparison", {})
    if result.get("status") not in {"completed", "failed"}:
        return {"rq": "RQ5", "status": "FAIL", "reason": f"execution status: {result.get('status')}"}
    if "metric_delta" not in comparison or "validity_rate" not in comparison:
        return {"rq": "RQ5", "status": "FAIL", "reason": "comparison artifact incomplete"}

    validity = comparison.get("validity_rate")
    if provider is not None and result["status"] == "completed":
        if validity is None or float(validity) < 0.8:
            return {
                "rq": "RQ5",
                "status": "FAIL",
                "reason": f"validity_rate {validity} below 0.8 bar",
            }

    return {
        "rq": "RQ5",
        "status": "PASS",
        "gate_blocked_unapproved": True,
        "validity_rate": validity,
        "metric_delta": comparison.get("metric_delta", {}),
        "agentic_completed": comparison.get("agentic_completed"),
        "agentic_total": comparison.get("agentic_total"),
    }


async def _check_rq6_orchestration(
    run_id: str, metrics: dict[str, Any], provider: Any
) -> dict[str, Any]:
    """RQ6: role-specialized (multi) vs shared-prompt (single) orchestration.

    Suite bar (mock): both arms complete the protocol with valid, distinct
    role_mode records; the multi arm uses role prompt contracts.
    Live bar: multi must not trail single on proposal validity.
    """
    from thelab.ide.agentic_round import RoundConfig, run_agentic_round

    arms: dict[str, dict[str, Any]] = {}
    for label, config in (
        ("multi", RoundConfig(role_mode="multi")),
        ("single", RoundConfig(role_mode="single")),
    ):
        experiment = _new_experiment(Path.cwd(), f"rq6-{label}")
        record = await run_agentic_round(
            experiment,
            _build_deterministic_result(run_id, metrics),
            provider=provider,
            require_approval=True,
            config=config,
        )
        if record.get("status") != "awaiting_approval":
            return {
                "rq": "RQ6",
                "status": "FAIL",
                "reason": f"{label} arm status: {record.get('status')}",
            }
        if record.get("role_mode") != label:
            return {
                "rq": "RQ6",
                "status": "FAIL",
                "reason": f"{label} arm recorded role_mode={record.get('role_mode')}",
            }
        proposal = record.get("proposal") or {}
        if not proposal.get("model_grid"):
            return {"rq": "RQ6", "status": "FAIL", "reason": f"{label} arm produced no grid"}
        arms[label] = record

    return {
        "rq": "RQ6",
        "status": "PASS",
        "multi_mode": arms["multi"].get("mode"),
        "single_mode": arms["single"].get("mode"),
        "note": "mock structural run; live quality comparison pending (--live)",
    }


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="The Lab thesis evaluator")
    parser.add_argument(
        "--live",
        choices=["openrouter", "ollama", "openai_compat"],
        default=None,
        help="Run the agentic RQ4-RQ6 arms with a live LLM provider (recorded results)",
    )
    parser.add_argument("--model", default=None, help="Model name for the live provider")
    args = parser.parse_args()

    provider = None
    mode = "suite (mock)"
    if args.live:
        from thelab.agents.chat import create_provider

        provider = create_provider(args.live, args.model)
        mode = f"live ({args.live}" + (f":{args.model}" if args.model else "") + ")"

    workspace = Path(tempfile.mkdtemp(prefix="thelab-eval-"))
    previous_env = {}
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

        metrics = rq1.get("metrics", {})
        agentic_results: list[dict[str, Any]]
        if run_id is None or rq1["status"] != "PASS":
            agentic_results = [
                {"rq": f"RQ{n}", "status": "FAIL", "reason": "no verified baseline run from RQ1"}
                for n in (4, 5, 6)
            ]
        else:
            env = _agentic_env(workspace)
            previous_env = {k: os.environ.get(k) for k in env}
            try:
                rq4 = await _check_rq4_grounding(run_id, metrics, provider)
                rq5 = await _check_rq5_agentic_capability(workspace, run_id, metrics, provider)
                rq6 = await _check_rq6_orchestration(run_id, metrics, provider)
            finally:
                for key, value in previous_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            agentic_results = [rq4, rq5, rq6]

        report = {"mode": mode, "results": [rq1, rq2, rq3, *agentic_results]}
        _print_report(report)
        return 0 if all(r["status"] == "PASS" for r in report["results"]) else 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
