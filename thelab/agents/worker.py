"""Worker agent: proposes ML experiments for human approval.

The worker routes sub-tasks (EDA, prior-run lookup) through the L1 agent
harness and MCP allowlist. It never executes proposals directly; approved
proposals are translated 1:1 into batch configs for ``thelab run batch``.
"""

from __future__ import annotations

import itertools
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from thelab.eda import class_balance, feature_types, missing_profile
from thelab.mcp.common import discover_run_ids, load_json_artifact
from thelab.run.model_registry import MODEL_REGISTRY
from thelab.run.task_type import infer_task_type

from .harness import AgentHarness, ServerConnection
from .json_repair import safe_json_loads
from .provider import AgentMessage, LLMProvider


def _parse_datetime(value: Any) -> datetime:
    """Parse an ISO datetime string or return a datetime object unchanged."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"cannot parse datetime from {value!r}")


ISODatetime = Annotated[datetime, BeforeValidator(_parse_datetime)]


class ExperimentProposal(BaseModel):
    """A proposed batch of experiments for human approval."""

    model_config = ConfigDict(strict=True, extra="forbid")

    proposal_id: str
    goal: str
    dataset: str
    target: str
    model_grid: list[str] = Field(default_factory=list)
    seeds: list[int] = Field(default_factory=list)
    hyperparameter_grid: dict[str, list[Any]] = Field(default_factory=dict)
    task_type: str = "auto"
    rationale: str = ""
    prior_runs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: ISODatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("model_grid")
    @classmethod
    def _known_models(cls, value: list[str]) -> list[str]:
        known = set(MODEL_REGISTRY.list_models())
        for name in value:
            if name not in known:
                raise ValueError(f"unsupported model in proposal grid: {name}")
        return value

    @field_validator("hyperparameter_grid")
    @classmethod
    def _scalar_lists(cls, value: dict[str, Any]) -> dict[str, list[Any]]:
        if not isinstance(value, dict):
            raise ValueError("hyperparameter_grid must be a dict of parameter names to lists")
        for key, items in value.items():
            if not isinstance(items, list):
                raise ValueError(f"hyperparameter_grid['{key}'] must be a list")
        return dict(value)

    def safe_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the proposal."""
        return {
            "proposal_id": self.proposal_id,
            "goal": self.goal,
            "dataset": self.dataset,
            "target": self.target,
            "model_grid": self.model_grid,
            "seeds": self.seeds,
            "hyperparameter_grid": self.hyperparameter_grid,
            "task_type": self.task_type,
            "rationale": self.rationale,
            "prior_runs": self.prior_runs,
            "created_at": self.created_at.isoformat(),
        }


class ProposalStore:
    """Read/write proposals and approval/rejection records."""

    def __init__(self, proposals_dir: Path | str | None = None) -> None:
        self.proposals_dir = Path(proposals_dir) if proposals_dir else Path("proposals")
        self.proposals_dir.mkdir(parents=True, exist_ok=True)

    def _proposal_path(self, proposal_id: str) -> Path:
        return self.proposals_dir / f"{proposal_id}.json"

    def _approval_path(self, proposal_id: str) -> Path:
        return self.proposals_dir / f"{proposal_id}.approved.json"

    def _rejection_path(self, proposal_id: str) -> Path:
        return self.proposals_dir / f"{proposal_id}.rejected.json"

    def save(self, proposal: ExperimentProposal) -> Path:
        """Persist a proposal and return its path."""
        path = self._proposal_path(proposal.proposal_id)
        path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, proposal_id: str) -> ExperimentProposal:
        """Load a proposal by id."""
        path = self._proposal_path(proposal_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return ExperimentProposal.model_validate(data)

    def exists(self, proposal_id: str) -> bool:
        """Return True if the proposal file exists."""
        return self._proposal_path(proposal_id).is_file()

    def approve(self, proposal_id: str, principal: str = "human") -> Path:
        """Write an approval record and return its path."""
        path = self._approval_path(proposal_id)
        record = {
            "proposal_id": proposal_id,
            "principal": principal,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return path

    def reject(self, proposal_id: str, principal: str = "human", reason: str = "") -> Path:
        """Write a rejection record and return its path."""
        path = self._rejection_path(proposal_id)
        record = {
            "proposal_id": proposal_id,
            "principal": principal,
            "reason": reason,
            "rejected_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return path

    def is_approved(self, proposal_id: str) -> bool:
        return self._approval_path(proposal_id).is_file()

    def is_rejected(self, proposal_id: str) -> bool:
        return self._rejection_path(proposal_id).is_file()

    def list_proposals(self) -> list[str]:
        """Return all proposal ids with a stored proposal file."""
        ids: list[str] = []
        for path in sorted(self.proposals_dir.glob("*.json")):
            # Skip derived records (approval, rejection, batch config) by
            # requiring the base filename to have no extra dot suffixes.
            if "." in path.stem:
                continue
            ids.append(path.stem)
        return ids

    def write_batch_config(self, proposal_id: str) -> Path:
        """Translate an approved proposal into a batch config JSON file.

        The output is a JSON list that ``thelab run batch --config`` expects.
        If ``hyperparameter_grid`` is non-empty, entries include every Cartesian
        combination of hyperparameter values.
        """
        proposal = self.load(proposal_id)
        hp_grid = proposal.hyperparameter_grid or {}

        hp_names = list(hp_grid.keys())
        hp_values = [hp_grid[name] for name in hp_names]
        hp_combinations = [dict(zip(hp_names, combo, strict=True)) for combo in itertools.product(*hp_values)] or [{}]

        entries: list[dict[str, Any]] = []
        for model in proposal.model_grid:
            for seed in proposal.seeds:
                for hp in hp_combinations:
                    entry: dict[str, Any] = {
                        "dataset": proposal.dataset,
                        "target": proposal.target,
                        "model": model,
                        "seed": seed,
                        "task_type": proposal.task_type,
                    }
                    if hp:
                        entry["hyperparameters"] = hp
                    entries.append(entry)
        path = self.proposals_dir / f"{proposal_id}.batch.json"
        path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return path


def _generate_proposal_id() -> str:
    return f"prop-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _default_seeds() -> list[int]:
    return [42]


def _default_model_grid(task_type: str) -> list[str]:
    """Return a small default grid appropriate to the task type."""
    if task_type == "regression":
        return ["ridge", "random_forest_regressor"]
    return ["logistic_regression", "random_forest"]


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Try to extract the first JSON object from *text*.

    Uses conservative JSON repair to handle markdown fences, trailing commas,
    single quotes, and unquoted keys common in small local model outputs.
    """
    if not text:
        return None
    parsed = safe_json_loads(text)
    if isinstance(parsed, dict):
        return parsed
    return None


def _validate_proposal_dict(
    data: dict[str, Any],
    goal: str,
    dataset: str,
    target: str,
) -> dict[str, Any]:
    """Normalize and validate a raw proposal dict against the registry."""
    data = dict(data)
    data.setdefault("goal", goal)
    data.setdefault("dataset", dataset)
    data.setdefault("target", target)

    # Validate task_type.
    task_type = data.get("task_type", "auto")
    if task_type not in {"auto", "classification", "regression"}:
        task_type = "auto"
    data["task_type"] = task_type

    # Validate model_grid.
    known = set(MODEL_REGISTRY.list_models())
    grid = data.get("model_grid") or []
    if not isinstance(grid, list):
        grid = []
    grid = [str(m) for m in grid if str(m) in known]
    data["model_grid"] = grid

    # Validate seeds.
    seeds = data.get("seeds") or []
    if not isinstance(seeds, list):
        seeds = []
    seeds = [int(s) for s in seeds if isinstance(s, int) or (isinstance(s, str) and s.isdigit())]
    data["seeds"] = seeds or _default_seeds()

    # Validate hyperparameter_grid.
    hp_grid = data.get("hyperparameter_grid") or {}
    if not isinstance(hp_grid, dict):
        hp_grid = {}
    data["hyperparameter_grid"] = {str(k): list(v) for k, v in hp_grid.items() if isinstance(v, (list, tuple))}

    return data


def _find_prior_runs(runs_root: Path, dataset: str, target: str, limit: int = 3) -> list[dict[str, Any]]:
    """Find prior completed runs on the same dataset/target and return metrics."""
    prior: list[dict[str, Any]] = []
    for run_id in discover_run_ids(runs_root):
        manifest = load_json_artifact(runs_root, run_id, "manifest.json")
        if manifest is None or manifest.get("final_status") != "completed":
            continue
        inputs = load_json_artifact(runs_root, run_id, "inputs.json") or {}
        if inputs.get("dataset") != dataset or inputs.get("target") != target:
            continue
        metrics = load_json_artifact(runs_root, run_id, "metrics.json") or {}
        prior.append({
            "run_id": run_id,
            "model": inputs.get("model"),
            "metrics": metrics,
            "task_type": manifest.get("task_type") or inputs.get("task_type"),
        })
    # Return most recent first.
    prior.sort(key=lambda x: x["run_id"], reverse=True)
    return prior[:limit]


def _build_eda_rationale(
    dataset: str,
    target: str,
    df_path: Path,
    prior_runs: list[dict[str, Any]] | None = None,
) -> str:
    """Run deterministic EDA directly and return a compact rationale string."""
    from thelab.run.profile import read_csv

    df = read_csv(df_path)
    missing = missing_profile(df, target=target)
    balance = class_balance(df, target=target)
    types_report = feature_types(df, target=target)
    task_type = infer_task_type(df, target)

    parts = [
        f"Dataset {dataset} has {missing['total_rows']} rows and {len(missing['columns'])} columns.",
        f"Task type inferred as {task_type}.",
    ]
    missing_cols = missing["most_missing"]
    if missing_cols:
        parts.append(f"Columns with missing values: {missing_cols}.")
    if balance.get("classes"):
        parts.append(
            f"Target '{target}' has {len(balance['classes'])} classes; "
            f"imbalance ratio {balance.get('imbalance_ratio')}.")
    parts.append(
        f"Feature type mix: {types_report['numeric_count']} numeric, "
        f"{types_report['categorical_count']} categorical."
    )
    if prior_runs:
        prior_summary = "; ".join(
            f"{p['run_id']} ({p['model']}): "
            f"accuracy={p['metrics'].get('test_accuracy')}, rmse={p['metrics'].get('test_rmse')}"
            for p in prior_runs
        )
        parts.append(f"Prior runs on this dataset: {prior_summary}.")
    return " ".join(parts)


class WorkerAgent:
    """Agent that proposes experiments via the harness-mediated MCP surface."""

    def __init__(
        self,
        provider: LLMProvider,
        servers: list[ServerConnection],
        proposals_dir: Path | str | None = None,
        runs_root: Path | str | None = None,
        max_steps: int = 8,
    ) -> None:
        self.provider = provider
        self.servers = servers
        self.store = ProposalStore(proposals_dir)
        self.runs_root = Path(runs_root) if runs_root else None
        self.harness: AgentHarness | None = None
        if servers:
            self.harness = AgentHarness(
                provider=provider,
                servers=servers,
                runs_root=runs_root,
                max_steps=max_steps,
            )

    async def propose(
        self,
        goal: str,
        dataset: str,
        target: str,
        model_grid: list[str] | None = None,
        seeds: list[int] | None = None,
        task_type: str = "auto",
        hyperparameter_grid: dict[str, list[Any]] | None = None,
    ) -> ExperimentProposal:
        """Propose an experiment by reasoning over EDA tools and prior runs.

        The provider is asked to produce a JSON proposal. If the provider does
        not return parseable JSON, the worker falls back to a deterministic
        proposal built from direct EDA calls and prior-run metrics.
        """
        runs_root = self.runs_root
        dataset_path = Path(dataset)
        if not dataset_path.is_absolute() and runs_root:
            dataset_path = runs_root.parent / dataset_path

        prior_runs: list[dict[str, Any]] = []
        if runs_root:
            prior_runs = _find_prior_runs(runs_root, dataset, target)

        deterministic_rationale = _build_eda_rationale(dataset, target, dataset_path, prior_runs)

        prompt = (
            "You are the experiment-planning worker for The Lab. "
            "Analyze the dataset and return a single JSON object. "
            "Do not wrap the JSON in markdown fences and do not add any text outside the JSON object.\n\n"
            "Required schema (all fields are required):\n"
            "{\n"
            '  "dataset": "' + dataset + '",\n'
            '  "target": "' + target + '",\n'
            '  "model_grid": ["logistic_regression"],\n'
            '  "seeds": [42],\n'
            '  "hyperparameter_grid": {},\n'
            '  "task_type": "classification" or "regression",\n'
            '  "rationale": "Brief justification based on the EDA summary."\n'
            "}\n\n"
            f"Goal: {goal}\n"
            f"Initial EDA summary: {deterministic_rationale}\n\n"
            "Return only the JSON object."
        )

        # Ask the provider directly for a JSON proposal (no tools). The prompt
        # already includes the deterministic EDA summary, so small local models
        # are more likely to emit valid JSON than when distracted by tool calls.
        turn = self.provider.complete([AgentMessage(role="user", content=prompt)], [])
        proposal_id = _generate_proposal_id()

        parsed: dict[str, Any] | None = None
        if turn.text is not None:
            parsed = _extract_json_block(turn.text)
        elif turn.tool_calls and self.harness is not None:
            # The provider decided it needs tool results first; fall back to the
            # harness so the tool calls are executed and the conversation resumes.
            result = await self.harness.run(prompt)
            if result.get("status") == "success":
                parsed = _extract_json_block(result.get("answer", ""))

        if parsed is not None:
            parsed = _validate_proposal_dict(parsed, goal, dataset, target)
            parsed.setdefault("proposal_id", proposal_id)
            parsed.setdefault("model_grid", model_grid or [])
            parsed.setdefault("seeds", seeds or [])
            parsed.setdefault("hyperparameter_grid", hyperparameter_grid or {})
            parsed.setdefault("rationale", deterministic_rationale)
            parsed["prior_runs"] = prior_runs
            try:
                proposal = ExperimentProposal.model_validate(parsed)
                self.store.save(proposal)
                return proposal
            except Exception:
                pass

        # Fallback: deterministic proposal from EDA and prior runs.
        resolved_task_type = task_type
        if resolved_task_type == "auto":
            from thelab.run.profile import read_csv

            df = read_csv(dataset_path)
            resolved_task_type = infer_task_type(df, target)

        grid = model_grid or _default_model_grid(resolved_task_type)
        proposal = ExperimentProposal(
            proposal_id=proposal_id,
            goal=goal,
            dataset=dataset,
            target=target,
            model_grid=grid,
            seeds=seeds or _default_seeds(),
            hyperparameter_grid=hyperparameter_grid or {},
            task_type=resolved_task_type,
            rationale=deterministic_rationale,
            prior_runs=prior_runs,
        )
        self.store.save(proposal)
        return proposal
