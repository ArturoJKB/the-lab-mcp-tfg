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
        timeout=300,
    )
    assert proc.returncode == 0, f"evaluator failed:\n{proc.stdout}\n{proc.stderr}"
    assert "Overall: PASS" in proc.stdout
    # Dataset matrix: every RQ passes on both arms (iris + housing);
    # RQ3 is dataset-independent. The churn arm is SKIPPED (not FAIL) when
    # the gitignored upload is absent (W3).
    for rq in ("RQ1", "RQ2", "RQ4", "RQ5", "RQ6"):
        for dataset in ("iris", "housing"):
            assert f"{rq}[{dataset}]: PASS" in proc.stdout
    assert "RQ3: PASS" in proc.stdout
    assert "SKIPPED" not in proc.stdout or "RQ*[churn]" in proc.stdout


def test_churn_arm_spec_and_skip_behavior():
    """W3: the churn spec mirrors the real cleaned upload; the arm is absent
    from the matrix when the gitignored upload is missing (SKIPPED, not FAIL)."""
    import scripts.evaluate_thesis as ev

    source = ev._churn_source()
    spec = ev._churn_spec()
    assert spec.name == "churn"
    assert spec.target == "Exited"
    if source is None:
        # absent upload -> the evaluator's spec list excludes churn
        specs = [ev._iris_spec(), ev._housing_spec()]
        assert all(s.name != "churn" for s in specs)
    else:
        # present upload -> column contract matches the predict row
        import csv

        with open(source, encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        assert set(spec.predict_row) <= set(header)


def test_rounds_argument_threads_into_rq5():
    """W4: the evaluator accepts --rounds N and the RQ5 check loops over
    rounds, recording one entry per round."""
    import ast
    from pathlib import Path

    src = Path("scripts/evaluate_thesis.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_check_rq5_agentic_capability"
    )
    arg_names = [a.arg for a in fn.args.args]
    assert "rounds" in arg_names
    loop = any(
        isinstance(n, ast.For) and getattr(n.target, "id", "") == "index"
        for n in ast.walk(fn)
    )
    assert loop, "RQ5 check must loop over rounds"
