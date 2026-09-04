#!/usr/bin/env python3
"""Harvest P6 findings from recorded workspace evidence (P6.B.0).

Scans local artifacts for failures and emits evidence-backed ticket skeletons
into ``docs/P6_FINDINGS.md``. Every ticket cites its evidence (run/experiment/
job paths); known signatures already fixed in P5 are marked ``applied`` with
the commit. Deterministic: output is sorted and stable, no timestamps.

Scanned sources:
- ``runs/<run_id>/events.jsonl``   -> run_failed / run_rejected error messages
- ``.thelab/experiments/*.json``   -> failed experiment errors
- ``.thelab/jobs/*.json``          -> failed background jobs

Usage:
    python scripts/harvest_findings.py                    # write P6_FINDINGS.md
    python scripts/harvest_findings.py --runs <dir> ...   # custom sources
    python scripts/harvest_findings.py --format json      # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Known signatures: (pattern, title, root cause, fix hint, status)
# Ordered: first match wins.
# ---------------------------------------------------------------------------

_KNOWN_SIGNATURES: list[tuple[str, str, str, str, str]] = [
    (
        r"unexpected keyword argument",
        "Foreign hyperparameters passed to estimator constructor",
        "Shared LLM hyperparameter grids contained params that do not exist on every model in the grid",
        "Per-model filtering via ModelRegistry.valid_param_keys at batch translation",
        "applied",
    ),
    (
        r"candidate (training runs|models) (failed|completed)",
        "Experiment completed with zero trained models",
        "Status laundering: all-failing batches were reported as completed experiments",
        "Honest status mapping in jobs._run_experiment (P5 audit BUG 1b)",
        "applied",
    ),
    (
        r"only uploaded datasets can be cleaned",
        "Fixture datasets rejected mid-orchestration",
        "Orchestrator attempted cleaning on fixtures/* which the cleaning API rejects",
        "Fixtures skip cleaning (P5 audit BUG 2); provider-blame removed via OrchestrationFailed",
        "applied",
    ),
    (
        r"is a (regression|classification) model, but the dataset resolves to",
        "Wrong-task models in the training grid",
        "Model selection did not filter the registry by inferred task type",
        "Task-aware selection + deterministic post-filter (thelab/ide/agentic_round.py)",
        "applied",
    ),
    (
        r"provider '.*' failed during orchestration: target column '([^']+)' not found",
        "Invalid target column accepted at experiment entry",
        "POST /experiment/run validates the dataset but not the target column; "
        "the failure surfaces mid-orchestration wrapped as a provider failure",
        "Validate target against dataset columns at experiment entry; report "
        "deterministic failures via OrchestrationFailed",
        "proposed",
    ),
    (
        r"is already cleaned",
        "Re-running an experiment on an already-cleaned dataset id fails",
        "Re-cleaning guard treats the cleaned id as invalid instead of idempotent",
        "Idempotent re-clean: return the existing cleaned dataset_id with a note",
        "proposed",
    ),
    (
        r"target column '([^']+)' not found",
        "Invalid target column accepted at experiment entry",
        "POST /experiment/run validates the dataset but not the target column; "
        "the failure surfaces mid-orchestration wrapped as a provider failure",
        "Validate target against dataset columns at experiment entry; report "
        "deterministic failures via OrchestrationFailed",
        "proposed",
    ),
    (
        r"unhashable type: 'numpy\.ndarray'",
        "EDA crashes on array-valued columns",
        "run_eda correlation/missing profiling assumes scalar columns; list/array "
        "columns (e.g. from naive JSON ingestion) break it",
        "Guard EDA stage against non-scalar column dtypes with a traceable "
        "OrchestrationFailed message",
        "proposed",
    ),
    (
        r"constant feature columns found",
        "Constant feature columns rejected by validation",
        "Validation guardrail: constant columns carry no signal",
        "By-design first-class rejection (P0 AC-02); optionally surfaced by the "
        "cleaning policy as a drop report entry",
        "applied",
    ),
    (
        r"target column contains \d+ missing",
        "Target column with missing values rejected",
        "Validation guardrail: drop_missing_target policy or explicit rejection",
        "By-design first-class rejection (PRD AC-02)",
        "applied",
    ),
    (
        r"not all feature columns are numeric",
        "Non-numeric feature columns rejected before training",
        "Cleaning policy (cardinality-aware encoding) did not run on this dataset; "
        "the factory requires numeric features",
        "By-design first-class rejection; run the cleaning policy first",
        "applied",
    ),
    (
        r"is limited to \d+ training rows",
        "Scale guard rejected an impractical model/dataset pair",
        "Registry scale guards reject super-linear models on large datasets",
        "By-design first-class rejection (P2.6.5 scale guards)",
        "applied",
    ),
    (
        r"(invalid dataset_id|dataset not found|escapes root)",
        "Unsafe or unknown dataset id rejected",
        "Path-safety validation rejected the id",
        "By-design first-class rejection (path safety)",
        "applied",
    ),
    (
        r"'str' object has no attribute 'get'",
        "Tool/provider payload treated as dict when it was a string",
        "A response payload bypassed strict JSON parsing and was used as a dict "
        "downstream (recorded in a failed job)",
        "Parse tool responses strictly at the boundary (json.loads + typed "
        "contract) so string payloads fail at parse time, not at use time",
        "proposed",
    ),
    (
        r"\[(config|network)\]",
        "Provider configuration or connectivity failure",
        "Dead/misconfigured LLM provider",
        "Fail-fast with named provider and hint (implemented); run the provider "
        "setup check before starting live sessions",
        "applied",
    ),
]

_SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "note": 3}


@dataclass
class Finding:
    """One grouped evidence-backed finding."""

    signature: str
    title: str
    root_cause: str
    fix: str
    status: str
    severity: str
    category: str  # run | experiment | job
    evidence: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


def _normalize_error(text: str) -> str:
    """Normalize an error message into a grouping signature."""
    text = re.sub(r"run-\d{8}-\d{6}-[0-9a-f]{8}", "<run_id>", text)
    text = re.sub(r"exp-\d{8}-\d{6}-[0-9a-f]{8}", "<experiment_id>", text)
    text = re.sub(r"job-\d{8}-\d{6}-[0-9a-f]{8}", "<job_id>", text)
    text = re.sub(r"prop-\S+", "<proposal_id>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*", "<timestamp>", text)
    text = re.sub(r"'[^']{20,}'", "'<long>'", text)
    return text.strip()


def _classify_severity(signature: str, category: str) -> str:
    lowered = signature.lower()
    if "unexpected keyword argument" in lowered:
        return "major"
    if "candidate training runs failed" in lowered or "no candidate models" in lowered:
        return "major"
    if "provider" in lowered and "failed" in lowered:
        return "major"
    note_markers = (
        "resolves to",
        "scale guard",
        "limited to",
        "constant feature columns",
        "target column contains",
        "not all feature columns are numeric",
        "invalid dataset_id",
        "dataset not found",
        "escapes root",
    )
    if any(marker in lowered for marker in note_markers):
        return "note"  # traceable rejection, first-class by design
    if "sandbox" in lowered or "import not allowed" in lowered:
        return "minor"
    return "minor" if category == "run" else "minor"


def _match_known(signature: str) -> tuple[str, str, str, str] | None:
    for pattern, title, root_cause, fix, status in _KNOWN_SIGNATURES:
        if re.search(pattern, signature, re.IGNORECASE):
            return title, root_cause, fix, status
    return None


def _add(findings: dict[str, Finding], category: str, error: str, evidence: str) -> None:
    if not error or not error.strip():
        return
    signature = _normalize_error(error)
    # Known signatures match on the RAW error text: normalization collapses
    # quoted strings and would destroy the distinguishing patterns.
    known = _match_known(error)
    if known is None:
        known = _match_known(signature)
    title, root_cause, fix, status = known or (
        "Unclassified failure",
        "see evidence (no recorded hypothesis)",
        "triage: reproduce from the cited evidence, then classify",
        "proposed",
    )
    severity = _classify_severity(error + " " + signature, category)
    if severity == "note" and known is None:
        severity = "minor"
    # Known signatures group under their title (one ticket per known hole,
    # regardless of message variants); unknown ones group by raw signature.
    group_key = title if known is not None else signature
    finding = findings.get(group_key)
    if finding is None:
        findings[group_key] = Finding(
            signature=signature,
            title=title,
            root_cause=root_cause,
            fix=fix,
            status=status,
            severity=severity,
            category=category,
        )
        finding = findings[group_key]
    if evidence not in finding.evidence:
        finding.evidence.append(evidence)
    if error not in finding.samples and len(finding.samples) < 3:
        finding.samples.append(error)


def scan_runs(runs_root: Path) -> dict[str, Finding]:
    findings: dict[str, Finding] = {}
    for run_dir in sorted(runs_root.glob("run-*")):
        events = run_dir / "events.jsonl"
        if not events.is_file():
            continue
        for line in events.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event_type") not in {"run_failed", "run_rejected"}:
                continue
            error = str((event.get("data") or {}).get("error") or event.get("message") or "")
            _add(findings, "run", error, evidence=str(run_dir))
    return findings


def scan_experiments(experiments_dir: Path) -> dict[str, Finding]:
    findings: dict[str, Finding] = {}
    if not experiments_dir.is_dir():
        return findings
    for path in sorted(experiments_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("state") != "failed" or not data.get("error"):
            continue
        _add(findings, "experiment", str(data.get("error")), evidence=str(path))
    return findings


def scan_jobs(jobs_dir: Path) -> dict[str, Finding]:
    findings: dict[str, Finding] = {}
    if not jobs_dir.is_dir():
        return findings
    for path in sorted(jobs_dir.glob("job-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") != "failed" or not data.get("error"):
            continue
        _add(findings, "job", str(data.get("error")), evidence=str(path))
    return findings


def render_markdown(
    findings: dict[str, Finding], sources: list[str]
) -> str:
    ordered = sorted(
        findings.values(),
        key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.signature),
    )
    counts = {s: sum(1 for f in ordered if f.severity == s) for s in _SEVERITY_ORDER}
    lines = [
        "# P6 Findings — Hole & Fix Log",
        "",
        "Harvested deterministically by `scripts/harvest_findings.py` from",
        "recorded workspace evidence: " + ", ".join(f"`{s}`" for s in sources) + ".",
        "Every ticket cites its evidence; known signatures fixed in P5 are",
        "marked `applied`. Remaining `proposed` tickets are the P6.B.1 backlog.",
        "",
        f"**Summary:** {len(ordered)} findings — "
        + ", ".join(f"{s}: {n}" for s, n in counts.items() if n)
        + ".",
        "",
    ]
    for i, finding in enumerate(ordered, 1):
        ticket_id = f"P6-BLK-{i:03d}"
        lines += [
            f"### {ticket_id}: {_collapse(finding.title)}",
            f"- Severity:   {finding.severity}",
            f"- Category:   {finding.category}",
            f"- Symptom:    {_collapse(finding.signature)}",
            f"- Evidence:   {', '.join(f'`{e}`' for e in finding.evidence[:8])}"
            + (f" (+{len(finding.evidence) - 8} more)" if len(finding.evidence) > 8 else ""),
            f"- Samples:    {_collapse(finding.samples[0]) if finding.samples else '—'}",
            f"- Root cause: {finding.root_cause}",
            f"- Fix:        {finding.fix}",
            f"- Status:     {finding.status}",
            "",
        ]
    return "\n".join(lines)


def _collapse(text: str, limit: int = 160) -> str:
    text = str(text).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest P6 findings from workspace evidence")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--jobs", type=Path, default=Path(".thelab/jobs"))
    parser.add_argument("--experiments", type=Path, default=Path(".thelab/experiments"))
    parser.add_argument("--out", type=Path, default=Path("docs/P6_FINDINGS.md"))
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args(argv)

    findings: dict[str, Finding] = {}
    for scan, directory in (
        (scan_runs, args.runs),
        (scan_experiments, args.experiments),
        (scan_jobs, args.jobs),
    ):
        for finding in scan(directory).values():
            # Merge across sources by title (known signatures) or signature
            # (unclassified) — one ticket per hole regardless of source.
            key = finding.title if finding.title != "Unclassified failure" else finding.signature
            existing = findings.get(key)
            if existing is None:
                findings[key] = finding
            else:
                existing.evidence.extend(
                    e for e in finding.evidence if e not in existing.evidence
                )
                existing.samples.extend(
                    s for s in finding.samples if s not in existing.samples
                )

    if args.format == "json":
        payload = [
            {
                "signature": f.signature,
                "title": f.title,
                "severity": f.severity,
                "status": f.status,
                "category": f.category,
                "occurrences": len(f.evidence),
                "evidence": f.evidence,
            }
            for f in sorted(
                findings.values(),
                key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.signature),
            )
        ]
        print(json.dumps(payload, indent=2))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_markdown(findings, [args.runs.as_posix(), args.jobs.as_posix(), args.experiments.as_posix()]),
        encoding="utf-8",
    )
    print(f"findings written to {args.out} ({len(findings)} signatures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
