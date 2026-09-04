"""Tests for the P6.B.0 findings harvester (scripts/harvest_findings.py).

The harvester turns recorded workspace evidence (runs, jobs, experiments)
into grouped, severity-ordered ticket skeletons. Known signatures fixed in
P5 must merge into one ticket marked `applied`; by-design guardrails must be
severity `note`; unclassified failures stay `proposed`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HARVESTER = Path(__file__).resolve().parents[1] / "scripts" / "harvest_findings.py"


def _load_harvester():
    import sys

    spec = importlib.util.spec_from_file_location("harvest_findings", _HARVESTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harvester():
    return _load_harvester()


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    runs = tmp_path / "runs"
    jobs = tmp_path / "jobs"
    experiments = tmp_path / "experiments"
    for d in (runs, jobs, experiments):
        d.mkdir()

    def run(run_id: str, event_type: str, error: str) -> Path:
        run_dir = runs / run_id
        run_dir.mkdir()
        events = run_dir / "events.jsonl"
        events.write_text(
            json.dumps(
                {
                    "event_type": event_type,
                    "run_id": run_id,
                    "data": {"error": error},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return run_dir

    # Two known-signature failures with different message variants -> one ticket
    run("run-20260824-220409-14a52bf6", "run_failed",
        "LinearRegression.__init__() got an unexpected keyword argument 'alpha'")
    run("run-20260903-033052-71d7cbaf", "run_failed",
        "RandomForestClassifier.__init__() got an unexpected keyword argument 'C'")
    # A by-design rejection -> severity note, applied status
    run("run-20260825-193427-92a7db9e", "run_rejected",
        "target column contains 12783 missing values")
    # An unclassified failure -> proposed
    run("run-20260829-144653-a5b569af", "run_failed",
        "totally novel failure mode")

    # Failed experiment (known signature) + a provider failure
    (experiments / "exp-20260829-144800-10e853b5.json").write_text(
        json.dumps({"state": "failed", "error": "no candidate models completed"}),
        encoding="utf-8",
    )
    (experiments / "exp-20260901-173434-e18e0bca.json").write_text(
        json.dumps(
            {
                "state": "failed",
                "error": "provider 'openrouter' failed during orchestration: "
                "target column 'IsActiveMemeber' not found",
            }
        ),
        encoding="utf-8",
    )
    return {"runs": runs, "jobs": jobs, "experiments": experiments}


def test_known_signatures_merge_into_one_applied_ticket(harvester, workspace):
    findings = harvester.scan_runs(workspace["runs"])
    merged = [f for f in findings.values() if "unexpected keyword" in f.title.lower() or "foreign" in f.title.lower()]
    assert len(merged) == 1, f"known variants must merge: {[f.signature for f in merged]}"
    finding = merged[0]
    assert finding.status == "applied"
    assert len(finding.evidence) == 2


def test_by_design_rejections_are_notes(harvester, workspace):
    findings = harvester.scan_runs(workspace["runs"])
    missing_target = [
        f for f in findings.values() if "missing" in f.signature
    ]
    assert missing_target, "expected the missing-target rejection to be harvested"
    assert all(f.severity == "note" for f in missing_target)
    assert all(f.status == "applied" for f in missing_target)  # by-design guardrail


def test_unclassified_stays_proposed(harvester, workspace):
    findings = harvester.scan_runs(workspace["runs"])
    unclassified = [f for f in findings.values() if f.title == "Unclassified failure"]
    assert len(unclassified) == 1
    assert unclassified[0].status == "proposed"
    assert "totally novel failure mode" in unclassified[0].signature


def test_markdown_renders_sorted_tickets(harvester, workspace, tmp_path: Path):
    findings: dict = {}
    for scan, directory in (
        (harvester.scan_runs, workspace["runs"]),
        (harvester.scan_jobs, workspace["jobs"]),
        (harvester.scan_experiments, workspace["experiments"]),
    ):
        for finding in scan(directory).values():
            key = finding.title if finding.title != "Unclassified failure" else finding.signature
            findings.setdefault(key, finding)

    markdown = harvester.render_markdown(
        findings, ["runs", ".thelab/jobs", ".thelab/experiments"]
    )
    assert "# P6 Findings — Hole & Fix Log" in markdown
    assert "P6-BLK-001" in markdown
    # applied tickets come before proposed ones within a severity band:
    applied_pos = markdown.index("Status:     applied")
    proposed_pos = markdown.index("Status:     proposed")
    assert applied_pos < proposed_pos


def test_cli_end_to_end(tmp_path: Path):
    spec = _load_harvester()
    runs = tmp_path / "runs"
    run_dir = runs / "run-20260903-000000-00000000"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "run_failed", "data": {"error": "boom: new hole"}}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "FINDINGS.md"
    rc = spec.main(["--runs", str(runs), "--out", str(out)])
    assert rc == 0
    content = out.read_text(encoding="utf-8")
    assert "P6-BLK-001" in content
    assert "boom: new hole" in content
