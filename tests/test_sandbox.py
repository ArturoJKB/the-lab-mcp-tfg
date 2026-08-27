"""Tests for the restricted code sandbox."""

import pytest

from thelab.model_service.app import app
from thelab.sandbox import run_in_sandbox
from thelab.sandbox.ast_check import check_code


def test_extreme_resource_params_are_clamped():
    """Absurd timeout/memory/output values must not error or disable limits."""
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/sandbox/run",
            json={
                "code": "print('ok')",
                "timeout": 10**9,
                "memory_limit_mb": 0,
                "max_output_bytes": 10**12,
            },
        )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"


def test_allowed_code_executes():
    result = run_in_sandbox("x = 1 + 1\nprint(x)")
    assert result.status == "completed"
    assert "2" in result.stdout


def test_import_whitelist_blocks_unknown():
    result = run_in_sandbox("import os")
    assert result.status in {"rejected", "failed"}
    assert result.error is not None
    assert "os" in result.error or "import not allowed" in (result.stderr or "")


def test_import_whitelist_allows_numpy():
    result = run_in_sandbox("import numpy as np\nprint(np.array([1,2,3]).sum())")
    assert result.status == "completed"
    assert "6" in result.stdout


def test_blocked_builtins_rejected():
    result = run_in_sandbox("eval('1+1')")
    assert result.status in {"rejected", "failed"}


def test_blocked_exec_rejected():
    result = run_in_sandbox("exec('print(1)')")
    assert result.status in {"rejected", "failed"}


def test_blocked_dynamic_class_rejected():
    result = run_in_sandbox("MyClass = type('MyClass', (), {})")
    assert result.status == "rejected"


def test_artifacts_collected():
    code = (
        "import pandas as pd\n"
        "df = pd.DataFrame({'x': [1, 2, 3]})\n"
        "df.to_csv('out.csv', index=False)\n"
    )
    result = run_in_sandbox(code)
    assert result.status == "completed"
    assert result.artifacts
    assert any(a["name"] == "out.csv" for a in result.artifacts)


def test_timeout_kills_long_running_code():
    result = run_in_sandbox("while True: pass", timeout=1)
    assert result.status == "timeout"


def test_check_code_blocks_dunder_access():
    result = check_code("x = ().__class__")
    assert not result.ok


def test_check_code_allows_safe_code():
    result = check_code("import numpy as np\nprint(np.pi)")
    assert result.ok


def test_inspect_blocked_to_protect_frames():
    # inspect.currentframe().f_builtins recovers unfiltered builtins; the
    # module must therefore be denied by the whitelist.
    result = run_in_sandbox("import inspect\nprint(inspect.currentframe())")
    assert result.status == "rejected"
    assert "inspect" in (result.error or "")


def test_sandbox_module_refs_scrubbed():
    # Importing thelab.eda initializes the thelab package; the sandbox
    # machinery must not remain reachable through plain attributes.
    code = (
        "import thelab.eda\n"
        "try:\n"
        "    thelab.sandbox.child\n"
        "    print('LEAK')\n"
        "except AttributeError:\n"
        "    print('SCRUBBED')\n"
    )
    result = run_in_sandbox(code)
    assert result.status == "completed"
    assert "SCRUBBED" in result.stdout
    assert "LEAK" not in result.stdout


def test_system_exit_returns_structured_result():
    # BaseException must not escape before the result JSON is written.
    result = run_in_sandbox("print('before')\nraise SystemExit(0)")
    assert result.status == "failed"
    assert "before" in result.stdout
    assert "SystemExit" in result.stderr


def test_matplotlib_savefig_headless():
    # matplotlib is whitelisted but optional; skip where it is not installed.
    pytest.importorskip("matplotlib")
    code = (
        "import matplotlib\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
        "plt.savefig('plot.png')\n"
        "print('saved')\n"
    )
    result = run_in_sandbox(code)
    assert result.status == "completed", result.stderr or result.error
    assert "saved" in result.stdout
    assert any(a["name"] == "plot.png" and a["kind"] == "image" for a in (result.artifacts or []))


def test_oversize_artifact_replaced_with_marker():
    code = "from pathlib import Path\nPath('big.txt').write_text('x' * (1024 * 1024 + 10))\n"
    result = run_in_sandbox(code)
    assert result.status == "completed"
    artifacts = {a["name"]: a for a in (result.artifacts or [])}
    assert "big.txt" in artifacts
    assert "too large" in (artifacts["big.txt"]["content"] or "")
