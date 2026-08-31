"""Generated research notebooks for completed runs (P3.6).

Builds an nbformat-4 notebook dict describing one run: manifest summary,
dataset load, an exact reproduce cell, metrics/validation output, the
artifact index, and findings. Generated on demand — nothing is written into
the run directory, so manifest artifact hashes stay untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from thelab.mcp.common import get_runs_root, load_json_artifact


def _md(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def _code(source: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _artifact_names(manifest: dict[str, Any]) -> list[str]:
    names = [str(ref.get("artifact_type", "")) for ref in manifest.get("artifact_refs", [])]
    names = [n for n in names if n]
    names.append("model_card.md")
    return sorted(set(names))


def _reproduce_source(inputs: dict[str, Any], training_config: dict[str, Any]) -> str:
    estimator = (training_config or {}).get("estimator") or {}
    hyper = estimator.get("hyperparameters") or {}
    hyper_line = f",\n    hyperparameters={json.dumps(hyper)}" if hyper else ""
    return (
        "from thelab.run.runner import run_model\n"
        "\n"
        "result = run_model(\n"
        f"    dataset={inputs.get('dataset', '')!r},\n"
        f"    target={inputs.get('target', '')!r},\n"
        f"    model={inputs.get('model', '')!r},\n"
        f"    seed={inputs.get('seed', 42)!r},\n"
        f"    output={inputs.get('output', 'runs')!r},\n"
        f"    task_type={inputs.get('task_type', 'auto')!r}"
        f"{hyper_line},\n"
        ")\n"
        'print(result["status"])\n'
        'print(result["metrics"])'
    )


def _metrics_source(run_dir: str) -> str:
    return (
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        f"run_dir = Path({run_dir!r})\n"
        'metrics = json.loads((run_dir / "metrics.json").read_text())\n'
        "print(json.dumps(metrics, indent=2))\n"
        "\n"
        'validation = json.loads((run_dir / "validation_report.json").read_text())\n'
        'print("valid:", validation.get("valid"))\n'
        'for check in validation.get("checks", []):\n'
        "    if not check.get(\"passed\"):\n"
        '        print("FAILED:", check["check"], "-", check["message"])'
    )


def _findings_markdown(manifest: dict[str, Any], validation: dict[str, Any] | None) -> str:
    lines: list[str] = ["## Findings", ""]
    if manifest.get("final_status") == "rejected":
        lines.append(f"- **Rejected**: {manifest.get('error_summary') or 'validation failed'}")
    warnings = (validation or {}).get("warnings") or []
    for warning in warnings:
        lines.append(f"- Warning: {warning}")
    if manifest.get("final_status") != "rejected" and not warnings:
        lines.append("- No validation warnings recorded for this run.")
    lines.extend(
        [
            "",
            "Reproduce this run with the cell above, or via the CLI:",
            "",
            "```bash",
            "thelab run model --dataset <dataset> --target <target> --model <model> \\",
            "  --seed <seed> --output runs",
            "```",
        ]
    )
    return "\n".join(lines)


def generate_run_notebook(run_id: str, runs_root: Path | str | None = None) -> dict[str, Any]:
    """Build the research notebook dict for *run_id*.

    Raises ``FileNotFoundError`` when the run (or its manifest) does not exist.
    """
    root = Path(runs_root) if runs_root else Path(get_runs_root())
    manifest = load_json_artifact(root, run_id, "manifest.json")
    if manifest is None:
        raise FileNotFoundError(f"run not found: {run_id}")

    inputs = load_json_artifact(root, run_id, "inputs.json") or {}
    training_config = manifest.get("training_config") or {}
    validation = load_json_artifact(root, run_id, "validation_report.json")

    task_type = inputs.get("task_type") or manifest.get("task_type") or "classification"
    dataset_value = inputs.get("dataset", "")
    run_id_value = manifest.get("run_id", run_id)
    artifact_refs = manifest.get("artifact_refs") or []
    artifact_rows = "\n".join(
        f"| {ref.get('artifact_type', ref.get('path', '?'))} | `runs/{run_id}/{Path(str(ref.get('path', '') )).name}` |"
        for ref in artifact_refs
    )

    summary_md = f"""# The Lab — Run report

Reproducible notebook generated for run `{run_id_value}`.

| Field | Value |
|---|---|
| Model | {inputs.get("model", "unknown")} |
| Seed | {inputs.get("seed", manifest.get("random_seed", "unknown"))} |
| Task type | {task_type} |
| Dataset | `{dataset_value}` |
| Target | {inputs.get("target", "unknown")} |
| Status | {manifest.get("final_status")} (validation: {manifest.get("validation_status")}) |
| Started | {manifest.get("started_at", "")} |
| Finished | {manifest.get("finished_at", "")} |

Dependency versions are recorded in `manifest.json`; the cell below retrains
with the exact recorded parameters.
"""

    artifacts_md = (
        "## Artifacts\n\n"
        "| Artifact | Path |\n|---|---|\n"
        + artifact_rows
        + "\n\nThe model card is the human-readable summary: "
        f"`runs/{run_id}/model_card.md`."
    )

    cells = [
        _md(summary_md),
        _code(
            f"from pathlib import Path\n\n"
            f"DATASET = {dataset_value!r}\n"
            f"RUN_ID = {run_id_value!r}\n"
            f'print("Dataset:", DATASET)\n'
            f'print("Run:", RUN_ID)'
        ),
        _code(_reproduce_source(inputs, training_config)),
        _code(_metrics_source(f"runs/{run_id}")),
        _md(artifacts_md),
        _md(_findings_markdown(manifest, validation)),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "thelab": {
                "run_id": run_id_value,
                "final_status": manifest.get("final_status"),
                "validation_status": manifest.get("validation_status"),
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
