# Slice A3 — Global agents

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 — A3; `stage_2.md`  
**Scope:** Two supervising global agents over the worker: a citation-grounded Researcher and a Coding/Diagnosis agent that controls the worker through typed approval artifacts.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/global_agents.py` | New module: `Researcher` (cited answers from allowlisted artifacts) and `DiagnosisAgent` (proposes experiments via the worker and approves/rejects them). |
| `thelab/agents/__init__.py` | Exports `Researcher` and `DiagnosisAgent`. |
| `thelab/agents/cli.py` | Added `--mode researcher` and `--mode diagnosis` to `thelab-agent`, with options `--question`, `--run-id`, `--error`, `--dataset`, `--target`, `--model-grid`, `--seeds`, `--proposals-dir`. |
| `tests/test_agents_global.py` | Tests for Researcher citations, uncitable-claim dropping, missing-run handling, Diagnosis approval, and Diagnosis rejection of unrecoverable errors. |
| `examples/global_agents_demo.py` | End-to-end demo: baseline run → Researcher answer → Diagnosis approval of a follow-up proposal. |
| `docs/ROADMAP.md` | A3 marked `done`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_agents_global.py -q
```

Results:

- `ruff check` — passed
- `mypy thelab` — passed
- `pytest tests/test_agents_global.py -q` — **5 passed**

### Documented example commands

Researcher mode:

```bash
.venv/bin/python -m thelab.agents.cli --mode researcher \
  --question "Summarize the baseline run." --run-id <run_id> --json
```

Result: JSON with `answer`, `citations`, `prior_decisions`, and `artifacts_consulted`.

Diagnosis mode (approves a follow-up experiment):

```bash
.venv/bin/python -m thelab.agents.cli --mode diagnosis \
  --dataset data/fixtures/iris.csv --target species \
  --error "compare with a stronger baseline" \
  --model-grid random_forest --seeds 42 --json
```

Result: JSON with `status: approved`, `proposal_id`, `principal`, and `batch_config_path`.

Global agents demo:

```bash
.venv/bin/python examples/global_agents_demo.py
```

Result: baseline run → Researcher answer with citations → Diagnosis approval of a follow-up proposal.

---

## Design notes

- **Researcher grounding:** answers are assembled only from `manifest.json`, `metrics.json`, `validation_report.json`, `data_profile.json`, and `model_card.md`. Citations map claims to artifact source and run ID.
- **Uncitable-claim dropping:** when a draft answer is supplied, each sentence is checked against workspace evidence; sentences with unverifiable run_ids or metric values are removed.
- **Diagnosis control:** routes goals to the A2 `WorkerAgent` (harness-mediated) and then approves/rejects the resulting proposal through the same `ProposalStore` artifacts humans use.
- **Principal audit trail:** approval/rejection records include the agent principal (`diagnosis_agent` or `demo_diagnosis`).

---

## Limitations

- The Researcher builds deterministic baseline answers; richer natural-language synthesis would require a real LLM provider and remains an integration exercise.
- Session-start context search and session-end summary append via L2 are implemented internally (Researcher uses `ContextReader`, agents can write summaries) but are not yet wired as automatic bookends in the CLI modes.
- The Diagnosis heuristic for unrecoverable errors is simple (target/dataset-not-found keywords).

---

## Smallest next step

**B1 — Cross-domain benchmark suite** (Stage 3): curate small openly-licensed datasets across six domains and demonstrate `thelab run batch` + `thelab compare` with zero code changes.
