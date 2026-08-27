"""Prepare the three B1 benchmark datasets as CSV files.

Usage:
    .venv/bin/python scripts/prepare_b1_datasets.py

Output:
    data/benchmarks/california_housing.csv
    data/benchmarks/breast_cancer.csv
    data/benchmarks/wine_quality_red.csv
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pandas as pd
from sklearn.datasets import fetch_california_housing, load_breast_cancer

DATA_DIR = Path("data/benchmarks")
WINE_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/wine-quality/winequality-red.csv"


def _prepare_california_housing() -> Path:
    path = DATA_DIR / "california_housing.csv"
    data = fetch_california_housing(as_frame=True)
    df = data.frame
    df["MedHouseVal"] = data.target
    df.to_csv(path, index=False)
    return path


def _prepare_breast_cancer() -> Path:
    path = DATA_DIR / "breast_cancer.csv"
    data = load_breast_cancer(as_frame=True)
    df = data.frame
    df["target"] = data.target
    df.to_csv(path, index=False)
    return path


def _prepare_wine_quality() -> Path:
    path = DATA_DIR / "wine_quality_red.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        response = httpx.get(WINE_URL, timeout=60)
        response.raise_for_status()
        # UCI wine quality CSV is semicolon-separated; rewrite as comma-separated.
        df = pd.read_csv(io.StringIO(response.text), sep=";")
        df.to_csv(path, index=False)
    except httpx.HTTPError as exc:
        print(f"Failed to download wine quality data: {exc}", file=__import__("sys").stderr)
        raise
    return path


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    paths = [
        _prepare_california_housing(),
        _prepare_breast_cancer(),
        _prepare_wine_quality(),
    ]

    for path in paths:
        print(f"Prepared: {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
