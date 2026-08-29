# Slice 5 Plan — Minimal Local UI on Existing Model Service

> **Status:** ready for implementation  
> **Last updated:** 2026-08-10  
> **Audience:** coding agent (implement only what this plan lists)  
> **Sources:** Slice 5 planning audit + coding-agent proposal (merged)

## Role split

| Role | Does | Does not |
|---|---|---|
| Coding agent | Implement tasks below, tests, `SLICE5_CONTEXT.md` handoff | Expand scope, start Slice 6, redesign architecture |
| Audit agent | Re-audit after green tests | Implement code in the coding pass |

After green tests and handoff doc, **stop**. Do not open follow-up scope.

---

## Goal

Provide a **minimal human-facing local dashboard** for approved model runs, artifacts, metrics, and prediction—served by the **existing** `thelab-model-service` FastAPI app.

This slice is **UI + thin read-only HTTP helpers**. It is **not** a rewrite of the inference backend.

---

## Already done (do not rebuild)

These shipped in **Slice 2** and must remain working:

| Piece | Location |
|---|---|
| `GET /health` | `thelab/model_service/app.py` |
| `GET /models` (completed + approved only) | same |
| `POST /predict` | same |
| CLI `thelab-model-service` (default bind `127.0.0.1:8000`) | `thelab/model_service/cli.py` |
| Tests | `tests/test_model_service.py` |

Agents continue to use MCP `predict` on `model_registry_mcp`. This HTTP service is for **local human/UI** consumption.

---

## Locked product decisions (do not re-ask)

1. **Serving model:** UI is served by **`thelab-model-service`** (same FastAPI process). No separate `thelab ui` server.
2. **Tech stack:** **Vanilla HTML + CSS + JS only**. No React/Vue/Svelte, no npm/Vite build step, no new frontend dependencies.
3. **Context integration:** **None** in Slice 5. No context DB, no `context_mcp`, no `THELAB_CONTEXT_DB` in the model service.
4. **Artifact browser:** List + render **allowlisted** JSON/text artifacts. No `model.joblib` download. No absolute paths. No arbitrary path parameters.
5. **Navigation:** **Single-page** dashboard. No client-side router. No agent navigation (Slice 6).

---

## In scope

1. Static dashboard mounted on the existing FastAPI app (`GET /` → `index.html`).
2. Thin **read-only** REST endpoints for run summary and allowlisted artifacts.
3. Dashboard panels: status, approved models, metrics, artifact browser, predict form.
4. Safety defaults (localhost-oriented, no writes, path-safe artifact access).
5. Tests (TestClient / httpx only).
6. Docs: this plan (done), then `docs/SLICE5_CONTEXT.md` after implementation; update `docs/ROADMAP.md` status when complete.

## Out of scope (do not implement)

- Separate UI process or second HTTP server.
- React/Vue/SPA build tooling or new UI frameworks.
- Context index status, context search, or any Slice 3/4 integration.
- Agent panels, LLM calls, Coding/Logger or Research/Copilot UI (Slice 6).
- Playwright / browser E2E harness.
- Dependency lockfile / Python pin chore (separate track).
- SSE/HTTP MCP transports.
- Write endpoints (index, delete, train, approve, mutate runs).
- Serving or downloading `model.joblib`.
- Auth, CORS-for-internet, cloud deploy, multi-user.
- Showing absolute filesystem paths (runs root, DB paths, etc.).

---

## Backend additions

Reuse `thelab.mcp.common`: `get_runs_root`, `safe_run_dir`, `discover_run_ids`, `load_json_artifact`, `load_text_artifact`.

### Endpoints to add

All return the existing envelope style where applicable: `{"ok": true, "data": ...}` or HTTP error / `{"ok": false, "error": "..."}` consistent with current service patterns.

#### 1. `GET /runs/{run_id}`

Run summary for dashboard selection and predict form.

**Requirements:**

- Validate `run_id` via `safe_run_dir` (reject `..`, separators, hidden names—same as MCP).
- Prefer **approved + completed** runs for full summary used by predict UI (same gates as `/models` and `/predict`).
- If run missing/unsafe → 404.
- If not completed/approved → 400 with clear message (or 404—pick one and test it; prefer **400** with reason to match `/predict`).

**Response `data` should include at least:**

- `run_id`
- `final_status`, `validation_status` (from manifest)
- `model`, `target` (from inputs)
- `feature_columns` (same derivation as predict: profile columns minus target)
- `metrics` summary (`test_accuracy`, `test_f1_macro` when present)
- Optional short fields from inputs/manifest useful to the UI (seed, dataset name)—keep small

**Do not** include absolute paths.

#### 2. `GET /runs/{run_id}/artifacts`

List artifacts available for the run.

**Requirements:**

- `safe_run_dir` required.
- Return only **allowlisted basenames** that exist as files in the run directory (and/or intersect with manifest `artifact_refs` basenames—either approach is fine if tests lock behavior).
- Each item: `{ "name": "<basename>", "kind": "json" | "text" }` (or equivalent).
- **Never** return absolute paths or parent-relative paths.
- **Never** list `model.joblib` (even if present on disk).

#### 3. `GET /runs/{run_id}/artifacts/{artifact_name}`

Fetch one allowlisted artifact.

**Requirements:**

- `artifact_name` must be a **basename only** (no `/`, `\`, `..`).
- Must be in the allowlist below.
- Load via run dir join after `safe_run_dir`; reject if resolved path escapes run dir.
- JSON files → parse and return JSON in `data`.
- `model_card.md` → return text (string field).
- Missing → 404.
- Non-allowlisted → 400 or 404 (prefer **400** “not allowed”).

### Artifact allowlist

```text
manifest.json
metrics.json
data_profile.json
inputs.json
validation_report.json
training_config.json
dataset_contract.json
model_card.md
task_spec.json
```

**Optional (only if cheap):** `events.jsonl` as a **bounded** view—e.g. `{ "line_count": N, "tail": [ ... last 20 parsed objects or raw lines ] }`. Do **not** build a full log explorer.

**Excluded:** `model.joblib`, any other file name, nested paths.

### Existing endpoints

- Keep `/health`, `/models`, `/predict` behavior.
- Do not break `tests/test_model_service.py`.

### CLI

- Default host remains `127.0.0.1`.
- No change required unless needed to document UI URL; do not default-bind `0.0.0.0`.

---

## Frontend (static)

### Layout

```text
thelab/model_service/static/
  index.html
  app.js
  styles.css
```

Mount with FastAPI `StaticFiles` and serve `index.html` at `GET /` (and/or mount static at `/static` with `/` returning the HTML). Pick one clear scheme and test it.

### Panels (single page)

| Panel | Behavior |
|---|---|
| **Status** | Call `GET /health`. Show logical status (`ok`). Optionally show approved model **count**. **Do not** show absolute runs-root path. |
| **Approved models** | Call `GET /models`. Table: `run_id`, model, target, test accuracy, test F1. Row select sets active `run_id`. |
| **Run / metrics** | On select: `GET /runs/{run_id}`. Show metrics summary + feature column list. |
| **Artifacts** | `GET /runs/{run_id}/artifacts` then fetch selected allowlisted artifact and render JSON pretty-printed or model card as `<pre>` text. |
| **Predict** | Build inputs from `feature_columns` (number inputs). `POST /predict` with `{ run_id, features: [ { ... } ] }`. Show predictions or error. |

### UI constraints

- Vanilla JS `fetch` only; no bundler.
- Stable DOM hooks for tests, e.g. `id="panel-status"`, `id="panel-models"`, `id="panel-metrics"`, `id="panel-artifacts"`, `id="panel-predict"` (names can vary but must be asserted in tests).
- Readable minimal CSS; no design-system package.
- Works against same origin as the service (no CORS science project).

---

## Safety requirements

1. **Read-only UI layer** — no new write/mutate endpoints.
2. **Path safety** — all run access through `safe_run_dir`; artifact names basename + allowlist only.
3. **No absolute path leakage** in HTML or JSON API responses.
4. **Approved + completed** for `/models`, `/predict`, and run summary used for prediction.
5. **Local-first** — document that the service is for localhost use; keep default bind `127.0.0.1`.
6. **No shell, no MCP subprocess from the UI, no LLM.**

---

## File map (expected touch set)

```text
thelab/model_service/
  app.py                 # add read-only run/artifact routes; mount static; GET /
  cli.py                 # only if docstring/help needs UI mention
  static/
    index.html
    app.js
    styles.css

tests/
  test_model_service.py      # keep green; extend if natural
  test_model_service_ui.py   # new: /, static, artifact API safety, panel hooks

docs/
  SLICE5_PLAN.md             # this file
  SLICE5_CONTEXT.md          # coding agent writes after implementation
  ROADMAP.md                 # status update when done
```

Do not modify context MCP/CLI, training pipeline, or unrelated MCP servers unless a tiny shared helper extraction in `thelab/mcp/common.py` is clearly needed (prefer not).

---

## Implementation order

1. Add allowlist helpers + `GET /runs/{run_id}` (+ tests).
2. Add artifact list + get endpoints (+ path-traversal / allowlist tests).
3. Mount static files + `GET /` HTML.
4. Implement single-page panels in vanilla JS.
5. UI/API integration tests via TestClient.
6. Full `pytest` suite.
7. Write `docs/SLICE5_CONTEXT.md`; set ROADMAP Slice 5 → `done`.
8. Stop for audit.

---

## Tests

### Required

| Area | Assert |
|---|---|
| `GET /` | 200, HTML content-type or HTML body; contains panel hooks |
| Static assets | `app.js` / `styles.css` reachable (per mount scheme) |
| `GET /runs/{run_id}` | 200 for approved run; includes `feature_columns` and metrics |
| Rejected/unknown run | non-200 as specified |
| Artifact list | only allowlisted names; no `model.joblib`; no absolute paths |
| Artifact get | metrics/model_card happy path |
| Traversal | `../`, absolute-like names, nested `a/b` → rejected |
| Non-allowlisted name | rejected |
| Existing suite | `tests/test_model_service.py` still passes |
| Predict still approved-only | existing tests remain |

### Forbidden for Slice 5

- Playwright / Selenium / real browser automation.
- Network calls to non-local services.

### Verification commands

```bash
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q
```

Manual smoke:

```bash
PATH=.venv/bin:$PATH
# ensure at least one approved run exists under runs/ or THELAB_RUNS_ROOT
thelab-model-service --port 8000
# browser or curl:
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ | head
curl -s http://127.0.0.1:8000/models
```

---

## Acceptance checklist

- [ ] UI served from `thelab-model-service` at `GET /`
- [ ] Vanilla static assets only (no frontend build)
- [ ] Panels: status, models, metrics, artifacts, predict
- [ ] Read-only run summary + artifact list/get APIs
- [ ] Artifact allowlist enforced; no `model.joblib` over HTTP
- [ ] No absolute filesystem paths in API/UI payloads
- [ ] Path traversal tests pass
- [ ] No context/agent/LLM features
- [ ] Default bind remains `127.0.0.1`
- [ ] `PATH=.venv/bin:$PATH pytest tests/ -q` green
- [ ] `docs/SLICE5_CONTEXT.md` written
- [ ] `docs/ROADMAP.md` Slice 5 marked `done`

---

## Handoff back to audit

When the checklist is green:

1. Stop implementing.
2. Summarize changed files and test output.
3. User may `/log`.
4. Audit agent re-checks Slice 5 acceptance only.

---

## Non-goals reminder (from `docs/Agents.md`)

- Do not add arbitrary shell or LLM code execution.
- Do not modify files outside this slice.
- Do not silently change architecture or dependencies.
- Ask before destructive commands or broad refactors.
