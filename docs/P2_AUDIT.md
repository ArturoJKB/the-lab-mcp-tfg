---
phase: p2-ide
reviewed: 2026-08-26T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - thelab/sandbox/policy.py
  - thelab/sandbox/ast_check.py
  - thelab/sandbox/child.py
  - thelab/sandbox/runner.py
  - thelab/sandbox/artifacts.py
  - thelab/ide/jobs.py
  - thelab/ide/datasets.py
  - thelab/ide/eda_api.py
  - thelab/ide/cleaning.py
  - thelab/ide/worker_api.py
  - thelab/ide/train_api.py
  - thelab/ide/proposals_api.py
  - thelab/ide/iterate_api.py
  - thelab/ide/viewer_api.py
  - thelab/model_service/app.py
  - thelab/model_service/static/app.js
findings:
  blocker: 1
  major: 3
  minor: 9
  note: 5
  fixed_during_audit: 10
status: issues_found
verification:
  ruff: pass
  mypy: "pass (84 files)"
  pytest: "418 passed, 1 skipped"
  thesis_evaluation: "Overall PASS (RQ1/RQ2/RQ3)"
---

# P2 IDE Audit Report

**Reviewed:** 2026-08-26
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found — 10 small fixes applied during audit; OS-level sandbox containment and error sanitization deferred to a remediation slice.

## Summary

The P2 IDE delivers its five phases functionally end-to-end: upload → EDA → clean → propose → approve → background train/batch with live SSE logs → sandbox iteration → viewer/charts. Requirements coverage is complete except one Phase 5 item (artifact-image endpoints), and route ordering, dataset containment, upload sanitization, artifact allowlists, and XSS escaping discipline are largely sound.

The headline problem: **the code sandbox enforces a syntax policy, not a capability policy.** An independent adversarial review demonstrated three escape chains that use only syntax the AST checker permits; the two most practical ones were mitigated during this audit (removed `inspect`, scrub `thelab.sandbox` package attribute), but arbitrary filesystem read/write from sandboxed code via whitelisted libraries remains possible and requires OS-level confinement to fix properly. Until then the sandbox provides *compute* isolation only — this must be documented, not assumed.

## Findings fixed during this audit

| ID | Sev | Finding | Fix |
|---|---|---|---|
| XSS-01 | MAJOR | Heatmap SVG `<title>` interpolated raw CSV column names (`renderCorrelationHeatmap`) → stored XSS from an uploaded dataset on hover | Escaped labels/values in `app.js` |
| JSON-01 | MINOR | `/runs/comparison` returned NaN metrics; Starlette's strict encoder raises on NaN → **HTTP 500** whenever any completed run recorded NaN (verified empirically) | Metrics sanitized through `_json_safe` in `viewer_api.py` |
| SBX-06 | MINOR | Client-controlled `timeout`/`memory_limit_mb`/`max_output_bytes` unclamped → could pin threadpool workers or disable output truncation | Clamped server-side in `app.py`; negative/zero memory no longer disables RLIMIT silently |
| SBX-03 | MAJOR→mitigated | `inspect.currentframe().f_builtins` recovered unfiltered builtins using fully permitted syntax | Removed `inspect` from import whitelist; generators/coroutines/lambdas are already AST-blocked, closing known frame-reach paths |
| SBX-02 | BLOCKER→mitigated | `import thelab.eda` initializes the `thelab` package whose `.sandbox` attribute chained to real `os` module | `_scrub_sandbox_module_refs()` deletes the reference before user code runs; re-import blocked by whitelist |
| SBX-05 | MINOR | `SystemExit` escaped before result JSON was written, breaking the child protocol mid-stream | `_run_code` now catches `BaseException` and still emits a structured `failed` result (forged-fd1-write variant noted below) |
| COR-01 | MINOR | Artifact `base64` field contained hexadecimal | Real base64 encoding |
| RES-01 | MINOR | Artifacts bypassed output caps; a workspace file near the RLIMIT ceiling was hex-inflated into one HTTP response | 1 MiB per-artifact cap with placeholder marker |
| JOB-01 | MINOR | Fire-and-forget `asyncio.create_task` could be GC'd mid-flight, silently dropping jobs | Strong task references with done-callbacks |
| XSS-02/03 | MINOR | Unescaped `entry.tags`, model `predictions` (arbitrary class labels!), proposal `seeds` interpolated into innerHTML | Escaped in `app.js` |
| — | NOTE | Matplotlib backend unpinned in headless contexts | `MPLBACKEND=Agg` forced in child before user code |

## Open findings (deferred — remediation slice required)

### BLK-01 (BLOCKER): Sandbox has no filesystem confinement

**Files:** `thelab/sandbox/policy.py:27-42`, `thelab/sandbox/child.py`
**Evidence:** Whitelist includes `io` (= builtins.open), `pathlib`, `pandas`, `matplotlib`; the only confinement is `os.chdir(workspace)`.
```python
import pandas as pd
pd.read_csv("/etc/passwd")            # read anywhere
df.to_csv("/anywhere/out.csv")        # write anywhere, incl. repo files
```
**Impact:** The stated boundary "no writes outside temp dir" is not enforced by anything but convention. Single-user localhost lowers exposure but violates the project invariant and the plan text.
**Fix direction:** OS-level isolation (dedicated unprivileged UID + private tmp dir permissions, bubblewrap/nsjail/Landlock, or at minimum remove `io`/`pathlib` from the whitelist and document pandas I/O as unrestricted). AST filtering cannot fix this class.

### MAJ-01 (MAJOR): Absolute paths leak in HTTP error details

**Files:** `thelab/ide/viewer_api.py:40`, `thelab/ide/datasets.py:110,150`, `thelab/model_service/app.py` (artifact-read 500s), `thelab/sandbox/runner.py:70`, `thelab/sandbox/child.py` stderr passthrough.
**Impact:** pandas/OSError messages embed resolved absolute paths into 400/500 `detail` bodies — contradicts the "no absolute paths" invariant.
**Fix direction:** Centralized sanitizer mapping exceptions to stable path-free messages; log details server-side. Touches several P0-era endpoints too, hence deferred.

### MAJ-02 (MAJOR): Phase 5 requirement gap — artifact-image endpoints missing

**Source:** `docs/P2_IDE_PLAN.md` §6 Phase 5 backend: "Endpoints for model metrics comparison and artifact images."
**Status:** Metrics comparison delivered (`GET /runs/comparison`); artifact-image serving is not implemented (charts are computed client-side from EDA/metrics data instead). Recorded as PARTIAL coverage; low urgency given the UI need is met another way.

### Minor / notes (deferred)

- **RES-02:** `JobManager` never evicts finished jobs/events; SSE connections can linger up to 30 s past terminal event (no heartbeat).
- **JOB-02:** Phantom `"rejected"` terminal branch never produced; `list_jobs` builds DTOs outside the lock (torn-snapshot reads possible).
- **COR-02:** `iterate_api._path_to_dataset_id` resolves runs' datasets by basename only — basename collisions between uploads/fixtures can ground iteration on the wrong file. Proper fix: persist `dataset_id` in run inputs at train time.
- **NOTE-1:** Forged-result variant of SBX-05: whitelisted `io` can still write fabricated JSON to fd 1 before exiting cleanly. Full fix = result channel separation (fd/file + nonce).
- **NOTE-2:** Policy whitelists `matplotlib`/`seaborn` but neither is a project dependency — sandbox plotting silently unavailable until installed (test skips without it). Add as optional extras or document.
- **NOTE-3:** `proposals_api.py` returns `path.as_posix()` — relative by default but absolute if `THELAB_PROPOSALS_DIR` is set absolute.
- **NOTE-4:** `docs/CODEBASE_GUIDE.md` is stale: no coverage of `thelab/ide`, `thelab/sandbox`, or the ~14 new endpoints (flagged per audit scope decision).

## Verified sound

- **Route ordering:** `/runs/comparison` precedes `/runs/{run_id}`; `{dataset_id:path}` literal tails (`/preview`, `/clean`) cannot collide; `/models/available`, `/jobs*` disjoint.
- **Dataset containment chain:** sanitize → basename check → resolve() → `relative_to(root)` blocks traversal and symlink escape (verified incl. planted-link scenario).
- **Upload safety:** size cap sentinel read, collision suffixing, CSV parse validation.
- **Artifact serving:** strict allowlist; `model.joblib` never served over HTTP.
- **JSON-02 false positive:** suspected numpy-int64-as-string issue disproven empirically — `to_dict(orient="records")` boxes native ints; preview rows are histogram-compatible.
- **JobManager concurrency:** subscribe/replay ordering atomic under the event loop; unsubscribe guaranteed via `finally`; SSE 404s unknown jobs pre-stream.
- **AST checker behavior:** f-string expressions visited; star-imports/relative imports handled statically and at runtime hook; dynamic `type()` blocked.
- **app.js escaping discipline:** systematic outside the three fixed sinks; no eval/Function/document.write; CSS.escape used for selectors.
- **Runner protocol:** timeout kill, nonzero-exit and malformed-JSON branches well-formed.

## Requirements coverage matrix

| Phase | Acceptance criteria | Status |
|---|---|---|
| 1 Upload + EDA | Dropzone/picker upload; safe storage under `data/uploads/`; listing without absolute paths; EDA render; invalid uploads rejected | COVERED (tests: test_ide_datasets, test_ide_eda) |
| 2 Goal launcher + training | Worker proposal; approve/reject/run records w/ `principal:"ui"`; deterministic `/train`; cleaning endpoint; banners/detail errors | COVERED (test_ide_worker, test_ide_proposals_actions, test_ide_train, test_ide_cleaning) |
| 3 Pipeline + execution view | Background job queue; status + SSE; diagram steps reflect state; live log tail | COVERED (test_ide_jobs) |
| 4 Sandbox + iteration | Restricted subprocess; `/sandbox/run`; `/agent/iterate`; editor/output/artifacts UI; iterate button | COVERED (test_sandbox, test_ide_iterate); confinement caveat BLK-01 |
| 5 Viewer + visualizations | CSV viewer table; metric bars; heatmap; distributions; comparison table; **artifact-image endpoints** | PARTIAL — all charts/viewer covered; artifact-image endpoints MISSING (MAJ-02) |

## Verification results (after fixes)

```bash
ruff check thelab tests scripts   # All checks passed!
mypy thelab                       # Success: no issues found in 84 source files
pytest tests/ -q                  # 418 passed, 1 skipped (matplotlib optional)
scripts/evaluate_thesis.py        # Overall: PASS (RQ1/RQ2/RQ3)
```

## Recommended remediation order

1. **BLK-01** — OS-level sandbox confinement (or minimum: drop `io`/`pathlib` from whitelist + document compute-only isolation). Highest value.
2. **MAJ-01** — centralized error-detail sanitizer across all HTTP surfaces.
3. **COR-02** — persist `dataset_id` in run inputs; use it in iterate.
4. **RES-02/JOB-02** — job eviction + heartbeat; snapshot DTOs under lock.
5. **MAJ-02** — decide: implement artifact-image serving or amend the P2 plan text.
6. **NOTE-2/3/4** — optional deps, proposals path normalization, CODEBASE_GUIDE refresh.
