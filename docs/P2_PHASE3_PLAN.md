# P2 Phase 3 Plan — Pipeline Diagram + Execution View

> Authority: Binding plan for Phase 3 of `docs/P2_IDE_PLAN.md`. Implement only what is listed here.

## Goal

Visualize the ML workflow and show live execution status for training/batch jobs.

## In scope

1. **Backend**
   - `thelab/ide/jobs.py`: in-memory job manager + persisted summaries under `.thelab/jobs/`.
   - Job types: `train`, `batch`.
   - `POST /jobs`: submit a job, return `{job_id, status}`.
   - `GET /jobs/{job_id}`: status, events, result.
   - `GET /jobs/{job_id}/events`: SSE stream of job events.
   - Reuse existing `train_model` and `run_proposal`; run them in `asyncio.to_thread`.

2. **Frontend**
   - New **Pipeline** sidebar panel.
   - Pipeline diagram: Upload → EDA → Propose → Approve → Train → Validate → Evaluate.
   - Per-step status indicators.
   - Live log tail from SSE.
   - "Run in background" toggle on Train model and proposal Run buttons.

3. **Tests**
   - `tests/test_ide_jobs.py`: submit, status, events, SSE.

## Out of scope

- Real-time LLM providers.
- Code sandbox (Phase 4).
- CSV viewer / charts (Phase 5).

## Safety boundaries

- Only `train` and `batch` job types; no arbitrary code execution.
- Payloads validated through existing `train_model` / `run_proposal` paths.
- No absolute paths in responses.
- Default bind remains `127.0.0.1`.

## Verification

- `ruff check thelab tests scripts`
- `mypy thelab`
- `pytest tests/test_ide_jobs.py -q`
- Full suite green.
