# Stage 2 Implementation Prompt — Agent Intelligence

## Mission
Implement **P1 Stage 2 — Agent Intelligence** in full: build the deterministic EDA skill pack, the worker agent, the context writer MCP, and the two global supervising agents. Run in the order **S1 → A2 → L2 → A3**. Each slice ends with green tests, an example command, and its own handoff doc.

## Context initialization — read first
Read these documents in order before writing any code:
1. `AGENTS.md` and `docs/Agents.md`
2. `docs/PRD_P0.md`
3. `docs/P1_PLAN.md` §1 (locked decisions), §2 Stage 2 (S1, A2, L2, A3), §5 (activation protocol)
4. `docs/ROADMAP.md`
5. `docs/SliceM1_CONTEXT.md`
6. `docs/SliceL1_CONTEXT.md`
7. `docs/SliceA1_CONTEXT.md`

Inspect the relevant existing modules:
- `thelab/run/batch.py` and `thelab/run/inputs.py` — A2 proposal→batch translation
- `thelab/context/indexer.py`, `thelab/context/redaction.py`, `thelab/context/privacy.py`, `thelab/context/schema.py` — L2 redaction/schema
- `thelab/agents/harness.py`, `thelab/agents/provider.py`, `thelab/agents/mock.py`, `thelab/agents/cli.py` — agent loop wiring
- `thelab/mcp/*.py` — MCP server patterns to follow
- `tests/test_mcp.py`, `tests/test_agents_harness.py` — test/fixture patterns

## Stage 2 dependency order
Implement strictly in this sequence. Do **not** start A2 before S1 handoff exists, etc.

```text
S1 → A2 → L2 → A3
```

---

## Slice S1 — Deterministic EDA skill pack

**Goal:** heuristics as typed tools agents must cite.

Create `thelab/eda/` with pure DataFrame functions:
- `missing_profile(df, target=None)`
- `correlation_hints(df, target=None)`
- `class_balance(df, target)`
- `outlier_scan(df, target=None)`
- `leakage_suspects(df, target)`
- `feature_types(df, target=None)`

Each returns a stable JSON-serializable dict. Document the schema of each return value. Functions must be deterministic (no unseeded sampling).

Create `thelab/mcp/eda_mcp.py` stdio server exposing these as MCP tools. Add `thelab-eda-mcp` entry point in `pyproject.toml`. Each tool accepts `dataset` (relative CSV path) and `target` where applicable; rejects absolute/`..` paths.

Update `thelab/agents/cli.py` so `thelab-agent` spawns the EDA MCP server alongside the existing four servers.

Tests: `tests/test_eda_*.py` with golden fixtures, determinism check, size-bounds check, and MCP integration test.

Demo: `examples/eda_demo.py`.

Handoff: `docs/SliceS1_CONTEXT.md`. Update `docs/ROADMAP.md`: S1 → `done`, A2 → `in_progress`.

---

## Slice A2 — Worker agent

**Goal:** an agent that carries an ML task end-to-end and proposes experiments for human approval.

New module `thelab/agents/worker.py`:
- Accepts a goal, dataset path, target, and optional model grid.
- Uses the S1 EDA tools via the harness to analyze the dataset.
- Produces an `ExperimentProposal` Pydantic contract containing:
  - `dataset` (relative path)
  - `target`
  - `model_grid` (list of model names)
  - `seeds`
  - `rationale` (must cite prior-run manifests if relevant)
- Persists proposals under `proposals/<proposal_id>.json`.
- Never executes proposals directly.

New CLI:
- `thelab proposals approve <proposal_id>` — writes an approval record and translates the proposal 1:1 into a batch config for `thelab run batch`.
- `thelab proposals reject <proposal_id>` — writes a rejection record.

Wire the worker into `thelab-agent` via a `--mode worker` or equivalent, using the mock provider for deterministic tests. The worker must route sub-tasks (EDA, manifest fetch) through the L1 allowlist.

Tests: `tests/test_agents_worker.py` — mock-provider loops, approval gate, proposal→batch-config equivalence, rejection paths.

Demo: `examples/worker_proposal_demo.py` showing goal → EDA → proposal → approve → batch run.

Handoff: `docs/SliceA2_CONTEXT.md`. Update `docs/ROADMAP.md`: A2 → `done`, L2 → `in_progress`.

---

## Slice L2 — Context writer MCP

**Goal:** agents persist session summaries; later sessions retrieve them via the existing read-only context surface.

New entry point `thelab-context-write-mcp` in `pyproject.toml`.
- New module `thelab/mcp/context_write_mcp.py`.
- Exposes exactly one tool: `append_session_summary(event)`.
- Validates the full canonical `/log` JSONL schema (see existing records in `.thelab/local-logs/agent-events.jsonl` and normalization in `thelab/context/indexer.py`).
- Applies server-side redaction via `thelab/context/redaction.py` before storage.
- Append-only writes to `THELAB_CONTEXT_LOG_SOURCE` (default `.thelab/local-logs/agent-events.jsonl`).
- Uses `thelab/context/privacy.py` for privacy-level mapping.
- No client filesystem-path arguments.

Read-only `context_mcp` must remain untouched.

Tests: `tests/test_context_write_mcp.py` — schema rejection, redaction-before-store, idempotent indexing after append, byte-hash proof that the read-only DB/server is unchanged.

Demo: `examples/context_write_demo.py`.

Handoff: `docs/SliceL2_CONTEXT.md`. Update `docs/ROADMAP.md`: L2 → `done`, A3 → `in_progress`.

---

## Slice A3 — Global agents

**Goal:** two supervising global agents over the worker.

New modules under `thelab/agents/global_agents.py` or split as `researcher.py` and `diagnosis.py`:

**Researcher**
- Receives a question.
- Assembles context exclusively from allowlisted artifacts: `manifest.json`, `metrics.json`, `validation_report.json`, `data_profile.json`, `model_card.md`.
- Uses workspace + context store tools (read-only).
- Produces an answer with a claim-ID citation map; drops uncitable claims.
- Dataset contents never leave the machine.

**Coding/Diagnosis**
- Receives error summaries, validation reports, or events.
- Assigns goals to the worker (A2) and approves/rejects proposals through the same approval artifacts as humans.
- Approval log records which principal approved.

Topology: supervisor pattern; both globals reach the worker through harness-mediated tool calls and typed artifacts. No direct worker-to-worker channel.

Memory: at session start, call `search_context` for prior decisions; at end, append session summary via L2.

Wire into `thelab-agent` with `--mode researcher|diagnosis` or goal-based routing.

Tests: `tests/test_agents_global.py` — scripted multi-agent scenarios with mock providers; Researcher citations resolvable; Diagnosis control actions produce persisted approvals/state transitions.

Demo: `examples/global_agents_demo.py`.

Handoff: `docs/SliceA3_CONTEXT.md`. Update `docs/ROADMAP.md`: A3 → `done`; optionally add B1 → `in_progress` if Stage 3 is approved.

---

## Cross-cutting rules
- **No new runtime dependencies** without explicit approval.
- No cloud APIs, embeddings, vector DBs, or LLM calls in S1/A2/L2/A3.
- No arbitrary shell execution or autonomous code execution.
- Read-only by default; writes only through explicitly activated surfaces.
- Project-relative paths only in persisted artifacts.
- Rejected actions and failed validations are first-class, persisted outcomes.
- If you discover a missing dependency or ambiguous requirement, **halt and report** rather than expanding scope.

## Verification gates
Run after every slice and at the end of Stage 2:

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
```

Also run the documented example command for each slice.

## Deliverables
For each slice (S1, A2, L2, A3):
1. Implemented code and tests.
2. Green verification gates.
3. Runnable example/demo.
4. `docs/Slice<S1|A2|L2|A3>_CONTEXT.md`.
5. Updated `docs/ROADMAP.md` status.

Final Stage 2 deliverable: all four handoff docs exist, all tests green, ROADMAP reflects Stage 2 done.
