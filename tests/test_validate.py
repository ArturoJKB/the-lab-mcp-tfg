from pathlib import Path

import numpy as np
import pandas as pd

from thelab.run.runner import run_model


def _write_csv(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(content)
    return path


def test_single_class_target_rejected(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "a,b,label\n"
        "1,2,alpha\n"
        "3,4,alpha\n"
        "5,6,alpha\n"
        "7,8,alpha\n"
        "9,10,alpha\n"
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert ("only 1 unique target value" in result["error"].lower()
            or "only 1 classes" in result["error"].lower())


def test_id_like_target_rejected(tmp_path: Path):
    # 12 rows with 12 unique classes is ID-like and not sensible for classification.
    rows = "\n".join(f"{i},{i+1},class{i}" for i in range(12))
    csv = _write_csv(tmp_path, f"a,b,label\n{rows}\n")
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "not sensible" in result["error"].lower()


def test_cannot_stratify_rejected(tmp_path: Path):
    # 3 classes, 1 sample each: too small for stratification.
    csv = _write_csv(
        tmp_path,
        "a,b,label\n1,2,alpha\n3,4,beta\n5,6,gamma\n",
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "cannot stratify" in result["error"].lower()


def test_duplicate_columns_rejected(tmp_path: Path):
    # Enough rows and 2 classes so stratification and target-type checks pass.
    csv = _write_csv(
        tmp_path,
        "a,a,label\n"
        "1,2,alpha\n" "3,4,beta\n" "5,6,alpha\n" "7,8,beta\n"
        "9,10,alpha\n" "11,12,beta\n" "13,14,alpha\n" "15,16,beta\n"
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "duplicate column" in result["error"].lower()


def test_constant_feature_rejected(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "a,b,label\n"
        "1,2,alpha\n" "1,3,beta\n" "1,4,gamma\n" "1,5,delta\n"
        "1,6,alpha\n" "1,7,beta\n" "1,8,gamma\n" "1,9,delta\n"
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "constant" in result["error"].lower()


def test_infinite_feature_rejected(tmp_path: Path):
    df = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "b": [1.0, 2.0, np.inf, 4.0, 5.0, 6.0, 7.0, 8.0],
        "label": ["alpha", "beta", "gamma", "delta", "alpha", "beta", "gamma", "delta"],
    })
    csv = tmp_path / "data.csv"
    df.to_csv(csv, index=False)
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "infinite" in result["error"].lower()


def test_non_numeric_feature_rejected(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "a,b,label\n"
        "1,x,alpha\n" "2,y,beta\n" "3,z,gamma\n" "4,x,delta\n"
        "5,y,alpha\n" "6,z,beta\n" "7,x,gamma\n" "8,y,delta\n"
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "numeric" in result["error"].lower()


def test_no_features_after_target_rejected(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "label\nalpha\nbeta\ngamma\ndelta\n",
    )
    result = run_model(
        dataset=csv,
        target="label",
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=tmp_path,
    )
    assert result["status"] == "rejected"
    assert "feature" in result["error"].lower()
