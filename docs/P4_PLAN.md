# P4 Plan — UI Rework

> Binding plan for the UI rebuild. Stack decision (approved): React 18 +
> TypeScript + Vite + hand-rolled "Breeze" CSS tokens (no Tailwind, no
> component library) + Recharts. FastAPI keeps serving a static build;
> node is dev-only. Breaks the P0 "vanilla/no-toolchain" constraint
> deliberately (see AGENTS.md working mode).

## Goal

Replace the 11-panel dashboard with a 5-view experiment-centric workspace:
one deterministic pipeline, three ways in, personality via precision and
motion — not glassmorphism.

## IA

- **Mini-dock (56px)**: brand · Global Agent (chat drawer) · Admin · health.
- **Sidebar, two folders**:
  - **Deterministic** → Data (upload, preview, EDA, charts, clean + report) ·
    Model Lab (deterministic try-all + comparison)
  - **Agentic** → Experiments (Plan → Run with live sub-agent pipeline →
    History + feedback) · Proposals
- **Admin**: Models (registry → Metrics · Artifacts · Predict · Evidence) ·
  Context (search + sessions) · Tools (Sandbox playground, de-emphasized).
- **Removed**: Benchmarks panel (scripts remain), Coding Agent panel (content
  → Evidence tab), static pipeline diagram, Workflow placeholder card,
  duplicate dataset selects.

## Status: P4.A–F implemented (2026-09-01). See ROADMAP.

## Phases

### P4.A — Scaffold
- `web/` Vite + React + TS project; `theme/breeze.css` tokens; dock + sidebar
  shell with empty views; FastAPI serves dist (`/`) with committed
  `fallback.html` when unbuilt; `/static` mount → dist; vanilla files deleted;
  `scripts/build_ui.sh`; UI tests rewritten to the new contract; AGENTS/README
  build instructions.

### P4.B — Deterministic folder
- Data view: upload, list, sortable preview (capped), EDA sections, Recharts
  histogram, SVG correlation heatmap, Clean + `cleaning_report` display.
- Model Lab: job type `try_all` in `JobManager` (dry-run try-all, per-model
  events, cancellable) + comparison table/bars view.

### P4.C — Agentic folder
- Experiments: plan form (dataset/target/goal/provider) → run (stage pipeline
  + sub-agent cards + per-model SSE events + cancel) → history + feedback.
- Proposals: list, detail, approve/reject/approve-and-run.

### P4.D — Chat UI
- Chat drawer consuming P3 `POST /agent/chat`: conversation, citations,
  `run_python` code/result rendering, proposal links.
- Experiment Run view shows P3.4 LLM interpretations when present.

### P4.E — Admin + polish
- Models (registry, detail tabs incl. Evidence), Context (search + sessions),
  Sandbox playground; read-only notebook viewer for P3.6 `report.ipynb`
  artifacts; empty states; screenshots for docs; fresh-venv check.

## File map

```text
web/                                    # new source (committed)
  package.json, vite.config.ts, tsconfig.json
  src/ main.tsx, App.tsx, api.ts
      theme/breeze.css
      views/ Data.tsx ModelLab.tsx Experiments.tsx Proposals.tsx Models.tsx Context.tsx Sandbox.tsx
      components/ Dock.tsx Sidebar.tsx ChatDrawer.tsx StagePipeline.tsx ...
thelab/model_service/
  static/                               # build output (gitignored)
  fallback.html                         # committed
  app.py                                # / serves dist or fallback; /static mount
scripts/build_ui.sh                     # npm ci && npm run build
thelab/ide/jobs.py                      # "try_all" job type (P4.B)
tests/test_model_service_ui.py          # rewritten contract
docs/P4_PLAN.md                         # this file
```

## P4.F — Flow cohesion (implemented 2026-09-02)

Driven by first-review findings; keeps the app honest and connected:

| # | Work item | Notes |
|---|---|---|
| 1 | Streaming chat | `POST /agent/chat/stream` (SSE): tool progress live, `max_steps` 12, EDA/context memoization per session, markdown rendering, expandable drawer, multi-line input, style/role directives, usage+token+time telemetry, **conversation persisted** across drawer open/close, **exchanges indexed** into the context store |
| 2 | Proposal → Experiment | `POST /proposals/{id}/run-as-experiment`: approval executes a **first-class experiment** (job-backed, SSE stage pipeline, best-run + generated notebook) — replaces the opaque synchronous batch run; inline **Approve & run** button inside chat messages (proposal ids carried in tool trace) |
| 3 | Proposals merged into Experiments | Tab row: Plan / Run / Proposals / History; actions at top; newest-first; filters by dataset + date; Proposals removed from sidebar |
| 4 | Dataset context shared | Lifted state in App: Data ↔ Experiments keep the same dataset/target until changed; target dropdowns from dataset columns |
| 5 | Data additions | Kaggle import form (link/snippet/slug → ingest + context pack); **parquet** upload/list/preview/EDA/clean→CSV (`pyarrow` dep); chat tool `clean_dataset` (agent-cleaned data lands in Data viewer) |
| 6 | MCP panel | Admin inventory of the 7 stdio servers + tools + how to connect |
| — | Providers | Ollama model discovery (`/api/tags` probe) + OpenRouter public catalog dropdown; `.env` loader accepts `export KEY=…`; `OPENROUTER_API_KEY` alias; **loud provider failures** (named provider + hint), no silent fallback; provider+model persisted per experiment and reused by feedback iterations |

## P4.G — Streaming tokens + Kaggle MCP (implemented 2026-09-02)

| # | Work item | Notes |
|---|---|---|
| 1 | Streaming LLM tokens | `LLMProvider.stream()` (Ollama NDJSON + OpenAI-compat SSE, non-streaming fallback in `provider.default_stream`); `chat()` forwards token deltas as `{"type": "token"}` events; the chat drawer renders the answer progressively with a pulse cursor; token streams also cover sub-agent interpretation calls |
| 2 | Kaggle MCP integration | `thelab/agents/remote_mcp.py`: streamable-HTTP JSON-RPC handshake (initialize → tools/list → tools/call, session-id handling, SSE + JSON body parsing). Configured via `THELAB_REMOTE_MCP_SERVERS` JSON in `.env`. Discovered tools are merged into the chat agent's tool set (name-spaced `kaggle__*`), probed fail-soft; `GET /mcp/remote` reports connection status + tool inventory in the MCP panel. Verified live: 71 Kaggle tools discovered; `kaggle__search_content` called end-to-end |

Deferred: deeper Admin panel work, job eviction/heartbeat, per-session chat
memory across page reloads.

## P4.H — Benchmark doc + demo (2026-09-02)

- `docs/BENCHMARK_LOCAL_VS_CLOUD.md`: Ollama vs OpenRouter side-by-side (agent quality, token usage, multi-dataset results)
- `examples/notebooks/03_benchmark_comparison.ipynb`: companion notebook
- `scripts/demo_defense.sh`: full defense demo (RQ1→RQ3→multi-agent→notebook)

## Out of scope

Agent→training execution (LLMs never train models directly), streaming chat
UI, benchmarks UI, multi-user/auth, cloud deployment.

## Verification

```bash
cd web && npm ci && npm run build       # produces static dist
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
# Manual: thelab-model-service → all five views; UI-less fallback via GET /
```
