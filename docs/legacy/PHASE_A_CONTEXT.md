# Phase A Context — Harden P0 Before Agent Connection

> Slices 7–11 of the P0 roadmap. Completed after the previous session was interrupted.

---

## Slice 7 — Cleanup + Tooling + README Skeleton

**Goal:** Make the repo look professor-ready.

**What changed:**
- Removed stale files (`docs/PRD_PO.md.save`, `thelab/run/.__init__.py.kate-swp`, renamed audit doc).
- Updated `.gitignore` with tool caches and editor swap files.
- Created root `AGENTS.md` pointing to project docs.
- Added `ruff` and `mypy` config to `pyproject.toml` under `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]`, `[tool.mypy]`, and `[project.optional-dependencies] dev`.
- Fixed all `ruff` findings and established a clean `mypy` baseline (`python_version = "3.14"`).
- Refreshed `README.md` with a P0-closeout skeleton.

**Verification:** `ruff check thelab tests scripts` passes; `mypy thelab` passes.

---

## Slice 8 — Safety Hardening

**Goal:** The workspace must be a safe container.

**What changed:**
- `thelab/run/inputs.py` now rejects absolute dataset/output paths and `..` traversal; `run_model()` normalizes absolute paths that fall under the workspace root for programmatic callers.
- Added path-traversal tests in `tests/test_run.py`.
- Created `thelab/run/inference.py` with shared `feature_columns()` and `normalize_features()` helpers. Helpers validate finite floats, numeric values, missing columns, and row length.
- Updated `thelab/model_service/app.py` and `thelab/mcp/model_registry_mcp.py` to import the shared inference helpers.
- Added inference validation tests in `tests/test_model_service.py`.
- `ContextRepository.status()` now redacts `db_path` to the basename.
- `thelab-model-service --host` warns when bound to a non-loopback address.
- `scripts/evaluate_thesis.py` bootstraps `PYTHONPATH` for the subprocess MCP server.
- `task_spec.json` is now referenced in `manifest.json` artifact refs, fixing the previous test failure.

**Verification:** `pytest tests/ -q` all green; thesis evaluator passes RQ1–RQ3.

---

## Slice 9 — Model Registry + New Models

**Goal:** Make the ML layer extensible.

**What changed:**
- Created `thelab/run/model_registry.py` with `ModelRegistry`, `ModelEntry`, and a global `MODEL_REGISTRY`.
- Registered `logistic_regression`, `random_forest`, `svc`, and `sgd_classifier` with default hyperparameters and `supports_probability` flags.
- Probability-enabled variants are supported via the `_probability` suffix (e.g. `svc_probability`).
- Refactored `thelab/run/inputs.py`, `preprocess.py`, `train.py`, `artifacts.py`, and `runner.py` to use the registry.
- `FittedPipeline.predict_proba()` raises a clear error for models without probability support.
- Model card generation is now model-agnostic and reads estimator metadata from `training_config.json`.
- Added tests for each new model and for probability behavior in `tests/test_run.py`.

**Verification:** All model variants train successfully; `pytest tests/test_run.py` passes.

---

## Slice 10 — Dataset Validation Hardening

**Goal:** Handle real-world dataset mess gracefully.

**What changed:**
- Refactored `thelab/run/validate.py` into small validator functions with a `DEFAULT_VALIDATORS` sequence.
- Added validation rules: target exists, target not among features, all features numeric, no duplicate column names, no constant features, at least one feature, no NaN/Inf in features, sensible target type for classification, stratified split feasibility.
- Duplicate column detection is enforced in `thelab/run/profile.py` before pandas mangles names.
- Added `tests/test_validate.py` with parametrized edge-case tests.

**Verification:** Edge-case tests pass; full suite green.

---

## Slice 11 — Batch Runner + Final README

**Goal:** Run many experiments systematically and finish the README.

**What changed:**
- Created `thelab/run/batch.py` with `BatchRunner`, `BatchEntry`, `BatchResult`, `write_markdown_report()`.
- Batch runner loads JSON configs, continues past failures, and writes `batch_summary.json`.
- Added `thelab run batch --config <path> --output <dir> --report <path>` CLI.
- Created `examples/iris.csv`, `examples/wine.csv`, `examples/breast_cancer.csv`, and batch configs:
  - `examples/iris-batch.json`
  - `examples/wine-batch.json`
  - `examples/breast-cancer-batch.json`
  - `examples/multi-dataset-batch.json`
- Added `tests/test_batch.py` covering config loading, execution, summary writing, failure continuation, report generation, and CLI invocation.
- Added `tests/test_examples.py` verifying all shipped datasets and batch configs train successfully.
- Rewrote `README.md` to be short and concise; created `docs/CLI_GUIDE.md` with full command reference, supported models, batch config format, examples, and troubleshooting.

**Verification:** `pytest tests/test_batch.py` and `pytest tests/test_examples.py` pass; manual `thelab run batch --config examples/multi-dataset-batch.json --output demo_runs --report demo_runs/demo_report.md` works.

---

## Final verification

```bash
ruff check thelab tests scripts   # passes
mypy thelab                       # passes
pytest tests/ -q                  # 199 passed
python scripts/evaluate_thesis.py # RQ1–RQ3 PASS
thelab run batch --config examples/multi-dataset-batch.json --output demo_runs --report demo_runs/demo_report.md
```

## Post-implementation /log and /audit

- `/log` captured Phase A completion in a global note (`~/.claude/notes/`).
- `/audit` (gsd-code-review) produced `PHASE_A_REVIEW.md` with 1 critical, 5 warnings, 7 info findings.
- Critical probability-variant crash was fixed; all probability variants now train and predict successfully.
- Addressed warnings: `workspace_root` default factory, empty CSV handling, generic prediction-error messages, symlink path containment.
- Addressed info items: SQLite foreign keys enabled, dead branch removed, MCP tool schemas forbid additional properties.

## Limitations / next suggested slice

- SVC probability uses the deprecated `probability=True` parameter; future slices could migrate to `CalibratedClassifierCV`.
- Batch runner does not yet support hyperparameter overrides per entry; that is a natural future enhancement.
- Phase A focused on hardening P0; the next milestone should connect the first real AI provider/agent only after a GitHub-readiness review.
