"""Demo: global agents (Researcher + Diagnosis) supervising the worker.

Usage:
    .venv/bin/python examples/global_agents_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from thelab.agents import MockProvider, ServerConnection, WorkerAgent
from thelab.agents.cli import _connect_server
from thelab.agents.global_agents import DiagnosisAgent, Researcher
from thelab.agents.worker import ProposalStore
from thelab.run.runner import run_model


_SERVER_MODULES = {
    "data_catalog": "thelab.mcp.data_catalog_mcp",
    "model_registry": "thelab.mcp.model_registry_mcp",
    "workspace": "thelab.mcp.workspace_mcp",
    "context": "thelab.mcp.context_mcp",
    "eda": "thelab.mcp.eda_mcp",
}


async def main() -> int:
    dataset = "data/fixtures/iris.csv"
    target = "species"
    csv_path = repo_root / dataset
    if not csv_path.is_file():
        print(f"Dataset not found: {csv_path}", file=sys.stderr)
        return 1

    runs_root = repo_root / "runs"
    proposals_dir = repo_root / "proposals"
    proposals_dir.mkdir(exist_ok=True)

    # 1. Train a baseline run for the Researcher to ground its answer.
    print("Training baseline run...")
    run_result = run_model(
        dataset=csv_path,
        target=target,
        model="logistic_regression",
        seed=42,
        output="runs",
        workspace_root=repo_root,
    )
    if run_result["status"] != "completed":
        print("Baseline run failed.", file=sys.stderr)
        return 1
    run_id = run_result["run_id"]
    print(f"Baseline run: {run_id}")

    # 2. Researcher answers a grounded question.
    researcher = Researcher(runs_root=runs_root)
    answer = researcher.answer("Summarize the baseline run.", run_id=run_id)
    print("\nResearcher answer:")
    print(answer["answer"])
    print("Citations:", json.dumps(answer["citations"], indent=2))

    # 3. Diagnosis agent proposes and approves a follow-up experiment.
    print("\nDiagnosis agent handling follow-up goal...")
    provider = MockProvider([
        json.dumps({
            "dataset": dataset,
            "target": target,
            "model_grid": ["random_forest"],
            "seeds": [42],
            "task_type": "classification",
            "rationale": "Compare against tree ensemble.",
        })
    ])

    async with AsyncExitStack() as stack:
        connections: list[ServerConnection] = []
        for name, module in _SERVER_MODULES.items():
            connections.append(await _connect_server(stack, name, runs_root))

        worker = WorkerAgent(
            provider=provider,
            servers=connections,
            proposals_dir=proposals_dir,
            runs_root=runs_root,
        )
        store = ProposalStore(proposals_dir)
        diagnosis = DiagnosisAgent(worker=worker, proposal_store=store, principal="demo_diagnosis")
        result = await diagnosis.handle(
            dataset=dataset,
            target=target,
            error_summary="compare with a stronger baseline",
            model_grid=["random_forest"],
            seeds=[42],
        )

    print(f"Diagnosis result: {result['status']}")
    print(f"  Proposal: {result['proposal_id']}")
    if result["status"] == "approved":
        print(f"  Batch config: {result['batch_config_path']}")
    else:
        print(f"  Rejection path: {result['rejection_path']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
