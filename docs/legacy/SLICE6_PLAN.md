# Slice 6 Plan — FINAL Implementation Guide (P0 Closeout)

> **Status:** ready for implementation — **binding**  
> **Last updated:** 2026-08-10  
> **Audience:** coding agent (Kimi or equivalent)  
> **Authority:** This file supersedes informal chat proposals. Implement **only** what is listed here.

---

## 0. How this plan was decided

Three inputs were merged:

| Source | Role |
|---|---|
| **Kimi coding agent** | Initial Slice 6 questions + proposed scope (panels, eval, lockfile gate) |
| **Gemini 2.5 Pro (`/audit`)** | Audit of that proposal; market-research N/A; decision recommendations |
| **Project audit agent (this repo’s `docs/AUDIT_AGENT.md` practice)** | PRD/ROADMAP alignment; anti-scope-creep; compose existing MCP/UI |

### Decision matrix (final lock)

| Topic | Kimi asked | Gemini audit | Project audit | **FINAL** |
|---|---|---|---|---|
| Market / “deep web” trends | (n/a) | Not applicable; trends that violate non-goals are BLOCKERs | Agree | **No market-driven features** |
| Agent surface | a MCP / b UI / c both | **(c) UI + new/extended MCP** | **(b) UI + thin HTTP; no new `agent_mcp`** | **UI panels + thin read-only HTTP on `thelab-model-service`. No new MCP server.** Agent interoperability is already Slices 2–4; RQ2 **re-verifies existing** MCP. |
| Research/Copilot LLM | yes/no + provider? | **No LLM** | **No LLM** | **No LLM** — local evidence browser only |
| Dependency lock | include? | **Must include** | **Task 0 must** | **Task 0 — required** |
| Eval format | script / md / both | **Both** | **Both** | **Both** |
| Phasing | 6.0/6.1/6.2? | Endorse sub-slices | Single slice, ordered tasks | **One Slice 6**, tasks **T0→T5** (logical phases, not separate roadmap rows) |

### Why not a new `agent_mcp` (disagreement resolved)

Gemini’s “both” is correct that **humans need panels** and **agents need APIs**. In this repo those agent APIs **already exist**:

- `workspace_mcp` — runs, manifests, artifacts  
- `context_mcp` — search/get/status  
- `model_registry_mcp` — list/card/metrics/**predict**  
- `data_catalog_mcp` — datasets/profiles  

Adding `agent_mcp` in P0 would **duplicate** surfaces, expand test/maintenance load, and is **not required** to answer RQ2 (independent client already uses `model_registry` + friends).  

**P0 closeout rule:** human panels compose evidence over **HTTP** (same host as Slice 5 UI); programmatic agents keep using **existing stdio MCP**. The thesis eval script must prove MCP paths **without** a new server.

If a future P1 wants a single façade MCP, that is out of Slice 6.

---

## 1. Role split

| Role | Does | Does not |
|---|---|---|
| Coding agent | Implement T0–T5, tests, fill eval results, `SLICE6_CONTEXT.md` | LLM providers, RAG, write agents, new MCP server, cloud |
| Audit agent | `/audit 6` after green checklist | Implement in the coding pass |

After green checklist + recorded eval results → **stop**. P0 implementation complete pending final audit.

---

## 2. Goal (P0 wrap-up)

Close the first part of the project by delivering:

1. **Read-only Coding/Logger panel** (human) over runs/artifacts/metrics.  
2. **Read-only Research/Copilot panel** (human) over **local** context search — no generative model.  
3. **Thesis evaluation protocol** mapped to PRD RQ1–RQ3 with **automated** pass/fail + **markdown** record.  
4. **Reproducibility gate:** supported Python + committed lockfile (honest RQ1).

This is **composition + demonstration + evaluation**, not a new agent runtime.

---

## 3. PRD binding

### Research questions → checks

| RQ | Check | Pass bar |
|---|---|---|
| **RQ1** Reproducible run | Two `thelab run model` on same fixture/seed/model; compare key metrics; seed/config/deps recorded | Both succeed with comparable metrics within documented tolerance; artifacts contain seed + config |
| **RQ2** MCP interoperability | Independent stdio client: `list_models` + `predict` (and card/metrics as available) on **existing** `model_registry_mcp` | `ok` envelopes; predictions returned; client does not import `thelab.run` |
| **RQ3** Context retrieval | Index small JSONL; search via `ContextReader` and/or `context_mcp` | ≥1 useful hit; stable fields; search does not write DB bytes |

### Acceptance criteria

| AC | Slice 6 action |
|---|---|
| AC-01..05 | Re-verify via evaluator (already built in earlier slices) |
| AC-06 | Coding panel/API **read-only**; banner: no autonomous writes; approval required for modifications |
| AC-07 | Slice 5 + new panels show status/metrics/artifacts/context evidence |

### Non-goals (violations = BLOCKER)

No trading, shell execution, autonomous code execution, cloud hosting, RAG/vector DB, multi-user auth, **multiple/new LLM provider integrations**, new write tools, React/SPA build toolchain, Playwright-as-required-gate.

---

## 4. Already done (compose only)

| Piece | Location |
|---|---|
| Training + artifacts | `thelab run model`, `runs/<run_id>/` |
| MCP suite + demo client | `thelab/mcp/*` |
| Context store/reader/MCP | `thelab/context/*`, `context_mcp` |
| Human dashboard | `thelab/model_service` + `static/` (Slice 5) |
| Path helpers | `thelab/mcp/common.py` |

---

## 5. Locked product decisions (do not re-ask)

1. **Surface:** Panels in **existing** `thelab-model-service` UI + thin **read-only HTTP** under e.g. `/agent/...`. **No** `agent_mcp`, **no** second UI server.  
2. **Copilot:** **No LLM** — structured local evidence browser only.  
3. **Lockfile:** **Required** in T0 (`uv.lock` preferred, else pinned requirements lock).  
4. **Eval:** `scripts/evaluate_thesis.py` (or `thelab evaluate thesis`) **and** `docs/THESIS_EVALUATION.md`.  
5. **Structure:** Single Slice 6, tasks T0→T5 (optional labels “phase A/B/C” in notes only).

---

## 6. Tasks (implement in order)

### T0 — Reproducibility gate (lock + Python)

**Must complete before claiming RQ1.**

1. Set intentional `requires-python` in `pyproject.toml` (e.g. `>=3.11,<3.15` or project-standard 3.12-only — **document choice**).  
2. Commit lockfile: prefer `uv.lock`; else hashed/pinned `requirements.lock`.  
3. Update `README.md` install instructions to match lock (remove false “pinned” claims if still wrong).  
4. Confirm: fresh install from lock + `PATH=.venv/bin:$PATH pytest tests/ -q` green.

**Done when:** lock is in repo; README tells truth; full suite passes on supported Python.

---

### T1 — Read-only HTTP APIs for panels

Extend `thelab/model_service/app.py` only (same process, default bind `127.0.0.1`).

| Endpoint | Behavior |
|---|---|
| `GET /agent/coding/overview` | Logical counts / latest run ids — **no absolute paths** |
| `GET /agent/coding/runs` | Safe run list + status from manifests (`discover_run_ids`) |
| `GET /agent/coding/runs/{run_id}` | Summary: status, metrics, allowlisted artifact **names** |
| `GET /agent/research/context/status` | `ContextReader.status()` (no `db_path`) |
| `GET /agent/research/context/search` | `query`, `limit` (bounded); `ContextReader.search`; agent-safe privacy default |
| `GET /agent/research/context/entries/{event_id}` | `ContextReader.get`; missing/filtered → not found |

**Safety (hard):**

- Env only: `THELAB_RUNS_ROOT`, `THELAB_CONTEXT_DB` — **no path query params**.  
- GET-only (prefer).  
- `safe_run_dir` for all run_ids.  
- Context: **reader only** (no indexer, no repository writes).  
- No absolute filesystem paths in JSON.  
- Reuse Slice 5 artifact allowlist spirit for names exposed to coding panel.

---

### T2 — Coding/Logger panel (UI)

Vanilla HTML/JS in `thelab/model_service/static/` (tab or section on same page — **no** React/Vue).

- Stable hooks: e.g. `id="panel-coding"`.  
- Show run list, selected run metrics/manifest summary, artifact names + view via existing Slice 5 artifact APIs or T1 coding endpoints.  
- **Banner (required):** “Read-only — no autonomous writes. Approval required before any modification or destructive action.”  
- **No** train/delete/shell/edit actions.

---

### T3 — Research/Copilot panel (UI) — local evidence only

- Stable hooks: e.g. `id="panel-research"`.  
- Context status + search + entry detail via T1 research endpoints.  
- Note in UI: grounded in **local** runs/context only; no external RAG; no generative answers.  
- Optional static pointers to doc titles (`PRD`, `ROADMAP`) — text only is enough.  
- **No** LLM calls, API keys, chat widgets that hit providers.

---

### T4 — Thesis evaluation protocol + automation

#### T4a. `docs/THESIS_EVALUATION.md`

Contents:

1. Hypothesis (from PRD).  
2. RQ1–RQ3: method, pass bar, commands.  
3. Environment: Python, lockfile, install.  
4. Manual demo script (defense-friendly ordered steps).  
5. **Results** section — filled after evaluator run (paste or summarize output).  
6. Limitations (stdio MCP only, no LLM copilot, redaction best-effort, etc.).

#### T4b. Evaluator

`scripts/evaluate_thesis.py` and/or `thelab evaluate thesis`:

- Exit `0` iff required checks pass.  
- Print clear per-RQ PASS/FAIL (+ optional JSON summary).  
- Use temp dirs for runs/DB when possible.  
- **RQ1:** double train on small fixture; compare metrics; assert seed/config present.  
- **RQ2:** MCP stdio to **existing** `model_registry_mcp` (pattern from `tests/test_mcp.py` / demo client).  
- **RQ3:** temp JSONL → index → search; assert hit; optionally hash DB around search-only phase.

**Tests:** `tests/test_thesis_eval.py` and `tests/test_agent_panels.py` (API safety, UI hooks, privacy, no path leak).

---

### T5 — Handoff docs

1. Write `docs/SLICE6_CONTEXT.md` (file map, how to run UI + eval).  
2. Set `docs/ROADMAP.md` Slice 6 → `done`; active pointer → P0 complete / audit.  
3. Ensure `THESIS_EVALUATION.md` results filled.  
4. Do not rewrite PRD.

---

## 7. Out of scope (do not implement)

- New `agent_mcp` or any new MCP server process.  
- LLM SDKs, local GPU stacks, embeddings, RAG.  
- Write/index/delete HTTP or MCP tools.  
- Playwright as a required gate.  
- Separate `thelab ui` server.  
- Frontend frameworks / npm build.  
- Cloud, auth, multi-user.  
- Sub-slice directories `6.0/6.1/6.2` as separate roadmap items.

---

## 8. File map (expected touch set)

```text
pyproject.toml
uv.lock | requirements.lock
README.md

thelab/model_service/app.py
thelab/model_service/static/index.html
thelab/model_service/static/app.js
thelab/model_service/static/styles.css

scripts/evaluate_thesis.py          # and/or CLI hook in thelab/
tests/test_agent_panels.py
tests/test_thesis_eval.py

docs/SLICE6_PLAN.md                 # this file (binding)
docs/SLICE6_CONTEXT.md              # after impl
docs/THESIS_EVALUATION.md
docs/ROADMAP.md
```

Prefer **not** changing context/MCP core except imports/reuse. No drive-by refactors.

---

## 9. Implementation order

```text
T0 lock/python/README
 → T1 agent HTTP APIs + tests
 → T2 coding panel
 → T3 research panel
 → T4 THESIS_EVALUATION.md + evaluator + tests
 → T5 CONTEXT + ROADMAP + results
 → full pytest + evaluator exit 0
 → STOP for /audit 6
```

---

## 10. Verification

```bash
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q

PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py
# or: thelab evaluate thesis

thelab-model-service --port 8000
# http://127.0.0.1:8000/ — Models + Coding + Research panels
```

---

## 11. Acceptance checklist (DoD)

- [ ] Lockfile committed; README install matches; `requires-python` intentional  
- [ ] Coding panel live; read-only banner present  
- [ ] Research panel searches local context; **no LLM**  
- [ ] Agent HTTP routes read-only, path-safe, no absolute paths  
- [ ] **No** new MCP server  
- [ ] RQ1–RQ3 automated checks pass; results recorded in `THESIS_EVALUATION.md`  
- [ ] Full pytest green  
- [ ] `SLICE6_CONTEXT.md` written; ROADMAP Slice 6 `done`  
- [ ] Coding agent stops; user runs `/audit 6` then `/log`  

---

## 12. Handoff

**Coding agent:** implement this file only.  
**User:** after green → `/audit 6` → `/log`.  
**Audit agent:** GO/NO-GO against this checklist; no scope expansion.

---

## 13. Paste-ready prompt for Kimi

> Read and implement `docs/SLICE6_PLAN.md` exactly (FINAL binding plan).  
> Do not add `agent_mcp`, LLMs, RAG, or frontend frameworks.  
> Order: T0 → T5. Run full pytest and the thesis evaluator.  
> Write `docs/SLICE6_CONTEXT.md`, fill `docs/THESIS_EVALUATION.md` results, mark Slice 6 done in `docs/ROADMAP.md`.  
> Stop for audit. Do not start P1.
