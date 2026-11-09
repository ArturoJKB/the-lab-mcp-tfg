"""Temporal split policy: split ordering, naive benchmarks, honest failures."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from thelab.run.preprocess import build_pipeline
from thelab.run.runner import run_model
from thelab.run.train import train_and_evaluate


def _hourly_df(rows: int = 500, seed: int = 7) -> pd.DataFrame:
    """Time-ordered synthetic demand-like series with strong lag-24 seasonality."""
    rng = np.random.default_rng(seed)
    t = np.arange(rows)
    daily = 1000 * np.sin(2 * np.pi * t / 24)
    weekly = 200 * np.sin(2 * np.pi * t / 168)
    trend = 0.5 * t
    noise = rng.normal(0, 10, rows)
    y = 5000 + daily + weekly + trend + noise
    return pd.DataFrame({"hour_idx": t.astype(float), "load": y})


def test_temporal_split_test_rows_are_the_future():
    df = _hourly_df()
    pipeline = build_pipeline("ridge", 42)
    _, metrics, split_info, X_train, X_test, _, _ = train_and_evaluate(
        df, ["hour_idx"], "load", pipeline, 42, task_type="regression", split="temporal"
    )
    assert split_info["strategy"] == "temporal"
    assert X_test["hour_idx"].min() >= X_train["hour_idx"].max()
    assert metrics["test_mae_naive_lag1"] >= 0
    assert metrics["test_mae_naive_lag24"] >= 0
    assert metrics["test_mae_naive_lag168"] >= 0
    assert metrics["test_mae_train_mean"] >= 0


def test_naive_lag24_is_near_perfect_on_strong_seasonality():
    """A pure lag-24 seasonal series makes the lag-24 naive MAE ~0 (sanity)."""
    rows = 500
    t = np.arange(rows)
    y = 1000 * np.sin(2 * np.pi * t / 24)
    df = pd.DataFrame({"hour_idx": t.astype(float), "load": y})
    n_test = int(rows * 0.2)
    y_all = df["load"].to_numpy(float)
    naive24 = y_all[rows - n_test - 24 : rows - 24]
    test = y_all[rows - n_test :]
    assert np.abs(test - naive24).mean() < 1e-9


def test_random_split_records_train_mean_but_no_lags():
    df = _hourly_df()
    pipeline = build_pipeline("ridge", 42)
    _, metrics, split_info, *_ = train_and_evaluate(
        df, ["hour_idx"], "load", pipeline, 42, task_type="regression", split="random"
    )
    assert split_info["strategy"] == "random"
    assert "test_mae_train_mean" in metrics
    assert "test_mae_naive_lag24" not in metrics


def test_temporal_classification_rejects_unseen_future_class():
    df = pd.DataFrame(
        {
            "t": np.arange(120, dtype=float),
            "x": np.linspace(0, 1, 120),
            "phase": ["a"] * 100 + ["b"] * 20,  # class 'b' exists only in the future
        }
    )
    pipeline = build_pipeline("logistic_regression", 42)
    with pytest.raises(ValueError, match="cannot predict unseen classes"):
        train_and_evaluate(
            df, ["t", "x"], "phase", pipeline, 42, task_type="classification", split="temporal"
        )


def test_temporal_classification_records_majority_baseline():
    df = pd.DataFrame(
        {
            "t": np.arange(300, dtype=float),
            "x": np.linspace(0, 1, 300),
            "phase": (["a"] * 200) + (["b"] * 100),
        }
    )
    pipeline = build_pipeline("logistic_regression", 42)
    _, metrics, split_info, *_ = train_and_evaluate(
        df, ["t", "x"], "phase", pipeline, 42, task_type="classification", split="temporal"
    )
    assert split_info["strategy"] == "temporal"
    assert 0.0 <= metrics["test_accuracy_majority"] <= 1.0


def test_run_model_temporal_persists_split_policy_and_naive_metrics(tmp_path: Path):
    csv = tmp_path / "series.csv"
    _hourly_df(400).to_csv(csv, index=False)
    result = run_model(
        dataset=csv,
        target="load",
        model="ridge",
        seed=42,
        output=tmp_path / "runs",
        workspace_root=tmp_path,
        split="temporal",
    )
    assert result["status"] == "completed"
    run_dir = tmp_path / "runs" / result["run_id"]
    inputs = json.loads((run_dir / "inputs.json").read_text())
    config = json.loads((run_dir / "training_config.json").read_text())
    metrics = json.loads((run_dir / "metrics.json").read_text())
    card = (run_dir / "model_card.md").read_text()
    assert inputs["split"] == "temporal"
    assert config["split_policy"] == "temporal"
    assert metrics["test_mae_naive_lag24"] >= 0
    assert "temporal" in card
    assert "--split temporal" in card


def test_run_model_rejects_unsupported_split(tmp_path: Path):
    from thelab.run.errors import RejectedRunError

    csv = tmp_path / "series.csv"
    _hourly_df(60).to_csv(csv, index=False)
    with pytest.raises(RejectedRunError, match="unsupported split policy"):
        run_model(
            dataset=csv,
            target="load",
            model="ridge",
            seed=42,
            output=tmp_path / "runs",
            workspace_root=tmp_path,
            split="shuffle-chaos",
        )
