# B1 Benchmark — CLI Recreation Guide

This document shows how to reproduce the B1 cross-domain benchmark manually via the existing `thelab` CLI. It mirrors what `scripts/run_b1_benchmark.py` does.

## Prerequisites

```bash
source .env
```

Your `.env` should contain:

```bash
export THELAB_LLM_API_KEY="sk-or-v1-..."   # for OpenRouter
export THELAB_LLM_MODEL="stealth/ox-alpha"  # or another OpenRouter model
export OLLAMA_MODEL="llama3.2:3b"           # for Ollama
```

## 1. Prepare datasets

```bash
.venv/bin/python scripts/prepare_b1_datasets.py
```

This creates:

```text
data/benchmarks/california_housing.csv
data/benchmarks/breast_cancer.csv
data/benchmarks/wine_quality_red.csv
```

## 2. Deterministic baseline (one per domain)

```bash
# Regression — real estate
.venv/bin/python -m thelab run model \
  --dataset data/benchmarks/california_housing.csv \
  --target MedHouseVal \
  --model ridge \
  --seed 42 \
  --output runs

# Binary classification — medical
.venv/bin/python -m thelab run model \
  --dataset data/benchmarks/breast_cancer.csv \
  --target target \
  --model logistic_regression \
  --seed 42 \
  --output runs

# Multi-class classification — wine quality
.venv/bin/python -m thelab run model \
  --dataset data/benchmarks/wine_quality_red.csv \
  --target quality \
  --model logistic_regression \
  --seed 42 \
  --output runs
```

## 3. Agent-boosted proposals

### OpenRouter

```bash
.venv/bin/python -m thelab.agents.cli --mode worker --provider openrouter \
  "predict california housing prices" \
  --dataset data/benchmarks/california_housing.csv \
  --target MedHouseVal \
  --proposals-dir benchmarks/b1/proposals \
  --json

.venv/bin/python -m thelab.agents.cli --mode worker --provider openrouter \
  "classify breast cancer" \
  --dataset data/benchmarks/breast_cancer.csv \
  --target target \
  --proposals-dir benchmarks/b1/proposals \
  --json

.venv/bin/python -m thelab.agents.cli --mode worker --provider openrouter \
  "predict wine quality" \
  --dataset data/benchmarks/wine_quality_red.csv \
  --target quality \
  --proposals-dir benchmarks/b1/proposals \
  --json
```

### Ollama

```bash
.venv/bin/python -m thelab.agents.cli --mode worker --provider ollama \
  "predict california housing prices" \
  --dataset data/benchmarks/california_housing.csv \
  --target MedHouseVal \
  --proposals-dir benchmarks/b1/proposals \
  --json

.venv/bin/python -m thelab.agents.cli --mode worker --provider ollama \
  "classify breast cancer" \
  --dataset data/benchmarks/breast_cancer.csv \
  --target target \
  --proposals-dir benchmarks/b1/proposals \
  --json

.venv/bin/python -m thelab.agents.cli --mode worker --provider ollama \
  "predict wine quality" \
  --dataset data/benchmarks/wine_quality_red.csv \
  --target quality \
  --proposals-dir benchmarks/b1/proposals \
  --json
```

## 4. Approve and run agent proposals

Replace `<proposal_id>` with the IDs printed by the worker steps above.

```bash
.venv/bin/python -m thelab proposals approve --principal benchmark --run \
  --proposal-id <proposal_id> \
  --output runs
```

This writes a batch summary to `runs/batch_summary.json` and a report next to the batch config.

## 5. Compare results

```bash
.venv/bin/python -m thelab compare --output runs
```

You can also inspect individual run artifacts:

```bash
.venv/bin/python -m thelab context index   # if you want to index agent logs
```

## Notes

- The benchmark script automates steps 1–4 for both providers and writes `benchmarks/b1/benchmark_manifest.json` plus `benchmarks/b1/reports/b1_report.md`.
- Generated datasets and benchmark results are **not committed** to git (`data/benchmarks/` and `benchmarks/b1/` are ignored).
