"""Run the B1 cross-domain benchmark.

Compares deterministic baselines against agent-boosted proposals for three
domains, using both OpenRouter and Ollama providers.

Usage:
    source .env
    .venv/bin/python scripts/run_b1_benchmark.py

Output:
    benchmarks/b1/benchmark_manifest.json
    benchmarks/b1/reports/b1_report.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.agents.worker import ProposalStore
from thelab.run.batch import BatchRunner
from thelab.run.runner import run_model

BENCHMARK_DIR = Path("benchmarks/b1")
PROPOSALS_DIR = BENCHMARK_DIR / "proposals"
REPORTS_DIR = BENCHMARK_DIR / "reports"

BENCHMARK_DATASETS: list[dict[str, Any]] = [
    {
        "domain": "real_estate",
        "name": "california_housing",
        "dataset": "data/benchmarks/california_housing.csv",
        "target": "MedHouseVal",
        "task_type": "regression",
        "baseline_model": "ridge",
    },
    {
        "domain": "medical",
        "name": "breast_cancer",
        "dataset": "data/benchmarks/breast_cancer.csv",
        "target": "target",
        "task_type": "classification",
        "baseline_model": "logistic_regression",
    },
    {
        "domain": "food_chemistry",
        "name": "wine_quality_red",
        "dataset": "data/benchmarks/wine_quality_red.csv",
        "target": "quality",
        "task_type": "classification",
        "baseline_model": "logistic_regression",
    },
]


@dataclass
class ProviderConfig:
    name: str
    model_env_var: str
    default_model: str


PROVIDERS = [
    ProviderConfig("openrouter", "THELAB_LLM_MODEL", "stealth/ox-alpha"),
    ProviderConfig("ollama", "OLLAMA_MODEL", "llama3.2:3b"),
]


def _load_metrics(run_id: str) -> dict[str, Any]:
    path = Path("runs") / run_id / "metrics.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _run_deterministic(dataset: str, target: str, model: str, task_type: str) -> dict[str, Any]:
    result = run_model(
        dataset=dataset,
        target=target,
        model=model,
        seed=42,
        output="runs",
        task_type=task_type,
    )
    return {
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "metrics": result.get("metrics", {}),
    }


def _run_worker_provider(provider: str, dataset: str, target: str, goal: str) -> dict[str, Any] | None:
    """Run the worker CLI and return the parsed proposal, or None on failure."""
    cmd = [
        sys.executable,
        "-m",
        "thelab.agents.cli",
        "--mode",
        "worker",
        "--provider",
        provider,
        "--dataset",
        dataset,
        "--target",
        target,
        "--proposals-dir",
        str(PROPOSALS_DIR),
        "--json",
        goal,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            print(f"  Worker failed ({provider}): {result.stderr.strip()}", file=sys.stderr)
            return None
        proposal = json.loads(result.stdout)
        return proposal
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"  Worker error ({provider}): {exc}", file=sys.stderr)
        return None


def _approve_and_run_batch(proposal_id: str) -> dict[str, Any] | None:
    """Approve a proposal, run its batch config, and return aggregated metrics."""
    store = ProposalStore(proposals_dir=PROPOSALS_DIR)
    store.approve(proposal_id, principal="benchmark")
    batch_path = store.write_batch_config(proposal_id)

    runner = BatchRunner(workspace_root=Path.cwd())
    entries = runner.load_config(batch_path)
    results = runner.run(entries, output="runs")

    completed = [r for r in results if r.status == "completed" and r.run_id]
    if not completed:
        return None

    # Aggregate metrics: average across completed runs.
    aggregated: dict[str, list[float]] = {}
    for result in completed:
        for key, value in result.metrics.items():
            if isinstance(value, (int, float)):
                aggregated.setdefault(key, []).append(float(value))

    return {
        "run_ids": [r.run_id for r in completed],
        "metrics": {key: sum(values) / len(values) for key, values in aggregated.items()},
    }


def _run_provider(provider: ProviderConfig) -> dict[str, Any]:
    provider_results: list[dict[str, Any]] = []
    model = os.environ.get(provider.model_env_var, provider.default_model)

    for ds in BENCHMARK_DATASETS:
        print(f"[{provider.name}] {ds['name']} — deterministic baseline...")
        deterministic = _run_deterministic(
            dataset=ds["dataset"],
            target=ds["target"],
            model=ds["baseline_model"],
            task_type=ds["task_type"],
        )

        print(f"[{provider.name}] {ds['name']} — agent proposal...")
        goal = f"{ds['task_type']} on {ds['name']}"
        proposal = _run_worker_provider(provider.name, ds["dataset"], ds["target"], goal)

        agent_runs: dict[str, Any] | None = None
        if proposal and proposal.get("proposal_id"):
            print(f"[{provider.name}] {ds['name']} — batch run...")
            agent_runs = _approve_and_run_batch(proposal["proposal_id"])

        provider_results.append({
            "domain": ds["domain"],
            "name": ds["name"],
            "dataset": ds["dataset"],
            "target": ds["target"],
            "task_type": ds["task_type"],
            "deterministic_run_id": deterministic.get("run_id"),
            "deterministic_status": deterministic.get("status"),
            "agent_proposal_id": proposal.get("proposal_id") if proposal else None,
            "agent_run_ids": agent_runs.get("run_ids") if agent_runs else None,
            "metrics": {
                "deterministic": deterministic.get("metrics", {}),
                "agent": agent_runs.get("metrics") if agent_runs else None,
            },
        })

    return {
        "provider": provider.name,
        "model": model,
        "datasets": provider_results,
    }


def _write_report(manifest: dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "b1_report.md"

    lines = [
        "# B1 Cross-domain Benchmark Report\n",
        f"Created: {manifest['created_at']}\n",
        "\n",
    ]

    for provider in manifest["providers"]:
        lines.append(f"## Provider: {provider['provider']} ({provider['model']})\n\n")
        lines.append("| Domain | Dataset | Deterministic | Agent | Status |\n")
        lines.append("|---|---|---|---|---|\n")
        for ds in provider["datasets"]:
            det = ds["metrics"]["deterministic"]
            agent = ds["metrics"]["agent"] or {}
            det_score = _summary_metric(det, ds["task_type"])
            agent_score = _summary_metric(agent, ds["task_type"]) if agent else "N/A"
            status = "OK" if ds["agent_run_ids"] else "AGENT_FAILED"
            lines.append(
                f"| {ds['domain']} | {ds['name']} | {det_score} | {agent_score} | {status} |\n"
            )
        lines.append("\n")

    path.write_text("".join(lines), encoding="utf-8")
    return path


def _summary_metric(metrics: dict[str, Any], task_type: str) -> str:
    if task_type == "regression":
        value = metrics.get("test_rmse")
        return f"RMSE={value:.4f}" if value is not None else "N/A"
    value = metrics.get("test_accuracy")
    return f"Acc={value:.4f}" if value is not None else "N/A"


def main() -> int:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

    provider_manifests = []
    for provider in PROVIDERS:
        print(f"\n=== Provider: {provider.name} ===")
        provider_manifests.append(_run_provider(provider))

    manifest = {
        "benchmark_id": "b1",
        "created_at": datetime.now(UTC).isoformat(),
        "providers": provider_manifests,
    }

    manifest_path = BENCHMARK_DIR / "benchmark_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"\nManifest: {manifest_path}")

    report_path = _write_report(manifest)
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
