# Slice 3 Context Handoff — Local Context Store and CLI

> Last updated: 2026-08-09  
> Status: Slice 3 implemented and verified. Slice 4 not started.

## What exists

A local SQLite + FTS5 context store that indexes JSONL agent logs defensively, plus a CLI to manage it.

- `thelab context index` — idempotently index `.thelab/local-logs/agent-events.jsonl` into `.thelab/context/context.db`.
- `thelab context search "<query>"` — FTS5 keyword search with structured filters.
- `thelab context show <event_id>` — display a single indexed entry.
- Defensive secret redaction is applied before any content enters the SQLite index.
- Supports both canonical LogEntry-style events and the existing `/log` agent-session-summary schema.
- Malformed records are skipped and reported; they are never persisted.

## File map

```text
thelab/
  __main__.py            # enables `python -m thelab`
  cli.py                 # top-level CLI wiring
  context/
    __init__.py
    contracts.py         # IndexedEntry
    repository.py        # SQLite + FTS5 repository
    indexer.py           # JSONL -> SQLite indexing
    redaction.py         # secret-detection and redaction
    filters.py           # SearchFilters dataclass
    cli.py               # `thelab context` commands

docs/
  SLICE3_PLAN.md         # detailed slice plan
  SLICE3_CONTEXT.md      # this file

tests/
  test_context_redaction.py
  test_context_repository.py
  test_context_indexer.py
  test_context_cli.py
```

## SQLite schema

- `entries` — normalized log entry fields, including `event_id`, `content_hash`, `indexed_at`, and `related_artifact_refs` (JSON text).
- `entry_tags` — many-to-many tag mapping.
- `entries_fts` — FTS5 virtual table over `redacted_summary`.

## CLI usage

```bash
# Index local logs
thelab context index

# Search
thelab context search "error"
thelab context search "validation" --run-id run-20260809-212944-785f03ac --tag important

# Show one entry
thelab context show evt-1

# Use a custom database path (testing/local use)
thelab context index --db /tmp/context.db --source /tmp/agent-events.jsonl
thelab context search "error" --db /tmp/context.db
```

The database path can also be set via `THELAB_CONTEXT_DB`.

## Key design decisions

1. **Derived index path.** The SQLite database lives at `.thelab/context/context.db`. It is a local derivative and is ignored by Git.
2. **Single source file.** The indexer reads only `.thelab/local-logs/agent-events.jsonl`. Per-run `runs/<run_id>/events.jsonl` files are technical training events, not agent logs; they can be linked later via `run_id`.
3. **Schema normalization.** A dedicated layer adapts both canonical LogEntry events and the existing `/log` agent-session-summary shape before persistence.
4. **Malformed record handling.** Invalid records are skipped and reported; they are never inserted and never cause content-conflict errors.
5. **Idempotency by content hash.** Each valid entry uses `event_id` as its visible identifier and a SHA-256 hash of its canonical JSON as a content fingerprint. Re-indexing the same content is a no-op; the same `event_id` with different content is rejected.
6. **Defensive redaction before storage.** API keys, bearer tokens, password assignments, private-key blocks, and common env-var secret patterns are masked before the summary enters the SQLite index. Original source files are never modified.
7. **No MCP, UI, agents, or visibility policy.** This slice is CLI-only; formal `private` / `agent_safe` policy is out of scope.

## Verification

```bash
# Full test suite
. .venv/bin/activate && python -m pytest tests/ -q

# Manual end-to-end (uses temporary files; does not touch .thelab/local-logs/)
cat > /tmp/demo-events.jsonl <<'EOF'
{"event_id":"evt-demo","event_type":"system","session_id":"sess-1","run_id":"run-20260809-212944-785f03ac","tags":["demo"],"redacted_summary":"Demo event with API key sk-1234567890abcdef","privacy_level":"internal","timestamp":"2026-08-09T12:00:00+00:00"}
EOF
thelab context index --source /tmp/demo-events.jsonl --db /tmp/demo-context.db
thelab context search "demo" --db /tmp/demo-context.db
thelab context show evt-demo --db /tmp/demo-context.db
```

Expected: the indexed `redacted_summary` contains `[REDACTED]` instead of the raw API key.

## Test results

- `tests/test_context_redaction.py`: 8 passed
- `tests/test_context_repository.py`: 13 passed
- `tests/test_context_indexer.py`: 13 passed
- `tests/test_context_cli.py`: 7 passed
- Full suite: 81 passed (after fixes)

## Known limitations

- Redaction is pattern-based and best-effort; callers should still avoid logging raw secrets.
- Only single JSONL source file is supported.
- FTS5 is required; the CLI fails with a clear error if the SQLite build lacks it.
- No semantic search, embeddings, RAG, MCP, UI, or agent panels yet.

## Next suggested work

**Slice 4: Context MCP and Agent-Safe Retrieval.** Implement read-only `context_mcp` (`search_context`, `get_context_entry`, `get_context_status`) with `THELAB_CONTEXT_DB` propagation in the demo client.
