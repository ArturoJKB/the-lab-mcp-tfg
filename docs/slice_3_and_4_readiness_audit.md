# Independent Slice 4 readiness audit

**Repository audited (read-only):** `/home/user/workspace/audit-slice3-final/Copia de the-lab-mcp-tfg`  
**Audit date:** 2026-08-10  
**Scope:** readiness to implement Slice 4, a read-only local MCP context server. No repository files were changed.

## Recommendation: NO-GO until the two blockers below are addressed

The Slice 3 normalization and FTS search are a usable base, and the supplied real `/log` record is compatible. However, the current repository API mutates SQLite for every construction, including intended read operations. Building an MCP server on it would violate the explicit no-write requirement. In addition, the supplied environment cannot execute the full test suite or the `python -m thelab context` subprocess path.

## What was verified

### Real `/log` JSONL compatibility — PASS, with limited coverage

- The actual `.thelab/local-logs/agent-events.jsonl` contains one valid `agent_session_summary` event in the documented `/log` shape.
- Indexed into an isolated `/tmp` database: `indexed=1`, `skipped=0`, `errors=[]`.
- `search("SQLite")` returned event `devlog_20260809-223139-e73e9924`.
- The normalized record correctly used `project` as `session_id`, retained `context.run_id=None`, and produced tags from `learning.topics` plus `context.slice`.
- Re-indexing the same source yielded `indexed=0`, `skipped=1`, confirming normal single-process idempotency.

Evidence: `thelab/context/indexer.py:63-205,248-292`; actual record `.thelab/local-logs/agent-events.jsonl:1`; isolated audit run output was saved in this session but no project artifact was changed.

**Compatibility limitation (medium):** only one real `/log` record is supplied. Tests use a hand-built lookalike fixture, so compatibility with multiple producers, schema versions, optional/malformed `privacy`, and non-string `context.run_id` is not demonstrated. The normalizer accepts the exact observed record but does not validate `schema_version` or the `/log` nested structure beyond `outcome.summary`.

## Findings — repository code/configuration

### BLOCKER — Context “read” API performs writes and changes existing database bytes

`ContextRepository.__init__()` always calls `_ensure_db()`. That method creates parent directories, creates an FTS5 probe table and drops it, runs schema DDL, and may apply an `ALTER TABLE` migration. Ordinary connections are also read-write (`sqlite3.connect(self.db_path)`), and `PRAGMA query_only` is `0`.

- Evidence: `thelab/context/repository.py:136-151`, including `mkdir`, FTS probe at lines 74-82, `executescript` at line 145, and migration at lines 84-98.
- Empirical check: an existing, valid audit database changed SHA-256 merely by constructing `ContextRepository`, calling `status()`, and `get()`. Hash before: `c3c8...e8dc4`; after: `a2ec...7418f`.
- A status/read on a missing path also creates a 53,248-byte SQLite database.

**Why this matters:** A Slice 4 MCP handler using the existing repository would create files on a missing index and issue DDL on startup/read. It is not read-only even if the tool list contains no explicit write tool.

**Exact fix:** split writer and reader responsibilities before implementing the MCP handler.

1. Keep schema creation, migrations, FTS probing, and upsert only in a writer/indexer repository.
2. Add a reader that never invokes `_ensure_db`, never calls `mkdir`, and opens an existing DB with SQLite URI `mode=ro`; set `PRAGMA query_only=ON` defensively.
3. For absent/non-regular DB paths, return the specified uninitialized status (`indexed: false`, `entry_count: 0`) and empty search results without opening/creating anything.
4. Validate expected schema from `sqlite_master` through the read-only connection and return a controlled error for a corrupted/incompatible index.
5. Add a regression test that hashes a populated DB before and after every MCP tool, and asserts that a missing DB path and its parent are still absent afterward.

### HIGH — “Agent-safe” retrieval has no enforceable visibility policy; only summaries are redacted

Slice 3 allows `public`, `internal`, `restricted`, and `secret` privacy levels, but `search()` and `get()` return all records without a visibility predicate. The normalizer applies regex redaction only to `summary`; it returns raw tags, session/run identifiers, and canonical `related_artifact_refs`. `/log` privacy metadata is not mapped; records lacking root `privacy_level` silently become `internal`.

- Evidence: privacy enum `thelab/contracts/log_entry.py:19-23`; permissive fallback/default in `thelab/context/indexer.py:175,184,188-193`; unfiltered repository return paths `thelab/context/repository.py:207-284`; redaction scope `thelab/context/redaction.py:56-64`.
- Slice 3 handoff explicitly says there is no formal private/agent-safe policy: `docs/SLICE3_CONTEXT.md:77`.

**Why this matters:** An MCP endpoint labelled agent-safe would be able to expose `restricted` and `secret` entries and metadata. Best-effort secret patterns in a summary do not make all indexed metadata agent-safe.

**Exact fix:** decide and encode policy before exposure. A minimal Slice 4 policy is to return only `public` and `internal` records and reject/omit `restricted` and `secret` by default. Define how `/log.privacy` maps into the stored visibility field, redact or exclude all returned free-text metadata (not only summaries), and write tests for each level plus a secret placed in tags/metadata. If a policy decision is intentionally deferred, do not call the MCP surface “agent-safe.”

### HIGH — Required test/release verification is not reproducible from package metadata

`pyproject.toml` specifies broad lower bounds only (`pydantic>=2`, `pandas>=2`, `scikit-learn>=1.4`, `mcp>=1.6`), contains no lock file, and does not pin a supported Python minor version. This conflicts with the README claim of “Pinned dependencies.”

- Evidence: `pyproject.toml:1-20`; README reproducibility claim at `README.md:30-35`.

**Exact fix:** define supported Python versions (or an exact interpreter), give compatible bounded/pinned dependency versions, commit a Python lock file with hashes (for example `uv.lock`/requirements lock), and verify a clean install plus full suite in CI before Slice 4 is declared complete. Include the new MCP entry point in a built-wheel/installed-script smoke test.

### MEDIUM — Invalid FTS5 input raises raw SQLite errors; the planned MCP path needs bounded validation

User query text is correctly passed as a parameter (no conventional SQL injection found), but it is interpreted as FTS5 syntax. Inputs such as `"`, `(`, `NEAR/`, and `foo OR` raise `sqlite3.OperationalError`; a too-large integer limit raises `OverflowError`; `limit=-1` means unlimited SQLite results.

- Evidence: FTS SQL construction and parameter binding: `thelab/context/repository.py:231-281`.
- Empirical isolated checks produced `fts5: syntax error`/`unterminated string`, an overflow for an extremely large limit, and one row for `limit=-1`.

**Exact fix:** MCP tools should use a fixed, safe server-side result cap (or strictly validate `1 <= limit <= MAX` if it is exposed), catch `sqlite3.OperationalError` from `MATCH`, and return a structured invalid-query response rather than a protocol/internal error. Bound query/tag lengths and tag count; parse and normalize only timezone-aware timestamps to UTC.

### MEDIUM — Relative artifact references can contain parent traversal components

`ArtifactRef` rejects absolute paths but accepts `../sensitive.txt` and `a/../../sensitive.txt`. The current context store does not dereference these paths, so this is not a present file-read vulnerability. It becomes unsafe/confusing metadata to hand to MCP clients and would be dangerous if a later tool follows it.

- Evidence: validator checks only `is_absolute()`: `thelab/contracts/artifact_ref.py:26-31`.
- Isolated contract check accepted both parent-traversal examples.

**Exact fix:** reject any `relative_path` whose normalized path contains `..` (and optionally require it to resolve beneath a configured run root at creation). Keep Slice 4 responses as opaque metadata only; do not add an artifact/path tool.

### MEDIUM — Status leaks configured local filesystem location and missing-index behavior is wrong for Slice 4

`status()` returns `str(self.db_path)`, which can expose an absolute local path supplied through `THELAB_CONTEXT_DB`. More importantly, it initializes a missing database due to the blocker above instead of reporting unindexed/absent state.

- Evidence: `thelab/context/repository.py:286-299`; Slice 4 plan calls for a no-write uninitialized status at `docs/SLICE3_PLAN.md:254-261`.

**Exact fix:** use the read-only reader behavior above and return a non-sensitive logical status (`indexed`, count, timestamp, FTS availability). Omit the absolute path from MCP responses; if operational identification is essential, expose only a fixed logical name or a redacted/basename form.

### MEDIUM — Context CLI unnecessarily imports the ML runtime before dispatching a context command

`thelab/cli.py` imports `run_model` at module import time. Consequently, a context-only subprocess imports scikit-learn even though it needs neither training nor pandas. This defeats isolation and turns an unrelated ML environment failure into a context CLI failure.

- Evidence: `thelab/cli.py:7-8,34-58`.

**Exact fix:** lazy-import `run_model` inside the `run model` branch, or split the command entry points so the context server/CLI imports only `thelab.context`. Add a subprocess test covering `python -m thelab context ...` in the clean locked environment.

### LOW — Existing test coverage does not yet cover Slice 4’s claimed safety boundary

There is no `test_context_mcp.py`. Existing context tests cover indexing, repository behavior, redaction, and CLI, but not MCP tool discovery, readonly database bytes, no-file-creation behavior, path-free schemas, privacy filtering, invalid FTS requests, or child-environment propagation.

- Evidence: no `*context*mcp*` test file exists; proposed tests are documented at `docs/SLICE3_PLAN.md:235-252`.

**Exact fix:** add the acceptance/safety tests listed in the final implementation checklist below.

## Findings — supplied archive/environment (not source-code defects)

### BLOCKER — Supplied virtual environment is inconsistent; full suite cannot collect

Using the supplied `.venv` (Python 3.14.3), full `pytest -q` stops during collection: `tests/test_mcp.py` and `tests/test_run.py` cannot import scikit-learn because `sklearn.externals.array_api_extra._lib._utils` lacks `_compat`. No Slice 4 change can be validated against the full baseline in this environment.

- Full-suite result: **2 collection errors**, exit code 2.
- Installed versions observed: Python 3.14.3, scikit-learn 1.9.0, pandas 3.0.5, MCP 2.0.0, pydantic 2.13.4.

The same broken scikit-learn import makes `python -m thelab context index ...` exit 1 before a database is created. This particular context CLI failure is caused by the archive’s Python environment plus the eager-import code issue above.

**Required environment repair:** do not trust or ship the supplied 409 MB `.venv`; build a fresh environment from a lock against the selected supported Python version. Confirm `python -c 'import sklearn'`, run the complete suite, then run installed CLI and MCP smoke tests.

### HIGH — The archive is not a usable Git repository and is therefore not auditable/reproducible as a revision

The supplied `.git` directory exists but is empty; `git -C <repo> status` returns “not a git repository.” There is no commit/branch identity to tie the audit, run outputs, or future Slice 4 implementation to a source revision.

**Required archive repair:** provide a normal Git worktree (including `HEAD`, object database, and refs) or a source archive with a separately recorded commit SHA and checksum.

### MEDIUM — Archive contents include ignored/generated state and a malformed nested run path

Despite `.gitignore`, the archive includes `.venv`, `.pytest_cache`, `__pycache__`, local log data, and generated runs. It also contains `runs/runs/run-20260809-202059-b3fe4fd9`, contrary to the documented `runs/<run_id>` convention. These do not prevent a read-only context MCP server, but they make baseline provenance and repeatability unclear.

**Required archive repair:** distribute clean source plus intentionally curated fixtures; put generated runs/logs in a clearly labelled fixture set or manifest, remove/avoid vendored virtual environments and caches, and correct or document the nested run path.

## Tests executed during the audit

| Check | Result |
|---|---|
| Index actual `/log` JSONL into isolated DB | PASS: 1 indexed, FTS result returned, re-index skipped duplicate |
| Context test files only | 37 passed, 1 failed |
| Failure in context-only set | `test_thelab_context_invocation_via_subprocess` failed due supplied scikit-learn import through eager `run_model` import |
| Complete project suite | BLOCKED: 2 collection errors from supplied scikit-learn installation |
| Existing MCP module imports against supplied MCP 2.0.0 | PASS: common, data catalog, registry, and demo client imported |
| Existing DB byte immutability under repository construction/status/get | FAIL: database SHA-256 changed |
| FTS5 availability and DB integrity in supplied Python SQLite | PASS: SQLite 3.50.4 has FTS5; isolated DB integrity check returned `ok` |

## Exact pre-Slice-4 implementation checklist

1. **Implement a strictly read-only context reader** as described under the blocker; MCP handlers must never instantiate the current write-capable `ContextRepository`.
2. **Define and enforce agent-safe visibility**: default deny `restricted`/`secret`, map `/log.privacy`, and prevent non-summary metadata from bypassing redaction/policy.
3. **Add `thelab/mcp/context_mcp.py` with only** `search_context`, `get_context_entry`, and `get_context_status`; accept no path/source/database arguments; no import of indexer or writer methods.
4. **Use precise, bounded tool schemas**: safe strings/lists/timestamps, a fixed or capped result limit, controlled invalid FTS errors, and no filesystem-path parameter anywhere.
5. **Do not leak the DB’s absolute path** in MCP status. Missing DB means uninitialized/empty without any filesystem change.
6. **Harden artifact reference validation** to reject parent traversal; do not resolve/dereference artifact refs in Slice 4.
7. **Add an MCP entry point** `thelab-context-mcp` and demo-client `context` mode that sets `THELAB_CONTEXT_DB` only in the child environment; MCP tool input must not override it.
8. **Add end-to-end tests** that spawn the installed/module server against a temporary prebuilt index and prove: exact three-tool discovery; search/get/status correctness; byte-for-byte DB and source-log immutability; missing DB no-create; no accepted path fields; privacy filtering/redaction; traversal metadata rejection; malformed FTS structured error; and environment propagation.
9. **Repair reproducibility first**: lock dependencies, choose a supported Python version, remove reliance on archive `.venv`, lazy-load the ML CLI branch, then run clean-install full tests plus MCP smoke tests.
10. **Provide a valid revisioned source archive** before recording Slice 4 verification evidence.
