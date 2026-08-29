# Slice A3.1 — Agent hardening

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 hardening; `stage_2.md`  
**Scope:** Strengthen the A2/A3 agent surface with prior-run awareness, hyperparameter grids, agent memory via L2 session summaries, and validation-report-driven diagnosis.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/worker.py` | `ExperimentProposal` gains `hyperparameter_grid` and `prior_runs`; `WorkerAgent` compares against prior runs, validates JSON proposals, strips unsupported models, and emits hyperparameter-aware batch configs. |
| `thelab/agents/global_agents.py` | `DiagnosisAgent` now uses validation reports + EDA signals (`class_balance`, `outlier_scan`) to decide approve/reject and augment grids. |
| `thelab/agents/cli.py` | Session summaries are appended to the L2 context log after every agent invocation via `_run_session` / `_append_session_summary`. |
| `thelab/run/batch.py` | `BatchEntry` carries `hyperparameters`; batch config/report propagate them. |
| `thelab/run/runner.py` | `run_model` accepts hyperparameter overrides and persists them in `training_config.json`. |
| `thelab/run/model_registry.py` | `MODEL_REGISTRY.build_estimator` applies hyperparameter overrides safely. |
| `thelab/run/preprocess.py` | `build_pipeline` accepts hyperparameter overrides. |
| `tests/test_agents_worker.py` | Added tests for prior-run citation, hyperparameter grids in batch config, and unsupported-model filtering. |
| `tests/test_agents_global.py` | Added tests for validation-report approval/rejection and imbalance-driven grid augmentation. |
| `tests/test_agents_cli.py` | New test verifying the CLI appends a canonical L2 `agent_session_summary` event. |
| `docs/ROADMAP.md` | A3.1 marked `done`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_agents_worker.py tests/test_agents_global.py tests/test_agents_cli.py -q
.venv/bin/python scripts/evaluate_thesis.py
```

Results:

- `ruff check thelab tests scripts` — passed
- `mypy thelab` — passed
- `pytest tests/test_agents_worker.py tests/test_agents_global.py tests/test_agents_cli.py -q` — **18 passed**
- `pytest tests/ -q` — **315 passed**
- `evaluate_thesis.py` — **Overall: PASS**

### Documented example commands

Worker mode with a hyperparameter grid:

```bash
.venv/bin/python -m thelab.agents.cli --mode worker --provider mock \
  --dataset data/fixtures/iris.csv --target species \
  --hyperparameter-grid '{"C": [0.1, 1.0, 10.0]}' \
  --json
```

Result: proposal JSON includes `hyperparameter_grid`; the generated batch config expands the Cartesian product of models × seeds × hyperparameters.

Diagnosis mode using a prior validation report:

```bash
.venv/bin/python -m thelab.agents.cli --mode diagnosis --provider mock \
  --dataset data/fixtures/iris.csv --target species \
  --run-id <run_id> --json
```

Result: `DiagnosisAgent` loads the run's `validation_report.json`, decides whether the issue is recoverable, and either approves a new proposal (with grid augmentation for imbalance/outliers) or writes a rejection artifact.

---

## Design decisions

- **Prior-run comparison** is based on dataset path + target equality. The worker reads `runs/<run_id>/manifest.json` and `metrics.json` and includes the best-scoring prior run in the proposal rationale. This keeps the worker grounded in local evidence rather than LLM hallucination.
- **Hyperparameter grids** are stored on `ExperimentProposal` and expanded at batch-config generation time, not at proposal time. This keeps proposals small and deterministic while still enabling exhaustive sweeps.
- **Session summaries** are best-effort: `_run` catches and swallows append errors so a context-server outage cannot crash an agent invocation. Each summary is tagged with the agent mode, dataset, and target for later retrieval.
- **Diagnosis hardening** moves the approve/reject decision upstream of the LLM: unrecoverable validation failures (e.g., missing target) always reject; recoverable EDA signals (class imbalance, outliers) augment the hyperparameter grid rather than relying on the LLM to remember to do so.

---

## Known limitations

- Prior-run comparison only considers exact dataset path matches. If the same dataset is copied to a new path, the worker will not cite the earlier run.
- Hyperparameter override support is limited to parameters that the scikit-learn estimator accepts; unknown keys are currently ignored by `build_estimator`.
- Session summaries append to the L2 JSONL log but are not yet indexed into the SQLite context DB automatically; `thelab context index` must still be run.

---

## Next suggested slice

**B1 (Cross-domain benchmark suite)** — exercise the hardened worker/diagnosis flow across classification and regression tasks, then use the results to define a benchmark manifest that future slices must keep green.
