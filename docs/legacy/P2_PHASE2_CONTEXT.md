# P2 Phase 2 Context — Agent Goal Launcher + Deterministic Training

> Second phase of the P2 Agentic ML IDE plan.

## Changed files

| File | Change |
|---|---|
| `thelab/agents/worker.py` | `WorkerAgent` now allows an empty `servers` list for deterministic-fallback-only usage. |
| `thelab/ide/worker_api.py` | New module: HTTP-facing wrapper for deterministic worker proposals. |
| `thelab/ide/proposals_api.py` | New module: approve, reject, and run proposal actions. |
| `thelab/ide/train_api.py` | New module: deterministic single-model training without agents. |
| `thelab/ide/cleaning.py` | New module: deterministic dataset cleaning (missing targets, categoricals, numeric imputation). |
| `thelab/model_service/app.py` | Added `POST /agent/worker`, `POST /proposals/{id}/{approve,reject,run}`, `POST /train`, `POST /datasets/{id}/clean`, `GET /models/available`. |
| `thelab/model_service/static/index.html` | Added **Goal launcher**, **Train model**, and **Clean dataset** UI; added status divs. |
| `thelab/model_service/static/styles.css` | Styles for forms, buttons, status banners, EDA toolbar. |
| `thelab/model_service/static/app.js` | Goal launcher, train panel, cleaning, proposal actions, improved error messages using `detail`. |
| `tests/test_ide_worker.py` | Tests for worker proposal endpoint. |
| `tests/test_ide_proposals_actions.py` | Tests for approve/reject/run endpoints. |
| `tests/test_ide_train.py` | Tests for deterministic train endpoint and available models. |
| `tests/test_ide_cleaning.py` | Tests for dataset cleaning endpoint. |
| `docs/P2_PHASE2_PLAN.md` | Binding plan for this phase. |

## What was implemented

1. **Agent goal launcher** (`POST /agent/worker`):
   - Accepts `dataset_id`, `target`, `goal`, optional `model_grid` and `seeds`.
   - Uses `WorkerAgent` with `MockProvider([])` and no MCP servers, triggering the deterministic fallback.
   - Persists a proposal under `proposals/`.

2. **Proposal actions**:
   - `POST /proposals/{id}/approve` writes an approval record with `"principal": "ui"`.
   - `POST /proposals/{id}/reject` writes a rejection record.
   - `POST /proposals/{id}/run` translates an approved proposal to a batch config and executes it.

3. **Deterministic training** (`POST /train`):
   - Accepts `dataset_id`, `target`, `model`, `seed`, `task_type`.
   - Calls `run_model` directly, no agent or approval required.
   - Useful for exploring dataset/model boundaries before using agents.

4. **Dataset cleaning** (`POST /datasets/{id}/clean`):
   - Drops rows with missing target values.
   - Drops empty columns.
   - One-hot encodes categorical features.
   - Imputes missing numeric values with median.
   - Creates a new `*_cleaned.csv` upload.

5. **Frontend**:
   - Goal launcher form with dataset/target/goal inputs.
   - Train model form with dataset/target/model/seed/task-type inputs.
   - Clean dataset button in the EDA panel.
   - Proposal cards show status and context-aware action buttons.
   - Prominent banner status messages for actions and cleaning.
   - Error messages now surface FastAPI `detail` responses.

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 74 source files

.venv/bin/python -m pytest tests/test_ide_worker.py tests/test_ide_proposals_actions.py tests/test_ide_train.py tests/test_ide_cleaning.py -q
# 32 passed
```

## Manual check

```bash
pkill -f "thelab-model-service"
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/
# Datasets panel → upload messy CSV → Run EDA → Clean dataset.
# Datasets panel → Train model: pick cleaned dataset, target, model, click Train.
# Datasets panel → Goal launcher: pick dataset, target, goal, click Propose, then Approve/Run.
```

## Limitations / boundaries found

- Raw datasets with missing target values or categorical features are rejected by the deterministic runner; use the **Clean dataset** button first.
- Cleaning is deterministic pandas preprocessing, not a Python sandbox or agent-generated code.
- Agent proposals use the deterministic fallback, not a live LLM, so rationale is EDA-based rather than LLM-reasoned.
- Training and batch runs are synchronous; large datasets block the request until finished.

## Next suggested slice

P2 Phase 3 — Pipeline diagram + execution view (background jobs / SSE), or continue hardening deterministic UI with preprocessing options.
