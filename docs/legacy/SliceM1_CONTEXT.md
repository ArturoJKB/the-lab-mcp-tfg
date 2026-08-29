# Slice M1 — Task-type generalization (classification + regression)

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §2 Stage 1 — M1  
**Scope:** Make the factory task-general across validation, training, metrics, artifacts, compare, batch, MCP, CLI, and UI.

---

## Changed files

| File | Change |
|---|---|
| `thelab/run/task_type.py` | New deterministic task-type inference (`auto` → `classification`/`regression`). |
| `thelab/run/model_registry.py` | `ModelEntry` gains `task_type`; registers `linear_regression`, `ridge`, `random_forest_regressor`, `hist_gradient_boosting_regressor`, `hist_gradient_boosting`. Rejects `*_probability` on regression models. |
| `thelab/run/inputs.py` | Adds `--task-type auto|classification|regression` CLI argument defaulting to `auto`. |
| `thelab/run/runner.py` | Resolves task type, validates model/task compatibility, persists `task_type` in `inputs.json`, `training_config.json`, and manifest; task-appropriate print output. |
| `thelab/run/validate.py` | Task-aware validators: regression requires numeric target with positive variance; stratified-split feasibility checked for classification only. |
| `thelab/run/train.py` | Branches on task type: regression uses shuffle split and RMSE/MAE/R²; classification keeps stratified split and accuracy/F1. |
| `thelab/run/artifacts.py` | `RunManifest` includes `task_type`; model card renders task-appropriate metrics and split description. |
| `thelab/run/compare.py` | Groups comparison table by task type with correct metric columns. |
| `thelab/run/batch.py` | Batch entries accept `task_type`; report includes task type and task-appropriate metrics. |
| `thelab/run/preprocess.py` | Uses updated `MODEL_REGISTRY.build_estimator`. |
| `thelab/quick.py` | Python API accepts `task_type`; `compare()`/experiment pass it through. |
| `thelab/cli.py` | `--task-type` exposed on `thelab run model`; `--try-all` prints status column and task-agnostic metrics. |
| `thelab/contracts/run_manifest.py` | Adds `task_type: Literal["classification", "regression"] \| None`. |
| `thelab/contracts/__init__.py` | Re-exports `TaskType`. |
| `thelab/mcp/model_registry_mcp.py` | `list_models` returns `task_type` per model. |
| `thelab/model_service/app.py` | `/models`, `/runs/*`, `/agent/coding/*` include `task_type` and regression metrics. |
| `thelab/model_service/static/index.html` | Models table shows "Task type" column. |
| `thelab/model_service/static/app.js` | Models/metrics panels render regression metrics (RMSE/R2) when `task_type == "regression"`. |
| `tests/test_m1_task_types.py` | New tests: inference edge cases, regression end-to-end, determinism, probability-suffix rejection, task mismatch rejection, compare grouping, MCP manifest field. |
| `tests/test_exploratory.py` | Updated `try_all_models` expectations to filter incompatible regression models for classification fixtures. |
| `data/fixtures/housing.csv` | New small regression fixture (~50 rows, target `price`). |
| `docs/ROADMAP.md` | Added M1 row to slice map. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
```

Results:

- `ruff check` — passed
- `mypy thelab` — passed
- `pytest tests/ -q` — **237 passed, 520 warnings** (warnings are sklearn/joblib/numpy deprecation notices, not failures)

### Documented example command

```bash
thelab run model --dataset data/fixtures/housing.csv --target price --model ridge --seed 42 --output runs
thelab compare
```

Result: run completed with `task_type=regression`, test RMSE ≈ 7130.43, R² ≈ 0.9956. `thelab compare` shows separate "Classification runs" and "Regression runs" sections with task-appropriate columns.

---

## Design notes

- **Inference rule** (`thelab/run/task_type.py`): non-numeric target → classification; numeric target with ≤ 20 distinct values → classification; otherwise regression. The constant `_CLASSIFICATION_MAX_CLASSES = 20` is documented in the spec and exposed via a default argument.
- **Model/task mismatch** is treated as a validation rejection (traceable outcome), not a crash.
- **Probability suffix**: `*_probability` on regression models raises `ValueError` at registry lookup time.
- **No new runtime dependencies** were added; the slice uses existing scikit-learn estimators.

---

## Limitations

- Time-series, multi-label, and ordinal targets remain out of scope.
- The `--try-all` CLI sort still prefers classification metrics (`test_f1_macro`, `test_accuracy`, `test_r2`) for tie-breaking; this is acceptable because regression-only grids sort by `test_r2`.
- The UI metrics panel renders task-appropriate metrics but does not chart them; full UI rework is U1 scope.

---

## Smallest next step

**L1 — Agent harness + protocol**: implement `thelab/agents/provider.py` (`LLMProvider` Protocol + Pydantic contracts) and `thelab/agents/harness.py` (MCP discovery, bounded tool loop, grounding check, approval gate), plus entry point `thelab-agent` and tests.
