# P2 Phase 1 Context — Dataset Upload + EDA Panel

> First phase of the P2 Agentic ML IDE plan.

## Changed files

| File | Change |
|---|---|
| `thelab/ide/__init__.py` | New IDE package marker. |
| `thelab/ide/datasets.py` | Dataset upload, filename sanitization, CSV validation, dataset listing, safe path resolution. |
| `thelab/ide/eda_api.py` | HTTP-facing wrapper that runs all deterministic EDA skills. |
| `thelab/model_service/app.py` | Added `POST /datasets/upload`, `GET /datasets`, `GET /eda/{dataset_id:path}`. |
| `thelab/model_service/static/index.html` | Added **Datasets** sidebar nav and panels for upload, dataset list, and EDA; grouped sidebar items. |
| `thelab/model_service/static/styles.css` | Upload dropzone, EDA section cards, metric grid styles, sticky headers, scrollable tables, toggle buttons, warning banners. |
| `thelab/model_service/static/app.js` | Upload drag-and-drop with loading/errors, dataset list rendering, human-friendly EDA fetch/render with capped tables and toggles. |
| `tests/test_ide_datasets.py` | Tests for upload, validation, listing, path safety. |
| `tests/test_ide_eda.py` | Tests for EDA endpoint, target handling, error cases. |
| `.gitignore` | Added `data/uploads/` to ignore uploaded datasets. |
| `docs/P2_IDE_PLAN.md` | High-level P2 plan document. |
| `docs/P2_PHASE1_PLAN.md` | Binding plan for this phase. |
| `docs/ROADMAP.md` | Marked P2 Phase 1 `done`; added remaining P2 phases as `planned`. |

## What was implemented

1. **Dataset upload endpoint** (`POST /datasets/upload`):
   - Accepts `multipart/form-data` CSV uploads.
   - Stores files under `data/uploads/` (configurable via `THELAB_UPLOADS_DIR`).
   - Sanitizes filenames, rejects traversal/hidden names, CSV-only, size cap (default 100 MB).
   - Handles name collisions with numeric suffixes.
   - Returns stable `dataset_id` of the form `uploads/<basename>`.

2. **Dataset list endpoint** (`GET /datasets`):
   - Returns uploaded datasets plus fixture datasets under `data/fixtures/`.
   - No absolute paths in responses.

3. **EDA endpoint** (`GET /eda/{dataset_id:path}`):
   - Runs the full deterministic EDA skill pack from `thelab.eda`.
   - Optional `target` query parameter for target-aware skills.
   - Returns JSON with feature types, missing profile, class balance, correlations, outliers, leakage suspects.

4. **Frontend Datasets panel**:
   - Drag-and-drop / click-to-browse upload zone with loading state and clear size/error messages.
   - Dataset list table.
   - EDA results view with optional target input.
   - Human-friendly EDA cards (tables, metric grids) instead of raw JSON.
   - Extreme-case handling: capped tables with "Show more / Show less" toggles, scrollable wrappers, sticky headers, and a high-cardinality target warning in class balance.

5. **Sidebar grouping**:
   - "Workflow" group: Models, Benchmarks, Proposals.
   - "Agents" group: Agent Sessions, Research Agent, Coding Agent.

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 71 source files

.venv/bin/python -m pytest tests/ -q
# 368 passed

.venv/bin/python scripts/evaluate_thesis.py
# Overall: PASS (RQ1/RQ2/RQ3 PASS)
```

## Manual check

```bash
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/
# Use the Datasets panel to upload a CSV, view the dataset list, and run EDA.
```

## Limitations

- Only CSV uploads are supported.
- No CSV viewer or charts yet (Phase 5).
- No agent integration yet (Phase 2).
- Uploaded datasets are stored locally and not versioned.

## Next suggested slice

P2 Phase 2 — Agent goal launcher + proposals.
