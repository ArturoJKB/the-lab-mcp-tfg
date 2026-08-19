"""Batch runner for systematic multi-experiment execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .runner import run_model


@dataclass
class BatchEntry:
    """Single experiment configuration within a batch."""

    dataset: str
    target: str
    model: str
    seed: int


@dataclass
class BatchResult:
    """Outcome for a single batch entry."""

    entry: BatchEntry
    run_id: str | None = None
    status: str = "pending"
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BatchRunner:
    """Run many experiments from a JSON config and produce a summary."""

    def __init__(self, workspace_root: Path | None = None):
        self.workspace_root = workspace_root or Path.cwd()

    def load_config(self, config_path: Path) -> list[BatchEntry]:
        """Load and validate a batch JSON config."""
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("batch config must be a JSON list of run entries")
        entries = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"batch entry {idx} must be an object")
            for key in ("dataset", "target", "model", "seed"):
                if key not in item:
                    raise ValueError(f"batch entry {idx} missing required key: {key}")
            entries.append(
                BatchEntry(
                    dataset=str(item["dataset"]),
                    target=str(item["target"]),
                    model=str(item["model"]),
                    seed=int(item["seed"]),
                )
            )
        return entries

    def run(
        self,
        entries: list[BatchEntry],
        output: str = "runs",
    ) -> list[BatchResult]:
        """Execute all entries, continuing past individual failures."""
        results: list[BatchResult] = []
        for entry in entries:
            result = BatchResult(entry=entry)
            try:
                outcome = run_model(
                    dataset=entry.dataset,
                    target=entry.target,
                    model=entry.model,
                    seed=entry.seed,
                    output=output,
                    workspace_root=self.workspace_root,
                )
                result.run_id = outcome.get("run_id")
                result.status = outcome.get("status", "unknown")
                result.metrics = outcome.get("metrics", {})
                result.error = outcome.get("error")
            except Exception as exc:  # noqa: BLE001
                result.status = "failed"
                result.error = str(exc)
            results.append(result)
        return results

    def write_summary(
        self,
        results: list[BatchResult],
        output_path: Path,
    ) -> None:
        """Write a JSON summary of the batch run."""
        summary = {
            "started_at": datetime.now(UTC).isoformat(),
            "total": len(results),
            "completed": sum(1 for r in results if r.status == "completed"),
            "rejected": sum(1 for r in results if r.status == "rejected"),
            "failed": sum(1 for r in results if r.status == "failed"),
            "results": [
                {
                    "dataset": r.entry.dataset,
                    "target": r.entry.target,
                    "model": r.entry.model,
                    "seed": r.entry.seed,
                    "run_id": r.run_id,
                    "status": r.status,
                    "metrics": r.metrics,
                    "error": r.error,
                }
                for r in results
            ],
        }
        output_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")


def write_markdown_report(
    results: list[BatchResult],
    report_path: Path,
) -> None:
    """Write a human-readable Markdown batch report."""
    completed = [r for r in results if r.status == "completed"]
    rejected = [r for r in results if r.status == "rejected"]
    failed = [r for r in results if r.status == "failed"]

    lines = [
        "# Batch Run Report",
        "",
        "## Summary",
        f"- Total experiments: {len(results)}",
        f"- Completed: {len(completed)}",
        f"- Rejected: {len(rejected)}",
        f"- Failed: {len(failed)}",
        "",
        "## Results",
        "",
        "| Dataset | Target | Model | Seed | Status | Test Accuracy | Test F1 Macro | Error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        metrics = r.metrics or {}
        acc = metrics.get("test_accuracy")
        f1 = metrics.get("test_f1_macro")
        acc_str = f"{acc:.6f}" if acc is not None else "-"
        f1_str = f"{f1:.6f}" if f1 is not None else "-"
        error = (r.error or "").replace("|", "\\|")
        lines.append(
            f"| {r.entry.dataset} | {r.entry.target} | {r.entry.model} | "
            f"{r.entry.seed} | {r.status} | {acc_str} | {f1_str} | {error} |"
        )

    if failed:
        lines.extend(["", "## Failures", ""])
        for r in failed:
            lines.append(f"- `{r.entry.model}` on `{r.entry.dataset}`: {r.error}")

    if rejected:
        lines.extend(["", "## Rejections", ""])
        for r in rejected:
            lines.append(f"- `{r.entry.model}` on `{r.entry.dataset}`: {r.error}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
