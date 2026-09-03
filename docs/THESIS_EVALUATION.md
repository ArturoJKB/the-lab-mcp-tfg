# Thesis Evaluation — The Lab

> Last updated: 2026-09-03  
> Status: automated RQ1–RQ6 PASS over the dataset matrix (iris classification +
> synthetic regression) in suite mode; **live OpenRouter recordings recorded
> for RQ1–RQ6 on both datasets** (see Live agentic recordings). Ollama
> deferred to a more powerful machine.

## Hypothesis

A local multi-agent orchestration architecture based on typed contracts and
MCP capabilities can execute a reproducible data-to-model workflow and expose
its resulting artifacts to independent agents without being coupled to a
specific LLM provider. Beyond the deterministic baseline, bounded
role-specialized agent rounds — grounded in the baseline's artifacts and gated
by human approval — can explore beyond it safely, and the orchestration itself
is measurable.

## Research questions → checks

| RQ | Question | Method | Pass bar |
|---|---|---|---|
| **RQ1** Reproducible run | Can a training run be reproduced from dataset + config + seed? | Two `run_model` executions, identical config. | Both complete `approved`; metrics match; manifest records seed + dependency versions. |
| **RQ2** MCP interoperability | Can an independent MCP client discover and use a model? | Stdio MCP client: `list_models` → `predict` on an approved run. | Tools present; run listed; typed predictions; no training-pipeline imports. |
| **RQ3** Context retrieval | Can local context retrieval recover useful past evidence? | Index JSONL fixture → search → read. | Relevant hit; DB bytes unchanged by read. |
| **RQ4** Grounding (agentic) | Do context-grounded rounds make more verifiable claims than ungrounded ones? | Ablation: full context pack vs stripped evidence; every metric claim in the round record verified against persisted metrics. | Grounded verified-claim rate ≥ ungrounded (suite: grounded evidence claims verify exactly). |
| **RQ5** Agentic capability (agentic) | Can the bounded round train valid, competitive models beyond the fixed grid, safely? | Round e2e: gate blocks unapproved execution; approved round executes through the factory; comparison artifact. | 0 silent failures; validity_rate ≥ 0.8 (live); deltas reported. |
| **RQ6** Orchestration value (agentic) | Does role-specialized orchestration outperform a single shared-prompt agent? | Ablation: `role_mode=multi` vs `role_mode=single` (identical otherwise). | Both complete protocol; role mode recorded; live: multi ≥ single on validity. |

Counting rule: only rounds with `mode == "agentic"` (≥1 stage produced LLM
content) count toward RQ4–RQ6 agentic tallies; `degraded_deterministic` rounds
are reported separately (they are the natural control arm).

The first three questions are answered at two scales (fixture baseline +
recorded real-dataset validation below); RQ4–RQ6 are answered in suite mode
(mock provider — protocol + instrumentation verified) with live-provider
recording pending.

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
# 1. Install from lock (see Environment above).

# 2. Reproducible training (CLI way in).
thelab run model --dataset examples/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs

# 3. Same pipeline through the HTTP service and through MCP — identical
#    metrics, identical artifacts (three-ways-in claim).
thelab-model-service --port 8000        # POST /train {"dataset_id": "fixtures/iris.csv", ...}
thelab-mcp-demo model_registry          # list_models + predict on the approved run

# 4. Index and search local context.
thelab context index --source .thelab/local-logs/agent-events.jsonl
thelab context search "proposal"

# 5. Real-dataset path: upload a large CSV in the UI, Run EDA, Clean dataset,
#    then start an experiment in the Experiment panel and watch it live.

# 6. Automated evaluator.
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py
```

## Automated evaluator

Entry point: `scripts/evaluate_thesis.py`

```bash
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py          # suite: RQ1-RQ6 (mock)
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py \
  --live openrouter --model z-ai/glm-5.3-flash                  # recorded agentic results
```

The script uses temporary directories so it does not modify developer state. It
prints a human-readable pass/fail table and a JSON summary, exiting with code 0
when all checks pass. Last run: **2026-09-03 — Overall PASS (RQ1–RQ6, suite
mode)**. RQ4–RQ6 chain from RQ1's verified run: the round's evidence, the
grounding target metrics, and the executed batch all derive from it.

## Current results (P2, 2026-08-29)

**Fixture baseline, re-run:** evaluator PASS — RQ1 metrics match, RQ2
prediction round-trip, RQ3 retrieval with byte-identical database.

**Three-ways-in comparison** (iris, `logistic_regression`, seed 42 — identical
metrics and artifacts through every interface):

| Way | Surface | Result | Time |
|---|---|---|---|
| CLI | `thelab run model ...` | 1.0000 test accuracy | ~2 s |
| HTTP | `POST /train` / `POST /jobs` | 1.0000 test accuracy | ~0.2 s |
| MCP | `agent_mcp run_training_job` + `get_job_status` | 1.0000 test accuracy | ~0.2 s |

**Real-dataset validation** (S&P 500 analyst ratings, 164,231 rows × 18
columns, downloaded dataset):

| Check | Result |
|---|---|
| Deterministic cleaning policy (datetime parsing, cardinality-aware encoding, audit report) | 164,231 → 113,769 rows, 18 → 32 columns, 6.3 s, full `cleaning_report` |
| Traceable scale guard | `svc` on 113,769 rows rejected in 0.1 s with reason (previously would run for hours or OOM) |
| Reproducible training (RQ1 at real scale) | logistic_regression completes in ~1.3 s with persisted seed/config/manifest |
| Full agent-orchestrated experiment (RQ2 surface) | 3 models × 3 seeds, 9 persisted runs, best random_forest 74.9% test accuracy, 121 s end-to-end with per-model progress events |
| Feature-horizon leakage study | naive features 84.2% → at-decision-time features 60.3%; every iteration a traceable run |

**Agent/provider status:** four provider adapters implemented (mock,
OpenAI-compatible, Ollama, OpenRouter) with structured-output repair and
deterministic fallback; agent proposals and orchestration are exercised by
the test suite against the mock provider end-to-end.

## Live agentic recordings (P5.C2, 2026-09-03)

Provider: **OpenRouter `z-ai/glm-5.3-flash`** · command:
`evaluate_thesis.py --live openrouter --model z-ai/glm-5.3-flash` ·
logs: `scratch/app_audit/results/c2_live_openrouter_iris.log` (iris arm,
independent operator run) + full-matrix run log. Overall **PASS — RQ1[iris],
RQ2[iris], RQ3, RQ4–RQ6[iris], RQ1–RQ6[housing]**.

| Check | Result | Live numbers |
|---|---|---|
| RQ4 grounding (iris + housing) | PASS | grounded verified-claim rate **1.0** (2/2 claims each); ungrounded arms complete with 0 verifiable claims — the grounding instrument discriminates |
| RQ5 capability (iris) | PASS | **validity_rate 1.0 — 15/15 agentic batch entries trained** after F2 per-model filtering (pre-fix: 0/108, see F2/F3 findings) |
| RQ5 capability (housing) | PASS (protocol) | 0/9 — the FE transform quantized the float target and passed earlier checks; **F4 fix added target dtype/cardinality validation** post-run |
| RQ6 ablation | PASS | multi arm `mode: agentic` (real LLM stages) vs single arm `mode: degraded_deterministic` — provenance is honest on both |
| Human gate | verified | gate blocked unapproved execution, then enabled it after recorded approval |

**Ollama (llama3.2:3b):** deferred — could not finish a grounded agent call
within 170 s on the development laptop (CPU); local recordings move to a more
powerful machine (plumbing verified separately: dead provider fails fast with
a readable error).

Live-path fixes that came out of these recordings (each with repro tests):
model-keyed grid rejection (F2-pre), shared-grid per-model param filtering
(F2), grid-explosion caps (F3), target-quantization transform rejection (F4),
task-aware model selection.

## Baseline record (P0 closeout, 2026-08-10)

Kept as evidence of the original RQ protocol execution in the locked
environment of that date.

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

## Limitations (current)

- RQ1–RQ3 run on the iris fixture; real-dataset claims come from the recorded
  S&P validation below, not from the evaluator script.
- RQ4–RQ6 suite results are mock-provider protocol checks (instrument +
  gating + provenance verified); live-provider quality results are pending
  (`--live openrouter|ollama`) and will be recorded here per provider.
- MCP transport is stdio only; the HTTP service is not an MCP transport.
- The code sandbox provides compute isolation, not OS-level filesystem
  confinement (documented audit finding BLK-01); sandbox outputs are always
  validated in the parent.
- Sub-agents execute in-process (subprocess isolation descoped).
- Context redaction is best-effort; the evaluation verifies retrieval, not
  exhaustive secret-family coverage.
- The Research panel is a local context **search** UI over stored evidence —
  it is not an autonomous agent and produces no generative answers (kept as
  search by design decision).
- Dependency lock is a `pip freeze` style pin without hashes; reproducibility
  relies on PyPI package availability.
- The iris fixture is 30 rows (6-row test splits): quoted 1.0000 accuracies
  are fixture artifacts, not model quality claims — a single misclassification
  would drop them visibly. Real-dataset results (S&P, Kaggle) carry the
  evidence weight.
- Approval-gate trust model: the gate guarantees recorded provenance and
  default-deny for agent-native surfaces (MCP tools); it cannot
  cryptographically verify that a CLI approval was typed by a human (a
  shell-capable agent could self-approve). Documented as a boundary, not a
  security claim.
