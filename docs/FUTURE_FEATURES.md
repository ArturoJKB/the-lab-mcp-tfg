# Future Features Backlog

This document captures ideas that improve The Lab but are not part of the current active slice. Items are grouped by theme and include a rough scope estimate.

## Exploratory / usability

### 1. `thelab inspect <dataset>`
Quickly profile a CSV without creating a full run. Shows row/column counts, types, target distribution, and validation-style red flags.

- **Status:** implemented in current slice.
- **Files:** `thelab/run/inspect.py`, `thelab/cli.py`.

### 2. `thelab run model --dry-run`
Train and validate in-memory, print metrics, but do not persist any artifacts. Useful for quick iteration.

- **Status:** implemented in current slice.
- **Files:** `thelab/run/runner.py`, `thelab/cli.py`.

### 3. `thelab predict --run-id <id>`
One-shot CLI prediction using an approved, persisted run. Removes the need to start the HTTP service for a single prediction.

- **Status:** implemented in current slice.
- **Files:** `thelab/run/prediction.py`, `thelab/cli.py`.

### 4. `thelab compare runs/`
Print a comparison table of completed runs with model, dataset, seed, and metrics.

- **Status:** implemented in current slice.
- **Files:** `thelab/run/compare.py`, `thelab/cli.py`.

### 5. `thelab run model --try-all`
Train every registered model on the same dataset/target/seed and print a comparison table. Defaults to dry-run so exploratory runs do not pollute `runs/`.

- **Status:** implemented in current slice.
- **Files:** `thelab/run/runner.py`, `thelab/cli.py`.

### 6. Python / Jupyter API
Expose the runner through a small, importable API (`thelab.quick`) so users can experiment in notebooks while still benefiting from deterministic runs.

- **Status:** implemented in current slice.
- **Files:** `thelab/quick.py`, `docs/PYTHON_API.md`, `examples/notebooks/01_quick_start.ipynb`.

### 7. `thelab sketch` interactive mode
A lightweight TUI or interactive prompt that walks through: pick dataset, pick target, preview profile, try models, and optionally persist the best one. This is the most exploratory-friendly option but also the highest effort.

- **Status:** future.
- **Value:** closes the gap almost completely for non-technical users.
- **Complexity:** medium-high (requires a TUI library or multi-step prompt loop).

## Hardening

- **Hash-verified model loading:** verify `model.joblib` hash before `joblib.load()` to mitigate pickle deserialization risks.
- **Subprocess sandbox for predictions:** run `predict` inside a restricted subprocess.
- **Context foreign keys:** already enabled via `PRAGMA foreign_keys = ON`.

## Extensibility

- **Custom estimator registration:** allow users to register new estimators via a config file without editing `model_registry.py`.
- **Hyperparameter overrides in batch config:** support per-entry `params` in batch JSON.
- **Notebook artifact tracking:** index `.ipynb` files in the context store or workspace MCP.

## Integration

- **First LLM provider / agent slice (P1):** connect a real AI provider or autonomous agent that can call the MCP tools.
- **Agent-readable run summaries:** generate a concise natural-language summary of each run for agent context windows.
