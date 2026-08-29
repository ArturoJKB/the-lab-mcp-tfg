# The Lab — Agent Onboarding

Single source of truth for any coding agent (or human) changing this repository.

## Current documentation

| Doc | Purpose |
|---|---|
| [`README.md`](README.md) | Product overview, quick start, architecture diagram |
| [`docs/THESIS_MAP.md`](docs/THESIS_MAP.md) | Thesis concepts → implementation → demos |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Global roadmap: P0 → P1 → P2, current focus |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | UI + CLI + HTTP API + MCP usage |
| [`docs/CODEBASE_GUIDE.md`](docs/CODEBASE_GUIDE.md) | Codebase tour by phase |
| [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md) | CLI reference |
| [`docs/PYTHON_API.md`](docs/PYTHON_API.md) | Python/notebook API |
| [`docs/THESIS_EVALUATION.md`](docs/THESIS_EVALUATION.md) | RQ1–RQ3 protocol and results |

**Everything else** lives in `docs/legacy/` — historical slice/phase records kept as
source material for the thesis document. They are **not binding** for new code and are
not updated.

## Working mode

Development is **dynamic**: small, focused changes instead of big planned phases.

- Implement exactly what was asked; smallest surface that works.
- No binding phase plans or ceremony for small changes. A short written plan is only
  worth it for multi-file or architectural work.
- Keep the full test suite green; update docs when behavior changes.
- Do not build unrequested features, and do not resurrect legacy plans without an
  explicit request.

## Core principles

- Local-first, auditable, reproducible, reusable.
- Typed contracts and deterministic pipelines.
- All run outputs stay under `runs/<run_id>/`; persisted references use relative paths.
- A rejected validation is a valid, traceable result — never swallow it.

## Safety boundaries

- LLM-generated code executes **only** inside `thelab/sandbox` (AST-restricted
  subprocess). No arbitrary shell execution or unsandboxed code paths.
- Local-first by default. External LLM providers are supported through the provider
  abstraction (Ollama local, OpenAI-compatible, OpenRouter) with explicit user
  configuration. No other cloud services without an explicit request.
- Out of thesis scope: trading, brokers, order execution, portfolios.
- Do not silently change dependencies or architecture; ask before destructive commands
  or broad refactors.

## Definition of done (proportionate)

1. Implement the requested change.
2. Add or adjust **focused** tests for new behavior — not exhaustive suites.
3. Run the affected tests, then the full suite:
   ```bash
   .venv/bin/ruff check thelab tests scripts
   .venv/bin/mypy thelab
   .venv/bin/python -m pytest tests/ -q
   ```
4. Run the documented example command when one exists.
5. Report: changed files, test output, limitations, next step.

## Thesis evaluation

`scripts/evaluate_thesis.py` checks RQ1 (reproducibility), RQ2 (MCP interoperability),
RQ3 (context retrieval). It must pass before claiming any work is complete.
