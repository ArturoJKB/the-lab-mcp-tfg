"""Demo: deterministic EDA skills over a local CSV.

Usage:
    .venv/bin/python examples/eda_demo.py data/fixtures/iris.csv species
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is importable when running directly.
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from thelab.eda import (
    class_balance,
    correlation_hints,
    feature_types,
    leakage_suspects,
    missing_profile,
    outlier_scan,
)
from thelab.run.profile import read_csv


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: eda_demo.py <csv-path> [target]", file=sys.stderr)
        return 1

    dataset_path = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else None

    df = read_csv(dataset_path)
    report = {
        "dataset": str(dataset_path),
        "target": target,
        "missing_profile": missing_profile(df, target=target),
        "correlation_hints": correlation_hints(df, target=target),
        "class_balance": class_balance(df, target=target) if target else None,
        "outlier_scan": outlier_scan(df, target=target),
        "leakage_suspects": leakage_suspects(df, target=target) if target else None,
        "feature_types": feature_types(df, target=target),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
