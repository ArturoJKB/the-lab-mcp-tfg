# Slice L1 — Agent harness + LLM provider protocol

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §2 Stage 1 — L1  
**Scope:** A local harness connecting a pluggable LLM provider to the four existing read-only MCP servers, with grounding check and approval gate.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/__init__.py` | Public exports for the agent package. |
| `thelab/agents/provider.py` | `LLMProvider` Protocol + Pydantic contracts: `AgentMessage`, `ToolSpec`, `ToolCallRequest`, `AgentTurn`, `LLMProviderError`. |
| `thelab/agents/harness.py` | `AgentHarness`: MCP tool discovery, pinned allowlist, bounded execution loop, grounding checker, approval request persistence. |
| `thelab/agents/mock.py` | `MockProvider` (scripted deterministic turns) and `EchoProvider` for offline tests/demo; `load_script()` helper. |
| `thelab/agents/cli.py` | Entry point `thelab-agent` spawning the four stdio MCP servers and running the harness. |
| `pyproject.toml` | Added `thelab-agent` console script. |
| `examples/agent_mock_demo.py` | End-to-end offline demo: train a run → scripted mock-provider loop → grounded answer. |
| `tests/test_agents_contracts.py` | Unit tests for provider contracts and mock provider. |
| `tests/test_agents_harness.py` | Integration tests against real stdio MCP servers: discovery, tool loop, grounding, approval gate, step bound. |
| `docs/ROADMAP.md` | Added L1 and A1 rows to the slice map. |

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
- `pytest tests/ -q` — **253 passed, 520 warnings** (deprecation notices from dependencies)

### Documented example commands

Offline demo script (no network):

```bash
.venv/bin/python examples/agent_mock_demo.py
```

Result: JSON output with `status: success`, a grounded answer citing the trained run's `test_accuracy`, and a session id.

CLI example (train a run, then run the agent with a mock script):

```bash
.venv/bin/python -m thelab.cli run model \
  --dataset data/fixtures/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs

RUN_ID=$(.venv/bin/python -m thelab.cli run model \
  --dataset data/fixtures/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs | head -1 | cut -d' ' -f3)

.venv/bin/python -c "
import json
run_id = '$RUN_ID'
metrics = json.load(open(f'runs/{run_id}/metrics.json'))
script = [
    {'tool_calls': [{'tool': 'list_models', 'arguments': {}}]},
    {'tool_calls': [{'tool': 'get_model_metrics', 'arguments': {'run_id': run_id}}]},
    f'Run {run_id} has test_accuracy {metrics[\"test_accuracy\"]}.'
]
json.dump(script, open('/tmp/mock_script.json', 'w'), indent=2)
"

.venv/bin/python -m thelab.agents.cli \
  'summarize the latest model' --provider mock \
  --mock-script /tmp/mock_script.json --runs-root runs --json
```

Approval gate example (disallowed tool → exit code 2, persisted request):

```bash
.venv/bin/python -m thelab.agents.cli 'do something dangerous' \
  --provider mock --mock-script /dev/stdin --runs-root runs --json <<'EOF'
[
  {"tool_calls": [{"tool": "delete_run", "arguments": {"run_id": "run-123"}}]}
]
EOF
# exit code 2
```

---

## Design notes

- **Provider protocol**: `complete(messages, tools) -> AgentTurn`. `AgentTurn` is validated to contain exactly one of `text` or `tool_calls`.
- **Tool allowlist**: discovered dynamically from the four read-only MCP servers (`data_catalog`, `model_registry`, `workspace`, `context`). Any provider request for a tool not in the union is rejected before execution.
- **Grounding**: final text answers are scanned for `run-YYYYMMDD-HHMMSS-xxxxxxxx` IDs and numeric claims against known metric keys. Every cited run_id must be readable via `workspace_mcp.get_run_manifest`; every metric claim must match the run's `metrics.json` within `1e-3`.
- **Approval requests**: persisted under `.thelab/approvals/<session_id>_<timestamp>.json` with `tool`, `arguments`, `session_id`, `timestamp`.
- **Bounded execution**: default `max_steps=8`; exceeding it returns a structured refusal.
- **No new runtime dependencies**: uses the existing `mcp` package for stdio transport.

---

## Limitations

- Only the mock provider is wired in L1; real adapters are A1.
- Metric claim detection is regex-based and limited to the known metric keys in `_METRIC_KEYS`.
- Conversation persistence is out of scope (L2/A3).
- The harness executes tool calls serially within a single provider turn.
- No streaming UI or rich agent panels (U1).

---

## Smallest next step

**A1 — Real LLM adapter**: implement `thelab/agents/providers/openai_compat.py` with `OpenAICompatProvider(LLMProvider)`, env-based configuration, retry logic, request/response mapping, and `LLMProviderError` codes. Wire the provider factory in `thelab-agent --provider openai_compat`.
