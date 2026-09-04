"""Tests for the thesis evidence generator (P6.D.0).

The generator must be deterministic (byte-stable across runs) and emit
booktabs tables ready for \\input into the thesis chapters.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_GENERATOR = Path(__file__).resolve().parents[1] / "scripts" / "thesis" / "generate_evidence.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_evidence", _GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    report = {
        "mode": "suite (mock)",
        "results": [
            {"rq": "RQ3", "status": "PASS", "hits": 1, "event_id": "evt-1"},
            {
                "rq": "RQ1[iris]",
                "status": "PASS",
                "run_ids": ["run-1", "run-2"],
                "metrics": {"test_accuracy": 1.0, "test_f1_macro": 1.0},
            },
            {
                "rq": "RQ5[iris]",
                "status": "PASS",
                "validity_rate": 1.0,
                "agentic_completed": 3,
                "agentic_total": 3,
            },
            {
                "rq": "RQ6[iris]",
                "status": "PASS",
                "multi_mode": "agentic",
                "single_mode": "degraded_deterministic",
            },
            {"rq": "RQ1[housing]", "status": "PASS", "metrics": {"test_rmse": 12310.539861502295}},
        ],
    }
    (raw / "suite_matrix.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    round_record = {
        "round_id": "round-20260903-231759-1b3f35",
        "experiment_id": "exp-demo",
        "mode": "agentic",
        "execution": {
            "comparison": {
                "deterministic_best": {"run_id": "run-1", "metrics": {"test_accuracy": 0.859}},
                "agentic_best": {"run_id": "run-2", "metrics": {"test_accuracy": 0.8715}},
                "validity_rate": 1.0,
                "metric_delta": {"test_accuracy": 0.0125},
            }
        },
    }
    (raw / "demo_round.json").write_text(json.dumps(round_record, indent=2), encoding="utf-8")
    return raw


def _run_generator(raw_dir: Path, out: Path) -> None:
    spec = _load_generator()
    assert spec.main is not None
    rc = spec.main(["--raw-dir", str(raw_dir), "--out", str(out)])
    assert rc == 0


def test_generates_tables_figure_and_manifest(raw_dir: Path, tmp_path: Path):
    out = tmp_path / "evidence"
    _run_generator(raw_dir, out)

    assert (out / "rq_matrix_suite_matrix.tex").is_file()
    assert (out / "agentic_comparison.tex").is_file()
    assert (out / "validity_rates.pdf").is_file()
    assert (out / "MANIFEST.md").is_file()

    matrix = (out / "rq_matrix_suite_matrix.tex").read_text(encoding="utf-8")
    assert "\\toprule" in matrix and "\\bottomrule" in matrix  # booktabs
    assert "\\label{tab:rq-matrix-suite-matrix}" in matrix  # plain label, unique
    assert "RQ1 & iris & PASS" in matrix
    assert "test\\_accuracy=1.0000" in matrix  # rounded, escaped

    comparison = (out / "agentic_comparison.tex").read_text(encoding="utf-8")
    assert "0.8590 & 0.8715 & +0.0125 & 1.0 & agentic" in comparison

    manifest = (out / "MANIFEST.md").read_text(encoding="utf-8")
    assert "scripts/thesis/generate_evidence.py" in manifest
    assert "raw/suite_matrix.json" in manifest


def test_regeneration_is_byte_stable(raw_dir: Path, tmp_path: Path):
    out = tmp_path / "evidence"
    _run_generator(raw_dir, out)

    def digest() -> dict[str, str]:
        return {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(out.iterdir())
            if f.is_file()
        }

    first = digest()
    _run_generator(raw_dir, out)
    assert digest() == first, "regeneration must be byte-stable"


def test_malformed_snapshot_is_skipped(raw_dir: Path, tmp_path: Path):
    (raw_dir / "broken.json").write_text("{not json", encoding="utf-8")
    out = tmp_path / "evidence"
    _run_generator(raw_dir, out)  # must not raise
    assert (out / "rq_matrix_suite_matrix.tex").is_file()
