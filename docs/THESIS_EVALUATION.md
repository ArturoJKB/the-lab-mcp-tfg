# Thesis Evaluation — The Lab

> Last updated: 2026-08-29  
> Status: automated RQ1–RQ3 checks PASS (fixture baseline + re-run); real-dataset validation recorded.

## Hypothesis

A local multi-agent orchestration architecture based on typed contracts and
MCP capabilities can execute a reproducible data-to-model workflow and expose
its resulting artifacts to independent agents without being coupled to a
specific LLM provider.

## Research questions → checks

| RQ | Method | Pass bar |
|---|---|---|
| **RQ1** Reproducible run | Two `thelab run model` executions on the same fixture with identical dataset, model, and seed. | Both runs complete with `approved` validation status. Key metrics match within tolerance. Manifest records seed, config, and dependency versions. |
| **RQ2** MCP interoperability | Independent stdio MCP client connects to existing `model_registry_mcp`, calls `list_models`, then `predict` on an approved run. | Tool list contains expected tools. `list_models` returns the approved run. `predict` returns typed predictions. Client does not import training pipeline internals. |
| **RQ3** Context retrieval | Index a small JSONL fixture and search via `ContextReader` / context MCP. | Search returns at least one relevant hit. Result contains stable fields (event_id, summary, tags). Database bytes are unchanged by read-only search. |

The same three questions are answered at two scales:

- **Fixture baseline** — iris fixture, single model, P0 closeout record (kept
  below as evidence).
- **Real-dataset scale** — S&P 500 analyst ratings (164k rows), full agent
  orchestration, recorded in *Current results*.

## Environment

- Supported Python: `>=3.11,<3.15`
- Lockfile: `requirements.lock`
- Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e .
```

## Manual demo script

```bash
# 1. Install from lock (see Environment above).

# 2. Reproducible training (CLI way in).
thelab run model --dataset examples/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs

# 3. Same pipeline through the HTTP service and through MCP — identical
#    metrics, identical artifacts (three-ways-in claim).
thelab-model-service --port 8000        # POST /train {"dataset_id": "fixtures/iris.csv", ...}
thelab-mcp-demo model_registry          # list_models + predict on the approved run

# 4. Index and search local context.
thelab context index --source .thelab/local-logs/agent-events.jsonl
thelab context search "proposal"

# 5. Real-dataset path: upload a large CSV in the UI, Run EDA, Clean dataset,
#    then start an experiment in the Experiment panel and watch it live.

# 6. Automated evaluator.
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py
```

## Automated evaluator

Entry point: `scripts/evaluate_thesis.py`

```bash
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py
```

The script uses temporary directories so it does not modify developer state. It
prints a human-readable pass/fail table and a JSON summary, exiting with code 0
when all checks pass. Last run: **2026-08-29 — Overall PASS (RQ1/RQ2/RQ3)**.

## Current results (P2, 2026-08-29)

**Fixture baseline, re-run:** evaluator PASS — RQ1 metrics match, RQ2
prediction round-trip, RQ3 retrieval with byte-identical database.

**Three-ways-in comparison** (iris, `logistic_regression`, seed 42 — identical
metrics and artifacts through every interface):

| Way | Surface | Result | Time |
|---|---|---|---|
| CLI | `thelab run model ...` | 1.0000 test accuracy | ~2 s |
| HTTP | `POST /train` / `POST /jobs` | 1.0000 test accuracy | ~0.2 s |
| MCP | `agent_mcp run_training_job` + `get_job_status` | 1.0000 test accuracy | ~0.2 s |

**Real-dataset validation** (S&P 500 analyst ratings, 164,231 rows × 18
columns, downloaded dataset):

| Check | Result |
|---|---|
| Deterministic cleaning policy (datetime parsing, cardinality-aware encoding, audit report) | 164,231 → 113,769 rows, 18 → 32 columns, 6.3 s, full `cleaning_report` |
| Traceable scale guard | `svc` on 113,769 rows rejected in 0.1 s with reason (previously would run for hours or OOM) |
| Reproducible training (RQ1 at real scale) | logistic_regression completes in ~1.3 s with persisted seed/config/manifest |
| Full agent-orchestrated experiment (RQ2 surface) | 3 models × 3 seeds, 9 persisted runs, best random_forest 74.9% test accuracy, 121 s end-to-end with per-model progress events |
| Feature-horizon leakage study | naive features 84.2% → at-decision-time features 60.3%; every iteration a traceable run |

**Agent/provider status:** four provider adapters implemented (mock,
OpenAI-compatible, Ollama, OpenRouter) with structured-output repair and
deterministic fallback; agent proposals and orchestration are exercised by
the test suite against the mock provider end-to-end.

## Baseline record (P0 closeout, 2026-08-10)

Kept as evidence of the original RQ protocol execution in the locked
environment of that date.

```text
============================================================
The Lab P0 — Thesis Evaluation Report
============================================================
Overall: PASS

RQ1: PASS
  run_ids: ['run-20260810-023703-2e37998c', 'run-20260810-023703-237bc12c']
  metrics: {'test_accuracy': 1.0, 'test_f1_macro': 1.0}
RQ2: PASS
  predictions: ['setosa']
RQ3: PASS
  hits: 1
  event_id: evt-repro
```

## Limitations (current)

- The automated RQ checks run on the iris fixture; real-dataset claims come
  from the recorded S&P validation above, not from the evaluator script.
- MCP transport is stdio only; the HTTP service is not an MCP transport.
- Recorded RQ/agent results use the deterministic fallback provider; live
  Ollama/OpenRouter-driven experiment evaluation is pending (see
  `docs/THESIS_MAP.md` → Current focus).
- The code sandbox provides compute isolation, not OS-level filesystem
  confinement (documented audit finding BLK-01).
- Sub-agents execute in-process (subprocess isolation descoped).
- Context redaction is best-effort; the evaluation verifies retrieval, not
  exhaustive secret-family coverage.
- The Research panel is a local context **search** UI over stored evidence —
  it is not an autonomous agent and produces no generative answers (kept as
  search by design decision).
- Dependency lock is a `pip freeze` style pin without hashes; reproducibility
  relies on PyPI package availability.
