# P2 Phase 5 Context — CSV Viewer + Visualizations

> Fifth and final phase of the P2 Agentic ML IDE plan.

## Changed files

| File | Change |
|---|---|
| `thelab/ide/viewer_api.py` | New module: `preview_dataset()` (bounded JSON rows + column types) and `compare_runs()` (metrics across completed runs). |
| `thelab/model_service/app.py` | Added `GET /datasets/{dataset_id}/preview` (limit capped at 1000, default 100) and `GET /runs/comparison` (registered **before** `/runs/{run_id}` to avoid route shadowing). |
| `thelab/model_service/static/index.html` | **Viewer** nav button; dataset viewer (selector, row limit, sortable table), histogram controls, correlation heatmap controls, model comparison table. |
| `thelab/model_service/static/app.js` | Preview fetch/render with client-side column sorting; SVG histogram renderer; EDA-driven SVG correlation heatmap; comparison table + metric bars. |
| `thelab/model_service/static/styles.css` | Viewer table (sticky headers, numeric right-align), heatmap/histogram SVG styles, metric bar rows. |
| `tests/test_ide_viewer.py` | Preview limits/NaN handling/safety, comparison inclusion/exclusion rules. |
| `docs/P2_PHASE5_PLAN.md` | Binding plan for this phase. |

## What was implemented

1. **Dataset preview endpoint** (`GET /datasets/{id:path}/preview?limit=N`):
   - Server-side bounded rows (default 100, hard cap 1000).
   - Column dtype classification (`numeric`/`text`), NaN → `null`, no absolute paths.
   - IDs resolved through the existing safe `resolve_dataset_path`.
2. **Runs comparison endpoint** (`GET /runs/comparison`):
   - Completed runs only, newest first, with model/target/task/seed/validation status and full test metrics.
3. **Viewer panel**:
   - Sortable, scrollable CSV table (click headers to sort asc/desc) with per-column type chips.
   - Histogram: client-side binned SVG for any numeric column of the loaded preview.
   - Correlation heatmap: renders top feature correlations as an inline SVG matrix (red negative / blue positive, hover titles), fed by the existing EDA endpoint — no new computation path.
4. **Model comparison**:
   - Table over `/runs/comparison` plus horizontal metric bars (accuracy or R² depending on task mix).

## Design decision: no CDN chart libraries

The P2 plan permitted CDN libs (`neiki-table`, ECharts). This phase implements
the viewer/charts in vanilla JS/SVG instead to keep the service fully
offline-first (consistent with the PRD's local-first principle): no network
fetches, no new dependencies, no build step.

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 84 source files

.venv/bin/python -m pytest tests/test_ide_viewer.py -q
# 8 passed

.venv/bin/python -m pytest tests/ -q
# 412 passed (full suite)

.venv/bin/python scripts/evaluate_thesis.py
# Overall: PASS (RQ1/RQ2/RQ3 PASS)
```

## Manual check

```bash
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/ → Viewer panel.
# Pick a dataset → Load → sort columns, render a histogram.
# Render heatmap for a dataset (+ optional target).
# Model comparison table + bars populate on page load.
```

## Limitations

- Sorting/pagination are client-side over the previewed window (max 1000 rows); larger datasets should be filtered upstream.
- Heatmap covers the top-8 correlated pairs returned by EDA, not the full matrix.

## Next suggested slice

P2 is complete. Suggested follow-ups: audit of P2 as a whole, or the still-planned D1 slice (demos and notebook) from the P1 plan.
