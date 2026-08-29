# Phase 1 Plan — Dataset Upload + EDA Panel

> **Status:** binding  
> **Audience:** coding agent  
> **Authority:** Implements the first phase of `docs/P2_IDE_PLAN.md`. Implement only what is listed here.

## 1. Goal

Let the user upload a CSV dataset through the UI and immediately view deterministic EDA results. This phase establishes the upload/EDA foundation for later agentic phases.

## 2. Current state

- `thelab/eda/skills.py` exposes deterministic EDA functions over a `pd.DataFrame`.
- `thelab/mcp/eda_mcp.py` exposes the same skills as MCP tools with path validation.
- `thelab/model_service/app.py` serves the existing dashboard but has no upload or EDA endpoints.
- Datasets are currently referenced by existing fixture paths; there is no upload mechanism.

## 3. In scope

1. New `thelab/ide/` package with:
   - Dataset upload helper (`thelab/ide/datasets.py`).
   - EDA API helpers (`thelab/ide/eda_api.py`).
2. New HTTP endpoints in `thelab/model_service/app.py`:
   - `POST /datasets/upload`
   - `GET /datasets`
   - `GET /eda/{dataset_id}`
3. Frontend updates:
   - Add **Datasets** panel to sidebar.
   - Upload dropzone.
   - Dataset list.
   - EDA results view for selected dataset.
4. Tests:
   - `tests/test_ide_datasets.py`
   - `tests/test_ide_eda.py`
5. Docs:
   - `docs/P2_PHASE1_CONTEXT.md` after implementation.
   - Update `docs/ROADMAP.md` to mark Phase 1 done.

## 4. Out of scope

- Agent proposal creation/approval (Phase 2).
- Background job runner (Phase 3).
- Code sandbox (Phase 4).
- CSV viewer / charts (Phase 5).
- Bash terminal in the UI.
- Any write endpoint that does not require explicit user action.

## 5. Backend additions

### 5.1 `thelab/ide/datasets.py`

Responsibilities:
- Determine dataset storage root: `data/uploads/` (configurable via `THELAB_UPLOADS_DIR`).
- Sanitize uploaded filenames (basename only, no `..`, no hidden names, no path separators).
- Validate CSV: non-empty, parseable by `pandas.read_csv`, has at least one row and one column.
- Enforce max file size (default 10 MB).
- List datasets: uploaded files under `data/uploads/` plus fixture datasets under `data/fixtures/`.
- Resolve a `dataset_id` to a safe relative path that can be consumed by `thelab.eda` and `RunInputs`.

Functions:

```python
get_uploads_root() -> Path
sanitize_filename(name: str) -> str
validate_csv(path: Path) -> None
save_upload(file: BinaryIO, filename: str) -> dict[str, Any]
list_datasets() -> list[dict[str, Any]]
resolve_dataset_path(dataset_id: str) -> Path | None
```

`dataset_id` format: `uploads/<basename>` for uploaded files, `fixtures/<basename>` for fixtures. This keeps IDs stable and avoids leaking absolute paths.

### 5.2 `thelab/ide/eda_api.py`

Responsibilities:
- Load a dataset by `dataset_id`.
- Run all EDA skills from `thelab.eda`.
- Return a stable JSON structure.

Functions:

```python
run_eda(dataset_id: str, target: str | None = None) -> dict[str, Any]
```

Returned structure:

```json
{
  "ok": true,
  "data": {
    "dataset_id": "uploads/iris.csv",
    "rows": 150,
    "columns": 5,
    "column_names": ["sepal_length", ...],
    "feature_types": {...},
    "missing_profile": {...},
    "class_balance": {...},
    "correlation_hints": {...},
    "outlier_scan": {...},
    "leakage_suspects": {...}
  }
}
```

If `target` is provided, skills that use a target column receive it; otherwise target-aware skills are skipped or receive `None`.

### 5.3 Endpoints in `thelab/model_service/app.py`

#### `POST /datasets/upload`

Accepts `multipart/form-data` with a single `file` field.

Response on success:

```json
{
  "ok": true,
  "data": {
    "dataset_id": "uploads/iris.csv",
    "filename": "iris.csv",
    "rows": 150,
    "columns": 5
  }
}
```

Errors:
- Missing file → 400.
- Unsafe filename → 400.
- Non-CSV / unreadable CSV → 400.
- File too large → 413.

#### `GET /datasets`

Response:

```json
{
  "ok": true,
  "data": [
    {"dataset_id": "uploads/iris.csv", "filename": "iris.csv", "source": "upload", "rows": 150, "columns": 5},
    {"dataset_id": "fixtures/iris.csv", "filename": "iris.csv", "source": "fixture", "rows": 150, "columns": 5}
  ]
}
```

No absolute paths.

#### `GET /eda/{dataset_id}`

`dataset_id` is URL-encoded (e.g., `uploads%2Firis.csv`).

Optional query param: `target`.

Response: EDA result structure above.

Errors:
- Unsafe/unknown dataset_id → 404.
- Invalid target column → 400.

## 6. Frontend changes

### 6.1 `index.html`

- Add a **Datasets** nav button to the sidebar (above Models).
- Add a `#panel-datasets` section containing:
  - Upload dropzone (`#dataset-upload-zone`).
  - Dataset list table (`#datasets-table-body`).
  - EDA panel (`#eda-content`) with placeholder text when no dataset is selected.

### 6.2 `app.js`

- Add `loadDatasets()` to fetch `/datasets` and render the list.
- Add `uploadDataset(file)` to POST to `/datasets/upload`.
- Add `loadEda(datasetId, target)` to fetch `/eda/{dataset_id}` and render each skill section.
- Wire drag-and-drop on the dropzone.
- Add row selection in the dataset list; selected dataset triggers EDA load.
- Optionally allow user to input a target column for target-aware EDA.

### 6.3 `styles.css`

- Dropzone styles (dashed border, hover state).
- Dataset table row hover/active states (reuse existing table styles).
- EDA section cards for each skill.

## 7. Safety requirements

1. **Filename sanitization** — reject names with `/`, `\`, `..`, hidden names, or empty names.
2. **Storage containment** — uploaded files live only under `data/uploads/`.
3. **CSV validation** — parse the file with pandas before saving; reject non-tabular content.
4. **Size limit** — default 10 MB, configurable via `THELAB_MAX_UPLOAD_BYTES`.
5. **No absolute paths** in API responses; use `uploads/<basename>` and `fixtures/<basename>` IDs.
6. **Path resolution** — verify resolved path is inside `data/uploads/` or `data/fixtures/` before reading.
7. **Default bind stays `127.0.0.1`.**

## 8. Tests

### `tests/test_ide_datasets.py`

- Upload a valid CSV → returns `dataset_id`, file exists under `data/uploads/`.
- Upload missing file → 400.
- Upload unsafe filename (`../etc/passwd`) → 400.
- Upload non-CSV text → 400.
- Upload oversized file → 413.
- `GET /datasets` lists upload and fixtures.
- `GET /datasets` response contains no absolute paths.

### `tests/test_ide_eda.py`

- `GET /eda/uploads%2Firis.csv` returns all EDA skills.
- Invalid dataset_id → 404.
- Invalid target column → 400.
- EDA response has `ok: true` and expected top-level keys.

## 9. File map

```text
thelab/ide/__init__.py
thelab/ide/datasets.py
thelab/ide/eda_api.py

thelab/model_service/app.py        # add /datasets/upload, /datasets, /eda/*
thelab/model_service/static/index.html
thelab/model_service/static/app.js
thelab/model_service/static/styles.css

tests/test_ide_datasets.py
tests/test_ide_eda.py

docs/P2_PHASE1_PLAN.md             # this file
docs/P2_PHASE1_CONTEXT.md          # after implementation
docs/ROADMAP.md                    # mark Phase 1 done
data/uploads/                      # created at runtime, gitignored
```

## 10. Implementation order

1. Create `thelab/ide/datasets.py` + unit tests for sanitization/validation.
2. Create `thelab/ide/eda_api.py`.
3. Add endpoints to `thelab/model_service/app.py`.
4. Add UI panel + upload/EDA rendering in static files.
5. Add `tests/test_ide_datasets.py` and `tests/test_ide_eda.py`.
6. Run full verification.
7. Write `docs/P2_PHASE1_CONTEXT.md` and update `docs/ROADMAP.md`.

## 11. Acceptance criteria

- [ ] User can upload a CSV via drag-and-drop or file picker.
- [ ] Uploaded file is stored safely under `data/uploads/`.
- [ ] `GET /datasets` lists uploaded and fixture datasets without absolute paths.
- [ ] Selecting a dataset runs deterministic EDA and displays results.
- [ ] Invalid uploads are rejected with clear errors.
- [ ] `ruff check thelab tests scripts` passes.
- [ ] `mypy thelab` passes.
- [ ] `pytest tests/ -q` passes.
- [ ] `scripts/evaluate_thesis.py` still passes.
- [ ] `docs/P2_PHASE1_CONTEXT.md` written and `docs/ROADMAP.md` updated.

## 12. Non-goals reminder

- Do not add agent proposal endpoints.
- Do not add background job runner.
- Do not add sandboxed code execution.
- Do not add a terminal.
- Do not change the existing model training pipeline.
