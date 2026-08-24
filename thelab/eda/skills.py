"""Pure, deterministic DataFrame EDA functions.

Every function accepts a pandas ``DataFrame`` and returns a stable,
JSON-serializable dict with a documented schema. No unseeded sampling is
performed; outputs depend only on the input DataFrame (and optional *target*).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

_TOP_K = 10

_MISSING_RATE_DIGITS = 6
_CORR_DIGITS = 6


def missing_profile(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    """Return per-column and co-occurrence missingness statistics.

    Schema::

        {
          "total_rows": int,
          "columns": {
            "col_name": {"missing": int, "missing_rate": float}
          },
          "co_missing_pairs": [
            {"columns": [str, str], "co_missing_count": int, "co_missing_rate": float}
          ],
          "most_missing": [str]  # columns with missing > 0, sorted desc
        }
    """
    total = len(df)
    missing = df.isna().sum().to_dict()
    column_stats: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        count = int(missing.get(col, 0))
        rate = round(count / total, _MISSING_RATE_DIGITS) if total else 0.0
        column_stats[col] = {"missing": count, "missing_rate": rate}

    # Co-missingness pairs: both columns missing in the same row.
    cols_with_missing = [c for c in df.columns if missing.get(c, 0) > 0]
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(cols_with_missing):
        for b in cols_with_missing[i + 1 :]:
            co_missing = int((df[a].isna() & df[b].isna()).sum())
            if co_missing:
                pairs.append({
                    "columns": [a, b],
                    "co_missing_count": co_missing,
                    "co_missing_rate": round(co_missing / total, _MISSING_RATE_DIGITS) if total else 0.0,
                })
    pairs = sorted(pairs, key=lambda x: (-x["co_missing_count"], x["columns"]))[:_TOP_K]

    most_missing = sorted(
        [c for c in df.columns if missing.get(c, 0) > 0],
        key=lambda c: (-missing[c], c),
    )

    return {
        "total_rows": total,
        "columns": column_stats,
        "co_missing_pairs": pairs,
        "most_missing": most_missing,
    }


def correlation_hints(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    """Return top Pearson correlations among numeric features and with target.

    Schema::

        {
          "top_correlations": [
            {"feature_a": str, "feature_b": str, "correlation": float, "abs_correlation": float}
          ],
          "target_correlations": [
            {"feature": str, "correlation": float, "abs_correlation": float}
          ]
        }
    """
    numeric = df.select_dtypes(include="number")
    numeric_cols = [c for c in numeric.columns if c != target]

    top_pairs: list[dict[str, Any]] = []
    if len(numeric_cols) >= 2:
        corr_matrix = numeric[numeric_cols].corr(method="pearson")
        for i, a in enumerate(numeric_cols):
            for b in numeric_cols[i + 1 :]:
                value = float(corr_matrix.loc[a, b])
                if pd.isna(value):
                    continue
                top_pairs.append({
                    "feature_a": a,
                    "feature_b": b,
                    "correlation": round(value, _CORR_DIGITS),
                    "abs_correlation": round(abs(value), _CORR_DIGITS),
                })
        top_pairs = sorted(top_pairs, key=lambda x: -x["abs_correlation"])[:_TOP_K]

    target_cors: list[dict[str, Any]] = []
    target_is_numeric = target is not None and target in numeric.columns
    if target_is_numeric and numeric_cols:
        for col in numeric_cols:
            # Use pairwise-complete observations.
            value = float(df[[col, target]].dropna().corr(method="pearson").iloc[0, 1])
            if pd.isna(value):
                continue
            target_cors.append({
                "feature": col,
                "correlation": round(value, _CORR_DIGITS),
                "abs_correlation": round(abs(value), _CORR_DIGITS),
            })
        target_cors = sorted(target_cors, key=lambda x: -x["abs_correlation"])[:_TOP_K]

    return {
        "top_correlations": top_pairs,
        "target_correlations": target_cors,
    }


def class_balance(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    """Return class distribution and imbalance diagnostics for a target column.

    Schema::

        {
          "classes": [
            {"class": str, "count": int, "rate": float}
          ],
          "minority_class": {"class": str, "count": int, "rate": float},
          "majority_class": {"class": str, "count": int, "rate": float},
          "imbalance_ratio": float,  # majority_count / minority_count
          "min_class_warning": bool  # true if any class has < 5% of rows
        }
    """
    if target not in df.columns:
        return {
            "classes": [],
            "minority_class": None,
            "majority_class": None,
            "imbalance_ratio": None,
            "min_class_warning": False,
            "error": f"target column '{target}' not found",
        }

    total = len(df)
    counts = df[target].value_counts(dropna=False)
    classes = []
    for value, count in counts.items():
        rate = round(count / total, _MISSING_RATE_DIGITS) if total else 0.0
        classes.append({"class": str(value), "count": int(count), "rate": rate})

    minority_count = min(int(count) for _value, count in counts.items())
    majority_count = max(int(count) for _value, count in counts.items())
    imbalance_ratio = round(majority_count / minority_count, 2) if minority_count else None
    min_class_warning = any(float(c["rate"]) < 0.05 for c in classes)

    minority = min(classes, key=lambda x: (x["count"], x["class"]))
    majority = max(classes, key=lambda x: (x["count"], x["class"]))

    return {
        "classes": classes,
        "minority_class": minority,
        "majority_class": majority,
        "imbalance_ratio": imbalance_ratio,
        "min_class_warning": min_class_warning,
    }


def outlier_scan(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    """Return IQR and z-score outlier flags per numeric column.

    Schema::

        {
          "numeric_columns": [str],
          "columns": {
            "col_name": {
              "iqr_lower": float,
              "iqr_upper": float,
              "iqr_outlier_count": int,
              "iqr_outlier_rate": float,
              "z_outlier_count": int,  # |z| > 3
              "z_outlier_rate": float
            }
          }
        }
    """
    numeric = df.select_dtypes(include="number")
    numeric_cols = [c for c in numeric.columns if c != target]
    total = len(df)
    columns: dict[str, dict[str, Any]] = {}

    for col in numeric_cols:
        series = numeric[col].dropna()
        if len(series) == 0:
            columns[col] = {
                "iqr_lower": float("nan"),
                "iqr_upper": float("nan"),
                "iqr_outlier_count": 0,
                "iqr_outlier_rate": 0.0,
                "z_outlier_count": 0,
                "z_outlier_rate": 0.0,
            }
            continue

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = float(q1 - 1.5 * iqr)
        upper = float(q3 + 1.5 * iqr)
        iqr_outliers = int(((numeric[col] < lower) | (numeric[col] > upper)).sum())

        mean = series.mean()
        std = series.std(ddof=0)
        if std and not pd.isna(std):
            z_scores = ((numeric[col] - mean) / std).abs()
            z_outliers = int((z_scores > 3).sum())
        else:
            z_outliers = 0

        columns[col] = {
            "iqr_lower": lower,
            "iqr_upper": upper,
            "iqr_outlier_count": iqr_outliers,
            "iqr_outlier_rate": round(iqr_outliers / total, _MISSING_RATE_DIGITS) if total else 0.0,
            "z_outlier_count": z_outliers,
            "z_outlier_rate": round(z_outliers / total, _MISSING_RATE_DIGITS) if total else 0.0,
        }

    return {
        "numeric_columns": numeric_cols,
        "columns": columns,
    }


def leakage_suspects(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    """Return features suspiciously correlated with or predictive of the target.

    Heuristics (documented and deterministic):

    1. Perfect/near-perfect correlation with a numeric target (|rho| >= 0.99).
    2. Feature name contains the target name (case-insensitive) and is not the
       target itself — may indicate a derived/post-outcome column.
    3. Feature that is an exact duplicate of the target column.

    Schema::

        {
          "suspects": [
            {"feature": str, "reason": str, "target_correlation": float | None}
          ]
        }
    """
    if target is None:
        return {"suspects": [], "error": "target is required"}
    if target not in df.columns:
        return {"suspects": [], "error": f"target column '{target}' not found"}

    suspects: list[dict[str, Any]] = []
    numeric = df.select_dtypes(include="number")
    target_is_numeric = target in numeric.columns

    for col in df.columns:
        if col == target:
            continue

        # Name-based leakage heuristic.
        if target.lower() in col.lower():
            suspects.append({
                "feature": col,
                "reason": f"feature name contains target name '{target}'",
                "target_correlation": None,
            })
            continue

        # Exact duplicate of target.
        if df[col].equals(df[target]):
            suspects.append({
                "feature": col,
                "reason": "feature is an exact duplicate of the target",
                "target_correlation": None,
            })
            continue

        # Near-perfect correlation with numeric target.
        if target_is_numeric and col in numeric.columns:
            corr = float(df[[col, target]].dropna().corr(method="pearson").iloc[0, 1])
            if not pd.isna(corr) and abs(corr) >= 0.99:
                suspects.append({
                    "feature": col,
                    "reason": f"near-perfect correlation with target (|rho|={round(abs(corr), _CORR_DIGITS)})",
                    "target_correlation": round(corr, _CORR_DIGITS),
                })

    return {"suspects": suspects}


def feature_types(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    """Return a dtype/coercion report for each column.

    Schema::

        {
          "columns": {
            "col_name": {
              "inferred_dtype": str,
              "coerced_type": "numeric" | "categorical" | "datetime" | "text",
              "unique_count": int,
              "sample_values": [str]  # first 3 non-null values, stringified
            }
          },
          "numeric_count": int,
          "categorical_count": int,
          "datetime_count": int,
          "text_count": int
        }
    """
    columns: dict[str, dict[str, Any]] = {}
    counts = {"numeric": 0, "categorical": 0, "datetime": 0, "text": 0}

    for col in df.columns:
        dtype = str(df[col].dtype)
        unique_count = int(df[col].nunique(dropna=False))

        # First 3 non-null values, stringified deterministically.
        sample = df[col].dropna().head(3).tolist()
        sample_values = [str(v) for v in sample]

        # Coerce to a small set of semantic types.
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            coerced = "datetime"
        elif pd.api.types.is_numeric_dtype(df[col]):
            coerced = "numeric"
        elif unique_count <= 20 or isinstance(df[col].dtype, pd.CategoricalDtype):
            coerced = "categorical"
        else:
            coerced = "text"

        counts[coerced] += 1
        columns[col] = {
            "inferred_dtype": dtype,
            "coerced_type": coerced,
            "unique_count": unique_count,
            "sample_values": sample_values,
        }

    return {
        "columns": columns,
        "numeric_count": counts["numeric"],
        "categorical_count": counts["categorical"],
        "datetime_count": counts["datetime"],
        "text_count": counts["text"],
    }
