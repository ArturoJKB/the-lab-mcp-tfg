# Slice 2 Context Handoff — Local MCP Servers and Model Serving

> Last updated: 2026-08-10
> Status: Slice 2 implemented and verified. Slice 3 implemented.

## What exists

Local stdio MCP servers that expose Slice 1/1.5 run artifacts to MCP clients, an independent demo client, and a local HTTP model inference service.

- `thelab-data-catalog-mcp` — read-only data catalog over persisted runs.
- `thelab-model-registry-mcp` — read-only registry of approved models, now with a `predict` tool.
- `thelab-workspace-mcp` — read-only workspace/artifact access.
- `thelab-mcp-demo` — headless demo client for all MCP servers.
- `thelab-model-service` — local FastAPI HTTP service for approved model inference.

## File map

```text
thelab/
  mcp/
    __init__.py
    common.py              # safe run discovery, manifest loading, path validation
    data_catalog_mcp.py    # data catalog MCP server
    model_registry_mcp.py  # model registry MCP server (includes predict)
    workspace_mcp.py       # workspace/artifact MCP server
    demo_client.py         # independent MCP demo client
  model_service/
    __init__.py
    app.py                 # FastAPI inference app
    cli.py                 # thelab-model-service entry point
  run/
    runner.py              # now generates and persists a TaskSpec per run

docs/
  SLICE2_CONTEXT.md        # this file
  ROADMAP.md               # master slice map

tests/
  test_mcp.py              # MCP integration tests
  test_workspace_mcp.py    # workspace MCP tests
  test_model_service.py    # HTTP service tests
  test_run.py              # includes TaskSpec tests
```

## Tools exposed

### Data catalog server

| Tool | Arguments | Description |
|------|-----------|-------------|
| `list_datasets` | — | All runs with dataset metadata, row/column counts, validation status. |
| `get_data_profile` | `run_id` | Full persisted `data_profile.json`. |
| `get_dataset_contract` | `run_id` | Full persisted `dataset_contract.json`. |

### Model registry server

| Tool | Arguments | Description |
|------|-----------|-------------|
| `list_models` | — | Approved, completed runs with key metrics and artifact paths. |
| `get_model_manifest` | `run_id` | Full persisted `manifest.json`. |
| `get_model_metrics` | `run_id` | Full persisted `metrics.json`. |
| `get_model_card` | `run_id` | Full persisted `model_card.md`. |
| `predict` | `run_id`, `features` | Load `model.joblib` and return predictions for feature rows. |

### Workspace server

| Tool | Arguments | Description |
|------|-----------|-------------|
| `list_runs` | — | Safe run IDs in the workspace. |
| `get_run_manifest` | `run_id` | Full persisted `manifest.json`. |
| `list_run_artifacts` | `run_id` | Artifact references from the manifest. |
| `get_artifact` | `run_id`, `artifact_type` | Load a JSON artifact by type. |
| `read_model_card` | `run_id` | Full persisted `model_card.md`. |

## Usage

Run a model first (Slice 1):

```bash
thelab run model \
  --dataset data/fixtures/iris.csv \
  --target species \
  --model logistic_regression \
  --seed 42 \
  --output runs/
```

Then query via MCP or HTTP:

```bash
# Data catalog
thelab-mcp-demo data_catalog --run-id <run_id>

# Model registry (auto-selects first approved run if --run-id omitted)
thelab-mcp-demo model_registry --run-id <run_id>

# Model registry with predict tool
thelab-mcp-demo model_registry --run-id <run_id> --predict

# Workspace artifacts
thelab-mcp-demo workspace --run-id <run_id>

# HTTP model service
thelab-model-service --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/models
curl -X POST http://127.0.0.1:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"run_id":"<run_id>","features":[{"sepal_length":5.1,"sepal_width":3.5,"petal_length":1.4,"petal_width":0.2}]}'
```

## Dependencies

Added `mcp>=1.6`, `fastapi>=0.110`, and `uvicorn>=0.29` to `pyproject.toml` project dependencies. `httpx>=0.27` is a dev dependency for FastAPI `TestClient`.

Install: `. .venv/bin/activate && pip install -e ".[dev]"`

## How to verify

```bash
# Full test suite (venv scripts must be on PATH for MCP subprocess tests)
PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/ -q

# Manual demo
thelab run model --dataset data/fixtures/iris.csv --target species --model logistic_regression --seed 42 --output runs/
RUN_ID=$(ls -t runs/ | head -n 1)
thelab-mcp-demo data_catalog --run-id "$RUN_ID"
thelab-mcp-demo model_registry --run-id "$RUN_ID" --predict
thelab-mcp-demo workspace --run-id "$RUN_ID"
thelab-model-service --port 8000 &
curl -s http://127.0.0.1:8000/predict -H "Content-Type: application/json" \
  -d "{\"run_id\":\"$RUN_ID\",\"features\":[[5.1,3.5,1.4,0.2]]}"

# Custom runs root propagation demo
export THELAB_RUNS_ROOT=/tmp/custom-runs
thelab run model --dataset data/fixtures/iris.csv --target species --model logistic_regression --seed 42 --output "$THELAB_RUNS_ROOT"
RUN_ID=$(ls -t "$THELAB_RUNS_ROOT" | head -n 1)
thelab-mcp-demo workspace --run-id "$RUN_ID"
```

Verification result: with `THELAB_RUNS_ROOT=/tmp/custom-runs`, `thelab-mcp-demo` successfully lists the temporary run and retrieves its artifacts; the child server does not fall back to the repository default `runs/` directory.

## Key design decisions

1. **Stdio transport.** Both servers use MCP's `stdio_server` so they work with any MCP client that launches subprocesses (Claude Desktop, Inspector, custom clients).

2. **Read-only.** Servers never write to the runs directory. They only discover and load artifacts already produced by `thelab run model`.

3. **Path safety.** `common.safe_run_dir` rejects traversal attempts, hidden names, and names containing path separators. `discover_run_ids` only enumerates safe directory names.

4. **Configurable runs root.** `get_runs_root()` defaults to `runs/` and respects `THELAB_RUNS_ROOT`. The demo client propagates its own `THELAB_RUNS_ROOT` value to each child MCP server process via `StdioServerParameters(env=dict(os.environ))`, so custom roots work end-to-end.

5. **Registry only surfaces approved models.** `list_models` filters by `final_status == completed` and `validation_status == approved`. Rejected or failed runs are excluded.

6. **Tool responses are JSON envelopes.** Every tool returns `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}` so clients can distinguish missing runs from successful empty results.

7. **Demo client is server-agnostic.** It uses the MCP SDK `stdio_client` and discovers available tools before calling them, so it validates against the actual server surface.

## Known limitations

- MCP servers are local-only (stdio transport). No SSE or HTTP transport for MCP yet.
- `predict` and the HTTP service support only the feature columns recorded in `data_profile.json`.
- No remote model serving, UI, or agent panels yet.
- Artifact updates or run creation are not supported through MCP or the HTTP service.

## Next suggested work

See `docs/ROADMAP.md` for the master slice map.

- **Slice 4: Context MCP** — read-only `context_mcp` server (`search_context`, `get_context_entry`, `get_context_status`) plus demo-client propagation of `THELAB_CONTEXT_DB`. No write tools.
- **Slice 5: Local UI** — minimal dashboard for status, artifacts, and metrics.
- **Slice 6: Agent panels and evaluation** — read-only Coding/Logger Agent panel, Research/Copilot panel, and thesis evaluation protocol.
