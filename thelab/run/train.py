from __future__ import annotations

from typing import Any

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder


class FittedPipeline:
    """Complete fitted inference pipeline bundling preprocessing and label decoding."""

    def __init__(self, pipeline: Pipeline, label_encoder: LabelEncoder):
        self.pipeline = pipeline
        self.label_encoder = label_encoder
        self.classes_ = label_encoder.classes_

    def predict(self, X: Any) -> Any:
        encoded = self.pipeline.predict(X)
        return self.label_encoder.inverse_transform(encoded)

    def predict_proba(self, X: Any) -> Any:
        if not hasattr(self.pipeline.named_steps["classifier"], "predict_proba"):
            raise ValueError(
                "the fitted model does not support probability estimates; "
                "train with a probability-enabled variant (e.g. svc_probability) if needed"
            )
        return self.pipeline.predict_proba(X)


def train_and_evaluate(
    df: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    pipeline: Pipeline,
    seed: int,
    test_size: float = 0.2,
) -> tuple[FittedPipeline, dict[str, Any], dict[str, int], pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Train the pipeline and return the fitted model, metrics, split counts, and splits."""
    X = df[feature_columns]
    y = df[target_column]

    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_encoded, test_size=test_size, random_state=seed, stratify=y_encoded
    )

    pipeline.fit(X_train, y_train)

    y_train_pred = pipeline.predict(X_train)
    y_test_pred = pipeline.predict(X_test)

    split_info = {
        "train_count": int(len(y_train)),
        "test_count": int(len(y_test)),
    }

    metrics = {
        "train_samples": split_info["train_count"],
        "test_samples": split_info["test_count"],
        "train_accuracy": float(accuracy_score(y_train, y_train_pred)),
        "test_accuracy": float(accuracy_score(y_test, y_test_pred)),
        "train_f1_macro": float(f1_score(y_train, y_train_pred, average="macro")),
        "test_f1_macro": float(f1_score(y_test, y_test_pred, average="macro")),
    }

    fitted = FittedPipeline(pipeline=pipeline, label_encoder=label_encoder)
    return fitted, metrics, split_info, X_train, X_test, pd.Series(y_train), pd.Series(y_test)
