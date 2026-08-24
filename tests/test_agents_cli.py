"""Tests for the A3.1 agent CLI hardening."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_worker_appends_session_summary(tmp_path: Path) -> None:
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
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    proposals_dir = tmp_path / "proposals"
    log_source = tmp_path / "agent-events.jsonl"

    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    env["THELAB_CONTEXT_LOG_SOURCE"] = str(log_source)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "thelab.agents.cli",
            "--mode",
            "worker",
            "--provider",
            "mock",
            "classify iris",
            "--dataset",
            str(csv),
            "--target",
            "species",
            "--proposals-dir",
            str(proposals_dir),
            "--json",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    # Verify the context log contains a session summary event.
    assert log_source.exists()
    lines = log_source.read_text().strip().splitlines()
    assert lines
    events = [json.loads(line) for line in lines]
    summaries = [e for e in events if e.get("event_type") == "agent_session_summary"]
    assert summaries
    tags = {tag for e in summaries for tag in e.get("tags", [])}
    assert any("agent_mode:worker" in tag for tag in tags)
