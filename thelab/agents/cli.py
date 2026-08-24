"""Entry point: ``thelab-agent "goal" --provider mock``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .global_agents import DiagnosisAgent, Researcher
from .harness import AgentHarness, ApprovalRequiredError, ServerConnection
from .mock import MockProvider, load_script
from .provider import LLMProvider
from .providers import OllamaProvider, OpenAICompatProvider, OpenRouterProvider
from .worker import ProposalStore, WorkerAgent

_WRITE_SERVER_MODULE = "thelab.mcp.context_write_mcp"
_SERVER_MODULES = {
    "data_catalog": "thelab.mcp.data_catalog_mcp",
    "model_registry": "thelab.mcp.model_registry_mcp",
    "workspace": "thelab.mcp.workspace_mcp",
    "context": "thelab.mcp.context_mcp",
    "eda": "thelab.mcp.eda_mcp",
}


def _parse_string_list(value: str | None) -> list[str]:
    """Parse a comma-separated or JSON-string list."""
    if not value:
        return []
    value = value.strip()
    if value.startswith("["):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int_list(value: str | None) -> list[int]:
    """Parse a comma-separated or JSON integer list."""
    if not value:
        return []
    value = value.strip()
    if value.startswith("["):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [int(item) for item in parsed]
        return []
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _parse_hyperparameter_grid(value: str | None) -> dict[str, list[Any]]:
    """Parse a JSON hyperparameter grid object."""
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("hyperparameter-grid must be a JSON object")
    return {str(k): list(v) for k, v in parsed.items()}


def _build_session_event(
    mode: str,
    goal: str,
    result: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Build a canonical /log session summary event."""
    from datetime import UTC, datetime

    event_id = f"agent_{mode}_{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    tags = [f"agent_mode:{mode}"]
    if args.dataset:
        tags.append(f"dataset:{args.dataset}")
    if args.target:
        tags.append(f"target:{args.target}")
    if args.run_id:
        tags.append(f"run_id:{args.run_id}")

    status = result.get("status", "unknown")
    summary = f"{mode} session completed with status {status}."
    if mode == "worker" and result.get("proposal_id"):
        summary += f" Proposal {result['proposal_id']} created."
    elif mode == "diagnosis" and result.get("proposal_id"):
        summary += f" Proposal {result['proposal_id']} {status}."
    elif mode == "researcher":
        summary = f"Researcher answered: {result.get('answer', '')[:120]}"
    elif mode == "agent":
        summary = result.get("answer", "Agent session completed.")

    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": "agent_session_summary",
        "project": "the-lab-mcp-tfg",
        "context": {
            "slice": "A3.1",
            "mode": mode,
            "goal": goal,
            "run_id": args.run_id,
        },
        "outcome": {"status": status, "summary": summary},
        "learning": {"topics": ["agent_memory", mode]},
        "evidence": {"artifacts": [], "source_refs": []},
        "privacy": {"level": "internal"},
        "tags": tags,
    }


async def _connect_server(
    stack: AsyncExitStack,
    name: str,
    runs_root: Path,
) -> ServerConnection:
    """Spawn one stdio MCP server and return a named connection."""
    env = dict(os.environ)
    env["THELAB_RUNS_ROOT"] = str(runs_root)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", _SERVER_MODULES[name]],
        env=env,
    )
    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()
    return ServerConnection(name=name, session=session)


async def _append_session_summary(event: dict[str, Any]) -> dict[str, Any]:
    """Append a session summary via the context writer MCP server."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", _WRITE_SERVER_MODULE],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("append_session_summary", {"event": event})
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            return dict(json.loads(text))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thelab-agent",
        description="The Lab — local agent harness over read-only MCP servers.",
    )
    parser.add_argument("goal", nargs="?", default="", help="User goal for the agent")
    parser.add_argument(
        "--mode",
        choices=["agent", "worker", "researcher", "diagnosis"],
        default="agent",
        help="Agent mode: agent = read-only Q&A, worker = propose experiment, "
             "researcher = cited answer, diagnosis = worker supervision (default: agent)",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "openai_compat", "ollama", "openrouter"],
        default="mock",
        help="LLM provider backend (default: mock)",
    )
    parser.add_argument(
        "--mock-script",
        help="JSON script for the mock provider (required for non-trivial mock runs)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum provider turns (default: 8)",
    )
    parser.add_argument(
        "--runs-root",
        default=None,
        help="Workspace runs directory (default: THELAB_RUNS_ROOT or ./runs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON outcome instead of human-readable text",
    )
    # Worker-only options.
    parser.add_argument(
        "--dataset",
        help="Relative path to the dataset CSV (worker mode)",
    )
    parser.add_argument(
        "--target",
        help="Target column name (worker mode)",
    )
    parser.add_argument(
        "--model-grid",
        help="Comma-separated or JSON list of model names (worker/diagnosis mode)",
    )
    parser.add_argument(
        "--seeds",
        help="Comma-separated or JSON list of seeds (worker/diagnosis mode)",
    )
    parser.add_argument(
        "--hyperparameter-grid",
        help="JSON object mapping parameter names to lists of values (worker/diagnosis mode)",
    )
    parser.add_argument(
        "--proposals-dir",
        default="proposals",
        help="Directory for persisted proposals (worker/diagnosis mode, default: proposals)",
    )
    # Researcher options.
    parser.add_argument(
        "--question",
        help="Question to answer (researcher mode)",
    )
    parser.add_argument(
        "--run-id",
        help="Run ID to ground the answer (researcher/diagnosis mode)",
    )
    # Diagnosis options.
    parser.add_argument(
        "--error",
        help="Error summary for diagnosis mode",
    )
    return parser


def _create_provider(args: argparse.Namespace) -> LLMProvider:
    """Instantiate the selected provider from CLI arguments."""
    if args.provider == "mock":
        script: list[str | dict[str, Any]] = []
        if args.mock_script:
            script = load_script(args.mock_script)
        return MockProvider(script)
    if args.provider == "openai_compat":
        return OpenAICompatProvider()
    if args.provider == "ollama":
        return OllamaProvider()
    if args.provider == "openrouter":
        return OpenRouterProvider()
    raise ValueError(
        f"unsupported provider: {args.provider}. Supported: mock, openai_compat, ollama, openrouter"
    )


async def _run_session(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Run the harness or worker and return (exit_code, result_dict)."""
    runs_root = (
        Path(args.runs_root)
        if args.runs_root
        else Path(os.environ.get("THELAB_RUNS_ROOT", "runs"))
    )
    provider = _create_provider(args)

    async with AsyncExitStack() as stack:
        connections: list[ServerConnection] = []
        for name in _SERVER_MODULES:
            connections.append(await _connect_server(stack, name, runs_root))

        if args.mode == "worker":
            if not args.dataset or not args.target:
                print("error: --dataset and --target are required in worker mode", file=sys.stderr)
                return 2, {"status": "error", "reason": "missing_dataset_or_target"}
            worker = WorkerAgent(
                provider=provider,
                servers=connections,
                proposals_dir=Path(args.proposals_dir),
                runs_root=runs_root,
                max_steps=args.max_steps,
            )
            proposal = await worker.propose(
                goal=args.goal,
                dataset=args.dataset,
                target=args.target,
                model_grid=_parse_string_list(args.model_grid),
                seeds=_parse_int_list(args.seeds),
                hyperparameter_grid=_parse_hyperparameter_grid(args.hyperparameter_grid),
            )
            result = proposal.safe_dict()
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"Proposal created: {proposal.proposal_id}")
                print(f"  Dataset: {proposal.dataset}")
                print(f"  Target: {proposal.target}")
                print(f"  Models: {', '.join(proposal.model_grid)}")
                print(f"  Seeds: {proposal.seeds}")
                print(f"  Path: proposals/{proposal.proposal_id}.json")
            return 0, result

        if args.mode == "researcher":
            if not args.question:
                print("error: --question is required in researcher mode", file=sys.stderr)
                return 2, {"status": "error", "reason": "missing_question"}
            from thelab.mcp.context_mcp import _get_context_db_path

            researcher = Researcher(
                runs_root=runs_root,
                context_db_path=_get_context_db_path(),
            )
            result = researcher.answer(question=args.question, run_id=args.run_id)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(result["answer"])
                if result.get("citations"):
                    print("\nCitations:")
                    for key, citation in result["citations"].items():
                        print(f"  {key}: {citation}")
            return 0, result

        if args.mode == "diagnosis":
            if not args.dataset or not args.target:
                print("error: --dataset and --target are required in diagnosis mode", file=sys.stderr)
                return 2, {"status": "error", "reason": "missing_dataset_or_target"}
            worker = WorkerAgent(
                provider=provider,
                servers=connections,
                proposals_dir=Path(args.proposals_dir),
                runs_root=runs_root,
                max_steps=args.max_steps,
            )
            store = ProposalStore(proposals_dir=Path(args.proposals_dir))
            from thelab.mcp.context_mcp import _get_context_db_path

            diagnosis = DiagnosisAgent(
                worker=worker,
                proposal_store=store,
                principal="diagnosis_agent",
                runs_root=runs_root,
                context_db_path=_get_context_db_path(),
            )
            validation_report: dict[str, Any] | None = None
            if args.run_id:
                from thelab.mcp.common import load_json_artifact

                validation_report = load_json_artifact(runs_root, args.run_id, "validation_report.json")
            result = await diagnosis.handle(
                dataset=args.dataset,
                target=args.target,
                error_summary=args.error,
                validation_report=validation_report,
                run_id=args.run_id,
                model_grid=_parse_string_list(args.model_grid),
                seeds=_parse_int_list(args.seeds),
                hyperparameter_grid=_parse_hyperparameter_grid(args.hyperparameter_grid),
            )
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"Diagnosis result: {result['status']}")
                print(f"  Proposal: {result['proposal_id']}")
                print(f"  Principal: {result['principal']}")
                if result["status"] == "approved":
                    print(f"  Batch config: {result['batch_config_path']}")
                else:
                    print(f"  Rejection path: {result['rejection_path']}")
            return 0, result

        harness = AgentHarness(
            provider=provider,
            servers=connections,
            runs_root=runs_root,
            max_steps=args.max_steps,
        )
        result = await harness.run(args.goal)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if result.get("status") == "success":
            print(result["answer"])
        else:
            print(
                f"Refused: {result.get('reason')} — {result.get('message')}",
                file=sys.stderr,
            )

    return 0 if result.get("status") == "success" else 1, result


async def _run(args: argparse.Namespace) -> int:
    """Run the session and append a session summary to the context log."""
    exit_code, result = await _run_session(args)
    try:
        event = _build_session_event(args.mode, args.goal, result, args)
        await _append_session_summary(event)
    except Exception:
        # Session summary is best-effort; do not fail the agent invocation.
        pass
    return exit_code


def _emit_approval(exc: ApprovalRequiredError, json_output: bool) -> int:
    if json_output:
        print(
            json.dumps(
                {
                    "status": "approval_required",
                    "tool": exc.tool,
                    "arguments": exc.arguments,
                    "request_path": str(exc.request_path),
                },
                indent=2,
                default=str,
            )
        )
    else:
        print(f"Approval required: {exc}", file=sys.stderr)
    return 2


def _find_approval_error(exc: BaseException) -> ApprovalRequiredError | None:
    """Recursively search nested exception groups for ApprovalRequiredError."""
    if isinstance(exc, ApprovalRequiredError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = _find_approval_error(child)
            if found is not None:
                return found
    return None


def _print_exception_group(eg: BaseExceptionGroup) -> None:
    """Flatten and print every leaf exception in a group."""
    for exc in eg.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            _print_exception_group(exc)
        else:
            print(f"Error: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except ApprovalRequiredError as exc:
        return _emit_approval(exc, args.json)
    except BaseExceptionGroup as eg:
        approval = _find_approval_error(eg)
        if approval is not None:
            return _emit_approval(approval, args.json)
        _print_exception_group(eg)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
