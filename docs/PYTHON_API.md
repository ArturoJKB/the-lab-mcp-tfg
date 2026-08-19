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
