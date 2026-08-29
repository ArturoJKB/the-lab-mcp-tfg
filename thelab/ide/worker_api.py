"""HTTP-facing worker agent wrapper for the IDE.

Produces deterministic experiment proposals via the existing ``WorkerAgent``
with a mock provider fallback, so no external LLM or MCP server fleet is
required for the default UI flow.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from thelab.agents.mock import MockProvider
from thelab.agents.worker import WorkerAgent

from .datasets import DatasetNotFoundError, dataset_id_to_relative_path


def _workspace_root() -> Path:
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", "."))


def _runs_root() -> Path:
    return Path(os.environ.get("THELAB_RUNS_ROOT", "runs"))


def _proposals_dir() -> Path:
    return Path(os.environ.get("THELAB_PROPOSALS_DIR", "proposals"))


def _parse_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            import json

            parsed = json.loads(value)
            return [str(v) for v in parsed] if isinstance(parsed, list) else []
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _parse_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(v) for v in value]
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            import json

            parsed = json.loads(value)
            return [int(v) for v in parsed] if isinstance(parsed, list) else []
        return [int(item.strip()) for item in value.split(",") if item.strip()]
    return []


async def generate_proposal(
    dataset_id: str,
    target: str,
    goal: str,
    model_grid: list[str] | str | None = None,
    seeds: list[int] | str | None = None,
) -> dict[str, Any]:
    """Create a deterministic experiment proposal for the given dataset and target."""
    try:
        dataset_path = dataset_id_to_relative_path(dataset_id)
    except DatasetNotFoundError as exc:
        raise DatasetNotFoundError(str(exc)) from exc

    runs_root = _runs_root()
    proposals_dir = _proposals_dir()
    proposals_dir.mkdir(parents=True, exist_ok=True)

    worker = WorkerAgent(
        provider=MockProvider([]),
        servers=[],
        proposals_dir=proposals_dir,
        runs_root=runs_root,
        max_steps=1,
    )

    proposal = await worker.propose(
        goal=goal,
        dataset=dataset_path,
        target=target,
        model_grid=_parse_string_list(model_grid),
        seeds=_parse_int_list(seeds),
    )
    return proposal.safe_dict()
