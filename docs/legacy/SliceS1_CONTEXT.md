# Slice S1 — Deterministic EDA skill pack

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 — S1; `stage_2.md`  
**Scope:** Pure, deterministic DataFrame EDA functions exposed as typed MCP tools that future agents must cite.

---

## Changed files

| File | Change |
|---|---|
| `thelab/eda/__init__.py` | Public exports for the EDA skill pack. |
| `thelab/eda/skills.py` | New deterministic functions: `missing_profile`, `correlation_hints`, `class_balance`, `outlier_scan`, `leakage_suspects`, `feature_types`. Each returns a documented JSON-serializable schema. |
| `thelab/mcp/eda_mcp.py` | New stdio MCP server exposing the six EDA tools with path-safety checks (rejects absolute/`..` paths). |
| `thelab/agents/cli.py` | `thelab-agent` now spawns the EDA MCP server alongside the four existing read-only servers. |
| `pyproject.toml` | Added `thelab-eda-mcp` console script. |
| `tests/test_eda_skills.py` | Golden-output, determinism, size-bounds, and edge-case tests for each skill. |
| `tests/test_eda_mcp.py` | MCP integration tests: tool discovery, path traversal rejection, and end-to-end tool calls. |
| `examples/eda_demo.py` | Runnable demo printing a full EDA report for any local CSV. |
| `docs/ROADMAP.md` | Added S1/A2/L2/A3 rows; S1 marked `done`, A2 marked `in_progress`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_eda_skills.py tests/test_eda_mcp.py -q
```

Results:

- `ruff check` — passed
- `mypy thelab` — passed
- `pytest tests/test_eda_skills.py tests/test_eda_mcp.py -q` — **20 passed**

### Documented example command

```bash
.venv/bin/python examples/eda_demo.py data/fixtures/iris.csv species
```

Result: JSON report with `missing_profile`, `correlation_hints`, `class_balance`, `outlier_scan`, `leakage_suspects`, and `feature_types` for the iris fixture.

---

## Design notes

- **Determinism:** no random sampling; outputs depend only on the input DataFrame and optional target.
- **Bounded outputs:** top correlations, co-missing pairs, and per-column reports are capped at `_TOP_K = 10`.
- **Path safety:** the MCP server resolves `dataset` relative to `THELAB_RUNS_ROOT` and rejects absolute paths and `..` components.
- **Target handling:** `correlation_hints` skips Pearson target correlations for non-numeric targets; `class_balance` and `leakage_suspects` require a target.
- **Leakage heuristics:** documented name-based, duplicate-column, and near-perfect-correlation checks.

---

## Limitations

- Leakage detection is heuristic only; it does not prove causal leakage.
- Outlier scan uses fixed IQR (1.5×) and z-score (|z| > 3) thresholds.
- `feature_types` coerces columns into a small set of semantic types; nuanced datetime parsing is left to future work.

---

## Smallest next step

**A2 — Worker agent**: implement `thelab/agents/worker.py` to ingest a goal, run S1 EDA skills, produce a persisted `ExperimentProposal`, and add `thelab proposals approve|reject` CLI commands.
