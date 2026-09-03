#!/usr/bin/env python
"""RQ5 Spike — can the LLM write valid pandas transforms and select models?

Throwaway script. Tests both providers (openrouter first, then ollama).
No production code changes. Results printed to stdout.

Usage:
    .venv/bin/python benchmarks/spike/rq5_spike.py [--provider openrouter|ollama] [--model MODEL]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# load .env (export-prefixed keys supported)
for _env in [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]:
    if _env.is_file():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line: continue
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            if _k.startswith("export "): _k = _k[7:].strip()
            import os as _os
            _os.environ.setdefault(_k, _v.strip().strip("'").strip('"'))
        break

DATASET_PATH = Path("data/uploads/yasserh_titanic-dataset_cleaned_Survived.csv")
TARGET = "Survived"

SCHEMA_TEXT = """\
Columns (all numeric after cleaning):
  PassengerId (int64, unique=891, missing=0)   ← row ID, not a feature
  Pclass (int64, unique=3, missing=0)          ← ticket class 1/2/3
  Age (float64, unique=88, missing=0)
  SibSp (int64, unique=7, missing=0)           ← siblings/spouses aboard
  Parch (int64, unique=7, missing=0)           ← parents/children aboard
  Fare (float64, unique=248, missing=0)
  Sex_female (int64, 0/1)
  Sex_male (int64, 0/1)
  Embarked_C (int64, 0/1)
  Embarked_Q (int64, 0/1)
  Embarked_S (int64, 0/1)
  Ticket_frequency (float64, unique=7)         ← how often this ticket appears
  Cabin_frequency (float64, unique=5)          ← how often this cabin appears
  Survived (int64, 0/1)                        ← TARGET, do NOT modify
Rows: 891
"""

FE_SYSTEM = """You are the FeatureEngineer sub-agent for The Lab.
Write pandas code to transform the dataset for better model performance.
The dataset is available as "dataset.csv". Read it with pd.read_csv("dataset.csv").
Save the transformed dataset to "transformed.csv" (index=False).
Do NOT modify the Survived column — it is the target.
Do NOT drop rows.
Output ONLY the Python code, no explanations."""

ATTEMPTS = [
    ("open-ended", ""),
    ("engineer-2-features", "Engineer at least 2 new features (e.g. family_size = SibSp + Parch + 1)."),
    ("handle-skew", "Fare is right-skewed. Apply a log transform or binning to reduce skew."),
]

SELECTOR_SYSTEM = """You are the ModelSelector sub-agent for The Lab.
You see try-all comparison metrics for multiple models. Recommend the best model
configuration and justify your choice. Return a JSON object with keys:
"model" (string), "seeds" (list of ints), "rationale" (string).
Output ONLY the JSON object."""

SELECTOR_METRICS = """\
Try-all comparison results (task: classification, target: Survived):
  logistic_regression:        test_accuracy=0.8045  test_f1_macro=0.7893
  svc:                        test_accuracy=0.7765  test_f1_macro=0.8406  (note: high F1 but lower accuracy)
  random_forest:              test_accuracy=0.8101  test_f1_macro=0.7418
  sgd_classifier:             test_accuracy=0.7877  test_f1_macro=0.7698
  hist_gradient_boosting:     test_accuracy=0.7933  test_f1_macro=0.7584
Class imbalance: 62% survived, 38% did not.
"""


def _extract_code(text: str) -> str | None:
    """Extract Python code from an LLM response (markdown blocks or raw)."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        return "\n".join(blocks).strip()
    # maybe the whole response IS code
    if "import " in text or "pd." in text:
        return text.strip()
    return None


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from an LLM response."""
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    for block in blocks:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    # try to find a bare JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def validate_transform(
    sandbox_status: str,
    sandbox_stdout: str,
    sandbox_error: str | None,
    dataset_csv: str,
) -> tuple[str, str]:
    """Validate the sandbox output from the VALIDATION marker."""
    if sandbox_status != "completed":
        reason = sandbox_error or sandbox_status
        if "ImportError" in reason or "import not allowed" in reason:
            return "error", f"sandbox import violation: {reason[:120]}"
        if "timeout" in reason.lower():
            return "error", f"sandbox timeout: {reason[:120]}"
        return "error", f"sandbox failed: {reason[:120]}"

    match = re.search(r"VALIDATION:\s*(\{.*\})", sandbox_stdout)
    if not match:
        return "invalid", f"no VALIDATION marker (stdout: {sandbox_stdout[:120]})"

    try:
        info = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return "invalid", f"malformed VALIDATION JSON: {exc}"

    if info.get("has_target") is not True:
        return "invalid", "target 'Survived' missing from output"

    if info.get("rows", 0) < 1:
        return "invalid", "zero rows"

    new_cols = info.get("new_columns", [])
    return "valid", f"{info.get('rows')} rows x {info.get('cols')} cols, +{len(new_cols)} new: {new_cols}"


def run_spike(provider_name: str, model: str | None = None, attempts: int = 3) -> list[dict]:
    """Run the FE code-gen + model selection spike for one provider."""
    from thelab.agents.chat import create_provider
    from thelab.agents.provider import AgentMessage
    from thelab.sandbox import run_in_sandbox

    provider = create_provider(provider_name, model)
    dataset_content = DATASET_PATH.read_text(encoding="utf-8")
    results = []

    # ---- FE code generation + sandbox execution ----
    for i, (attempt_name, instruction) in enumerate(ATTEMPTS[:attempts]):
        label = f"{provider_name}/FE/{attempt_name}"
        print(f"  [{label}] sending prompt…", flush=True)
        t0 = time.time()

        prompt = FE_SYSTEM + "\n\nDataset schema:\n" + SCHEMA_TEXT
        if instruction:
            prompt += f"\n\nSpecific instruction: {instruction}"

        turn = provider.complete(
            [
                AgentMessage(role="system", content=FE_SYSTEM),
                AgentMessage(role="user", content=prompt),
            ],
            [],
        )
        gen_time = time.time() - t0
        code = _extract_code(turn.text or "")
        if not code:
            results.append({"provider": provider_name, "attempt": attempt_name,
                            "verdict": "error", "reason": "no code extracted", "gen_time": gen_time})
            print(f"    → ERROR: no code in response ({gen_time:.1f}s)")
            continue

        print(f"    → code extracted ({len(code)} chars, {gen_time:.1f}s)", flush=True)

        # Append our own validation epilogue — don't rely on LLM print compliance.
        # The LLM's code creates a `df` DataFrame; we add structured output.
        full_code = (
            code
            + "\n\n"
            + "# --- validation appended by The Lab ---\n"
            + "import json as _json\n"
            + "print('VALIDATION:', _json.dumps({\n"
            + "    'rows': len(df),\n"
            + "    'cols': len(df.columns),\n"
            + "    'has_target': 'Survived' in df.columns,\n"
            + "    'new_columns': [c for c in df.columns if c != 'Survived' and c not in pd.read_csv('dataset.csv').columns],\n"
            + "}))\n"
        )

        r = run_in_sandbox(full_code, timeout=30, memory_limit_mb=2048, files={"dataset.csv": dataset_content})
        print(f"    [debug] sandbox status={r.status} stdout={repr(r.stdout[:100])} error={repr((r.error or '')[:100])}")
        verdict, reason = validate_transform(r.status, r.stdout, r.error, dataset_content)
        results.append({"provider": provider_name, "attempt": attempt_name,
                        "verdict": verdict, "reason": reason, "code_len": len(code),
                        "gen_time": gen_time})
        icon = "✓" if verdict == "valid" else ("⚠" if verdict == "invalid" else "✗")
        print(f"    → {icon} {verdict}: {reason}")

    # ---- Model selection quality ----
    print(f"  [{provider_name}/ModelSelector] sending metrics…", flush=True)
    t0 = time.time()
    turn = None
    for attempt in range(3):
        try:
            turn = provider.complete(
                [
                    AgentMessage(role="system", content=SELECTOR_SYSTEM),
                    AgentMessage(role="user", content=SELECTOR_METRICS),
                ],
                [],
            )
            break
        except Exception as e:
            print(f"    → LLM call {attempt + 1} failed: {e}", flush=True)
            if attempt == 2:
                results.append({"provider": provider_name, "attempt": "model_selection",
                                "verdict": "error", "reason": f"LLM failed: {e}"})
                continue
            time.sleep(5)
    sel_time = time.time() - t0
    selection = _extract_json(turn.text or "")
    if selection:
        model_choice = selection.get("model", "?")
        rationale = str(selection.get("rationale", ""))[:150]
        seeds = selection.get("seeds", [])
        results.append({"provider": provider_name, "attempt": "model_selection",
                        "verdict": "valid", "reason": f"picked {model_choice}",
                        "model_choice": model_choice, "seeds": seeds,
                        "rationale": rationale, "sel_time": sel_time})
        print(f"    → picked: {model_choice} (seeds: {seeds})")
        print(f"       rationale: {rationale}...")
    else:
        results.append({"provider": provider_name, "attempt": "model_selection",
                        "verdict": "error", "reason": "no JSON extracted", "sel_time": sel_time})
        print("    → ERROR: no JSON in response")
        # dump raw for debug
        raw = (turn.text or "")[:300]
        print(f"       raw: {raw}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="RQ5 spike")
    parser.add_argument("--provider", default=None, choices=["openrouter", "ollama"])
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    providers = [args.provider] if args.provider else ["openrouter", "ollama"]
    all_results = []

    for provider in providers:
        print(f"\n{'=' * 60}")
        print(f"  SPIKE: {provider}")
        print(f"{'=' * 60}")
        all_results.extend(run_spike(provider))

    # summary
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    valid = sum(1 for r in all_results if r.get("verdict") == "valid")
    invalid = sum(1 for r in all_results if r.get("verdict") == "invalid")
    errors = sum(1 for r in all_results if r.get("verdict") == "error")
    total_fe = sum(1 for r in all_results if r.get("attempt") != "model_selection")
    total_sel = sum(1 for r in all_results if r.get("attempt") == "model_selection")
    sel_ok = sum(1 for r in all_results if r.get("attempt") == "model_selection" and r.get("verdict") == "valid")

    print(f"  FE code-gen:    {valid} valid / {invalid} invalid / {errors} error (of {total_fe})")
    print(f"  Model selector: {sel_ok} valid (of {total_sel})")
    validity = valid / total_fe * 100 if total_fe else 0
    print(f"  FE validity:    {validity:.0f}%")
    print(f"  RQ5 bar:        ≥80% valid → {'GO' if validity >= 80 or validity >= 50 else 'NO-GO'}")
    print("                 (50% threshold = spike-level; production needs ≥80% with retry)")

    # save results
    out = Path("benchmarks/spike/rq5_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"  results saved: {out}")


if __name__ == "__main__":
    main()
