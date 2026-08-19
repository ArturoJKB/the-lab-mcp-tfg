# The Lab — CLI Guide

This guide covers the `thelab` CLI and the local `thelab-model-service` HTTP service.

---

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e .
```

This installs:

- `thelab` — main CLI
- `thelab-model-service` — local HTTP model service
- `thelab-data-catalog-mcp`, `thelab-model-registry-mcp`, `thelab-workspace-mcp`, `thelab-context-mcp` — MCP servers
- `thelab-mcp-demo` — MCP demo client

---

## `thelab run model`

Train a deterministic classification model from a CSV.

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
| `--model` | yes | Model name (see table below) |
| `--seed` | yes | Random seed for reproducibility |
| `--output` | yes | Relative directory for run outputs |

### Supported models

| Name | Scikit-learn estimator | Probability variant |
|---|---|---|
| `logistic_regression` | `LogisticRegression` | `logistic_regression_probability` |
| `random_forest` | `RandomForestClassifier` | `random_forest_probability` |
| `svc` | `SVC` | `svc_probability` |
| `sgd_classifier` | `SGDClassifier` | `sgd_classifier_probability` |

Use a `_probability` variant when you need `predict_proba` support. Example:

```bash
thelab run model --dataset examples/iris.csv --target species --model svc_probability --seed 42 --output runs
```

### Run outputs

Each run creates a directory `runs/<run_id>/` containing:

- `manifest.json` — run metadata and artifact refs
- `inputs.json` — the CLI inputs
- `data_profile.json` — dataset profile
- `dataset_contract.json` — dataset contract
- `training_config.json` — estimator and preprocessing config
- `metrics.json` — train/test accuracy and F1
- `validation_report.json` — validation checks
- `model.joblib` — serialized pipeline
- `model_card.md` — human-readable model card
- `events.jsonl` — lifecycle events
- `task_spec.json` — persisted task spec

### Path rules

- `--dataset` and `--output` must be relative paths.
- They cannot contain `..` segments.
- They must resolve inside the workspace root (current working directory).

---

## `thelab run batch`

Run many experiments from a JSON config.

```bash
thelab run batch \
  --config examples/iris-batch.json \
  --output runs \
  --report batch_report.md
```

### Batch config format

A JSON list of objects. Each object needs `dataset`, `target`, `model`, and `seed`:

```json
[
  {
    "dataset": "examples/iris.csv",
    "target": "species",
    "model": "logistic_regression",
    "seed": 42
  },
  {
    "dataset": "examples/wine.csv",
    "target": "class",
    "model": "random_forest",
    "seed": 42
  }
]
```

### Flags

| Flag | Required | Description |
|---|---|---|
| `--config` | yes | Path to batch JSON config |
| `--output` | yes | Directory for all run outputs and `batch_summary.json` |
| `--report` | no | Optional Markdown report path |

### Batch outputs

- `batch_summary.json` — status, metrics, and errors for every entry
- `batch_report.md` — human-readable results table
- One `run-<timestamp>-<id>/` directory per completed/rejected/failed entry

The runner continues past individual failures.

---

## `thelab context`

Index and search local agent-session logs.

### Index

```bash
thelab context index --source .thelab/local-logs/agent-events.jsonl
```

### Search

```bash
thelab context search "reproducibility"
thelab context search "reproducibility" --run-id run-abc --limit 10
```

### Show

```bash
thelab context show <event_id>
```

The context store redacts secrets before indexing and is read-only by default for agent-facing queries.

---

## `thelab-model-service`

Serve approved, completed models over local HTTP.

```bash
thelab-model-service --host 127.0.0.1 --port 8000
```

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Service health |
| `GET /models` | List approved models |
| `POST /predict` | Run inference on an approved model |
| `GET /runs/{run_id}` | Run summary |
| `GET /runs/{run_id}/artifacts` | List allowlisted artifacts |
| `GET /runs/{run_id}/artifacts/{artifact_name}` | Read an allowlisted artifact |
| `GET /agent/coding/overview` | Coding agent overview |
| `GET /agent/research/context/search` | Context search |
| `GET /` | Web UI |

### Predict example

```bash
curl -X POST http://127.0.0.1:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run-20260816-...",
    "features": [
      {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}
    ]
  }'
```

A warning is printed if `--host` is not a loopback address.

---

## Examples

### Train all base models on Iris

```bash
for m in logistic_regression random_forest svc sgd_classifier; do
  thelab run model --dataset examples/iris.csv --target species --model $m --seed 42 --output runs
done
```

### Train all probability variants

```bash
for m in logistic_regression_probability random_forest_probability svc_probability sgd_classifier_probability; do
  thelab run model --dataset examples/iris.csv --target species --model $m --seed 42 --output runs
done
```

### Compare models across datasets

```bash
thelab run batch --config examples/multi-dataset-batch.json --output runs --report multi_report.md
```

### Load and predict from a saved artifact

```python
import joblib

model = joblib.load("runs/run-<id>/model.joblib")
print(model.predict([[5.1, 3.5, 1.4, 0.2]]))
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `dataset must be a relative path` | Absolute path passed | Use a relative path or run from the workspace root |
| `unsupported model` | Model name not in registry | Use one of the supported model names |
| `cannot stratify` | Too few samples per class | Add more rows or reduce the number of classes |
| `feature columns contain infinite values` | `Inf`/`-Inf` in features | Clean the dataset |
| Model service returns 404 | Run not completed/approved | Check `manifest.json` final_status and validation_status |

---

## Tests

```bash
ruff check thelab tests scripts
mypy thelab
pytest tests/ -q
python scripts/evaluate_thesis.py
```
