# P2 Phase 4 Context — Code Sandbox + Advanced Agent Iteration

> Fourth phase of the P2 Agentic ML IDE plan.

## Changed files

| File | Change |
|---|---|
| `thelab/sandbox/__init__.py` | New package; exports `run_in_sandbox`, `SandboxResult`. |
| `thelab/sandbox/policy.py` | `SandboxPolicy`: import whitelist, blocked builtins, blocked AST nodes, blocked names, artifact extensions. |
| `thelab/sandbox/ast_check.py` | `AstChecker` visitor + `check_code()`; rejects dangerous syntax before execution. |
| `thelab/sandbox/child.py` | Subprocess entry point (`python -m thelab.sandbox.child`): restricted builtins, import hook, temp workspace, output truncation, artifact collection. |
| `thelab/sandbox/runner.py` | Parent-side `run_in_sandbox()`: subprocess isolation, timeout, memory cap, JSON protocol. |
| `thelab/sandbox/artifacts.py` | Artifact listing/reading with extension allowlist. |
| `thelab/ide/iterate_api.py` | `iterate_on_run()`: loads a completed run, resolves its dataset back to a stable `dataset_id`, builds a grounded goal from metrics, calls the worker agent. |
| `thelab/model_service/app.py` | Added `POST /sandbox/run` and `POST /agent/iterate`. |
| `thelab/model_service/static/index.html` | **Sandbox** panel (textarea editor, run button, output, artifacts); "Iterate on run" card in the Models panel. |
| `thelab/model_service/static/app.js` | Sandbox execution/rendering (stdout/stderr/return value/artifact gallery); iterate form wired to `/agent/iterate`. |
| `thelab/model_service/static/styles.css` | Editor textarea, iterate form grid. |
| `tests/test_sandbox.py` | AST blocks, import whitelist, builtins, artifacts, timeout. |
| `tests/test_ide_iterate.py` | Iteration endpoint: proposal creation, missing-run 400s. |
| `docs/P2_PHASE4_PLAN.md` | Binding plan for this phase. |

## What was implemented

1. **Restricted sandbox**:
   - User code runs in a fresh `python -m thelab.sandbox.child` subprocess — never in the service process.
   - AST pre-check rejects `exec`/`eval`/`compile` calls, dunder attribute escapes, dynamic `type()` classes, `async` constructs, `lambda`, `class`, `global`/`nonlocal`, and blocked names (`__import__`, `__class__`, `__subclasses__`, ...).
   - Deny-by-default imports with whitelist (`numpy`, `pandas`, `sklearn`, plotting libs, `thelab.eda`, safe stdlib).
   - Filtered builtins (`open`, `eval`, `exec`, `compile`, `breakpoint`, `getattr`, `setattr`, `vars`, `globals`, ... removed); custom `__import__` hook re-enforces the whitelist at runtime.
   - Resource limits: wall-clock timeout, optional RLIMIT_AS memory cap, output size truncation.
   - Execution happens in a per-run temp directory; only allowlisted artifact extensions are copied out.
2. **Endpoints**:
   - `POST /sandbox/run {code, timeout?, memory_limit_mb?}` → `{status, stdout, stderr, return_value, artifacts}`.
   - `POST /agent/iterate {run_id, goal?}` → worker proposal grounded in the run's dataset/target/metrics via deterministic fallback.
3. **UI**:
   - Sandbox editor + output + artifact gallery.
   - "Iterate on run" card appears when selecting an approved model; created proposals surface Approve/Reject actions.

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 84 source files

.venv/bin/python -m pytest tests/test_sandbox.py tests/test_ide_iterate.py -q
# 13 passed

.venv/bin/python -m pytest tests/ -q
# 412 passed (full suite)
```

Manual smoke test (live service):

```bash
curl -s -X POST http://127.0.0.1:8000/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"code":"import pandas as pd\ndf = pd.DataFrame({\"x\": [1,2,3]})\nprint(df.shape)\ndf.to_csv(\"out.csv\")"}'
# {"ok":true,"data":{"status":"completed","stdout":"(3, 1)\n",...,"artifacts":[{"name":"out.csv",...}]}}
```

## Limitations / boundaries found

- The sandbox is a best-effort local guardrail (AST + builtins + import hook + subprocess isolation), not a VM-level boundary; per PRD it exists to support agent-assisted EDA, not to host untrusted multi-tenant code.
- No network access is needed by design; network blocking relies on the import whitelist plus no socket exposure in the child.
- Iteration uses the deterministic worker fallback (no live LLM), consistent with Phase 2.

## Next suggested slice

P2 Phase 5 — CSV viewer + visualizations.
