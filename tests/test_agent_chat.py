"""Tests for the grounded chat agent (P3.1–P3.3) and sub-agent interpretations (P3.4)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thelab.agents.chat import chat
from thelab.agents.mock import MockProvider
from thelab.context.contracts import IndexedEntry
from thelab.context.repository import ContextRepository
from thelab.contracts import EventType, PrivacyLevel
from thelab.ide.orchestrator import ExperimentOrchestrator

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
def chat_env(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    runs = tmp_path / "runs"
    proposals = tmp_path / "proposals"
    jobs = tmp_path / "jobs"
    for d in (uploads, fixtures, runs, proposals, jobs):
        d.mkdir()
    (fixtures / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("THELAB_RUNS_ROOT", str(runs))
    monkeypatch.setenv("THELAB_PROPOSALS_DIR", str(proposals))
    monkeypatch.setenv("THELAB_JOBS_DIR", str(jobs))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("THELAB_CONTEXT_DB", str(tmp_path / "context" / "context.db"))
    return tmp_path, proposals


def test_chat_plain_answer(chat_env):
    result = _scripted_chat(["Hello from the lab."])
    assert result["status"] == "success"
    assert result["answer"] == "Hello from the lab."
    assert result["tool_calls"] == []


def _scripted_chat(script: list, **kwargs) -> dict:
    """Run chat() with a MockProvider whose script is injected."""

    class ScriptedFactory:
        """Patch create_provider via monkeypatching is cleaner; use direct loop here."""

    # Direct: build the loop by monkeypatching create_provider in chat module.
    from thelab.agents import chat as chat_module

    original = chat_module.create_provider
    chat_module.create_provider = lambda name, model=None: MockProvider(script)  # noqa: ARG005
    try:
        return asyncio.run(chat("question", provider_name="mock", **kwargs))
    finally:
        chat_module.create_provider = original


def test_chat_tool_loop_runs_and_answers(chat_env):
    result = _scripted_chat(
        [
            {"tool_calls": [{"tool": "list_recent_runs", "arguments": {"limit": 3}}]},
            "No runs exist yet in this workspace.",
        ]
    )
    assert result["status"] == "success"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["tool"] == "list_recent_runs"
    assert result["tool_calls"][0]["ok"] is True


def test_chat_run_python_tool(chat_env):
    result = _scripted_chat(
        [
            {
                "tool_calls": [
                    {
                        "tool": "run_python",
                        "arguments": {
                            "code": (
                                "import pandas as pd\n"
                                "df = pd.read_csv('dataset.csv')\n"
                                "print(df.shape)\n"
                                "print(df['species'].nunique())"
                            )
                        },
                    }
                ]
            },
            "The dataset has 15 rows and 3 species.",
        ],
        dataset_id="fixtures/iris.csv",
    )
    assert result["status"] == "success"
    call = result["tool_calls"][0]
    assert call["ok"] is True


def test_chat_run_python_executes_real_code(chat_env):
    """The sandbox actually runs the code: capture output via the tool directly."""
    from thelab.agents.chat import _tool_run_python

    result = asyncio.run(
        _tool_run_python(
            {"code": "import pandas as pd\ndf = pd.read_csv('dataset.csv')\nprint(df.shape)"},
            "fixtures/iris.csv",
        )
    )
    assert result["ok"] is True
    assert "(15, 3)" in result["data"]["stdout"]


def test_chat_propose_experiment_tool(chat_env):
    _, proposals = chat_env
    result = _scripted_chat(
        [
            {
                "tool_calls": [
                    {
                        "tool": "propose_experiment",
                        "arguments": {
                            "goal": "Predict species",
                            "target": "species",
                            "model_grid": ["random_forest"],
                            "seeds": [42],
                        },
                    }
                ]
            },
            "I created a proposal for you to approve.",
        ],
        dataset_id="fixtures/iris.csv",
    )
    assert result["status"] == "success"
    assert result["tool_calls"][0]["ok"] is True
    assert list(proposals.glob("prop-*.json"))


def test_chat_grounding_refuses_unknown_run(chat_env):
    result = _scripted_chat(["Run run-20260829-999999-deadbeef achieved everything."])
    assert result["status"] == "refused"
    assert "run-20260829-999999-deadbeef" in (result["error"] or "")


def test_chat_search_context_tool(chat_env):
    tmp_path, _ = chat_env
    repo = ContextRepository(tmp_path / "context" / "context.db")
    repo.upsert(
        IndexedEntry(
            event_id="evt-chat-1",
            event_type=EventType.agent_session_summary,
            session_id="sess-demo",
            run_id=None,
            tags=["demo"],
            redacted_summary="worker proposed logistic_regression on iris",
            related_artifact_refs=[],
            privacy_level=PrivacyLevel.internal,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
            content_hash="hash-chat-1",
        )
    )
    result = _scripted_chat(
        [
            {"tool_calls": [{"tool": "search_context", "arguments": {"query": "logistic"}}]},
            "A previous session proposed logistic_regression on iris.",
        ]
    )
    assert result["status"] == "success"
    assert result["tool_calls"][0]["ok"] is True


def test_chat_rejects_unknown_provider(chat_env):
    with pytest.raises(ValueError):
        asyncio.run(chat("hi", provider_name="nope"))


# ---------------------------------------------------------------------------
# P3.4 — sub-agent interpretations
# ---------------------------------------------------------------------------

def test_orchestrator_llm_interpretations_with_live_provider(chat_env, monkeypatch):
    tmp_path, _ = chat_env
    (tmp_path / "uploads" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(tmp_path / "uploads"))

    orchestrator = ExperimentOrchestrator(
        runs_root=tmp_path / "runs",
        proposals_dir=tmp_path / "proposals",
    )
    provider = MockProvider(["EDA findings here.", "Cleaning rationale here.", "Model recommendation here."])
    result = asyncio.run(
        orchestrator.orchestrate(
            goal="Predict species",
            dataset_id="uploads/iris.csv",
            target="species",
            provider=provider,
        )
    )
    assert result["eda"]["llm_interpretation"] == "EDA findings here."
    assert result["feature_engineering"]["llm_interpretation"] == "Cleaning rationale here."
    assert result["model_selection"]["llm_interpretation"] == "Model recommendation here."


def test_orchestrator_no_interpretations_without_provider(chat_env):
    tmp_path, _ = chat_env
    (tmp_path / "uploads" / "iris.csv").write_text("\n".join(IRIS_ROWS), encoding="utf-8")

    orchestrator = ExperimentOrchestrator(
        runs_root=tmp_path / "runs",
        proposals_dir=tmp_path / "proposals",
    )
    result = asyncio.run(
        orchestrator.orchestrate(
            goal="Predict species",
            dataset_id="uploads/iris.csv",
            target="species",
        )
    )
    assert result["eda"].get("llm_interpretation") is None
    assert result["feature_engineering"].get("llm_interpretation") is None
    assert result["model_selection"].get("llm_interpretation") is None
