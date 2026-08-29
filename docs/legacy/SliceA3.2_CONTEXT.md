# Slice A3.2 — Ollama provider adapter

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 hardening; `stage_2.md`  
**Scope:** Connect the agent harness, worker, and diagnosis agents to a local Ollama server via Ollama's native `/api/chat` endpoint.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/providers/ollama.py` | New module: `OllamaProvider` implementing the `LLMProvider` protocol over Ollama `/api/chat` with JSON mode, tool support, and retries. |
| `thelab/agents/providers/__init__.py` | Exports `OllamaProvider`. |
| `thelab/agents/__init__.py` | Exports `OllamaProvider`. |
| `thelab/agents/cli.py` | `--provider ollama` is now accepted by `thelab-agent`. |
| `tests/test_agents_ollama.py` | Unit tests for config, request body mapping, text/tool turns, argument parsing, errors, and retries. |
| `docs/ROADMAP.md` | A3.2 marked `done`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_agents_ollama.py -q
.venv/bin/python scripts/evaluate_thesis.py
```

Results:

- `ruff check thelab tests scripts` — passed
- `mypy thelab` — passed
- `pytest tests/test_agents_ollama.py -q` — **12 passed**
- `evaluate_thesis.py` — **Overall: PASS**

### Manual integration

With a local Ollama server running `llama3.2:3b`:

```bash
.venv/bin/python -m thelab.agents.cli --mode worker --provider ollama \
  --dataset data/fixtures/iris.csv --target species \
  --proposals-dir proposals --json
```

Result: the worker produces a valid `ExperimentProposal`. When Ollama's JSON output does not match the required schema, the worker falls back to its deterministic EDA + prior-run proposal.

---

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model tag |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Request timeout |

No API key is required.

---

## Design decisions

- **Native endpoint:** uses `/api/chat` rather than Ollama's OpenAI-compatible `/v1` path. This gives direct access to Ollama-specific JSON mode and avoids requiring an API key.
- **JSON mode by default:** every request sets `format: "json"` to improve structured-output reliability for the worker's proposal extraction.
- **Tool support:** Ollama tool calls are parsed into the same `ToolCallRequest` shape used by the harness. Small models may not reliably call tools; the harness and worker already have fallbacks for that case.
- **Best-effort integration:** the worker's existing fallback (deterministic proposal from direct EDA + prior runs) means the integration is usable even when `llama3.2:3b` produces malformed JSON.

---

## Known limitations

- Small local models (e.g., `llama3.2:3b`) often return JSON that does not match the exact proposal schema. The worker falls back to deterministic proposals, so the integration is functional but not yet "agent-boosted" in a meaningful way.
- The provider does not yet expose Ollama's structured `format` JSON schema field (newer Ollama versions). Adding a per-call schema could improve fidelity.
- Streaming is disabled (`stream: false`). Long-running generations block until completion.

---

## Next suggested slice

**A3.3 — Prompt engineering / structured-output hardening for local models** — craft smaller, schema-constrained prompts and/or add a JSON-repair pass so local models produce valid worker proposals more often. This is the prerequisite for comparing deterministic vs. agent-boosted runs.

Alternatively, if you want to validate the full agent loop with a stronger model first, connect **OpenRouter** (`OpenAICompatProvider` with `THELAB_LLM_BASE_URL=https://openrouter.ai/api/v1` and an API key) before investing in local-model prompt engineering.
