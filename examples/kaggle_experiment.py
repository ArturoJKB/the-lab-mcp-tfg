"""The Lab — Kaggle experiment, end to end.

Downloads a Kaggle dataset, builds its context pack, cleans it, proposes an
experiment through the agent flow, approves and runs it, and reports the
results — then generates the run's reproducible notebook (P3.6).

Run from the repository root:
    python examples/kaggle_experiment.py                                   # default demo dataset
    python examples/kaggle_experiment.py <owner/dataset> <Target> [model_grid]

Model grid defaults are chosen per task type when omitted:
    classification -> logistic_regression, random_forest, hist_gradient_boosting
    regression     -> ridge, random_forest_regressor, hist_gradient_boosting_regressor

Network is used only by the kagglehub download and the page fetch.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

DEFAULT_SLUG = "erfan4524/e-commerce-sales-data-analysis-and-eda"
DEFAULT_TARGET = "Sales"

CLASSIFICATION_GRID = ["logistic_regression", "random_forest", "hist_gradient_boosting"]
REGRESSION_GRID = ["ridge", "random_forest_regressor", "hist_gradient_boosting_regressor"]


def _print_metrics(runs_root: Path, entry: dict) -> None:
    metrics = json.loads((runs_root / f"{entry['run_id']}" / "metrics.json").read_text())
    if "test_r2" in metrics:
        detail = f"R2={metrics['test_r2']:.4f} RMSE={metrics['test_rmse']:.2f}"
    else:
        detail = f"Acc={metrics['test_accuracy']:.4f} F1={metrics['test_f1_macro']:.4f}"
    print(f"    {entry['model']}: {detail} ({entry['status']})")


def run_experiment(slug: str, target: str, goal: str | None = None, model_grid: list[str] | None = None) -> int:
    from thelab.agents.mock import MockProvider
    from thelab.agents.worker import WorkerAgent
    from thelab.ide.cleaning import clean_dataset
    from thelab.ide.datasets import dataset_id_to_relative_path
    from thelab.ide.kaggle_api import (
        build_context_pack,
        fetch_kaggle_page_context,
        get_dataset_context,
        ingest_kaggle_dataset,
    )
    from thelab.ide.proposals_api import approve_and_run_proposal
    from thelab.run.notebook import generate_run_notebook

    # 1. Ingest from Kaggle (network) ------------------------------------------------
    ingestion = ingest_kaggle_dataset(slug)
    dataset_id = ingestion["dataset_id"]
    print(f"[1] ingested: {dataset_id} ({ingestion['profile']['rows']} rows x {ingestion['profile']['columns']} cols)")

    # 2. Dataset context pack: the dataset's own documentation + local profile ------
    page = fetch_kaggle_page_context(slug)
    pack = build_context_pack(slug, ingestion, page)
    description = (pack.get("description_markdown") or pack.get("description_short") or "")[:100]
    print(f"[2] context pack: {description.replace(chr(10), ' ')}...")
    assert get_dataset_context(dataset_id) is not None

    # 3. Clean (deterministic policy; required before training) ----------------------
    cleaned = clean_dataset(dataset_id, target=target)
    cleaned_id = cleaned["dataset_id"]
    print(f"[3] cleaned: {cleaned_id} ({cleaned['rows']} rows x {cleaned['columns']} cols)")

    # 4. Agent proposal (deterministic fallback; swap in a live provider if desired) -
    worker = WorkerAgent(provider=MockProvider([]), servers=[], proposals_dir="proposals")
    proposal = asyncio.run(
        worker.propose(
            goal=goal or f"Predict {target} (Kaggle dataset {slug})",
            dataset=dataset_id_to_relative_path(cleaned_id),
            target=target,
            model_grid=model_grid,
            seeds=[42],
        )
    )
    print(f"[4] proposal: {proposal.proposal_id} (task: {proposal.task_type}, grid: {proposal.model_grid})")

    # 5. Approve + run through the batch runner --------------------------------------
    outcome = approve_and_run_proposal(proposal.proposal_id, principal="kaggle_experiment")
    print(f"[5] outcome: {outcome['status']} ({outcome['completed']} completed)")

    # 6. Results + generated notebook --------------------------------------------------
    runs_root = Path(os.environ.get("THELAB_RUNS_ROOT", "runs"))
    completed = [entry for entry in outcome["results"] if entry["status"] == "completed" and entry.get("run_id")]
    for entry in outcome["results"]:
        if entry.get("run_id") and (runs_root / entry["run_id"] / "metrics.json").is_file():
            _print_metrics(runs_root, entry)
        else:
            print(f"    {entry['model']}: {entry['status']} - {entry.get('error') or ''}")

    if completed:
        best = completed[0]
        notebook = generate_run_notebook(best["run_id"])
        json.dumps(notebook)
        print(f"[6] notebook generated for {best['run_id']} ({len(notebook['cells'])} cells, nbformat {notebook['nbformat']})")
        print("    fetch: GET /runs/{run_id}/notebook  |  thesis artifact: reproducible report.ipynb")
    return 0


def main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SLUG
    target = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TARGET
    print(f"=== The Lab Kaggle experiment ===\n    slug:   {slug}\n    target: {target}\n")
    raise SystemExit(run_experiment(slug, target))


if __name__ == "__main__":
    main()
