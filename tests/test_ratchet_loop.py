"""Tests for the P6 ratchet loop runner (mock provider, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ratchet_loop import (
    DatasetCfg,
    absorption_decision,
    load_ledger,
    pick_baseline,
    run_dataset,
)


@pytest.fixture
def loop_env(tmp_path: Path, monkeypatch):
    """Tiny hermetic workspace: uploads/runs/proposals/experiments/generations."""
    uploads = tmp_path / "uploads"
    for d in ("uploads", "runs", "proposals", "experiments", ".thelab/generations"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(tmp_path / "proposals"))
    monkeypatch.setenv("THELAB_EXPERIMENTS_DIR", str(tmp_path / "experiments"))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("THELAB_CONTEXT_LOG_SOURCE", str(tmp_path / "logs" / "events.jsonl"))
    rows = ["f1,f2,label"]
    for i in range(80):
        rows.append(f"{1.0 + (i % 7) * 0.5},{(i % 5) * 1.25:.2f},{'x' if i % 2 else 'y'}")
    (uploads / "tiny_cleaned.csv").write_text("\n".join(rows), encoding="utf-8")
    return tmp_path, uploads


def _cfg(tmp_path: Path, rounds: int = 1) -> DatasetCfg:
    return DatasetCfg(
        slug="tiny",
        dataset="data/uploads/tiny_cleaned.csv",
        target="label",
        task="classification",
        arm="A",
        model_cells=[("mock", None, rounds)],
    )


def _with_ws(spec: DatasetCfg, monkeypatch, tmp_path: Path) -> DatasetCfg:
    # run_model validates that the dataset path stays inside the workspace:
    # point the spec at the same file via an absolute-safe relative path.
    import os

    os.chdir(tmp_path)
    (tmp_path / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "uploads" / "tiny_cleaned.csv").write_text(
        (tmp_path / "uploads" / "tiny_cleaned.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return spec


def test_pick_baseline_prefers_primary_metric():
    results = [
        {"status": "completed", "model": "a", "metrics": {"test_accuracy": 0.8}},
        {"status": "completed", "model": "b", "metrics": {"test_accuracy": 0.9}},
        {"status": "rejected", "model": "c", "metrics": {"test_accuracy": 1.0}},
        {"status": "completed", "model": "d", "metrics": {}},
    ]
    best = pick_baseline(results, "classification")
    assert best is not None and best["model"] == "b"
    assert pick_baseline([{"status": "rejected"}], "classification") is None


def test_absorption_requires_beating_baseline():
    baseline = {"model": "ridge", "metrics": {"test_accuracy": 0.85}}
    best = {"metrics": {"test_accuracy": 0.84}, "config": {"model": "x", "seed": 42}}
    d = absorption_decision(baseline, best, {"test_accuracy": 0.84}, "classification")
    assert d["absorbed"] is False and "does not beat" in d["reason"]


def test_absorption_requires_exact_replay():
    baseline = {"model": "ridge", "metrics": {"test_accuracy": 0.85}}
    best = {"metrics": {"test_accuracy": 0.90}, "config": {"model": "x", "seed": 42}}
    d = absorption_decision(baseline, best, {"test_accuracy": 0.71}, "classification")
    assert d["absorbed"] is False and "replay" in d["reason"]
    d2 = absorption_decision(baseline, best, {"test_accuracy": 0.90}, "classification")
    assert d2["absorbed"] is True and d2["delta"] == pytest.approx(0.05)


def test_absorption_with_no_agentic_rounds():
    baseline = {"model": "ridge", "metrics": {"test_accuracy": 0.85}}
    d = absorption_decision(baseline, None, None, "classification")
    assert d["absorbed"] is False and "no agentic round" in d["reason"]


def test_run_dataset_mock_writes_ledger(loop_env, tmp_path, monkeypatch):
    """Suite-mode generation: degraded rounds are recorded honestly, no
    absorption claim is made without an agentic round (P5.B8 counting rule)."""
    tmp, uploads = loop_env
    monkeypatch.chdir(tmp)
    (tmp / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "uploads" / "tiny_cleaned.csv").write_text(
        (uploads / "tiny_cleaned.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    cfg = _cfg(tmp, rounds=1)
    ledger_before = load_ledger("tiny")
    assert ledger_before["generations"] == []

    entry = run_dataset("tiny", registry={"tiny": cfg}, provider_override="mock")

    assert "baseline" in entry and entry["baseline"]["model"]
    assert len(entry["cells"]) == 1
    rounds = entry["cells"][0]["rounds"]
    assert rounds, "mock cell must record its round outcome"
    # degraded/deterministic rounds make no absorption claim
    assert entry["absorption"]["absorbed"] is False

    ledger = load_ledger("tiny")
    assert len(ledger["generations"]) == 1
    saved = json.loads((tmp / ".thelab" / "generations" / "tiny.json").read_text())
    assert saved["generations"][0]["baseline"]["metrics"]
