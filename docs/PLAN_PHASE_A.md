# Phase A Plan — Harden P0 Before Agent Connection

> Status: approved  
> Slices: 7–11  
> Goal: P0 is professor-ready, readable, and ready for the first agent.

---

## Why this phase exists

P0 was built fast. Before connecting real AI providers and global agents, the deterministic core must be solid, readable, and safe. This phase adds:

- Code quality tooling (ruff, mypy)
- Safety boundaries (path containment, input validation)
- Extensible model registry with new scikit-learn models
- Hardened dataset validation
- Batch runner for systematic experiments
- A README that a professor can read

No new MCP servers. No LLM providers. No cloud RAG.

---

## Slice map

| Slice | Name | Focus |
|---|---|---|
| 7 | Cleanup + Tooling + README Skeleton | Stale files, ruff/mypy config, root `AGENTS.md`, README structure |
| 8 | Safety Hardening | Path traversal, thesis evaluator fix, inference validation, db path redaction |
| 9 | Model Registry + New Models | `ModelRegistry`, `random_forest`, `svc`, `sgd_classifier`, optional probability |
| 10 | Dataset Validation Hardening | Refactor validators, add edge-case checks |
| 11 | Batch Runner + Final README | `thelab run batch`, JSON config, Markdown report, complete README |

---

## Cross-slice rules

- Every slice ends with `pytest tests/ -q` green.
- Every slice updates `docs/ROADMAP.md` status if it introduces new surfaces.
- Every slice writes or updates a slice context doc (e.g., `docs/SLICE7_CONTEXT.md`).
- No new MCP servers. No LLM providers. No cloud RAG.
- Approval required before any destructive change.

---

## Slice 7 — Cleanup + Tooling + README Skeleton

### Goal
Make the repo look like someone cares about it.

### Tasks

1. Delete stale files:
   - `docs/PRD_PO.md.save`
   - `thelab/run/.__init__.py.kate-swp`
2. Rename `docs/Slice 3 and Slice 4 Readiness Audit.md` → `docs/slice_3_and_4_readiness_audit.md`.
3. Update `.gitignore`:
   - `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `*.kate-swp`, `.dmypy.json`.
4. Create root `AGENTS.md` pointing to `docs/Agents.md` and `docs/CODEBASE_GUIDE.md`.
5. Add tooling config to `pyproject.toml`:
   - `[tool.ruff]` — line length 100, target Python 3.11
   - `[tool.ruff.lint]` — `E`, `F`, `I`, `UP`, `W`, `B`
   - `[tool.ruff.format]`
   - `[tool.mypy]` — strict but pragmatic; ignore missing imports for `sklearn`, `joblib`, `mcp`
   - Add `ruff`, `mypy` to `[project.optional-dependencies] dev`
6. Run `ruff check --fix` and `mypy`; fix reported issues without changing logic.
7. Minimal README refresh: structure, tone matching project voice, placeholder sections for CLI/UI/MCP/tests.

### Verification
- `ruff check thelab tests scripts` passes
- `mypy thelab` passes (or explicit baseline)
- `pytest tests/ -q` passes (1 expected failure fixed in slice 8)

### Deliverables
- Clean working tree of stale files
- Tooling config
- Root `AGENTS.md`
- Updated README skeleton

---

## Slice 8 — Safety Hardening

### Goal
The workspace must be a safe container.

### Tasks

1. Fix failing thesis evaluator:
   - Add self-bootstrapping in `scripts/evaluate_thesis.py` so subprocess finds `thelab`.
2. Enforce relative dataset/output paths in `thelab/run/inputs.py`:
   - Reject absolute paths and `..` traversal.
   - Raise clear `RejectedRunError` or `ValueError`.
3. Add path-traversal tests.
4. Validate inference inputs:
   - Finite-float checks in `_normalize_features`.
   - Reject missing columns explicitly.
5. Add inference validation tests.
6. Redact `db_path` in `ContextRepository.status()`.
7. Warn if `thelab-model-service --host` is not loopback.

### Verification
- `pytest tests/ -q` all green
- New path-safety and inference-validation tests pass

### Deliverables
- Safe CLI path handling
- Green test suite
- No absolute DB path leakage

---

## Slice 9 — Model Registry + New Models

### Goal
Make the ML layer extensible. One registry, one source of truth.

### Tasks

1. Create `thelab/run/model_registry.py`:
   - Maps model name → estimator class, default hyperparameters, `supports_probability` flag.
   - Entries: `logistic_regression`, `random_forest`, `svc`, `sgd_classifier`.
   - Probability is optional: models that can support it expose a flag; user can request probability-enabled variant or CLI flag.
2. Refactor `thelab/run/inputs.py` to use registry.
3. Refactor `thelab/run/preprocess.py` to build pipeline from registry.
4. Refactor `thelab/run/train.py`:
   - `FittedPipeline.predict_proba` handles models without probability support gracefully.
5. Refactor `thelab/run/artifacts.py`:
   - `training_config.json` and `model_card.md` are model-agnostic.
6. Deduplicate inference helpers:
   - Move `_feature_columns`, `_normalize_features` to `thelab/run/inference.py`.
   - Update HTTP service and MCP model registry to import them.
7. Add tests for each new model and for probability behavior.

### Verification
- `pytest tests/test_run.py`, `test_model_service.py`, `test_mcp.py` pass
- Each new model trains successfully

### Deliverables
- `ModelRegistry`
- `random_forest`, `svc`, `sgd_classifier` working
- Shared inference helpers
- Model-agnostic training config and model card

---

## Slice 10 — Dataset Validation Hardening

### Goal
Handle real-world dataset mess gracefully.

### Tasks

1. Refactor `thelab/run/validate.py`:
   - Split into small validator functions.
   - Use a registry or ordered sequence.
2. Add validation rules:
   - Target column exists
   - Target not among features
   - All features numeric
   - No duplicate column names
   - No constant features
   - At least one feature
   - No NaN/Inf in features
   - Stratified split feasible
   - Sensible target type for classification
3. Improve rejection messages.
4. Add parametrized edge-case tests.

### Verification
- New edge-case tests pass
- Full suite green

### Deliverables
- Refactored validators
- Edge-case coverage
- Clear rejection reasons

---

## Slice 11 — Batch Runner + Final README

### Goal
Run many experiments systematically and finish the README.

### Tasks

1. Create `thelab/run/batch.py`:
   - `BatchRunner` reads JSON config and calls `run_model` per entry.
   - Continues past failures.
   - Writes `batch_summary.json`.
2. Create `thelab run batch --config batch.json --output runs/` CLI.
3. Create human report generator:
   - `--report batch_report.md`
   - Summary table with status, metrics, failures.
4. Finalize README:
   - Quick start
   - CLI guide (`run model`, `run batch`, `context`, `thelab-model-service`)
   - UI guide
   - MCP guide
   - Running tests and thesis evaluator
   - Roadmap pointer
5. Add batch tests.

### Verification
- `pytest tests/ -q` all green
- Manual `thelab run batch --config examples/iris-batch.json` works

### Deliverables
- Batch runner
- JSON summary + Markdown report
- Complete README

---

## Post-phase A

After slice 11, pause for GitHub-readiness review:
- Clean working tree
- Final commit set
- Short release note
- Prepare for manual push

No automated push.
