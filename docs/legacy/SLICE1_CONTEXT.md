# Slice 1 Context Handoff — The Lab Data-to-Model Factory

> Last updated: 2026-08-09
> Status: Slice 1 implemented + audit remediation complete (including artifact hash integrity and stratified-split feasibility). Slice 2 not started.

## What exists

A local, deterministic CLI pipeline that turns a tabular CSV into a trained logistic-regression model plus run artifacts.

Primary command:

```bash
thelab run model \
  --dataset data/fixtures/iris.csv \
  --target species \
  --model logistic_regression \
  --seed 42 \
  --output runs/
```

## File map

```text
thelab/
  cli.py                 # argparse entry point: thelab run model
  version.py             # dependency version reporting
  contracts/             # Pydantic models (Slice 0)
  workspace/             # hashing + path helpers (Slice 0)
  run/
    __init__.py
    runner.py            # orchestration + real-time events
    inputs.py            # CLI input normalization/validation
    profile.py           # dataset profiling
    contract.py          # dataset contract
    preprocess.py        # sklearn Pipeline builder
    train.py             # train/eval + FittedPipeline wrapper
    validate.py          # validation checks
    artifacts.py         # artifact persistence + manifest
    errors.py            # RejectedRunError

tests/
  test_contracts.py      # Slice 0 contract tests
  test_workspace.py      # Slice 0 workspace tests
  test_run.py            # Slice 1 tests (18 tests)

docs/
  PRD_P0.md              # binding PRD
  Agents.md              # agent instructions
  SLICE1_CONTEXT.md      # this file
```

## Dependencies

Declared in `pyproject.toml`:

- `pydantic>=2`
- `pandas>=2`
- `scikit-learn>=1.4`

Transitive/runtime: `numpy`, `joblib`, `scipy`.

Install: `. .venv/bin/activate && pip install -e ".[dev]"`

## How to verify

```bash
# Full test suite
. .venv/bin/activate && python -m pytest tests/ -q

# Documented run
thelab run model --dataset data/fixtures/iris.csv --target species --model logistic_regression --seed 42 --output runs/
```

## Key design decisions

1. **Events are real-time.** `events.jsonl` is created at run start. Intermediate events (`data_validated`, `validation_completed`, `training_completed`) are emitted when those steps actually happen. Final event is emitted before `finished_at` is captured, so every timestamp is inside `[started_at, finished_at]`.

2. **Rejected vs failed.**
   - `rejected`: invalid input/schema/target/validation (raises `RejectedRunError`).
   - `failed`: unexpected runtime/infrastructure errors.
   - Rejected runs persist inputs, data_profile, validation_report, manifest, and events. They do **not** create `model.joblib`, `model_card.md`, training_config/metrics, or model ArtifactRefs.

3. **Manifest references every produced artifact**, including `events.jsonl`. `ArtifactRef.content_hash` is the SHA-256 of the exact persisted artifact bytes (`hash_file(path)` for JSON artifacts; byte hashing for binary/text artifacts). `manifest.json` itself is excluded from `artifact_refs` to avoid a circular content-hash; this is documented in `artifacts.py`.

4. **Validation rules (Slice 1):**
   - Target column must exist.
   - No missing values in target or feature columns.
   - All feature columns must be numeric.
   - Dataset must support a stratified split with sklearn's float `test_size=0.2` semantics:
     - `n_test = ceil(0.2 * n_rows)`; `n_train = n_rows - n_test`.
     - Rejected if any class would be unable to place at least one sample in both train and test partitions (e.g., 6 rows / 3 classes / 2 per class is rejected).
   - `validation_report.json` and `training_config.json` use the actual train/test counts returned by `train_test_split`.

5. **Model artifact.** `model.joblib` contains a `FittedPipeline` (sklearn `Pipeline` + `LabelEncoder`) so `predict()` returns string labels.

## Known limitations

- Only `logistic_regression` is supported; other `--model` values are rejected.
- Only numeric features are supported for Slice 1.
- No AutoML, hyperparameter search, or feature engineering.
- No MCP servers, model serving endpoint, `/log` command, SQLite, UI, or agent panels yet.
- sklearn emits an informative warning when predicting from a plain list instead of a DataFrame; predictions are still correct.

## Reproducibility note

Running the documented command twice with the same seed produces different `run_id`s and timestamps, but identical metrics for the Iris fixture (verified).

## Next suggested work

**Slice 2 — MCP reuse:** implement `data_catalog_mcp` and `model_registry_mcp` plus an independent MCP test client, as described in `docs/PRD_P0.md`.
