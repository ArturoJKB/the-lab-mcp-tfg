"""Local stdio MCP server for agent orchestration.

Tools:
- orchestrate_experiment: main entry point for experiment orchestration
- spawn_subagent: spawn typed sub-agents (EDAAnalyst, FeatureEngineer, ModelSelector)
- run_deterministic_skill: run EDA, cleaning, try-all via deterministic functions
- run_training_job: queue training via /jobs endpoint
- get_job_status: poll job status + logs
- log_agent_activity: write to context store
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from thelab.agents.approval import (
    ApprovalDenied,
    HumanApprovalRequired,
    auto_approve_enabled,
    ensure_executable,
)
from thelab.agents.mock import MockProvider
from thelab.agents.provider import LLMProvider
from thelab.agents.worker import ProposalStore, WorkerAgent
from thelab.ide.datasets import resolve_dataset_path
from thelab.ide.eda_api import run_eda
from thelab.ide.jobs import get_job_manager
from thelab.run.batch import BatchRunner

# Tool definitions
TOOLS = [
    types.Tool(
        name="orchestrate_experiment",
        description="Main entry point for experiment orchestration. Takes goal, dataset, target and returns an orchestration plan with sub-agent tasks.",
        input_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Natural language goal for the experiment"},
                "dataset_id": {"type": "string", "description": "Dataset identifier (e.g., uploads/data.csv)"},
                "target": {"type": "string", "description": "Target column name"},
                "feedback": {"type": "string", "description": "Optional user feedback for iteration"},
                "provider": {"type": "string", "enum": ["mock", "ollama", "openrouter"], "default": "mock"},
                "model": {"type": "string", "description": "Model name for LLM provider"},
            },
            "required": ["goal", "dataset_id", "target"],
        },
    ),
    types.Tool(
        name="run_full_journey",
        description="Start a full agentic journey: deterministic baseline -> agentic round -> "
        "awaiting human approval at the gate. Returns experiment_id and job_id for polling. "
        "After the gate, use continue_journey to execute after human approval.",
        input_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Natural language goal for the experiment"},
                "dataset_id": {"type": "string", "description": "Dataset identifier (e.g., uploads/data.csv)"},
                "target": {"type": "string", "description": "Target column name"},
                "provider": {"type": "string", "enum": ["mock", "ollama", "openrouter"], "default": "mock"},
                "model": {"type": "string", "description": "Model name for LLM provider"},
            },
            "required": ["goal", "dataset_id", "target"],
        },
    ),
    types.Tool(
        name="continue_journey",
        description="After human approval of the agentic-round proposal, execute it through the "
        "deterministic factory. Requires the proposal to be approved via the UI or CLI.",
        input_schema={
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string", "description": "Experiment ID from run_full_journey"},
            },
            "required": ["experiment_id"],
        },
    ),
    types.Tool(
        name="get_journey_status",
        description="Return the agentic-round record for a journey: brief, transform, proposal, "
        "execution comparison. Poll this to track progress.",
        input_schema={
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string", "description": "Experiment ID"},
            },
            "required": ["experiment_id"],
        },
    ),
    types.Tool(
        name="spawn_subagent",
        description="Spawn a typed sub-agent (EDAAnalyst, FeatureEngineer, ModelSelector) with a specific goal and context.",
        input_schema={
            "type": "object",
            "properties": {
                "agent_type": {"type": "string", "enum": ["EDAAnalyst", "FeatureEngineer", "ModelSelector"]},
                "goal": {"type": "string"},
                "dataset_id": {"type": "string"},
                "target": {"type": "string"},
                "context": {"type": "object", "description": "Additional context for the sub-agent"},
            },
            "required": ["agent_type", "goal", "dataset_id", "target"],
        },
    ),
    types.Tool(
        name="run_deterministic_skill",
        description="Run a deterministic skill (EDA, cleaning, try-all) directly without LLM.",
        input_schema={
            "type": "object",
            "properties": {
                "skill": {"type": "string", "enum": ["eda", "cleaning", "try_all"]},
                "dataset_id": {"type": "string"},
                "target": {"type": "string"},
                "params": {"type": "object", "description": "Skill-specific parameters"},
            },
            "required": ["skill", "dataset_id", "target"],
        },
    ),
    types.Tool(
        name="run_training_job",
        description="Queue a training job via the /jobs endpoint. Returns job_id.",
        input_schema={
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "target": {"type": "string"},
                "model": {"type": "string"},
                "seed": {"type": "integer", "default": 42},
                "task_type": {"type": "string", "enum": ["auto", "classification", "regression"], "default": "auto"},
            },
            "required": ["dataset_id", "target", "model"],
        },
    ),
    types.Tool(
        name="get_job_status",
        description="Poll job status and logs via the job manager.",
        input_schema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
            },
            "required": ["job_id"],
        },
    ),
    types.Tool(
        name="log_agent_activity",
        description="Write an agent activity event to the local context store.",
        input_schema={
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "enum": ["subagent_spawned", "skill_executed", "training_queued", "subagent_completed", "orchestration_started", "orchestration_completed"]},
                "summary": {"type": "string"},
                "run_id": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "details": {"type": "object"},
            },
            "required": ["event_type", "summary", "run_id"],
        },
    ),
]

# Helper functions
def _ok(data: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": True, "data": data}, default=str))]
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"ok": False, "error": message}, default=str))]
    )


def _generate_experiment_id() -> str:
    return f"exp-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _generate_subagent_id(agent_type: str) -> str:
    return f"{agent_type.lower()}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _get_context_db_path() -> Path:
    env_path = os.environ.get("THELAB_CONTEXT_DB")
    if env_path:
        return Path(env_path)
    return Path(".thelab") / "context" / "context.db"


def _get_runs_root() -> Path:
    env_path = os.environ.get("THELAB_RUNS_ROOT")
    if env_path:
        return Path(env_path)
    return Path("runs")


def _get_proposals_dir() -> Path:
    env_path = os.environ.get("THELAB_PROPOSALS_DIR")
    if env_path:
        return Path(env_path)
    return Path("proposals")


async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    arguments = params.arguments or {}

    try:
        if name == "run_full_journey":
            return await _run_full_journey(arguments)

        if name == "continue_journey":
            return await _continue_journey(arguments)

        if name == "get_journey_status":
            return await _get_journey_status(arguments)

        if name == "orchestrate_experiment":
            return await _orchestrate_experiment(arguments)

        if name == "spawn_subagent":
            return await _spawn_subagent(arguments)

        if name == "run_deterministic_skill":
            return await _run_deterministic_skill(arguments)

        if name == "run_training_job":
            return await _run_training_job(arguments)

        if name == "get_job_status":
            return await _get_job_status(arguments)

        if name == "log_agent_activity":
            return await _log_agent_activity(arguments)

        return _error(f"unknown tool: {name}")

    except Exception as exc:
        return _error(f"tool execution failed: {exc}")


async def _run_full_journey(arguments: dict[str, Any]) -> types.CallToolResult:
    """Start a full agentic journey (deterministic baseline -> agentic round -> gate).

    Thin MCP wrapper around start_experiment(agentic_round=True). The caller
    polls get_journey_status until state == awaiting_approval, then the human
    approves and continue_journey executes.
    """
    goal = arguments.get("goal", "")
    dataset_id = arguments.get("dataset_id", "")
    target = arguments.get("target", "")
    provider_name = arguments.get("provider", "mock")
    model = arguments.get("model")

    if not goal or not dataset_id or not target:
        return _error("goal, dataset_id, and target are required")

    try:
        from thelab.ide.experiment_api import start_experiment

        data = await start_experiment(
            goal=goal,
            dataset_id=dataset_id,
            target=target,
            provider_name=provider_name,
            model=model,
            agentic_round=True,
        )
        return _ok({
            "experiment_id": data["experiment_id"],
            "job_id": data["job_id"],
            "state": data["state"],
            "poll_hint": "poll get_journey_status until state == awaiting_approval",
        })
    except Exception as exc:
        return _error(f"journey failed to start: {exc}")


async def _continue_journey(arguments: dict[str, Any]) -> types.CallToolResult:
    """Execute an approved agentic-round proposal through the factory."""
    experiment_id = arguments.get("experiment_id", "")
    if not experiment_id:
        return _error("experiment_id is required")

    try:
        from thelab.ide.experiment_api import approve_agentic_round

        data = await approve_agentic_round(experiment_id, principal="agent_mcp")
        return _ok({
            "experiment_id": data["experiment_id"],
            "proposal_id": data["proposal_id"],
            "job_id": data["job_id"],
            "state": data["state"],
            "poll_hint": "poll get_journey_status until state == completed",
        })
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"continue_journey failed: {exc}")


async def _get_journey_status(arguments: dict[str, Any]) -> types.CallToolResult:
    """Return the agentic-round record for a journey."""
    experiment_id = arguments.get("experiment_id", "")
    if not experiment_id:
        return _error("experiment_id is required")

    try:
        from thelab.ide.experiment_api import get_agentic_round, get_experiment_status

        status = await get_experiment_status(experiment_id)
        round_data = await get_agentic_round(experiment_id)
        return _ok({
            "experiment_id": experiment_id,
            "state": status.get("state"),
            "best_run_id": status.get("best_run_id"),
            "round": round_data,
        })
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"get_journey_status failed: {exc}")


async def _orchestrate_experiment(arguments: dict[str, Any]) -> types.CallToolResult:
    """Main orchestration entry point.

    MCP clients are agents, not humans: by default the proposal is created and
    returned as ``awaiting_approval`` instead of being executed. Execution
    happens only after explicit human approval (UI / CLI) or when
    ``THELAB_AUTO_APPROVE=1`` is set by the local operator.
    """
    goal = arguments.get("goal", "")
    dataset_id = arguments.get("dataset_id", "")
    target = arguments.get("target", "")
    feedback = arguments.get("feedback")
    provider_name = arguments.get("provider", "mock")
    model = arguments.get("model")

    if not goal or not dataset_id or not target:
        return _error("goal, dataset_id, and target are required")

    proposals_dir = _get_proposals_dir()

    # Create provider
    provider: LLMProvider
    if provider_name == "ollama":
        from thelab.agents.providers.ollama import OllamaProvider
        provider = OllamaProvider(model=model)
    elif provider_name == "openrouter":
        from thelab.agents.providers.openrouter import OpenRouterProvider
        provider = OpenRouterProvider()
    else:
        provider = MockProvider([])

    # Create worker agent
    store = ProposalStore(_get_proposals_dir())
    runs_root_path = _get_runs_root()

    worker = WorkerAgent(
        provider=provider,
        servers=[],  # Use mock provider, no MCP servers needed
        proposals_dir=proposals_dir,
        runs_root=runs_root_path,
    )

    # User feedback is forwarded into the proposal goal (real consumer).
    propose_goal = goal
    if isinstance(feedback, str) and feedback.strip():
        propose_goal = f"{goal}\nPrior user feedback to address: {feedback.strip()}"

    # Create proposal via worker
    try:
        proposal = await worker.propose(
            goal=propose_goal,
            dataset=dataset_id,
            target=target,
        )
    except Exception as exc:
        return _error(f"failed to create proposal: {exc}")

    # Approval gate: agents never self-approve unless the operator opts in.
    try:
        ensure_executable(
            store,
            proposal.proposal_id,
            principal="agent_mcp",
            allow_auto=auto_approve_enabled(),
        )
    except ApprovalDenied as exc:
        return _error(str(exc))
    except HumanApprovalRequired:
        return _ok({
            "status": "awaiting_approval",
            "proposal_id": proposal.proposal_id,
            "proposal": proposal.safe_dict(),
            "approve": (
                "POST /proposals/{id}/approve (UI), 'thelab proposals approve <id>', "
                "or enable an operator auto-approve opt-in (THELAB_AUTO_APPROVE=1 "
                "or .thelab/auto-approve.json with auto_approve=true + reason)"
            ),
        })

    # Approved (human or operator opt-in): translate and run the batch.
    approve_path = store.approval_path(proposal.proposal_id)
    batch_path = store.write_batch_config(proposal.proposal_id)

    # Run batch
    workspace_root = os.environ.get("THELAB_WORKSPACE_ROOT", str(Path.cwd()))
    runner = BatchRunner(workspace_root=Path(workspace_root))
    entries = runner.load_config(batch_path)
    results = runner.run(entries)

    failed = sum(1 for r in results if r.status == "failed")

    return _ok({
        "experiment_id": _generate_experiment_id(),
        "status": "completed" if failed == 0 else "partial",
        "proposal_id": proposal.proposal_id,
        "proposal": proposal.safe_dict(),
        "approval_path": str(approve_path),
        "batch_config_path": str(batch_path),
        "results": [
            {
                "dataset": r.entry.dataset,
                "target": r.entry.target,
                "model": r.entry.model,
                "seed": r.entry.seed,
                "run_id": r.run_id,
                "status": r.status,
                "error": r.error,
            }
            for r in results
        ],
    })


async def _spawn_subagent(arguments: dict[str, Any]) -> types.CallToolResult:
    """Spawn a typed sub-agent."""
    agent_type = arguments.get("agent_type")
    goal = arguments.get("goal", "")
    dataset_id = arguments.get("dataset_id", "")
    target = arguments.get("target", "")
    _ = arguments.get("context", {})

    if not agent_type or not goal or not dataset_id or not target:
        return _error("agent_type, goal, dataset_id, and target are required")

    if agent_type not in ["EDAAnalyst", "FeatureEngineer", "ModelSelector"]:
        return _error(f"invalid agent_type: {agent_type}")

    # Create worker agent for sub-agent
    worker = WorkerAgent(
        provider=MockProvider([]),
        servers=[],
        proposals_dir=_get_proposals_dir(),
        runs_root=_get_runs_root(),
    )

    # Generate sub-agent specific goal
    if agent_type == "EDAAnalyst":
        subagent_goal = f"Analyze dataset {dataset_id} for target {target}. {goal}"
    elif agent_type == "FeatureEngineer":
        subagent_goal = f"Propose cleaning/transformations for {dataset_id} targeting {target}. {goal}"
    else:  # ModelSelector
        subagent_goal = f"Select best model for {dataset_id} targeting {target}. {goal}"

    try:
        proposal = await worker.propose(
            goal=subagent_goal,
            dataset=dataset_id,
            target=target,
        )
    except Exception as exc:
        return _error(f"sub-agent failed: {exc}")

    return _ok({
        "subagent_id": _generate_subagent_id(agent_type),
        "agent_type": agent_type,
        "status": "completed",
        "proposal": proposal.safe_dict(),
    })


async def _run_deterministic_skill(arguments: dict[str, Any]) -> types.CallToolResult:
    """Run a deterministic skill directly."""
    skill = arguments.get("skill")
    dataset_id = arguments.get("dataset_id", "")
    target = arguments.get("target", "")
    params = arguments.get("params", {})

    if not skill or not dataset_id or not target:
        return _error("skill, dataset_id, and target are required")

    try:
        # Resolve dataset path
        path = resolve_dataset_path(dataset_id)

        if skill == "eda":
            data = run_eda(dataset_id, target=target)
            return _ok({"skill": "eda", "data": data})

        if skill == "cleaning":
            from thelab.ide.cleaning import clean_dataset
            metadata = clean_dataset(
                dataset_id,
                target,
                drop_missing_target=params.get("drop_missing_target", True),
                drop_empty_columns=params.get("drop_empty_columns", True),
                one_hot_encode=params.get("one_hot_encode", True),
                numeric_impute_strategy=params.get("numeric_impute_strategy", "median"),
                categorical_impute_strategy=params.get("categorical_impute_strategy", "mode"),
            )
            return _ok({"skill": "cleaning", "metadata": metadata})

        if skill == "try_all":
            from thelab.run.runner import try_all_models
            results = try_all_models(
                dataset=path,
                target=target,
                seed=params.get("seed", 42),
                output="scratch",
                workspace_root=Path.cwd(),
                dry_run=True,
            )
            return _ok({
                "skill": "try_all",
                "results": [
                    {
                        "model": r.get("model"),
                        "status": r.get("status"),
                        "metrics": r.get("metrics"),
                    }
                    for r in results
                ],
            })

        return _error(f"unknown skill: {skill}")

    except Exception as exc:
        return _error(f"skill execution failed: {exc}")


async def _run_training_job(arguments: dict[str, Any]) -> types.CallToolResult:
    """Queue a training job via the job manager."""
    dataset_id = arguments.get("dataset_id", "")
    target = arguments.get("target", "")
    model = arguments.get("model", "")
    seed = arguments.get("seed", 42)
    task_type = arguments.get("task_type", "auto")

    if not dataset_id or not target or not model:
        return _error("dataset_id, target, and model are required")

    job_manager = get_job_manager()
    job = await job_manager.submit("train", {
        "dataset_id": dataset_id,
        "target": target,
        "model": model,
        "seed": seed,
        "task_type": task_type,
    })

    return _ok({
        "job_id": job.job_id,
        "status": job.status,
    })


async def _get_job_status(arguments: dict[str, Any]) -> types.CallToolResult:
    """Get job status and logs."""
    job_id = arguments.get("job_id", "")

    if not job_id:
        return _error("job_id is required")

    job_manager = get_job_manager()
    job = await job_manager.get(job_id)

    if job is None:
        return _error(f"job not found: {job_id}")

    return _ok(job.to_dict())


async def _log_agent_activity(arguments: dict[str, Any]) -> types.CallToolResult:
    """Log agent activity to the context store via the context-write path.

    Uses the ``context_write_mcp`` validation + append helpers so every event
    is schema-checked and secret-redacted before touching disk.
    """
    event_type = arguments.get("event_type")
    summary = arguments.get("summary", "")
    run_id = arguments.get("run_id", "")
    tags = arguments.get("tags", [])
    _ = arguments.get("details", {})

    if not event_type or not summary or not run_id:
        return _error("event_type, summary, and run_id are required")

    try:
        from thelab.mcp.context_write_mcp import append_event, validate_event

        now = datetime.now(UTC)
        event = {
            "event_id": f"evt-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
            "timestamp": now.isoformat(),
            "event_type": "agent_session_summary",
            "session_id": f"agent_mcp_{now.strftime('%Y%m%d-%H%M%S')}",
            "run_id": run_id,
            "tags": [f"agent_mcp:{event_type}", *[str(t) for t in tags]],
            "outcome": {"status": "completed", "summary": str(summary)},
            "privacy": {"level": "internal"},
        }

        normalized, error = validate_event(event)
        if error:
            return _error(error)

        log_path = append_event(normalized)
        return _ok({"event_id": event["event_id"], "status": "logged", "log_path": str(log_path)})

    except Exception as exc:
        return _error(f"failed to log activity: {exc}")


server = Server(
    "thelab-agent-mcp",
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync() -> None:
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
