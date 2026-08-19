# Slice 7 Plan — Cleanup + Tooling + README Skeleton

> Binding plan for the first hardening slice.

## Goal

Make the repo clean, toolable, and readable before adding new capabilities.

## What was wrong

- Stale backup/swap files in the tree.
- No linting, formatting, or type-checking config.
- Root `AGENTS.md` missing.
- README lacks structure for upcoming CLI/UI/MCP documentation.

## What this slice delivers

1. Clean working tree.
2. `ruff` and `mypy` configuration in `pyproject.toml`.
3. All lint/type issues fixed or explicitly baselined.
4. Root `AGENTS.md`.
5. README skeleton with placeholders for slice 11.

## File map

| File | Change |
|---|---|
| `docs/PRD_PO.md.save` | Delete |
| `thelab/run/.__init__.py.kate-swp` | Delete |
| `docs/Slice 3 and Slice 4 Readiness Audit.md` | Rename to `docs/slice_3_and_4_readiness_audit.md` |
| `.gitignore` | Add cache/swap patterns |
| `pyproject.toml` | Add `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]`, `[tool.mypy]`, dev deps |
| `AGENTS.md` (new) | Root agent onboarding pointer |
| `README.md` | Refresh structure and tone |

## Non-goals

- No logic changes beyond making tools green.
- No new models, validation rules, or batch runner.
- The one failing thesis-evaluator test is intentionally left for slice 8.

## Verification

```bash
ruff check thelab tests scripts
mypy thelab
pytest tests/ -q
```

Expected: ruff and mypy pass; pytest passes except the one known evaluator subprocess test.

## Risks

- `mypy` may flag many issues on first run. Fix safe ones; explicitly ignore tricky third-party stubs.
- Ruff formatting may touch many files. That is expected; keep the diff reviewable.
