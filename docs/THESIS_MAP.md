# Thesis Map — Concepts, Evidence, Demos

> This document maps every concept in the thesis title to its implementation, the tests that prove it, and a reproduction command. It is the bridge between the thesis narrative and the repository.

**Thesis:** *Context-Aware Multi-Agent Orchestration via MCP — an autonomous ML factory built on the Model Context Protocol.*
**Institution:** Universidad Carlos III de Madrid (UC3M), Data Science and Engineering.

---

## RQ mapping

The thesis answers six research questions, automated in `scripts/evaluate_thesis.py`:

| RQ | Question | Automated check |
|---|---|---|
| RQ1 | Can a model-training run be reproduced from dataset + config + seed? | Two identical trains; metrics match; manifest carries seed + dependency versions |
| RQ2 | Can an independent MCP client discover and use a model? | Spawns `model_registry_mcp`; `list_models` + `predict` round-trip |
| RQ3 | Can local context retrieval recover useful past evidence? | Index JSONL → search hit → DB byte-identical after read |
| RQ4 | Do context-grounded agent rounds make more verifiable claims? | Grounded vs stripped-context round ablation; every claim verified against persisted metrics |
| RQ5 | Can bounded agent rounds train valid, competitive models safely? | Round e2e: gate blocks unapproved execution; approved round runs through the factory; comparison artifact + validity rate |
| RQ6 | Does role-specialized orchestration beat a single shared-prompt agent? | `role_mode=multi` vs `single` ablation over identical deterministic evidence |

RQ1–RQ3 are deterministic checks; RQ4–RQ6 exercise the P5 agentic round
(suite mode: mock provider, protocol + instrumentation verified; `--live`
records provider-specific results). Current status: **PASS** (RQ1–RQ6, suite
mode — see `docs/THESIS_EVALUATION.md`).

---

## Concept 1 — Autonomous ML factory

**Claim:** a tabular CSV becomes a versioned, validated, locally served model with no manual steps.

| Evidence | Location |
|---|---|
| Deterministic pipeline (validate → profile → contract → train → validate → register) | `thelab/run/runner.py` |
| Full artifact set per run (`manifest.json`, `metrics.json`, `model_card.md`, …) | `thelab/run/artifacts.py` |
| Batch/try-all model comparison | `thelab/run/batch.py`, `thelab/run/runner.py` |
| Background job execution with SSE progress | `thelab/ide/jobs.py` |

**Demo (deterministic, no LLM):**

```bash
thelab run model --dataset examples/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs
thelab predict --run-id <run_id> --features '{"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}'
```

**Claim demonstrated:** re-running the command yields a new `run_id` with equivalent metrics; `manifest.json` proves the seed/config/dependency provenance.

---

## Concept 2 — Context-aware agents

**Claim:** agents ground decisions in a local, redacted, searchable context rather than free-form chat.

| Evidence | Location |
|---|---|
| SQLite + FTS5 store, SHA-256 fingerprinting, secret redaction | `thelab/context/` |
| Read-only retrieval (`mode=ro`, `query_only=ON`, privacy filtering) | `thelab/context/reader.py` |
| Worker proposals grounded in EDA + prior-run metrics | `thelab/agents/worker.py` (`_find_prior_runs`, `_build_eda_rationale`) |
| Agent activity logging with redaction | `thelab/mcp/context_write_mcp.py` |

**Demo:**

```bash
thelab context index --source .thelab/local-logs/agent-events.jsonl
thelab context search "proposal"
thelab-mcp-demo context
```

---

## Concept 3 — Multi-agent orchestration

**Claim:** specialized agents (EDAAnalyst, FeatureEngineer, ModelSelector) collaborate through typed artifacts with human approval boundaries.

| Evidence | Location |
|---|---|
| Per-role sub-agent prompt contracts (EDAAnalyst, FeatureEngineer, ModelSelector) | `thelab/ide/orchestrator.py` (`ROLE_SYSTEM_PROMPTS`) |
| Orchestration loop (EDA → clean → try-all → approved batch training) | `thelab/ide/orchestrator.py` |
| Experiment state machine (`pending → planning → … → completed`) | `thelab/ide/experiment.py` |
| Single approval gate (agent-initiated: human required; user-initiated: recorded mandate; rejection final) | `thelab/agents/approval.py`, `thelab/agents/worker.py` (`ProposalStore`) |
| Agent harness + provider abstraction (mock, Ollama, OpenAI-compatible, OpenRouter) | `thelab/agents/` |

**Demo (UI):** `thelab-model-service` → Experiment panel → start a run on an uploaded dataset → watch stage pipeline and agent activity stream (SSE) → send feedback to iterate → compare in History.

Experiment lifecycle (persisted state machine):

```mermaid
flowchart LR
    PENDING[pending] --> PLANNING[planning] --> CLEANING[cleaning] --> TRAINING[training] --> EVALUATING[evaluating] --> COMPLETED[completed]
    EVALUATING --> FAILED[failed]
    COMPLETED -->|feedback| ITERATING[iterating] --> PLANNING
    TRAINING -->|cancel| CANCELLED[cancelled]
```

---

## Concept 4 — MCP interoperability

**Claim:** an independent MCP client can use the factory without knowing its internals.

| Evidence | Location |
|---|---|
| 7 stdio MCP servers | `thelab/mcp/*.py` (entry points `thelab-*-mcp`) |
| Tool schemas with bounds and `additionalProperties: false` | `thelab/mcp/context_mcp.py`, `agent_mcp.py` |
| Demo client exercising servers end-to-end | `thelab/mcp/demo_client.py` |

**Demo:**

```bash
thelab-mcp-demo model_registry --run-id <run_id>   # list_models, get_model_card, predict
thelab-mcp-demo data_catalog --run-id <run_id>     # datasets, profiles, contracts
```

---

## Concept 5 — Real-world robustness (the honest boundary)

**Claim:** the factory behaves gracefully on real data — incompatible configurations are rejected traceably, never silently wrong.

| Evidence | Location |
|---|---|
| Validation failures are first-class outcomes | `thelab/run/validate.py`, PRD AC-02 |
| Cleaning policy: datetime parsing + cardinality-aware encoding + audit report | `thelab/ide/cleaning.py` |
| Per-model scale guards (rejection instead of multi-hour runs) | `thelab/run/model_registry.py`, `thelab/run/runner.py` |
| Cooperative job cancellation + per-model progress events | `thelab/ide/jobs.py`, `thelab/run/batch.py` |
| Documented limitations (sandbox isolation, in-process sub-agents) | `docs/legacy/P2_AUDIT.md`, `docs/legacy/P2_PHASE6_CONTEXT.md` |

**Recorded results — S&P 500 analyst ratings (164,231 rows × 18 columns, real downloaded dataset):**

| Step | Result | Time |
|---|---|---|
| Cleaning policy | 164,231 → 113,769 rows, 18 → 32 columns (datetime parsed, 501 tickers / 306 firms frequency-encoded), full `cleaning_report` | 6.3 s |
| **Before/after the policy** | naive one-hot cleaning produced a **22 GB** CSV; the policy writes **16–21 MB** for the same dataset | — |
| Feature-horizon leakage demo | naive feature set 84.2% accuracy → at-decision-time features **60.3%** (domain-plausible); all three runs traceable | ~1 s each |
| Scale guard | `svc` on 113,769 rows → `rejected` with reason in 0.1 s (was: hours or OOM) | 0.1 s |
| Full orchestrated experiment (API) | 3 models × 3 seeds = 9 persisted runs; best `random_forest` **74.9% test accuracy**; per-model progress events; experiment `completed` | 121 s |

**Demo:** upload the S&P CSV → EDA → Clean (report shows every action) → Experiment panel → watch stages + per-model events → inspect best run metrics in History.

---

## Current focus

Updated as work progresses — no fixed timeline; we iterate fast and the
present is what counts.

- [x] Real-dataset hardening: cleaning policy (datetime + cardinality), model
      scale guards, per-model progress, job cancellation — S&P dataset runs
      end-to-end (`tests/test_real_data_hardening.py`)
- [x] Documentation set: README + architecture diagram, user guide (UI / CLI /
      API / MCP), global roadmap, codebase guide rebalance
- [x] Multi-Kaggle proof (P3.7): churn / housing / attrition end-to-end, each
      with a generated notebook
- [x] Generated experiment notebooks (P3.6): verified exact metric
      reproduction on the S&P dataset
- [x] Agent-connected runs: experiments driven by local Ollama and OpenRouter
      (GLM) with per-interpretation token/model telemetry recorded
- [x] Workspace UI (P4.A–F): React rebuild, streaming agent chat with
      directives and telemetry, proposal→experiment runs, Kaggle import,
      parquet support, MCP panel
- [ ] D1 demos: scripted demo (direct run → MCP → context search) polished
      for the defense + screenshots of the new UI
- [ ] Fresh-venv install verification + demo rehearsal