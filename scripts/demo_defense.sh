#!/usr/bin/env bash
# =============================================================================
# The Lab — D1 defense demo (deterministic, network-optional)
#
# Story arc (maps to the thesis research questions):
#   RQ1    Reproducible direct run        (CLI, two identical trainings)
#   RQ2    MCP interoperability           (independent client predicts)
#   RQ3    Local context retrieval        (index -> search, DB untouched)
#   CORE   Multi-agent experiment         (EDA -> clean -> select -> train via API,
#                                          proposal approval, generated notebook)
#   RQ4-6  Agentic round + human gate     (grounded round -> awaiting_approval ->
#                                          presenter approves -> comparison artifact)
#   EVAL   Automated evaluator            (RQ1-RQ6 over the dataset matrix)
#
# Usage:
#   ./scripts/demo_defense.sh                        # network-optional (mock provider)
#   ./scripts/demo_defense.sh --live                 # LLM steps via live Ollama
#   ./scripts/demo_defense.sh --verify-venv          # + fresh-venv install verification
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

LIVE="${1:-}"
VERIFY_VENV="false"
for arg in "$@"; do
  [ "$arg" = "--verify-venv" ] && VERIFY_VENV="true"
done
export THELAB_RUNS_ROOT="${THELAB_RUNS_ROOT:-runs}"
PROVIDER="mock"
[ "$LIVE" = "--live" ] && PROVIDER="ollama"

step() { printf '\n\033[1;34m=== %s ===\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }

if [ "$VERIFY_VENV" = "true" ]; then
  step "VENV. Fresh-environment install verification"
  VENV_DIR="$(mktemp -d)/.venv-demo"
  python3 -m venv "$VENV_DIR"
  info "created throwaway venv: $VENV_DIR"
  "$VENV_DIR/bin/pip" install -q -r requirements.lock
  "$VENV_DIR/bin/pip" install -q -e .
  info "install from requirements.lock OK"
  THELAB_RUNS_ROOT="$(mktemp -d)" "$VENV_DIR/bin/thelab" run model \
    --dataset examples/iris.csv --target species \
    --model logistic_regression --seed 42 --output runs >/dev/null 2>&1
  info "smoke run in fresh env OK (RQ1 path)"
  rm -rf "$VENV_DIR"
  info "fresh-venv verification PASS"
fi

step "0. Health"
.venv/bin/python -c "
import urllib.request, json
print('   service-independent demo (no server required)')"

step "RQ1. Reproducible direct run — two identical trainings (iris, seed 42)"
RUN_A=$(.venv/bin/thelab run model --dataset examples/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs 2>&1 >/dev/null | grep "Run completed" | awk '{print $3}')
info "run A: $RUN_A"
RUN_B=$(.venv/bin/thelab run model --dataset examples/iris.csv --target species \
  --model logistic_regression --seed 42 --output runs 2>&1 >/dev/null | grep "Run completed" | awk '{print $3}')
info "run B: $RUN_B"
.venv/bin/python - "$RUN_A" "$RUN_B" <<'PY'
import json, sys
a, b = sys.argv[1], sys.argv[2]
ma = json.load(open(f"runs/{a}/metrics.json"))
mb = json.load(open(f"runs/{b}/metrics.json"))
assert ma["test_accuracy"] == mb["test_accuracy"], "metrics diverged"
print(f"    metrics identical: accuracy={ma['test_accuracy']:.4f} (RQ1 PASS)")
PY

step "RQ2. MCP interoperability — independent client discovers and predicts"
.venv/bin/thelab-mcp-demo model_registry --run-id "$RUN_A" 2>/dev/null | head -8 || true

step "RQ3. Local context retrieval — index then search (store untouched)"
mkdir -p .thelab/local-logs
# Unique event id per run: the indexer rejects a known event_id whose content
# changed (content-conflict detection is a feature, not a bug).
printf '%s\n' "{\"event_id\":\"evt-demo-$(date +%s)\",\"timestamp\":\"2026-09-01T10:00:00+00:00\",\"event_type\":\"agent_session_summary\",\"session_id\":\"demo\",\"outcome\":{\"status\":\"completed\",\"summary\":\"worker proposed logistic_regression on iris\"},\"privacy\":{\"level\":\"internal\"}}" \
  > .thelab/local-logs/demo-events.jsonl
.venv/bin/thelab context index --source .thelab/local-logs/demo-events.jsonl 2>/dev/null | grep '"ok"'
.venv/bin/thelab context search "logistic_regression" 2>/dev/null | grep -m1 '"count"'

step "CORE. Multi-agent experiment on a real dataset (provider: $PROVIDER)"
.venv/bin/python - "$PROVIDER" <<'PY'
import asyncio, json, os, sys, time
from pathlib import Path

provider = sys.argv[1]
# pick a real dataset already in uploads (network-free), prefer churn/housing/attrition
uploads = sorted(Path("data/uploads").glob("*.csv"))
preferred = [u for u in uploads if any(k in u.name for k in ("churn", "attrition", "housing", "e-commerce"))]
dataset = preferred[0] if preferred else (uploads[0] if uploads else None)
assert dataset is not None, "no local dataset found; run the kaggle ingest first"
dataset_id = f"uploads/{dataset.name}"
print(f"    dataset: {dataset_id}")

from thelab.ide.experiment_api import start_experiment

TARGET = {"churn": "Exited", "attrition": "Attrition", "housing": "median_house_value",
          "e-commerce": "Sales"}
target = next((t for k, t in TARGET.items() if k in dataset.name), None)
if target is None:
    import pandas as pd
    cols = pd.read_csv(dataset, nrows=5).columns.tolist()
    target = cols[-1]
    print(f"    target inferred: {target}")

started = asyncio.run(start_experiment(
    goal=f"Predict {target} and compare models (thesis defense demo)",
    dataset_id=dataset_id,
    target=target,
    provider_name=provider,
))
exp_id, job_id = started["experiment_id"], started["job_id"]
print(f"    experiment: {exp_id}  job: {job_id}")

from thelab.ide.jobs import get_job_manager

async def wait():
    while True:
        job = await get_job_manager().get(job_id)
        assert job is not None
        if job.status in {"completed", "failed"}:
            return job
        await asyncio.sleep(0.5)

job = asyncio.run(asyncio.wait_for(wait(), 1800))
print(f"    job: {job.status}")

status = asyncio.run(__import__("thelab.ide.experiment_api", fromlist=["get_experiment_status"]).get_experiment_status(exp_id))
print(f"    state: {status['state']}  best run: {status.get('best_run_id')}")
for role, block in (status.get("sub_agent_results") or {}).items():
    interp = block.get("llm_interpretation")
    if interp:
        snippet = " ".join(str(interp).split())[:160]
        print(f"    {role} (LLM): {snippet}...")

results = asyncio.run(__import__("thelab.ide.experiment_api", fromlist=["get_experiment_results"]).get_experiment_results(exp_id))
for r in results.get("training_results", []):
    print(f"    {r['model']} (seed {r['seed']}): {r['status']} -> {r.get('run_id')}")

# generated notebook (P3.6)
if status.get("best_run_id"):
    from thelab.run.notebook import generate_run_notebook
    from thelab.mcp.common import get_runs_root
    nb = generate_run_notebook(status["best_run_id"])
    out = Path("docs/demo_artifacts"); out.mkdir(parents=True, exist_ok=True)
    nb_path = out / f"{status['best_run_id']}_report.ipynb"
    nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"    notebook: {nb_path} ({len(nb['cells'])} cells)")

# persist the full experiment record as a demo artifact
art = out / f"{exp_id}.json"
art.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
print(f"    experiment record: {art}")
PY

step "RQ4-6. Agentic round grounded in the baseline — human approval gate"
.venv/bin/python - "$PROVIDER" <<'PY'
import asyncio, json, os, sys
from pathlib import Path

provider = sys.argv[1]
uploads = sorted(Path("data/uploads").glob("*.csv"))
assert uploads, "no local dataset found; run the kaggle ingest first"
preferred = [u for u in uploads if any(k in u.name for k in ("churn", "attrition", "housing", "e-commerce"))]
dataset = preferred[0] if preferred else uploads[0]
dataset_id = f"uploads/{dataset.name}"
TARGET = {"churn": "Exited", "attrition": "Attrition", "housing": "median_house_value",
          "e-commerce": "Sales"}
target = next((t for k, t in TARGET.items() if k in dataset.name), None)
if target is None:
    import pandas as pd
    target = pd.read_csv(dataset, nrows=5).columns.tolist()[-1]
print(f"    dataset: {dataset_id}  target: {target}")

from thelab.ide.experiment_api import start_experiment

started = asyncio.run(start_experiment(
    goal=f"Agentic round over the deterministic baseline (defense demo)",
    dataset_id=dataset_id,
    target=target,
    provider_name=provider,
    agentic_round=True,
))
exp_id, job_id = started["experiment_id"], started["job_id"]
print(f"    experiment: {exp_id}")

from thelab.ide.jobs import get_job_manager

async def wait(job_id):
    while True:
        job = await get_job_manager().get(job_id)
        assert job is not None
        if job.status in {"completed", "failed", "cancelled"}:
            return job
        await asyncio.sleep(0.5)

job = asyncio.run(asyncio.wait_for(wait(job_id), 1800))
print(f"    baseline job: {job.status}")

from thelab.ide.experiment_api import get_agentic_round
record = asyncio.run(get_agentic_round(exp_id))
rec = record.get("record") or {}
print(f"    round status: {rec.get('status')}  mode: {rec.get('mode')}")
print(f"    transform: {rec.get('transform', {}).get('status')}")
proposal = rec.get("proposal") or {}
print(f"    proposal: {proposal.get('proposal_id')}  grid: {proposal.get('model_grid')}  seeds: {proposal.get('seeds')}")
assert rec.get("status") == "awaiting_approval", "expected the human gate"

pid = rec["proposal_id"]
interactive = sys.stdin.isatty()
if interactive:
    print(f"    >>> HUMAN GATE: review the proposal above, press Enter to APPROVE (Ctrl+C to reject)")
    input()
from thelab.ide.experiment_api import approve_agentic_round
approved = asyncio.run(approve_agentic_round(exp_id, principal="ui"))
print(f"    approved ({approved['state']}) -> execution job {approved['job_id']}")

exec_job = asyncio.run(asyncio.wait_for(wait(approved["job_id"]), 1800))
print(f"    execution job: {exec_job.status}")

record = asyncio.run(get_agentic_round(exp_id))
comparison = (record.get("record") or {}).get("execution", {}).get("comparison") or {}
det = (comparison.get("deterministic_best") or {}).get("metrics") or {}
ag = (comparison.get("agentic_best") or {}).get("metrics") or {}
print(f"    deterministic best: {det.get('test_accuracy', det.get('test_rmse'))}")
print(f"    agentic best:       {ag.get('test_accuracy', ag.get('test_rmse'))}")
print(f"    delta: {comparison.get('metric_delta')}  validity: {comparison.get('validity_rate')}")
art = Path("docs/demo_artifacts"); art.mkdir(parents=True, exist_ok=True)
(art / f"{exp_id}.agentic_round.json").write_text(
    json.dumps(record.get("record") or {}, indent=2, default=str), encoding="utf-8")
print(f"    round record: docs/demo_artifacts/{exp_id}.agentic_round.json")
PY

step "EVAL. Automated evaluator — six research questions, dataset matrix"
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py 2>/dev/null | sed -n '/^Overall/p;/^RQ/p'

step "DONE. Live UI: start 'thelab-model-service' and open http://127.0.0.1:8000"
printf '\nAll demo artifacts saved under docs/demo_artifacts/ and runs/.\n'
