# Slice U1 Plan — UI v2 dashboard (P1 Stage 3)

> **Status:** ready for review — **binding after user approval**  
> **Last updated:** 2026-08-24  
> **Audience:** coding agent (Kimi or equivalent)  
> **Authority:** This file supersedes informal chat proposals. Implement **only** what is listed here.

---

## 1. Goal

Evolve the existing `thelab-model-service` dashboard into a friendlier, more useful owner-facing UI. This slice is **presentation-only enhancements** plus a small number of thin read-only endpoints. It does **not** add autonomous agent actions.

---

## 2. Current state (read before changing)

The existing dashboard is in `thelab/model_service/static/`:

- `index.html` — tabbed layout: **Models**, **Coding / Logger**, **Research / Copilot**.
- `app.js` — vanilla JS fetching `/health`, `/models`, `/runs/*`, `/agent/*`, `/predict`, context search.
- `styles.css` — basic styling.

Backend is `thelab/model_service/app.py` (FastAPI). It already serves static files and read-only endpoints. No separate UI server.

Recent slices added:
- B1 benchmark manifest: `benchmarks/b1/benchmark_manifest.json`
- B1 benchmark report: `benchmarks/b1/reports/b1_report.md`
- Proposals directory: `proposals/`
- Agent session summaries: `.thelab/local-logs/agent-events.jsonl`

---

## 3. Revised scope for this implementation step

P1_PLAN §U1 describes a rich future dashboard (left rail, DAG, CSV viewer, batch form, log search). This slice is a **pragmatic step** toward that vision. We implement the highest-value, lowest-risk improvements first.

### In scope

1. **Navigation refresh** — replace top tab bar with a left sidebar so the UI can grow. Keep tabs as an internal concept if easier, but the visual nav should be a rail.
2. **Benchmarks panel** — new section that loads `benchmarks/b1/benchmark_manifest.json` and renders:
   - Provider/model selector.
   - Per-domain comparison table (deterministic vs agent).
   - Status badges (OK / AGENT_FAILED).
   - Link to the markdown report.
3. **Proposals browser** — new section that lists files in `proposals/`:
   - Pending / approved / rejected status.
   - Goal, dataset, target, model grid, seeds.
   - Rationale preview (expandable).
   - Link to batch config if approved.
4. **Improved prediction form** — in the Models panel, when a run is selected, render one labeled input per feature column instead of a raw JSON textarea.
5. **Agent session log viewer** — new section that reads `.thelab/local-logs/agent-events.jsonl` and shows recent `agent_session_summary` events (timestamp, source, outcome summary, tags).
6. **UI polish** — CSS design tokens, card layout, loading/empty/error states, better typography, hover states.

### Out of scope (do not implement)

- No separate UI server or new frontend framework (keep vanilla JS/CSS).
- No npm/build step.
- No autonomous actions: no "train", "approve", "run batch", or "delete" buttons that mutate state.
- No DAG visualization.
- No paginated CSV viewer.
- No context DB search beyond what Slice 6 already provides.
- No real-time SSE/WebSocket updates.

---

## 4. Backend additions

All additions go in `thelab/model_service/app.py`. Keep path-safety and allowlist rules consistent with existing endpoints.

### `GET /benchmarks`

Return the B1 benchmark manifest if it exists.

Response:

```json
{
  "ok": true,
  "data": {
    "benchmark_id": "b1",
    "providers": [...]
  }
}
```

If no manifest:

```json
{"ok": true, "data": null, "message": "No benchmark manifest found"}
```

### `GET /proposals`

List proposals from `proposals/` directory. Skip derived files (`*.approved.json`, `*.rejected.json`, `*.batch.json`).

Response:

```json
{
  "ok": true,
  "data": [
    {
      "proposal_id": "prop-...",
      "status": "pending" | "approved" | "rejected",
      "goal": "...",
      "dataset": "...",
      "target": "...",
      "model_grid": [...],
      "seeds": [...],
      "rationale": "...",
      "batch_config": "prop-....batch.json" | null
    }
  ]
}
```

### `GET /proposals/{proposal_id}`

Return full proposal JSON plus status.

### `GET /agent-sessions`

Read `.thelab/local-logs/agent-events.jsonl` and return the most recent `agent_session_summary` events ( newest first, bounded to e.g. 50).

Response:

```json
{
  "ok": true,
  "data": [
    {
      "event_id": "...",
      "timestamp": "...",
      "source": "agent_worker",
      "outcome": {"status": "...", "summary": "..."},
      "tags": [...]
    }
  ]
}
```

---

## 5. Frontend changes

Update `thelab/model_service/static/`:

- `index.html` — add sidebar nav and new panel containers.
- `styles.css` — add CSS custom properties (design tokens), card styles, sidebar layout.
- `app.js` — add fetch/render logic for benchmarks, proposals, agent sessions, and improved predict form.

Keep the existing Models, Coding, Research panels working.

---

## 6. Tests

Add `tests/test_model_service_ui.py` (or extend existing UI tests):

- `GET /benchmarks` returns manifest/null safely.
- `GET /proposals` lists proposals with correct status.
- `GET /proposals/{id}` returns proposal data.
- `GET /agent-sessions` returns recent session summaries.
- Existing endpoints still work.

Use `fastapi.testclient.TestClient` and temp files.

---

## 7. Acceptance criteria (DoD)

- [ ] Sidebar navigation works; existing panels remain accessible.
- [ ] Benchmarks panel renders B1 results with provider selector.
- [ ] Proposals browser shows pending/approved/rejected proposals.
- [ ] Predict form renders labeled feature inputs for selected run.
- [ ] Agent sessions panel shows recent session summaries.
- [ ] New endpoints have tests.
- [ ] `ruff check thelab tests scripts`, `mypy thelab`, full `pytest tests/ -q` green.
- [ ] `scripts/evaluate_thesis.py` still passes.
- [ ] `docs/SLICEU1_CONTEXT.md` written.
- [ ] `docs/ROADMAP.md` marks U1 `done`.

---

## 8. File map

```text
thelab/model_service/app.py            # add /benchmarks, /proposals, /agent-sessions
thelab/model_service/static/index.html # sidebar + new panels
thelab/model_service/static/app.js     # new render functions
thelab/model_service/static/styles.css # design tokens + layout
tests/test_model_service_ui.py         # new tests
docs/SLICEU1_PLAN.md                   # this file
docs/SLICEU1_CONTEXT.md                # after impl
docs/ROADMAP.md
```

---

## 9. Proposed ideas for the next agent (optional polish)

- Add a small "status dot" in the sidebar showing whether the model service is healthy.
- Add keyboard shortcut `?` to show a help overlay with CLI equivalents.
- Make the proposals rationale expandable/collapsible.
- Add a "copy CLI command" button next to each proposal for manual reproduction.
- Dark mode toggle via CSS custom properties.

---

## 10. Paste-ready prompt

See `docs/UI_imp.md`.
