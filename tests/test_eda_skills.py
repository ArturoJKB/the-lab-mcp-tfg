"""Tests for the deterministic EDA skill pack."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from thelab.eda import (
    class_balance,
    correlation_hints,
    feature_types,
    leakage_suspects,
    missing_profile,
    outlier_scan,
)


@pytest.fixture
def iris_like_df() -> pd.DataFrame:
    return pd.DataFrame({
        "sepal_length": [5.1, 4.9, 4.7, 7.0, 6.4, 6.9, 6.3, 5.8, 7.1, 7.6, 4.9],
        "sepal_width": [3.5, 3.0, 3.2, 3.2, 3.2, 3.1, 3.3, 2.7, 3.0, 3.0, 2.5],
        "petal_length": [1.4, 1.4, 1.3, 4.7, 4.5, 4.9, 6.0, 5.1, 5.9, 6.6, 4.5],
        "petal_width": [0.2, 0.2, 0.2, 1.4, 1.5, 1.5, 2.5, 1.9, 2.1, 2.1, 1.7],
        "species": ["setosa"] * 3 + ["versicolor"] * 3 + ["virginica"] * 5,
    })


@pytest.fixture
def missing_df() -> pd.DataFrame:
    return pd.DataFrame({
        "a": [1.0, 2.0, None, 4.0],
        "b": [None, 2.0, None, 4.0],
        "c": ["x", "y", "z", "w"],
    })


def test_missing_profile_basic(missing_df: pd.DataFrame):
    result = missing_profile(missing_df)
    assert result["total_rows"] == 4
    assert result["columns"]["a"]["missing"] == 1
    assert result["columns"]["b"]["missing"] == 2
    assert result["columns"]["c"]["missing"] == 0
    pairs = {tuple(p["columns"]): p["co_missing_count"] for p in result["co_missing_pairs"]}
    assert pairs[("a", "b")] == 1
    assert result["most_missing"] == ["b", "a"]


def test_missing_profile_is_json_serializable(missing_df: pd.DataFrame):
    result = missing_profile(missing_df)
    text = json.dumps(result)
    assert json.loads(text) == result


def test_correlation_hints_top_pairs(iris_like_df: pd.DataFrame):
    result = correlation_hints(iris_like_df)
    assert result["top_correlations"]
    names = {(p["feature_a"], p["feature_b"]) for p in result["top_correlations"]}
    assert ("petal_length", "petal_width") in names
    for pair in result["top_correlations"]:
        assert "correlation" in pair
        assert "abs_correlation" in pair
        assert pair["abs_correlation"] >= 0.0


def test_correlation_hints_target_correlations(iris_like_df: pd.DataFrame):
    result = correlation_hints(iris_like_df, target="petal_width")
    features = {c["feature"] for c in result["target_correlations"]}
    assert "petal_length" in features


def test_class_balance(iris_like_df: pd.DataFrame):
    result = class_balance(iris_like_df, target="species")
    classes = {c["class"]: c["count"] for c in result["classes"]}
    assert classes == {"setosa": 3, "versicolor": 3, "virginica": 5}
    assert result["minority_class"]["class"] in {"setosa", "versicolor"}
    assert result["majority_class"]["class"] == "virginica"
    assert result["imbalance_ratio"] == pytest.approx(5 / 3, 0.01)


def test_class_balance_warning_for_small_class():
    df = pd.DataFrame({
        "target": (["majority"] * 100) + (["minority"] * 3),
    })
    result = class_balance(df, target="target")
    assert result["min_class_warning"] is True


def test_class_balance_missing_target():
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = class_balance(df, target="missing")
    assert "error" in result
    assert result["classes"] == []


def test_outlier_scan(iris_like_df: pd.DataFrame):
    result = outlier_scan(iris_like_df)
    assert set(result["numeric_columns"]) == {"sepal_length", "sepal_width", "petal_length", "petal_width"}
    for col in result["numeric_columns"]:
        col_result = result["columns"][col]
        assert "iqr_lower" in col_result
        assert "iqr_upper" in col_result
        assert "iqr_outlier_count" in col_result
        assert "z_outlier_count" in col_result


def test_leakage_suspects_name_based():
    df = pd.DataFrame({
        "species": ["a", "b", "c"],
        "species_encoded": [0, 1, 2],
        "other": [1.0, 2.0, 3.0],
    })
    result = leakage_suspects(df, target="species")
    features = {s["feature"] for s in result["suspects"]}
    assert "species_encoded" in features
    assert "other" not in features


def test_leakage_suspects_perfect_correlation():
    df = pd.DataFrame({
        "target": [1.0, 2.0, 3.0, 4.0],
        "copy": [1.0, 2.0, 3.0, 4.0],
        "other": [1.0, 2.0, 4.0, 5.0],
    })
    result = leakage_suspects(df, target="target")
    features = {s["feature"]: s["reason"] for s in result["suspects"]}
    assert "copy" in features


def test_feature_types(iris_like_df: pd.DataFrame):
    result = feature_types(iris_like_df)
    assert result["numeric_count"] == 4
    assert result["categorical_count"] == 1
    for col in iris_like_df.columns:
        col_result = result["columns"][col]
        assert "inferred_dtype" in col_result
        assert "coerced_type" in col_result
        assert "unique_count" in col_result
        assert isinstance(col_result["sample_values"], list)


def test_feature_types_text_vs_categorical():
    df = pd.DataFrame({
        "low_card": (["a", "b"] * 15)[:30],
        "high_card": [f"x{i}" for i in range(30)],
    })
    result = feature_types(df)
    assert result["columns"]["low_card"]["coerced_type"] == "categorical"
    assert result["columns"]["high_card"]["coerced_type"] == "text"


def test_determinism(iris_like_df: pd.DataFrame):
    """Identical input must produce identical JSON output."""
    first = json.dumps(missing_profile(iris_like_df), sort_keys=True)
    second = json.dumps(missing_profile(iris_like_df), sort_keys=True)
    assert first == second


def test_size_bounds(iris_like_df: pd.DataFrame):
    """Outputs should stay bounded relative to small inputs."""
    result = correlation_hints(iris_like_df)
    assert len(result["top_correlations"]) <= 10
    assert len(result["target_correlations"]) <= 10

    result = missing_profile(iris_like_df)
    assert len(result["co_missing_pairs"]) <= 10
