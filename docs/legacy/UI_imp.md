# Initiation Prompt — UI v2 Dashboard (Slice U1)

You are the coding agent assigned to implement **Slice U1: UI v2 dashboard** for The Lab.

## Read first (in order)

1. `docs/SLICEU1_PLAN.md` — binding scope for this slice.
2. `docs/P1_PLAN.md` §U1 — original UI vision (do not implement everything; use it for context).
3. `docs/SLICE5_PLAN.md` and `docs/SLICE6_PLAN.md` — existing dashboard and agent-panel constraints.
4. `thelab/model_service/app.py` — current FastAPI backend.
5. `thelab/model_service/static/index.html`, `app.js`, `styles.css` — current frontend.
6. `docs/B1_CLI_RECREATION.md` and `benchmarks/b1/benchmark_manifest.json` (if available) — understand B1 output shape.
7. `tests/test_model_service.py` and `tests/test_model_service_ui.py` — test patterns.

## What to implement

Implement **only** what is listed in `docs/SLICEU1_PLAN.md`:

1. Add backend endpoints in `thelab/model_service/app.py`:
   - `GET /benchmarks`
   - `GET /proposals`
   - `GET /proposals/{proposal_id}`
   - `GET /agent-sessions`

2. Update the frontend in `thelab/model_service/static/`:
   - Replace top tabs with a left sidebar.
   - Add a **Benchmarks** panel.
   - Add a **Proposals** panel.
   - Add an **Agent Sessions** panel.
   - Improve the **Predict** form with labeled feature inputs.
   - Apply CSS design tokens and polish (cards, loading/empty states).

3. Add tests in `tests/test_model_service_ui.py`.

4. Write `docs/SLICEU1_CONTEXT.md` and update `docs/ROADMAP.md` to mark U1 `done`.

## Hard constraints

- **No new UI server** — extend the existing `thelab-model-service` FastAPI app.
- **No frontend frameworks or build steps** — vanilla HTML/CSS/JS only.
- **No autonomous writes** — the UI is read-only. Do not add buttons that train, approve, reject, delete, or run batches.
- **Path safety** — reuse `safe_run_dir`, allowlists, and basename-only patterns from existing endpoints.
- **No absolute filesystem paths** in API responses or UI.

## Verification

Before finishing, run:

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_model_service_ui.py tests/test_model_service.py -q
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/evaluate_thesis.py
```

All must pass.

## Manual check

```bash
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/
# Verify sidebar navigation, benchmarks panel, proposals browser, agent sessions, and improved predict form.
```

## Stop condition

Stop when the acceptance checklist in `docs/SLICEU1_PLAN.md` is complete and all tests pass. Do not start D1 or any other slice.
