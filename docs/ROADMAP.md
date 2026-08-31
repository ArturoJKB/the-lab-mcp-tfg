# The Lab — Roadmap

Global roadmap: what was built (P0 → P1 → P2), what is current, and how work
is done now. Historical slice/phase records live in [`docs/legacy/`](legacy/);
they are context for the thesis document, not binding for new code.

## Status legend

- `done` — implemented and verified.
- `planned` — agreed, not started.

## Slice map

| Implementation slice | Phase | Status | Focus |
|---|---|---|---|
| Slice 0–1.5 | P0 | done | Contracts, workspace, `thelab run model`, TaskSpec |
| Slice 2–4.1 | P0 | done | MCP reuse, context store + CLI, read-only `context_mcp` |
| Slice 5–6 | P0 | done | Local UI, agent panels, thesis evaluation protocol |
| Slice 7–12 | P0 | done | Hardening, registry, batch runner, inspect/predict/compare, Python API |
| M1 | P1 | done | Task-type generalization (classification + regression) |
| L1 | P1 | done | Agent harness + LLM provider protocol (mock) |
| A1 | P1 | done | OpenAI-compatible LLM provider adapter |
| S1 | P1 | done | Deterministic EDA skill pack |
| A2 | P1 | done | Worker agent + experiment proposals |
| L2 | P1 | done | Context writer MCP |
| A3 (+3.1–3.4) | P1 | done | Global agents (researcher + diagnosis) + hardening: prior-run grounding, hyperparameter grids, JSON repair, Ollama + OpenRouter adapters |
| B1 | P1 | done | Cross-domain benchmark suite (deterministic + agent-boosted) |
| U1 | P1 | done | UI v2 dashboard |
| D1 | P1 | planned | Demos and notebook |
| P2 Phase 1 | P2 | done | Dataset upload + deterministic EDA panel |
| P2 Phase 2 | P2 | done | Agent goal launcher + deterministic training + cleaning |
| P2 Phase 3 | P2 | done | Pipeline diagram + background jobs + SSE execution view |
| P2 Phase 4 | P2 | done | Code sandbox (`thelab/sandbox`) + agent iteration on runs |
| P2 Phase 5 | P2 | done | CSV viewer, SVG charts (histogram/heatmap), run comparison |
| P2 Phase 6 | P2 | done | Agent orchestration: `agent_mcp`, `ExperimentOrchestrator`, unified `/experiment/*` API + UI panel |
| P2 Phase 6.5 | P2 | done | Real-dataset hardening: cleaning policy, model scale guards, per-model progress, job cancellation, UI consolidation, user guide |
| P3 | P3 | done | Multiagentic features: grounded chat agent, `run_python` sandbox tool, `propose_experiment` tool, LLM-interpreted sub-agents (`docs/P3_PLAN.md`) |
| P3.5 | P3 | done | Kaggle dataset ingestion + web-context pack for the global agent (`docs/P3_PLAN.md` §P3.5) |
| P3.6 | P3 | done | Generated experiment notebooks per completed run + read-only UI viewer (`docs/P3_PLAN.md` §P3.6) |
| P3.7 | P3 | done | Multi-Kaggle pipeline proof: 3 public datasets end-to-end (churn / housing / attrition), each with a generated notebook; cleaning policy gained constant-column drop (`docs/P3_PLAN.md` §P3.7) |
| P4 | P4 | planned | UI rework: React/TS/Vite workspace, 5 views, Breeze theme, chat UI; P4.E includes the P3.6 notebook viewer (`docs/P4_PLAN.md`) |

## Phase summaries

### P0 — Local-first data-to-model factory

Typed contracts (`TaskSpec`, `RunManifest`, `ArtifactRef`, `DatasetSpec`,
`ModelSpec`, `LogEntry`), the deterministic training pipeline with full run
artifacts, four read-only MCP servers, the SQLite+FTS5 context store with
redaction, the local model service + dashboard, read-only agent panels, and
the automated RQ1–RQ3 evaluator. Hardening slices added path-safety,
inference validation, the model registry, batch runs, and the exploratory
surface (`inspect`/`predict`/`compare`, `thelab.quick`, notebook).
Details: `docs/legacy/SLICE*.md`, `docs/legacy/PRD_P0.md`.

### P1 — Agentic layer

Task-type generalization (classification + regression, 9 models), the agent
harness with a typed `LLMProvider` protocol and four adapters (mock,
OpenAI-compatible, Ollama, OpenRouter), the WorkerAgent with EDA-grounded
experiment proposals and approval records, the deterministic EDA skill pack
behind `eda_mcp`, the context-writer MCP with server-side redaction, global
agents (researcher, diagnosis) with grounding checks, a cross-domain
benchmark suite, and the UI v2 dashboard. Details: `docs/legacy/Slice*.md`,
`docs/legacy/P1_PLAN.md`.

### P2 — Agentic ML IDE

Dataset upload + EDA panel, goal launcher + deterministic training +
cleaning, background jobs with SSE, the AST-restricted code sandbox + agent
iteration, the CSV viewer with SVG charts, and agent orchestration
(`agent_mcp`, `ExperimentOrchestrator`, unified `/experiment/*` API and
Experiment panel). Phase 6.5 hardened the whole thing for real data:
datetime/cardinality-aware cleaning with an audit report, per-model scale
guards, cooperative cancellation, UI consolidation, and the user guide.
Details: `docs/legacy/P2_*.md`.

## Current scope

See [`docs/THESIS_MAP.md`](THESIS_MAP.md) → "Current focus". Small, dynamic
changes; no binding phase plans.

**Formally descoped** (documented limitations, not work items): sub-agent
subprocess isolation, Experiment-panel full consolidation of every legacy
panel, sandbox OS-level confinement (compute isolation only — see
`docs/legacy/P2_AUDIT.md`).

## Working mode

Development is **dynamic**: small, focused changes instead of planned phases.
Implement exactly what is asked, keep the suite green, update docs when
behavior changes. See [`AGENTS.md`](../AGENTS.md).
