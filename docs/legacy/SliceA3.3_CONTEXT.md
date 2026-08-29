# Slice A3.3 — Structured-output hardening for local models

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 hardening; `stage_2.md`  
**Scope:** Make the worker produce valid JSON proposals from small local LLMs without falling back to deterministic output.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/json_repair.py` | New module: conservative JSON repair for markdown fences, trailing commas, single quotes, and unquoted keys. |
| `thelab/agents/worker.py` | `WorkerAgent.propose` now calls the provider directly with a focused JSON prompt; `_extract_json_block` uses `safe_json_loads`; improved prompt with explicit schema and constraints. |
| `tests/test_json_repair.py` | Unit tests for all repair heuristics. |
| `tests/test_agents_worker.py` | Updated disallowed-tool test to account for the worker's direct provider call before harness delegation. |
| `docs/ROADMAP.md` | A3.3 marked `done`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_json_repair.py tests/test_agents_worker.py -q
```

Results:

- `ruff check thelab tests scripts` — passed
- `mypy thelab` — passed
- `pytest tests/test_json_repair.py tests/test_agents_worker.py -q` — **21 passed**
- `pytest tests/ -q` — **345 passed**
- `scripts/evaluate_thesis.py` — **Overall: PASS**

### Manual integration

With Ollama running `llama3.2:3b`:

```bash
.venv/bin/python -m thelab.agents.cli --mode worker --provider ollama \
  --dataset data/fixtures/iris.csv --target species \
  --proposals-dir proposals --json
```

Result: the proposal is generated from the LLM output (model-selected `logistic_regression`, seed `42`, LLM-written rationale) rather than the deterministic fallback.

---

## Design decisions

- **Direct provider call for proposals:** the worker no longer runs the tool-using harness for the initial proposal. The prompt already contains the deterministic EDA summary, so small models are not distracted by tool schemas and are more likely to emit valid JSON.
- **Tool-call fallback preserved:** if the provider returns tool calls instead of JSON, the worker delegates to the harness so the conversation can continue. This keeps compatibility with bigger models that may want to query tools.
- **Conservative JSON repair:** `json_repair.py` fixes common small-model mistakes but returns `None` rather than hallucinate. The existing deterministic fallback remains the safety net.
- **Prompt constraints:** the prompt now includes a concrete JSON example, explicit "no markdown fences" instruction, and dataset/target values pre-filled.

---

## Known limitations

- Rationales from small models can be generic or repeat prompt boilerplate. Quality will improve with better examples and potentially a second-chance "revise rationale" prompt.
- The worker still validates model names against the registry; a model that proposes an unknown model will be corrected to the deterministic grid.
- JSON repair is heuristic; adversarial or deeply nested malformed JSON may still fail.

---

## Next suggested slice

**A3.4 — OpenRouter provider adapter** (already implemented in this session) lets you validate the hardened worker against stronger remote models before returning to local-model quality tuning.
