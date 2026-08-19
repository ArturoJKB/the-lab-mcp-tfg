# The Lab — Local-First Data-to-Model Factory

Bachelor thesis (TFG) at **Universidad Carlos III de Madrid**, Data Science and Engineering.

> **Status:** P0 + Phase A hardening complete.

## What it is

A local-first, reproducible ML experiment runner. Train models from CSVs, expose them via MCP/HTTP, index agent logs, and compare experiments in batches.

No cloud services, LLM providers, or vector databases are required for P0.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e .
```

## Quick start

```bash
# Train one model
thelab run model --dataset examples/iris.csv --target species --model logistic_regression --seed 42 --output runs

# Run a batch experiment
thelab run batch --config examples/iris-batch.json --output runs --report batch_report.md

# Serve approved models over HTTP
thelab-model-service
```

Run outputs live under `runs/<run_id>/` and include `manifest.json`, `metrics.json`, `model.joblib`, and `model_card.md`.

## CLI commands

| Command | Purpose |
|---|---|
| `thelab run model` | Train a single model from a CSV |
| `thelab run batch` | Run many experiments from a JSON config |
| `thelab context index` | Index agent-session logs |
| `thelab context search` | Search indexed logs |
| `thelab context show` | Show one log entry |
| `thelab-model-service` | Local HTTP service for approved models |

See [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md) for the full command reference, supported models, batch config format, and examples.

## Supported models

- `logistic_regression`
- `random_forest`
- `svc`
- `sgd_classifier`
- `*_probability` variants for probability estimates

## Tests

```bash
ruff check thelab tests scripts
mypy thelab
pytest tests/ -q
python scripts/evaluate_thesis.py
```

## Docs

- [`docs/CLI_GUIDE.md`](docs/CLI_GUIDE.md) — CLI usage and examples
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — implementation slices and status
- [`docs/PRD_P0.md`](docs/PRD_P0.md) — binding P0 requirements

## Author

**Arturo Kolster Borges** · Universidad Carlos III de Madrid · Data Science and Engineering (2022-2026)

## License

[MIT](LICENSE)
