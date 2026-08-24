"""Demo: worker agent proposes an experiment, human approves, batch runs.

Usage:
    .venv/bin/python examples/worker_proposal_demo.py
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
from thelab.agents.worker import ProposalStore
from thelab.run.batch import BatchRunner, write_markdown_report


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
    goal = "Train a small, interpretable classifier for iris species"

    csv_path = repo_root / dataset
    if not csv_path.is_file():
        print(f"Dataset not found: {csv_path}", file=sys.stderr)
        return 1

    runs_root = repo_root / "runs"
    proposals_dir = repo_root / "proposals"
    proposals_dir.mkdir(exist_ok=True)

    # Mock provider returns a JSON proposal directly.
    provider = MockProvider([
        json.dumps({
            "dataset": dataset,
            "target": target,
            "model_grid": ["logistic_regression", "random_forest"],
            "seeds": [42],
            "task_type": "classification",
            "rationale": "Interpretable baseline plus tree ensemble for comparison.",
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
        proposal = await worker.propose(
            goal=goal,
            dataset=dataset,
            target=target,
        )

    print(f"Created proposal: {proposal.proposal_id}")
    print(f"  Path: proposals/{proposal.proposal_id}.json")

    # Human approval step.
    store = ProposalStore(proposals_dir)
    store.approve(proposal.proposal_id, principal="demo")
    batch_path = store.write_batch_config(proposal.proposal_id)
    print(f"  Approved. Batch config: {batch_path}")

    # Execute batch.
    runner = BatchRunner(workspace_root=repo_root)
    entries = runner.load_config(batch_path)
    results = runner.run(entries, output="runs")
    summary_path = runs_root / "batch_summary.json"
    runner.write_summary(results, summary_path)
    report_path = batch_path.with_suffix(".md")
    write_markdown_report(results, report_path)

    print(f"  Batch summary: {summary_path}")
    print(f"  Batch report: {report_path}")
    completed = sum(1 for r in results if r.status == "completed")
    print(f"  Completed {completed}/{len(results)} experiments")
    return 0 if completed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
