# Slice 4 Context Handoff — Read-Only Context MCP

> Last updated: 2026-08-10  
> Status: Slice 4 implemented and verified. Slice 5 not started.

## What exists

A read-only stdio MCP server that exposes the Slice 3 SQLite context index to MCP clients. It uses the hardened `ContextReader` abstraction, so it never writes to the database, never creates directories, and never accepts a database path argument.

- `thelab-context-mcp` — read-only context MCP server.
- `thelab-mcp-demo context` — demo client with `--context-db` propagation via `THELAB_CONTEXT_DB`.

## File map

```text
thelab/
  mcp/
    context_mcp.py         # read-only context MCP server
    demo_client.py         # extended to support 'context' server
  context/
    reader.py              # read-only ContextReader used by the MCP server

docs/
  SLICE4_CONTEXT.md        # this file
  ROADMAP.md               # master slice map

tests/
  test_context_mcp.py      # MCP integration and safety tests
```

## Tools exposed

| Tool | Arguments | Description |
|---|---|---|
| `get_context_status` | — | Logical index status (`indexed`, `entry_count`, `last_indexed_at`, `fts5_available`). No absolute DB path. |
| `get_context_entry` | `event_id` | Single entry by ID. Restricted/secret entries are excluded by default. |
| `search_context` | `query?`, `run_id?`, `tags?`, `event_type?`, `since?`, `until?`, `limit?` | FTS5 + structured search. Default privacy filter is `public` + `internal`. |

## Safety guarantees

- The server only instantiates `ContextReader`, which opens SQLite with `mode=ro` and `PRAGMA query_only=ON`.
- No tool accepts a database path; the path comes from `THELAB_CONTEXT_DB` only.
- No `append_log`, `insert`, `update`, or `delete` tools are exposed.
- Default privacy filtering excludes `restricted` and `secret` entries.
- Malformed FTS5 queries return a controlled empty result.

## Usage

First populate the context index (Slice 3):

```bash
thelab context index --source .thelab/local-logs/agent-events.jsonl
```

Then query via MCP:

```bash
# Default DB path (.thelab/context/context.db)
thelab-mcp-demo context

# Custom DB path (sets THELAB_CONTEXT_DB for the child server)
thelab-mcp-demo context --context-db /tmp/demo-context.db
```

## How to verify

```bash
# Full test suite (venv scripts must be on PATH for MCP subprocess tests)
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q

# Manual demo
cat > /tmp/demo-events.jsonl <<'EOF'
{"event_id":"evt-demo","event_type":"system","session_id":"sess-1","run_id":"run-abc","tags":["demo"],"redacted_summary":"Demo event","privacy_level":"internal","timestamp":"2026-08-09T12:00:00+00:00"}
EOF
thelab context index --source /tmp/demo-events.jsonl --db /tmp/demo-context.db
thelab-mcp-demo context --context-db /tmp/demo-context.db
```

Expected output:
- Tool list contains only `get_context_status`, `get_context_entry`, `search_context`.
- `get_context_status` reports `indexed: true`, `entry_count: 1`.
- `search_context("Demo")` returns the entry.
- `get_context_entry("evt-demo")` returns the entry.

## Dependencies

No new dependencies beyond the existing `mcp>=1.6` package. The server reuses the Slice 3 `ContextReader` and SQLite standard library.

## Key design decisions

1. **Read-only only.** The server deliberately has no write tools; indexing remains a CLI/orchestrator concern.
2. **No path arguments.** `THELAB_CONTEXT_DB` is trusted local process configuration, not a tool parameter.
3. **Agent-safe defaults.** `search_context` and `get_context_entry` default to `public` + `internal` privacy levels.
4. **Reuses `ContextReader`.** All bounds, timestamp normalization, malformed-FTS handling, and privacy filtering are inherited from the Slice 3.1 remediation.

## Known limitations

- Stdio transport only; no SSE or HTTP MCP transport yet.
- No semantic search, RAG, embeddings, or vector DB.
- No UI or agent panels yet.

## Next suggested work

See `docs/ROADMAP.md`.

- **Slice 5: Local model inference HTTP service + minimal UI** — build on the existing `model_service` and add a small dashboard.
- **Slice 6: Agent panels and evaluation** — read-only Coding/Logger Agent panel, Research/Copilot panel, and thesis evaluation protocol.
