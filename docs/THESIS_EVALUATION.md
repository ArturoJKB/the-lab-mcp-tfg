# Thesis Evaluation — The Lab P0

> Last updated: 2026-08-10  
> Status: evaluation protocol defined and automated checks executed.

## Hypothesis

A local multi-agent orchestration architecture based on typed contracts and
MCP capabilities can execute a reproducible data-to-model workflow and expose
its resulting artifacts to independent agents without being coupled to a
specific LLM provider.

## Research questions → checks

| RQ | Method | Pass bar |
|---|---|---|
| **RQ1** Reproducible run | Two `thelab run model` executions on the same fixture with identical dataset, model, and seed. | Both runs complete with `approved` validation status. Key metrics match within tolerance. Manifest records seed, config, and dependency versions. |
| **RQ2** MCP interoperability | Independent stdio MCP client connects to existing `model_registry_mcp`, calls `list_models`, then `predict` on an approved run. | Tool list contains expected tools. `list_models` returns the approved run. `predict` returns typed predictions. Client does not import training pipeline internals. |
| **RQ3** Context retrieval | Index a small JSONL fixture and search via `ContextReader` / context MCP. | Search returns at least one relevant hit. Result contains stable fields (event_id, summary, tags). Database bytes are unchanged by read-only search. |

## Environment

- Supported Python: `>=3.11,<3.15`
- Lockfile: `requirements.lock`
- Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e .
```

## Manual demo script

```bash
# 1. Start with a clean terminal in the project root.
# 2. Install from lock (see Environment above).

# 3. Run a reproducible training pipeline.
thelab run model --dataset data/iris.csv --target species --model logistic_regression --seed 42

# 4. Discover and predict via MCP.
thelab-mcp-demo model_registry

# 5. Index and search local context.
thelab context index --source .thelab/local-logs/agent-events.jsonl
thelab-mcp-demo context

# 6. Open the human dashboard.
thelab-model-service --port 8000
# Browse to http://127.0.0.1:8000/ — Models, Coding/Logger, and Research/Copilot panels.

# 7. Run the automated evaluator.
python scripts/evaluate_thesis.py
```

## Automated evaluator

Entry point: `scripts/evaluate_thesis.py`

```bash
python scripts/evaluate_thesis.py
```

The script uses temporary directories so it does not modify developer state. It
prints a human-readable pass/fail table and a JSON summary, exiting with code 0
when all checks pass.

## Results

Run on 2026-08-10 in the locked environment described above.

```text
============================================================
The Lab P0 — Thesis Evaluation Report
============================================================
Overall: PASS

RQ1: PASS
  run_ids: ['run-20260810-023703-2e37998c', 'run-20260810-023703-237bc12c']
  metrics: {'test_accuracy': 1.0, 'test_f1_macro': 1.0}
RQ2: PASS
  predictions: ['setosa']
RQ3: PASS
  hits: 1
  event_id: evt-repro
```

JSON summary:

```json
{
  "results": [
    {
      "rq": "RQ1",
      "status": "PASS",
      "run_ids": [
        "run-20260810-023703-2e37998c",
        "run-20260810-023703-237bc12c"
      ],
      "metrics": {
        "test_accuracy": 1.0,
        "test_f1_macro": 1.0
      }
    },
    {
      "rq": "RQ2",
      "status": "PASS",
      "predictions": [
        "setosa"
      ]
    },
    {
      "rq": "RQ3",
      "status": "PASS",
      "hits": 1,
      "event_id": "evt-repro"
    }
  ]
}
```

## Limitations

- The evaluation uses a small fixture dataset and a single scikit-learn model.
- MCP transport is stdio only; no SSE or HTTP MCP transport is evaluated.
- Context redaction is best-effort; the evaluation verifies retrieval, not
  exhaustive secret-family coverage.
- The Research/Copilot panel is a local-evidence browser; no LLM or generative
  answers are included in P0.
- Dependency lock is a `pip freeze` style pin without hashes; reproducibility
  relies on PyPI package availability.
