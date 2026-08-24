# The Lab — Implementation Roadmap

> This document maps the implementation slices to the binding P0 spec in `docs/PRD_P0.md`. The PRD remains the source of truth; this roadmap explains how the implementation is organized into focused, testable vertical slices.

## Status legend

- `done` — implemented and verified.
- `in_progress` — actively being worked on.
- `planned` — agreed scope, not started.

## Slice map

| Implementation slice | PRD slice | Status | Focus |
|---|---|---|---|
| Slice 0 | Slice 0 | done | Contracts, workspace conventions, hashing, fixtures |
| Slice 1 | Slice 1 | done | `thelab run model`, validation, deterministic training, artifacts, manifest |
| Slice 1.5 | Slice 1 enhancement | done | `TaskSpec` generation and persistence |
| Slice 2 | Slice 2 (+ inference service) | done | MCP reuse + local HTTP model service (`/health`, `/models`, `/predict`) |
| Slice 3 | Slice 3 (store/CLI) | done | Local context store + CLI |
| Slice 3.1 | Slice 3 hardening | done | Remediation: read-only `ContextReader`, expanded redaction, privacy filtering |
| Slice 4 | Slice 3 remaining | done | Read-only `context_mcp` server |
| Slice 4.1 | Slice 3/4 hardening | done | CLI reader path, agent-visible status counts, MCP schemas/DTO |
| Slice 5 | PRD “Slice 4” visual results | done | **Minimal local UI** on existing `thelab-model-service` |
| Slice 6 | PRD “Slice 5” agents/eval | done | Read-only agent panels + thesis evaluation protocol |

> **Note on PRD numbering:** The PRD groups “service + dashboard” as its Slice 4 and “agent panels + evaluation” as its Slice 5. This roadmap split inference service into implementation Slice 2 and keeps implementation Slice 5 = **UI only**, Slice 6 = **agents + evaluation**.

| Implementation slice | PRD slice | Status | Focus |
|---|---|---|---|
| Slice 7 | P0 hardening | done | Cleanup, ruff/mypy, README skeleton |
| Slice 8 | P0 hardening | done | Path traversal, inference validation, safety |
| Slice 9 | P0 hardening | done | Model registry + random_forest/svc/sgd_classifier |
| Slice 10 | P0 hardening | done | Refactored dataset validators + edge cases |
| Slice 11 | P0 hardening | done | Batch runner + final README |
| Slice 12 | Exploratory UX | done | Inspect, dry-run, try-all, predict, compare, Python/Jupyter API |
| M1 | P1 Stage 1 | done | Task-type generalization (classification + regression) |
| L1 | P1 Stage 1 | done | Agent harness + LLM provider protocol (mock provider) |
| A1 | P1 Stage 1 | done | OpenAI-compatible LLM provider adapter |

## Slice 0 — Contracts and workspace

**Goal:** Establish typed contracts and local workspace helpers.

- `TaskSpec`, `RunManifest`, `ArtifactRef`, `DatasetSpec`, `ModelSpec`, `LogEntry` contracts.
- Workspace hashing and path helpers.
- Fixture placeholder.
- Unit tests for contracts and workspace utilities.

**Verification:** `tests/test_contracts.py`, `tests/test_workspace.py` pass.

## Slice 1 — Direct reproducible run

**Goal:** Run a deterministic training pipeline from the CLI without any LLM or UI.

- `thelab run model --dataset --target --model --seed --output`.
- Dataset validation and profiling.
- Deterministic logistic-regression training.
- Required run artifacts: `manifest.json`, `events.jsonl`, `inputs.json`, `data_profile.json`, `dataset_contract.json`, `training_config.json`, `metrics.json`, `validation_report.json`, `model.joblib`, `model_card.md`.
- Validation failures are traceable outcomes.

**Verification:** `tests/test_run.py` passes; manual `thelab run model` completes and creates all artifacts.

## Slice 1.5 — TaskSpec orchestration

**Goal:** Give every run a persisted `TaskSpec` so future agentic slices have a pre-agentic baseline to compare against.

- `thelab run model` creates a `TaskSpec` at start with `task_state=pending`.
- State transitions through `running` to `completed`/`rejected`/`failed`.
- Persist `task_spec.json` in `runs/<run_id>/`.
- Add `task_spec_id` to `RunManifest` for explicit traceability.
- `TaskSpec.task_id` equals `run_id`.

**Verification:** `task_spec.json` exists after a run and reflects the final state.

## Slice 2 — MCP reuse and local model service

**Goal:** Expose datasets, models, workspace artifacts, and predictions to independent MCP clients; serve approved models over local HTTP for humans.

### `data_catalog_mcp`
- `list_datasets`
- `get_data_profile(run_id)`
- `get_dataset_contract(run_id)`

### `model_registry_mcp`
- `list_models`
- `get_model_manifest(run_id)`
- `get_model_card(run_id)`
- `get_model_metrics(run_id)`
- **`predict(run_id, features)`** — load the approved `model.joblib` and return predictions

### `workspace_mcp`
Read-only workspace/artifact access:
- `list_runs()`
- `get_run_manifest(run_id)`
- `list_run_artifacts(run_id)`
- `get_artifact(run_id, artifact_type)`
- `read_model_card(run_id)`

### Local HTTP model service (done here — not Slice 5)
- Entry point: `thelab-model-service` (default bind `127.0.0.1:8000`).
- `GET /health`, `GET /models`, `POST /predict`.
- Approved + completed runs only.

### Demo client
- `thelab-mcp-demo data_catalog --run-id <run_id>`
- `thelab-mcp-demo model_registry [--run-id <run_id>]`
- `thelab-mcp-demo workspace --run-id <run_id>`

**Verification:** `tests/test_mcp.py`, `tests/test_workspace_mcp.py`, `tests/test_model_service.py` pass; demo client connects to each server.

## Slice 3 — Local context store and CLI

**Goal:** Index JSONL agent logs into a searchable SQLite store.

- SQLite + FTS5 repository.
- Idempotent JSONL indexing with SHA-256 content fingerprint.
- Defensive secret redaction before storage.
- `thelab context index/search/show`.
- Supports canonical `LogEntry` events and the `/log` agent-session-summary shape.

**Verification:** `tests/test_context_*.py` pass; manual CLI search returns redacted results.

## Slice 3.1 — Context store remediation

**Goal:** Make Slice 3 safe enough for a genuinely read-only Context MCP in Slice 4.

- Expand redaction to GitHub, Google, AWS, and Slack token families.
- Add `ContextReader` (read-only URI, `query_only=ON`, bounded queries, schema validation, privacy filtering).
- Reject `..` path components in `ArtifactRef`.
- Map `/log` privacy objects to stored privacy levels explicitly and safely.
- Isolate `thelab context ...` CLI from sklearn/pandas imports.

**Verification:** Full suite green; DB hash-before/hash-after read-only verification succeeds.

## Slice 4 — Context MCP

**Goal:** Expose the context index to MCP clients through a read-only, agent-safe interface.

- `thelab-context-mcp` entry point.
- Tools: `search_context`, `get_context_entry`, `get_context_status`.
- No write tools, no `append_log`, no filesystem path arguments.
- Uses `ContextReader` and `THELAB_CONTEXT_DB`.
- Extend demo client: `thelab-mcp-demo context`.

**Verification:** Tool discovery shows only read-only tools; source JSONL is not modified by queries.

## Slice 4.1 — Context surface hardening

**Goal:** Align CLI retrieval with MCP agent-safe policy; tighten MCP contract.

- CLI `search` / `show` use `ContextReader` only (privacy defaults, no DB creation on read).
- Status `entry_count` / `last_indexed_at` count agent-visible rows only.
- MCP tool JSON schemas: bounds + `additionalProperties: false`.
- MCP public response DTO (omit `content_hash`, `indexed_at`).
- Expanded regression tests.

**Verification:** Full suite green; see `docs/SLICE4.1_REMEDIATION_PLAN.md`.

## Slice 5 — Minimal local UI

**Goal:** Human-facing dashboard on the **existing** model service. Do **not** reimplement inference.

**Plan:** `docs/SLICE5_PLAN.md` (binding for implementation).

- Serve vanilla HTML/CSS/JS from `thelab-model-service` (`GET /`).
- Panels: health/status, approved models, metrics, allowlisted artifact browser, predict form.
- Thin read-only APIs: run summary + artifact list/get (path-safe, allowlisted basenames).
- No absolute path leakage; default bind remains `127.0.0.1`.
- No context index, no agent panels, no frontend build toolchain, no Playwright.

**Verification:** `tests/test_model_service.py` and new UI/API tests pass; manual open of `http://127.0.0.1:8000/` shows panels and can predict on an approved run.

## Slice 6 — Agent panels and thesis evaluation

**Status:** done. P0 implementation is complete pending final audit.

**What was delivered:**

- Read-only Coding/Logger Agent panel in the existing `thelab-model-service` UI (repository evidence, logs, artifacts—**no** autonomous writes).
- Research/Copilot panel grounded in **local** evidence (workspace + context retrieval)—not cloud RAG and **no LLM**.
- Reproducibility gate: supported Python pin and committed `requirements.lock`.
- Reproducibility and interoperability demonstrations (direct run → MCP discover/predict → context search).
- Thesis evaluation rubrics, automated evaluator, and recorded results.

**Handoff docs:**

- Implementation summary: `docs/SLICE6_CONTEXT.md`
- Protocol + results: `docs/THESIS_EVALUATION.md`
- Binding plan: `docs/SLICE6_PLAN.md`

**Verification:** End-to-end demonstration with documented results; panels remain read-only by default; any write path requires explicit approval (PRD).

## Non-goals preserved from PRD

No trading, arbitrary shell execution, autonomous code execution, embedded terminals, RAG/vector DB, multi-user support, cloud deployment, public hosting, complex authentication, or multiple LLM-provider integrations in P0.

## Backlog

See `docs/FUTURE_FEATURES.md` for the full idea parking lot. Highlights:

| # | Idea | Status | Notes |
|---|---|---|---|
| 1 | `thelab inspect` | done | Quick dataset profiling without a full run |
| 2 | `thelab run model --dry-run` | done | Train in-memory, no artifacts |
| 3 | `thelab predict` | done | One-off CLI prediction from an approved run |
| 4 | `thelab compare` | done | Metrics table across completed runs |
| 5 | `thelab run model --try-all` | done | Compare every registered model |
| 6 | Python / Jupyter API | done | `thelab.quick` + notebook example |
| 7 | `thelab sketch` interactive mode | future | Highest exploratory value, medium effort |
| 8 | Hash-verified `model.joblib` loading | future | Hardens pickle deserialization risk |
| 9 | Hyperparameter overrides in batch config | future | Natural extension of batch runner |
| 10 | First LLM provider / agent slice (P1) | specified | Superseded by `docs/P1_PLAN.md` (slices L1, A1, A2, A3) |

## P1 planning (draft — not activated)

Unified P1 plan: [`docs/P1_PLAN.md`](P1_PLAN.md) (slices M1 → D1, in three
stages). Slice rows are added to the slice map above only as each slice is
activated.

## Active implementation pointer

| Now | Doc |
|---|---|---|
| **Status** | P0 + Phase A hardening complete — exploratory CLI/API slice done — pending GitHub-readiness review |
| Master map | this file |
| Binding product spec | `docs/PRD_P0.md` |
| Coding constraints | `docs/Agents.md` |
| Last completed | Slice 6 — `docs/SLICE6_CONTEXT.md` |
