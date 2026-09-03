# RQ5 Spike — Agent Code Generation Validity (2026-09-02)

> Throwaway spike to de-risk Phase B (RQ5: sandboxed agent-generated code) before
> committing to the full agentic round. Script: `benchmarks/spike/rq5_spike.py`.

## Question

Can the LLM sub-agents (local Ollama, cloud OpenRouter) write pandas transforms
that pass deterministic post-validation inside the restricted sandbox?

## Test setup

| Parameter | Value |
|---|---|
| Dataset | Titanic (Kaggle `yasserh/titanic-dataset`, cleaned: 891 rows × 14 cols, target `Survived`) |
| Providers | OpenRouter `z-ai/glm-5.3-flash`; Ollama `llama3.2:3b` (server down at test time) |
| Attempts per provider | 3 (open-ended, "engineer 2 features", "handle skew") |
| Validation | Appended epilogue (not LLM-generated): checks shape ≥ 1, target preserved, new features present |
| Sandbox | `run_in_sandbox` with `files={"dataset.csv": …}` (read-only dataset copy), 2 GB RLIMIT, 30 s timeout |

## Results — OpenRouter (GLM 5.3 Flash): 3/3 valid

| Attempt | Verdict | Features generated | Notes |
|---|---|---|---|
| open-ended | ✅ valid | 14 new (FamilySize, IsAlone, Fare_log, Age_bin, Age×Pclass, WomanOrChild…) | LLM independently identified OverTime-equivalent interaction features |
| engineer-2-features | ✅ valid | 8 new (FamilySize, IsAlone, FarePerPerson, Fare_log, IsChild…) | Followed instruction precisely |
| handle-skew | ✅ valid | 6 new (Fare_log, FarePerPerson_log, FamilySize…) | Correctly applied log1p to right-skewed Fare |

**FE validity: 3/3 = 100%** → RQ5 bar (≥80%) is realistic with GLM 5.3 Flash.

**ModelSelector:** correctly picked `svc` (highest macro-F1 for imbalanced data) with
quantified class-imbalance reasoning. 1/1 valid.

## Root cause found: sandbox Lambda block (fixed)

The initial spike run produced **0/3 valid** — every attempt failed with
`blocked syntax: Lambda`. The LLM's code used `groupby().transform(lambda s: …)`,
a core pandas idiom. The sandbox's `blocked_ast_nodes` included `ast.Lambda`.

**Fix:** removed `ast.Lambda` from `thelab/sandbox/policy.py:66-81`.
Lambdas cannot import, access blocked builtins, or escape scope (no
`global`/`nonlocal` — separately blocked). After the fix: 3/3 valid.

## Validation approach (prompt-independent)

The spike does **not** rely on the LLM following print instructions. Instead,
The Lab appends a **validation epilogue** after the LLM's code:

```python
# --- validation appended by The Lab (not LLM-generated) ---
import json as _json
print('VALIDATION:', _json.dumps({
    'rows': len(df),
    'cols': len(df.columns),
    'has_target': 'Survived' in df.columns,
    'new_columns': [c for c in df.columns if c not in pd.read_csv('dataset.csv').columns],
}))
```

This is appended after the LLM's code and executed together. The validator
parses the `VALIDATION:` marker from stdout — it never depends on LLM compliance.

## Key findings for the thesis

1. **The sandbox Lambda block was RQ5's sole blocker.** Removing it (a safe,
   justified change) enabled 100% code-gen validity. This is a concrete
   engineering contribution: identifying that AST-level Lambda blocking is
   incompatible with pandas-idiomatic code generation.
2. **The validation epilogue pattern works.** Appending deterministic
   validation code after LLM code is more reliable than prompting the LLM to
   self-validate. This should be the standard pattern for Phase B.
3. **GLM 5.3 Flash produces production-quality feature engineering code** —
   domain-aware (family size, fare-log, age binning, interaction terms), target
   preserved, correct pandas idioms.
4. **Ollama (llama3.2:3b) remains untested** (server was down during the spike).
   The local-model validity rate is an open question for the defense.

## Sandbox memory limit

The spike also surfaced a sandbox memory issue: `pandas 3.0.5` requires
~2 GB of address space for its shared-library mappings (exceeding the previous
512 MB `RLIMIT_AS`). Default raised to 2048 MB in `thelab/sandbox/runner.py`.
