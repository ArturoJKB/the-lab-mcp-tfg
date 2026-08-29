---
phase: phase-a
reviewed: 2026-08-16T00:00:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - thelab/run/inputs.py
  - thelab/run/runner.py
  - thelab/run/preprocess.py
  - thelab/run/train.py
  - thelab/run/artifacts.py
  - thelab/run/validate.py
  - thelab/run/profile.py
  - thelab/run/model_registry.py
  - thelab/run/inference.py
  - thelab/run/batch.py
  - thelab/cli.py
  - thelab/model_service/app.py
  - thelab/model_service/cli.py
  - thelab/mcp/model_registry_mcp.py
  - thelab/context/repository.py
  - scripts/evaluate_thesis.py
  - tests/test_run.py
  - tests/test_model_service.py
  - tests/test_validate.py
  - tests/test_batch.py
findings:
  critical: 1
  warning: 5
  info: 7
  total: 13
status: issues_found
---

# Phase A: Code Review Report

**Reviewed:** 2026-08-16
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

Phase A hardening code is generally well-structured: paths are validated, runs produce complete manifests, the MCP and HTTP surfaces gate predictions to approved completed runs, and tests cover the main success and rejection paths. However, one **critical correctness bug** was proven: the new `*_probability` model variants are advertised as supported but crash for every model except `svc_probability`. There are also several warnings around path containment (symlink escapes), unsafe deserialization of model artifacts, stale defaults, and error-detail leakage.

## Top findings

- **CR-01:** `logistic_regression_probability`, `random_forest_probability`, and `sgd_classifier_probability` all fail at estimator construction because `build_estimator()` unconditionally injects `probability=True`, which only `SVC` accepts. This makes three supported model variants unusable.
- **WR-01:** Dataset and output paths are only checked for `..` segments and absolute paths; symlinks inside the workspace can still escape the workspace root.
- **WR-02:** `joblib.load()` deserializes pickle data without validation. Anyone who can replace `model.joblib` in an approved run can achieve arbitrary code execution on the next prediction.
- **WR-03:** `RunInputs.workspace_root` default is evaluated once at import time, not at call time, so programmatic callers outside the CLI may write to a stale directory.
- **WR-04:** An empty CSV file raises an unhandled `IndexError` instead of a clean `RejectedRunError`.

## Recommended next steps

1. Fix `build_estimator` so `probability=True` is only set when the estimator class actually accepts that parameter.
2. Resolve and containment-check dataset/output paths against `workspace_root` before use.
3. Use `default_factory=Path.cwd` for `workspace_root`.
4. Add explicit empty-file handling in `read_csv`.
5. Return generic prediction-failure messages to clients and log full traces server-side.
6. Add tests for the three broken probability variants once fixed.

---

## Critical Issues

### CR-01: Probability variants crash for non-SVC models

**File:** `thelab/run/model_registry.py:113-114`
**Issue:** `build_estimator()` adds `params["probability"] = True` whenever the requested name ends in `_probability` and the base model's `supports_probability` flag is `True`. Only `SVC` has a `probability` constructor parameter; `LogisticRegression`, `RandomForestClassifier`, and `SGDClassifier` do not. As a result, `logistic_regression_probability`, `random_forest_probability`, and `sgd_classifier_probability` all raise `TypeError: ... got an unexpected keyword argument 'probability'` during training. These names are advertised as valid in `thelab/run/inputs.py:51-56`.

**Fix:**
```python
if probability and entry.supports_probability:
    if "probability" in entry.estimator_class._get_param_names():
        params["probability"] = True
return entry.estimator_class(**params)
```

---

## Warnings

### WR-01: Symlink escapes bypass path-safety checks

**File:** `thelab/run/inputs.py:18-22`
**Issue:** `_reject_unsafe_path()` only rejects absolute paths and literal `..` components. A relative path such as `data.csv` or `runs` that is a symlink pointing outside `workspace_root` is accepted, allowing dataset reads and run outputs to escape the workspace. This is inconsistent with `thelab/mcp/common.py`, which resolves paths before containment checks.

**Fix:** After confirming a relative path, resolve it under `workspace_root` and verify containment:
```python
def _reject_unsafe_path(value: Path, field_name: str, root: Path) -> Path:
    if value.is_absolute():
        raise ValueError(f"{field_name} must be a relative path: {value}")
    if ".." in value.parts:
        raise ValueError(f"{field_name} must not contain '..' components: {value}")
    resolved = (root / value).resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError(f"{field_name} resolves outside workspace: {value}")
    return value
```

### WR-02: Unvalidated `joblib.load` on model artifacts

**File:** `thelab/model_service/app.py:263`; `thelab/mcp/model_registry_mcp.py:188`
**Issue:** Both the HTTP `/predict` endpoint and the MCP `predict` tool call `joblib.load(model_path)` directly. `joblib` uses Python pickle under the hood, so a malicious actor who can write to `runs/<run_id>/model.joblib` can execute arbitrary code during prediction.

**Fix:** Document the trust assumption (run directories must be writable only by the owner). For stronger defense, consider hashing the model file at registration time and verifying the hash before loading, or loading inside a restricted subprocess. At minimum, log the full path and hash of every loaded model.

### WR-03: `workspace_root` default evaluated at import time

**File:** `thelab/run/inputs.py:35`
**Issue:** `workspace_root: Path = Field(default=Path.cwd())` evaluates `Path.cwd()` once when the model class is defined. If the process changes directory after import, any `RunInputs` created without an explicit `workspace_root` will use the stale directory.

**Fix:**
```python
workspace_root: Path = Field(default_factory=Path.cwd)
```

### WR-04: Empty CSV file raises `IndexError`

**File:** `thelab/run/profile.py:14`
**Issue:** `read_csv()` accesses `path.read_text(...).splitlines()[0]` without checking for an empty file. A zero-byte CSV raises an unhandled `IndexError`, producing a `failed` run instead of a clean `rejected` run with a clear reason.

**Fix:**
```python
try:
    header_line = path.read_text(encoding="utf-8").splitlines()[0]
except IndexError as exc:
    raise RejectedRunError("dataset file is empty or has no header") from exc
```

### WR-05: Prediction failures leak internal exception details

**File:** `thelab/model_service/app.py:265-266`; `thelab/mcp/model_registry_mcp.py:199-200`
**Issue:** Both surfaces return the raw exception message to clients (`detail=f"prediction failed: {exc}"` / `_error(f"prediction failed: {exc}")`). In a local service the risk is limited, but this can expose file paths, estimator internals, or other implementation details.

**Fix:** Log the full exception server-side and return a generic message:
```python
except Exception as exc:
    logger.exception("prediction failed for run_id=%s", run_id)
    raise HTTPException(status_code=500, detail="prediction failed") from exc
```

---

## Info

### IN-01: Foreign-key constraints are not enforced

**File:** `thelab/context/repository.py:118-121`
**Issue:** SQLite disables foreign keys by default. `ContextRepository._connect()` does not execute `PRAGMA foreign_keys = ON`, so the `ON DELETE CASCADE` clause on `entry_tags` has no effect if entries are ever deleted directly.

**Fix:**
```python
def _connect(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

### IN-02: Unused `dataset_path` parameter in `validate_dataset`

**File:** `thelab/run/validate.py:154`
**Issue:** `validate_dataset` accepts `dataset_path: Any` but never uses it. All checks operate on the passed DataFrame.

**Fix:** Remove the parameter or document why it is retained for API compatibility.

### IN-03: `train_and_evaluate` returns unused split data

**File:** `thelab/run/train.py:40`; `thelab/run/runner.py:154`
**Issue:** `train_and_evaluate` returns `X_train, X_test, y_train, y_test`, but the runner ignores them with `_, _, _, _`. This adds noise to the signature and call site.

**Fix:** Either consume the splits (e.g., for optional artifact storage) or remove them from the return tuple.

### IN-04: `dependency_versions()` called twice per run

**File:** `thelab/run/runner.py:11,223`
**Issue:** `dependency_versions()` is invoked once at import (via `from thelab.version import dependency_versions`) and once in `run_model()`. The second call result is passed to `write_artifacts()`, while `write_artifacts()` receives a fresh third call inside.

**Fix:** Compute versions once per run and reuse the value:
```python
deps = dependency_versions()
manifest = write_artifacts(..., dependency_versions=deps, ...)
```

### IN-05: Duplicate-column check is brittle and reads the file twice

**File:** `thelab/run/profile.py:14-23`
**Issue:** The duplicate-column detector parses the header with a simple `split(",")`, which mishandles quoted headers containing commas. It also reads the entire CSV once for the check and again inside `pd.read_csv`.

**Fix:** Use `csv.Sniffer`/module or ask pandas to detect duplicates via `df.columns[df.columns.duplicated()]` after reading, avoiding the double read.

### IN-06: Dead defensive branch in `_context_entry_to_dict`

**File:** `thelab/model_service/app.py:82`
**Issue:** `model_dump(mode="json", include=...)` already returns a `dict`, so the `else dict(data)` branch is unreachable.

**Fix:**
```python
return entry.model_dump(mode="json", include={...})
```

### IN-07: MCP tool schemas do not forbid additional properties

**File:** `thelab/mcp/model_registry_mcp.py:30-79`
**Issue:** The tool `input_schema` objects do not set `additionalProperties: false`. Extra arguments are silently ignored rather than rejected, which is inconsistent with the hardened `context_mcp` schemas described in the codebase guide.

**Fix:** Add `"additionalProperties": false` to every tool schema.

---

_Reviewed: 2026-08-16_
_Reviewer: gsd-code-reviewer_
_Depth: standard_
