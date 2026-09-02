"""Real-dataset hardening tests: cleaning policy, scale guards, cancel, progress.

These mirror the S&P 500 analyst-ratings dataset shape: a datetime column,
high-cardinality categorical columns, missing target values, and enough rows
to exercise per-model scale guards.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from thelab.ide.cleaning import clean_dataset
from thelab.run.batch import BatchEntry, BatchRunner
from thelab.run.model_registry import MODEL_REGISTRY, ModelEntry
from thelab.run.runner import run_model


def _write_market_csv(uploads: Path, rows: int = 120) -> None:
    """Write an S&P-analyst-ratings-like dataset: datetime + high-cardinality strings."""
    lines = ["event_date,ticker,firm,action,prior_price_target,accuracy_90d"]
    for i in range(rows):
        target = "" if i % 7 == 0 else ("1.0" if i % 3 == 0 else "0.0")
        lines.append(
            f"{2024 + i % 2}-{1 + i % 12:02d}-{1 + i % 28:02d} {i % 24:02d}:32:00,"
            f"tick{i % 25},firm_{i % 29},{'up' if i % 3 else 'down'},"
            f"{(i % 40) + 100}.0,{target}"
        )
    (uploads / "market.csv").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Cleaning policy (datetime + cardinality)
# ---------------------------------------------------------------------------

def test_cleaning_parses_datetime_and_encodes_cardinality(tmp_path, monkeypatch):
    """Datetime columns become numeric features; high-cardinality strings are frequency-encoded."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    _write_market_csv(uploads, rows=120)

    result = clean_dataset("uploads/market.csv", target="accuracy_90d")
    report = result["cleaning_report"]
    actions = " | ".join(report["actions"])

    assert "event_date" in actions and "datetime" in actions
    assert "frequency-encoded" in actions

    cleaned = pd.read_csv(uploads / "market_cleaned_accuracy_90d.csv")
    assert "event_date" not in cleaned.columns
    assert "event_date_year" in cleaned.columns
    assert "firm_frequency" in cleaned.columns
    # No dummy explosion and no residual missing values.
    assert len(cleaned.columns) < 30
    assert not cleaned.isna().any().any()
    assert result["dataset_id"] == "uploads/market_cleaned_accuracy_90d.csv"


def test_cleaning_one_hots_low_cardinality_still(tmp_path, monkeypatch):
    """Low-cardinality categoricals keep one-hot encoding."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    (uploads / "small.csv").write_text(
        "num,cat,target\n1,red,x\n2,blue,y\n3,red,x\n",
        encoding="utf-8",
    )
    clean_dataset("uploads/small.csv", target="target")
    cleaned = pd.read_csv(uploads / "small_cleaned_target.csv")
    assert {"cat_red", "cat_blue"}.issubset(cleaned.columns)
    assert not any(c.endswith("_frequency") for c in cleaned.columns)


# ---------------------------------------------------------------------------
# Model scale guard
# ---------------------------------------------------------------------------

def test_scale_guard_rejects_oversized_model(tmp_path, monkeypatch):
    """run_model rejects a model above its max_train_rows with a clear reason."""
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    _write_market_csv(uploads, rows=150)

    original = MODEL_REGISTRY.get("svc")
    MODEL_REGISTRY.register(
        ModelEntry(
            name=original.name,
            estimator_class=original.estimator_class,
            default_params=original.default_params,
            supports_probability=original.supports_probability,
            task_type=original.task_type,
            max_train_rows=100,
        )
    )
    try:
        result = run_model(
            dataset="uploads/market.csv",
            target="accuracy_90d",
            model="svc",
            seed=42,
            output="runs",
            workspace_root=tmp_path,
        )
    finally:
        MODEL_REGISTRY.register(original)

    assert result["status"] == "rejected"
    assert "limited to 100 training rows" in (result.get("error") or "")


def test_scale_guard_allows_small_datasets(tmp_path):
    """Models within their row limit still train normally (dry run, nothing persisted)."""
    csv = tmp_path / "small.csv"
    rows = ["a,b,species"]
    for i in range(30):
        rows.append(f"{i},{i % 2},{i % 2}")
    csv.write_text("\n".join(rows), encoding="utf-8")
    result = run_model(
        dataset=csv,
        target="species",
        model="svc",
        seed=42,
        output="scratch",
        workspace_root=tmp_path,
        dry_run=True,
    )
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Batch cancellation + per-entry progress callbacks
# ---------------------------------------------------------------------------

def test_batch_runner_should_continue_stops_between_entries(tmp_path):
    """should_continue() returning False stops the loop before any entry runs."""
    runner = BatchRunner(workspace_root=tmp_path)
    entries = [BatchEntry(dataset="a.csv", target="t", model="logistic_regression", seed=1)]
    results = runner.run(entries, should_continue=lambda: False)
    assert results == []


def test_batch_runner_on_result_fires_per_entry(tmp_path):
    """on_result fires after each entry; results keep their statuses."""
    csv = tmp_path / "tiny.csv"
    rows = ["a,b,t"]
    for i in range(20):
        rows.append(f"{i},{i % 2},{i % 2}")
    csv.write_text("\n".join(rows), encoding="utf-8")

    runner = BatchRunner(workspace_root=tmp_path)
    entries = [
        BatchEntry(dataset="tiny.csv", target="t", model="logistic_regression", seed=42),
        BatchEntry(dataset="tiny.csv", target="t", model="sgd_classifier", seed=42),
    ]
    seen: list[str] = []
    results = runner.run(
        entries,
        should_continue=lambda: True,
        on_result=lambda r: seen.append(f"{r.entry.model}:{r.status}"),
    )
    assert len(results) == 2
    assert len(seen) == 2
    assert all(r.status == "completed" for r in results)
    assert seen[0].startswith("logistic_regression:completed")


def test_orchestrator_cancelled_before_start(tmp_path):
    """should_continue returning False raises OrchestrationCancelled immediately."""
    import asyncio

    from thelab.ide.orchestrator import ExperimentOrchestrator, OrchestrationCancelled

    (tmp_path / "proposals").mkdir()
    (tmp_path / "runs").mkdir()
    orchestrator = ExperimentOrchestrator(
        runs_root=tmp_path / "runs",
        proposals_dir=tmp_path / "proposals",
    )
    with pytest.raises(OrchestrationCancelled):
        asyncio.run(
            orchestrator.orchestrate(
                goal="g",
                dataset_id="uploads/x.csv",
                target="t",
                should_continue=lambda: False,
            )
        )


# ---------------------------------------------------------------------------
# Job cancel endpoint (HTTP surface)
# ---------------------------------------------------------------------------

def test_job_cancel_endpoint_404_and_flag(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from thelab.ide.jobs import reset_job_manager
    from thelab.model_service.app import app

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    for name in ("fixtures", "runs", "proposals", "jobs", "experiments"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(tmp_path / "proposals"))
    monkeypatch.setenv("THELAB_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    reset_job_manager()
    _write_market_csv(uploads, rows=60)

    # A context-managed client keeps the portal (and its event loop) alive
    # across requests, so jobs suspended on asyncio.to_thread can finish.
    with TestClient(app) as client:
        cleaned = client.post(
            "/datasets/uploads%2Fmarket.csv/clean", json={"target": "accuracy_90d"}
        )
        assert cleaned.status_code == 200
        dataset_id = cleaned.json()["data"]["dataset_id"]

        started = client.post(
            "/jobs",
            json={
                "type": "train",
                "payload": {"dataset_id": dataset_id, "target": "accuracy_90d", "model": "logistic_regression"},
            },
        )
        assert started.status_code == 200
        job_id = started.json()["data"]["job_id"]

        deadline = time.time() + 120.0
        payload = {}
        while time.time() < deadline:
            payload = client.get(f"/jobs/{job_id}").json()["data"]
            if payload["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert payload["status"] == "completed"
        assert payload["cancel_requested"] is False
        assert client.post("/jobs/does-not-exist/cancel").status_code == 404
