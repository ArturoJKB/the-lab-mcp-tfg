"""Experiment Orchestrator for multi-agent ML workflow."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thelab.agents.mock import MockProvider
from thelab.agents.provider import LLMProvider
from thelab.agents.worker import ProposalStore, WorkerAgent
from thelab.ide.cleaning import clean_dataset
from thelab.ide.datasets import dataset_id_to_relative_path, resolve_dataset_path
from thelab.ide.eda_api import run_eda
from thelab.ide.experiment import generate_experiment_id
from thelab.mcp.common import get_runs_root
from thelab.run.batch import BatchRunner
from thelab.run.runner import try_all_models

EventCallback = Callable[[str, str], None]
ShouldContinue = Callable[[], bool]


class OrchestrationCancelled(RuntimeError):
    """Raised when a caller requests cancellation between stages."""


def _workspace_root() -> Path:
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))


class ExperimentOrchestrator:
    """Orchestrates multi-agent ML experiments with sub-agents and deterministic skills."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        runs_root: Path | str | None = None,
        proposals_dir: Path | str | None = None,
    ) -> None:
        self.provider = provider or MockProvider([])
        self.runs_root = Path(runs_root) if runs_root else Path(get_runs_root())
        self.proposals_dir = (
            Path(proposals_dir)
            if proposals_dir
            else Path(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))
        )
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.proposal_store = ProposalStore(self.proposals_dir)

    def _create_worker(self, provider: LLMProvider | None = None) -> WorkerAgent:
        return WorkerAgent(
            provider=provider or self.provider,
            servers=[],
            proposals_dir=self.proposals_dir,
            runs_root=self.runs_root,
        )

    async def run_eda_analysis(self, dataset_id: str, target: str, goal: str = "") -> dict[str, Any]:
        """Run EDA analysis using deterministic skills."""
        _ = resolve_dataset_path(dataset_id)

        # Run EDA
        eda_result = run_eda(dataset_id, target=target)

        # Build EDA context string for downstream agents
        eda_context = self._build_eda_context(eda_result)

        return {
            "eda_result": eda_result,
            "eda_context": eda_context,
        }

    def _build_eda_context(self, eda_result: dict[str, Any]) -> str:
        """Build a concise EDA context string for downstream agents."""
        parts = []

        # Feature types
        ft = eda_result.get("feature_types", {})
        parts.append(f"Features: {ft.get('numeric_count', 0)} numeric, {ft.get('categorical_count', 0)} categorical")

        # Missing values
        mp = eda_result.get("missing_profile", {})
        missing_cols = mp.get("most_missing", [])
        if missing_cols:
            parts.append(f"Missing values in: {', '.join(missing_cols)}")

        # Class balance
        cb = eda_result.get("class_balance", {})
        if cb.get("classes"):
            parts.append(f"Classes: {len(cb['classes'])}, imbalance ratio: {cb.get('imbalance_ratio', 'N/A')}")

        # Correlations
        ch = eda_result.get("correlation_hints", {})
        top_corr = ch.get("top_correlations", [])
        if top_corr:
            top_pair = top_corr[0]
            parts.append(f"Top correlation: {top_pair['feature_a']} vs {top_pair['feature_b']} ({top_pair['correlation']:.3f})")

        # Outliers
        os = eda_result.get("outlier_scan", {})
        numeric_cols = os.get("numeric_columns", [])
        if numeric_cols:
            outlier_counts = [os["columns"][c].get("iqr_outlier_count", 0) for c in numeric_cols]
            if any(c > 0 for c in outlier_counts):
                parts.append("Outliers detected in numeric columns")

        # Leakage
        ls = eda_result.get("leakage_suspects", {})
        suspects = ls.get("suspects", [])
        if suspects:
            parts.append(f"Leakage suspects: {', '.join(s['feature'] for s in suspects)}")

        return "; ".join(parts) if parts else "No significant issues detected"

    async def run_feature_engineering(
        self,
        dataset_id: str,
        target: str,
        eda_context: str,
        goal: str = "",
        provider: Any = None,
    ) -> dict[str, Any]:
        """Run feature engineering: cleaning + try-all."""
        _ = resolve_dataset_path(dataset_id)

        # Run cleaning
        clean_metadata = clean_dataset(
            dataset_id,
            target,
            drop_missing_target=True,
            drop_empty_columns=True,
            one_hot_encode=True,
            numeric_impute_strategy="median",
            categorical_impute_strategy="mode",
        )

        cleaned_dataset_id = clean_metadata["dataset_id"]

        # Run try-all on cleaned data (relative dataset id + workspace root).
        try_all_results = try_all_models(
            dataset=dataset_id_to_relative_path(cleaned_dataset_id),
            target=target,
            seed=42,
            output="scratch",
            workspace_root=_workspace_root(),
            dry_run=True,
        )

        # Get top 3 models
        top_models = [
            {"model": r.get("model"), "status": r.get("status"), "metrics": r.get("metrics")}
            for r in try_all_results[:3]
        ]

        return {
            "cleaned_dataset_id": cleaned_dataset_id,
            "clean_metadata": clean_metadata,
            "try_all_results": try_all_results,
            "top_models": top_models,
        }

    async def run_model_selection(
        self,
        dataset_id: str,
        target: str,
        task_type: str,
        eda_context: str,
        goal: str = "",
        provider: Any = None,
    ) -> dict[str, Any]:
        """Run model selection using try-all and recommend best models."""
        try_all_results = try_all_models(
            dataset=dataset_id_to_relative_path(dataset_id),
            target=target,
            seed=42,
            output="scratch",
            workspace_root=_workspace_root(),
            dry_run=True,
        )

        # Filter completed results
        completed = [r for r in try_all_results if r.get("status") == "completed"]

        # Sort by appropriate metric
        if task_type == "regression":
            completed.sort(key=lambda r: r.get("metrics", {}).get("test_rmse", float("inf")))
        else:
            completed.sort(key=lambda r: -r.get("metrics", {}).get("test_accuracy", 0))

        top_3 = completed[:3]

        return {
            "all_results": try_all_results,
            "top_models": [
                {
                    "model": r.get("model"),
                    "metrics": r.get("metrics"),
                    "status": r.get("status"),
                }
                for r in top_3
            ],
            "recommendation": {
                "best_model": top_3[0].get("model") if top_3 else None,
                "model_grid": [r.get("model") for r in top_3],
                "seeds": [42, 43, 44],
            },
        }

    async def orchestrate(
        self,
        goal: str,
        dataset_id: str,
        target: str,
        feedback: str | None = None,
        provider: LLMProvider | None = None,
        on_event: EventCallback | None = None,
        should_continue: ShouldContinue | None = None,
    ) -> dict[str, Any]:
        """Main orchestration loop: EDA -> Feature Engineering -> Model Selection -> Training.

        ``on_event(stage, message)`` is invoked at each stage boundary so
        callers can stream progress (stage is one of ``planning``, ``cleaning``,
        ``training``, ``evaluating``). ``should_continue()`` returning False
        raises :class:`OrchestrationCancelled` at the next stage boundary or
        batch entry.
        """

        def emit(stage: str, message: str) -> None:
            if on_event is not None:
                on_event(stage, message)

        def check_cancelled() -> bool:
            return should_continue is not None and not should_continue()

        def ensure_not_cancelled() -> None:
            if check_cancelled():
                raise OrchestrationCancelled("experiment cancelled by user")

        experiment_id = generate_experiment_id()

        # Step 1: EDA Analysis
        ensure_not_cancelled()
        emit("planning", "EDAAnalyst analyzing dataset")
        eda_result = await self.run_eda_analysis(dataset_id, target, goal)

        # Step 2: Feature Engineering
        ensure_not_cancelled()
        emit("cleaning", "FeatureEngineer cleaning dataset and computing baselines")
        fe_result = await self.run_feature_engineering(
            dataset_id=dataset_id,
            target=target,
            eda_context=eda_result["eda_context"],
            goal=goal,
        )

        # Step 3: Model Selection
        # Infer task type from EDA
        class_balance_result = eda_result["eda_result"].get("class_balance", {})
        task_type = "regression" if not class_balance_result.get("classes") else "classification"

        ensure_not_cancelled()
        emit("training", "ModelSelector comparing registered models")
        ms_result = await self.run_model_selection(
            dataset_id=fe_result["cleaned_dataset_id"],
            target=target,
            task_type=task_type,
            eda_context=eda_result["eda_context"],
        )

        # Step 4: Run training with best models
        best_models = ms_result.get("recommendation", {}).get("model_grid", [])
        seeds = ms_result.get("recommendation", {}).get("seeds", [42, 43, 44])

        if best_models:
            ensure_not_cancelled()
            emit("training", f"Training {len(best_models)} candidate model(s)")
            worker = self._create_worker(provider)

            proposal = await worker.propose(
                goal=f"Train best models for {goal}",
                dataset=dataset_id_to_relative_path(fe_result["cleaned_dataset_id"]),
                target=target,
                model_grid=best_models,
                seeds=seeds,
            )

            # Approve and run
            self.proposal_store.approve(proposal.proposal_id, principal="orchestrator")
            batch_path = self.proposal_store.write_batch_config(proposal.proposal_id)

            runner = BatchRunner(
                workspace_root=Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))
            )
            entries = runner.load_config(batch_path)

            def on_result(result: Any) -> None:
                emit(
                    "training",
                    f"model {result.entry.model} (seed {result.entry.seed}): {result.status}",
                )

            results = runner.run(
                entries,
                on_result=on_result,
                should_continue=lambda: not check_cancelled(),
            )

            failed = sum(1 for r in results if r.status == "failed")

            emit("evaluating", "Comparing metrics and selecting best run")
            return {
                "experiment_id": experiment_id,
                "status": "completed" if failed == 0 else "partial",
                "eda": eda_result,
                "feature_engineering": fe_result,
                "model_selection": ms_result,
                "training_results": [
                    {
                        "dataset": r.entry.dataset,
                        "target": r.entry.target,
                        "model": r.entry.model,
                        "seed": r.entry.seed,
                        "run_id": r.run_id,
                        "status": r.status,
                        "error": r.error,
                    }
                    for r in results
                ],
            }

        emit("evaluating", "No candidate models completed; stopping")
        return {
            "experiment_id": experiment_id,
            "status": "no_models_found",
            "eda": eda_result,
            "feature_engineering": fe_result,
            "model_selection": ms_result,
        }


def create_orchestrator(
    provider: LLMProvider | None = None,
    runs_root: Path | str | None = None,
    proposals_dir: Path | str | None = None,
) -> ExperimentOrchestrator:
    """Factory function to create an ExperimentOrchestrator."""
    return ExperimentOrchestrator(
        provider=provider,
        runs_root=runs_root,
        proposals_dir=proposals_dir,
    )
