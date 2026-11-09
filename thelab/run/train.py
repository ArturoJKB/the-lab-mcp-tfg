from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder


class FittedPipeline:
    """Complete fitted inference pipeline bundling preprocessing and optional label decoding."""

    def __init__(self, pipeline: Pipeline, label_encoder: LabelEncoder | None = None):
        self.pipeline = pipeline
        self.label_encoder = label_encoder
        self.classes_ = label_encoder.classes_ if label_encoder is not None else None

    def predict(self, X: Any) -> Any:
        encoded = self.pipeline.predict(X)
        if self.label_encoder is not None:
            return self.label_encoder.inverse_transform(encoded)
        return encoded

    def predict_proba(self, X: Any) -> Any:
        estimator = self.pipeline.named_steps["estimator"]
        if not hasattr(estimator, "predict_proba"):
            raise ValueError(
                "the fitted model does not support probability estimates; "
                "train with a probability-enabled variant (e.g. svc_probability) if needed"
            )
        return estimator.predict_proba(X)


def _classification_metrics(
    y_train: np.ndarray,
    y_test: np.ndarray,
    y_train_pred: np.ndarray,
    y_test_pred: np.ndarray,
) -> dict[str, Any]:
    return {
        "train_samples": int(len(y_train)),
        "test_samples": int(len(y_test)),
        "train_accuracy": float(accuracy_score(y_train, y_train_pred)),
        "test_accuracy": float(accuracy_score(y_test, y_test_pred)),
        "train_f1_macro": float(f1_score(y_train, y_train_pred, average="macro")),
        "test_f1_macro": float(f1_score(y_test, y_test_pred, average="macro")),
    }


def _regression_metrics(
    y_train: np.ndarray,
    y_test: np.ndarray,
    y_train_pred: np.ndarray,
    y_test_pred: np.ndarray,
) -> dict[str, Any]:
    return {
        "train_samples": int(len(y_train)),
        "test_samples": int(len(y_test)),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, y_train_pred))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, y_test_pred))),
        "train_mae": float(mean_absolute_error(y_train, y_train_pred)),
        "test_mae": float(mean_absolute_error(y_test, y_test_pred)),
        "train_r2": float(r2_score(y_train, y_train_pred)),
        "test_r2": float(r2_score(y_test, y_test_pred)),
    }


def train_and_evaluate(
    df: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    pipeline: Pipeline,
    seed: int,
    test_size: float = 0.2,
    task_type: str = "classification",
    split: str = "random",
) -> tuple[FittedPipeline, dict[str, Any], dict[str, Any], pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Train the pipeline and return the fitted model, metrics, split counts, and splits.

    Split policies:
    - ``random`` (default): shuffled (stratified for classification) split —
      the thesis baseline behavior.
    - ``temporal``: rows are assumed ordered by time; the LAST ``test_size``
      fraction is held out as the future. No shuffling, no stratification.
      Regression runs additionally record naive-persistence benchmarks
      (``test_mae_naive_lag{1,24,168}`` where the series is long enough) and
      a ``test_mae_train_mean`` floor; classification records
      ``test_accuracy_majority``. Every forecasting claim is therefore
      reported against a baseline.
    """
    X = df[feature_columns]
    y = df[target_column]

    if split == "temporal":
        n_test = int(len(df) * test_size)
        if n_test <= 0 or len(df) - n_test <= 0:
            raise ValueError(
                f"temporal split impossible: {len(df)} rows cannot yield a "
                f"non-empty {test_size:.0%} future holdout"
            )
        if task_type == "regression":
            label_encoder = None
            y_encoded = y.to_numpy()
        else:
            label_encoder = LabelEncoder()
            y_encoded = label_encoder.fit_transform(y)
        split_idx = len(df) - n_test
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y_encoded[:split_idx], y_encoded[split_idx:]
        if label_encoder is not None:
            missing = set(y_test.tolist()) - set(y_train.tolist())
            if missing:
                names = sorted(label_encoder.inverse_transform(sorted(missing)))
                raise ValueError(
                    "temporal split rejected: classes "
                    f"{names} appear only in the future holdout — the model "
                    "cannot predict unseen classes"
                )
    elif task_type == "regression":
        label_encoder = None
        y_encoded = y.to_numpy()
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=test_size, random_state=seed, shuffle=True
        )
    else:
        label_encoder = LabelEncoder()
        y_encoded = label_encoder.fit_transform(y)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=test_size, random_state=seed, stratify=y_encoded
        )

    pipeline.fit(X_train, y_train)

    y_train_pred = pipeline.predict(X_train)
    y_test_pred = pipeline.predict(X_test)

    split_info = {
        "strategy": split,
        "train_count": int(len(y_train)),
        "test_count": int(len(y_test)),
    }

    if task_type == "regression":
        metrics = _regression_metrics(y_train, y_test, y_train_pred, y_test_pred)
        metrics.update(_baseline_metrics(y, y_train, y_test, split=split))
    else:
        metrics = _classification_metrics(y_train, y_test, y_train_pred, y_test_pred)
        majority = pd.Series(y_train).mode().min()
        metrics["test_accuracy_majority"] = float(
            float(pd.Series(y_test).eq(majority).mean())
        )

    fitted = FittedPipeline(pipeline=pipeline, label_encoder=label_encoder)
    return fitted, metrics, split_info, X_train, X_test, pd.Series(y_train), pd.Series(y_test)


def _baseline_metrics(
    y: pd.Series,
    y_train: np.ndarray,
    y_test: np.ndarray,
    split: str,
) -> dict[str, Any]:
    """Deterministic baseline metrics every regression run reports against.

    ``test_mae_train_mean`` is always defined (predict the train mean). The
    naive-persistence lags are only defined on a temporally ordered split:
    test row i is predicted from the actual value *lag* rows earlier in the
    full series.
    """
    y_all = y.to_numpy(dtype=float)
    k = len(y_test)
    test = np.asarray(y_test, dtype=float)
    out: dict[str, Any] = {}
    train_mean = float(np.mean(np.asarray(y_train, dtype=float)))
    out["test_mae_train_mean"] = float(np.abs(test - train_mean).mean())
    if split != "temporal":
        return out
    for lag in (1, 24, 168):
        start = len(y_all) - k - lag
        if start < 0:
            continue  # series too short for this lag's warm-up
        naive = y_all[start : len(y_all) - lag]
        out[f"test_mae_naive_lag{lag}"] = float(np.abs(test - naive).mean())
    return out
