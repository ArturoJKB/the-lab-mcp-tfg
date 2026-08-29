# P2 Plan — Agentic ML IDE

> **Status:** approved for implementation  
> **Audience:** coding agent  
> **Authority:** This document supersedes informal chat proposals. Implement only the activated phase at a time.

## 1. Vision

Evolve `thelab-model-service` from a read-only dashboard into a **human-in-the-loop agentic workbench** for ML experiments. A student or data scientist can:

1. Upload a CSV dataset through the UI.
2. Run deterministic EDA and view structured results.
3. Launch a worker agent with a natural-language goal.
4. Review the agent's experiment proposal (models, seeds, rationale).
5. Approve or reject the proposal.
6. Watch the training pipeline execute step by step.
7. Iterate with sandboxed agent-generated code for richer EDA or custom models.
8. Explore datasets and results with a CSV viewer and charts.

## 2. Guiding principles

1. **Human-in-the-loop.** Every write and every code execution requires explicit user approval initiated from the UI.
2. **Local-first.** No cloud dependencies, no Docker required, no Kubernetes.
3. **Context engineering.** The UI surfaces structured context (dataset profile, prior runs, proposals, approvals) rather than unstructured chat.
4. **Reuse existing backend.** EDA skills, worker agent, proposals, batch runner, context store, and model service are reused.
5. **KDE Plasma / EndeavourOS aesthetic.** Dark, dense, monospace data, single accent color, no generic SaaS look.
6. **Preserve safety boundaries.** No arbitrary shell execution, no absolute paths in responses, no unapproved writes, default bind `127.0.0.1`.

## 3. Architecture

```text
User
  ↓
thelab-model-service (FastAPI)
  ↓
thelab/ide/     thelab/sandbox/
  ↓
thelab.eda      thelab.agents      thelab.run
  ↓
data/uploads/   proposals/         runs/<run_id>/
```

- **Existing model service** is extended with new IDE endpoints; no second UI server.
- **Frontend** stays vanilla HTML/CSS/JS with a small set of CDN libraries.
- **Background jobs** run training/batch tasks asynchronously so the UI remains responsive.
- **Sandbox** runs agent-generated Python in a restricted subprocess with temp workspace.

## 4. Tech choices

| Layer | Choice | Reason |
|---|---|---|
| Backend | Existing FastAPI + new `thelab/ide/` package | No new server process; reuses auth/bind/safety patterns. |
| Background jobs | `asyncio` task queue or `concurrent.futures.ProcessPoolExecutor` | Local-first; no Celery/RabbitMQ. |
| Code sandbox | Custom `thelab/sandbox/` restricted subprocess | Lighter than Docker/OpenSandbox/DeepSeek; Python-only; fits local agents. |
| CSV viewer | `neiki-table` Web Component (CDN) | Zero deps, dark theme, sorting/filtering/pagination/export. |
| Charts | `uPlot` or `Apache ECharts` (CDN) | Small, themeable via CSS variables. |
| Pipeline diagram | `mermaid.js` (CDN) or hand-rolled SVG | Good enough for train → validate → evaluate flow. |
| Code editor | Plain textarea first; optionally CodeMirror lite (CDN) | Avoid build step. |

## 5. Reference research

- **MLflow** — validated the run/artifact/metric tracking model; too large to adopt as a dependency.
- **McKinsey Ark** — validated declarative agents, multi-agent teams, persistent memory; too heavy (K8s) for local use.
- **Context Engineering (Boni García)** — framing discipline for the thesis; confirms that structured context, MCP tools, memory, and human-in-the-loop are the right pillars.

## 6. Phases

> **Status:** All five phases are implemented and verified.
> See `docs/P2_PHASE{1..5}_CONTEXT.md` for per-phase delivery summaries.

### Phase 1 — Dataset upload + EDA panel

**Goal:** user uploads a CSV and sees deterministic EDA results.

Backend:
- `POST /datasets/upload` — save CSV to `data/uploads/`, sanitize filename, validate CSV, return dataset id.
- `GET /datasets` — list uploaded + fixture datasets.
- `GET /eda/{dataset_id}` — run `thelab.eda.*` skills and return JSON.

Frontend:
- Upload dropzone in sidebar.
- Dataset list.
- EDA panel: missing values, feature types, class balance, correlations, outliers.

### Phase 2 — Agent goal launcher + proposals

**Goal:** user types a goal, worker agent proposes models, user approves/rejects.

Backend:
- `POST /agent/worker` — run `WorkerAgent.propose()` with dataset + target + goal.
- `POST /proposals/{id}/approve` — write approval artifact with `"principal": "ui"`.
- `POST /proposals/{id}/reject` — write rejection artifact.
- `POST /proposals/{id}/run` — translate to batch config and execute.

Frontend:
- Goal input form.
- Proposal card: goal, model grid, seeds, rationale.
- Approve / Reject / Run buttons.
- Job status indicator.

### Phase 3 — Pipeline diagram + execution view

**Goal:** visualize the ML workflow and see live status.

Backend:
- In-memory job queue / background runner.
- `POST /jobs` — submit a training/batch job.
- `GET /jobs/{job_id}/status` or SSE from `events.jsonl`.

Frontend:
- Pipeline diagram: Upload → EDA → Propose → Approve → Train → Validate → Evaluate.
- Each step shows status.
- Live log tail.

### Phase 4 — Code sandbox + advanced agent iteration

**Goal:** agent generates and runs Python code for richer EDA / custom models.

Backend:
- `thelab/sandbox/` module.
- `POST /sandbox/run` endpoint.
- `POST /agent/iterate` — given a completed run, ask agent to propose improvements using EDA + metrics.

Frontend:
- Code editor panel.
- Output/artifacts panel.
- “Iterate on run” button.

### Phase 5 — CSV viewer + visualizations

**Goal:** rich data exploration and model comparison.

Backend:
- Endpoints for model metrics comparison and artifact images.

Frontend:
- `neiki-table` CSV viewer.
- Charts: metric bars, correlation heatmap, feature distributions.
- Model comparison table.

## 7. Sandbox design

A restricted Python subprocess inspired by `pysandbox` and `safe-py-runner`:

- AST pre-check blocks `exec`, `eval`, `compile`, `__import__`, dunder escapes, dynamic `type()` classes.
- Restricted builtins: remove `open`, `eval`, `exec`, `breakpoint`, dangerous `getattr`.
- Import whitelist: `numpy`, `pandas`, `sklearn`, `matplotlib`, `seaborn`, `thelab.eda`, plus safe stdlib.
- Resource limits: timeout, memory cap, output size cap.
- Temp working directory per session; approved artifacts copied out.
- No network, no subprocess spawning, no writes outside temp dir.
- Captures stdout, stderr, return value, and artifacts.

## 8. Safety boundaries

- File uploads: CSV only, size cap, basename-only storage under `data/uploads/`.
- All writes (`approve`, `run`, `sandbox/run`) require explicit POST from UI.
- Approval artifacts record `"principal": "ui"` and timestamp.
- Sandbox: deny-by-default for imports/network/subprocess, temp workspace only.
- Default bind remains `127.0.0.1`.
- No absolute paths in API responses.
- No bash terminal in the UI. CLI remains available separately for power users.

## 9. File map

```text
docs/P2_IDE_PLAN.md
docs/P2_PHASE1_PLAN.md
docs/P2_PHASE1_CONTEXT.md

thelab/ide/
  __init__.py
  datasets.py
  eda_api.py
  jobs.py
  proposals_api.py
  agents_api.py
  sandbox_api.py

thelab/sandbox/
  __init__.py
  runner.py
  policy.py
  ast_check.py
  artifacts.py

thelab/model_service/app.py
thelab/model_service/static/index.html
thelab/model_service/static/app.js
thelab/model_service/static/styles.css

tests/
  test_ide_datasets.py
  test_ide_eda.py
  test_ide_jobs.py
  test_ide_proposals.py
  test_sandbox.py
```

## 10. Verification

For every phase:

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/evaluate_thesis.py
```

## 11. Phase activation record

- Phase 1 — Dataset upload + EDA panel: **done** (`docs/P2_PHASE1_PLAN.md`, `docs/P2_PHASE1_CONTEXT.md`)
- Phase 2 — Agent goal launcher + deterministic training: **done** (`docs/P2_PHASE2_PLAN.md`, `docs/P2_PHASE2_CONTEXT.md`)
- Phase 3 — Pipeline diagram + execution view: **done** (`docs/P2_PHASE3_PLAN.md`, `docs/P2_PHASE3_CONTEXT.md`)
- Phase 4 — Code sandbox + advanced agent iteration: **done** (`docs/P2_PHASE4_PLAN.md`, `docs/P2_PHASE4_CONTEXT.md`)
- Phase 5 — CSV viewer + visualizations: **done** (`docs/P2_PHASE5_PLAN.md`, `docs/P2_PHASE5_CONTEXT.md`)
