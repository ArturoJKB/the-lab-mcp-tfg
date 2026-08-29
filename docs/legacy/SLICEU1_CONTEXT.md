# Slice U1 Context — UI v2 Dashboard

> Slice U1 of P1 Stage 3: owner-facing dashboard refresh for `thelab-model-service`.

## Changed files

| File | Change |
|---|---|
| `thelab/model_service/app.py` | Added read-only endpoints: `GET /benchmarks`, `GET /proposals`, `GET /proposals/{proposal_id}`, `GET /agent-sessions`. Added helper functions for proposal status, safe basename checks, and agent-session source inference. |
| `thelab/model_service/static/index.html` | Replaced top tab bar with a left sidebar; added **Benchmarks**, **Proposals**, and **Agent Sessions** panel sections; kept existing Models, Coding/Logger, and Research/Copilot panels. |
| `thelab/model_service/static/styles.css` | New dark-theme design tokens, sidebar layout, card styles, badges, loading/empty/error states, responsive rules. |
| `thelab/model_service/static/app.js` | Sidebar navigation, Benchmarks provider selector + comparison table, Proposals browser + detail view, Agent Sessions list, improved Predict form with labeled feature inputs. |
| `tests/test_model_service_ui.py` | New tests for endpoints, path safety, UI hooks, and existing endpoint regression. |
| `docs/ROADMAP.md` | Marked U1 `done`; updated active implementation pointer. |

## What was implemented

1. **Backend endpoints** (all read-only, path-safe):
   - `GET /benchmarks` — returns `benchmarks/b1/benchmark_manifest.json` when present.
   - `GET /proposals` — lists proposal files from `proposals/`, skipping derived `*.approved.json`, `*.rejected.json`, and `*.batch.json` files.
   - `GET /proposals/{proposal_id}` — returns a single proposal plus its status.
   - `GET /agent-sessions` — returns the most recent `agent_session_summary` events from `.thelab/local-logs/agent-events.jsonl`.

2. **Frontend refresh**:
   - Left sidebar navigation with icons.
   - Dark, information-first theme using CSS custom properties.
   - **Benchmarks** panel with provider/model selector and per-domain comparison table.
   - **Proposals** browser with status badges and detail view.
   - **Agent Sessions** panel showing recent session summaries.
   - Improved **Predict** form with one labeled input per feature column.
   - Existing Models, Coding/Logger, and Research/Copilot panels remain functional.

3. **Safety preserved**:
   - No new UI server; extends existing `thelab-model-service`.
   - No write endpoints or autonomous actions.
   - Proposal IDs validated as basename-only; no absolute paths returned.
   - Agent events path configurable via `THELAB_AGENT_EVENTS`; proposals dir via `THELAB_PROPOSALS_DIR`.

## Verification results

```bash
.venv/bin/ruff check thelab tests scripts
# All checks passed!

.venv/bin/mypy thelab
# Success: no issues found in 68 source files

.venv/bin/python -m pytest tests/test_model_service_ui.py tests/test_model_service.py -q
# 23 passed

.venv/bin/python -m pytest tests/ -q
# 353 passed

.venv/bin/python scripts/evaluate_thesis.py
# Overall: PASS (RQ1/RQ2/RQ3 PASS)
```

## Manual check

```bash
.venv/bin/thelab-model-service --port 8000
# Open http://127.0.0.1:8000/
# Verify sidebar navigation, benchmarks panel, proposals browser, agent sessions, and improved predict form.
```

## Limitations

- Batch config and B1 report are shown as filenames, not served as downloads (no new static mount added).
- Benchmark provider selector is local to the UI; no server-side filtering.
- Agent session source is inferred from `agent_mode:*` tags when present.
- No real-time updates; refresh the page to reload data.

## Next suggested slice

D1 — Demos and notebook (P1 Stage 3).
