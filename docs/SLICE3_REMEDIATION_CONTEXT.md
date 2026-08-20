# Slice 3 Context Remediation — Pre-Slice-4 Safety Hardening

> Status: completed  
> Scope: harden the existing Slice 3 context store so it is safe for a genuinely read-only Context MCP in Slice 4.

## What this remediation does

This is a **pre-Slice-4 remediation only**. It does **not** implement `context_mcp`, UI, LLM, RAG, embeddings, inference, agents, or any new MCP server.

The work hardens four boundaries of the existing Slice 3 context store:

1. **Defensive redaction** — expands the pattern-based secret detector to cover GitHub, Google, AWS, and Slack token families before any text reaches SQLite.
2. **Strict read-only reader** — introduces `ContextReader`, a separate abstraction from `ContextRepository` that opens the database with `mode=ro`, sets `PRAGMA query_only=ON`, never writes, never creates directories, validates schema, and enforces bounded, safe queries.
3. **CLI isolation** — removes the eager import of `run_model` from the top-level `thelab` CLI so that `python -m thelab context ...` never loads sklearn/pandas/training modules.
4. **Data contracts & privacy policy** — rejects `..` path components in `ArtifactRef`, normalizes timezone-aware timestamps to UTC, and defines an explicit agent-safe privacy default (`public` + `internal`; `restricted` and `secret` excluded unless explicitly requested).

## Files changed

- `thelab/context/redaction.py` — added GitHub (`ghp_`, `github_pat_`, `gho_`), Google (`AIza`), AWS (`AKIA`), and Slack (`xoxb-`, `xoxp-`, `xoxa-`, `xoxs-`) token families.
- `thelab/context/privacy.py` — **new** agent-safe privacy levels and documented `/log` privacy-object mapping.
- `thelab/context/schema.py` — **new** shared schema metadata and row-to-entry normalization.
- `thelab/context/repository.py` — refactored to share `schema.py`; timestamps are now normalized to UTC before storage.
- `thelab/context/reader.py` — **new** `ContextReader` read-only implementation.
- `thelab/context/indexer.py` — uses the `/log` privacy helper; rejects naive timestamps.
- `thelab/context/__init__.py` — exports `ContextReader`, `ContextReaderError`, and privacy helpers.
- `thelab/contracts/artifact_ref.py` — rejects parent-traversal (`..`) path components.
- `thelab/cli.py` — `run_model` is imported only inside the `thelab run model` branch.
- `tests/test_context_redaction.py` — tests for every new token family.
- `tests/test_context_reader.py` — **new** read-only safety, bounds, and privacy tests.
- `tests/test_context_indexer.py` — `/log` privacy mapping tests.
- `tests/test_contracts.py` — `ArtifactRef` parent-traversal tests.
- `tests/test_context_cli.py` — subprocess test proving `thelab context` does not import sklearn/pandas.

## Safety guarantees

- Redaction runs on the summary **before** it is inserted into SQLite.
- `ContextReader`:
  - never calls `mkdir` or creates parent directories;
  - never executes `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`, or `DROP`;
  - opens databases with SQLite URI `mode=ro`;
  - sets `PRAGMA query_only=ON` on every connection;
  - validates the expected schema and degrades safely on missing/incompatible databases;
  - bounds query length, tag count, tag length, and result limit;
  - accepts only timezone-aware timestamps and normalizes them to UTC;
  - returns a controlled empty result for malformed FTS5 syntax;
  - does not expose the absolute database path in `status()`.
- `ArtifactRef.relative_path` cannot be absolute or contain `..`.
- `/log` privacy objects are mapped to stored privacy levels only through an explicit, documented `privacy.level` field; missing or unknown values safely default to `internal`.

## Known limitations

- Redaction is pattern-based and best-effort; it is **not** a cryptographic or complete secret-detection guarantee. Callers must still avoid logging raw secrets.
- Only the `redacted_summary` field is redacted; tags and artifact references are assumed to be controlled vocabulary / relative paths.
- The read-only reader cannot create or repair a database; indexing must still be done through `ContextRepository` / `thelab context index`.
- FTS5 is required; behavior is undefined (and will fail cleanly) if the SQLite build lacks FTS5.
- No semantic search, vector DB, RAG, MCP server, UI, agents, or model inference is included.

## Verification commands and results

### 1. Full test suite

```bash
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q
```

Result:

```text
107 passed, 8 warnings in 26.40s
```

> The MCP integration tests require the package entry-point scripts to be on `PATH` (i.e., the venv `bin` directory). Running pytest with `.venv/bin/python` alone is not sufficient for those tests because the demo client spawns `thelab-data-catalog-mcp` as a subprocess.

### 2. CLI smoke test for `thelab context index`

```bash
PATH=.venv/bin:$PATH
cat > /tmp/demo-events.jsonl <<'EOF'
{"event_id":"evt-demo","event_type":"system","session_id":"sess-1","run_id":"run-20260809-212944-785f03ac","tags":["demo"],"redacted_summary":"Demo event with AWS key [REDACTED] and Slack [REDACTED]","privacy_level":"internal","timestamp":"2026-08-09T12:00:00+00:00"}
EOF
thelab context index --source /tmp/demo-events.jsonl --db /tmp/demo-context.db
thelab context search "AWS" --db /tmp/demo-context.db
thelab context show evt-demo --db /tmp/demo-context.db
```

Result:

- `thelab context index` returned `"ok": true`, `"indexed": 1`.
- The stored `redacted_summary` is `Demo event with AWS key [REDACTED] and Slack [REDACTED]`.
- `search` and `show` returned the entry successfully.

### 3. DB hash-before/hash-after read-only verification

```bash
.venv/bin/python - <<'PY'
import hashlib
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from thelab.contracts import EventType, PrivacyLevel
from thelab.context.contracts import IndexedEntry
from thelab.context.repository import ContextRepository
from thelab.context.reader import ContextReader

with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "context.db"
    repo = ContextRepository(db)
    entry = IndexedEntry(
        event_id="evt-1",
        event_type=EventType.system,
        session_id="session-1",
        redacted_summary="hello world",
        privacy_level=PrivacyLevel.internal,
        timestamp=datetime.now(timezone.utc),
        content_hash="hash-1",
    )
    repo.upsert(entry)

    before = hashlib.sha256(db.read_bytes()).hexdigest()

    reader = ContextReader(db)
    reader.status()
    reader.search("hello")
    reader.search("world", limit=10)
    reader.get("evt-1")
    reader.get("missing")
    reader.search('"malformed')  # invalid FTS5 syntax

    after = hashlib.sha256(db.read_bytes()).hexdigest()
    assert before == after
    print("hash-before:", before)
    print("hash-after: ", after)
PY
```

Result:

```text
hash-before: f9910744ded4652a5c2dadb2c1061ef8da705ad7dd56f6b4bd144bc5af30f28f
hash-after:  f9910744ded4652a5c2dadb2c1061ef8da705ad7dd56f6b4bd144bc5af30f28f
```

The database bytes were unchanged after read-only access.

## Confirmation

No Slice 4 MCP server (`context_mcp`, demo-client extension, or new MCP entry point) was implemented in this remediation. The new `ContextReader` is intentionally a library abstraction so that Slice 4 can build the read-only MCP server on top of it without modifying storage behavior.
