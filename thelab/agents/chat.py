"""Grounded chat agent for The Lab.

A bounded provider tool-loop over plain async tool callables (no MCP
subprocesses): the agent can search the context store, inspect recent runs,
run EDA on the selected dataset, execute pandas code in the restricted
sandbox, and propose experiments. LLMs decide; deterministic code executes.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.agents.harness import _METRIC_KEYS, _METRIC_TOLERANCE, _RUN_ID_RE
from thelab.agents.mock import MockProvider
from thelab.agents.provider import AgentMessage, LLMProvider, ToolSpec
from thelab.context.reader import ContextReader
from thelab.ide.datasets import resolve_dataset_path
from thelab.mcp.common import discover_run_ids, get_runs_root, load_json_artifact

from .providers.ollama import OllamaProvider
from .providers.openai_compat import OpenAICompatProvider
from .providers.openrouter import OpenRouterProvider


def _complete_turn(provider: LLMProvider, messages: list[AgentMessage], tools: list[ToolSpec]) -> Any:
    return provider.complete(messages, tools)


_MAX_STEPS = 12
_MAX_TOOL_RESULT_CHARS = 4000
_MAX_DATASET_BYTES = 128 * 1024 * 1024

ToolCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def create_provider(provider: str, model: str | None = None) -> LLMProvider:
    if provider == "mock":
        return MockProvider([])
    if provider == "ollama":
        return OllamaProvider(model=model)
    if provider == "openrouter":
        return OpenRouterProvider()
    if provider == "openai_compat":
        return OpenAICompatProvider()
    raise ValueError(
        f"unsupported provider: {provider}. Supported: mock, openai_compat, ollama, openrouter"
    )


def ollama_models(base_url: str | None = None) -> dict[str, Any]:
    """Query the local Ollama server for downloaded models. Fail-soft."""
    resolved = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    try:
        import httpx

        response = httpx.get(f"{resolved}/api/tags", timeout=3.0)
        response.raise_for_status()
        payload = response.json()
        models = sorted(
            str(m.get("name"))
            for m in payload.get("models", [])
            if m.get("name")
        )
        return {"reachable": True, "models": models, "base_url": resolved}
    except Exception as exc:  # noqa: BLE001 - probe must never break the UI
        return {"reachable": False, "models": [], "base_url": resolved, "error": str(exc)}


def openrouter_models() -> dict[str, Any]:
    """Fetch OpenRouter's public model catalog (no auth needed). Fail-soft."""
    try:
        import httpx

        response = httpx.get("https://openrouter.ai/api/v1/models", timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        models = [
            {"id": str(m.get("id")), "name": str(m.get("name", ""))}
            for m in payload.get("data", [])
            if m.get("id")
        ]
        models.sort(key=lambda m: m["id"])
        return {"models": models[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"models": [], "error": str(exc)}


def provider_status() -> list[dict[str, Any]]:
    """Report which LLM providers are configured and what env they need."""
    return [
        {"name": "mock", "configured": True, "env": [], "note": "deterministic fallback"},
        {
            "name": "ollama",
            "configured": True,
            "env": ["OLLAMA_BASE_URL (optional)", "OLLAMA_MODEL (optional)"],
            "note": "local server must be running",
        },
        {
            "name": "openai_compat",
            "configured": bool(os.environ.get("THELAB_LLM_BASE_URL"))
            and bool(os.environ.get("THELAB_LLM_API_KEY")),
            "env": ["THELAB_LLM_BASE_URL", "THELAB_LLM_API_KEY", "THELAB_LLM_MODEL (optional)"],
            "note": "any OpenAI-compatible endpoint",
        },
        {
            "name": "openrouter",
            "configured": bool(os.environ.get("THELAB_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")),
            "env": ["THELAB_LLM_API_KEY (or OPENROUTER_API_KEY)", "THELAB_LLM_MODEL (optional)"],
            "note": "openrouter.ai",
        },
    ]


def _truncate(value: Any, limit: int = _MAX_TOOL_RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text)} chars total]"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _context_db_path() -> Path:
    env_path = os.environ.get("THELAB_CONTEXT_DB")
    if env_path:
        return Path(env_path)
    return Path(".thelab") / "context" / "context.db"


async def _tool_search_context(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))[:200]
    limit = min(int(args.get("limit", 5)), 20)
    reader = ContextReader(_context_db_path())
    hits = reader.search(query, limit=limit) if query else []
    return {
        "ok": True,
        "data": [
            {
                "event_id": h.event_id,
                "summary": h.redacted_summary[:400],
                "run_id": h.run_id,
                "tags": h.tags,
                "timestamp": h.timestamp.isoformat(),
            }
            for h in hits
        ],
    }


def _run_brief(run_id: str) -> dict[str, Any] | None:
    manifest = load_json_artifact(Path(get_runs_root()), run_id, "manifest.json")
    if manifest is None:
        return None
    metrics = load_json_artifact(Path(get_runs_root()), run_id, "metrics.json") or {}
    return {
        "run_id": run_id,
        "status": manifest.get("final_status"),
        "validation": manifest.get("validation_status"),
        "model": (manifest.get("config") or {}).get("model"),
        "dataset": (manifest.get("inputs") or {}).get("dataset"),
        "seed": (manifest.get("config") or {}).get("seed"),
        "metrics": {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
    }


async def _tool_list_recent_runs(args: dict[str, Any]) -> dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 30)
    runs = discover_run_ids(Path(get_runs_root()))
    briefs = []
    for run_id in reversed(runs[-limit:]):
        brief = _run_brief(run_id)
        if brief is not None:
            briefs.append(brief)
    return {"ok": True, "data": briefs}


async def _tool_get_run_summary(args: dict[str, Any]) -> dict[str, Any]:
    run_id = str(args.get("run_id", ""))
    brief = _run_brief(run_id)
    if brief is None:
        return {"ok": False, "error": f"run not found: {run_id}"}
    return {"ok": True, "data": brief}


async def _tool_dataset_eda(args: dict[str, Any], dataset_id: str | None) -> dict[str, Any]:
    target_dataset = str(args.get("dataset_id") or dataset_id or "")
    if not target_dataset:
        return {"ok": False, "error": "no dataset selected"}
    from thelab.ide.eda_api import run_eda

    target = args.get("target")
    result = await asyncio.to_thread(run_eda, target_dataset, target)
    return {"ok": True, "data": _truncate(result)}


_MAX_RUN_PYTHON_CHARS = 12000


async def _tool_run_python(args: dict[str, Any], dataset_id: str | None) -> dict[str, Any]:
    """Execute agent-written pandas code in the sandbox against a dataset copy."""
    from thelab.sandbox import run_in_sandbox

    code = str(args.get("code", ""))
    if not code.strip():
        return {"ok": False, "error": "code is empty"}

    target_dataset = str(args.get("dataset_id") or dataset_id or "")
    files: dict[str, str] = {}
    context_note = "No dataset is loaded; only pure-Python computation is available."
    if target_dataset:
        path = resolve_dataset_path(target_dataset)
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content.encode("utf-8")) > _MAX_DATASET_BYTES:
            return {"ok": False, "error": "dataset too large for sandbox analysis"}
        files["dataset.csv"] = content
        context_note = (
            "The selected dataset is available in the sandbox as 'dataset.csv' "
            "(pandas: pd.read_csv('dataset.csv'))."
        )

    result = await asyncio.to_thread(
        run_in_sandbox,
        code,
        30,
        2048,
        64 * 1024,
        files,
    )
    stdout_text = _truncate(result.stdout)
    payload: dict[str, Any] = {
        "status": result.status,
        "stdout": stdout_text,
        "return_value": _truncate(result.return_value) if result.return_value is not None else None,
        "error": result.error,
    }
    if len(json.dumps(payload)) > _MAX_RUN_PYTHON_CHARS:
        payload["stdout"] = stdout_text[:_MAX_RUN_PYTHON_CHARS] + "...[truncated]"
    return {"ok": result.status == "completed", "data": payload, "context_note": context_note}


async def _tool_clean_dataset(args: dict[str, Any], dataset_id: str | None) -> dict[str, Any]:
    """Clean the selected dataset deterministically; result lands in uploads."""
    from thelab.ide.cleaning import clean_dataset

    target_dataset = str(args.get("dataset_id") or dataset_id or "")
    target = str(args.get("target", ""))
    if not target_dataset or not target:
        return {"ok": False, "error": "dataset_id and target are required"}
    try:
        metadata = await asyncio.to_thread(clean_dataset, target_dataset, target)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "data": {
            "dataset_id": metadata["dataset_id"],
            "rows": metadata["rows"],
            "columns": metadata["columns"],
            "actions": metadata["cleaning_report"]["actions"],
        },
    }


async def _tool_start_experiment(args: dict[str, Any], dataset_id: str | None) -> dict[str, Any]:
    """Launch the FULL multi-agent pipeline (EDA -> clean -> select -> train)."""
    from thelab.ide.experiment_api import start_experiment

    target_dataset = str(args.get("dataset_id") or dataset_id or "")
    goal = str(args.get("goal", ""))
    target = str(args.get("target", ""))
    if not target_dataset or not goal or not target:
        return {"ok": False, "error": "dataset_id, goal, and target are required"}
    result = await start_experiment(
        goal=goal,
        dataset_id=target_dataset,
        target=target,
        provider_name=str(args.get("provider") or "mock"),
        model=args.get("model"),
    )
    return {
        "ok": True,
        "data": {
            "experiment_id": result["experiment_id"],
            "job_id": result["job_id"],
            "state": result["state"],
            "note": "Full pipeline started: EDAAnalyst -> FeatureEngineer -> "
            "ModelSelector -> training. Track it in Experiments -> Run.",
        },
    }


async def _tool_propose_experiment(args: dict[str, Any], dataset_id: str | None) -> dict[str, Any]:
    from thelab.ide.worker_api import generate_proposal

    target_dataset = str(args.get("dataset_id") or dataset_id or "")
    if not target_dataset:
        return {"ok": False, "error": "no dataset selected"}
    proposal = await generate_proposal(
        dataset_id=target_dataset,
        target=str(args.get("target", "")),
        goal=str(args.get("goal", "")),
        model_grid=args.get("model_grid"),
        seeds=args.get("seeds"),
    )
    return {"ok": True, "data": {"proposal_id": proposal["proposal_id"], "proposal": proposal}}


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def _build_tools(dataset_id: str | None) -> tuple[list[ToolSpec], dict[str, ToolCallable]]:
    """Return the tool specs and executor map, bound to the dataset context."""

    async def run_python(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_run_python(args, dataset_id)

    async def propose(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_propose_experiment(args, dataset_id)

    async def start_exp(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_start_experiment(args, dataset_id)

    async def clean(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_clean_dataset(args, dataset_id)

    async def eda(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_dataset_eda(args, dataset_id)

    async def dataset_context(args: dict[str, Any]) -> dict[str, Any]:
        target_dataset = str(args.get("dataset_id") or dataset_id or "")
        if not target_dataset:
            return {"ok": False, "error": "no dataset selected"}
        from thelab.ide.kaggle_api import get_dataset_context

        pack = await asyncio.to_thread(get_dataset_context, target_dataset)
        if pack is None:
            return {
                "ok": True,
                "data": "No external context pack stored for this dataset (local dataset).",
            }
        return {"ok": True, "data": _truncate(pack)}

    specs = [
        ToolSpec(
            name="search_context",
            description="Search the local context store for past runs, decisions, and errors.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        ),
        ToolSpec(
            name="list_recent_runs",
            description="List recent training runs with status and metrics.",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 30}},
            },
        ),
        ToolSpec(
            name="get_run_summary",
            description="Get manifest, config, and metrics for one run id.",
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        ),
        ToolSpec(
            name="dataset_eda",
            description=(
                "Run deterministic EDA on the selected dataset: missing values, "
                "feature types, class balance, correlations, outliers, leakage suspects."
            ),
            input_schema={
                "type": "object",
                "properties": {"target": {"type": "string"}},
            },
        ),
        ToolSpec(
            name="run_python",
            description=(
                "Execute pandas/Python code in a restricted sandbox against the "
                "selected dataset (available as 'dataset.csv'). Use for concrete "
                "data questions (NaN counts, groupbys, distributions). No network, "
                "no file writes outside the sandbox."
            ),
            input_schema={
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        ),
        ToolSpec(
            name="get_dataset_context",
            description=(
                "Read the stored context pack for the selected dataset: source "
                "documentation (e.g. Kaggle description, keywords), profile, and "
                "provenance. Use it to understand what the dataset is about."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        ToolSpec(
            name="clean_dataset",
            description=(
                "Deterministically clean the selected dataset for a target (missing "
                "values, datetime parsing, encoding). The cleaned copy is stored in "
                "uploads and visible in the Data view. Skips if already cleaned."
            ),
            input_schema={
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
        ),
        ToolSpec(
            name="start_experiment",
            description=(
                "Launch the FULL multi-agent experiment pipeline on the selected "
                "dataset: EDA analysis, cleaning, model selection, and batch "
                "training. Use when the user asks to run/execute an experiment. "
                "For a lightweight proposal they can review first, use "
                "propose_experiment instead."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "target": {"type": "string"},
                    "model_grid": {"type": "array", "items": {"type": "string"}},
                    "seeds": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["goal", "target"],
            },
        ),
        ToolSpec(
            name="propose_experiment",
            description=(
                "Create an experiment proposal (models, seeds, rationale) for the "
                "selected dataset and target. The user must approve it before it runs."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "target": {"type": "string"},
                    "model_grid": {"type": "array", "items": {"type": "string"}},
                    "seeds": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["goal", "target"],
            },
        ),
    ]
    registry: dict[str, ToolCallable] = {
        "search_context": _tool_search_context,
        "list_recent_runs": _tool_list_recent_runs,
        "get_run_summary": _tool_get_run_summary,
        "dataset_eda": eda,
        "get_dataset_context": dataset_context,
        "clean_dataset": clean,
        "run_python": run_python,
        "propose_experiment": propose,
        "start_experiment": start_exp,
    }
    return specs, registry


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

def _check_grounding(answer: str) -> str | None:
    """Return an error message if cited run ids or metric claims are unsupported."""
    import re

    run_ids = _RUN_ID_RE.findall(answer)
    for run_id in run_ids:
        brief = _run_brief(run_id)
        if brief is None:
            return f"cited run_id '{run_id}' does not exist in the workspace"
    claims: dict[str, float] = {}
    for key in _METRIC_KEYS:
        match = re.search(rf"{key}[^0-9\n]{{0,30}}(-?\d+(?:\.\d+)?)", answer)
        if match:
            try:
                claims[key] = float(match.group(1))
            except ValueError:
                continue
    for run_id in run_ids:
        brief = _run_brief(run_id)
        metrics = (brief or {}).get("metrics") or {}
        for key, claimed in claims.items():
            actual = metrics.get(key)
            if isinstance(actual, (int, float)) and abs(claimed - float(actual)) > _METRIC_TOLERANCE:
                return (
                    f"metric claim {key}={claimed} for run {run_id} does not "
                    f"match evidence ({actual})"
                )
    return None


# ---------------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------------

def _persist_chat_event(
    session: str,
    provider_name: str,
    message: str,
    answer: str | None,
    tool_trace: list[dict[str, Any]],
) -> None:
    """Index the chat exchange into the context store (best-effort)."""
    try:
        from thelab.context.contracts import IndexedEntry
        from thelab.context.redaction import redact
        from thelab.context.repository import ContextRepository
        from thelab.contracts import EventType, PrivacyLevel

        now = datetime.now(UTC)
        tools_used = ", ".join(t["tool"] for t in tool_trace) or "none"
        summary = (
            f"chat[{provider_name}] Q: {message[:300]} | "
            f"A: {(answer or '(refused/failed)')[:300]} | tools: {tools_used}"
        )
        db_path = Path(os.environ.get("THELAB_CONTEXT_DB", ".thelab/context/context.db"))
        repo = ContextRepository(db_path)
        repo.upsert(
            IndexedEntry(
                event_id=f"evt-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
                event_type=EventType.agent_session_summary,
                session_id=session,
                run_id=None,
                tags=["chat", f"provider:{provider_name}"],
                redacted_summary=redact(summary),
                related_artifact_refs=[],
                privacy_level=PrivacyLevel.internal,
                timestamp=now,
                content_hash=uuid.uuid4().hex,
            )
        )
    except Exception:  # noqa: BLE001 - persistence is best-effort
        pass


def _system_prompt(dataset_id: str | None, style: str | None = None, role_hint: str | None = None) -> str:
    dataset_line = (
        f"The user has selected dataset '{dataset_id}'."
        if dataset_id
        else "No dataset is selected yet; ask for one when relevant."
    )
    style_line = f" Response style: {style}." if style and style.strip() else ""
    role_line = f" You are acting as: {role_hint}." if role_hint and role_hint.strip() else ""
    return (
        "You are The Lab's assistant: a grounded agent for a local ML factory. "
        "You can search the local context, inspect training runs, run EDA, "
        "execute pandas code in a restricted sandbox, clean datasets, and propose experiments. "
        f"{dataset_line} "
        "Use tools to ground every factual claim about data or runs; cite run_ids "
        "only when a tool returned them. Never claim to train models — you propose; "
        "the user approves; the deterministic pipeline executes. "
        "Reuse earlier tool results instead of repeating identical calls; the sandbox "
        "has no network access, so never suggest downloading data there."
        + style_line + role_line
    )


async def chat(
    message: str,
    history: list[dict[str, str]] | None = None,
    provider_name: str = "mock",
    model: str | None = None,
    dataset_id: str | None = None,
    session_id: str | None = None,
    max_steps: int = _MAX_STEPS,
    style: str | None = None,
    role_hint: str | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Run one bounded chat turn and return the outcome."""
    if not message or not message.strip():
        raise ValueError("message must be a non-empty string")
    if dataset_id is not None:
        resolve_dataset_path(dataset_id)  # validate early

    provider = create_provider(provider_name, model)
    specs, registry = _build_tools(dataset_id)

    messages: list[AgentMessage] = [
        AgentMessage(role="system", content=_system_prompt(dataset_id, style, role_hint))
    ]
    for past in history or []:
        role = past.get("role")
        content = past.get("content", "")
        if role == "user" and content:
            messages.append(AgentMessage(role="user", content=content))
        elif role == "assistant" and content:
            messages.append(AgentMessage(role="assistant", content=content))
    messages.append(AgentMessage(role="user", content=message))

    session = session_id or f"chat-{uuid.uuid4().hex[:8]}"
    tool_trace: list[dict[str, Any]] = []
    tool_cache: dict[str, dict[str, Any]] = {}
    started = time.time()
    usage_total: dict[str, Any] = {"models": [], "prompt_tokens": 0, "completion_tokens": 0}

    for _step in range(max_steps):
        turn = await asyncio.to_thread(_complete_turn, provider, messages, specs)

        if turn.usage:
            model_name = turn.usage.get("model")
            if model_name and model_name not in usage_total["models"]:
                usage_total["models"].append(model_name)
            usage_total["prompt_tokens"] += int(turn.usage.get("prompt_tokens") or 0)
            usage_total["completion_tokens"] += int(turn.usage.get("completion_tokens") or 0)

        if turn.text is not None:
            grounding_error = _check_grounding(turn.text)
            if grounding_error:
                return {
                    "status": "refused",
                    "answer": None,
                    "error": grounding_error,
                    "session_id": session,
                    "tool_calls": tool_trace,
                }
            result = {
                "status": "success",
                "answer": turn.text,
                "session_id": session,
                "tool_calls": tool_trace,
                "usage": {
                    **usage_total,
                    "elapsed_seconds": round(time.time() - started, 1),
                },
            }
            if persist:
                _persist_chat_event(session, provider_name, message, str(turn.text or ""), tool_trace)
            return result

        if not turn.tool_calls:
            return {
                "status": "refused",
                "answer": None,
                "error": "provider returned an empty turn",
                "session_id": session,
                "tool_calls": tool_trace,
            }

        for call in turn.tool_calls:
            if on_event is not None:
                on_event({"type": "tool_started", "tool": call.tool})
            executor = registry.get(call.tool)
            if executor is None:
                result = {"ok": False, "error": f"unknown tool: {call.tool}"}
            else:
                cache_key = json.dumps(
                    {"tool": call.tool, "args": call.arguments, "dataset": dataset_id},
                    sort_keys=True,
                    default=str,
                )
                if call.tool in {"dataset_eda", "get_dataset_context"} and cache_key in tool_cache:
                    result = dict(tool_cache[cache_key])
                    result["cached"] = True
                else:
                    try:
                        result = await executor(call.arguments)
                    except Exception as exc:  # noqa: BLE001
                        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                    if call.tool in {"dataset_eda", "get_dataset_context"} and result.get("ok"):
                        tool_cache[cache_key] = result
            proposal_id = None
            if call.tool == "propose_experiment" and result.get("ok"):
                data = result.get("data") or {}
                proposal_id = (data or {}).get("proposal_id")
            if on_event is not None:
                on_event(
                    {
                        "type": "tool_result",
                        "tool": call.tool,
                        "ok": result.get("ok", False),
                        "error": result.get("error"),
                        "proposal_id": proposal_id,
                    }
                )
            tool_trace.append(
                {
                    "tool": call.tool,
                    "arguments": call.arguments,
                    "ok": result.get("ok", False),
                    "error": result.get("error"),
                    "proposal_id": proposal_id,
                }
            )
            messages.append(
                AgentMessage(
                    role="tool",
                    content=_truncate(result),
                    tool_call_id=call.id or f"{call.tool}-{uuid.uuid4().hex[:4]}",
                )
            )

    result = {
        "status": "refused",
        "answer": None,
        "error": f"agent loop exceeded max_steps ({max_steps})",
        "session_id": session,
        "tool_calls": tool_trace,
        "usage": {**usage_total, "elapsed_seconds": round(time.time() - started, 1)},
    }
    if persist:
        _persist_chat_event(session, provider_name, message, None, tool_trace)
    return result
