# The Lab — Codebase Guide

> Companion document for reading the P0 codebase slice by slice.  
> Last updated: 2026-08-10

## How to use this guide

Each section maps to one implementation slice. Read the **Key files** first, then the **Public surface**, then the **Safety boundaries**. Cross-reference `docs/ROADMAP.md` and `docs/PRD_P0.md` for requirements.

---

## Architecture at a glance

```
CLI              MCP servers           HTTP service
 |                    |                      |
 thelab run model     data_catalog_mcp       thelab-model-service  (Slice 5/6)
 |                    model_registry_mcp     |
 thelab context       workspace_mcp          /agent/* panels
 |                    context_mcp            |
 v                    v                      v
 runs/<run_id>/     .thelab/context/        static/
```

- **Contracts & workspace** (Slice 0) are imported everywhere.
- **Training pipeline** (Slice 1/1.5) writes versioned run directories.
- **MCP servers** (Slice 2/4) expose read-only reuse surfaces.
- **Context store** (Slice 3/3.1/4.1) indexes redacted logs.
- **Model service + UI** (Slice 5/6) serves the human dashboard and agent panels.

---

## Slice 0 — Contracts and workspace

**Purpose:** typed, hash-verified, auditable data primitives.

### Key files

| File | Role |
|---|---|
| `thelab/contracts/__init__.py` | Public re-export of all contracts. |
| `thelab/contracts/task_spec.py` | `TaskSpec`, `TaskState`. |
| `thelab/contracts/run_manifest.py` | `RunManifest`, `RunStatus`, `ValidationStatus`. |
| `thelab/contracts/artifact_ref.py` | `ArtifactRef` — relative, no-`..` path reference. |
| `thelab/contracts/dataset_spec.py` | `DatasetSpec` — schema, target, split, privacy. |
| `thelab/contracts/model_spec.py` | `ModelSpec` — algorithm, hyperparameters, seed. |
| `thelab/contracts/log_entry.py` | `LogEntry`, `EventType`, `PrivacyLevel`. |
| `thelab/workspace/paths.py` | `RUNS_DIR`, `ensure_run_dir`, `artifact_path`. |
| `thelab/workspace/hashing.py` | SHA-256 helpers. |
| `thelab/mcp/common.py` | Shared safe-run helpers. |

### Safety boundaries

- `ArtifactRef.relative_path` must be relative and contain no `..`.
- `artifact_path()` raises on any escape from `runs/<run_id>/`.
- `safe_run_dir()` resolves the run dir and verifies it lives under `runs_root`.

---

## Slice 1 — Direct reproducible run

**Purpose:** `thelab run model` trains a deterministic classifier and writes a complete evidence directory.

### Key files

| File | Role |
|---|---|
| `thelab/cli.py` | Top-level CLI; dispatches `context` and `run model`. |
| `thelab/run/runner.py` | `run_model()` orchestration lifecycle. |
| `thelab/run/inputs.py` | `RunInputs`, supported-model check. |
| `thelab/run/validate.py` | Dataset validation; rejects stratified-infeasible data. |
| `thelab/run/preprocess.py` | `StandardScaler` pipeline builder. |
| `thelab/run/train.py` | `LogisticRegression` train/eval; `FittedPipeline`. |
| `thelab/run/profile.py` | CSV profiling. |
| `thelab/run/contract.py` | Dataset contract generation. |
| `thelab/run/artifacts.py` | Artifact persistence + manifest assembly. |

### Public surface

```bash
thelab run model --dataset <csv> --target <col> --model logistic_regression --seed <n> --output <dir>
```

### Artifacts produced (in `runs/<run_id>/`)

```
manifest.json
task_spec.json
events.jsonl
inputs.json
data_profile.json
dataset_contract.json
training_config.json
metrics.json
validation_report.json
model.joblib
model_card.md
```

### Determinism

- Fixed `random_state=seed` for split and model.
- `training_config.json` records model, seed, split, preprocessing, dependency versions.
- Rejected runs still write `manifest.json`, `events.jsonl`, `inputs.json`, `data_profile.json`, `validation_report.json`, `task_spec.json`.

---

## Slice 1.5 — TaskSpec orchestration

**Purpose:** every run has a persisted `TaskSpec` linked to its manifest.

- `TaskSpec.task_id == run_id`.
- States: `pending` → `running` → `completed|rejected|failed`.
- Written as `task_spec.json` inside the run directory.

---

## Slice 2 — MCP reuse servers

**Purpose:** expose datasets, models, workspace artifacts, and predictions to independent MCP clients.

| Server | Tools | File |
|---|---|---|
| `data_catalog_mcp` | `list_datasets`, `get_data_profile`, `get_dataset_contract` | `thelab/mcp/data_catalog_mcp.py` |
| `model_registry_mcp` | `list_models`, `get_model_manifest`, `get_model_card`, `get_model_metrics`, `predict` | `thelab/mcp/model_registry_mcp.py` |
| `workspace_mcp` | `list_runs`, `get_run_manifest`, `list_run_artifacts`, `get_artifact`, `read_model_card` | `thelab/mcp/workspace_mcp.py` |

### Shared safety (`thelab/mcp/common.py`)

- `get_runs_root()` from `THELAB_RUNS_ROOT` env, default `runs/`.
- `_is_safe_run_id()` rejects `/`, `\`, `..`, hidden names.
- `safe_run_dir()` resolves and verifies containment.
- `load_json_artifact()` / `load_text_artifact()` return `None` on any error.

### Demo client

`thelab/mcp/demo_client.py` spawns each server over stdio and exercises tools. It propagates `THELAB_RUNS_ROOT` and `THELAB_CONTEXT_DB`.

---

## Slice 3 — Local context store and CLI

**Purpose:** index JSONL agent logs into a searchable SQLite + FTS5 store.

### Key files

| File | Role |
|---|---|
| `thelab/context/contracts.py` | `IndexedEntry` Pydantic model. |
| `thelab/context/repository.py` | `ContextRepository` — write side, schema, upsert, search. |
| `thelab/context/indexer.py` | Idempotent JSONL → SQLite; redacts secrets. |
| `thelab/context/schema.py` | Shared schema + `row_to_entry`. |
| `thelab/context/redaction.py` | Pattern-based secret redaction. |
| `thelab/context/filters.py` | `SearchFilters` dataclass. |
| `thelab/context/cli.py` | `thelab context index|search|show`. |

### CLI

```bash
thelab context index --source <jsonl> [--db <db>]
thelab context search [query] [--run-id] [--tag] [--event-type] [--since] [--until] [--limit]
thelab context show <event_id>
```

### Redaction families

Private keys, bearer tokens, GitHub/Google/AWS/Slack tokens, `sk-` keys, `api_key=`, `password=`, env-style secrets → `[REDACTED]`.

---

## Slice 3.1/4.1 — Context hardening

**Purpose:** make the context surface genuinely read-only and agent-safe.

### Key additions

| File | Role |
|---|---|
| `thelab/context/reader.py` | `ContextReader` — read-only DB access, bounded queries, privacy filtering. |
| `thelab/context/privacy.py` | `AGENT_SAFE_PRIVACY_LEVELS`, `/log` privacy mapping. |

### `ContextReader` safety

- Opens with `file:<path>?mode=ro` and `PRAGMA query_only=ON`.
- Never creates directories or runs DDL/DML.
- Bounds: query ≤ 200 chars, tags ≤ 10 × ≤ 64 chars, limit 1–1000.
- Rejects naive timestamps; normalizes to UTC.
- Malformed FTS5 → empty list.
- `status()` never exposes `db_path`.

### Privacy

- Default returns only `public` + `internal`.
- `restricted`/`secret` require explicit override.
- `status()` counts only visible rows.

---

## Slice 4 — Context MCP

**Purpose:** read-only stdio MCP server over the context index.

- `thelab/mcp/context_mcp.py`
- Tools: `get_context_status`, `get_context_entry`, `search_context`.
- No write tools, no DB path arguments, uses `THELAB_CONTEXT_DB`.

### Slice 4.1 hardening in the MCP layer

- Tool schemas set `additionalProperties: false`.
- Bounds match `ContextReader`.
- Response DTO excludes `content_hash` and `indexed_at`.

---

## Slice 5 — Minimal local UI

**Purpose:** human dashboard served by the existing `thelab-model-service`.

### Key files

- `thelab/model_service/app.py`
- `thelab/model_service/cli.py`
- `thelab/model_service/static/index.html`, `app.js`, `styles.css`

### HTTP endpoints

| Method | Path |
|---|---|
| `GET` | `/` |
| `GET` | `/static/*` |
| `GET` | `/health` |
| `GET` | `/models` |
| `POST` | `/predict` |
| `GET` | `/runs/{run_id}` |
| `GET` | `/runs/{run_id}/artifacts` |
| `GET` | `/runs/{run_id}/artifacts/{artifact_name}` |

### Safety

- Only `completed` + `approved` runs.
- `model.joblib` never served over HTTP.
- Artifact allowlist: `manifest.json`, `metrics.json`, `data_profile.json`, `inputs.json`, `validation_report.json`, `training_config.json`, `dataset_contract.json`, `model_card.md`, `task_spec.json`.

---

## Slice 6 — Agent panels and thesis evaluation

**Purpose:** P0 closeout. Read-only agent panels, lockfile, automated evaluator.

### Agent HTTP endpoints

| Method | Path |
|---|---|
| `GET` | `/agent/coding/overview` |
| `GET` | `/agent/coding/runs` |
| `GET` | `/agent/coding/runs/{run_id}` |
| `GET` | `/agent/research/context/status` |
| `GET` | `/agent/research/context/search` |
| `GET` | `/agent/research/context/entries/{event_id}` |

### UI tabs

- **Models** — existing Slice 5 dashboard.
- **Coding / Logger** — run evidence + read-only banner.
- **Research / Copilot** — local context search + no-LLM banner.

### Lockfile / reproducibility

- `pyproject.toml`: `requires-python = ">=3.11,<3.15"`.
- `requirements.lock`: pinned dependency set.
- `README.md`: install instructions.
- Verified in a fresh temp venv.

### Thesis evaluator

`scripts/evaluate_thesis.py` checks:

| RQ | Verified |
|---|---|
| RQ1 Reproducibility | Two identical trains; metrics match; manifest has seed + dependency versions. |
| RQ2 MCP interoperability | Spawns `model_registry_mcp`; `list_models` + `predict`. |
| RQ3 Context retrieval | Index JSONL; search returns hit; DB unchanged. |

Results recorded in `docs/THESIS_EVALUATION.md`.

---

## Public surface inventory

### CLI commands

| Command | File |
|---|---|
| `thelab run model ...` | `thelab/cli.py` → `thelab/run/runner.py` |
| `thelab context index|search|show` | `thelab/context/cli.py` |
| `thelab-model-service` | `thelab/model_service/cli.py` |
| `thelab-mcp-demo ...` | `thelab/mcp/demo_client.py` |

### MCP tools

| Server | Tools |
|---|---|
| `data_catalog_mcp` | `list_datasets`, `get_data_profile`, `get_dataset_contract` |
| `model_registry_mcp` | `list_models`, `get_model_manifest`, `get_model_card`, `get_model_metrics`, `predict` |
| `workspace_mcp` | `list_runs`, `get_run_manifest`, `list_run_artifacts`, `get_artifact`, `read_model_card` |
| `context_mcp` | `get_context_status`, `get_context_entry`, `search_context` |

### HTTP endpoints

See Slice 5 and Slice 6 tables above.

---

## Safety inventory

| Boundary | Where enforced |
|---|---|
| Path traversal in run IDs | `thelab/mcp/common.py` `_is_safe_run_id`, `safe_run_dir` |
| Artifact path containment | `thelab/workspace/paths.py`, `ArtifactRef` validation |
| Read-only context | `thelab/context/reader.py` (`mode=ro`, `query_only=ON`) |
| Context privacy filtering | `thelab/context/privacy.py` → default `public`+`internal` |
| Secret redaction | `thelab/context/redaction.py` before SQLite storage |
| MCP schema bounds | `thelab/mcp/context_mcp.py` |
| HTTP artifact allowlist | `thelab/model_service/app.py` `_ARTIFACT_ALLOWLIST` |
| HTTP no absolute paths | `thelab/model_service/app.py` `_dataset_basename`, status DTOs |
| Localhost-only HTTP | `thelab/model_service/cli.py` default `--host 127.0.0.1` |
| Approved-only predict | `thelab/model_service/app.py` `_predict`, MCP `predict` tools |

---

## How to read the code by question

| “I want to understand…” | Start here |
|---|---|
| How a run is created | `thelab/run/runner.py` → `thelab/run/artifacts.py` |
| How determinism is guaranteed | `thelab/run/train.py`, `thelab/run/artifacts.py` `training_config.json` |
| How MCP servers stay safe | `thelab/mcp/common.py`, then any `*_mcp.py` |
| How context privacy works | `thelab/context/privacy.py` → `thelab/context/reader.py` → `thelab/mcp/context_mcp.py` |
| How the UI talks to the backend | `thelab/model_service/static/app.js` → `thelab/model_service/app.py` |
| How RQ1–RQ3 are checked | `scripts/evaluate_thesis.py` → `docs/THESIS_EVALUATION.md` |

---

## Known drift / notes

- ROADMAP PRD numbering differs from implementation slice numbering (explained in `docs/ROADMAP.md`).
- `requirements.lock` is a `pip freeze` lock without hashes; reproducibility assumes PyPI package availability.
- No new `agent_mcp` server exists; agent panels use HTTP, and programmatic agents use existing MCP servers.

---

# Appendix — For future code agents

## Agent onboarding checklist

Before writing or changing code:

1. Read `docs/Agents.md` and `docs/PRD_P0.md`.
2. Read `docs/ROADMAP.md` to find the active slice and status.
3. Read the relevant `docs/SLICE{N}_PLAN.md` / `docs/SLICE{N}_CONTEXT.md`.
4. Read this `CODEBASE_GUIDE.md` for the slice map and safety inventory.
5. Run the verification commands below and confirm the baseline is green.

## Hard boundaries every agent must respect

| Boundary | Rule |
|---|---|
| MCP surface | Do not add a new MCP server (`agent_mcp`, etc.) unless the active plan explicitly requires it. |
| LLM / RAG | No LLM SDKs, embeddings, vector DB, or cloud RAG in P0. |
| Write tools | Read-only surfaces get no `append_log`, `train`, `delete`, or shell-execution tools. |
| Path safety | No absolute filesystem paths in API/UI responses. Use `safe_run_dir` and basename-only artifact names. |
| HTTP bind | Default stays `127.0.0.1`; do not switch to `0.0.0.0` without explicit approval. |
| Context privacy | Default context retrieval is `public` + `internal` only. `restricted`/`secret` need explicit override. |
| Scope | Implement only the active slice. Do not build future slices early. |

## Common pitfalls

- **`pip freeze` includes the editable `thelab` line.** Remove `-e git+...#egg=thelab` from `requirements.lock` if it is meant as a dependency-only lock.
- **HTTP clients normalize `..` path segments.** Path-traversal tests should use encoded forms (e.g. `%2e%2e`) to reach application code.
- **Use `ContextReader` for all context reads.** Never use `ContextRepository` in read-only CLI/MCP/HTTP paths; it can create directories and run DDL.
- **MCP subprocess commands may fail if `PATH` lacks venv scripts.** Prefer `sys.executable -m thelab.mcp.<module>` over bare command names.
- **Rejected runs are valid outcomes.** Do not treat `validation_status=rejected` as a test failure unless the test explicitly expects completion.

## How to start a new slice

1. Confirm the slice is planned and `docs/SLICE{N}_PLAN.md` exists and is binding.
2. Note what is marked “already done” in that plan.
3. Touch only the files listed in the plan’s file map.
4. Add or update tests for every new behavior or safety boundary.
5. Run the verification commands below.
6. Write/update `docs/SLICE{N}_CONTEXT.md` and update `docs/ROADMAP.md`.
7. Stop for audit; do not start the next slice early.

## Verification commands that should always pass

```bash
# Full test suite
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q

# Thesis evaluation (P0 closeout sanity check)
PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py
```

Both must be green before claiming a slice is complete.
