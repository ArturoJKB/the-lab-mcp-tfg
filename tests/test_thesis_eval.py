"""Tests for the thesis evaluation script."""

import subprocess
import sys
from pathlib import Path


def test_evaluate_thesis_script_exits_zero():
    proc = subprocess.run(
        [sys.executable, "scripts/evaluate_thesis.py"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"evaluator failed:\n{proc.stdout}\n{proc.stderr}"
    assert "Overall: PASS" in proc.stdout
    assert "RQ1: PASS" in proc.stdout
    assert "RQ2: PASS" in proc.stdout
    assert "RQ3: PASS" in proc.stdout
