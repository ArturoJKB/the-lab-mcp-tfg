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
| P4.H | P4 | done | Benchmark doc: local vs cloud LLM comparison + companion notebook (`docs/BENCHMARK_LOCAL_VS_CLOUD.md`) |
| RQ5 spike | P5 | done | Agent code-gen validity spike: GLM 3/3 valid, Lambda sandbox fix (`docs/RQ5_SPIKE_RESULTS.md`) |
| P3.7 | P3 | done | Multi-Kaggle pipeline proof: 3 public datasets end-to-end (churn / housing / attrition), each with a generated notebook; cleaning policy gained constant-column drop (`docs/P3_PLAN.md` §P3.7) |
| P4 | P4 | done (A–F) | UI rework: React workspace, 5 views, global-agent chat, flow-cohesion patch (P4.F) — `docs/P4_PLAN.md` |
| P5.A | P5 | done (2026-09-02) | Honesty fixes: real role prompts, single approval gate (agents can no longer self-execute training), feedback wiring, sandbox description accuracy — `docs/P5_PLAN.md` |
| P5.B | P5 | done (2026-09-03) | Agentic round: role agents over MCP, sandboxed generated code with deterministic validation, human approval gate, comparison artifact + UI approval flow; B7 sandbox artifact channel (large-dataset transforms) + B8 provenance policy (`mode: agentic\|degraded_deterministic`) — `docs/P5_PLAN.md` |
| P5.C | P5 | planned | RQ4–RQ6 evaluation: grounding ablation, agentic-vs-deterministic, multi-vs-single — `docs/P5_PLAN.md` |

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

### P4 — UI rework (Agentic ML workspace)

Full frontend rebuild: `web/` (React + TS + Vite, hand-rolled Breeze CSS,
no component library) served as a static build by FastAPI; node is dev-only.
Five views + a global-agent drawer, replacing the 11-panel P0 dashboard:

- **P4.A** — scaffold, dock + two-folder sidebar (Deterministic / Agentic),
  fallback page, vanilla UI deleted.
- **P4.B** — Data view (upload incl. parquet, Kaggle import + context pack,
  preview with horizontal scroll, EDA card grid, cleaning with audit report)
  and Model Lab (deterministic try-all job with per-model SSE + comparison bars).
- **P4.C** — Experiments (Plan / Run with live sub-agent stage pipeline /
  History / feedback iteration), provider setup (Ollama model discovery,
  OpenRouter catalog, loud provider failures with named causes).
- **P4.D** — Global-agent chat drawer: streaming tool progress, markdown,
  usage/token/time telemetry, style/role directives, inline proposal approval,
  conversation persisted across open/close, exchanges indexed into the
  context store.
- **P4.E** — Admin: Models (registry + Metrics/Artifacts/Predict/Evidence
  tabs with the generated-notebook viewer), Context (search + sessions),
  Sandbox playground, MCP server inventory panel.
- **P4.F (flow cohesion)** — proposals merged into Experiments; proposal
  approval runs a **first-class tracked experiment** (SSE stage pipeline,
  best-run + notebook); chat tool `clean_dataset` (agent-cleaned data lands
  in Data); dataset context shared across views; target as dropdown; streaming
  tool progress; `max_steps` raised with per-session tool memoization; pandas-3
  sandbox memory limit raised.

Details: `docs/P4_PLAN.md`.

### P5 — Real multi-agent orchestration (grounded autonomy)

Makes the thesis title literally true while keeping the deterministic factory
byte-for-byte unchanged as the baseline. First-review audit (2026-09-02) found
the agentic claims overstated (shared sub-agent prompts, self-approving
orchestrator paths, unread feedback) — P5.A closes every gap before new claims
are added. P5.B adds an agentic round after the deterministic batch: a context
pack (EDA brief + baseline metrics + prior-run evidence) seeds role-specialized
agents (Analyst, FeatureEngineer, ModelSelector) that work through the MCP
servers with per-role tool allowlists; agent-generated code runs only in
`thelab/sandbox` and is deterministically validated outside it; execution is
gated by a single human-approval chokepoint. P5.C turns it into measured
results: RQ4 (grounded vs ungrounded proposals), RQ5 (agentic capability,
validity + competitiveness bars), RQ6 (multi vs single-agent ablation) —
recorded for Ollama and OpenRouter separately, with the mock provider driving
the suite. Details: `docs/P5_PLAN.md`.

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
