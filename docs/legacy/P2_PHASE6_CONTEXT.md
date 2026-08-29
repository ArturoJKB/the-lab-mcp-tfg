# P2 Phase 6 Context — Agent Orchestration & Unified Workflow

> Implements the binding plan in `docs/P2_PHASE6_PLAN.md`.

## Changed files

| File | Change |
|---|---|
| `thelab/ide/orchestrator.py` | `ExperimentOrchestrator` now reads `THELAB_PROPOSALS_DIR` by default, uses its own proposal store, resolves `try_all_models` through workspace-relative dataset ids, and accepts an `on_event(stage, message)` callback for live progress. |
| `thelab/ide/jobs.py` | New `experiment` job type: runs the orchestrator, streams stage events, maps stages to `ExperimentState`, persists sub-agent findings, plan, and best-run metrics. |
| `thelab/ide/experiment_api.py` | New module: `start_experiment`, `get_experiment_status`, `get_experiment_events`, `add_experiment_feedback`, `get_experiment_results`, `list_experiments`. |
| `thelab/ide/experiment.py` | Experiment state machine + `ExperimentStore` (from Phase 1 core). |
| `thelab/ide/sub_agents.py` | Sub-agent prompt templates (from Phase 1 core). |
| `thelab/ide/__init__.py` | Exported experiment API functions. |
| `thelab/mcp/agent_mcp.py` | `log_agent_activity` now routes through `context_write_mcp` validation + redaction (canonical `/log` event); `orchestrate_experiment` batch runner uses `THELAB_WORKSPACE_ROOT`; provider branches typed with `LLMProvider`. |
| `thelab/model_service/app.py` | New endpoints: `POST /experiment/run`, `GET /experiment/{id}/status`, `GET /experiment/{id}/events` (SSE), `POST /experiment/{id}/feedback`, `GET /experiment/{id}/results`, `GET /experiments`. |
| `thelab/model_service/static/index.html` | New **Experiment** panel (Plan / Run / History tabs) + nav entry. |
| `thelab/model_service/static/app.js` | Experiment tab switching, start/SSE activity feed/feedback/history flows. |
| `thelab/model_service/static/styles.css` | Experiment tabs, stages, activity feed, history cards. |
| `tests/test_ide_cleaning.py` | Added categorical-NaN imputation-before-encoding test. |
| `tests/test_agent_mcp.py` | New: tool discovery, deterministic skills, sub-agent spawn, orchestration, job status, redacted activity logging (stdio transport). |
| `tests/test_ide_orchestrator.py` | New: EDA context, full orchestration, stage events, dataset rejection, factory. |
| `tests/test_ide_experiment.py` | New: run/status/SSE/feedback/results endpoints, validation errors, history. |

## What was implemented

1. **Unified experiment flow**: `POST /experiment/run` creates a persisted `Experiment` and queues an `experiment` job. The job runs `ExperimentOrchestrator.orchestrate()` (EDA → cleaning → try-all model selection → approved proposal + batch training), emitting stage events over SSE.
2. **Experiment state machine**: `pending → planning → cleaning → training → evaluating → completed/failed`, with `iterating` for feedback loops. Feedback starts a new orchestration iteration and preserves `previous_job_ids`.
3. **`agent_mcp` hardening**: activity logging goes through the `context_write_mcp` schema validation and secret-redaction path (canonical `/log` events), never raw SQLite writes.
4. **UI**: Experiment panel with Plan (goal + dataset + provider), Run (live stages + agent activity feed + best-run summary + feedback), and History (all experiments, click to re-open).

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 89 source files

.venv/bin/python -m pytest tests/test_ide_cleaning.py tests/test_agent_mcp.py tests/test_ide_orchestrator.py tests/test_ide_experiment.py -q
# 30 passed

.venv/bin/python -m pytest tests/ -q
# 443 passed, 1 skipped

PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py
# RQ1/RQ2/RQ3: PASS
```

## Manual check

```bash
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/ → Experiment panel:
# Plan tab → pick dataset + target + goal → Start experiment.
# Run tab → watch stage pipeline + agent activity stream; send feedback to iterate.
# History tab → click a past experiment to reopen it.
```

## Limitations / boundaries found

- The orchestrator uses the deterministic/mock provider by default; `ollama`/`openrouter` providers require the respective env configuration.
- Orchestration runs as a synchronous background job per stage; sub-agents execute in-process (no subprocess isolation yet — plan boundary noted for hardening).
- Existing Goal Launcher / Train / Proposals panels remain alongside the new Experiment panel; consolidating them is UI cleanup for a follow-up slice.
- Try-all and batch training remain deterministic; rejected runs inside a batch mark the experiment `partial` (a rejected validation stays a valid, traceable outcome).

## Final scope decision (thesis delivery week)

The two plan items above — **sub-agent subprocess isolation** and **panel
consolidation** — are formally **descoped** and recorded as documented
limitations (see `AGENTS.md` active scope and `docs/THESIS_MAP.md`). The
remaining pre-submission work is real-dataset hardening (cleaning policy,
model scale guards, progress/cancellation) and D1 demos; see
`docs/THESIS_MAP.md` for the 7-day checklist.
