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
