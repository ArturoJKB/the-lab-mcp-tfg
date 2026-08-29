# Slice B1 — Cross-domain benchmark suite

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` § Stage 3 — B1; `docs/SLICEB1_PLAN.md`  
**Scope:** Trial benchmark comparing deterministic baselines against agent-boosted proposals across three easy tabular domains, using both OpenRouter and Ollama providers.

---

## Changed files

| File | Change |
|---|---|
| `scripts/prepare_b1_datasets.py` | Downloads/generates the three benchmark CSVs (California Housing, Breast Cancer, Wine Quality Red). |
| `scripts/run_b1_benchmark.py` | Runs deterministic baselines and agent-boosted experiments for OpenRouter and Ollama, then writes the manifest and report. |
| `docs/B1_CLI_RECREATION.md` | Manual CLI steps to reproduce every part of the benchmark without the script. |
| `docs/SLICEB1_PLAN.md` | Binding plan for this slice. |
| `tests/test_b1_benchmark.py` | Unit tests for dataset preparation, report generation, and metric summary helpers. |
| `.gitignore` | Ignores generated `data/benchmarks/` and `benchmarks/b1/` directories. |
| `docs/ROADMAP.md` | B1 marked `done`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_b1_benchmark.py -q
.venv/bin/python scripts/evaluate_thesis.py
```

Results:

- `ruff check thelab tests scripts` — passed
- `mypy thelab` — passed
- `pytest tests/test_b1_benchmark.py -q` — **6 passed**
- `pytest tests/ -q` — **351 passed**
- `scripts/evaluate_thesis.py` — **Overall: PASS**

### Manual benchmark run

```bash
source .env
.venv/bin/python scripts/prepare_b1_datasets.py
.venv/bin/python scripts/run_b1_benchmark.py
```

Result: benchmark completed for both providers. OpenRouter (`stealth/ox-alpha`) succeeded on all three domains; Ollama (`llama3.2:3b`) succeeded on breast cancer and wine quality, but its California Housing proposal selected a classification model for a regression task, so the agent run was recorded as failed.

Manifest: `benchmarks/b1/benchmark_manifest.json`  
Report: `benchmarks/b1/reports/b1_report.md`

---

## Observed results (snapshot)

| Provider | Domain | Deterministic | Agent | Status |
|---|---|---|---|---|
| openrouter / stealth/ox-alpha | real_estate | RMSE=0.7456 | RMSE=0.7455 | OK |
| openrouter / stealth/ox-alpha | medical | Acc=0.9825 | Acc=0.9825 | OK |
| openrouter / stealth/ox-alpha | food_chemistry | Acc=0.5906 | Acc=0.5906 | OK |
| ollama / llama3.2:3b | real_estate | RMSE=0.7456 | N/A | AGENT_FAILED |
| ollama / llama3.2:3b | medical | Acc=0.9825 | Acc=0.9825 | OK |
| ollama / llama3.2:3b | food_chemistry | Acc=0.5906 | Acc=0.5906 | OK |

---

## Design decisions

- **Trial scope:** kept intentionally simple. No new CLI subcommand, no benchmark database, no hyperparameter search — just a script that orchestrates existing commands.
- **Both providers:** the script runs OpenRouter and Ollama back-to-back so the same datasets are compared under the same conditions.
- **Generated artifacts ignored:** `data/benchmarks/` and `benchmarks/b1/` are not committed. The scripts and docs are the reproducible entry points.
- **Failure tolerance:** if the agent proposes an invalid model or the batch fails, the script records `agent: null` and continues. This is important for small local models.

---

## Known limitations

- This is a **trial** benchmark. The datasets are well-studied and chosen for ease of access, not for novelty.
- Wine quality is a hard multi-class problem; the baseline accuracy is low (~0.59).
- Ollama `llama3.2:3b` occasionally proposes a classification model for regression, causing agent-run rejection.
- The benchmark runner is synchronous and re-runs from scratch each time; there is no caching of proposals or runs.
- The script does not track OpenRouter cost or token usage.

---

## Next suggested slice

**U1 — UI v2 dashboard** — surface the B1 results (runs, proposals, comparison tables) in a richer web UI, or **D1 — Demos and notebook** — wrap the B1 flow into a reproducible demo/notebook. Both are independent and can be picked based on whether you want to prioritize human-facing presentation or documentation first.
