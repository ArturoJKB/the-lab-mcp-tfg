"""Agentic round: bounded, role-specialized agent exploration.

Runs after the deterministic baseline batch and is grounded in its artifacts.
Three role-specialized stages, each with a distinct system prompt and bound:

1. **Analyst** builds a findings brief via the read-only MCP servers
   (context + EDA) with a deterministic fallback when no LLM is available.
2. **FeatureEngineer** generates pandas transform code that executes only
   inside :mod:`thelab.sandbox`; a deterministic post-validator checks the
   artifact before it can be used for training. Metrics are always recomputed
   by the deterministic factory — sandbox output is never trusted.
3. **ModelSelector** proposes configs beyond the fixed grid (validated against
   the model registry) and saved through :class:`ProposalStore`.

Autonomy policy (see ``docs/P5_PLAN.md``): the round defaults to
**human-required approval**. ``require_approval`` is an explicit parameter and
must not inherit auto-approval from any caller. Agent-generated code executes
only inside the sandbox.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thelab.agents.approval import ensure_executable
from thelab.agents.json_repair import safe_json_loads
from thelab.agents.provider import AgentMessage, LLMProvider
from thelab.agents.worker import ExperimentProposal, ProposalStore
from thelab.ide.datasets import dataset_id_to_relative_path, get_uploads_root, resolve_dataset_path
from thelab.run.model_registry import MODEL_REGISTRY

RoundEvent = Any  # Callable[[str, str], None] | None
ShouldContinue = Any  # Callable[[], bool] | None

ROUND_TIMEOUT_S = 60
# Aligned with the upload cap (datasets.py): inputs reach the sandbox through
# the trusted input_dir channel, so large datasets no longer inline in JSON.
MAX_TRANSFORM_SOURCE_BYTES = 100 * 1024 * 1024

# ---------------------------------------------------------------------------
# Role prompt contracts (per-role identity, scope, output format)
# ---------------------------------------------------------------------------

ANALYST_SYSTEM_PROMPT = (
    "You are the Analyst agent of The Lab's agentic round. You search the local "
    "context store and EDA evidence through read-only MCP tools to explain WHY the "
    "deterministic baseline performs as it does and what to try next. Ground every "
    "statement in tool output or the provided data; cite run_ids only when a tool "
    "returned them. Your final answer must be a single JSON object with keys "
    "'findings' (list of strings), 'opportunities' (list of strings), 'risks' "
    "(list of strings), and no other text."
)

FEATURE_ENGINEER_SYSTEM_PROMPT = (
    "You are the FeatureEngineer agent of The Lab's agentic round. You write one "
    "pandas transform that improves on the deterministic cleaning without leaking "
    "the target. The dataset is available as 'dataset.csv'; write the result to "
    "'transformed.csv' (same target column, no target mutation, no row explosion). "
    "Do not import anything outside numpy/pandas/sklearn. Your final answer must "
    "be a single JSON object with keys 'code' (string, Python source) and "
    "'rationale' (string), and no other text."
)

MODEL_SELECTOR_SYSTEM_PROMPT = (
    "You are the ModelSelector agent of The Lab's agentic round. You propose a "
    "training configuration that goes beyond the deterministic baseline grid, "
    "using only models from the provided registry list. Your final answer must be "
    "a single JSON object with keys 'model_grid' (list of model names from the "
    "registry), 'seeds' (list of integers), 'hyperparameter_grid' (object mapping "
    "parameter names to lists), and 'rationale' (string), and no other text."
)


@dataclass(frozen=True)
class RoundConfig:
    """Bounds and policy for one agentic round."""

    require_approval: bool = True  # binding: never inherit auto-approval
    transform_timeout_s: int = ROUND_TIMEOUT_S
    analyst_max_steps: int = 6
    # "multi": each stage uses its role-specific prompt contract (the thesis
    # claim). "single": all stages share one generic analyst prompt — the
    # pre-P5.A behavior, used as the RQ6 ablation control arm.
    role_mode: str = "multi"

    def __post_init__(self) -> None:
        if self.role_mode not in {"multi", "single"}:
            raise ValueError(f"unknown role_mode: {self.role_mode}")

    def prompt_for(self, role_prompt: str) -> str:
        """Return the system prompt for a stage under the current role mode."""
        if self.role_mode == "single":
            return _GENERIC_ANALYST_PROMPT
        return role_prompt


_GENERIC_ANALYST_PROMPT = (
    "You are a concise ML analyst sub-agent for The Lab. "
    "Ground every statement in the provided data; no speculation."
)


# ---------------------------------------------------------------------------
# Context pack (deterministic grounding — no LLM)
# ---------------------------------------------------------------------------

def build_context_pack(experiment: Any, deterministic_result: dict[str, Any]) -> dict[str, Any]:
    """Assemble the grounding pack from the deterministic batch artifacts."""
    training_results = deterministic_result.get("training_results", [])
    completed = [r for r in training_results if r.get("status") == "completed"]
    best_det = None
    if completed:
        best_det = max(
            completed,
            key=lambda r: (r.get("metrics") or {}).get("test_accuracy", -1.0),
        )
    fe = deterministic_result.get("feature_engineering", {})
    ms = deterministic_result.get("model_selection", {})
    return {
        "experiment_id": experiment.experiment_id,
        "goal": experiment.goal,
        "dataset_id": experiment.dataset_id,
        "target": experiment.target,
        "feedback": experiment.feedback,
        "cleaned_dataset_id": fe.get("cleaned_dataset_id"),
        "clean_metadata": fe.get("clean_metadata", {}),
        "baseline_top_models": fe.get("top_models", []),
        "recommendation": ms.get("recommendation", {}),
        "best_deterministic": best_det,
        "eda_context": deterministic_result.get("eda", {}).get("eda_context", ""),
    }


def _deterministic_brief(pack: dict[str, Any]) -> dict[str, Any]:
    """Fallback brief built deterministically from the EDA context."""
    findings: list[str] = []
    opportunities: list[str] = []
    if pack.get("eda_context"):
        findings.append(f"EDA: {pack['eda_context']}")
    baseline = pack.get("baseline_top_models") or []
    if baseline:
        top = baseline[0]
        metrics = top.get("metrics") or {}
        key = next((k for k in ("test_accuracy", "test_rmse") if k in metrics), None)
        if key:
            findings.append(f"Best dry-run baseline: {top.get('model')} ({key}={metrics[key]})")
        opportunities.append(
            "Evaluate whether feature transformations improve on the best dry-run baseline."
        )
    if pack.get("clean_metadata", {}).get("skipped"):
        opportunities.append("Dataset was already cleaned; targeted transforms may still help.")
    if not findings:
        findings.append("No EDA context available; baseline evidence missing.")
    risks = ["Agent-proposed transforms must be validated for target leakage."]
    return {"findings": findings, "opportunities": opportunities, "risks": risks}


# ---------------------------------------------------------------------------
# LLM helpers (bounded, JSON-repaired, degrade-to-None)
# ---------------------------------------------------------------------------

def _parse_json_answer(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    candidate = text[start : end + 1] if 0 <= start < end else text
    parsed = safe_json_loads(candidate)
    return parsed if isinstance(parsed, dict) else None


async def _analyst_via_mcp(
    provider: LLMProvider,
    server_names: list[str],
    instruction: str,
    config: RoundConfig,
) -> dict[str, Any] | None:
    """Run the analyst through real stdio MCP servers; return parsed JSON or None."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from thelab.agents.harness import AgentHarness, ServerConnection

    server_modules = {
        "context": "thelab.mcp.context_mcp",
        "eda": "thelab.mcp.eda_mcp",
        "model_registry": "thelab.mcp.model_registry_mcp",
    }

    connections = []
    async with contextlib.AsyncExitStack() as stack:
        for name in server_names:
            module = server_modules.get(name)
            if module is None:
                raise ValueError(f"unknown MCP server: {name}")
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", module],
                env=dict(os.environ),
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            connections.append(ServerConnection(name=name, session=session))

        harness = AgentHarness(
            provider=provider,
            servers=connections,
            max_steps=config.analyst_max_steps,
            system_prompt=config.prompt_for(ANALYST_SYSTEM_PROMPT),
        )
        outcome = await harness.run(instruction)

    if outcome.get("status") != "success":
        return None
    return _parse_json_answer(outcome.get("answer"))


def _single_turn_json(
    provider: LLMProvider,
    system_prompt: str,
    instruction: str,
) -> dict[str, Any] | None:
    """One provider turn with a role prompt; returns parsed JSON or None.

    Runs synchronously — callers invoke it from a worker thread.
    """
    try:
        turn = provider.complete(
            [
                AgentMessage(role="system", content=system_prompt),
                AgentMessage(role="user", content=instruction),
            ],
            [],
        )
    except Exception:  # noqa: BLE001 - degrade to deterministic, never block
        return None
    return _parse_json_answer(turn.text)


# ---------------------------------------------------------------------------
# Feature-engineering transform: sandbox execution + deterministic validation
# ---------------------------------------------------------------------------

def _validate_transform(artifact: Path, source: Path, target: str) -> list[str]:
    """Deterministic post-checks on a sandbox-produced transform. Never raises."""
    import pandas as pd

    errors: list[str] = []
    try:
        src = pd.read_csv(source)
    except Exception as exc:  # noqa: BLE001
        return [f"source dataset unreadable: {exc}"]
    try:
        out = pd.read_csv(artifact)
    except Exception as exc:  # noqa: BLE001
        return [f"transformed artifact unreadable: {exc}"]

    if len(out) == 0:
        errors.append("transformed dataset is empty")
    if len(out) > len(src):
        errors.append(f"row explosion: {len(src)} -> {len(out)} rows")
    if target not in out.columns:
        errors.append(f"target column '{target}' missing from transformed dataset")
    else:
        target_series = out[target]
        if target_series.isna().any() and not src[target].isna().any():
            errors.append("transform introduced NaN values in the target column")
        if src[target].nunique(dropna=True) >= 2 and target_series.nunique(dropna=True) < 2:
            errors.append("target collapsed to a single value (degenerate target)")
    for column in ("target", "label", "y"):
        if column != target and column in out.columns and out[column].equals(out[target]):
            errors.append(f"column '{column}' duplicates the target column")
    return errors


def _generate_transform(
    provider: LLMProvider | None,
    pack: dict[str, Any],
    brief: dict[str, Any],
    config: RoundConfig,
) -> dict[str, Any]:
    """FE stage: LLM code -> sandbox -> validation -> optional dataset artifact.

    Large inputs/outputs bypass the inline JSON round-trip via the trusted
    ``input_dir``/``artifact_dir`` channels (P5.B7); validation always reads
    from disk in the parent, never trusting sandbox output.
    """
    record: dict[str, Any] = {
        "stage": "feature_engineering",
        "status": "skipped",
        "llm_used": provider is not None,
        "source": "llm" if provider is not None else "deterministic_fallback",
    }
    if provider is None:
        record["reason"] = "no LLM provider configured; deterministic baseline stands"
        return record

    cleaned_dataset_id = pack.get("cleaned_dataset_id")
    if not cleaned_dataset_id:
        record["status"] = "rejected"
        record["error"] = "no cleaned dataset available from the deterministic stage"
        return record

    try:
        source_path = resolve_dataset_path(cleaned_dataset_id)
    except Exception as exc:  # noqa: BLE001
        record["status"] = "rejected"
        record["error"] = f"cannot resolve cleaned dataset: {exc}"
        return record
    if source_path.stat().st_size > MAX_TRANSFORM_SOURCE_BYTES:
        record["status"] = "skipped"
        record["reason"] = "dataset exceeds the transform input cap"
        return record

    instruction = (
        f"Dataset context: {pack.get('eda_context', '')}\n"
        f"Target column: {pack.get('target')}\n"
        f"Analyst brief: {json.dumps(brief, default=str)[:2500]}\n"
        "Write one pandas transform improving on the deterministic cleaning and "
        "save it to 'transformed.csv'."
    )
    parsed = _single_turn_json(provider, config.prompt_for(FEATURE_ENGINEER_SYSTEM_PROMPT), instruction)
    code = (parsed or {}).get("code")
    record["rationale"] = (parsed or {}).get("rationale", "")
    if not isinstance(code, str) or not code.strip():
        record["status"] = "skipped"
        record["reason"] = "feature engineer produced no usable code"
        return record
    record["code"] = code

    import shutil
    import tempfile

    from thelab.sandbox import run_in_sandbox

    with tempfile.TemporaryDirectory(prefix="thelab-round-") as tmp:
        input_dir = Path(tmp) / "in"
        artifact_dir = Path(tmp) / "out"
        input_dir.mkdir()
        artifact_dir.mkdir()
        shutil.copyfile(source_path, input_dir / "dataset.csv")

        result = run_in_sandbox(
            code,
            timeout=config.transform_timeout_s,
            artifact_dir=artifact_dir,
            input_dir=input_dir,
        )
        record["sandbox"] = {"status": result.status, "error": result.error}
        if result.status != "completed":
            record["status"] = "rejected"
            record["error"] = result.error or f"sandbox status: {result.status}"
            return record

        spilled = next(
            (s for s in (result.spilled or []) if s.get("name") == "transformed.csv"),
            None,
        )
        if spilled is None or not Path(str(spilled.get("path"))).is_file():
            record["status"] = "rejected"
            record["error"] = "transform did not produce transformed.csv"
            return record
        spilled_path = Path(str(spilled["path"]))

        # Persist, then validate from disk (pandas in the parent, never the sandbox).
        dest_dir = get_uploads_root()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{Path(str(cleaned_dataset_id)).stem}_agentic.csv"
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{Path(str(cleaned_dataset_id)).stem}_agentic_{counter}.csv"
            counter += 1
        shutil.copyfile(spilled_path, dest)

        errors = _validate_transform(dest, source_path, str(pack.get("target")))
        record["validation"] = {"ok": not errors, "errors": errors}
        if errors:
            record["status"] = "rejected"
            record["error"] = "; ".join(errors)
            dest.unlink(missing_ok=True)
            return record

    record["status"] = "completed"
    record["dataset_id"] = f"uploads/{dest.name}"
    record["source_dataset_id"] = cleaned_dataset_id
    return record


# ---------------------------------------------------------------------------
# Model selection: proposal beyond the grid, gated by the approval chokepoint
# ---------------------------------------------------------------------------

def _selection_fallback(pack: dict[str, Any]) -> dict[str, Any]:
    recommendation = pack.get("recommendation", {})
    grid = [m for m in recommendation.get("model_grid", []) if m] or ["logistic_regression"]
    seeds = recommendation.get("seeds") or [42]
    return {
        "model_grid": grid,
        "seeds": seeds,
        "hyperparameter_grid": {},
        "rationale": "deterministic baseline recommendation (no LLM selection available)",
    }


def _generate_selection(
    provider: LLMProvider | None,
    pack: dict[str, Any],
    brief: dict[str, Any],
    transform_record: dict[str, Any],
    config: RoundConfig,
) -> tuple[dict[str, Any], bool]:
    """Selector stage: returns (selection_dict, llm_used)."""
    registry_models = sorted(MODEL_REGISTRY.list_models())
    if provider is not None:
        instruction = (
            f"Registry models: {registry_models}\n"
            f"Task target: {pack.get('target')}\n"
            f"Baseline top models: {json.dumps(pack.get('baseline_top_models', []), default=str)[:1500]}\n"
            f"Analyst brief: {json.dumps(brief, default=str)[:1500]}\n"
            f"Transform outcome: {json.dumps({k: transform_record.get(k) for k in ('status', 'rationale', 'validation')}, default=str)}\n"
            "Propose a small training grid (1-3 models, 1-3 seeds)."
        )
        parsed = _single_turn_json(provider, config.prompt_for(MODEL_SELECTOR_SYSTEM_PROMPT), instruction)
        if parsed and isinstance(parsed.get("model_grid"), list) and parsed["model_grid"]:
            return parsed, True
    return _selection_fallback(pack), False


# ---------------------------------------------------------------------------
# Round orchestration
# ---------------------------------------------------------------------------

def _round_record_path(experiments_dir: Path, experiment_id: str) -> Path:
    return experiments_dir / f"{experiment_id}.agentic_round.json"


def _index_round_event(summary: str, tags: list[str], run_id: str | None) -> None:
    """Best-effort: append a validated, redacted event to the context JSONL."""
    try:
        from thelab.mcp.context_write_mcp import append_event, validate_event

        now = datetime.now(UTC)
        event = {
            "event_id": f"evt-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
            "timestamp": now.isoformat(),
            "event_type": "agent_session_summary",
            "session_id": f"agentic_round_{now.strftime('%Y%m%d-%H%M%S')}",
            "run_id": run_id or "none",
            "tags": ["agentic_round", *tags],
            "outcome": {"status": "completed", "summary": summary[:2000]},
            "privacy": {"level": "internal"},
        }
        normalized, error = validate_event(event)
        if not error and normalized is not None:
            append_event(normalized)
    except Exception:  # noqa: BLE001 - indexing is best-effort, never blocks
        pass


async def run_agentic_round(
    experiment: Any,
    deterministic_result: dict[str, Any],
    *,
    provider: LLMProvider | None,
    require_approval: bool = True,
    config: RoundConfig | None = None,
    on_event: RoundEvent = None,
    should_continue: ShouldContinue = None,
    runs_root: Path | str | None = None,
    proposals_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run the three-stage agentic round; returns the round record.

    Approval policy: ``require_approval=True`` (the default and the value the
    experiment job always passes) forces the human gate. ``require_approval``
    must never be derived from caller context.
    """
    config = config or RoundConfig()
    config = RoundConfig(
        require_approval=require_approval,
        transform_timeout_s=config.transform_timeout_s,
        analyst_max_steps=config.analyst_max_steps,
        role_mode=config.role_mode,
    )

    def emit(message: str) -> None:
        if on_event is not None:
            on_event("agentic_round", message)

    def cancelled() -> bool:
        return should_continue is not None and not should_continue()

    experiment_id = experiment.experiment_id
    pack = build_context_pack(experiment, deterministic_result)
    record: dict[str, Any] = {
        "round_id": f"round-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "experiment_id": experiment_id,
        "require_approval": require_approval,
        "created_at": datetime.now(UTC).isoformat(),
        "policy": "human_required" if require_approval else "auto_approved_by_operator",
        "role_mode": config.role_mode,
    }

    # Stage 1: Analyst
    if cancelled():
        record["status"] = "cancelled"
        return record
    emit("Analyst building findings brief from EDA and context evidence")
    brief: dict[str, Any]
    if provider is not None:
        instruction = (
            f"Goal: {pack['goal']}\nTarget: {pack['target']}\n"
            f"EDA context: {pack.get('eda_context', '')}\n"
            f"Baseline top models: {json.dumps(pack.get('baseline_top_models', []), default=str)[:1500]}\n"
            "Search the context and EDA tools if useful, then produce the brief JSON."
        )
        try:
            parsed = await _analyst_via_mcp(
                provider, ["context", "eda"], instruction, config
            )
        except Exception:  # noqa: BLE001 - MCP/server failures degrade to fallback
            parsed = None
        brief_from_llm = parsed is not None and "findings" in parsed
        if brief_from_llm and parsed is not None:
            brief = parsed
        else:
            brief = _deterministic_brief(pack)
        brief["source"] = "llm" if brief_from_llm else "deterministic_fallback"
        record["analyst_llm_used"] = brief_from_llm
    else:
        brief = _deterministic_brief(pack)
        brief["source"] = "deterministic_fallback"
        record["analyst_llm_used"] = False
    record["brief"] = brief

    # Stage 2: FeatureEngineer (sandbox). Blocking in the coroutine — the
    # sandbox subprocess is synchronous and the job loop tolerates it (same
    # pattern as BatchRunner in the deterministic stage).
    if cancelled():
        record["status"] = "cancelled"
        return record
    emit("FeatureEngineer proposing sandboxed transform")
    transform_record = _generate_transform(provider, pack, brief, config)
    record["transform"] = transform_record

    # Stage 3: ModelSelector -> proposal -> approval gate
    if cancelled():
        record["status"] = "cancelled"
        return record
    emit("ModelSelector proposing training configuration beyond the baseline grid")
    selection, selector_llm_used = _generate_selection(provider, pack, brief, transform_record, config)
    selection["source"] = "llm" if selector_llm_used else "deterministic_fallback"
    record["selector_llm_used"] = selector_llm_used

    # Provenance mode (P5.B8): a round in which no stage produced LLM content
    # is recorded as degraded_deterministic — it never presents itself as
    # agentic. RQ5/RQ6 counting only includes mode == "agentic" rounds.
    llm_contributed = bool(
        record.get("analyst_llm_used")
        or selector_llm_used
        or (
            transform_record.get("llm_used")
            and transform_record.get("status") == "completed"
        )
    )
    record["mode"] = "agentic" if llm_contributed else "degraded_deterministic"

    dataset_id = transform_record.get("dataset_id") or pack.get("cleaned_dataset_id")
    if not dataset_id:
        record["status"] = "failed"
        record["error"] = "no dataset available for the agentic proposal"
        return record

    store = ProposalStore(
        proposals_dir if proposals_dir else os.environ.get("THELAB_PROPOSALS_DIR", "proposals")
    )
    proposal_id = f"prop-round-{uuid.uuid4().hex[:12]}"
    proposal = ExperimentProposal(
        proposal_id=proposal_id,
        goal=f"Agentic round for experiment {experiment_id}: {pack['goal']}",
        dataset=dataset_id_to_relative_path(dataset_id),
        target=str(pack["target"]),
        model_grid=[str(m) for m in selection.get("model_grid", [])],
        seeds=[int(s) for s in selection.get("seeds", [42])],
        hyperparameter_grid={
            str(k): list(v) for k, v in (selection.get("hyperparameter_grid") or {}).items()
        },
        task_type="auto",
        rationale=str(selection.get("rationale", "")),
    )
    store.save(proposal)
    record["proposal_id"] = proposal_id
    record["proposal"] = proposal.safe_dict()
    record["selection"] = selection

    try:
        approval_path = ensure_executable(
            store,
            proposal_id,
            principal=f"agentic_round:{experiment_id}",
            allow_auto=not require_approval,
        )
        record["status"] = "approved_for_execution"
        record["approval_path"] = str(approval_path)
    except Exception as exc:  # ApprovalDenied / HumanApprovalRequired
        record["status"] = "awaiting_approval" if "not approved" in str(exc) else "rejected"
        record["approval_error"] = str(exc)

    experiments_dir = Path(
        os.environ.get("THELAB_EXPERIMENTS_DIR", Path(".thelab") / "experiments")
    )
    experiments_dir.mkdir(parents=True, exist_ok=True)
    _round_record_path(experiments_dir, experiment_id).write_text(
        json.dumps(record, indent=2, default=str), encoding="utf-8"
    )
    _index_round_event(
        f"agentic round {record['round_id']} for {experiment_id}: {record['status']}; "
        f"transform={transform_record.get('status')}; proposal={proposal_id}",
        [record["status"], f"transform:{transform_record.get('status')}"],
        (pack.get("best_deterministic") or {}).get("run_id"),
    )
    return record


def execute_approved_round(
    experiment: Any,
    proposal_id: str,
    *,
    on_event: RoundEvent = None,
    should_continue: ShouldContinue = None,
    runs_root: Path | str | None = None,
) -> dict[str, Any]:
    """Execute an approved round proposal through the deterministic factory.

    The gate is called with ``allow_auto=False`` — execution requires the
    proposal to be explicitly approved by a human. Builds the
    agentic-vs-deterministic comparison artifact afterwards.
    """
    from thelab.run.batch import BatchRunner

    def emit(message: str) -> None:
        if on_event is not None:
            on_event("agentic_round", message)

    experiment_id = experiment.experiment_id
    proposals_dir = Path(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))
    store = ProposalStore(proposals_dir)
    if not store.exists(proposal_id):
        raise ValueError(f"round proposal not found: {proposal_id}")
    # Gate errors (HumanApprovalRequired / ApprovalDenied) propagate: callers
    # must surface them as awaiting_approval / rejected, never auto-approve.
    ensure_executable(
        store,
        proposal_id,
        principal=f"agentic_round_execute:{experiment_id}",
        allow_auto=False,
    )
    emit(f"Round proposal {proposal_id} approved; running through the deterministic factory")

    batch_path = store.write_batch_config(proposal_id)
    runner = BatchRunner(workspace_root=Path(os.environ.get("THELAB_WORKSPACE_ROOT", ".")))
    entries = runner.load_config(batch_path)
    results = runner.run(
        entries,
        on_result=lambda r: emit(
            f"model {r.entry.model} (seed {r.entry.seed}): {r.status}"
        ),
        should_continue=lambda: should_continue is None or should_continue(),
    )

    runs = Path(runs_root) if runs_root else Path(os.environ.get("THELAB_RUNS_ROOT", "runs"))
    training_results = [
        {
            "model": r.entry.model,
            "seed": r.entry.seed,
            "status": r.status,
            "run_id": r.run_id,
            "metrics": r.metrics,
            "error": r.error,
        }
        for r in results
    ]
    completed = [r for r in results if r.status == "completed"]
    best_agentic: dict[str, Any] | None = None
    if completed:
        best = max(completed, key=lambda r: (r.metrics or {}).get("test_accuracy", -1.0))
        best_metrics: dict[str, Any] = dict(best.metrics or {})
        if best.run_id:
            from thelab.mcp.common import load_json_artifact

            persisted = load_json_artifact(runs, best.run_id, "metrics.json")
            if persisted:
                best_metrics = persisted
        best_agentic = {
            "model": best.entry.model,
            "seed": best.entry.seed,
            "run_id": best.run_id,
            "metrics": best_metrics,
        }

    best_det: dict[str, Any] = dict(experiment.best_metrics or {})
    agent_metrics: dict[str, Any] = dict((best_agentic or {}).get("metrics") or {})
    det_run_id: str | None = experiment.best_run_id
    comparison: dict[str, Any] = {
        "deterministic_best": {"run_id": det_run_id, "metrics": best_det},
        "agentic_best": best_agentic,
        "agentic_completed": len(completed),
        "agentic_total": len(results),
        "validity_rate": round(len(completed) / len(results), 4) if results else None,
        "metric_delta": _metric_delta(best_det, agent_metrics),
    }

    experiments_dir = Path(
        os.environ.get("THELAB_EXPERIMENTS_DIR", Path(".thelab") / "experiments")
    )
    record_path = _round_record_path(experiments_dir, experiment_id)
    record: dict[str, Any] = {}
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            record = {}
    record["execution"] = {
        "proposal_id": proposal_id,
        "status": "completed" if completed else "failed",
        "training_results": training_results,
        "comparison": comparison,
        "executed_at": datetime.now(UTC).isoformat(),
    }
    experiments_dir.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    _index_round_event(
        f"agentic round executed for {experiment_id}: best_agentic="
        f"{(best_agentic or {}).get('run_id')}; delta={comparison['metric_delta']}",
        ["executed", "completed" if completed else "failed"],
        str((best_agentic or {}).get("run_id")) if (best_agentic or {}).get("run_id") else None,
    )
    return {"status": "completed" if completed else "failed", "comparison": comparison}


def _metric_delta(det_metrics: dict[str, Any], agentic_metrics: dict[str, Any]) -> dict[str, float]:
    """Signed improvement (agentic - deterministic) for shared metric keys."""
    deltas: dict[str, float] = {}
    for key in ("test_accuracy", "test_f1_macro", "test_rmse", "test_mae", "test_r2"):
        det_value = det_metrics.get(key)
        agent_value = agentic_metrics.get(key)
        if isinstance(det_value, (int, float)) and isinstance(agent_value, (int, float)):
            deltas[key] = round(float(agent_value) - float(det_value), 6)
    return deltas
