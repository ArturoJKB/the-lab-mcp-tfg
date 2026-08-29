# Slice 4.1 Remediation Plan — Post–Context-MCP Safety Hardening

> **Status:** ready for implementation  
> **Last updated:** 2026-08-10  
> **Audience:** coding agent (implement only what this plan lists)  
> **Source:** independent Slice 4 post-implementation audit (2026-08-10)

## Role split

| Role | Does | Does not |
|---|---|---|
| Audit agent | Findings, this plan, re-audit after | Implement code in this pass |
| Coding agent | Implement tasks 1–5 below, add/update tests, run verification | Expand scope, start Slice 5/6, redesign architecture |

After green tests, **stop**. Do not open follow-up scope. Hand back for re-audit.

---

## Goal

Make **CLI retrieval** match the **MCP agent-safe read-only policy**, and tighten the MCP contract so status counts, tool schemas, and response payloads are consistent with that policy.

Slice 4 MCP is already largely correct. This remediation closes residual gaps found in audit—not a rewrite.

---

## In scope (must-fix)

1. CLI `search` / `show` → `ContextReader` only (privacy + no writes).
2. MCP/reader `entry_count` = agent-visible rows only.
3. Tighten MCP tool JSON schemas (bounds + `additionalProperties: false`).
4. MCP public response DTO (drop internal fields).
5. Expand regression tests for the above.

## Out of scope (do not implement in 4.1)

- Slice 5 / Slice 6 (model service UI, agent panels).
- Dependency lockfile, pinned versions, supported-Python matrix, README pin honesty.
- Changing `/log` mapping when `contains_sensitive_data` is true but `privacy.level` is absent.
- Caching / session-scoped `ContextReader` inside the MCP server.
- New MCP transports (SSE/HTTP), write tools, path tool arguments, privacy-override tool params.
- RAG, embeddings, vector DB, cloud, new dependencies.
- Broad refactors of `ContextRepository` beyond what CLI needs.

---

## Background (audit summary)

### Already good (do not break)

- `thelab-context-mcp` exposes only `get_context_status`, `get_context_entry`, `search_context`.
- MCP uses `ContextReader` (`mode=ro`, `PRAGMA query_only=ON`); no indexer/writer imports.
- No tool accepts a database path; path comes from `THELAB_CONTEXT_DB` only.
- Default privacy filter: `public` + `internal`; `restricted` / `secret` excluded.
- DB and source JSONL bytes unchanged under MCP queries; missing DB creates nothing.
- Full suite was green at audit time (`132 passed` with venv on `PATH`).
- `ArtifactRef` rejects `..`; CLI no longer eagerly imports sklearn for context commands.

### Must fix

| ID | Severity | Finding |
|---|---|---|
| F1 | HIGH | `thelab context search` / `show` still use `ContextRepository`: can mkdir/DDL, RW open, return secret/restricted, and (via repo status) expose paths. |
| F2 | MEDIUM | `get_context_status.entry_count` is `COUNT(*)` over all rows, including non-agent-visible privacy levels. |
| F3 | MEDIUM | MCP tool schemas lack bounds and `additionalProperties: false` (junk args like `db_path` appear accepted). |
| F4 | MEDIUM | MCP returns full `IndexedEntry.model_dump()` including `content_hash` and `indexed_at`. |
| F5 | LOW | Tests miss secret-via-MCP, schema bounds, invalid limit/timestamp paths, CLI reader migration. |

---

## Current code anchors

```text
thelab/context/cli.py           # search/show still ContextRepository — FIX
thelab/context/reader.py        # status entry_count — FIX
thelab/context/privacy.py       # AGENT_SAFE_PRIVACY_LEVELS — REUSE
thelab/context/repository.py    # writer/index only — keep for index
thelab/mcp/context_mcp.py       # schemas + DTO + status via reader — FIX
tests/test_context_cli.py       # extend
tests/test_context_mcp.py       # extend
tests/test_context_reader.py    # extend status count semantics
```

Reader bounds (keep aligned with schemas):

- `_MAX_QUERY_LEN = 200`
- `_MAX_TAGS = 10`
- `_MAX_TAG_LEN = 64`
- `_MAX_LIMIT = 1000`
- default search `limit = 50`

---

## Task 1 — CLI read path uses `ContextReader`

**Files:** `thelab/context/cli.py`, `tests/test_context_cli.py`

### Requirements

1. **`thelab context index`**
   - Continues to use `ContextRepository` + `index_source_file`.
   - May create DB/dirs as today.

2. **`thelab context search`**
   - Instantiate `ContextReader(db_path)` only.
   - Call `reader.search(...)` with the same CLI filters (`query`, `run_id`, tags, `event_type`, `since`, `until`, `limit`).
   - Default privacy = reader default (`AGENT_SAFE_PRIVACY_LEVELS`). Do **not** add a CLI flag to request secret/restricted in this slice.
   - On `ContextReaderError`, print JSON `{"ok": false, "error": "..."}` and exit non-zero.
   - Do not call `ContextRepository`, `mkdir`, or schema DDL on this path.

3. **`thelab context show`**
   - Use `ContextReader.get(event_id)` only.
   - Missing or privacy-filtered entries → `ok: false`, same as “not found” (do not leak that a secret id exists).

4. **Serialization**
   - Keep CLI JSON useful for humans/operators. CLI **may** still include `content_hash` / `indexed_at` if already present in `_entry_to_dict`.
   - Do **not** print absolute `db_path` on search/show success payloads.
   - Do not add `db_path` to search/show output.

5. **Imports**
   - `ContextRepository` only needed for `index`. Prefer importing reader for search/show; avoid pulling writer behavior into read commands.

### Tests (`tests/test_context_cli.py`)

Add or extend tests to prove:

| Test | Assert |
|---|---|
| Search does not create missing DB/parent | missing path stays absent after `search` |
| Search/show do not change DB bytes | SHA-256 before/after identical on a populated DB |
| Secret/restricted omitted | index public+internal+restricted+secret; search/show never return restricted/secret |
| Invalid limit/query surfaces error | non-zero exit or `ok: false` with message (match reader validation) |

Reuse patterns from `tests/test_context_reader.py` and existing CLI subprocess tests. Keep sklearn-isolation test passing.

### Done when

- `search` / `show` never construct `ContextRepository`.
- Privacy default matches MCP.
- New CLI tests pass.

---

## Task 2 — Agent-visible `entry_count` in status

**Files:** `thelab/context/reader.py`, tests in `tests/test_context_reader.py` and `tests/test_context_mcp.py`

### Requirements

1. `ContextReader.status()["entry_count"]` must count only rows whose `privacy_level` is in `AGENT_SAFE_PRIVACY_LEVELS` (default agent-safe set).
2. Do **not** add `total_entry_count` to MCP responses in this slice.
3. `indexed` remains true when DB exists and schema is OK, even if visible count is 0.
4. `last_indexed_at` may stay as max over all rows **or** over visible rows only—pick **visible rows only** for consistency with `entry_count`. Document the choice in a one-line comment near the query.
5. MCP `get_context_status` already returns `reader.status()`—no separate counter in `context_mcp.py` unless needed.

### Implementation sketch

```sql
SELECT COUNT(*) FROM entries
WHERE privacy_level IN ('public', 'internal')
```

Use the same validated privacy value list as `get`/`search` (from `AGENT_SAFE_PRIVACY_LEVELS`), not hard-coded strings scattered elsewhere if avoidable.

### Tests

| Test | Assert |
|---|---|
| Reader status count | DB with 2 safe + 2 restricted/secret → `entry_count == 2` |
| MCP status count | same fixture via MCP → `entry_count == 2` |
| Update existing MCP test | `test_context_status_returns_logical_fields` currently expects `3` with a fixture that includes restricted—change fixture expectation to **visible only** (public+internal = 2) |

### Done when

- Status count matches the default search universe.
- MCP + reader tests updated and green.

---

## Task 3 — Tighten MCP tool JSON schemas

**File:** `thelab/mcp/context_mcp.py`

### Requirements

Apply to all three tools where applicable:

1. `"additionalProperties": false` on every tool `input_schema` object.
2. `get_context_entry`:
   - `event_id`: `type: string`, `minLength: 1` (and keep `required: ["event_id"]`).
3. `search_context`:
   - `query`: `type: string`, `maxLength: 200`
   - `run_id`: `type: string`
   - `tags`: `type: array`, `maxItems: 10`, `items: { type: string, maxLength: 64 }`
   - `event_type`: `type: string`
   - `since` / `until`: `type: string` (ISO-8601; runtime still validates timezone-aware)
   - `limit`: `type: integer`, `minimum: 1`, `maximum: 1000`, `default: 50`
4. Do **not** add `privacy_levels`, `db_path`, `path`, or any filesystem parameter to schemas.
5. Runtime validation in `ContextReader` remains the authority; schemas must **match** those bounds (not invent different numbers).

### Tests

| Test | Assert |
|---|---|
| Schema advertisement | `list_tools` → `search_context` schema has `additionalProperties is false`, `limit.maximum == 1000`, `query.maxLength == 200` |
| No path properties | schema property keys do not include `db_path` / `path` |

Note: some MCP client stacks may still deliver extra args; handler already ignores unknown keys. Schema correctness is for agents/clients. Keep runtime bounds tests.

### Done when

- Schemas match reader bounds.
- Discovery test asserts key schema constraints.

---

## Task 4 — MCP public response DTO

**File:** `thelab/mcp/context_mcp.py` (small helper in-file is fine; no new package required)

### Requirements

Replace raw `entry.model_dump(mode="json")` for tool responses with an explicit public dict:

**Include:**

- `event_id`
- `event_type`
- `session_id`
- `run_id`
- `tags`
- `redacted_summary`
- `related_artifact_refs` (JSON-safe; existing artifact ref dump is OK)
- `privacy_level`
- `timestamp`

**Exclude:**

- `content_hash`
- `indexed_at`

Apply to both `get_context_entry` and `search_context` list items.

`get_context_status` unchanged aside from Task 2 semantics (still no `db_path`).

### Tests

| Test | Assert |
|---|---|
| Get/search payload keys | response entries do not contain `content_hash` or `indexed_at` |
| Required fields present | `event_id`, `redacted_summary`, `privacy_level` present on a known public entry |

### Done when

- No internal index bookkeeping fields on MCP wire format.
- Tests lock the field set.

---

## Task 5 — Expand safety tests

**Files:** `tests/test_context_mcp.py`, `tests/test_context_cli.py`, `tests/test_context_reader.py` as needed

### Required cases (if not already covered after tasks 1–4)

1. **Secret exclusion via MCP** — index a `privacy_level=secret` entry; `get_context_entry` → `ok: false`; `search_context` never returns it.
2. **Restricted exclusion via MCP** — keep/extend existing restricted test.
3. **Invalid limit via MCP** — `limit` -1, 0, 1001 → `ok: false` with error string.
4. **Invalid timestamp via MCP** — naive or garbage `since` → `ok: false`.
5. **DB immutability** — existing hash test remains.
6. **Missing DB no-create** — existing test remains.
7. **Source JSONL immutability (MCP)** — if cheap: hash source file before/after search/get/status; assert equal. Optional but preferred.
8. **CLI tasks from Task 1** — must land.

Do **not** require installed-entrypoint subprocess smoke or demo-client env tests in 4.1 (deferred).

### Fixtures

Extend `_index_demo_db` (or local helpers) to include a `secret` row where needed. Avoid depending on developer machine `.thelab/` state.

---

## Implementation order

Execute strictly in order:

1. Task 1 (CLI reader) + CLI tests  
2. Task 2 (status count) + reader/MCP test updates  
3. Task 3 (schemas) + discovery assertions  
4. Task 4 (DTO) + payload assertions  
5. Task 5 (fill any remaining gaps)  
6. Full verification command  

No drive-by refactors. No new dependencies. No commits unless the user explicitly asks.

---

## Verification (definition of done)

```bash
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q
```

Expected: **all tests passed** (no new failures; warnings pre-existing from sklearn/joblib are OK).

Manual smoke (optional but recommended):

```bash
PATH=.venv/bin:$PATH
# index into temp DB
thelab context index --source .thelab/local-logs/agent-events.jsonl --db /tmp/s41-context.db
# read path must not create writes: search/show
thelab context search "Slice" --db /tmp/s41-context.db
thelab-mcp-demo context --context-db /tmp/s41-context.db
```

### Acceptance checklist

- [ ] `thelab context search` / `show` use `ContextReader` only  
- [ ] CLI search/show omit secret/restricted by default  
- [ ] CLI search/show do not create DB or change DB bytes  
- [ ] `get_context_status.entry_count` counts agent-safe rows only  
- [ ] MCP tool schemas: `additionalProperties: false` + limit/query/tag bounds  
- [ ] MCP entry payloads omit `content_hash` and `indexed_at`  
- [ ] Secret + restricted excluded on MCP get/search  
- [ ] Invalid limit/timestamp return structured MCP errors  
- [ ] `PATH=.venv/bin:$PATH pytest tests/ -q` green  
- [ ] No Slice 5+ files, no lockfile work, no new deps  

---

## Deferred follow-ups (for later plans / audit)

| Item | Notes |
|---|---|
| Dependency lock + supported Python | Prior HIGH reproducibility gap; separate chore |
| `/log` + `contains_sensitive_data` without level | Consider mapping to `restricted` in a policy slice |
| Cache `ContextReader` per MCP process | Performance only |
| Demo-client `--context-db` automated test | Nice-to-have |
| Installed script `thelab-context-mcp` smoke | Tests may keep `python -m thelab.mcp.context_mcp` |

---

## Handoff back to audit

When the checklist is green:

1. Stop implementing.  
2. Summarize changed files and test output for the user.  
3. User runs `/log` if desired.  
4. Audit agent re-checks only 4.1 acceptance (chat disposition)—no scope expansion.

---

## Non-goals reminder (from `docs/Agents.md`)

- Do not add arbitrary shell/LLM code execution.  
- Do not modify files outside this remediation.  
- Do not silently change architecture or dependencies.  
- Ask before destructive commands or broad refactors.
