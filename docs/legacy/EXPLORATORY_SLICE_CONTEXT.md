# Exploratory CLI + Python API Slice

> Follow-up to Phase A hardening. Goal: make The Lab fast for exploration without losing the structured, auditable path.

---

## What changed

### New CLI commands

| Command | Purpose |
|---|---|
| `thelab inspect --dataset <csv> [--target <col>]` | Quick dataset profile without training |
| `thelab predict --run-id <id> --features <values>` | One-off prediction from an approved run |
| `thelab compare --output <dir>` | Metrics table across completed runs |

### Enhanced `thelab run model`

| Flag | Purpose |
|---|---|
| `--dry-run` | Train in-memory, print metrics, persist nothing |
| `--try-all` | Train every registered model and print a comparison table |

`--try-all` defaults to dry-run mode so exploratory comparisons do not pollute `runs/`.

### Python / Jupyter API

- Added `thelab/quick.py` with `experiment()`, `compare()`, and `list_models()`.
- Added `docs/PYTHON_API.md` documenting both low-level (`thelab.run.runner`) and high-level (`thelab.quick`) APIs.
- Added `examples/notebooks/01_quick_start.ipynb` demonstrating inspection, training, comparison, and prediction.

### Example datasets

- Added `examples/wine.csv` and `examples/breast_cancer.csv` from scikit-learn.
- Added batch configs:
  - `examples/wine-batch.json`
  - `examples/breast-cancer-batch.json`
  - `examples/multi-dataset-batch.json`

### Scratch directory convention

- Exploratory outputs can go to `scratch/` instead of `runs/`.
- `scratch/` is listed in `.gitignore` so quick experiments are not committed.

### Documentation

- Rewrote `README.md` to be short and concise.
- Created `docs/CLI_GUIDE.md` with full command reference, supported models, batch config format, examples, and troubleshooting.
- Created `docs/FUTURE_FEATURES.md` capturing all seven exploratory ideas plus future hardening/extensibility items.
- Added a backlog table to `docs/ROADMAP.md`.

### Tests

- `tests/test_exploratory.py` covers inspect, dry-run, try-all, predict, compare, and the quick API.
- `tests/test_examples.py` verifies all shipped datasets and batch configs train successfully.

---

## Verification

```bash
ruff check thelab tests scripts   # passes
mypy thelab                       # passes
pytest tests/ -q                  # 211 passed
python scripts/evaluate_thesis.py # RQ1–RQ3 PASS
```

Example exploratory workflow:

```bash
thelab inspect --dataset examples/iris.csv --target species
thelab run model --dataset examples/iris.csv --target species --model logistic_regression --seed 42 --output scratch --dry-run
thelab run model --dataset examples/iris.csv --target species --model logistic_regression --seed 42 --output scratch --try-all --dry-run
thelab run model --dataset examples/iris.csv --target species --model logistic_regression --seed 42 --output runs
thelab predict --run-id run-20260819-... --features "5.1,3.5,1.4,0.2"
thelab compare --output runs
```

---

## Limitations / next suggested slice

- `--try-all` uses dry-run by default; persisting all model runs requires explicit `--output` and removing `--dry-run`.
- `thelab sketch` interactive mode remains future work.
- Hash-verified model loading and prediction sandboxing are documented in `docs/FUTURE_FEATURES.md` but not implemented.
