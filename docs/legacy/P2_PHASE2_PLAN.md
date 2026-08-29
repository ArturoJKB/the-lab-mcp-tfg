# P2 Phase 2 Plan — Agent Goal Launcher + Deterministic Training

> Authority: This document is binding for Phase 2 and supersedes informal chat proposals. Implement only what is listed here.

## Goal

Expose both agent-driven experiment proposals and a deterministic, agent-free "Train model" path so users can explore boundaries before relying on agents.

## In scope

1. **Backend**
   - `POST /agent/worker` — accept `{dataset_id, target, goal, model_grid?, seeds?}` and produce a deterministic proposal via `WorkerAgent.propose()` using the mock provider fallback.
   - `POST /proposals/{id}/approve` — write `proposals/<id>.approved.json` with `"principal": "ui"`.
   - `POST /proposals/{id}/reject` — write `proposals/<id>.rejected.json`.
   - `POST /proposals/{id}/run` — translate the approved proposal to a batch config and execute it synchronously.
   - `POST /train` — train a single model deterministically without proposals or agents.
   - `POST /datasets/{dataset_id}/clean` — create a cleaned CSV (drop missing targets, one-hot encode categoricals, impute numeric missing values).
   - `GET /models/available` — list registered model names for the train form.
   - Reuse existing `ProposalStore`, `ExperimentProposal`, batch runner, `run_model`, and pandas preprocessing.

2. **Frontend**
   - **Goal launcher** card: dataset, target, goal, optional model grid/seeds; creates a proposal.
   - **Train model** card: dataset, target, model select, seed, task type; trains directly.
   - **Clean dataset** button in the EDA panel: drops rows with missing target, encodes categoricals, imputes numeric missing values.
   - Proposal list cards show status and action buttons: **Approve**, **Reject**, **Run**.
   - Prominent banner status messages for proposal actions and cleaning.
   - Status indicators show actual backend error `detail` messages.

3. **Tests**
   - `tests/test_ide_worker.py`: worker endpoint creates a proposal.
   - `tests/test_ide_proposals_actions.py`: approve, reject, run endpoints.
   - `tests/test_ide_train.py`: deterministic train endpoint and available models.
   - `tests/test_ide_cleaning.py`: dataset cleaning endpoint.

## Out of scope

- Real-time LLM providers in the worker endpoint (use deterministic fallback).
- Background job queue / SSE (Phase 3).
- Sandbox or code generation (Phase 4).

## Safety boundaries

- Do not execute arbitrary code.
- `/train` and `/proposals/{id}/run` only invoke the existing deterministic `run_model` / batch runner.
- Paths are resolved through `thelab.ide.datasets` helpers; no absolute paths in requests.

## Verification

- `ruff check thelab tests scripts`
- `mypy thelab`
- `pytest tests/test_ide_worker.py tests/test_ide_proposals_actions.py tests/test_ide_train.py tests/test_ide_cleaning.py -q`
- Manual: open UI, upload a messy dataset, run EDA, click Clean dataset, then Train model. Also try goal launcher + approve/run flow.
