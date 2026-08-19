from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

Validator = Callable[[pd.DataFrame, str, list[str], int], dict[str, Any]]


def _check(name: str, passed: bool, message: str) -> dict[str, Any]:
    return {"check": name, "passed": passed, "message": "OK" if passed else message}


def _target_column_exists(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    passed = target in df.columns
    return _check("target_column_exists", passed, f"target column '{target}' not found")


def _target_not_among_features(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    passed = target not in features
    return _check(
        "target_not_among_features",
        passed,
        f"target column '{target}' is also listed as a feature column",
    )


def _dataset_not_empty(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    passed = len(df) > 0
    return _check("dataset_not_empty", passed, "dataset has no rows")


def _target_no_missing_values(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    count = int(df[target].isna().sum()) if target in df.columns else 0
    passed = count == 0
    return _check("target_no_missing_values", passed, f"target column contains {count} missing values")


def _features_no_missing_values(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    if not features:
        return _check("features_no_missing_values", True, "OK")
    count = int(df[features].isna().sum().sum())
    passed = count == 0
    return _check("features_no_missing_values", passed, f"feature columns contain {count} missing values")


def _features_no_infinite_values(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    if not features:
        return _check("features_no_infinite_values", True, "OK")
    numeric = df[features].select_dtypes(include="number")
    if numeric.empty:
        return _check("features_no_infinite_values", True, "OK")
    inf_count = int(np.isinf(numeric.to_numpy()).sum())
    passed = inf_count == 0
    return _check("features_no_infinite_values", passed, f"feature columns contain {inf_count} infinite values (Inf/-Inf)")


def _features_numeric(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    if not features:
        return _check("features_numeric", True, "OK")
    numeric_cols = df[features].select_dtypes(include="number").columns.tolist()
    passed = len(numeric_cols) == len(features)
    non_numeric = [col for col in features if col not in numeric_cols]
    return _check("features_numeric", passed, f"not all feature columns are numeric: {non_numeric}")


def _no_duplicate_columns(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    dupes = df.columns[df.columns.duplicated()].unique().tolist()
    passed = len(dupes) == 0
    return _check("no_duplicate_columns", passed, f"duplicate column names found: {dupes}")


def _at_least_one_feature(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    passed = len(features) > 0
    return _check("at_least_one_feature", passed, "dataset has no feature columns after excluding target")


def _no_constant_features(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    if not features:
        return _check("no_constant_features", True, "OK")
    numeric = df[features].select_dtypes(include="number")
    constant = [col for col in numeric.columns if numeric[col].nunique(dropna=True) <= 1]
    passed = len(constant) == 0
    return _check("no_constant_features", passed, f"constant feature columns found: {constant}")


def _sensible_target_type(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    if target not in df.columns:
        return _check("sensible_target_type", True, "OK")
    target_series = df[target]
    n_unique = target_series.nunique(dropna=True)
    n_rows = len(target_series)
    # Allow a reasonable number of classes; reject ID-like targets where every
    # row is its own class on larger datasets.
    passed = n_unique >= 2 and (n_unique <= 10 or n_unique <= n_rows // 2)
    reason = []
    if n_unique < 2:
        reason.append(f"only {n_unique} unique target value")
    if n_unique > 10 and n_unique > n_rows // 2:
        reason.append(f"{n_unique} classes for {n_rows} rows")
    return _check("sensible_target_type", passed, "target type is not sensible for classification: " + "; ".join(reason))


def _stratified_split_feasible(df: pd.DataFrame, target: str, features: list[str], seed: int) -> dict[str, Any]:
    if target not in df.columns or len(df) == 0:
        return _check("stratified_split_feasible", True, "OK")
    class_counts = df[target].value_counts()
    n_classes = int(len(class_counts))
    min_class_size = int(class_counts.min()) if n_classes > 0 else 0
    n_rows = int(len(df))
    test_size = 0.2
    n_test = math.ceil(test_size * n_rows)
    n_train = n_rows - n_test

    can_stratify = True
    reasons = []
    if n_classes < 2:
        can_stratify = False
        reasons.append(f"only {n_classes} classes")
    if min_class_size < 2:
        can_stratify = False
        reasons.append(f"smallest class has {min_class_size} samples")
    if n_test < n_classes:
        can_stratify = False
        reasons.append(f"test split ({n_test}) smaller than number of classes ({n_classes})")
    if n_train < n_classes:
        can_stratify = False
        reasons.append(f"train split ({n_train}) smaller than number of classes ({n_classes})")

    return _check("stratified_split_feasible", can_stratify, "cannot stratify: " + "; ".join(reasons))


DEFAULT_VALIDATORS: list[Validator] = [
    _target_column_exists,
    _dataset_not_empty,
    _target_no_missing_values,
    _no_duplicate_columns,
    _at_least_one_feature,
    _target_not_among_features,
    _features_numeric,
    _features_no_missing_values,
    _features_no_infinite_values,
    _no_constant_features,
    _sensible_target_type,
    _stratified_split_feasible,
]


def validate_dataset(
    df: pd.DataFrame,
    dataset_path: Any,
    target_column: str,
    feature_columns: list[str],
    seed: int,
    test_size: float = 0.2,
    validators: list[Validator] | None = None,
) -> dict[str, Any]:
    """Run dataset validation checks and return a structured report."""
    validators = validators or DEFAULT_VALIDATORS
    checks = [validator(df, target_column, feature_columns, seed) for validator in validators]
    passed = all(c["passed"] for c in checks)

    n_test = math.ceil(test_size * len(df)) if len(df) > 0 else 0
    n_train = len(df) - n_test
    split_summary = {
        "strategy": "train_test_split",
        "test_size": test_size,
        "random_state": seed,
        "stratify": True,
        "train_count": n_train,
        "test_count": n_test,
    }

    warnings = []
    if len(df) < 100:
        warnings.append("dataset is small; metrics may have high variance")

    return {
        "valid": passed,
        "checks": checks,
        "warnings": warnings,
        "schema_checks": {
            "expected_target": target_column,
            "expected_features": feature_columns,
            "actual_columns": list(df.columns),
        },
        "split_summary": split_summary,
        "reproducibility": {
            "seed": seed,
            "split_strategy": "train_test_split",
            "stratify": True,
        },
    }
