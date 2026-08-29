# P2 Phase 3 Context — Pipeline Diagram + Execution View

> Third phase of the P2 Agentic ML IDE plan.

## Changed files

| File | Change |
|---|---|
| `thelab/ide/jobs.py` | New module: async `JobManager`, `Job`, `JobEvent`; background execution of `train` and `batch` jobs via `asyncio.to_thread`; persisted summaries under `.thelab/jobs/`. |
| `thelab/model_service/app.py` | Added `POST /jobs`, `GET /jobs`, `GET /jobs/{job_id}`, `GET /jobs/{job_id}/events` (SSE). |
| `thelab/model_service/static/index.html` | Added **Pipeline** nav button; pipeline diagram (Upload → EDA → Propose → Approve → Train → Validate → Evaluate) with per-step status; active-jobs list; live job log panel; "Run in background" checkbox on the train form. |
| `thelab/model_service/static/app.js` | Job submission helper, jobs list rendering, SSE log tail (`EventSource`) with replay, pipeline status updater, proposal Run action now queues a background batch job. |
| `thelab/model_service/static/styles.css` | Pipeline node/status styles, job cards, monospace live log, checkbox styling. |
| `tests/test_ide_jobs.py` | Tests for submission, lifecycle, SSE stream, validation errors, 404s. |
| `docs/P2_PHASE3_PLAN.md` | Binding plan for this phase. |

## What was implemented

1. **Background jobs** (`POST /jobs`):
   - Types: `train` (single model via existing `train_model`) and `batch` (approved proposal via existing `run_proposal`).
   - Executed off the request thread with `asyncio.to_thread`; UI stays responsive.
   - Each job emits timestamped events; final state persisted to `.thelab/jobs/<job_id>.json`.
2. **Status + SSE**:
   - `GET /jobs/{job_id}` returns full status, events, result.
   - `GET /jobs/{job_id}/events` streams server-sent events; subscribers replay history and stop after the terminal `done` event.
3. **Pipeline view**:
   - Seven-step diagram whose statuses derive from real workspace state (datasets present, EDA rendered, proposals exist/approved, approved models, running jobs).
4. **UI integration**:
   - Train form "Run in background" toggle submits via `/jobs` and opens the live log.
   - Proposal **Run** buttons queue background batch jobs instead of blocking the request.

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 84 source files

.venv/bin/python -m pytest tests/test_ide_jobs.py tests/test_model_service.py -q
# all passed

.venv/bin/python -m pytest tests/ -q
# 412 passed (full suite)
```

## Manual check

```bash
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/ → Pipeline panel.
# Train model card → check "Run in background" → Train.
# Live log tails the job; Active jobs list updates; pipeline Train step shows running/completed.
```

## Limitations

- Job state is in-memory; persisted summaries under `.thelab/jobs/` are for audit only (not reloaded on restart).
- Only `train` and `batch` job types; EDA remains synchronous (fast).

## Next suggested slice

P2 Phase 4 — Code sandbox + advanced agent iteration.
