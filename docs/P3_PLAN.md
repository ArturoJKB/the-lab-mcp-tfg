# P3 Plan — Multiagentic Features

> Binding plan for the P3 phase. Light by design: scope + file map + verification.
> Old UI stays untouched; everything is verified via tests and HTTP calls.

## Goal

Make "multi-agent" literally true: a grounded chat agent that reads, computes
(in the sandbox), and proposes experiments; sub-agents that reason over their
deterministic outputs. LLMs decide; deterministic code executes.

## Slices

### P3.1 — Chat service + endpoint
- `thelab/agents/chat.py` — provider tool-loop (bounded steps, tool allowlist,
  grounding check on cited run ids/metrics) with plain async tool callables:
  - `search_context(query, limit)` — ContextReader
  - `list_recent_runs(limit)` / `get_run_summary(run_id)` — workspace helpers
  - `dataset_eda(dataset_id, target?)` — `run_eda`
- `POST /agent/chat` — `{message, history[], provider, dataset_id?}` →
  `{answer, citations[], tool_calls[], proposal_id?}`. Sync v1 (no streaming).
- Provider factory: mock (tests) / ollama / openrouter / openai_compat.

### P3.2 — `run_python` sandbox tool
- Harness tool: agent writes pandas code → executed via `run_in_sandbox`
  against a **read-only copy** of the selected dataset (copied into the
  sandbox temp workspace; never writes back to uploads).
- Stdout + final result returned to the LLM as tool result; sandbox safety
  unchanged (deny-by-default imports, RLIMIT, timeout).

### P3.3 — `propose_experiment` chat tool
- Chat can create a WorkerAgent proposal → returns `proposal_id`.
- User approves/runs in Proposals (approval boundary preserved).

### P3.4 — LLM-interpreted sub-agents
- Orchestrator passes provider; when ≠ mock, each sub-agent adds one LLM
  interpretation over its deterministic output (EDAAnalyst → findings,
  FeatureEngineer → cleaning rationale, ModelSelector → recommendation),
  persisted in `experiment.sub_agent_results`.
- On LLM failure → deterministic text fallback; execution never blocks.

### P3.5 — Kaggle dataset ingestion + web context
- Goal: from a Kaggle slug (e.g. `erfan4524/e-commerce-sales-data-analysis-and-eda`),
  The Lab downloads the dataset into uploads, builds a **dataset context pack**
  (page description + tags + file metadata + local profile: shape/dtypes/head),
  indexes it into the context store, and exposes it to the chat agent via a
  `get_dataset_context` tool — so the global agent can propose experiments
  grounded in the dataset's own documentation.
- `thelab/ide/kaggle_api.py`:
  - `ingest_kaggle_dataset(slug, file_path?)` — kagglehub adapter → CSV in
    `data/uploads/`, returns dataset_id + profile. Network only here,
    explicit user action.
  - `fetch_kaggle_page_context(slug)` — httpx GET, parse embedded state JSON
    (description markdown, tags, file metadata). Fail-soft.
  - `build_context_pack(...)` — merge web + local context, save
    `data/uploads/<name>.kaggle.json`, index event into the context store
    (searchable), return pack.
- `POST /datasets/ingest-kaggle {slug, file_path?}`; chat tool
  `get_dataset_context(dataset_id)`.
- Dependency: `kagglehub[pandas-datasets]` (explicitly requested). Page fetch
  reuses `httpx`. Tests mock the adapter and the page fetch (no network).

### P3.6 — Generated experiment notebooks (current slice)

- Goal: every completed run / experiment ships with a reproducible **research
  notebook** artifact: `runs/<run_id>/report.ipynb`.
- Generated cells (hand-built nbformat-compatible JSON, no new deps):
  1. Title + manifest summary (run id, model, seed, dataset, status).
  2. Dataset load cell (path from `inputs.json`).
  3. Reproduce cell: `run_model(...)` with the exact recorded parameters.
  4. Metrics + validation report display.
  5. Artifacts index (`model_card.md`, contracts).
  6. Findings: sub-agent LLM interpretations / context notes when present.
- Endpoint: `GET /runs/{run_id}/notebook` (generated on demand).
- UI (P4.E): read-only notebook viewer in run detail.
- Future work (out of scope): executing notebook cells sequentially inside the
  sandbox (the sandbox runs single snippets today; per-cell state is a bigger
  feature).
- Reference implementation of the target format:
  `examples/notebooks/02_kaggle_experiment.ipynb` +
  `examples/kaggle_experiment.py`.

### P3.7 — Multi-Kaggle pipeline proof (done, 2026-08-31)

- Goal: prove the full journey (ingest -> context pack -> clean -> agent
  proposal -> approve & run -> generated notebook) on diverse public data,
  recorded as thesis evidence.
- `examples/kaggle_experiment.py` is parameterized (slug + target via argv).

**Recorded results (all end-to-end, live Kaggle download + page context):**

| Dataset | Shape | Task (auto) | Best result | Bug found & fixed |
|---|---|---|---|---|
| `shrutimechlearn/churn-modelling` (10,000 × 14) | classification | random_forest Acc 0.862, F1 0.742 | — |
| `camnugent/california-housing-prices` (20,640 × 10) | regression | random_forest_regressor R² 0.817 (matches the textbook result cited in the dataset's own context) | — |
| `pavansubhasht/ibm-hr-analytics-attrition-dataset` (1,470 × 35) | classification | logistic_regression Acc 0.861, F1 0.679 | constant columns (`EmployeeCount`, `StandardHours`, `Over18_Y`) rejected by validation → **cleaning policy now drops constant feature columns** |

- All three runs produced valid generated notebooks (6 cells, nbformat 4)
  via `GET /runs/{id}/notebook` — the thesis appendix examples.
- Scope kept: bug fixed in the cleaning policy; nothing generalized beyond
  CSV ingestion.

## File map

```text
thelab/agents/chat.py          # new: tool loop + tools + provider factory
thelab/model_service/app.py    # POST /agent/chat
thelab/ide/orchestrator.py     # P3.4 interpretations
tests/test_agent_chat.py       # new: chat loop, tools, grounding, propose
tests/test_orchestrator.py     # extended: interpretations with mock
docs/P3_PLAN.md                # this file
```

## Out of scope

Streaming chat, diagnosis/iterate upgrades, chat UI (P4), agent→training
execution (LLMs never train models directly — thesis invariant).

## Verification

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_agent_chat.py tests/ -q
PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py
```
