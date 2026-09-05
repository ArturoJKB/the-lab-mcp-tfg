#!/usr/bin/env python3
"""P6 ratchet loop — deterministic baseline vs agentic rounds per dataset.

Protocol per dataset (P6_RATCHET_PLAN.md, user-approved 2026-09-04):
  1. Fair baseline: deterministic try-all (all registered models, persisted).
  2. Agentic rounds per model cell (approval gate; mandate principal recorded).
  3. Absorption gate: the best agentic config is replayed via ``run_model`` with
     the SAME seed — only an exact factory reproduction is absorbed as the
     dataset's champion config (RQ1 instrument). Fresh-seed generalization is
     NOT the gate; the winner's curse is handled by reporting best AND mean.
  4. Ledger: ``.thelab/generations/<slug>.json``.

``thelab/`` core is untouched: this runner only composes existing blocks.
The HTTP service is never used (X1 freeze irrelevant here).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast


def _ws() -> Path:
    """Workspace root, resolved per call (respects THELAB_WORKSPACE_ROOT)."""
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent)).resolve()


def _generations_dir() -> Path:
    return _ws() / ".thelab" / "generations"

PRIMARY = {"classification": ("test_accuracy", "test_f1_macro"), "regression": ("test_r2", "test_rmse")}
TOLERANCE = 1e-9

MODEL_LLAMA = "meta-llama/llama-3.3-70b-instruct"
MODEL_MISTRAL = "mistralai/mistral-small-24b-instruct-2501"
MODEL_GLM = "z-ai/glm-5.3-flash"


@dataclass
class DatasetCfg:
    slug: str
    dataset: str  # workspace-relative analysis CSV
    target: str
    task: str  # classification | regression
    arm: str  # "A" | "B"
    model_cells: list[tuple[str, str, int]]  # (provider, model, rounds)
    ingest_slug: str | None = None  # kaggle slug when the file must be ingested first


def default_registry() -> dict[str, DatasetCfg]:
    arm_a_cells = [("openrouter", MODEL_LLAMA, 3)]
    arm_b_cells = [
        ("openrouter", MODEL_LLAMA, 2),
        ("openrouter", MODEL_MISTRAL, 2),
        ("openrouter", MODEL_GLM, 1),
    ]
    return {
        "titanic": DatasetCfg("titanic", "data/uploads/yasserh_titanic-dataset_cleaned_Survived.csv",
                              "Survived", "classification", "A", arm_a_cells),
        "hr-attrition": DatasetCfg("hr-attrition", "data/uploads/pavansubhasht_ibm-hr-analytics-attrition-dataset_1_cleaned.csv",
                                   "Attrition", "classification", "A", arm_a_cells),
        "e-commerce": DatasetCfg("e-commerce", "data/uploads/erfan4524_e-commerce-sales-data-analysis-and-eda_cleaned.csv",
                                 "Sales", "regression", "A", arm_a_cells),
        "california-housing": DatasetCfg("california-housing", "data/uploads/camnugent_california-housing-prices_cleaned_median_house_value.csv",
                                         "median_house_value", "regression", "A", arm_a_cells),
        "clinvar": DatasetCfg("clinvar", "data/uploads/kevinarvai_clinvar-conflicting.csv",
                              "CLASS", "classification", "B", arm_b_cells,
                              ingest_slug="kevinarvai/clinvar-conflicting"),
        "kidney": DatasetCfg("kidney", "data/uploads/rabieelkharoua_chronic-kidney-disease-dataset-analysis.csv",
                             "Diagnosis", "classification", "B", arm_b_cells,
                             ingest_slug="rabieelkharoua/chronic-kidney-disease-dataset-analysis"),
        "crypto": DatasetCfg("crypto", "data/uploads/sudalairajkumar_cryptocurrencypricehistory.csv",
                             "direction", "classification", "B", arm_b_cells,
                             ingest_slug="sudalairajkumar/cryptocurrencypricehistory"),
        "energy": DatasetCfg("energy", "data/uploads/robikscube_hourly-energy-consumption.csv",
                             "AEP_MW", "regression", "B", arm_b_cells,
                             ingest_slug="robikscube/hourly-energy-consumption"),
        "churn": DatasetCfg("churn", "data/uploads/shrutimechlearn_churn-modelling_cleaned.csv",
                            "Exited", "classification", "A", arm_a_cells),
        "sp500": DatasetCfg("sp500", "data/uploads/sp500_analyst.csv",
                            "action", "classification", "A", arm_a_cells),
    }


# ---------------------------------------------------------------------------
# Pure bookkeeping (unit-tested)
# ---------------------------------------------------------------------------

def pick_baseline(try_all_results: list[dict[str, Any]], task: str) -> dict[str, Any] | None:
    """Fair bar: best completed try-all entry by the task's primary metric."""
    primary = PRIMARY[task][0]
    completed = [r for r in try_all_results if r.get("status") == "completed" and r.get("metrics")]
    if not completed:
        return None
    return max(completed, key=lambda r: float(r["metrics"].get(primary, float("-inf"))))


def absorption_decision(
    baseline: dict[str, Any] | None,
    best_round: dict[str, Any] | None,
    replay_metrics: dict[str, Any] | None,
    task: str,
) -> dict[str, Any]:
    """Absorption gate: agentic win on the fair bar + exact factory replay."""
    primary = PRIMARY[task][0]
    if baseline is None:
        return {"absorbed": False, "reason": "no completed deterministic baseline"}
    if best_round is None:
        return {"absorbed": False, "reason": "no agentic round (all degraded or rejected)"}
    best_metrics = best_round.get("metrics") or {}
    base_val = float(baseline["metrics"].get(primary, float("-inf")))
    ag_val = float(best_metrics.get(primary, float("-inf")))
    if ag_val <= base_val:
        return {
            "absorbed": False,
            "reason": f"agentic best {ag_val:.6f} does not beat baseline {base_val:.6f} ({primary})",
        }
    if replay_metrics is None:
        return {"absorbed": False, "reason": "no replay available"}
    shared = [k for k in best_metrics if k in replay_metrics and best_metrics[k] is not None]
    mismatch = [
        k for k in shared
        if abs(float(best_metrics[k]) - float(replay_metrics[k])) > TOLERANCE
    ]
    if mismatch:
        return {
            "absorbed": False,
            "reason": f"factory replay did not reproduce the win: {mismatch[:4]}",
            "replay_metrics": replay_metrics,
        }
    return {
        "absorbed": True,
        "reason": "agentic win reproduced exactly by the deterministic factory",
        "champion": best_round.get("config"),
        "primary": primary,
        "baseline_value": base_val,
        "agentic_value": ag_val,
        "delta": ag_val - base_val,
    }


def load_ledger(slug: str) -> dict[str, Any]:
    path = _generations_dir() / f"{slug}.json"
    if path.is_file():
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    return {"slug": slug, "generations": []}


def save_ledger(slug: str, ledger: dict[str, Any]) -> Path:
    _generations_dir().mkdir(parents=True, exist_ok=True)
    path = _generations_dir() / f"{slug}.json"
    path.write_text(json.dumps(ledger, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Composition of existing blocks
# ---------------------------------------------------------------------------

def build_provider(provider_name: str, model: str | None) -> Any:
    if provider_name == "mock":
        from thelab.agents.mock import MockProvider

        return MockProvider([])
    if provider_name == "openrouter":
        from thelab.agents.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(model=model)
    if provider_name == "ollama":
        from thelab.agents.providers.ollama import OllamaProvider

        return OllamaProvider(model=model)
    raise ValueError(f"unsupported provider: {provider_name}")


def _deterministic_result(
    spec: DatasetCfg, baseline: dict[str, Any], dataset_id: str | None = None
) -> dict[str, Any]:
    metrics = baseline.get("metrics", {})
    analysis_id = dataset_id or f"uploads/{Path(spec.dataset).name}"
    return {
        "status": "completed",
        "eda": {"eda_context": f"{spec.task} dataset; baseline from deterministic try-all"},
        "feature_engineering": {
            "cleaned_dataset_id": analysis_id,
            "clean_metadata": {"skipped": True, "reason": "ratchet analysis csv is clean"},
            "top_models": [{"model": baseline.get("model"), "metrics": dict(metrics)}],
        },
        "model_selection": {
            "recommendation": {
                "best_model": baseline.get("model"),
                "model_grid": [baseline.get("model")],
                "seeds": [42],
            }
        },
    }


def run_cell_rounds(
    spec: DatasetCfg,
    provider_name: str,
    model: str,
    n_rounds: int,
    baseline: dict[str, Any],
    config: Any | None = None,
    cell_label: str | None = None,
    dataset_id: str | None = None,
) -> list[dict[str, Any]]:
    """One model cell: n gated agentic rounds; returns per-round records.

    ``config`` (optional) carries per-stage providers for mixed-model rounds;
    ``cell_label`` overrides the experiment-id/label segment.
    """
    from thelab.agents.approval import record_human_approval
    from thelab.agents.worker import ProposalStore
    from thelab.ide.agentic_round import (
        RoundConfig,
        execute_approved_round,
        run_agentic_round,
    )
    from thelab.ide.experiment import Experiment, ExperimentStore

    if config is None:
        config = RoundConfig(require_approval=True)
        provider = build_provider(provider_name, model)
    else:
        provider = config.provider_for("Analyst", None)
        if provider is None:
            provider = build_provider(provider_name, model)
    model_short = cell_label or ((model or provider_name).split("/")[-1][:28])
    rounds: list[dict[str, Any]] = []
    for index in range(n_rounds):
        t0 = time.time()
        exp_id = f"exp-ratchet-{spec.slug}-{model_short}-{index}-{time.strftime('%H%M%S')}"
        analysis_id = dataset_id or f"uploads/{Path(spec.dataset).name}"
        experiment = Experiment(
            experiment_id=exp_id,
            goal=f"Ratchet loop: beat the deterministic try-all baseline ({spec.slug})",
            dataset_id=analysis_id,
            target=spec.target,
        )
        ExperimentStore().save(experiment)
        record = asyncio.run(
            run_agentic_round(
                experiment,
                _deterministic_result(spec, baseline, analysis_id),
                provider=provider,
                require_approval=True,
                config=config,
            )
        )
        if record.get("status") != "awaiting_approval":
            rounds.append({"round": index, "provider": provider_name, "model": model,
                           "status": record.get("status"), "mode": record.get("mode")})
            print(f"    round {index}: {record.get('status')} (no proposal)", flush=True)
            continue
        proposal_id = record["proposal_id"]
        store = ProposalStore(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))
        record_human_approval(store, proposal_id, principal=f"auto:p6loop:{spec.slug}")
        result = execute_approved_round(experiment, proposal_id)
        comparison = result.get("comparison", {})
        entry = {
            "round": index,
            "provider": provider_name,
            "model": model,
            "status": result.get("status"),
            "mode": record.get("mode"),
            "validity_rate": comparison.get("validity_rate"),
            "agentic_completed": comparison.get("agentic_completed"),
            "agentic_total": comparison.get("agentic_total"),
            "agentic_best": comparison.get("agentic_best"),
            "metric_delta": comparison.get("metric_delta", {}),
            "seconds": round(time.time() - t0, 1),
        }
        rounds.append(entry)
        best = comparison.get("agentic_best") or {}
        met = (best.get("metrics") or {})
        print(
            f"    round {index}: mode={record.get('mode')} validity={entry['validity_rate']} "
            f"entries={entry['agentic_completed']}/{entry['agentic_total']} "
            f"best={(best.get('model') or '-')} acc/r2={met.get('test_accuracy', met.get('test_r2'))} "
            f"({entry['seconds']}s)",
            flush=True,
        )
    return rounds


def _best_agentic(rounds: list[dict[str, Any]], task: str) -> dict[str, Any] | None:
    """Best round record among mode=='agentic' rounds (P5.B8 counting rule)."""
    primary = PRIMARY[task][0]
    candidates = [
        r for r in rounds
        if r.get("mode") == "agentic" and isinstance(r.get("agentic_best"), dict)
        and (r["agentic_best"].get("metrics") or {}).get(primary) is not None
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda r: float(r["agentic_best"]["metrics"][primary]),
    )


def _replay_winner(spec: DatasetCfg, agentic_best: dict[str, Any]) -> dict[str, Any] | None:
    """Replay the winning config through run_model (same seed) -> metrics.

    The winning run's full configuration is reconstructed from its artifacts:
    dataset/seed/task type from ``inputs.json``, hyperparameters from
    ``training_config.json -> estimator.hyperparameters``.
    """
    from thelab.run.runner import run_model

    run_id = agentic_best.get("run_id")
    if not run_id:
        return None
    run_dir = _ws() / "runs" / str(run_id)
    inputs_path = run_dir / "inputs.json"
    config_path = run_dir / "training_config.json"
    if not inputs_path.is_file() or not config_path.is_file():
        return None
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    training_config = json.loads(config_path.read_text(encoding="utf-8"))
    hyperparams = ((training_config.get("estimator") or {}).get("hyperparameters")) or None
    task_raw = str(inputs.get("task_type") or "auto")
    task: Literal["auto", "classification", "regression"] = (
        cast(Literal["auto", "classification", "regression"], task_raw)
        if task_raw in ("auto", "classification", "regression")
        else "auto"
    )
    result = run_model(
        dataset=str(inputs.get("dataset") or spec.dataset),
        target=str(inputs.get("target") or spec.target),
        model=str(inputs.get("model") or agentic_best.get("model")),
        seed=int(inputs.get("seed", agentic_best.get("seed", 42))),
        output="runs",
        workspace_root=_ws(),
        task_type=task,
        hyperparameters=hyperparams,
    )
    if result.get("status") != "completed":
        return None
    return result.get("metrics") or {}


def parse_stage_models(raw: str) -> dict[str, tuple[str, str]]:
    """Parse "Role=provider:model,..." into {role: (provider, model)}."""
    out: dict[str, tuple[str, str]] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        role, _, rest = part.partition("=")
        provider, _, model = rest.partition(":")
        role = role.strip()
        if role not in {"Analyst", "FeatureEngineer", "ModelSelector"} or not provider.strip():
            raise ValueError(f"invalid --stage-models part: {part!r}")
        out[role] = (provider.strip(), model.strip())
    return out


def _prepare_dataset(spec: DatasetCfg, ingest: bool) -> str | None:
    """Ensure the spec's analysis CSV exists as a *cleaned* upload.

    Returns the workspace-relative cleaned dataset id, or None when the file
    is missing and ingest was not requested. Chain (Arm B): kaggle ingest ->
    deterministic cleaning policy -> cleaned CSV. Idempotent: re-running
    returns the existing cleaned dataset (the cleaning API rejects
    re-cleaning an already-cleaned id).
    """
    raw_path = _ws() / spec.dataset
    if raw_path.is_file() and "_cleaned_" in spec.dataset:
        return f"uploads/{Path(spec.dataset).name}"  # uploads-form id (matches raw branch)

    if not raw_path.is_file():
        if not ingest or not spec.ingest_slug:
            return None
        from thelab.ide.kaggle_api import ingest_kaggle_dataset

        print(f"  ingest: {spec.ingest_slug} ...", flush=True)
        info = ingest_kaggle_dataset(spec.ingest_slug)
        ingested_id = info.get("dataset_id") or ""
        print(f"  ingested: {ingested_id}", flush=True)
        if not ingested_id:
            return None
        raw_id = ingested_id
    else:
        # File exists but the registry points at the raw (uncleaned) name:
        # resolve the actual uploaded id from the raw file's basename.
        raw_id = f"uploads/{Path(spec.dataset).name}"

    from thelab.ide.cleaning import clean_dataset

    print(f"  clean: {raw_id} (target {spec.target}) ...", flush=True)
    try:
        metadata = clean_dataset(
            raw_id,
            spec.target,
            drop_missing_target=True,
            drop_empty_columns=True,
            one_hot_encode=True,
            numeric_impute_strategy="median",
            categorical_impute_strategy="mode",
        )
    except ValueError as exc:
        # Idempotent re-clean: return the existing cleaned dataset id when the
        # cleaning API's "already cleaned" naming convention tells us where it is.
        match = re.search(r"'(uploads/[^']+)' is already cleaned", str(exc))
        if match:
            print(f"  clean skipped: already cleaned -> {match.group(1)}", flush=True)
            return match.group(1)
        print(f"  clean skipped ({exc}); using raw file directly", flush=True)
        return raw_id
    cleaned_id = metadata.get("dataset_id") or ""
    print(f"  cleaned: {cleaned_id} ({metadata.get('rows_cleaned', '?')} rows)", flush=True)
    return cleaned_id or None


def run_dataset(
    slug: str,
    registry: dict[str, DatasetCfg] | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    rounds_override: int | None = None,
    mixed: dict[str, tuple[str, str]] | None = None,
    mixed_rounds: int = 1,
    ingest: bool = False,
) -> dict[str, Any]:
    from thelab.ide.datasets import dataset_id_to_relative_path
    from thelab.run.runner import try_all_models

    registry = registry or default_registry()
    spec = registry[slug]
    ledger = load_ledger(slug)
    entry: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cells": []}

    # Arm B chain: kaggle ingest -> deterministic clean -> cleaned analysis CSV.
    analysis_id = _prepare_dataset(spec, ingest)
    if analysis_id is None:
        entry["error"] = f"dataset not available: {spec.dataset} (ingest={ingest})"
        ledger.setdefault("generations", []).append(entry)
        save_ledger(slug, ledger)
        print("  FAILED: dataset not available", flush=True)
        return entry
    analysis_rel = dataset_id_to_relative_path(analysis_id)

    print(f"== ratchet: {slug} ({spec.task}, arm {spec.arm}) ==", flush=True)
    print(f"  analysis dataset: {analysis_rel}", flush=True)
    print("  baseline: deterministic try-all (persisted)", flush=True)
    results = try_all_models(
        dataset=analysis_rel,
        target=spec.target,
        seed=42,
        output="runs",
        workspace_root=_ws(),
        dry_run=False,
    )
    baseline = pick_baseline(results, spec.task)
    if baseline is None:
        entry["error"] = "no completed try-all baseline"
        ledger.setdefault("generations", []).append(entry)
        save_ledger(slug, ledger)
        print("  FAILED: no completed baseline", flush=True)
        return entry
    bmet = baseline.get("metrics", {})
    print(
        f"  baseline best: {baseline.get('model')} "
        f"{bmet.get(PRIMARY[spec.task][0])} ({PRIMARY[spec.task][0]})",
        flush=True,
    )
    entry["baseline"] = {
        "model": baseline.get("model"),
        "seed": 42,
        "metrics": dict(bmet),
        "run_id": baseline.get("run_id"),
    }

    if mixed:
        from thelab.ide.agentic_round import RoundConfig

        providers = {role: build_provider(pn, m) for role, (pn, m) in mixed.items()}
        labels = {role: m for role, (pn, m) in mixed.items()}
        config = RoundConfig(require_approval=True, stage_providers=providers, stage_models=labels)
        print(f"  cell: mixed team {labels} x{mixed_rounds}", flush=True)
        cell_rounds = run_cell_rounds(
            spec, "mixed", "mixed", mixed_rounds, baseline,
            config=config, cell_label="mixed", dataset_id=analysis_id,
        )
        entry["cells"].append({
            "provider": "mixed", "model": json.dumps(labels), "rounds": cell_rounds,
        })

    for provider_name, model, n_rounds in ([] if mixed else spec.model_cells):
        if provider_override:
            provider_name = provider_override
        if model_override:
            model = model_override
        n = rounds_override if rounds_override else n_rounds
        label = (model or provider_name).split("/")[-1][:34]
        print(f"  cell: {provider_name}/{label} x{n}", flush=True)
        cell_rounds = run_cell_rounds(spec, provider_name, model, n, baseline, dataset_id=analysis_id)
        entry["cells"].append({
            "provider": provider_name, "model": model, "rounds": cell_rounds,
        })

    # Absorption gate across all agentic rounds of this generation.
    all_rounds = [r for c in entry["cells"] for r in c["rounds"]]
    best_round = _best_agentic(all_rounds, spec.task)
    decision: dict[str, Any]
    replay_metrics = None
    if best_round is not None:
        agentic_best = best_round["agentic_best"]
        print("  absorption gate: replaying winner config via run_model (same seed)", flush=True)
        replay_metrics = _replay_winner(spec, agentic_best)
        best_round["metrics"] = agentic_best.get("metrics") or {}
        winner_inputs = {}
        winner_run = agentic_best.get("run_id")
        winner_config_path = _ws() / "runs" / str(winner_run) / "training_config.json"
        if winner_config_path.is_file():
            winner_inputs = json.loads(winner_config_path.read_text(encoding="utf-8")).get(
                "estimator", {}
            )
        best_round["config"] = {
            "dataset": spec.dataset,
            "target": spec.target,
            "model": agentic_best.get("model"),
            "seed": agentic_best.get("seed"),
            "hyperparameters": (winner_inputs or {}).get("hyperparameters") or None,
        }
        decision = absorption_decision(baseline, best_round, replay_metrics, spec.task)
    else:
        decision = absorption_decision(baseline, None, None, spec.task)
    entry["absorption"] = decision
    if decision.get("absorbed"):
        print(
            f"  ABSORBED champion: {decision['champion']['model']} "
            f"({decision['primary']} {decision['baseline_value']:.6f} -> {decision['agentic_value']:.6f})",
            flush=True,
        )
    else:
        print(f"  no absorption: {decision['reason']}", flush=True)

    ledger.setdefault("generations", []).append(entry)
    path = save_ledger(slug, ledger)
    print(f"  ledger: {path}", flush=True)
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P6 ratchet loop (see scratch/app_audit/P6_RATCHET_PLAN.md)")
    parser.add_argument("--datasets", default="", help="comma-separated slugs (default: all present)")
    parser.add_argument("--provider", default=None, help="override provider for every cell")
    parser.add_argument("--model", default=None, help="override model for every cell")
    parser.add_argument("--rounds", type=int, default=None, help="override rounds for every cell")
    parser.add_argument("--dry-run", action="store_true", help="mock provider, no network")
    parser.add_argument("--ingest", action="store_true", help="ingest missing Arm B datasets first")
    parser.add_argument(
        "--stage-models",
        default=None,
        help="mixed-model rounds: 'Analyst=openrouter:<model>,FeatureEngineer=openrouter:<model>,ModelSelector=openrouter:<model>'",
    )
    args = parser.parse_args(argv)

    from thelab.env import load_dotenv

    load_dotenv()

    registry = default_registry()
    slugs = [s.strip() for s in args.datasets.split(",") if s.strip()] or list(registry)

    for slug in slugs:
        spec = registry.get(slug)
        if spec is None:
            print(f"unknown dataset slug: {slug}", flush=True)
            return 2
        if not (_ws() / spec.dataset).is_file():
            if args.ingest and spec.ingest_slug:
                from thelab.ide.kaggle_api import ingest_kaggle_dataset

                print(f"ingesting {spec.ingest_slug} ...", flush=True)
                info = ingest_kaggle_dataset(spec.ingest_slug)
                print(f"  ingested: {info.get('dataset_id')}", flush=True)
                # Arm B raw uploads need the deterministic clean step before use;
                # that produces <stem>_cleaned_<target>.csv. Point the spec at it
                # if the raw file is not directly trainable.
                # (Handled per-dataset in the execution session; see ledger notes.)
            print(f"dataset file missing for {slug}: {spec.dataset}", flush=True)
            return 2

    provider_name = "mock" if args.dry_run else (args.provider or "openrouter")
    mixed = parse_stage_models(args.stage_models) if args.stage_models else None
    if args.dry_run and mixed:
        for role in mixed:
            mixed[role] = ("mock", mixed[role][1] or "mock")
    for slug in slugs:
        entry = run_dataset(
            slug, registry, provider_name, args.model, args.rounds,
            mixed=mixed, mixed_rounds=max(1, args.rounds or 1),
        )
        if entry.get("error"):
            return 1
        print("", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
