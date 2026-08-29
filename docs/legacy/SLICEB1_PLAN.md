# Slice B1 Plan — Cross-domain benchmark suite (P1 Stage 3)

> **Status:** ready for review — **binding after user approval**  
> **Last updated:** 2026-08-24  
> **Audience:** coding agent (Kimi or equivalent)  
> **Authority:** This file supersedes informal chat proposals. Implement **only** what is listed here.

---

## 1. Goal

Create a reproducible, persisted benchmark suite that exercises the hardened P1 Stage 2 agent surface across **three domains not yet studied** in the repo. For each domain we run:

1. A **deterministic baseline** (`thelab run model`).
2. An **agent-boosted experiment** (`thelab-agent --mode worker` → approved proposal → batch run).

The results are saved to `benchmarks/b1/` so future slices can keep them green.

---

## 2. Binding spec references

- `docs/P1_PLAN.md` § Stage 3 — B1
- `docs/PRD_P0.md` (reproducibility, artifact, and comparison requirements)
- `docs/ROADMAP.md` — B1 row (currently `planned`)

---

## 3. Proposed datasets (easy-to-use, 3 domains)

| Domain | Dataset | Task type | Target | Source |
|---|---|---|---|---|
| **Real estate** | California Housing | regression | `MedHouseVal` | `sklearn.datasets.fetch_california_housing` |
| **Medical** | Breast Cancer Wisconsin | binary classification | `target` | `sklearn.datasets.load_breast_cancer` |
| **Food / chemistry** | Wine Quality (red) | multi-class classification | `quality` | UCI ML Repository CSV |

Rationale:
- All are tabular CSV, no auth, no heavy preprocessing.
- `sklearn` built-ins for the first two make them trivially reproducible.
- Wine Quality is a classic public CSV from UCI and gives us a multi-class problem.
- None overlap with the existing Iris classification baseline.

**Decision needed:** confirm these three domains/datasets, or swap one (e.g., replace Wine with Titanic / Adult / Diabetes).

---

## 4. Protocol

For each dataset:

### 4.1 Prepare data

Write a small helper that ensures CSVs exist under `data/benchmarks/`:

```text
data/benchmarks/
  california_housing.csv
  breast_cancer.csv
  wine_quality_red.csv
```

If a CSV is missing, generate/download it deterministically.

### 4.2 Deterministic baseline

```bash
.venv/bin/python -m thelab.run.model \
  --dataset data/benchmarks/california_housing.csv \
  --target MedHouseVal \
  --model ridge \
  --seed 42 \
  --output runs
```

Models per task type:
- regression: `ridge`
- binary classification: `logistic_regression`
- multi-class classification: `logistic_regression`

Record the resulting `run_id` and metrics.

### 4.3 Agent-boosted run

```bash
source .env
.venv/bin/python -m thelab.agents.cli --mode worker --provider openrouter \
  "predict housing prices" \
  --dataset data/benchmarks/california_housing.csv \
  --target MedHouseVal \
  --proposals-dir benchmarks/b1/proposals \
  --json
```

Then approve the proposal programmatically and run its batch config:

```bash
.venv/bin/python -m thelab.run.batch \
  --config benchmarks/b1/proposals/<proposal_id>.batch.json
```

Record agent proposal ID, batch run IDs, and metrics.

### 4.4 Result collection

Read `metrics.json` for each run and store:
- `test_accuracy` / `test_f1_macro` / `test_rmse` as appropriate.
- `train_samples`, `test_samples`.
- Run duration from `manifest.json`.

---

## 5. Result persistence

Output directory: `benchmarks/b1/`

```text
benchmarks/b1/
  benchmark_manifest.json   # structured summary
  proposals/                # agent proposals
  reports/
    b1_report.md            # human-readable comparison table
```

`benchmark_manifest.json` schema:

```json
{
  "benchmark_id": "b1",
  "created_at": "2026-08-24T...",
  "provider": "openrouter",
  "model": "stealth/ox-alpha",
  "datasets": [
    {
      "domain": "real_estate",
      "dataset": "data/benchmarks/california_housing.csv",
      "target": "MedHouseVal",
      "task_type": "regression",
      "deterministic_run_id": "run-...",
      "agent_proposal_id": "prop-...",
      "agent_run_ids": ["run-..."],
      "metrics": {
        "deterministic": {"test_rmse": 0.74},
        "agent": {"test_rmse": 0.71}
      }
    }
  ]
}
```

---

## 6. CLI / entry point

Add a single command to make B1 reproducible:

```bash
.venv/bin/python -m thelab.benchmark b1 --provider openrouter --output benchmarks/b1
```

or, if we prefer a script first:

```bash
.venv/bin/python scripts/run_b1_benchmark.py --provider openrouter
```

**Decision needed:** prefer a new `thelab benchmark b1` CLI subcommand (consistent with `thelab run model`) or a script under `scripts/` (smaller, faster to implement). Recommendation: start with the script, then promote to CLI if U1/D1 need it.

---

## 7. Tests

`tests/test_b1_benchmark.py`:

- Test dataset preparation helper creates expected CSVs.
- Test benchmark manifest generation from mocked deterministic + agent runs.
- Test comparison report markdown contains expected sections.
- Optional: run one tiny deterministic baseline end-to-end to prove the protocol works.

Keep tests offline where possible; do not require OpenRouter in CI.

---

## 8. Acceptance criteria (DoD)

- [ ] Three CSV datasets are prepared under `data/benchmarks/`.
- [ ] Deterministic baselines run for all three domains.
- [ ] Agent-boosted runs run for all three domains (using provider configured in `.env`).
- [ ] `benchmarks/b1/benchmark_manifest.json` is created with all run IDs and metrics.
- [ ] `benchmarks/b1/reports/b1_report.md` contains a comparison table.
- [ ] `tests/test_b1_benchmark.py` passes.
- [ ] `ruff check thelab tests scripts`, `mypy thelab`, and full `pytest tests/ -q` remain green.
- [ ] `docs/SLICEB1_CONTEXT.md` handoff doc is written.
- [ ] `docs/ROADMAP.md` marks B1 `done`.

---

## 9. File map (expected touch set)

```text
data/benchmarks/                         # generated datasets (not committed, or committed if small)
benchmarks/b1/                           # generated results (not committed)
scripts/run_b1_benchmark.py              # or thelab/benchmark/cli.py + thelab/benchmark/runner.py
thelab/benchmark/                        # if CLI route
  __init__.py
  runner.py
  report.py
tests/test_b1_benchmark.py
docs/SLICEB1_PLAN.md                     # this file
docs/SLICEB1_CONTEXT.md                  # after impl
docs/ROADMAP.md
```

**Question:** should the generated CSVs be committed to the repo? They are small (~2 MB total). Committing them makes B1 reproducible without internet, but it adds data to git. Recommendation: commit the three small CSVs under `data/benchmarks/` so the benchmark is fully offline.

---

## 10. Implementation order

```text
1. Confirm datasets with user.
2. Implement dataset preparation helper + CSVs.
3. Implement deterministic baseline runner.
4. Implement agent-boosted runner (worker → approve → batch).
5. Implement manifest + report writer.
6. Add tests.
7. Run full verification gates.
8. Write SLICEB1_CONTEXT.md and update ROADMAP.
```

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| OpenRouter costs / rate limits | Use deterministic fallback for unit tests; only agent runs hit the API. Cache proposals when possible. |
| `stealth/ox-alpha` produces invalid proposals | JSON repair + deterministic fallback from A3.3 still applies. |
| Wine Quality CSV URL changes | Pin UCI URL; include a small fixture fallback. |
| Tests become slow | Mock provider for manifest/report tests; keep one real deterministic run per domain. |
| Agent-boosted results are worse than deterministic | That is a valid benchmark result; report it honestly. |

---

## 12. Decisions needed from you before implementation

1. **Confirm the three datasets** (California Housing, Breast Cancer, Wine Quality Red) or propose swaps.
2. **Entry point:** script (`scripts/run_b1_benchmark.py`) or CLI (`thelab benchmark b1`)?
3. **Commit generated CSVs?** Yes/no.
4. **Agent provider for the recorded B1 run:** OpenRouter (`stealth/ox-alpha`) or also run Ollama variant?

---

## 13. Paste-ready prompt for the coding agent

> Implement `docs/SLICEB1_PLAN.md` exactly. Prepare the three benchmark datasets, run deterministic baselines, run agent-boosted experiments via the worker, and persist results to `benchmarks/b1/`. Add tests and keep all verification gates green. Write `docs/SLICEB1_CONTEXT.md` and mark B1 done in `docs/ROADMAP.md`.
