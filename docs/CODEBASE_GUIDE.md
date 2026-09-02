# The Lab — Codebase Guide

Tour of the codebase by phase. The system evolved through three phases:
**P0** (local-first data-to-model factory), **P1** (agentic layer), **P2**
(agentic ML IDE). Historical per-slice records live in
[`docs/legacy/`](legacy/).

## How to use this guide

Read the **phase sections** in order, then the **public surface** and
**safety** inventories. Companion docs: [`docs/ROADMAP.md`](ROADMAP.md)
(history + status), [`docs/USER_GUIDE.md`](USER_GUIDE.md) (usage),
[`docs/THESIS_MAP.md`](THESIS_MAP.md) (concept → evidence).

---

## Architecture at a glance

```
CLI              MCP servers           HTTP service
 |                    |                      |
 thelab run model     data_catalog_mcp       thelab-model-service
 |                    model_registry_mcp     |
 thelab context       workspace_mcp          /experiment /jobs /datasets
 |                    context_mcp            |
 v                    agent_mcp ...          v
 runs/<run_id>/     .thelab/context/        static/ dashboard
```

- **Contracts** (`thelab/contracts/`) are imported everywhere.
- **Training pipeline** (`thelab/run/`) writes versioned run directories.
- **IDE backend** (`thelab/ide/`) powers the dashboard: datasets, EDA,
  cleaning, jobs, experiments, orchestration.
- **Agents** (`thelab/agents/`) propose and orchestrate; providers are
  pluggable (mock, Ollama, OpenAI-compatible, OpenRouter).
- **MCP servers** (`thelab/mcp/`, 7 stdio servers) expose everything to
  independent clients.
- **Sandbox** (`thelab/sandbox/`) runs LLM-generated code in an
  AST-restricted subprocess.

---

## Phase P0 — Local-first data-to-model factory

**Purpose:** typed, hash-verified, deterministic, auditable core.

### Key files

| File | Role |
|---|---|
| `thelab/contracts/` | `TaskSpec`, `RunManifest`, `ArtifactRef`, `DatasetSpec`, `ModelSpec`, `LogEntry` |
| `thelab/run/runner.py` | `run_model()` lifecycle; `try_all_models()` |
| `thelab/run/validate.py` | dataset validators; rejection is a valid outcome |
| `thelab/run/train.py`, `preprocess.py` | deterministic train/eval, `StandardScaler` pipeline |
| `thelab/run/artifacts.py` | artifact persistence + manifest assembly |
| `thelab/workspace/paths.py`, `hashing.py` | contained paths, SHA-256 |
| `thelab/context/` | SQLite+FTS5 store: `repository.py` (write), `reader.py` (read-only), `redaction.py`, `privacy.py` |
| `thelab/model_service/` | FastAPI service + dashboard (`app.py`, `static/`) |
| `scripts/evaluate_thesis.py` | RQ1–RQ3 automated checks |

### Run artifacts (`runs/<run_id>/`)

`manifest.json`, `task_spec.json`, `events.jsonl`, `inputs.json`,
`data_profile.json`, `dataset_contract.json`, `training_config.json`,
`metrics.json`, `validation_report.json`, `model.joblib`, `model_card.md`.

Determinism: fixed `random_state` for split + model; seed, configuration and
dependency versions persisted. Rejected runs keep their evidence.

---

## Phase P1 — Agentic layer

**Purpose:** generalize the factory and add the agents on top of it.

### Task types & registry (M1)

- `thelab/run/task_type.py` — auto classification/regression inference (≤20 classes).
- `thelab/run/model_registry.py` — 9 estimators (classification + regression),
  `*_probability` variants, **per-model scale guards** (`max_train_rows`).
- Regression metrics (RMSE/MAE/R²); model/task mismatches rejected traceably.

### Agent harness & providers (L1, A1, A3.2, A3.4)

- `thelab/agents/provider.py` — `LLMProvider` Protocol, typed turns
  (`AgentMessage`, `ToolCallRequest`, `AgentTurn`).
- `thelab/agents/harness.py` — bounded tool loop (max steps), read-only tool
  allowlist, **grounding checks** (cited run_ids and metric claims verified
  against `metrics.json`).
- `thelab/agents/providers/` — `openai_compat.py` (base adapter, retries on
  429/5xx only), `ollama.py` (native `/api/chat`), `openrouter.py`
  (extra headers), `mock.py`. Providers fail fast on config errors; no prompt
  content in logs.
- `thelab/agents/cli.py` → `thelab-agent` (mock / worker / researcher /
  diagnosis modes).

### Worker & proposals (A2, A3.1, A3.3)

- `thelab/agents/worker.py` — `WorkerAgent` produces `ExperimentProposal`
  (dataset, target, model grid, seeds, hyperparameter grid) grounded in EDA +
  prior runs; `ProposalStore` persists proposals and approval records with
  principal + timestamp.
- `thelab/agents/json_repair.py` — conservative LLM-JSON repair; deterministic
  fallback proposal if the model output is unusable.
- Proposals never execute directly: approval translates 1:1 into a batch
  config for the `BatchRunner`.

### EDA skills & context writer (S1, L2)

- `thelab/eda/skills.py` — six deterministic skills (missing profile,
  correlations, class balance, outliers, leakage suspects, feature types);
  `thelab/mcp/eda_mcp.py` exposes them with path-safety.
- `thelab/mcp/context_write_mcp.py` — single append tool, server-side
  redaction, canonical `/log` schema; the read-side `context_mcp` stays
  read-only.

### Global agents (A3)

- `thelab/agents/global_agents.py` — Researcher (answers from allowlisted
  artifacts with claim-ID citations) and DiagnosisAgent (approves/rejects
  failure follow-ups via the same proposal records).

### Benchmarks & UI (B1, U1)

- `scripts/prepare_b1_datasets.py`, `scripts/run_b1_benchmark.py` —
  deterministic vs agent-boosted comparison across datasets (California
  Housing, Breast Cancer, Wine Quality); outputs under `benchmarks/b1/`.
- UI v2: sidebar, Benchmarks / Proposals / Agent Sessions panels (read-only
  endpoints, no new server).

### Exploratory surface

`thelab/quick.py` (`experiment`, `compare`, `list_models`), `thelab inspect`,
`thelab predict`, `thelab compare`, `--dry-run` / `--try-all`,
`examples/notebooks/01_quick_start.ipynb`.

---

## Phase P2 — Agentic ML IDE

**Purpose:** an interactive IDE on the model service, ending in agent
orchestration.

### Backend modules (`thelab/ide/`)

| Module | Role |
|---|---|
| `datasets.py` | upload/sanitize/resolve (`uploads/<basename>`, `fixtures/<basename>`), `dataset_id_to_relative_path` |
| `eda_api.py` | EDA HTTP wrapper |
| `cleaning.py` | deterministic cleaning: drop missing targets/empty cols, datetime parsing → calendar features, cardinality-aware encoding (one-hot ≤ threshold, else frequency), numeric imputation; returns an audit `cleaning_report` |
| `worker_api.py`, `proposals_api.py`, `train_api.py` | goal launcher, approve/reject/run (+ atomic approve-and-run), direct deterministic training |
| `jobs.py` | async job manager (`train`, `batch`, `experiment`), SSE events, persisted summaries, cooperative cancellation |
| `viewer_api.py` | dataset preview + run comparison |
| `iterate_api.py` | agent iteration on completed runs |
| `orchestrator.py` | `ExperimentOrchestrator`: EDA → cleaning → try-all → approved batch training; `on_event` stage callbacks + cancellation |
| `experiment.py`, `experiment_api.py` | experiment state machine (`pending → planning → cleaning → training → evaluating → completed/failed/cancelled`, `iterating` on feedback) + HTTP-facing API |
| `sub_agents.py` | EDAAnalyst / FeatureEngineer / ModelSelector prompt contracts |

### Sandbox (`thelab/sandbox/`) + iteration (P2 Phase 4)

AST-restricted subprocess: deny-by-default imports, filtered builtins, blocked
`exec`/`eval`/dunder escapes, RLIMIT_AS + wall-clock timeout, per-run temp
dir. Provides **compute isolation**; OS-level filesystem confinement is a
documented limitation (`docs/legacy/P2_AUDIT.md`, finding BLK-01).

### Orchestration & agent MCP (P2 Phase 6)

- `thelab/mcp/agent_mcp.py` — `orchestrate_experiment`, `spawn_subagent`,
  `run_deterministic_skill`, `run_training_job`, `get_job_status`,
  `log_agent_activity` (routed through `context_write_mcp` validation +
  redaction).
- Experiment endpoints: `POST /experiment/run`,
  `GET /experiment/{id}/status|events|results`,
  `POST /experiment/{id}/feedback`, `GET /experiments`.

### Hardening for real data (P2 Phase 6.5)

- Cleaning policy above; scale guards above; per-model progress events;
  `POST /jobs/{id}/cancel`; `ExperimentState.CANCELLED`.
- UI: Experiment panel (Plan / Run / History) as the primary workflow;
  legacy goal-launcher/train cards removed; cancel buttons on run + job
  cards.
- Regression tests with an S&P-shaped synthetic dataset in
  `tests/test_real_data_hardening.py`.

### Audit results (`docs/legacy/P2_AUDIT.md`)

10 fixes applied during audit (XSS escapes, NaN-safe comparison endpoint,
sandbox hardening, job-task GC). Open documented findings: sandbox filesystem
confinement (BLK-01), absolute-path leakage in some error details (MAJ-01),
artifact-image endpoints (MAJ-02).

---

## Phase P4 — Agentic ML workspace UI (React)

**Purpose:** the P0-era 11-panel dashboard replaced by a 5-view workspace.
Source in `web/` (React + TS + Vite, strict TS, hand-rolled Breeze CSS — no
Tailwind/component library); FastAPI serves the built dist from `/static`
with a committed fallback page; node is dev-only (`scripts/build_ui.sh`).

| Area | Key files | Notes |
|---|---|---|
| Shell | `web/src/App.tsx`, `components/Dock.tsx`, `components/Sidebar.tsx` | mini-dock (brand · chat · admin toggle · health), Deterministic/Agentic folders, Admin group |
| API client | `web/src/api.ts` | typed `api()` wrapper over the HTTP JSON surface |
| Data view | `views/DataView.tsx` | upload (CSV + parquet), Kaggle import (link/snippet/slug → `ingest-kaggle` + context pack), preview (horizontal scroll), EDA card grid (missing/class-balance/correlation/outlier charts, leakage banner, stat chips), clean + audit report |
| Model Lab | `views/ModelLabView.tsx` + `components/ModelLabSection.tsx` | deterministic try-all via `try_all` job type (per-model SSE, cancellation, NaN-safe results, Recharts comparison) |
| Experiments | `views/ExperimentsView.tsx`, `components/StagePipeline.tsx`, `hooks/useExperimentStream.ts` | Plan (provider setup: Ollama model discovery, OpenRouter catalog) → Run (live stages + activity feed + cancel + best run + LLM interpretation cards) → Proposals tab → History; feedback iterations keep provider+model |
| Chat drawer | `components/ChatDrawer.tsx`, `hooks/useExperimentStream.ts` | `POST /agent/chat/stream` (SSE tool progress), markdown, directives (role/style), usage telemetry, always-mounted (conversation survives close), exchanges indexed into the context store, inline proposal approval |
| Admin | `views/ModelsView.tsx`, `ContextView.tsx`, `SandboxView.tsx`, `McpView.tsx` | registry detail tabs (Metrics/Artifacts/Predict/**Evidence** = generated notebook viewer), context search + sessions, restricted playground, MCP inventory |
| Jobs | `hooks/useJob.ts` | SSE consumption with polling fallback; job types: `train`, `batch`, `experiment`, `try_all`, `proposal_experiment` |
| Cleaning policy | `thelab/ide/cleaning.py` | datetime → calendar features, cardinality-aware encoding, **constant-column drop**, target-encoded output names (`*_cleaned_<target>.csv`), re-clean rejection |

Details: `docs/P4_PLAN.md`.

---

## Public surface inventory

### CLI commands

| Command | File |
|---|---|
| `thelab run model ...` (`--dry-run`, `--try-all`) | `thelab/cli.py` → `thelab/run/runner.py` |
| `thelab run batch --config ...` | `thelab/run/batch.py` |
| `thelab inspect` / `predict` / `compare` | exploratory slice |
| `thelab context index|search|show` | `thelab/context/cli.py` |
| `thelab proposals approve|reject|list|show` | `thelab/agents/worker.py` |
| `thelab agents ...` (mock/worker/researcher/diagnosis) | `thelab/agents/cli.py` |
| `thelab-model-service` | `thelab/model_service/cli.py` |
| `thelab-mcp-demo ...` | `thelab/mcp/demo_client.py` |
| `thelab-{data-catalog,model-registry,workspace,context,context-write,eda,agent}-mcp` | `thelab/mcp/*_mcp.py` |

### HTTP API

See [`docs/USER_GUIDE.md`](USER_GUIDE.md) — datasets/EDA/cleaning,
experiments, jobs (submit/status/cancel/SSE), models/predict, proposals,
sandbox, agent panels.

### MCP tools

| Server | Tools |
|---|---|
| `data_catalog_mcp` | `list_datasets`, `get_data_profile`, `get_dataset_contract` |
| `model_registry_mcp` | `list_models`, `get_model_manifest`, `get_model_card`, `get_model_metrics`, `predict` |
| `workspace_mcp` | `list_runs`, `get_run_manifest`, `list_run_artifacts`, `get_artifact`, `read_model_card` |
| `context_mcp` | `get_context_status`, `get_context_entry`, `search_context` |
| `context_write_mcp` | `append_session_summary` (validated + redacted) |
| `eda_mcp` | `missing_profile`, `correlation_hints`, `class_balance`, `outlier_scan`, `leakage_suspects`, `feature_types` |
| `agent_mcp` | `orchestrate_experiment`, `spawn_subagent`, `run_deterministic_skill`, `run_training_job`, `get_job_status`, `log_agent_activity` |

---

## Safety inventory

| Boundary | Where enforced |
|---|---|
| Path traversal in run IDs | `thelab/mcp/common.py`, `safe_run_dir` |
| Dataset upload sanitization + containment | `thelab/ide/datasets.py` |
| Artifact path containment | `thelab/workspace/paths.py`, `ArtifactRef` validation |
| Read-only context reads | `thelab/context/reader.py` (`mode=ro`, `query_only=ON`) |
| Secret redaction before storage | `thelab/context/redaction.py`, `context_write_mcp` |
| Privacy filtering (public+internal default) | `thelab/context/privacy.py` |
| HTTP artifact allowlist; `model.joblib` never served | `thelab/model_service/app.py` |
| Localhost-only bind | `thelab/model_service/cli.py` |
| Approved-only predict | `model_service/app.py`, MCP `predict` |
| LLM code execution only in sandbox | `thelab/sandbox/` (AST + RLIMIT + timeout) |
| Model/task mismatch + scale guards | `thelab/run/runner.py`, `model_registry.py` |
| Cooperative job cancellation | `thelab/ide/jobs.py`, `thelab/run/batch.py` |
| Agent grounding checks + approval records | `thelab/agents/harness.py`, `worker.py` |

---

## How to read the code by question

| "I want to understand…" | Start here |
|---|---|
| How a run is created | `thelab/run/runner.py` → `thelab/run/artifacts.py` |
| How determinism is guaranteed | `thelab/run/train.py`, `training_config.json` contents |
| How the experiment flow works | `thelab/ide/experiment_api.py` → `thelab/ide/jobs.py` → `thelab/ide/orchestrator.py` |
| How agents propose experiments | `thelab/agents/worker.py` |
| How MCP servers stay safe | `thelab/mcp/common.py`, then any `*_mcp.py` |
| How context privacy works | `thelab/context/privacy.py` → `reader.py` → `context_mcp.py` |
| How the UI talks to the backend | `thelab/model_service/static/app.js` → `app.py` |
| How RQ1–RQ3 are checked | `scripts/evaluate_thesis.py` → `docs/THESIS_EVALUATION.md` |

---

## Verification commands that should always pass

```bash
# Lint + types + full test suite
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q

# Thesis evaluation (RQ1 reproducibility, RQ2 MCP interop, RQ3 context retrieval)
PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py
```
