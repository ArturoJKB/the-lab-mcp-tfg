# P1 Plan — Unified (M1 → D1)

> **Status:** draft — **not activated**  
> **Last updated:** 2026-08-21  
> **Audience:** coding agent (implement only the activated slice)  
> **Authority:** Once a slice is activated (its row added to `docs/ROADMAP.md`), this
> document is binding for that slice and supersedes informal chat proposals.
> **Prerequisite reading:** `AGENTS.md`, `docs/PRD_P0.md`, `docs/Agents.md`

---

## §1 Decisions & Rules

### 1.1 Locked product decisions (do not re-ask)

1. **Task types:** classification and regression are both first-class after M1.
   Task-type inference is deterministic with explicit override.
2. **New models in M1:** `linear_regression`, `ridge`,
   `random_forest_regressor`, `hist_gradient_boosting_regressor` (regression);
   `hist_gradient_boosting` (classification). Nothing else — no KNN, no
   GaussianNB, no XGBoost/LightGBM (dependency lock).
3. **LLM provider strategy:** L1 defines an `LLMProvider` **Protocol only** —
   no vendor SDK, no network calls; a scripted/mock provider is the test
   double. A1 adds exactly one real adapter: OpenAI-compatible HTTP, covering
   local (Ollama, development) and cloud endpoints (final demo results).
4. **Finance demo boundary:** credit-risk / default classification trained by
   the factory and consumed by an agent via `model_registry_mcp.predict`. No
   trading, brokers, order execution, or autonomous financial strategies (PRD).
5. **Retrieval engine:** SQLite FTS5 (with prefix-expansion and LIKE fallback).
   Embeddings are out of scope until L4 is activated with a written PRD
   amendment.
6. **UI stack:** vanilla HTML/CSS/JS on the existing FastAPI static serving.
   Hand-rolled SVG charts. No chart libraries, no npm/Vite, no frontend build
   toolchain. Design language: dense, information-first, dark surface, single
   accent color, monospace data (KDE Plasma-inspired; explicitly not a generic
   SaaS look).
7. **Agent communication:** all inter-agent tasking flows through MCP surfaces
   and typed artifacts. Free-form chat messages are never the source of truth
   (PRD architecture rule).
8. **Dependencies:** no new runtime dependencies without explicit human
   approval and a `requirements.lock` update.

### 1.2 Safety boundaries (all slices)

1. Read-only by default; writes only via explicitly activated surfaces (L2
   server, A2 approval flow).
2. Redact before storage and before any provider call
   (`thelab/context/redaction.py`).
3. Project-relative paths only in persisted artifacts; reject absolute and
   parent-traversal paths.
4. Bounded loops, bounded query sizes, bounded payloads at every agent
   touchpoint.
5. Refused actions are valid, traceable outcomes and must be persisted.
6. No arbitrary shell execution, no arbitrary LLM-generated code execution,
   ever.

### 1.3 Definition of done (per slice)

1. Implement only the activated slice's tasks.
2. Full suite green: `ruff check thelab tests scripts`, `mypy thelab`,
   `pytest tests/ -q`.
3. Run the documented example command.
4. Write `docs/Slice<name>_CONTEXT.md`: changed files, test output,
   limitations, smallest next step.
5. Report changed files, verification results, limitations — and stop.

### 1.4 Roles

| Role | Does | Does not |
|---|---|---|
| Human | Activates slices, answers approval requests, reviews demos | Implements code |
| Coding agent | Implements the activated slice + tests + handoff doc; stops | Starts the next slice, expands scope, edits PRD/ROADMAP status unilaterally |
| Audit agent | Verifies the slice against this plan after green tests | Implements code |

---

## §2 Stage 1 — Generalize & Connect

*The factory becomes task-general (M1) and gains a pluggable brain (L1, A1).*

### M1 — Task-type generalization `[BINDING]`

**Goal:** classification **and** regression are first-class across validation,
training, metrics, artifacts, compare, batch, MCP, CLI, and UI.

**Non-goals:** no estimators beyond §1.1.2; no hyperparameter search; no
time-series support.

**T0 — Contracts and registry**

- `ModelEntry` (in `thelab/run/model_registry.py`) gains
  `task_type: Literal["classification", "regression"]`; existing entries
  default to `"classification"`.
- Register: `linear_regression`, `ridge`, `random_forest_regressor`,
  `hist_gradient_boosting_regressor` (regression); `hist_gradient_boosting`
  (classification).
- `*_probability` suffix on a regression model raises a clear `ValueError`.

**T1 — Deterministic task-type inference**

- Single source of truth (e.g. `thelab/run/task_type.py`): target column
  non-numeric **or** distinct-value count ≤ `_CLASSIFICATION_MAX_CLASSES`
  (documented constant, default 20) → classification; else regression.
- Surface: `--task-type auto|classification|regression` on
  `thelab run model`; same inference used by batch runner and Python API;
  `auto` is the default.
- Resolved task type persisted in `training_config.json`, `inputs.json`, and
  the manifest.

**T2 — Validation**

- `sensible_target_type`: task-aware branch — regression requires numeric
  target with variance > 0; classification keeps current checks.
- `stratified_split_feasible`: evaluated for classification only.
- Regression-specific checks: numeric target, no missing/inf target values.

**T3 — Training and metrics**

- `train.py` branches on task type:
  - Classification: current behavior (LabelEncoder, stratified split,
    accuracy/F1).
  - Regression: no LabelEncoder, plain seeded shuffle split, metrics = RMSE,
    MAE, R² (train and test).
- `metrics.json` gains regression keys; classification keys unchanged.
  Consumers treat metric sets as task-dependent.

**T4 — Downstream surfaces**

- `compare.py`: grouped table (section per task type) with task-appropriate
  metric columns.
- Model cards: task type + task-appropriate metrics.
- Batch runner and batch report: pass through inferred/explicit task type.
- `model_registry_mcp.list_models`: each entry gains `task_type`.
- UI metrics panel renders per-task-type metrics (minimal change; full rework
  is U1).

**T5 — Fixtures, tests, determinism**

- New fixture: small regression CSV (~50 rows) under `data/fixtures/`.
- Tests: inference edge cases (numeric low-cardinality, high-cardinality,
  non-numeric), regression run end-to-end, probability-suffix rejection,
  compare grouping, MCP `task_type` field, determinism (same seed twice →
  identical RMSE within tolerance).

**Verification example:**

```bash
thelab run model --dataset <regression-fixture> --target <col> --model ridge --seed 42 --output runs
thelab compare
```

### L1 — Agent harness + protocol `[BINDING]`

**Goal:** a local harness connecting a pluggable LLM provider to the four
existing MCP servers, enforcing grounding and approval rules. With the mock
provider it demonstrates the full loop deterministically and offline:
goal → tool discovery → tool calls → grounded answer (or approval request).

**Non-goals:** no real adapter (that is A1), no streaming UI, no conversation
persistence, no new MCP servers, no workspace writes.

**Contracts — new module `thelab/agents/provider.py`:**

```python
class LLMProvider(Protocol):
    def complete(
        self, messages: list[AgentMessage], tools: list[ToolSpec]
    ) -> AgentTurn: ...
```

Typed Pydantic contracts (repo style): `AgentMessage` (role, content, optional
tool_call_id), `ToolSpec` (name, description, JSON schema), `ToolCallRequest`
(tool name + arguments), `AgentTurn` (text or tool-call list; never both
empty).

**Harness — new module `thelab/agents/harness.py`:**

- Discovers tools from the four stdio MCP servers using the transport pattern
  proven in `thelab/mcp/demo_client.py` and `tests/test_mcp.py`.
- Loop: messages → `provider.complete(messages, tools)` → execute returned
  tool calls against the matching server → append results as tool messages →
  repeat (bounded, default max 8 iterations).
- Grounding check on final text turns: every referenced `run_id` must exist
  and be readable via `workspace_mcp.get_run_manifest`; detectable metric
  claims must match that run's `metrics.json` within tolerance. Failure raises
  `GroundingError`; the harness returns a structured refusal.
- Read-only enforcement: tools restricted to a pinned allowlist equal to the
  union of the four servers' current read-only tool lists.

**Approval gate:** a provider turn requesting any non-allowlisted tool is not
executed. The harness persists an `ApprovalRequest` (JSON under
`.thelab/approvals/`, project-relative: tool, arguments, timestamp, session
id), prints the request path, halts with exit code 2. No auto-approval path.

**Entry point:** `thelab-agent "goal"` with `--provider mock` (only choice in
L1), `--max-steps`, `--runs-root`. The mock provider is a deterministic script
defined per test/demo fixture.

**Tasks:**

| # | Task | Verification |
|---|---|---|
| T0 | Contracts + Protocol; unit tests | `pytest tests/test_agents_contracts.py` |
| T1 | MCP discovery + pinned allowlist | discovered names equal pinned set |
| T2 | Tool execution loop, bounded steps | scripted 3-step sequence against real servers |
| T3 | Grounding checker + refusal path | answer citing nonexistent `run_id` → refusal |
| T4 | Approval gate + persisted request | disallowed tool → file created, exit 2, nothing executed |
| T5 | Entry point + demo fixture + handoff doc | documented example runs green offline |

Tests: `tests/test_agents_contracts.py`, `tests/test_agents_harness.py`;
reuse in-process MCP fixtures from `tests/test_mcp.py`.

### A1 — Real LLM adapter `[BINDING]`

**Goal:** one OpenAI-compatible HTTP adapter implementing the L1
`LLMProvider` protocol, working unchanged against Ollama (development) and
cloud endpoints (final demonstrations). `httpx` is already in
`requirements.lock`; no new dependencies.

**T0 — Module and transport**

- New package `thelab/agents/providers/` with `openai_compat.py`.
- Class `OpenAICompatProvider(LLMProvider)`:
  - Configuration from env with explicit constructor override:
    `THELAB_LLM_BASE_URL` (required, no default — pointing at a cloud
    provider must be an explicit act), `THELAB_LLM_API_KEY`
    (required, non-empty; any value for Ollama), `THELAB_LLM_MODEL`
    (default `qwen3:4b`), `THELAB_LLM_TIMEOUT_SECONDS` (default 120).
  - Missing/empty required env → immediate clear `LLMProviderError`.
- POST `{base_url}/chat/completions` with tool definitions; bounded retries:
  max 3 attempts, exponential backoff (0.5s × 2ⁿ), retry only on 429, 5xx,
  and network errors; never on 4xx validation responses.

**T1 — Request/response mapping**

- Messages → OpenAI wire format (`system|user|assistant|tool`; tool messages
  carry `tool_call_id`; assistant tool calls carry name + JSON arguments).
- `ToolSpec` → `{"type": "function", "function": {name, description,
  parameters}}`.
- Response → `AgentTurn`: `finish_reason == "tool_calls"` → list of
  `ToolCallRequest` (arguments parsed with `json.loads`; parse failure =
  invalid turn); `"stop"` → text turn. Both empty or both present = protocol
  error.

**T2 — Errors and privacy**

- Single exception type `LLMProviderError(message, code)` with codes:
  `config`, `network`, `protocol`, `rate_limited`, `server`.
- No prompt content logging ever; debug-level logs carry only message count,
  payload byte size, status code, and duration.
- Redaction remains harness responsibility (pre-`complete()` per §1.2); the
  adapter adds none and documents this boundary in its docstring.

**T3 — Tests (`tests/test_agents_provider.py`)**

- Transport injected as a callable (no network in CI).
- Golden recorded fixture: one full tool-call round trip request/response.
- Malformed cases: non-JSON tool arguments, missing `choices`, empty and
  ambiguous turns → `LLMProviderError` with `protocol`.
- Retry behavior: 500,500,200 sequence succeeds; four 500s raise after
  exactly 3 retries; 400 never retried.
- Config contract: missing base URL / empty key fail fast with `config`.

**T4 — Harness wiring**

- Provider factory maps `--provider mock|openai_compat`; unknown names fail
  with the supported list.
- Documented local usage:

```bash
export THELAB_LLM_BASE_URL=http://localhost:11434/v1
export THELAB_LLM_API_KEY=ollama
thelab-agent --provider openai_compat "goal"
```

**Verification gates:** standard suite green plus the new provider tests;
manual live check against local Ollama documented in the handoff doc but not
required in CI.

---

## §3 Stage 2 — Agent Intelligence

*Deterministic knowledge (S1) plus agents that carry tasks (A2), remember (L2),
and supervise (A3).*

### S1 — Deterministic EDA skill pack `[spec]`

**Goal:** heuristics as typed tools the agents must cite — deterministic
knowledge layer, LLM as reasoner over tool output.

- New module `thelab/eda/`, pure functions over a DataFrame:
  - `missing_profile` — per-column missingness + co-missingness pairs
  - `correlation_hints` — top |ρ| pairs, target correlations
  - `class_balance` — imbalance ratios, minimum-class warnings
  - `outlier_scan` — IQR/z-score flags per numeric column
  - `leakage_suspects` — features suspiciously correlated with target or
    post-outcome columns (naming heuristics documented)
  - `feature_types` — dtype/coercion report
- Each returns structured JSON with a stable schema; exposed as an MCP tool
  surface (`eda_mcp`) or harness-native tools — decided at activation,
  favoring whichever reuses more existing transport code.
- Identical input → identical output (deterministic; seeded where sampling is
  unavoidable).
- Tests: golden-output fixtures per skill; determinism check; dataset-size
  bounds.

### A2 — Worker agent `[spec]` *(absorbs L5 experiment proposals)*

**Goal:** an agent that carries an ML task end-to-end and proposes next steps
for human approval.

- Loop: ingest goal → EDA skills (S1) → propose batch config → human approval
  → execute via existing batch runner → validate results → grounded report.
- `ExperimentProposal` contract (Pydantic): dataset ref (relative path),
  target, model grid, seeds, rationale citing prior-run manifests. Proposals
  stored under `proposals/<proposal_id>.json`; CLI
  `thelab proposals approve|reject <id>`; approved proposal translates 1:1
  into a batch config for the existing `thelab run batch`. Proposals never
  execute directly.
- Sub-delegation: worker requests sub-tasks ("run EDA", "fetch manifest") as
  tool calls through the L1 allowlist — never free-form agent-to-agent
  messaging.
- Rejections and failed validations are first-class outcomes: reported, never
  silently retried.
- Tests: mock-provider scripted loops; approval gate; grounding checker;
  proposal→batch-config equivalence.

### L2 — Context writer MCP `[spec]`

**Goal:** agents persist session summaries in the canonical `/log` JSONL
shape; later sessions retrieve them via the existing read-only surface.

- New entry point `thelab-context-write-mcp` with exactly one tool:
  `append_session_summary(event)` validating the full canonical schema (see
  `.thelab/local-logs/agent-events.jsonl` records and normalization in
  `thelab/context/indexer.py`).
- Server-side redaction via `thelab/context/redaction.py` before storage —
  never trusted from the client payload.
- Append-only writes to `THELAB_CONTEXT_LOG_SOURCE` (default
  `.thelab/local-logs/agent-events.jsonl`); privacy mapping via
  `thelab/context/privacy.py`.
- Read-only `context_mcp` code paths untouched; indexing still happens through
  `thelab context index`.
- Safety: single-tool server, schema-validated, bounded sizes, no client
  filesystem-path arguments.
- Tests: schema rejection cases, redaction-before-store, idempotent indexing
  after append, byte-hash proof that the read-only server is untouched.

### A3 — Global agents `[spec]` *(absorbs L3 narration)*

**Goal:** two supervising global agents over the worker — the thesis title
made real: context-aware multi-agent orchestration via MCP.

- **Researcher** — detailed, citation-heavy answers. Engine: narration flow
  absorbed from L3 — prompt assembled exclusively from allowlisted artifacts
  (`manifest.json`, `metrics.json`, `validation_report.json`,
  `data_profile.json`, `model_card.md`); output carries a claim-ID citation
  map verified post-generation (uncitable claims dropped); dataset contents
  never leave the machine. Reads workspace + context store; never executes
  tasks.
- **Coding/Diagnosis** — terse, direct. Inputs: error summaries, validation
  reports, events. Controls the worker: assigns goals, approves/rejects
  proposals through the same approval artifacts as humans; the approval log
  records which principal approved.
- Topology: supervisor pattern; both globals reach the worker through
  harness-mediated tool calls and typed artifacts; no direct worker-to-worker
  channel.
- Memory: session summaries appended via L2; each session begins with
  `search_context` for prior decisions.
- Tests: scripted multi-agent scenarios with mock providers; Researcher
  citations resolvable; Diagnosis control actions produce persisted
  approval/state transitions.

---

## §4 Stage 3 — Evidence & Product

*Prove generality (B1), make it visible (U1), and produce thesis material (D1).*

### B1 — Cross-domain benchmark suite `[spec]`

**Goal:** prove generality: one factory, six domains, zero code changes.

- Curated datasets (small, openly licensed, committed CSVs with provenance
  notes in `data/benchmarks/README.md`):
  - Health: Breast Cancer Wisconsin (exists in `examples/`)
  - Chemistry: Wine (exists)
  - AI/classic: Iris (exists) or Titanic
  - Finance: German Credit or UCI default-of-credit-card clients
    (classification — credit risk, inside PRD boundaries)
  - Biotech: Splice-junction or similar gene-sequence classification
  - Physics/EM: Ionosphere or Magic Telescope
  - Regression pair: one synthetic housing-like + one physical-measurement
    dataset (exercises M1)
- `thelab run batch` config per domain; `thelab compare` output committed as
  a generated thesis table.
- Baseline expectations recorded per dataset (sanity ranges, not assertions).
- Tests: suite configs validate; every dataset passes inspection; batch runs
  complete within documented time bounds.

### U1 — UI v2 `[spec]`

**Goal:** the owner-facing dashboard: simple, elegant, authored.

- Layout: left rail = two global agent panels; right = worker conversation /
  current task view. Tabs: Run graph (DAG from manifests), CSV viewer
  (paginated, type-aware), Import + batch form, Log registry + search
  (context store), Metrics.
- Implementation: extend `thelab-model-service` static serving (Slice 5
  precedent). CSS design tokens file; hand-rolled SVG components (sparkline,
  bar, DAG layout) — no libraries, per §1.1.6.
- Thin read-only JSON endpoints already exist (`/runs/*`, `/models`,
  `/predict`); add only what panels need (e.g., batch status polling),
  keeping path-safety and allowlist rules.
- Agent panels render persisted state (approvals, proposals, session logs);
  the UI never executes agent actions directly — humans act through the same
  CLI/approval artifacts.
- Tests: TestClient coverage for new endpoints; HTML smoke tests; manual JS
  checklist documented in handoff.

### D1 — Demos and notebook `[spec]`

**Goal:** thesis evaluation material.

- **D1a — Simple challenge:** Titanic-style classification solved three ways:
  logistic baseline / agent-chosen ensemble / EDA-guided (S1-informed);
  compared against known public results.
- **D1b — Credit-risk agent-via-MCP:** train credit-risk model → register →
  serve → autonomous agent scores applications via
  `model_registry_mcp.predict` with full evidence trail.
- **Notebook:** `examples/notebooks/factory_demo.ipynb` — boot factory →
  inspect → batch → compare → serve → predict → agent session summary, using
  `thelab.quick` and the harness.
- Every demo leaves its `runs/<run_id>/` evidence; scripts committed under
  `scripts/demos/`; results tables generated, not hand-written.

### L4 — Hybrid semantic search `[BLOCKED]`

Hard-blocked on a written PRD amendment permitting *local-only* embeddings
(no cloud, no external APIs). Do not start without it. Design sketch kept in
the project history: side table keyed by `event_id` with vectors from a small
local ONNX model; hybrid rank = FTS score ⊕ cosine; FTS5 remains primary;
vectors rebuilt by explicit `thelab context embed`; `ContextReader` stays
read-only.

---

## §5 Activation Protocol

1. One slice active at a time. To activate: add its row to the slice map in
   `docs/ROADMAP.md`, then implement from this document.
2. Recommended sequence:

```text
Stage 1: M1 → L1 → A1
Stage 2: S1 → A2 → L2 → A3
Stage 3: B1 → U1 → D1
```

Stages may overlap at the human's discretion, but within a stage slices run
in order, and no slice starts before the previous slice's handoff doc exists.

3. Only M1 and L1 are fully specified now; other slices are precise specs that
   receive their final task-level detail at activation (without changing
   scope or locked decisions).
4. If a missing dependency is discovered mid-slice, halt and report instead of
   expanding scope.
5. After green tests and the handoff doc: stop. Do not open follow-up scope.
