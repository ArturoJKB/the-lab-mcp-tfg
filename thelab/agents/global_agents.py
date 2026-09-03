"""Global supervising agents: Researcher and Coding/Diagnosis.

Both agents operate over typed artifacts and MCP-mediated tools. They do not
exchange free-form messages directly; the Researcher reads workspace/context
evidence, and the Diagnosis agent controls the worker through the same
proposal/approval artifacts used by humans.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from thelab.agents.grounding import METRIC_TOLERANCE, extract_metric_claims, extract_run_ids
from thelab.context.reader import ContextReader
from thelab.eda import class_balance, outlier_scan
from thelab.mcp.common import load_json_artifact, load_text_artifact
from thelab.run.model_registry import MODEL_REGISTRY
from thelab.run.profile import read_csv

from .worker import ProposalStore, WorkerAgent

_ALLOWLISTED_ARTIFACTS = {
    "manifest": "manifest.json",
    "metrics": "metrics.json",
    "validation_report": "validation_report.json",
    "data_profile": "data_profile.json",
    "model_card": "model_card.md",
}

def _is_citable(text: str, runs_root: Path) -> tuple[bool, dict[str, Any]]:
    """Return (citable, citation_map) for *text* against workspace artifacts.

    A claim is citable when every run_id it mentions exists and every metric
    claim matches the corresponding metrics.json within tolerance.
    """
    run_ids = extract_run_ids(text)
    if not run_ids:
        return False, {}

    citations: dict[str, Any] = {}
    for run_id in run_ids:
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None:
            return False, {}
        metrics = load_json_artifact(runs_root, run_id, "metrics.json")
        claims = extract_metric_claims(text)
        for key, claimed in claims.items():
            if metrics is None or key not in metrics:
                continue
            actual = float(metrics[key])
            if abs(claimed - actual) > METRIC_TOLERANCE:
                return False, {}
            citations[f"{run_id}:{key}"] = {"run_id": run_id, "source": "metrics.json", "value": actual}
        if not claims:
            citations[run_id] = {"run_id": run_id, "source": "manifest.json"}

    return True, citations


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitter that preserves metric references."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


class Researcher:
    """Citation-heavy answer agent grounded in allowlisted artifacts."""

    def __init__(
        self,
        runs_root: Path | str,
        context_db_path: Path | str | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.context_db_path = context_db_path

    def _load_artifact(self, run_id: str, artifact_type: str) -> dict[str, Any] | str | None:
        filename = _ALLOWLISTED_ARTIFACTS.get(artifact_type)
        if filename is None:
            return None
        if filename.endswith(".md"):
            return load_text_artifact(self.runs_root, run_id, filename)
        return load_json_artifact(self.runs_root, run_id, filename)

    def _prior_decisions(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if self.context_db_path is None:
            return []
        reader = ContextReader(self.context_db_path)
        if not reader.initialized:
            return []
        entries = reader.search(query="proposal approve reject", run_id=run_id, limit=10)
        return [
            {
                "event_id": entry.event_id,
                "timestamp": entry.timestamp.isoformat(),
                "summary": entry.redacted_summary,
            }
            for entry in entries
        ]

    def answer(
        self,
        question: str,
        run_id: str | None = None,
        draft: str | None = None,
    ) -> dict[str, Any]:
        """Answer a question using only allowlisted artifacts and prior context.

        If *draft* is provided, each sentence is checked for citability and
        uncitable sentences are dropped. If no draft is provided, a baseline
        answer is built deterministically from the artifacts.
        """
        if run_id is None:
            # No specific run: search context for relevant prior summaries.
            prior = self._prior_decisions()
            return {
                "answer": (
                    "No specific run_id was provided. "
                    f"Found {len(prior)} prior decision(s) in local context."
                ),
                "citations": {},
                "prior_decisions": prior,
            }

        manifest = self._load_artifact(run_id, "manifest")
        metrics = self._load_artifact(run_id, "metrics")
        validation_report = self._load_artifact(run_id, "validation_report")
        _data_profile = self._load_artifact(run_id, "data_profile")
        _model_card = self._load_artifact(run_id, "model_card")
        prior = self._prior_decisions(run_id=run_id)

        if manifest is None:
            return {
                "answer": f"No workspace evidence found for run_id {run_id}.",
                "citations": {},
                "prior_decisions": prior,
            }

        if draft:
            sentences = _split_sentences(draft)
            kept: list[str] = []
            all_citations: dict[str, Any] = {}
            for sentence in sentences:
                citable, citations = _is_citable(sentence, self.runs_root)
                if citable:
                    kept.append(sentence)
                    all_citations.update(citations)
            answer = " ".join(kept) if kept else "No verifiable claims could be made from the provided draft."
        else:
            # Deterministic baseline answer.
            parts = [f"Run {run_id} is present in the workspace."]
            if isinstance(metrics, dict):
                if "test_accuracy" in metrics:
                    parts.append(f"test_accuracy is {metrics['test_accuracy']}.")
                if "test_rmse" in metrics:
                    parts.append(f"test_rmse is {metrics['test_rmse']}.")
            if isinstance(validation_report, dict) and validation_report.get("valid"):
                parts.append("Validation passed.")
            answer = " ".join(parts)
            citable, all_citations = _is_citable(answer, self.runs_root)
            if not citable:
                all_citations = {}

        return {
            "answer": answer,
            "citations": all_citations,
            "prior_decisions": prior,
            "artifacts_consulted": list(_ALLOWLISTED_ARTIFACTS.keys()),
        }


class DiagnosisAgent:
    """Supervising agent that assigns goals to the worker and approves/rejects proposals."""

    def __init__(
        self,
        worker: WorkerAgent,
        proposal_store: ProposalStore,
        principal: str = "diagnosis_agent",
        runs_root: Path | str | None = None,
        context_db_path: Path | str | None = None,
    ) -> None:
        self.worker = worker
        self.store = proposal_store
        self.principal = principal
        self.runs_root = Path(runs_root) if runs_root else None
        self.context_db_path = context_db_path

    def _goal_from_input(
        self,
        error_summary: str | None,
        validation_report: dict[str, Any] | None,
        run_id: str | None,
    ) -> str:
        if error_summary:
            return f"Diagnose and fix: {error_summary}"
        if validation_report:
            failed = [c for c in validation_report.get("checks", []) if not c.get("passed")]
            messages = [c.get("message", "validation issue") for c in failed]
            return f"Address validation issues: {'; '.join(messages)}"
        if run_id:
            return f"Investigate run {run_id} and propose a recovery experiment"
        return "Propose a sensible baseline experiment"

    @staticmethod
    def _is_unrecoverable(error_summary: str | None, validation_report: dict[str, Any] | None) -> bool:
        """Return True when the failure cannot be fixed by a different model/seed."""
        if error_summary:
            lowered = error_summary.lower()
            if any(phrase in lowered for phrase in ("target column", "dataset not found", "no feature columns")):
                return True
        if validation_report:
            failed_checks = validation_report.get("checks", [])
            unrecoverable_checks = {
                "target_column_exists",
                "at_least_one_feature",
                "dataset_not_empty",
                "features_numeric",
            }
            for check in failed_checks:
                if not check.get("passed") and check.get("check") in unrecoverable_checks:
                    return True
        return False

    @staticmethod
    def _augment_grid_for_data(
        base_grid: list[str],
        dataset_path: Path,
        target: str,
    ) -> tuple[list[str], dict[str, list[Any]]]:
        """Adjust model grid and hyperparameters based on EDA signals."""
        df = read_csv(dataset_path)
        balance = class_balance(df, target=target)
        outliers = outlier_scan(df, target=target)

        grid = list(base_grid)
        hp_grid: dict[str, list[Any]] = {}

        # Imbalance: include class-weighted models if available.
        if balance.get("min_class_warning"):
            for candidate in ("svc", "sgd_classifier", "logistic_regression"):
                if candidate in MODEL_REGISTRY.list_models() and candidate not in grid:
                    grid.append(candidate)
            hp_grid.setdefault("class_weight", ["balanced"])

        # High outlier rate: prefer robust/ensemble models.
        high_outlier_rate = any(
            col.get("iqr_outlier_rate", 0) > 0.05 or col.get("z_outlier_rate", 0) > 0.05
            for col in outliers.get("columns", {}).values()
        )
        if high_outlier_rate:
            for candidate in ("random_forest", "hist_gradient_boosting"):
                if candidate in MODEL_REGISTRY.list_models() and candidate not in grid:
                    grid.append(candidate)

        return grid, hp_grid

    def _prior_decisions(self, dataset: str) -> list[dict[str, Any]]:
        if self.context_db_path is None:
            return []
        reader = ContextReader(self.context_db_path)
        if not reader.initialized:
            return []
        entries = reader.search(query=f"{dataset} proposal", limit=10)
        return [
            {
                "event_id": entry.event_id,
                "timestamp": entry.timestamp.isoformat(),
                "summary": entry.redacted_summary,
            }
            for entry in entries
        ]

    async def handle(
        self,
        dataset: str,
        target: str,
        error_summary: str | None = None,
        validation_report: dict[str, Any] | None = None,
        run_id: str | None = None,
        model_grid: list[str] | None = None,
        seeds: list[int] | None = None,
        hyperparameter_grid: dict[str, list[Any]] | None = None,
    ) -> dict[str, Any]:
        """Produce a proposal for the diagnosed problem and decide approval.

        The agent writes the proposal, then either approves or rejects it based
        on whether the underlying problem is recoverable through model/seed
        changes. Validation reports and EDA signals inform the grid.
        """
        prior = self._prior_decisions(dataset)
        goal = self._goal_from_input(error_summary, validation_report, run_id)

        # EDA-driven grid augmentation.
        dataset_path = Path(dataset)
        if self.runs_root and not dataset_path.is_absolute():
            dataset_path = self.runs_root.parent / dataset_path
        augmented_grid = model_grid
        augmented_hp = hyperparameter_grid
        if dataset_path.is_file():
            augmented_grid, augmented_hp = self._augment_grid_for_data(
                augmented_grid or [], dataset_path, target
            )
            if hyperparameter_grid:
                augmented_hp.update(hyperparameter_grid)

        proposal = await self.worker.propose(
            goal=goal,
            dataset=dataset,
            target=target,
            model_grid=augmented_grid,
            seeds=seeds,
            hyperparameter_grid=augmented_hp or None,
        )

        if self._is_unrecoverable(error_summary, validation_report) or not proposal.model_grid:
            rejection_path = self.store.reject(
                proposal.proposal_id,
                principal=self.principal,
                reason=error_summary or "unrecoverable validation failure",
            )
            return {
                "status": "rejected",
                "proposal_id": proposal.proposal_id,
                "principal": self.principal,
                "rejection_path": str(rejection_path),
                "prior_decisions": prior,
            }

        approval_path = self.store.approve(proposal.proposal_id, principal=self.principal)
        batch_path = self.store.write_batch_config(proposal.proposal_id)
        return {
            "status": "approved",
            "proposal_id": proposal.proposal_id,
            "principal": self.principal,
            "approval_path": str(approval_path),
            "batch_config_path": str(batch_path),
            "prior_decisions": prior,
        }
