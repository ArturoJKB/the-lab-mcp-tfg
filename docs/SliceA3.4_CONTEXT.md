# Slice A3.4 — OpenRouter provider adapter

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 hardening; `stage_2.md`  
**Scope:** Add a first-class OpenRouter provider so the agent harness/worker/diagnosis can use remote models through a single API key.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/providers/openrouter.py` | New module: `OpenRouterProvider`, a thin wrapper over `OpenAICompatProvider` with OpenRouter defaults and recommended headers (`HTTP-Referer`, `X-Title`). |
| `thelab/agents/providers/openai_compat.py` | Added `extra_headers` support so providers can inject vendor-specific headers. |
| `thelab/agents/providers/__init__.py` | Exports `OpenRouterProvider`. |
| `thelab/agents/__init__.py` | Exports `OpenRouterProvider`. |
| `thelab/agents/cli.py` | `--provider openrouter` is now accepted by `thelab-agent`. |
| `tests/test_agents_openrouter.py` | Unit tests for config, default endpoint, header injection, and response parsing. |
| `docs/ROADMAP.md` | A3.4 marked `done`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_agents_openrouter.py -q
```

Results:

- `ruff check thelab tests scripts` — passed
- `mypy thelab` — passed
- `pytest tests/test_agents_openrouter.py -q` — **5 passed**
- `pytest tests/ -q` — **345 passed**
- `scripts/evaluate_thesis.py` — **Overall: PASS**

### Configuration

```bash
export THELAB_LLM_API_KEY="sk-or-v1-..."
# Optional:
export THELAB_LLM_MODEL="openai/gpt-4o-mini"
export OPENROUTER_SITE_URL="https://your-site.example"
export OPENROUTER_SITE_NAME="Your Lab"
```

### Example command

```bash
.venv/bin/python -m thelab.agents.cli --mode worker --provider openrouter \
  --dataset data/fixtures/iris.csv --target species \
  --proposals-dir proposals --json
```

---

## Design decisions

- **Thin wrapper over OpenAI-compatible adapter:** OpenRouter's API is OpenAI-compatible, so we reuse the existing retry, tool-call parsing, and response handling logic.
- **Vendor headers:** OpenRouter uses `HTTP-Referer` and `X-Title` for attribution and rate-limit buckets. The adapter sends them only when configured.
- **No API key default:** OpenRouter requires a real key, so the provider fails fast if `THELAB_LLM_API_KEY` is missing.

---

## Known limitations

- OpenRouter model names follow the `provider/model` format (e.g., `openai/gpt-4o-mini`). The worker's model-grid validator only accepts registered The Lab model names (`logistic_regression`, `random_forest`, etc.), so the LLM must still propose from that allowlist.
- Costs and rate limits depend on the chosen model; this adapter does not track token usage.

---

## Next suggested slice

**B1 — Cross-domain benchmark suite** is now realistic: you can compare deterministic, Ollama-local, and OpenRouter-remote proposals on the same datasets and lock the results into a regression suite.
