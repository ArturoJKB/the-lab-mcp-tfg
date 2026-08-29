# Slice 6 Context Handoff — Agent Panels and Thesis Evaluation

> Last updated: 2026-08-10  
> Status: Slice 6 implemented and verified. P0 implementation complete pending final audit.

## What exists

Slice 6 closes P0 by adding human agent panels to the existing model-service dashboard, a reproducibility gate, and an automated thesis evaluation protocol.

- **Reproducibility gate:** `pyproject.toml` declares supported Python; `requirements.lock` pins dependencies; README documents the install path. The lockfile was verified by installing into a fresh temporary venv and running `pytest --version`.
- **Read-only agent HTTP APIs** on `thelab-model-service`:
  - `/agent/coding/overview`
  - `/agent/coding/runs`
  - `/agent/coding/runs/{run_id}`
  - `/agent/research/context/status`
  - `/agent/research/context/search`
  - `/agent/research/context/entries/{event_id}`
- **Coding/Logger panel:** run list, run details, allowlisted artifact browser, read-only banner.
- **Research/Copilot panel:** local context status, search, entry detail, no-LLM banner.
- **Thesis evaluator:** `scripts/evaluate_thesis.py` checks RQ1 (reproducibility), RQ2 (MCP interoperability), and RQ3 (context retrieval), exiting 0 on success.
- **Evaluation record:** `docs/THESIS_EVALUATION.md` contains rubrics, method, environment, manual demo script, and recorded results.

## File map

```text
pyproject.toml                         # requires-python pinned
requirements.lock                      # T0 dependency lock
README.md                              # install from lock

thelab/model_service/
  app.py                               # Slice 5 + agent HTTP APIs
  static/
    index.html                         # tabbed dashboard (Models / Coding / Research)
    app.js                             # panel logic
    styles.css                         # tab + banner styles

scripts/
  evaluate_thesis.py                   # RQ1–RQ3 automated checks

tests/
  test_agent_panels.py                 # API + UI hooks + privacy/path safety
  test_thesis_eval.py                  # evaluator exits 0 and reports PASS

docs/
  SLICE6_PLAN.md                       # binding implementation plan
  SLICE6_CONTEXT.md                    # this file
  THESIS_EVALUATION.md                 # protocol + recorded results
  ROADMAP.md                           # Slice 6 marked done
```

## Agent HTTP APIs

| Endpoint | Purpose |
|---|---|
| `GET /agent/coding/overview` | Logical workspace summary (counts, recent run ids). |
| `GET /agent/coding/runs` | Safe run list with status and dataset basename. |
| `GET /agent/coding/runs/{run_id}` | Run details + allowlisted artifact names. |
| `GET /agent/research/context/status` | Context index status (no `db_path`). |
| `GET /agent/research/context/search` | Bounded context search; agent-safe privacy default. |
| `GET /agent/research/context/entries/{event_id}` | Single context entry as public DTO. |

All endpoints are read-only, path-safe, and return no absolute filesystem paths.

## Dashboard tabs

Open `http://127.0.0.1:8000/` after starting `thelab-model-service`:

- **Models** — existing Slice 5 panels: status, approved models, metrics, artifacts, predict.
- **Coding / Logger** — run evidence viewer with read-only banner.
- **Research / Copilot** — local context search with no-LLM banner.

## Safety boundaries

- No new MCP server (`agent_mcp`) was added.
- No LLM SDK, API keys, embeddings, or RAG.
- Context access uses `ContextReader` only.
- Dataset paths are exposed as basenames only.
- Context entries use the same public DTO as `context_mcp` (no `content_hash`/`indexed_at`).
- Default service bind remains `127.0.0.1`.

## How to verify

```bash
# Full test suite
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q

# Thesis evaluator
PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py

# Manual UI
PATH=.venv/bin:$PATH thelab-model-service --port 8000
# open http://127.0.0.1:8000/
```

Expected results:
- `pytest` → all tests pass.
- `evaluate_thesis.py` → exit 0, `Overall: PASS`, RQ1–RQ3 PASS.

## Key design decisions

1. **No new MCP server.** Agent interoperability is proven by reusing existing `model_registry_mcp`, `workspace_mcp`, and `context_mcp`.
2. **No LLM in P0.** Research/Copilot is a structured local-evidence browser.
3. **Lockfile as reproducibility gate.** `requirements.lock` from `pip freeze` pins the environment used for verification.
4. **Evaluator composes existing pieces.** It trains, indexes, and calls MCP rather than mocking them, so the checks exercise real code paths.

## Known limitations

- Lockfile is a `pip freeze` pin without hashes; reproducibility assumes PyPI package availability.
- The evaluator uses a small fixture dataset and a single model.
- MCP transport evaluated is stdio only.
- Context redaction coverage is best-effort; RQ3 verifies retrieval, not exhaustive secret detection.

## Next step

Final audit (`/audit 6`) against `docs/SLICE6_PLAN.md`. After that, P0 is complete and the project can move to documentation/memoria or P1 planning.
