# P2 Phase 6 Plan — Agent Orchestration & Unified Workflow

> Authority: Binding plan for the Agent Orchestration phase of `docs/P2_IDE_PLAN.md`. Implement only what is listed here.

## Goal

Connect the fragmented UI workflow into a unified agent-driven experiment pipeline: fix the cleaning→training gap, implement `agent_mcp` for sub-agent orchestration, add a unified `/experiment/run` endpoint that spawns sub-agents (EDAAnalyst, FeatureEngineer, ModelSelector) alongside deterministic skills, and expose everything through a single "Experiment" panel.

## In scope

### 1. Backend — Fixes & Foundations
- Fix `thelab/ide/cleaning.py`: handle categorical NaN before one-hot encoding (impute with "missing" category).
- Fix Goal Launcher approve/reject flow: atomic approve+run endpoint, correct status element in UI.
- `thelab/ide/proposals_api.py`: add `approve_and_run_proposal()`.

### 2. Backend — `agent_mcp` Server
- New file: `thelab/mcp/agent_mcp.py`
- Tools exposed via MCP (stdio):
  - `orchestrate_experiment` — main entry: goal + dataset + target → orchestration plan with sub-agent tasks
  - `spawn_subagent` — spawn typed sub-agent (EDAAnalyst, FeatureEngineer, ModelSelector) with goal + context
  - `run_deterministic_skill` — run EDA, cleaning, try-all via existing deterministic functions
  - `run_training_job` — queue training via `/jobs` endpoint, return job_id
  - `get_job_status` — poll job status + logs
  - `log_agent_activity` — write to context store (uses context_write_mcp internally)
- Uses `ContextWriter` for logging, spawns sub-agents via `WorkerAgent` + `AgentHarness`, runs deterministic skills via direct imports.

### 3. Backend — Multi-Agent Orchestration
- New file: `thelab/ide/orchestrator.py` — `ExperimentOrchestrator` class
- Sub-agent types (specialized `WorkerAgent` prompts):
  - **EDAAnalyst** — analyzes dataset for leakage, outliers, class imbalance, feature quality
  - **FeatureEngineer** — proposes cleaning/transformations, runs cleaning via deterministic skills
  - **ModelSelector** — runs try-all, compares metrics, recommends hyperparameters
- New file: `thelab/ide/experiment.py` — `ExperimentState` machine
- Unified endpoint in `thelab/model_service/app.py`:
  - `POST /experiment/run` — starts experiment, returns experiment_id + plan + job_ids
  - `GET /experiment/{id}/status` — full state + sub-agent progress + logs
  - `GET /experiment/{id}/events` — SSE stream for live updates
  - `POST /experiment/{id}/feedback` — user feedback triggers iteration
  - `GET /experiment/{id}/results` — best model, metrics, artifacts, sub-agent findings

### 4. Backend — Fix Remaining Gaps
- Cleaned dataset auto-selection in training form
- Atomic `POST /proposals/{id}/approve-and-run`
- Validation error messages with actionable UI hints

### 5. Frontend — Unified Experiment Panel
- New **Experiment** sidebar panel (replaces Goal Launcher + Train + Pipeline + Proposals)
- Tabs:
  1. **Plan** — chat-like goal input + dataset/target context + model/provider selection
  2. **Run** — live pipeline visualization with SSE (cleaning → training → evaluation)
  3. **History** — all experiments for this dataset with status + best metrics
- Agent activity feed in Run tab: real-time sub-agent activity via SSE
- Merge Dataset + Viewer panels: single "Data" panel with tabs (Upload | Table | EDA | Distributions | Clean)

### 6. Tests
- `tests/test_ide_cleaning.py`: categorical NaN handling
- `tests/test_agent_mcp.py`: MCP tool discovery, sub-agent spawn, deterministic skills
- `tests/test_ide_orchestrator.py`: orchestration flow, sub-agent spawn, experiment state
- `tests/test_ide_experiment.py`: experiment endpoints, SSE, feedback loop

## Out of scope
- Persistent sandbox sessions.
- Network access inside sandbox.
- Real-time LLM provider configuration UI (use env vars).
- Export/sharing of experiments.
- Multi-user support.

## Safety boundaries
- Subprocess isolation for sub-agents; code never runs in main process.
- Sub-agents use same deny-by-default import whitelist as sandbox.
- Every write (approve, run, sub-agent action) requires explicit POST from UI.
- Approval artifacts record `"principal": "ui"` and timestamp.
- Sandbox: deny-by-default imports/network/subprocess, temp workspace only.
- Default bind remains `127.0.0.1`.
- No absolute paths in API responses.
- No bash terminal in UI. CLI remains available separately.

## Verification
```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_ide_cleaning.py tests/test_agent_mcp.py tests/test_ide_orchestrator.py tests/test_ide_experiment.py -q
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/evaluate_thesis.py
```

All must pass.

## File map
```text
docs/P2_PHASE6_PLAN.md
docs/P2_PHASE6_CONTEXT.md

thelab/ide/
  __init__.py
  cleaning.py          # fixed
  orchestrator.py      # new
  experiment.py        # new
  sub_agents.py        # new (prompt templates)
  proposals_api.py     # fixed (approve_and_run)

thelab/mcp/
  agent_mcp.py         # new

thelab/model_service/app.py          # new endpoints + fixes
thelab/model_service/static/index.html
thelab/model_service/static/app.js
thelab/model_service/static/styles.css

tests/
  test_ide_cleaning.py   # extended
  test_agent_mcp.py      # new
  test_ide_orchestrator.py # new
  test_ide_experiment.py # new
```