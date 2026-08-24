# Slice A1 — OpenAI-compatible LLM provider adapter

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §2 Stage 1 — A1  
**Scope:** One real LLM provider adapter implementing the L1 `LLMProvider` protocol, working against OpenAI-compatible endpoints (local Ollama or cloud).

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/providers/__init__.py` | Exports `OpenAICompatProvider`. |
| `thelab/agents/providers/openai_compat.py` | New adapter: env-based config, retry logic, request/response mapping, `LLMProviderError` codes, debug logging without prompt content. |
| `thelab/agents/provider.py` | `ToolCallRequest` gains optional `id` so assistant tool-call IDs round-trip through tool messages. |
| `thelab/agents/harness.py` | Uses `request.id` as `tool_call_id` when provider supplies one. |
| `thelab/agents/cli.py` | Provider factory now maps `--provider mock|openai_compat`; unknown names fail with the supported list. |
| `tests/test_agents_provider.py` | 18 unit tests covering config, request/response mapping, malformed responses, retry behavior, and a golden tool-call round trip. |
| `docs/ROADMAP.md` | A1 marked `done` in the slice map. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
```

Results:

- `ruff check` — passed
- `mypy thelab` — passed
- `pytest tests/ -q` — **271 passed, 520 warnings** (dependency deprecation notices)

### Provider-specific tests

```bash
.venv/bin/python -m pytest tests/test_agents_provider.py -q
```

Result: **18 passed**.

### Documented usage (config fast-fail)

```bash
THELAB_LLM_BASE_URL= THELAB_LLM_API_KEY= \
  .venv/bin/python -m thelab.agents.cli "goal" --provider openai_compat --runs-root runs --json
```

Result: exit code 1, clear `LLMProviderError` with code `config`.

Documented local Ollama usage:

```bash
export THELAB_LLM_BASE_URL=http://localhost:11434/v1
export THELAB_LLM_API_KEY=ollama
.venv/bin/python -m thelab.agents.cli "What models are approved?" \
  --provider openai_compat --runs-root runs
```

This requires a running Ollama instance with the configured model; it is documented but not required in CI.

---

## Design notes

- **Configuration**: `THELAB_LLM_BASE_URL` and `THELAB_LLM_API_KEY` are required (no default endpoint); `THELAB_LLM_MODEL` defaults to `qwen3:4b`; `THELAB_LLM_TIMEOUT_SECONDS` defaults to `120`. Constructor arguments override environment.
- **Transport**: production uses `httpx`; tests inject a `Transport` callable returning `_HTTPResponse`, so no network is needed in CI.
- **Retry policy**: max 3 retries, exponential backoff `0.5s × 2^n`. Retries only on 429, 5xx, and network errors. 4xx validation responses are never retried.
- **Request mapping**: `AgentMessage` → OpenAI `system|user|assistant|tool` messages with `tool_call_id`; `ToolSpec` → `{"type": "function", "function": {name, description, parameters}}`.
- **Response mapping**: `finish_reason == "tool_calls"` returns `AgentTurn(tool_calls=...)`; `"stop"` returns `AgentTurn(text=...)`. Malformed/ambiguous turns raise `LLMProviderError(code="protocol")`.
- **Error taxonomy**: `config`, `network`, `protocol`, `rate_limited`, `server`.
- **Privacy**: adapter logs only message count, payload byte size, status code, and duration. No prompt content. Redaction remains the harness's responsibility.
- **No new dependencies**: uses existing `httpx` already present in `requirements.lock`.

---

## Limitations

- Streaming responses are not implemented.
- Only `function` tool calls are supported.
- The adapter does not validate tool schemas beyond passing them through.
- Live cloud/Ollama checks are documented but not part of CI.
- Conversation persistence is still out of scope (L2/A3).

---

## Smallest next step

**S1 — Deterministic EDA skill pack** (Stage 2): implement pure, deterministic DataFrame analysis functions in `thelab/eda/` and expose them as typed tools the agent can cite, grounding future agent reasoning in local data evidence.
