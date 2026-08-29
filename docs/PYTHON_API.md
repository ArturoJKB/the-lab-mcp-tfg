# The Lab — Python API

The same deterministic pipeline behind the CLI is available as a Python API. This is useful for exploratory work in Jupyter notebooks or for embedding The Lab inside larger scripts.

## Low-level API: `thelab.run.runner`

```python
from thelab.run.runner import run_model

result = run_model(
    dataset="examples/iris.csv",
    target="species",
    model="logistic_regression",
    seed=42,
    output="runs",
)

print(result["run_id"])
print(result["status"])
print(result["metrics"]["test_accuracy"])
```

### Dry-run mode

Train in-memory without writing artifacts:

```python
result = run_model(
    dataset="examples/iris.csv",
    target="species",
    model="random_forest",
    seed=42,
    output="scratch",
    dry_run=True,
)

print(result["metrics"])
```

### Try all models

```python
from thelab.run.runner import try_all_models

results = try_all_models(
    dataset="examples/iris.csv",
    target="species",
    seed=42,
)

for r in results:
    print(r["model"], r["metrics"].get("test_accuracy"))
```

By default `try_all_models` uses dry-run mode. Pass `dry_run=False` and an `output` directory to persist every run.

## High-level API: `thelab.quick`

A more ergonomic wrapper for notebooks:

```python
from thelab.quick import experiment, compare, list_models

# Train one model
exp = experiment("examples/iris.csv", target="species", model="svc")
print(exp.metrics)
print(exp.predict([5.1, 3.5, 1.4, 0.2]))

# Compare all models in-memory
experiments = compare("examples/iris.csv", target="species")
for e in experiments:
    print(e.model, e.metrics.get("test_accuracy"))

# List available models
print(list_models())
```

## One-off prediction

```python
from thelab.run.prediction import predict

result = predict(
    run_id="run-20260819-...",
    features=[[5.1, 3.5, 1.4, 0.2]],
)
print(result["predictions"])
```

## Dataset inspection

```python
from thelab.run.inspect import inspect_dataset, format_inspect

result = inspect_dataset("examples/iris.csv", target="species")
print(format_inspect(result))
```

## EDA and cleaning (P2)

```python
from thelab.ide.eda_api import run_eda
from thelab.ide.cleaning import clean_dataset

eda = run_eda("data/uploads/my.csv", target="price")
print(eda["leakage_suspects"], eda["class_balance"])

# Deterministic cleaning with an audit report
result = clean_dataset("uploads/my.csv", target="price")
print(result["dataset_id"])              # uploads/my_cleaned.csv
for action in result["cleaning_report"]["actions"]:
    print("-", action)
```

Only uploaded datasets (`uploads/...`) can be cleaned; fixtures are read-only.
Datetime columns become calendar features; high-cardinality categoricals are
frequency-encoded instead of one-hot.

## Agents from Python / notebooks

Agents are plain Python objects — the same ones the CLI (`thelab-agent`) and
the UI use — so you can drive them from a notebook without any server.

**Propose an experiment** (deterministic fallback when no LLM is configured —
no API key, fully reproducible):

```python
import asyncio
from thelab.agents.mock import MockProvider
from thelab.agents.worker import WorkerAgent

worker = WorkerAgent(provider=MockProvider([]), servers=[], proposals_dir="proposals")
proposal = asyncio.run(
    worker.propose(goal="Predict price", dataset="data/uploads/my.csv",
                   target="price", model_grid=["random_forest"], seeds=[42, 43])
)
print(proposal.proposal_id, proposal.model_grid)

from thelab.ide.proposals_api import approve_and_run_proposal
outcome = approve_and_run_proposal(proposal.proposal_id, principal="notebook")
print(outcome["status"], outcome["completed"])
```

Approval records carry the principal; execution goes through the batch
runner — proposals never run directly.

**Plug in a real LLM** by swapping the provider — the notebook then drives
the same agent loop the CLI does:

```python
from thelab.agents.providers.ollama import OllamaProvider
worker = WorkerAgent(provider=OllamaProvider(), servers=[], proposals_dir="proposals")
```

`openai_compat` and `openrouter` adapters work the same way with their env
vars (`THELAB_LLM_BASE_URL`, `THELAB_LLM_API_KEY`, ...). See
[`docs/CLI_GUIDE.md`](CLI_GUIDE.md) for the `thelab-agent` equivalents.

## Context search

```python
from thelab.context.reader import ContextReader

reader = ContextReader()
print(reader.status())
hits = reader.search("proposal", limit=5)
for h in hits:
    print(h.event_id, h.summary)
```

Read-only: returns `public` + `internal` entries by default; `restricted` /
`secret` require an explicit override.

## Full experiment orchestration

The dashboard's experiment flow is available over HTTP
(`POST /experiment/run`, see [`docs/USER_GUIDE.md`](USER_GUIDE.md)); the
underlying pieces are importable directly — `thelab.ide.orchestrator.ExperimentOrchestrator`
for the EDA → cleaning → model-selection → batch-training loop and
`thelab.ide.jobs.get_job_manager` for background execution with SSE events.
