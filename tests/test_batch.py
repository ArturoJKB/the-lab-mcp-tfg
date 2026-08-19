import json
import subprocess
import sys
from pathlib import Path

from thelab.run.batch import BatchRunner, write_markdown_report


def _iris_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "iris.csv"
    csv.write_text(
        "sepal_length,sepal_width,petal_length,petal_width,species\n"
        "5.1,3.5,1.4,0.2,setosa\n"
        "4.9,3.0,1.4,0.2,setosa\n"
        "4.7,3.2,1.3,0.2,setosa\n"
        "7.0,3.2,4.7,1.4,versicolor\n"
        "6.4,3.2,4.5,1.5,versicolor\n"
        "6.9,3.1,4.9,1.5,versicolor\n"
        "6.3,3.3,6.0,2.5,virginica\n"
        "5.8,2.7,5.1,1.9,virginica\n"
        "7.1,3.0,5.9,2.1,virginica\n"
        "7.6,3.0,6.6,2.1,virginica\n"
        "4.9,2.5,4.5,1.7,virginica\n"
    )
    return csv


def _batch_config(tmp_path: Path, csv: Path) -> Path:
    config = tmp_path / "batch.json"
    config.write_text(
        json.dumps(
            [
                {
                    "dataset": str(csv.relative_to(tmp_path)),
                    "target": "species",
                    "model": "logistic_regression",
                    "seed": 42,
                },
                {
                    "dataset": str(csv.relative_to(tmp_path)),
                    "target": "species",
                    "model": "random_forest",
                    "seed": 42,
                },
            ]
        ),
        encoding="utf-8",
    )
    return config


def test_batch_runner_loads_config(tmp_path: Path):
    csv = _iris_csv(tmp_path)
    config = _batch_config(tmp_path, csv)
    runner = BatchRunner(workspace_root=tmp_path)
    entries = runner.load_config(config)
    assert len(entries) == 2
    assert entries[0].model == "logistic_regression"
    assert entries[1].model == "random_forest"


def test_batch_runner_executes_all_entries(tmp_path: Path):
    csv = _iris_csv(tmp_path)
    config = _batch_config(tmp_path, csv)
    runner = BatchRunner(workspace_root=tmp_path)
    entries = runner.load_config(config)
    results = runner.run(entries, output="runs")

    assert len(results) == 2
    assert all(r.status == "completed" for r in results)
    assert all(r.run_id for r in results)


def test_batch_runner_writes_summary(tmp_path: Path):
    csv = _iris_csv(tmp_path)
    config = _batch_config(tmp_path, csv)
    runner = BatchRunner(workspace_root=tmp_path)
    entries = runner.load_config(config)
    results = runner.run(entries, output="runs")
    summary_path = tmp_path / "batch_summary.json"
    runner.write_summary(results, summary_path)

    summary = json.loads(summary_path.read_text())
    assert summary["total"] == 2
    assert summary["completed"] == 2
    assert summary["failed"] == 0
    assert len(summary["results"]) == 2


def test_batch_runner_continues_past_failure(tmp_path: Path):
    csv = _iris_csv(tmp_path)
    config = tmp_path / "batch.json"
    config.write_text(
        json.dumps(
            [
                {
                    "dataset": "does_not_exist.csv",
                    "target": "species",
                    "model": "logistic_regression",
                    "seed": 42,
                },
                {
                    "dataset": str(csv.relative_to(tmp_path)),
                    "target": "species",
                    "model": "random_forest",
                    "seed": 42,
                },
            ]
        ),
        encoding="utf-8",
    )
    runner = BatchRunner(workspace_root=tmp_path)
    entries = runner.load_config(config)
    results = runner.run(entries, output="runs")

    assert len(results) == 2
    assert results[0].status == "rejected"
    assert results[1].status == "completed"


def test_write_markdown_report(tmp_path: Path):
    csv = _iris_csv(tmp_path)
    runner = BatchRunner(workspace_root=tmp_path)
    entries = runner.load_config(_batch_config(tmp_path, csv))
    results = runner.run(entries, output="runs")
    report_path = tmp_path / "batch_report.md"
    write_markdown_report(results, report_path)

    text = report_path.read_text()
    assert "# Batch Run Report" in text
    assert "| Dataset |" in text
    assert "logistic_regression" in text
    assert "random_forest" in text


def test_cli_batch_command(tmp_path: Path):
    csv = _iris_csv(tmp_path)
    config = _batch_config(tmp_path, csv)
    result = subprocess.run(
        [
            sys.executable, "-m", "thelab.cli",
            "run", "batch",
            "--config", str(config),
            "--output", "runs",
            "--report", str(tmp_path / "report.md"),
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "runs" / "batch_summary.json").is_file()
    assert (tmp_path / "report.md").is_file()
