# The Lab — User Guide

How to use The Lab. The same deterministic pipeline runs through **three
interfaces**, and every run produces the same auditable artifacts under
`runs/<run_id>/`.

## One app, three ways in

| Way | Best for | How it works |
|---|---|---|
| **UI** (`thelab-model-service`) | Exploring and iterating visually | Browser dashboard: upload, EDA, cleaning, agent experiments with live progress |
| **CLI** (`thelab ...`) | Scripting and quick checks | Direct, synchronous, no server needed |
| **MCP** (`thelab-*-mcp`) | Independent agents and tools | Typed tools over stdio; clients never touch pipeline internals |

**What the agents actually do:** the WorkerAgent reads your dataset's EDA and
prior runs and proposes an experiment (models, seeds, hyperparameters). The
ExperimentOrchestrator runs three specialized sub-agents — EDAAnalyst
(analysis), FeatureEngineer (cleaning + baselines), ModelSelector (comparison)
— and then trains through the same deterministic pipeline the CLI uses. Every
agent action is recorded as typed evidence; nothing runs without an approval
record.

All three ways produce **identical results** for identical inputs (same seed
→ same metrics). Verified side by side on the iris fixture
(`logistic_regression`, seed 42):

| Way | Command surface | Result | Time | Notes |
|---|---|---|---|---|
| CLI | `thelab run model ...` | 1.0000 accuracy | ~2 s | Synchronous; any workspace-relative CSV |
| HTTP | `POST /jobs {"type": "train"}` | 1.0000 accuracy | ~0.2 s | Background job + SSE; datasets via `uploads/`/`fixtures/` ids |
| MCP | `run_training_job` + `get_job_status` | 1.0000 accuracy | ~0.2 s | stdio; same job manager, same artifacts |

Use the UI to explore, the CLI to automate, MCP when another agent needs the
factory.

---

## 1. The UI

```bash
thelab-model-service          # open http://127.0.0.1:8000
```

### Step by step

1. **Upload a CSV** — Datasets panel, drag & drop (max 100 MB).
2. **Understand it** — pick the dataset, type the target column, click **Run EDA**.
   You get missing values, feature types, class balance, correlations,
   outliers, and leakage suspects.
3. **Clean it** — click **Clean dataset**. This creates a `*_cleaned.csv`:
   - rows with a missing target are dropped,
   - datetime columns become numeric calendar features,
   - categorical columns with ≤ 20 distinct values are one-hot encoded,
     wider ones (e.g. 500 tickers) are frequency-encoded,
   - missing numeric values are imputed.
   The response lists every action taken, per column.
4. **Run an experiment** — Experiment panel:
   - **Plan tab**: dataset, target, goal text → *Start experiment*.
   - **Run tab**: live stage pipeline (Plan → Clean → Train → Evaluate),
     per-model progress lines, best-run summary. A **Cancel** button stops
     the run between models or stages.
   - **History tab**: click any past experiment to reopen it. Send
     **feedback** ("focus on tree models") to start a new iteration.
5. **Use the model** — Models panel: metrics, artifacts, predict form.

### Reading errors

Rejections (bad schema, scale limits) are normal, valid outcomes — the banner
shows the exact reason and the run keeps its evidence.

---

## 2. The CLI

```bash
# Train one model
thelab run model --dataset examples/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs

# Compare every registered model in memory
thelab run model --dataset examples/iris.csv --target species --try-all

# Batch experiments
thelab run batch --config examples/iris-batch.json --output runs --report report.md

# Quick profile / one-off prediction / comparison table
thelab inspect --dataset examples/iris.csv --target species
thelab predict --run-id <run_id> --features '5.1,3.5,1.4,0.2'
thelab compare

# Context store (redacted, searchable)
thelab context index --source .thelab/local-logs/agent-events.jsonl
thelab context search "proposal"
```

Full reference: [`docs/CLI_GUIDE.md`](CLI_GUIDE.md).

---

## 3. The HTTP API

The model service exposes a local JSON API. Responses are
`{"ok": true, "data": ...}` or an HTTP error with `detail`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/datasets/upload` | multipart CSV upload |
| GET | `/eda/{dataset_id}?target=` | EDA report |
| POST | `/datasets/{dataset_id}/clean` | cleaning policy; body: `{"target": "..."}` |
| POST | `/experiment/run` | start an orchestrated experiment |
| GET | `/experiment/{id}/status` / `/events` / `/results` | state, SSE stream, best run |
| POST | `/experiment/{id}/feedback` | queue a new iteration |
| POST | `/jobs` / `POST /jobs/{id}/cancel` | submit / cancel background jobs |
| POST | `/predict` | inference on approved runs |

Example:

```bash
curl -s -X POST localhost:8000/train \
  -H 'Content-Type: application/json' \
  -d '{"dataset_id": "fixtures/iris.csv", "target": "species",
       "model": "logistic_regression", "seed": 42}'
```

Note: HTTP paths reference datasets by id (`uploads/<file>` or
`fixtures/<basename>`), not by arbitrary path.

---

## 4. MCP

Seven stdio servers expose the factory to independent clients — catalog,
registry (list models, predict), workspace (artifacts), context (read +
write), EDA, and agent (orchestration, training jobs). Smoke-test without an
MCP client:

```bash
thelab-mcp-demo model_registry --run-id <run_id>
thelab-mcp-demo data_catalog --run-id <run_id>
thelab-mcp-demo context
```

---

## 5. Real-world datasets: what to expect

- Upload and EDA work at any reasonable size.
- Cleaning applies its policy and reports what it did; the cleaned copy
  appears in the dataset list.
- Some models have **scale guards** (e.g. `svc`: max 50,000 training rows) —
  on bigger data they are rejected with a reason instead of running for
  hours. Prefer `logistic_regression`, `sgd_classifier`,
  `hist_gradient_boosting`, `random_forest`.
- A rejected run keeps its manifest, validation report, and reason.
- Long runs stream per-model progress and can be cancelled.

Verified on the S&P 500 analyst dataset (164k rows): clean 6.3 s, train 1.3 s,
full orchestrated experiment (9 runs) 121 s.

---

## 6. Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| `dataset is empty after dropping rows with missing target` | Every row lacks the target | Upload data with target values |
| `not all feature columns are numeric` | Raw strings survived cleaning | Clean first, or pre-encode |
| `constant feature columns found: [...]` | A feature has one distinct value | Remove the column or vary the data |
| `model 'X' is limited to N training rows` | Scale guard | Use a scalable model or subsample |
| `invalid dataset_id` (HTTP) | Only `uploads/`/`fixtures/` ids accepted | Upload the CSV first |
| `feature at index 0 is not numeric` (CLI predict) | Dict given to `--features` | Use comma-separated values in column order |
| Job stuck `running` | Long synchronous stage | Watch the Pipeline panel; use Cancel |
