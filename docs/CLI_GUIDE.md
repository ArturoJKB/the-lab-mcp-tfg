# The Lab — CLI Guide

All command-line entry points. For the UI and HTTP API see
[`docs/USER_GUIDE.md`](USER_GUIDE.md); for Python usage see
[`docs/PYTHON_API.md`](PYTHON_API.md). The `thelab` CLI resolves its workspace
from the current directory by design — for running from other folders and
disposable ("hermetic") labs see [`docs/WORKSPACES.md`](WORKSPACES.md).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e .
```

Installed commands:

| Command | Purpose |
|---|---|
| `thelab` | main CLI (run, inspect, predict, compare, context, proposals) |
| `thelab-agent` | agent CLI (mock / worker / researcher / diagnosis modes) |
| `thelab-model-service` | local HTTP service + dashboard |
| `thelab-mcp-demo` | MCP demo client |
| `thelab-{data-catalog,model-registry,workspace,context,context-write,eda,agent}-mcp` | MCP servers (stdio) |

---

## `thelab run model`

Train a deterministic model from a CSV.

```bash
thelab run model \
  --dataset examples/iris.csv \
  --target species \
  --model logistic_regression \
  --seed 42 \
  --output runs
```

### Flags

| Flag | Required | Description |
|---|---|---|
| `--dataset` | yes | Relative path to the CSV file |
| `--target` | yes | Name of the target column |
| `--model` | yes | Model name (see below) |
| `--seed` | yes | Random seed for reproducibility |
| `--output` | yes | Relative directory for run outputs |
| `--task-type` | no | `auto` (default) / `classification` / `regression` |
| `--dry-run` | no | Train in memory, persist nothing |
| `--try-all` | no | Compare every registered model (dry run by default) |

### Supported models

Classification: `logistic_regression`, `random_forest`, `svc` (max 50,000
training rows), `sgd_classifier`, `hist_gradient_boosting` — each with a
`_probability` variant.

Regression: `linear_regression`, `ridge`, `random_forest_regressor`,
`hist_gradient_boosting_regressor`.

With `--task-type auto` the task is inferred from the target (≤ 20 distinct
values → classification). Model/task mismatches and row-count limits are
**rejected with a reason** — a rejected run is a valid, traceable outcome.

### Run outputs

Each run creates `runs/<run_id>/` with `manifest.json`, `inputs.json`,
`data_profile.json`, `dataset_contract.json`, `training_config.json`,
`metrics.json`, `validation_report.json`, `model.joblib`, `model_card.md`,
`events.jsonl`, `task_spec.json`. Path rules: `--dataset`/`--output` must be
relative, no `..`, resolved inside the workspace root.

---

## `thelab run batch`

```bash
thelab run batch \
  --config examples/iris-batch.json \
  --output runs \
  --report batch_report.md
```

Batch config: a JSON list of `{dataset, target, model, seed, task_type?,
hyperparameters?}` objects. Outputs `batch_summary.json`, an optional
Markdown report, and one run directory per entry. The runner continues past
individual failures.

---

## `thelab inspect` / `predict` / `compare`

```bash
# Quick dataset profile, no training
thelab inspect --dataset examples/iris.csv [--target species]

# One-off prediction from an approved run
thelab predict --run-id <run_id> --features '5.1,3.5,1.4,0.2'

# Metrics table across completed runs
thelab compare [--output compare.md]
```

---

## `thelab context`

Index and search local agent-session logs (SQLite + FTS5, redacted,
read-only retrieval).

```bash
thelab context index --source .thelab/local-logs/agent-events.jsonl
thelab context search "reproducibility" [--run-id run-abc] [--limit 10]
thelab context show <event_id>
```

---

## `thelab proposals`

Manage worker-agent experiment proposals.

```bash
thelab proposals list
thelab proposals show <id>
thelab proposals approve <id>    # writes approval record (principal: "human")
thelab proposals reject <id> --reason "..."
thelab proposals approve <id> --run   # approve + execute as batch
```

---

## `thelab-agent`

Agent modes over the harness (provider via `--provider mock|openai_compat|ollama|openrouter`):

```bash
# Mock scripted agent answering a question over run artifacts
thelab-agent "Why did run X fail?" --provider mock --run-id <run_id>

# Worker: propose an experiment (EDA-grounded, deterministic fallback)
thelab-agent --mode worker --dataset examples/iris.csv --target species \
  --model-grid logistic_regression,random_forest --seeds 42,43

# Researcher / diagnosis
thelab-agent --mode researcher --question "..." --run-id <run_id>
thelab-agent --mode diagnosis --dataset ... --target ... --error "..." --model-grid ...
```

Provider env vars: `THELAB_LLM_BASE_URL`/`THELAB_LLM_API_KEY`/`THELAB_LLM_MODEL`
(openai_compat, openrouter), `OLLAMA_BASE_URL`/`OLLAMA_MODEL` (ollama).
Answers are grounded: claims must cite run IDs and match recorded metrics.

---

## `thelab-model-service`

```bash
thelab-model-service --host 127.0.0.1 --port 8000
```

Serves the dashboard at `/` plus the full HTTP API (datasets, EDA, cleaning,
experiments, jobs, predictions — see [`docs/USER_GUIDE.md`](USER_GUIDE.md)
for the endpoint tables). A warning is printed if `--host` is not loopback.

Predict example:

```bash
curl -X POST http://127.0.0.1:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"run_id": "run-20260829-...", "features": [{"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}]}'
```

---

## MCP smoke tests

```bash
thelab-mcp-demo model_registry --run-id <run_id>
thelab-mcp-demo data_catalog --run-id <run_id>
thelab-mcp-demo workspace --run-id <run_id>
thelab-mcp-demo context
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `dataset must be a relative path` | Absolute path passed | Run from the workspace root |
| `unsupported model` | Name not in registry | See supported models above |
| `model 'X' is limited to N training rows` | Scale guard | Use a scalable model or subsample |
| `cannot stratify` | Too few samples per class | More rows or fewer classes |
| `feature columns contain infinite values` | `Inf` in features | Clean the dataset first |
| `constant feature columns found` | A feature has one value | Fix the data upstream |
| Model service returns 404 | Run not completed/approved | Check `manifest.json` statuses |
| Job stuck `running` | Long stage | Watch the Pipeline panel; use Cancel |

## Tests

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
PATH=.venv/bin:$PATH .venv/bin/python scripts/evaluate_thesis.py
```
