# Revised Slice 3 / Slice 4 Plan — Local Context Store and Read-Only Context MCP

> Status: planning complete, awaiting implementation approval  
> Last updated: 2026-08-09

## Background

The original PRD grouped four concerns into a single "Slice 3: Logger and local memory":

1. SQLite context storage
2. FTS5 search
3. `/log` CLI
4. `context_mcp` server
5. Privacy levels and redaction

That mix combined **storage engine**, **human CLI**, **agent MCP surface**, and **data policy** in one slice. This document splits it into two focused vertical slices and applies three additional constraints requested by the team:

- SQLite FTS5 belongs in the first slice so local search is useful immediately.
- Defensive secret redaction must be applied before any content enters the derived SQLite index.
- The Context MCP server in the second slice is **read-only**: no `append_log` tool, no writes, no side effects.

---

## Slice 3: Local Context Store and CLI

### Goal

Provide a local, searchable context repository derived from existing JSONL log sources, with a defensive redaction layer and a small CLI.

### Scope

1. **Pydantic contracts**
   - Reuse `thelab.contracts.log_entry.LogEntry` as the canonical source event shape.
   - Add `agent_session_summary` as a valid `EventType` to represent the existing `/log` event shape.
   - Introduce `thelab.context.contracts.IndexedEntry` to capture derived index fields (`event_id`, `content_hash`, `indexed_at`) and a normalized view of both canonical and `/log` events.

2. **Local SQLite repository**
   - SQLite database located at `.thelab/context/context.db` under the workspace root (configurable via `THELAB_CONTEXT_DB`).
   - It is a local storage derivative and must be ignored by Git, like the logs.
   - Tables:
     - `entries` — normalized log entry fields.
     - `entry_tags` — many-to-many tag mapping.
     - `entries_fts` — FTS5 virtual table for keyword search over redacted summaries.
   - Use `sqlite3` from the standard library; verify `fts5` is available at runtime and fail gracefully if not.

3. **Idempotent JSONL indexing**
   - Source file: `.thelab/local-logs/agent-events.jsonl` only.
   - The per-run `runs/<run_id>/events.jsonl` files are technical training events, not agent logs; they are intentionally not indexed here. They may be linked later via `run_id` when needed.
   - Implement a dedicated normalization/adaptation layer that supports:
     - Canonical LogEntry-style events with root-level `redacted_summary`.
     - The existing `/log` agent-session-summary shape (`outcome.summary`, `context.run_id`, `context.slice`, `learning.topics`).
   - Validate normalized records before persistence. Malformed records (missing `event_id`, bad timestamp, missing summary, unsupported event type, invalid structure) are skipped and reported; they are never inserted and never cause content-conflict errors.
   - Each valid entry uses `event_id` as its visible identifier and a SHA-256 hash of its canonical JSON as a content fingerprint.
   - Re-running the indexer must not create duplicates.
   - If the same `event_id` appears with different content, reject it with a clear error.
   - The indexer must **not** modify the source JSONL file.

4. **Defensive redaction before indexing**
   - Apply pattern-based redaction to the `redacted_summary` field before storage.
   - Target patterns include:
     - API keys / tokens (`sk-...`, `Bearer ...`, etc.)
     - Password assignments (`password=...`, `passwd=...`)
     - Private-key blocks (`-----BEGIN ... PRIVATE KEY-----`)
     - Common environment-variable secret patterns (`SECRET_...=...`, `API_KEY=...`, `TOKEN=...`)
   - Store only the redacted text in the searchable index.
   - Keep the redaction rules in a dedicated, testable module.

5. **CLI**
   - `thelab context index` — index/re-index local logs into SQLite.
   - `thelab context search "<query>"` — FTS5 keyword search.
     - Optional filters: `--run-id`, `--tag`, `--event-type`, `--since`, `--until`.
   - `thelab context show <event_id>` — display a single indexed entry.

6. **No non-goal features**
   - No MCP server, UI, model inference, LLM, vector DB, RAG, embeddings, cloud, or agents.

### Acceptance criteria

| ID | Criterion |
|----|-----------|
| S3-AC-01 | `thelab context index` creates or updates `.thelab/context/context.db` from `.thelab/local-logs/agent-events.jsonl`. |
| S3-AC-02 | Re-running `thelab context index` is idempotent: no duplicate entries. |
| S3-AC-03 | `thelab context search "error"` returns matching entries ranked by FTS5 relevance. |
| S3-AC-04 | Structured filters (`--run-id`, `--tag`, `--event-type`, `--since`, `--until`) restrict search results correctly. |
| S3-AC-05 | `thelab context show <event_id>` returns the full indexed entry. |
| S3-AC-06 | Secrets present in the source JSONL are redacted before storage in SQLite. |
| S3-AC-07 | The source `.thelab/local-logs/agent-events.jsonl` file is not modified by indexing. |
| S3-AC-08 | Existing `/log` agent-session-summary events index correctly and their `outcome.summary`, `context.run_id`, `context.slice`, and `learning.topics` are normalized. |
| S3-AC-09 | Malformed records are skipped and reported; they are never persisted and never trigger content-conflict errors. |
| S3-AC-10 | `related_artifact_refs` round-trip through the indexer, SQLite repository, `get`, `search`, and `thelab context show`. |
| S3-AC-11 | `thelab context index` returns `"ok": false` and exits non-zero when malformed records are encountered. |
| S3-AC-12 | If FTS5 is unavailable, the command fails with a clear error instead of silently degrading. |

### Non-goals

- No semantic search, embeddings, RAG, or vector database.
- No MCP server or agent interface.
- No UI or web dashboard.
- No model inference, training triggers, or shell execution.
- No cloud storage or multi-user support.
- No modification of original source log files.
- No formal visibility policy (e.g., `private` vs `agent_safe`); Slice 3 stores only normalized, redacted local context.

### Proposed file/module layout

```text
thelab/
  context/
    __init__.py
    contracts.py          # IndexedEntry / ContextEntry contract
    repository.py         # SQLite + FTS5 repository
    indexer.py            # JSONL -> SQLite indexing with idempotency
    redaction.py          # secret-detection and redaction rules
    filters.py            # query filter parsing/building
    cli.py                # thelab context index/search/show

.thelab/
  local-logs/
    agent-events.jsonl    # source JSONL log events (existing or created by future logging)
  context/
    context.db            # derived SQLite index (ignored by Git)
```

### Test plan

1. **Unit tests** (`tests/test_context_redaction.py`)
   - Redaction patterns catch secrets and leave safe text intact.
   - Edge cases: empty strings, already-redacted text, multi-line private keys.

2. **Repository tests** (`tests/test_context_repository.py`)
   - Create schema, insert, search, filter, show.
   - Idempotent upsert behavior.
   - FTS5 ranking behavior.
   - Date-range filtering.

3. **Indexer tests** (`tests/test_context_indexer.py`)
   - Index a fixture JSONL file and verify SQLite contents.
   - Index a realistic `/log` agent-session-summary fixture and verify normalization.
   - Re-index and assert no duplicates.
   - Assert source file bytes are unchanged.
   - Assert secrets are redacted in the DB.
   - Assert malformed records are skipped and reported, not inserted.
   - Assert `related_artifact_refs` round-trip from valid source records.
   - Assert `/log` `evidence.artifacts` / `evidence.source_refs` plain strings are not converted to ArtifactRefs.

4. **CLI tests** (`tests/test_context_cli.py`)
   - `thelab context index` exits 0 and produces the DB when all records are valid.
   - `thelab context index` exits non-zero with `"ok": false` when malformed records are present.
   - `thelab context search` returns JSON/printable results.
   - `thelab context show` returns the requested entry.
   - Filter flags are parsed and applied.

### Risks and open questions

| Risk / Question | Mitigation / Note |
|-----------------|-------------------|
| **Source file location** | The PRD mentions `.thelab/local-logs/agent-events.jsonl`, but current runs emit per-run `events.jsonl` under `runs/<run_id>/`. Slice 3 should read the configured source path and not invent aggregation logic unless explicitly requested. |
| **FTS5 availability** | Modern Python `sqlite3` usually includes FTS5. Add a runtime check and a clear error message. |
| **Stable event_id** | Need to define how `event_id` is derived. Options: UUID in source JSONL, SHA-256 of canonical JSON, or composite `(source_path, line_number)`. Idempotency depends on this choice. |
| **Redaction completeness** | Pattern-based redaction is best-effort. Document that it is defensive, not a guarantee, and that no raw secrets should be logged in the first place. |
| **CLI output format** | Decide now between human-readable tables vs. JSON. Suggest JSON by default for composability, with optional `--format table`. |

---

## Slice 4: Context MCP and Agent-Safe Retrieval

### Goal

Expose the Slice 3 SQLite context index to MCP clients through a read-only, agent-safe interface.

### Scope

1. **Local stdio `context_mcp` server**
   - `thelab-context-mcp` entry point.
   - Uses MCP stdio transport, consistent with Slice 2 servers.
   - Reads the SQLite database path from `THELAB_CONTEXT_DB` (default: `.thelab/context/context.db` relative to workspace root).
   - `THELAB_CONTEXT_DB` is trusted local process configuration; no MCP tool accepts a path argument.

2. **Read-only tools only**
   - `search_context(query, run_id?, tags?, event_type?, since?, until?)` — keyword + structured search.
   - `get_context_entry(event_id)` — single entry lookup.
   - `get_context_status()` — index status: DB path, entry count, last indexed at, FTS5 availability.

3. **No write tools**
   - No `append_log`, no index rebuild, no database mutation.
   - No shell command execution, training triggers, or arbitrary filesystem access.

4. **Agent-safe response filtering (simple layer, optional)**
   - Slice 3 stores only normalized, redacted local context. Any additional agent-safe / private filtering is out of scope until an explicit design decision is made.
   - If needed, Slice 4 may later apply a minimal filter based on a field added by a future design decision.

5. **Independent MCP demo client support**
   - Extend `thelab-mcp-demo` to support `context` server.
   - Propagate `THELAB_CONTEXT_DB` to the child server via `env=dict(os.environ)`.

6. **No non-goal features**
   - No UI, inference, LLM, vector DB, RAG, cloud, agents, or write paths.

### Acceptance criteria

| ID | Criterion |
|----|-----------|
| S4-AC-01 | `thelab-context-mcp` lists only read-only tools (`search_context`, `get_context_entry`, `get_context_status`). |
| S4-AC-02 | `search_context` returns results from the SQLite index populated by Slice 3. |
| S4-AC-03 | `get_context_entry` returns a single entry by `event_id`. |
| S4-AC-04 | `get_context_status` reports index state and entry count without exposing secrets or filesystem internals. |
| S4-AC-05 | `thelab-mcp-demo context --db <path>` propagates `THELAB_CONTEXT_DB` to the child server and retrieves results. The CLI may explicitly accept `--db` for local use; MCP tools do not accept paths. |
| S4-AC-06 | No MCP tool writes to the database, filesystem, or triggers side effects. |

### Non-goals

- No `append_log` or any write tool.
- No indexing or re-indexing through MCP.
- No shell command execution or arbitrary filesystem access.
- No training, inference, or model serving.
- No UI or LLM integration.
- No cloud or multi-user support.
- No complex authorization or multi-tenant visibility policies.

### Proposed file/module layout

```text
thelab/
  mcp/
    context_mcp.py        # read-only context MCP server
    demo_client.py        # extended to support 'context' server

docs/
  SLICE4_CONTEXT.md       # post-implementation handoff

tests/
  test_context_mcp.py     # MCP integration and safety tests
```

### Test plan

1. **MCP integration tests** (`tests/test_context_mcp.py`)
   - Spawn `thelab-context-mcp` against a temporary indexed DB.
   - Verify `search_context`, `get_context_entry`, `get_context_status` work.
   - Verify no write tools are exposed.

2. **Safety tests**
   - Verify source JSONL is not modified by MCP queries.
   - Verify secret redaction persists through MCP responses.
   - Verify no MCP tool accepts a filesystem path.

3. **Environment propagation test**
   - Run `thelab-mcp-demo context --db <path>` with `THELAB_CONTEXT_DB` set to a temporary path.
   - Assert the demo client retrieves the temporary index, not the default.

4. **Tool-discovery test**
   - List tools and assert only the three read-only tools are present.

### Risks and open questions

| Risk / Question | Mitigation / Note |
|-----------------|-------------------|
| **Database path vs. runs root** | Use `THELAB_CONTEXT_DB` as a dedicated env var, separate from `THELAB_RUNS_ROOT`, because the context DB is a derived index, not a run artifact directory. |
| **Missing/uninitialized index** | Define behavior when the DB does not exist. Suggest returning `ok: true, data: { "indexed": false, "entry_count": 0 }` from `get_context_status` and empty results from search. |
| **Agent-safe filtering scope** | Keep it minimal in Slice 4. If no explicit `private` metadata exists, the filter can be a no-op placeholder. |
| **Demo client extension** | Decide CLI shape: `thelab-mcp-demo context --db <path>` or `thelab-mcp-demo context --context-db <path>`. Consistency with `--run-id` suggests `--context-db`. |

---

## Updated incremental delivery sequence

| Slice | Focus | Key deliverables |
|-------|-------|------------------|
| Slice 0 | Contracts and workspace | Pydantic contracts, hashing, paths |
| Slice 1 | Direct reproducible run | `thelab run model`, artifacts, manifest |
| Slice 2 | MCP reuse | `data_catalog_mcp`, `model_registry_mcp`, demo client |
| **Slice 3** | **Local context store and CLI** | SQLite + FTS5, JSONL indexing, redaction, `thelab context index/search/show` |
| **Slice 4** | **Context MCP and agent-safe retrieval** | Read-only `context_mcp`, demo client extension, `THELAB_CONTEXT_DB` propagation |
| Slice 5 | Service and visual results | Local inference service, minimal dashboard |
| Slice 6 | Global-agent panels and evaluation | Read-only agent panels, thesis evaluation |

This sequence preserves the PRD’s goal of auditable, reproducible, locally served ML while keeping each slice small, testable, and focused on a single interface or policy boundary.
