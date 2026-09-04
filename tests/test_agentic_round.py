"""Tests for the agentic round (P5.B): sandboxed transforms, gating, execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from thelab.agents.approval import record_human_approval
from thelab.agents.mock import MockProvider
from thelab.agents.worker import ProposalStore
from thelab.ide.agentic_round import (
    RoundConfig,
    _deterministic_brief,
    _generate_transform,
    _validate_transform,
    build_context_pack,
    execute_approved_round,
    run_agentic_round,
)
from thelab.ide.experiment import Experiment, ExperimentStore
from thelab.ide.jobs import reset_job_manager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

IRIS_ROWS = [
    "sepal_length,sepal_width,species",
    *[
        f"{sl},{sw},{sp}"
        for sp, samples in {
            "setosa": [(5.1, 3.5), (4.9, 3.0), (4.7, 3.2), (4.6, 3.1), (5.0, 3.6)],
            "versicolor": [(7.0, 3.2), (6.4, 3.2), (6.9, 3.1), (5.5, 2.3), (6.5, 2.8)],
            "virginica": [(6.3, 3.3), (5.8, 2.7), (7.1, 3.0), (6.3, 2.9), (6.5, 3.0)],
        }.items()
        for sl, sw in samples
    ],
]


@pytest.fixture
def round_env(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    experiments = tmp_path / "experiments"
    for d in (uploads, fixtures, runs, proposals, experiments):
        d.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_EXPERIMENTS_DIR", str(experiments))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("THELAB_CONTEXT_LOG_SOURCE", str(tmp_path / "logs" / "events.jsonl"))
    reset_job_manager()
    (uploads / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    return uploads, runs, proposals, experiments


@pytest.fixture
def deterministic_result() -> dict:
    return {
        "status": "completed",
        "eda": {"eda_context": "Features: 4 numeric; Classes: 3, imbalance ratio: 1.0"},
        "feature_engineering": {
            "cleaned_dataset_id": "uploads/iris.csv",
            "clean_metadata": {"skipped": True, "reason": "dataset already cleaned"},
            "top_models": [
                {"model": "logistic_regression", "metrics": {"test_accuracy": 0.9}}
            ],
        },
        "model_selection": {
            "recommendation": {
                "best_model": "logistic_regression",
                "model_grid": ["logistic_regression", "random_forest"],
                "seeds": [42, 43],
            }
        },
        "training_results": [
            {
                "dataset": "data/uploads/iris.csv",
                "model": "logistic_regression",
                "seed": 42,
                "status": "completed",
                "run_id": "run-20260902-000000-deadbeef",
                "metrics": {"test_accuracy": 1.0},
            }
        ],
    }


@pytest.fixture
def experiment(round_env) -> Experiment:
    experiment = Experiment(
        experiment_id="exp-test-round",
        goal="Predict the iris species",
        dataset_id="uploads/iris.csv",
        target="species",
    )
    ExperimentStore().save(experiment)
    return experiment


# ---------------------------------------------------------------------------
# Unit: context pack + deterministic brief
# ---------------------------------------------------------------------------


def test_context_pack_extracts_deterministic_evidence(experiment, deterministic_result):
    pack = build_context_pack(experiment, deterministic_result)
    assert pack["goal"] == "Predict the iris species"
    assert pack["best_deterministic"]["run_id"] == "run-20260902-000000-deadbeef"
    assert pack["recommendation"]["model_grid"] == ["logistic_regression", "random_forest"]


def test_deterministic_brief_is_grounded_in_pack(deterministic_result):
    experiment = Experiment("exp-x", "goal", "uploads/iris.csv", "species")
    pack = build_context_pack(experiment, deterministic_result)
    brief = _deterministic_brief(pack)
    assert brief["findings"]
    assert any("logistic_regression" in f for f in brief["findings"])
    assert brief["risks"]


# ---------------------------------------------------------------------------
# Unit: transform generation, validation, sandbox round-trip
# ---------------------------------------------------------------------------


def _transform_code(code: str) -> MockProvider:
    return MockProvider(
        [json.dumps({"code": code, "rationale": "test transform"})]
    )


def test_transform_valid_code_produces_dataset_artifact(
    round_env, experiment, deterministic_result
):
    uploads, _, _, _ = round_env
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "df['sepal_ratio'] = df['sepal_length'] / df['sepal_width']\n"
        "df.to_csv('transformed.csv', index=False)\n"
    )
    pack = build_context_pack(experiment, deterministic_result)
    record = _generate_transform(
        _transform_code(code), pack, _deterministic_brief(pack), RoundConfig()
    )
    assert record["status"] == "completed", record
    assert record["dataset_id"].startswith("uploads/")
    artifact = uploads / Path(record["dataset_id"]).name
    assert artifact.is_file()
    assert "sepal_ratio" in artifact.read_text(encoding="utf-8")


def test_transform_rejected_on_degenerate_target(round_env, experiment, deterministic_result):
    uploads, _, _, _ = round_env
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "df['species'] = 'setosa'\n"
        "df.to_csv('transformed.csv', index=False)\n"
    )
    pack = build_context_pack(experiment, deterministic_result)
    record = _generate_transform(
        _transform_code(code), pack, _deterministic_brief(pack), RoundConfig()
    )
    assert record["status"] == "rejected"
    assert "collapsed" in record["error"]
    assert not list(uploads.glob("*_agentic*.csv")), "rejected artifact must not persist"


def test_transform_rejected_when_sandbox_code_fails(round_env, experiment, deterministic_result):
    code = "df = undefined_variable\n"
    pack = build_context_pack(experiment, deterministic_result)
    record = _generate_transform(
        _transform_code(code), pack, _deterministic_brief(pack), RoundConfig()
    )
    assert record["status"] == "rejected"


def test_validate_transform_flags_row_explosion(tmp_path: Path):
    src = tmp_path / "src.csv"
    out = tmp_path / "out.csv"
    src.write_text("a,species\n1,x\n2,y\n", encoding="utf-8")
    out.write_text("a,species\n" + "\n".join(f"{i},x" for i in range(100)), encoding="utf-8")
    errors = _validate_transform(out, src, "species")
    assert any("row explosion" in e for e in errors)


def test_transform_skipped_without_provider(round_env, experiment, deterministic_result):
    pack = build_context_pack(experiment, deterministic_result)
    record = _generate_transform(None, pack, _deterministic_brief(pack), RoundConfig())
    assert record["status"] == "skipped"
    assert record["llm_used"] is False


# ---------------------------------------------------------------------------
# Round: approval gate + execution
# ---------------------------------------------------------------------------


def test_round_requires_human_approval_and_records_proposal(
    round_env, experiment, deterministic_result
):
    _, runs, proposals, experiments = round_env
    record = asyncio.run(
        run_agentic_round(
            experiment,
            deterministic_result,
            provider=None,
            require_approval=True,
        )
    )
    assert record["status"] == "awaiting_approval"
    assert record["require_approval"] is True
    assert record["proposal_id"]
    proposal = ProposalStore(proposals).load(record["proposal_id"])
    assert proposal.model_grid  # deterministic fallback selection
    assert not list(proposals.glob("*.approved.json")), "no silent approval"
    # Round record persisted next to the experiment
    record_file = experiments / f"{experiment.experiment_id}.agentic_round.json"
    assert record_file.is_file()
    persisted = json.loads(record_file.read_text(encoding="utf-8"))
    assert persisted["status"] == "awaiting_approval"
    # Transform stage skipped deterministically (no provider), never silently run
    assert persisted["transform"]["status"] == "skipped"


def test_execute_before_approval_raises(round_env, experiment, deterministic_result):
    from thelab.agents.approval import HumanApprovalRequired

    record = asyncio.run(
        run_agentic_round(experiment, deterministic_result, provider=None, require_approval=True)
    )
    with pytest.raises(HumanApprovalRequired):
        execute_approved_round(experiment, record["proposal_id"])


def test_rejected_round_proposal_cannot_execute(round_env, experiment, deterministic_result):
    _, _, proposals, _ = round_env
    record = asyncio.run(
        run_agentic_round(experiment, deterministic_result, provider=None, require_approval=True)
    )
    store = ProposalStore(proposals)
    store.reject(record["proposal_id"], principal="human", reason="nope")
    from thelab.agents.approval import ApprovalDenied

    with pytest.raises(ApprovalDenied):
        execute_approved_round(experiment, record["proposal_id"])


def test_execute_approved_round_builds_comparison(
    round_env, experiment, deterministic_result
):
    _, runs, proposals, experiments = round_env
    experiment.best_run_id = "run-20260902-000000-deadbeef"
    experiment.best_metrics = {"test_accuracy": 1.0, "test_f1_macro": 1.0}
    record = asyncio.run(
        run_agentic_round(experiment, deterministic_result, provider=None, require_approval=True)
    )
    record_human_approval(
        ProposalStore(proposals), record["proposal_id"], principal="ui"
    )
    result = execute_approved_round(experiment, record["proposal_id"])
    assert result["status"] in {"completed", "failed"}
    comparison = result["comparison"]
    assert comparison["deterministic_best"]["run_id"] == "run-20260902-000000-deadbeef"
    assert comparison["agentic_total"] >= comparison["agentic_completed"]
    assert 0.0 <= (comparison["validity_rate"] or 0.0) <= 1.0
    assert "metric_delta" in comparison
    # Round record updated with the execution outcome
    persisted = json.loads(
        (experiments / f"{experiment.experiment_id}.agentic_round.json").read_text(encoding="utf-8")
    )
    assert persisted["execution"]["proposal_id"] == record["proposal_id"]


# ---------------------------------------------------------------------------
# End-to-end: experiment job -> round -> UI approval -> gated execution
# ---------------------------------------------------------------------------


def test_e2e_agentic_round_via_api(round_env, iris_dataset=None):
    import time

    from fastapi.testclient import TestClient

    from thelab.model_service.app import app

    uploads, runs, proposals, experiments = round_env
    # A cleaned dataset so the deterministic stage skips cleaning and the
    # round has a cleaned_dataset_id to work from.
    (uploads / "iris_cleaned.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")

    client = TestClient(app)
    response = client.post(
        "/experiment/run",
        json={
            "goal": "Predict the iris species",
            "dataset_id": "uploads/iris_cleaned.csv",
            "target": "species",
            "provider": "mock",
            "agentic_round": True,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    experiment_id, job_id = data["experiment_id"], data["job_id"]

    deadline = time.time() + 420.0
    job = {"status": "running"}
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()["data"]
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.2)
    assert job["status"] == "completed", job.get("error")

    # Round produced a proposal and the experiment paused at the human gate.
    status = client.get(f"/experiment/{experiment_id}/status").json()["data"]
    assert status["state"] == "awaiting_approval"
    round_info = client.get(f"/experiment/{experiment_id}/agentic-round").json()["data"]
    assert round_info["record"]["status"] == "awaiting_approval"
    assert round_info["record"]["transform"]["status"] == "skipped"
    proposal_id = round_info["record"]["proposal_id"]
    assert not (proposals / f"{proposal_id}.approved.json").is_file(), "no silent round approval"

    # Human approves through the UI endpoint; execution runs gated.
    approved = client.post(f"/experiment/{experiment_id}/agentic-round/approve")
    assert approved.status_code == 200
    execute_job_id = approved.json()["data"]["job_id"]
    assert (proposals / f"{proposal_id}.approved.json").is_file()

    deadline = time.time() + 420.0
    while time.time() < deadline:
        exec_job = client.get(f"/jobs/{execute_job_id}").json()["data"]
        if exec_job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.2)
    assert exec_job["status"] == "completed", exec_job.get("error")

    final = client.get(f"/experiment/{experiment_id}/status").json()["data"]
    assert final["state"] == "completed"
    round_after = client.get(f"/experiment/{experiment_id}/agentic-round").json()["data"]
    assert round_after["record"]["execution"]["comparison"]["deterministic_best"]
    assert round_after["record"]["execution"]["comparison"]["agentic_total"] > 0


def test_e2e_agentic_round_reject_keeps_deterministic_result(round_env):
    import time

    from fastapi.testclient import TestClient

    from thelab.model_service.app import app

    uploads, _, proposals, _ = round_env
    (uploads / "iris_cleaned.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")

    client = TestClient(app)
    response = client.post(
        "/experiment/run",
        json={
            "goal": "Predict the iris species",
            "dataset_id": "uploads/iris_cleaned.csv",
            "target": "species",
            "provider": "mock",
            "agentic_round": True,
        },
    )
    data = response.json()["data"]
    experiment_id, job_id = data["experiment_id"], data["job_id"]

    deadline = time.time() + 420.0
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()["data"]
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.2)

    round_info = client.get(f"/experiment/{experiment_id}/agentic-round").json()["data"]
    proposal_id = round_info["record"]["proposal_id"]

    rejected = client.post(
        f"/experiment/{experiment_id}/agentic-round/reject",
        json={"reason": "not needed for this demo"},
    )
    assert rejected.status_code == 200
    assert (proposals / f"{proposal_id}.rejected.json").is_file()
    final = client.get(f"/experiment/{experiment_id}/status").json()["data"]
    assert final["state"] == "completed", "deterministic result stands after rejection"
    # Rejected proposals can never be executed afterwards.
    denied = client.post(f"/experiment/{experiment_id}/agentic-round/approve")
    assert denied.status_code == 400


# ---------------------------------------------------------------------------
# B7: large-dataset transform via the artifact-dir channel
# ---------------------------------------------------------------------------


def test_transform_handles_large_dataset(round_env, experiment):
    """A >1MB dataset transforms end-to-end (input_dir/artifact_dir channels)."""
    uploads, _, _, _ = round_env
    import io

    rows = ["f1,f2,f3,f4,species"]
    body = io.StringIO()
    for i in range(60000):
        body.write(
            f"{(i % 97) / 10:.2f},{(i % 53) / 7:.2f},{(i % 31) / 3:.2f},"
            f"{(i % 13) / 2:.2f},{'a' if i % 2 else 'b'}\n"
        )
    (uploads / "big_cleaned.csv").write_text("\n".join(rows) + "\n" + body.getvalue())
    big = uploads / "big_cleaned.csv"
    assert big.stat().st_size > 1024 * 1024

    pack = {
        "target": "species",
        "eda_context": "synthetic",
        "cleaned_dataset_id": "uploads/big_cleaned.csv",
        "baseline_top_models": [],
    }
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "df['f1_ratio'] = df['f1'] / (df['f2'] + 1)\n"
        "df.to_csv('transformed.csv', index=False)\n"
    )
    record = _generate_transform(
        _transform_code(code), pack, {"findings": ["x"]}, RoundConfig()
    )
    assert record["status"] == "completed", record
    artifact = uploads / Path(record["dataset_id"]).name
    assert artifact.is_file()
    assert artifact.stat().st_size > 1024 * 1024
    assert "f1_ratio" in artifact.read_text(encoding="utf-8")[:5000]


def test_round_mode_degraded_without_llm(round_env, experiment, deterministic_result):
    """provider=None => every stage is fallback and the round is not 'agentic'."""
    record = asyncio.run(
        run_agentic_round(experiment, deterministic_result, provider=None, require_approval=True)
    )
    assert record["mode"] == "degraded_deterministic"
    assert record["brief"]["source"] == "deterministic_fallback"
    assert record["transform"]["source"] == "deterministic_fallback"
    assert record["selection"]["source"] == "deterministic_fallback"


def test_round_mode_agentic_with_llm_transform(round_env, experiment, deterministic_result):
    """A scripted LLM transform makes the round authentically agentic."""
    record = asyncio.run(
        run_agentic_round(
            experiment,
            deterministic_result,
            provider=MockProvider(
                [
                    json.dumps(
                        {
                            "findings": ["class balance is even"],
                            "opportunities": ["sepal ratios may help"],
                            "risks": ["avoid target leakage"],
                        }
                    ),
                    json.dumps(
                        {
                            "code": (
                                "import pandas as pd\n"
                                "df = pd.read_csv('dataset.csv')\n"
                                "df['ratio'] = df['sepal_length'] / df['sepal_width']\n"
                                "df.to_csv('transformed.csv', index=False)\n"
                            ),
                            "rationale": "sepal ratio feature",
                        }
                    ),
                    json.dumps(
                        {
                            "model_grid": ["logistic_regression"],
                            "seeds": [42],
                            "hyperparameter_grid": {},
                            "rationale": "llm pick",
                        }
                    ),
                ]
            ),
            require_approval=True,
        )
    )
    assert record["mode"] == "agentic"
    assert record["brief"]["source"] == "llm"
    assert record["transform"]["source"] == "llm"
    assert record["selection"]["source"] == "llm"
    assert record["transform"]["status"] == "completed"
    assert record["status"] == "awaiting_approval"
    # The proposal trains on the transformed dataset, not the cleaned one.
    assert record["proposal"]["dataset"].endswith("_agentic.csv")


# ---------------------------------------------------------------------------
# Task-aware model selection (live-run audit 2026-09-03: LLM picked regression
# models for a classification task -> guaranteed rejection burst)
# ---------------------------------------------------------------------------


def test_registry_for_task_filters_by_task_type():
    from thelab.ide.agentic_round import _registry_for_task

    classification = _registry_for_task("classification")
    regression = _registry_for_task("regression")
    assert "logistic_regression" in classification
    assert "linear_regression" not in classification
    assert "ridge" in regression
    assert "logistic_regression" not in regression
    auto = _registry_for_task("auto")
    assert "logistic_regression" in auto and "ridge" in auto


def test_selector_post_filters_wrong_task_models(round_env, experiment, deterministic_result):
    """A scripted selector proposing a regressor for classification is
    deterministically filtered instead of producing a rejection burst."""
    from thelab.ide.agentic_round import _generate_selection, build_context_pack

    pack = build_context_pack(experiment, deterministic_result)
    assert pack["task_type"] == "classification"
    scripted = {
        "model_grid": ["linear_regression", "ridge", "logistic_regression"],
        "seeds": [42],
        "hyperparameter_grid": {},
        "rationale": "llm pick",
    }
    selection, llm_used = _generate_selection(
        MockProvider([json.dumps(scripted)]), pack, {"findings": []}, {"status": "skipped"}, RoundConfig()
    )
    assert llm_used is True
    assert "linear_regression" not in selection["model_grid"]
    assert "ridge" not in selection["model_grid"]
    assert "logistic_regression" in selection["model_grid"]


def test_selector_falls_back_when_all_wrong_task(round_env, experiment, deterministic_result):
    from thelab.ide.agentic_round import _generate_selection, build_context_pack

    pack = build_context_pack(experiment, deterministic_result)
    scripted = {
        "model_grid": ["linear_regression"],
        "seeds": [42],
        "hyperparameter_grid": {},
        "rationale": "llm pick",
    }
    selection, llm_used = _generate_selection(
        MockProvider([json.dumps(scripted)]), pack, {"findings": []}, {"status": "skipped"}, RoundConfig()
    )
    assert llm_used is False  # fell back to the deterministic recommendation
    assert "linear_regression" not in selection["model_grid"]


def test_selector_caps_llm_grid(round_env, experiment, deterministic_result):
    """F3: the round's selector stage caps the LLM grid deterministically
    (and the task filter keeps classification models only)."""
    from thelab.ide.agentic_round import (
        RoundConfig,
        _generate_selection,
        build_context_pack,
    )

    pack = build_context_pack(experiment, deterministic_result)
    scripted = {
        "model_grid": [
            "logistic_regression", "random_forest", "sgd_classifier",
            "hist_gradient_boosting", "svc",
        ],
        "seeds": [42, 43, 44, 45],
        "hyperparameter_grid": {"C": [0.1, 1.0, 10.0, 100.0, 1000.0], "max_iter": [100, 200]},
        "rationale": "llm explosion",
    }
    selection, llm_used = _generate_selection(
        MockProvider([json.dumps(scripted)]), pack, {"findings": []}, {"status": "skipped"},
        RoundConfig(),
    )
    assert llm_used is True
    assert len(selection["model_grid"]) <= 3
    assert len(selection["seeds"]) <= 3
    assert all("linear" not in m and "regressor" not in m and m != "ridge"
               for m in selection["model_grid"])
    product = 1
    for values in selection["hyperparameter_grid"].values():
        product *= max(len(values), 1)
    assert product <= 4
    assert selection["grid_capped"] is True


def test_transform_rejected_on_target_quantization(round_env, experiment):
    """Live housing failure (2026-09-03): a transform that binned the float
    target passed every earlier check and flipped the inferred task type."""
    uploads, _, _, _ = round_env
    rows = ["median_income,housing_age,median_house_value"]
    for i in range(200):
        rows.append(f"{1.0 + (i % 40) * 0.3:.2f},{5 + (i % 30)},{450000 + (i % 50) * 1731.17:.2f}")
    (uploads / "house_cleaned.csv").write_text("\n".join(rows), encoding="utf-8")

    pack = {
        "target": "median_house_value",
        "eda_context": "regression",
        "cleaned_dataset_id": "uploads/house_cleaned.csv",
        "baseline_top_models": [],
    }
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "df['median_house_value'] = (df['median_house_value'] // 50000) * 50000\n"
        "df.to_csv('transformed.csv', index=False)\n"
    )
    record = _generate_transform(
        _transform_code(code), pack, {"findings": []}, RoundConfig()
    )
    assert record["status"] == "rejected", record
    assert "dtype kind changed" in record["error"] or "cardinality" in record["error"]
    import glob
    assert not glob.glob(str(uploads / "house_cleaned_agentic*.csv"))


class _RecordingProvider:
    """Scripted provider that records the instructions it receives."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.prompts: list[str] = []

    def complete(self, messages, tools):  # noqa: ANN001, ANN202
        self.prompts.append(messages[-1].content if messages else "")
        from thelab.agents.provider import AgentTurn

        return AgentTurn(text=self.responses.pop(0))


def _good_transform_code() -> str:
    return (
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "df['income_per_age'] = df['median_income'] / (df['housing_age'] + 1)\n"
        "df.to_csv('transformed.csv', index=False)\n"
    )


def _quantizing_transform_code() -> str:
    return (
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "df['median_house_value'] = (df['median_house_value'] // 50000) * 50000\n"
        "df.to_csv('transformed.csv', index=False)\n"
    )


def test_transform_retry_recovers_after_validation_failure(round_env, experiment):
    """W2: a validation-failed first attempt is retried once with the exact
    rejection reasons fed back; a valid second attempt completes the round."""
    uploads, _, _, _ = round_env
    rows = ["median_income,housing_age,median_house_value"]
    for i in range(200):
        rows.append(f"{1.0 + (i % 40) * 0.3:.2f},{5 + (i % 30)},{450000 + (i % 50) * 1731.17:.2f}")
    (uploads / "house_cleaned.csv").write_text("\n".join(rows), encoding="utf-8")

    pack = {
        "target": "median_house_value",
        "eda_context": "regression",
        "cleaned_dataset_id": "uploads/house_cleaned.csv",
        "baseline_top_models": [],
    }
    provider = _RecordingProvider(
        [
            json.dumps({"code": _quantizing_transform_code(), "rationale": "bad attempt"}),
            json.dumps({"code": _good_transform_code(), "rationale": "fixed attempt"}),
        ]
    )
    record = _generate_transform(provider, pack, {"findings": []}, RoundConfig())

    assert record["status"] == "completed", json.dumps(
        {k: v for k, v in record.items() if k != "code"}, default=str
    )[:1500]
    assert record["attempt_count"] == 2
    assert [a["status"] for a in record["attempts"]] == ["rejected", "completed"]
    assert record["validation"]["ok"] is True
    assert record["dataset_id"].startswith("uploads/")
    # The remediation feedback reached attempt 2: the exact failure text and
    # the contract reminder must be in the second prompt.
    assert "FAILED deterministic validation" in provider.prompts[1]
    assert (
        "cardinality" in provider.prompts[1] or "dtype kind changed" in provider.prompts[1]
    )
    import glob

    assert len(glob.glob(str(uploads / "house_cleaned_agentic*.csv"))) == 1


def test_transform_retry_exhaustion_records_all_attempts(round_env, experiment):
    """Both attempts violate the contract -> rejected, but every attempt is
    recorded as evidence (no silent regeneration)."""
    uploads, _, _, _ = round_env
    rows = ["median_income,housing_age,median_house_value"]
    for i in range(200):
        rows.append(f"{1.0 + (i % 40) * 0.3:.2f},{5 + (i % 30)},{450000 + (i % 50) * 1731.17:.2f}")
    (uploads / "house_cleaned.csv").write_text("\n".join(rows), encoding="utf-8")

    pack = {
        "target": "median_house_value",
        "eda_context": "regression",
        "cleaned_dataset_id": "uploads/house_cleaned.csv",
        "baseline_top_models": [],
    }
    provider = _RecordingProvider(
        [
            json.dumps({"code": _quantizing_transform_code(), "rationale": "bad 1"}),
            json.dumps({"code": _quantizing_transform_code(), "rationale": "bad 2"}),
        ]
    )
    record = _generate_transform(
        provider, pack, {"findings": []}, RoundConfig()
    )
    assert record["status"] == "rejected", record
    assert record["attempt_count"] == 2
    assert [a["status"] for a in record["attempts"]] == ["rejected", "rejected"]
    assert "dtype kind changed" in record["error"] or "cardinality" in record["error"]
    import glob

    assert not glob.glob(str(uploads / "house_cleaned_agentic*.csv"))
    assert "FAILED deterministic validation" in provider.prompts[1]
