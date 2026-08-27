"""HTTP-facing proposal actions for the IDE.

Supports approve, reject, and run (translate to batch config + execute) for
proposals persisted under ``proposals/``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thelab.agents.worker import ProposalStore
from thelab.run.batch import BatchRunner


def _proposals_dir() -> Path:
    return Path(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))


def _workspace_root() -> Path:
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))


def approve_proposal(proposal_id: str, principal: str = "ui") -> dict[str, Any]:
    """Write an approval record for a proposal."""
    store = ProposalStore(_proposals_dir())
    if not store.exists(proposal_id):
        raise ValueError(f"proposal not found: {proposal_id}")
    path = store.approve(proposal_id, principal=principal)
    return {"proposal_id": proposal_id, "status": "approved", "path": path.as_posix()}


def reject_proposal(proposal_id: str, principal: str = "ui", reason: str = "") -> dict[str, Any]:
    """Write a rejection record for a proposal."""
    store = ProposalStore(_proposals_dir())
    if not store.exists(proposal_id):
        raise ValueError(f"proposal not found: {proposal_id}")
    path = store.reject(proposal_id, principal=principal, reason=reason)
    return {"proposal_id": proposal_id, "status": "rejected", "path": path.as_posix()}


def run_proposal(proposal_id: str) -> dict[str, Any]:
    """Translate an approved proposal to a batch config and execute it."""
    store = ProposalStore(_proposals_dir())
    if not store.exists(proposal_id):
        raise ValueError(f"proposal not found: {proposal_id}")
    if not store.is_approved(proposal_id):
        raise ValueError(f"proposal must be approved before running: {proposal_id}")

    config_path = store.write_batch_config(proposal_id)
    runner = BatchRunner(workspace_root=_workspace_root())
    entries = runner.load_config(config_path)
    results = runner.run(entries)

    completed = sum(1 for r in results if r.status == "completed")
    failed = sum(1 for r in results if r.status == "failed")
    rejected_count = sum(1 for r in results if r.status == "rejected")

    return {
        "proposal_id": proposal_id,
        "status": "completed" if failed == 0 and rejected_count == 0 else "partial",
        "total": len(results),
        "completed": completed,
        "failed": failed,
        "rejected": rejected_count,
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
    }
