# Slice 5 Context Handoff — Minimal Local UI on Model Service

> Last updated: 2026-08-10  
> Status: Slice 5 implemented and verified. Slice 6 not started.

## What exists

A minimal human-facing dashboard served by the existing `thelab-model-service` FastAPI app. The UI is vanilla HTML/CSS/JS with no build step, no separate server, and no context/agent integration.

- `GET /` serves `thelab/model_service/static/index.html`.
- `GET /static/*` serves `app.js` and `styles.css`.
- Read-only backend endpoints expose run summaries and allowlisted artifacts:
  - `GET /runs/{run_id}`
  - `GET /runs/{run_id}/artifacts`
  - `GET /runs/{run_id}/artifacts/{artifact_name}`
- Existing `/health`, `/models`, and `/predict` endpoints remain unchanged.

## File map

```text
thelab/
  model_service/
    app.py                 # added run/artifact routes; serves static UI
    static/
      index.html           # single-page dashboard
      app.js               # vanilla JS panel logic
      styles.css           # minimal styles

docs/
  SLICE5_PLAN.md           # implementation plan
  SLICE5_CONTEXT.md        # this file
  ROADMAP.md               # Slice 5 marked done

tests/
  test_model_service.py    # existing inference tests (unchanged)
  test_model_service_ui.py # new UI and artifact-safety tests
```

## Dashboard panels

| Panel | Data source | Behavior |
|---|---|---|
| Status | `GET /health` + `GET /models` count | Shows service status and number of approved models. No absolute paths. |
| Approved models | `GET /models` | Selectable table of completed + approved runs. |
| Run / metrics | `GET /runs/{run_id}` | Shows model, target, feature columns, and metrics summary. |
| Artifacts | `GET /runs/{run_id}/artifacts` + `GET /runs/{run_id}/artifacts/{name}` | Lists allowlisted artifacts; renders JSON or `model_card.md` text. |
| Predict | `GET /runs/{run_id}` then `POST /predict` | Builds number inputs from feature columns and shows predictions. |

## Artifact allowlist

Only these basenames are returned by the artifact API:

- `manifest.json`
- `metrics.json`
- `data_profile.json`
- `inputs.json`
- `validation_report.json`
- `training_config.json`
- `dataset_contract.json`
- `model_card.md`
- `task_spec.json`

Excluded: `model.joblib`, any other file, nested paths, and parent-relative names.

## Safety guarantees

- All run access uses `thelab.mcp.common.safe_run_dir` (rejects `..`, separators, hidden names).
- Artifact names are basename-only and allowlist-restricted.
- Only completed + approved runs are selectable for prediction and detailed metrics.
- No write/mutate endpoints are added.
- No absolute filesystem paths are returned in API responses or rendered HTML.
- Default bind remains `127.0.0.1`.

## Usage

First produce an approved run:

```bash
thelab run model --dataset data/iris.csv --target species --model logistic_regression --seed 42
```

Then start the service and open `http://127.0.0.1:8000/`:

```bash
thelab-model-service --port 8000
```

## How to verify

```bash
# Full test suite
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q
```

Expected result: `151 passed, 16 warnings`.

Manual smoke:

```bash
# Ensure at least one approved run exists under runs/ or THELAB_RUNS_ROOT
thelab-model-service --port 8000

# In another terminal:
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ | head
curl -s http://127.0.0.1:8000/models
curl -s http://127.0.0.1:8000/static/app.js | head
```

## Dependencies

No new dependencies beyond the existing FastAPI/uvicorn stack. The UI is served with `fastapi.staticfiles.StaticFiles` and `fastapi.responses.HTMLResponse`.

## Key design decisions

1. **Same process.** The UI is served by `thelab-model-service`; no separate UI server.
2. **Vanilla front end.** No React/Vue/Svelte, no npm, no build step.
3. **Read-only API additions.** New endpoints only list and fetch; they never write or train.
4. **No context integration in Slice 5.** Context MCP/CLI features are left for Slice 6.
5. **Path-safe artifact access.** Basename + allowlist only, with traversal rejected by `safe_run_dir` and endpoint validation.

## Known limitations

- Single-page dashboard only; no client-side routing.
- No Playwright/browser E2E tests (TestClient/httpx only).
- No real-time updates; panels refresh on user selection.
- Prediction form supports numeric features only (matches current model service contract).

## Next suggested work

See `docs/ROADMAP.md`.

- **Slice 6: Agent panels and evaluation** — read-only Coding/Logger Agent panel, Research/Copilot panel, and thesis evaluation protocol.
