"""Tests for B1 cross-domain benchmark utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prepare_b1_datasets import main as prepare_main
from scripts.run_b1_benchmark import (
    BENCHMARK_DATASETS,
    _summary_metric,
    _write_report,
)


def test_dataset_configs_point_to_csv_files() -> None:
    for ds in BENCHMARK_DATASETS:
        assert "domain" in ds
        assert "name" in ds
        assert "dataset" in ds
        assert "target" in ds
        assert "task_type" in ds
        assert "baseline_model" in ds


def test_summary_metric_for_regression() -> None:
    assert _summary_metric({"test_rmse": 0.5}, "regression") == "RMSE=0.5000"


def test_summary_metric_for_classification() -> None:
    assert _summary_metric({"test_accuracy": 0.95}, "classification") == "Acc=0.9500"


def test_summary_metric_missing_value() -> None:
    assert _summary_metric({}, "regression") == "N/A"


def test_write_report_creates_markdown(tmp_path: Path) -> None:
    manifest = {
        "created_at": "2026-08-24T00:00:00+00:00",
        "providers": [
            {
                "provider": "mock",
                "model": "mock-model",
                "datasets": [
                    {
                        "domain": "real_estate",
                        "name": "california_housing",
                        "dataset": "data/benchmarks/california_housing.csv",
                        "target": "MedHouseVal",
                        "task_type": "regression",
                        "deterministic_run_id": "run-1",
                        "deterministic_status": "completed",
                        "agent_proposal_id": "prop-1",
                        "agent_run_ids": ["run-2"],
                        "metrics": {
                            "deterministic": {"test_rmse": 0.75},
                            "agent": {"test_rmse": 0.70},
                        },
                    }
                ],
            }
        ],
    }

    from scripts.run_b1_benchmark import BENCHMARK_DIR

    original_dir = BENCHMARK_DIR
    try:
        # Patch the global benchmark dir to use tmp_path for the test.
        from scripts import run_b1_benchmark

        run_b1_benchmark.BENCHMARK_DIR = tmp_path
        run_b1_benchmark.REPORTS_DIR = tmp_path / "reports"
        report_path = _write_report(manifest)
        assert report_path.exists()
        text = report_path.read_text(encoding="utf-8")
        assert "B1 Cross-domain Benchmark Report" in text
        assert "mock-model" in text
        assert "RMSE=0.7500" in text
        assert "RMSE=0.7000" in text
    finally:
        run_b1_benchmark.BENCHMARK_DIR = original_dir
        run_b1_benchmark.REPORTS_DIR = original_dir / "reports"


def test_prepare_datasets_creates_expected_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import prepare_b1_datasets

    monkeypatch.setattr(prepare_b1_datasets, "DATA_DIR", tmp_path)

    # Wine download is network-dependent; skip the download in this unit test
    # by writing a minimal CSV first.
    wine_path = tmp_path / "wine_quality_red.csv"
    wine_path.write_text("fixed acidity;volatile acidity;citric acid;quality\n7.4;0.7;0;5\n", encoding="utf-8")

    # Patch httpx.get to avoid network.
    wine_text = wine_path.read_text(encoding="utf-8")

    class FakeResponse:
        status_code = 200
        text = wine_text

        def raise_for_status(self) -> None:
            pass

        @property
        def content(self) -> bytes:
            return wine_text.encode("utf-8")

    monkeypatch.setattr("httpx.get", lambda url, timeout: FakeResponse())

    assert prepare_main() == 0

    assert (tmp_path / "california_housing.csv").exists()
    assert (tmp_path / "breast_cancer.csv").exists()
    assert (tmp_path / "wine_quality_red.csv").exists()
