# P2 Phase 5 Plan — CSV Viewer + Visualizations

> Authority: Binding plan for Phase 5 of `docs/P2_IDE_PLAN.md`. Implement only what is listed here.

## Goal

Rich data exploration and model comparison without leaving the UI.

## In scope

1. **Backend**
   - `thelab/ide/viewer_api.py`:
     - `preview_dataset(dataset_id, limit)` — return columns, rows, and totals as JSON.
     - `compare_runs()` — metrics table across completed runs.
   - New HTTP endpoints in `thelab/model_service/app.py`:
     - `GET /datasets/{dataset_id}/preview?limit=N`
     - `GET /runs/comparison`

2. **Frontend** (vanilla JS/CSS/SVG — no CDN dependency, keeping the app offline-first)
   - New **Viewer** sidebar panel:
     - Dataset selector reusing `/datasets`.
     - Sortable, paginated CSV table from the preview endpoint.
     - Per-column type/count summary.
   - Charts rendered as inline SVG/CSS:
     - Correlation heatmap built from the EDA endpoint data.
     - Model metric bars built from `/models`.
     - Feature distribution histogram per numeric column (computed client-side from preview rows).

3. **Tests**
   - `tests/test_ide_viewer.py`: preview endpoint (limits, safety, errors), comparison endpoint.

## Out of scope

- Export beyond what already exists.
- Editing datasets from the viewer.
- Any new dependencies (no CDN chart/table libraries; keep local-first).

## Safety boundaries

- Dataset IDs resolved through `thelab.ide.datasets.resolve_dataset_path`.
- Row limits enforced server-side (default 100, max 1000).
- No absolute paths in responses.

## Verification

- `ruff check thelab tests scripts`
- `mypy thelab`
- `pytest tests/test_ide_viewer.py -q`
- Full suite green + `scripts/evaluate_thesis.py`.
