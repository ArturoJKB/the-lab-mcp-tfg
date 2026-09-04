#!/usr/bin/env python3
"""Thesis evaluation script for The Lab.

Runs automated checks for the six research questions over a small dataset
matrix (iris classification + deterministic synthetic regression) and prints a
structured pass/fail report. Exit code 0 means all required checks passed.

Usage:
    python scripts/evaluate_thesis.py                 # suite mode (mock)
    python scripts/evaluate_thesis.py --live openrouter --model <id>
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from thelab.context.indexer import index_source_file
from thelab.context.reader import ContextReader
from thelab.context.repository import ContextRepository
from thelab.run.runner import run_model

_TOLERANCE = 1e-12


@dataclass(frozen=True)
class DatasetSpec:
    """One arm of the evaluator's dataset matrix."""

    name: str
    target: str
    task: str  # classification | regression
    model: str
    metric_keys: list[str]  # RQ1 comparison keys
    predict_row: dict[str, float]
    recommendation_grid: list[str] = field(default_factory=list)

    def label(self, rq: str) -> str:
        return f"{rq}[{self.name}]"


def _churn_spec() -> DatasetSpec:
    """Real-data arm (W3): bank-customer churn, 10k rows, 16 cleaned features.

    Uses the repo-local cleaned upload (gitignored). The arm is SKIPPED when
    the file is absent so fresh clones keep the evaluator green.
    """
    return DatasetSpec(
        name="churn",
        target="Exited",
        task="classification",
        model="logistic_regression",
        metric_keys=["test_accuracy", "test_f1_macro"],
        predict_row={
            "RowNumber": 1,
            "CustomerId": 15634602,
            "CreditScore": 650,
            "Age": 45,
            "Tenure": 3,
            "Balance": 80000.0,
            "NumOfProducts": 1,
            "HasCrCard": 1,
            "IsActiveMember": 1,
            "EstimatedSalary": 50000.0,
            "Geography_France": 1,
            "Geography_Germany": 0,
            "Geography_Spain": 0,
            "Gender_Female": 0,
            "Gender_Male": 1,
            "Surname_frequency": 0.05,
        },
        recommendation_grid=["logistic_regression"],
    )


def _churn_source() -> Path | None:
    """Locate the repo-local cleaned churn upload; None when absent."""
    candidates = [
        Path("data/uploads/shrutimechlearn_churn-modelling_cleaned.csv"),
        Path(__file__).resolve().parent.parent
        / "data"
        / "uploads"
        / "shrutimechlearn_churn-modelling_cleaned.csv",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _iris_spec() -> DatasetSpec:
    return DatasetSpec(
        name="iris",
        target="species",
        task="classification",
        model="logistic_regression",
        metric_keys=["test_accuracy", "test_f1_macro"],
        predict_row={
            "sepal_length": 5.1,
            "sepal_width": 3.5,
            "petal_length": 1.4,
            "petal_width": 0.2,
        },
        recommendation_grid=["logistic_regression"],
    )


def _housing_spec() -> DatasetSpec:
    return DatasetSpec(
        name="housing",
        target="median_house_value",
        task="regression",
        model="ridge",
        metric_keys=["test_rmse", "test_r2"],
        predict_row={
            "median_income": 5.0,
            "avg_rooms": 4.5,
            "housing_age": 20.0,
            "avg_occupancy": 3.0,
        },
        recommendation_grid=["ridge"],
    )


def _churn_csv(path: Path) -> Path:
    """Hermetic copy of the repo-local cleaned churn upload (10k rows)."""
    import shutil

    csv = path / "churn.csv"
    source = _churn_source()
    if source is None:
        raise FileNotFoundError("cleaned churn upload not present in the repo")
    shutil.copyfile(source, csv)
    return csv


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


def _housing_csv(path: Path) -> Path:
    """Deterministic synthetic regression dataset (housing-shaped).

    Seeded generator: price is a linear function of the features plus noise,
    so RQ1's determinism check is meaningful and ridge reaches a solid R2.
    """
    import numpy as np

    rng = np.random.RandomState(42)
    n = 4000
    income = rng.uniform(0.5, 15.0, n)
    rooms = rng.uniform(1.0, 9.0, n)
    age = rng.uniform(1.0, 52.0, n)
    occupancy = rng.uniform(0.5, 6.0, n)
    price = (
        45_000.0
        + 32_000.0 * income
        + 8_500.0 * rooms
        - 900.0 * age
        + 1_200.0 * occupancy
        + rng.normal(0.0, 12_000.0, n)
    )
    lines = ["median_income,avg_rooms,housing_age,avg_occupancy,median_house_value"]
    for i in range(n):
        lines.append(
            f"{income[i]:.4f},{rooms[i]:.3f},{age[i]:.1f},{occupancy[i]:.3f},{price[i]:.2f}"
        )
    csv = path / "housing.csv"
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv


def _dataset_csv(workspace: Path, spec: DatasetSpec) -> Path:
    builders = {"iris": _iris_csv, "housing": _housing_csv, "churn": _churn_csv}
    return builders[spec.name](workspace / "uploads")


def _metrics_equal(a: dict[str, Any], b: dict[str, Any], keys: list[str]) -> bool:
    for key in keys:
        if a.get(key) is None or b.get(key) is None:
            return False
        if abs(float(a[key]) - float(b[key])) > _TOLERANCE:
            return False
    return True


def _check_rq1_reproducibility(workspace: Path, spec: DatasetSpec) -> dict[str, Any]:
    """RQ1: same dataset + config + seed -> comparable metrics."""
    csv = _dataset_csv(workspace, spec)
    runs_dir = workspace / "runs"

    result1 = run_model(
        dataset=csv,
        target=spec.target,
        model=spec.model,
        seed=42,
        output="runs",
        workspace_root=workspace,
    )
    result2 = run_model(
        dataset=csv,
        target=spec.target,
        model=spec.model,
        seed=42,
        output="runs",
        workspace_root=workspace,
    )

    if result1["status"] != "completed" or result2["status"] != "completed":
        return {
            "rq": spec.label("RQ1"),
            "status": "FAIL",
            "reason": f"run statuses: {result1['status']}, {result2['status']}",
        }

    metrics1 = result1.get("metrics", {})
    metrics2 = result2.get("metrics", {})
    if not _metrics_equal(metrics1, metrics2, spec.metric_keys):
        return {
            "rq": spec.label("RQ1"),
            "status": "FAIL",
            "reason": f"metrics differ: {metrics1} vs {metrics2}",
        }

    manifest_path = runs_dir / result1["run_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("random_seed") != 42:
        return {
            "rq": spec.label("RQ1"),
            "status": "FAIL",
            "reason": "manifest missing seed",
        }

    dep_versions = manifest.get("dependency_versions")
    if not isinstance(dep_versions, dict) or not dep_versions:
        return {
            "rq": spec.label("RQ1"),
            "status": "FAIL",
            "reason": "manifest missing non-empty dependency_versions",
        }

    return {
        "rq": spec.label("RQ1"),
        "status": "PASS",
        "run_ids": [result1["run_id"], result2["run_id"]],
        "metrics": {key: metrics1.get(key) for key in spec.metric_keys},
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


async def _check_rq2_mcp_interop(
    run_id: str, runs_root: Path, spec: DatasetSpec
) -> dict[str, Any]:
    """RQ2: independent MCP client discovers and predicts."""

    async def exercise(session: ClientSession) -> dict[str, Any]:
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        if "list_models" not in tool_names or "predict" not in tool_names:
            return {
                "rq": spec.label("RQ2"),
                "status": "FAIL",
                "reason": f"missing tools: {tool_names}",
            }

        result = await session.call_tool("list_models", {})
        text = "".join(c.text for c in result.content if hasattr(c, "text"))
        payload = json.loads(text)
        if not payload.get("ok"):
            return {
                "rq": spec.label("RQ2"),
                "status": "FAIL",
                "reason": "list_models returned ok=false",
            }
        models = payload.get("data", [])
        matching = [m for m in models if m.get("run_id") == run_id]
        if not matching:
            return {
                "rq": spec.label("RQ2"),
                "status": "FAIL",
                "reason": "run_id not in list_models",
            }

        result = await session.call_tool(
            "predict",
            {"run_id": run_id, "features": [spec.predict_row]},
        )
        text = "".join(c.text for c in result.content if hasattr(c, "text"))
        payload = json.loads(text)
        if not payload.get("ok"):
            return {
                "rq": spec.label("RQ2"),
                "status": "FAIL",
                "reason": f"predict returned ok=false: {payload.get('error')}",
            }
        predictions = payload.get("data", {}).get("predictions")
        if not predictions or not isinstance(predictions, list):
            return {
                "rq": spec.label("RQ2"),
                "status": "FAIL",
                "reason": "predict returned no predictions",
            }

        return {"rq": spec.label("RQ2"), "status": "PASS", "predictions": predictions}

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

def _agentic_env(workspace: Path, specs: list[DatasetSpec]) -> dict[str, str]:
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
    for spec in specs:
        _dataset_csv(workspace, spec)
    return env


def _build_deterministic_result(
    spec: DatasetSpec, run_id: str, metrics: dict[str, Any]
) -> dict[str, Any]:
    """Deterministic-baseline evidence derived from the real RQ1 run."""
    eda_context = (
        "Features: 4 numeric, 0 categorical; Classes: 3, imbalance ratio: 1.0"
        if spec.task == "classification"
        else "Features: 4 numeric, 0 categorical; regression target with linear signal"
    )
    return {
        "status": "completed",
        "eda": {"eda_context": eda_context},
        "feature_engineering": {
            "cleaned_dataset_id": f"uploads/{spec.name}.csv",
            "clean_metadata": {"skipped": True, "reason": "fixture already clean"},
            "top_models": [
                {"model": spec.model, "metrics": dict(metrics)},
            ],
        },
        "model_selection": {
            "recommendation": {
                "best_model": spec.model,
                "model_grid": list(spec.recommendation_grid),
                "seeds": [42],
            }
        },
        "training_results": [
            {
                "dataset": f"uploads/{spec.name}.csv",
                "model": spec.model,
                "seed": 42,
                "status": "completed",
                "run_id": run_id,
                "metrics": dict(metrics),
            }
        ],
    }


def _stripped_deterministic_result(spec: DatasetSpec) -> dict[str, Any]:
    """Ungrounded arm for RQ4: all context evidence removed."""
    return {
        "status": "completed",
        "eda": {"eda_context": ""},
        "feature_engineering": {
            "cleaned_dataset_id": f"uploads/{spec.name}.csv",
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


def _new_experiment(workspace: Path, label: str, spec: DatasetSpec) -> Any:
    from thelab.ide.experiment import Experiment, ExperimentStore

    experiment = Experiment(
        experiment_id=f"exp-eval-{label}",
        goal=f"Evaluate {spec.target} prediction ({spec.name} arm, evaluator)",
        dataset_id=f"uploads/{spec.name}.csv",
        target=spec.target,
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
    spec: DatasetSpec, run_id: str, metrics: dict[str, Any], provider: Any
) -> dict[str, Any]:
    """RQ4: grounded vs stripped-context round; claims verified against evidence.

    Suite mode (mock/no provider): verifies the ablation instrument runs and
    that the grounded arm's deterministic-evidence claims verify 1:1.
    Live mode: compares verified-claim rates between arms.
    """
    from thelab.ide.agentic_round import run_agentic_round

    grounded_experiment = _new_experiment(Path.cwd(), f"rq4-grounded-{spec.name}", spec)
    grounded = await run_agentic_round(
        grounded_experiment,
        _build_deterministic_result(spec, run_id, metrics),
        provider=provider,
        require_approval=True,
    )
    ungrounded_experiment = _new_experiment(Path.cwd(), f"rq4-ungrounded-{spec.name}", spec)
    ungrounded = await run_agentic_round(
        ungrounded_experiment,
        _stripped_deterministic_result(spec),
        provider=provider,
        require_approval=True,
    )

    for arm in (grounded, ungrounded):
        if arm.get("status") != "awaiting_approval":
            return {"rq": spec.label("RQ4"), "status": "FAIL", "reason": f"arm status: {arm.get('status')}"}

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
                "rq": spec.label("RQ4"),
                "status": "FAIL",
                "reason": f"grounded arm has unverified claims: {g_verified}/{g_total}",
            }
        return {
            "rq": spec.label("RQ4"),
            "status": "PASS",
            "grounded_claims": f"{g_verified}/{g_total} verified",
            "ungrounded_claims": f"{u_verified}/{u_total} verified",
            "note": "mock instrument run; live comparison pending (--live)",
        }

    g_rate = g_verified / g_total if g_total else 1.0
    u_rate = u_verified / u_total if u_total else 1.0
    if g_rate < u_rate:
        return {
            "rq": spec.label("RQ4"),
            "status": "FAIL",
            "reason": f"grounded verified-rate {g_rate:.2f} < ungrounded {u_rate:.2f}",
        }
    return {
        "rq": spec.label("RQ4"),
        "status": "PASS",
        "grounded_verified_rate": round(g_rate, 3),
        "ungrounded_verified_rate": round(u_rate, 3),
        "grounded_claims": g_total,
        "ungrounded_claims": u_total,
    }


async def _check_rq5_agentic_capability(
    workspace: Path,
    spec: DatasetSpec,
    run_id: str,
    metrics: dict[str, Any],
    provider: Any,
    rounds: int = 1,
) -> dict[str, Any]:
    """RQ5: the round protocol end-to-end — gate blocks, approval enables.

    Suite bar (mock): the unapproved round cannot execute; the approved round
    runs through the factory and produces the comparison artifact.
    Live bar: script validity_rate >= 0.8.
    W4: repeats the agentic round N times and reports per-round validity and
    metric deltas — variance evidence, not a single-shot headline.
    """
    from thelab.agents.approval import (
        HumanApprovalRequired,
        record_human_approval,
    )
    from thelab.agents.worker import ProposalStore
    from thelab.ide.agentic_round import execute_approved_round, run_agentic_round

    round_results: list[dict[str, Any]] = []
    for index in range(max(1, rounds)):
        experiment = _new_experiment(workspace, f"rq5-{spec.name}-r{index}", spec)
        deterministic_result = _build_deterministic_result(spec, run_id, metrics)
        record = await run_agentic_round(
            experiment,
            deterministic_result,
            provider=provider,
            require_approval=True,
        )
        if record.get("status") != "awaiting_approval":
            return {
                "rq": spec.label("RQ5"),
                "status": "FAIL",
                "reason": f"round {index} status: {record.get('status')}",
            }
        proposal_id = record["proposal_id"]

        # Gate: unapproved execution must be refused.
        blocked = False
        try:
            execute_approved_round(experiment, proposal_id)
        except HumanApprovalRequired:
            blocked = True
        if not blocked:
            return {
                "rq": spec.label("RQ5"),
                "status": "FAIL",
                "reason": "execution was not blocked by the gate",
            }

        record_human_approval(
            ProposalStore(os.environ["THELAB_PROPOSALS_DIR"]), proposal_id, principal="evaluator"
        )
        result = execute_approved_round(experiment, proposal_id)
        comparison = result.get("comparison", {})
        if result.get("status") not in {"completed", "failed"}:
            return {
                "rq": spec.label("RQ5"),
                "status": "FAIL",
                "reason": f"round {index} execution status: {result.get('status')}",
            }
        if "metric_delta" not in comparison or "validity_rate" not in comparison:
            return {
                "rq": spec.label("RQ5"),
                "status": "FAIL",
                "reason": "comparison artifact incomplete",
            }
        round_results.append(
            {
                "round": index,
                "mode": record.get("mode"),
                "validity_rate": comparison.get("validity_rate"),
                "metric_delta": comparison.get("metric_delta", {}),
                "agentic_completed": comparison.get("agentic_completed"),
                "agentic_total": comparison.get("agentic_total"),
                "agentic_best": comparison.get("agentic_best"),
                "execution_status": result.get("status"),
            }
        )

    validity = round_results[-1]["validity_rate"]
    if provider is not None and round_results[-1]["execution_status"] == "completed":
        validities = [
            r["validity_rate"]
            for r in round_results
            if r["mode"] == "agentic" and r["validity_rate"] is not None
        ]
        if validities and (sum(validities) / len(validities)) < 0.8:
            return {
                "rq": spec.label("RQ5"),
                "status": "FAIL",
                "reason": f"mean validity {sum(validities) / len(validities):.2f} below 0.8 bar",
                "rounds": round_results,
            }

    return {
        "rq": spec.label("RQ5"),
        "status": "PASS",
        "gate_blocked_unapproved": True,
        "validity_rate": validity,
        "metric_delta": round_results[-1]["metric_delta"],
        "agentic_completed": round_results[-1]["agentic_completed"],
        "agentic_total": round_results[-1]["agentic_total"],
        "rounds": round_results,
    }


async def _check_rq6_orchestration(
    spec: DatasetSpec, run_id: str, metrics: dict[str, Any], provider: Any
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
        experiment = _new_experiment(Path.cwd(), f"rq6-{label}-{spec.name}", spec)
        record = await run_agentic_round(
            experiment,
            _build_deterministic_result(spec, run_id, metrics),
            provider=provider,
            require_approval=True,
            config=config,
        )
        if record.get("status") != "awaiting_approval":
            return {
                "rq": spec.label("RQ6"),
                "status": "FAIL",
                "reason": f"{label} arm status: {record.get('status')}",
            }
        if record.get("role_mode") != label:
            return {
                "rq": spec.label("RQ6"),
                "status": "FAIL",
                "reason": f"{label} arm recorded role_mode={record.get('role_mode')}",
            }
        proposal = record.get("proposal") or {}
        if not proposal.get("model_grid"):
            return {"rq": spec.label("RQ6"), "status": "FAIL", "reason": f"{label} arm produced no grid"}
        arms[label] = record

    return {
        "rq": spec.label("RQ6"),
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
    parser.add_argument(
        "--datasets",
        default="all",
        choices=["all", "iris", "housing", "churn"],
        help="Run the chain on one dataset arm or all (default: all)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="Repeat the RQ5 agentic round N times per dataset (variance evidence, W4)",
    )
    args = parser.parse_args()

    from thelab.env import load_dotenv

    load_dotenv()

    provider = None
    mode = "suite (mock)"
    if args.live:
        from thelab.agents.chat import create_provider

        provider = create_provider(args.live, args.model)
        mode = f"live ({args.live}" + (f":{args.model}" if args.model else "") + ")"

    specs = [_iris_spec(), _housing_spec()]
    # Real-data arm (W3): only when the gitignored upload exists.
    churn_available = _churn_source() is not None
    if churn_available:
        specs.append(_churn_spec())
    if args.datasets != "all":
        selected = [s for s in specs if s.name == args.datasets]
        specs = selected
    workspace = Path(tempfile.mkdtemp(prefix="thelab-eval-"))
    previous_env = {}
    report: dict[str, Any] = {"mode": mode, "results": []}
    if args.datasets in {"all", "churn"} and not churn_available:
        report["results"].append(
            {
                "rq": "RQ*[churn]",
                "status": "SKIPPED",
                "reason": "cleaned churn upload not present (data/uploads is gitignored)",
            }
        )
    try:
        # RQ3 is dataset-independent; run once.
        rq3 = _check_rq3_context_retrieval(workspace)
        report["results"].append(rq3)

        env = _agentic_env(workspace, specs)
        previous_env = {k: os.environ.get(k) for k in env}
        try:
            # Deterministic chain per spec first (sequential — RQ2 depends on
            # RQ1's run). The three agentic checks per spec are independent of
            # each other: run them concurrently behind a small semaphore
            # (provider rate limits) and stream verdicts as they complete
            # (work order X3).
            sem = asyncio.Semaphore(2)

            async def _run_check(coro_factory):
                async with sem:
                    res = await coro_factory()
                print(f"  -> {res['rq']}: {res['status']}", flush=True)
                return res

            agentic_tasks = []
            total_rounds = max(1, args.rounds)
            for spec in specs:
                rq1 = _check_rq1_reproducibility(workspace, spec)
                report["results"].append(rq1)

                run_id = rq1.get("run_ids", [None])[0]
                if rq1["status"] != "PASS" or run_id is None:
                    report["results"].append(
                        {"rq": spec.label("RQ2"), "status": "FAIL", "reason": "no verified run from RQ1"}
                    )
                    for n in (4, 5, 6):
                        report["results"].append(
                            {
                                "rq": spec.label(f"RQ{n}"),
                                "status": "FAIL",
                                "reason": "no verified baseline run from RQ1",
                            }
                        )
                    continue

                rq2 = await _check_rq2_mcp_interop(run_id, workspace / "runs", spec)
                report["results"].append(rq2)

                metrics = rq1.get("metrics", {})
                agentic_tasks.append(
                    _run_check(
                        lambda s=spec, r=run_id, m=metrics: _check_rq4_grounding(s, r, m, provider)
                    )
                )
                agentic_tasks.append(
                    _run_check(
                        lambda s=spec, r=run_id, m=metrics, n=total_rounds: _check_rq5_agentic_capability(
                            workspace, s, r, m, provider, rounds=n
                        )
                    )
                )
                agentic_tasks.append(
                    _run_check(
                        lambda s=spec, r=run_id, m=metrics: _check_rq6_orchestration(s, r, m, provider)
                    )
                )

            if agentic_tasks:
                print("Agentic checks (RQ4-RQ6) running", flush=True)
                report["results"].extend(await asyncio.gather(*agentic_tasks))
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        _print_report(report)
        failed = [r for r in report["results"] if r["status"] not in {"PASS", "SKIPPED"}]
        return 0 if not failed else 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
