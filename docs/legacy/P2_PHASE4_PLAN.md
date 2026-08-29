# P2 Phase 4 Plan — Code Sandbox + Advanced Agent Iteration

> Authority: Binding plan for Phase 4 of `docs/P2_IDE_PLAN.md`. Implement only what is listed here.

## Goal

Let users run sandboxed Python code and ask the agent to iterate on a completed run.

## In scope

1. **Backend**
   - `thelab/sandbox/ast_check.py`: AST visitor that blocks dangerous nodes/names.
   - `thelab/sandbox/policy.py`: import whitelist + restricted builtins list.
   - `thelab/sandbox/child.py`: subprocess entry point that executes code under restrictions.
   - `thelab/sandbox/runner.py`: `run_in_sandbox()` wrapper with timeout/memory/output limits.
   - `thelab/sandbox/artifacts.py`: collect allowed artifacts from the temp workspace.
   - `POST /sandbox/run`: accept `{code, timeout?}` and return stdout/stderr/artifacts.
   - `POST /agent/iterate`: accept `{run_id, goal?}` and return a worker proposal grounded in the run's metrics + EDA.

2. **Frontend**
   - New **Sandbox** sidebar panel with a textarea code editor.
   - Run button, stdout/stderr output area, artifact gallery.
   - "Iterate on run" button in the Models panel (for approved runs).

3. **Tests**
   - `tests/test_sandbox.py`: AST blocks, import whitelist, resource limits, artifact collection.
   - `tests/test_ide_iterate.py`: iteration endpoint creates a proposal.

## Out of scope

- Real LLM providers for iteration (use deterministic fallback).
- Persistent sandbox sessions.
- Network access inside sandbox.

## Safety boundaries

- Subprocess isolation; code never runs in the main process.
- Deny-by-default imports with explicit whitelist.
- Block AST nodes for `exec`, `eval`, `compile`, `__import__`, dynamic classes, etc.
- Remove dangerous builtins (`open`, `eval`, `exec`, `breakpoint`).
- Temp workspace only; allowed artifacts copied out by extension.
- Timeout and memory caps.
- `/agent/iterate` only reads existing runs; no writes.

## Verification

- `ruff check thelab tests scripts`
- `mypy thelab`
- `pytest tests/test_sandbox.py tests/test_ide_iterate.py -q`
- Full suite green.
