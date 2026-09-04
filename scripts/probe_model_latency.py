#!/usr/bin/env python3
"""Probe OpenRouter model latency for the P6 live runs (P6.D evidence).

Measures p50/p90 completion latency per candidate model with a trivial
prompt (5 calls each), so the cheap model to standardize on for P6.A live
runs is chosen from data, not anecdote. Results land in
``thesis/evidence/raw/latency_probe_<name>.json`` and become a
provider-comparison table via ``scripts/thesis/generate_evidence.py``.

Free tiers can be rate-limited or queued — the probe measures the route,
not the brochure. Token cost: ~25 trivial completions total.

Usage:
    python scripts/probe_model_latency.py                 # probe all candidates
    python scripts/probe_model_latency.py --calls 3 --models a,b
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# (model_id, label, tier) — tier: free | paid. Ids validated against the
# OpenRouter catalog 2026-09-04 (stale ids return HTTP 404).
CANDIDATES: list[tuple[str, str, str]] = [
    ("z-ai/glm-5.3-flash", "GLM 5.3 Flash (baseline)", "paid"),
    ("deepseek/deepseek-v4-flash-0731", "DeepSeek V4 Flash (paid)", "paid"),
    ("google/gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite (paid)", "paid"),
    ("minimax/minimax-m2.7:free", "MiniMax M2.7 (free)", "free"),
    ("google/gemma-4-31b-it:free", "Gemma 4 31B (free)", "free"),
]

_CALL_TIMEOUT_S = 60.0


def _api_key() -> str | None:
    from thelab.env import load_dotenv

    load_dotenv()
    key = os.environ.get("THELAB_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    return key or None


def _probe_model(
    model: str, calls: int, api_key: str, base_url: str, realistic: bool = False
) -> dict[str, Any]:
    import httpx

    latencies: list[float] = []
    tokens: list[int] = []
    errors: list[str] = []
    for i in range(calls):
        if realistic:
            # Mirrors round-stage calls: a structured JSON brief (~300 tokens).
            content = (
                "You are an ML analyst. Given the EDA context '4 numeric features, "
                "3 balanced classes, top baseline logistic_regression (accuracy 0.85)', "
                "produce a JSON object with keys findings, opportunities, risks "
                "(each a list of 2 short strings). Reply with JSON only."
            )
            max_tokens = 400
        else:
            content = "Reply with exactly: ok"
            max_tokens = 16
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }
        t0 = time.monotonic()
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=60.0,
            )
            latency = time.monotonic() - t0
            latencies.append(round(latency, 3))
            if response.status_code != 200:
                errors.append(f"call {i + 1}: HTTP {response.status_code}")
                continue
            data = response.json()
            usage = data.get("usage") or {}
            tokens.append(int(usage.get("completion_tokens") or 0))
        except Exception as exc:  # noqa: BLE001 - probe records, never raises
            latencies.append(round(time.monotonic() - t0, 2))
            errors.append(f"{type(exc).__name__}: {exc}"[:120])
        time.sleep(1.0)

    ordered = sorted(latencies)

    def pct(p: float) -> float | None:
        if not ordered:
            return None
        return ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))]

    mode = "realistic" if realistic else "trivial"
    return {
        "model": model,
        "mode": mode,
        "calls": calls,
        "ok": len(latencies) - len(errors),
        "latencies_s": latencies,
        "p50_s": ordered[len(ordered) // 2] if ordered else None,
        "p90_s": pct(0.9),
        "mean_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "completion_tokens_avg": (
            round(sum(tokens) / len(tokens), 1) if tokens else None
        ),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    import httpx  # noqa: F401 - fail fast if missing

    parser = argparse.ArgumentParser(description="Probe OpenRouter model latency")
    parser.add_argument("--calls", type=int, default=5, help="Completions per model")
    parser.add_argument(
        "--models", default=None, help="Comma-separated subset of candidate ids"
    )
    parser.add_argument(
        "--realistic",
        action="store_true",
        help="Probe with a ~300-token structured generation (mirrors round stages)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "thesis" / "evidence" / "raw",
        help="Where to write the probe snapshot",
    )
    args = parser.parse_args(argv)

    api_key = _api_key()
    if not api_key:
        print("error: set THELAB_LLM_API_KEY (or OPENROUTER_API_KEY) in .env", file=sys.stderr)
        return 1
    base_url = os.environ.get("THELAB_LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    if "openrouter" not in base_url:
        # Allow explicit override but warn: probes target the OpenRouter route.
        print(f"note: probing base_url {base_url}", file=sys.stderr)

    candidates = CANDIDATES
    if args.models:
        wanted = set(args.models.split(","))
        candidates = [c for c in CANDIDATES if c[0] in wanted]

    probes = []
    for model, label, tier in candidates:
        print(f"probing {model} ({tier})...", flush=True)
        result = _probe_model(
            model, max(1, args.calls), api_key, base_url, realistic=args.realistic
        )
        result["label"] = label
        result["tier"] = tier
        probes.append(result)
        print(
            f"  ok={result['ok']}/{result['calls']}  p50={result.get('p50_s')}s  "
            f"errors={len(result['errors'])}",
            flush=True,
        )

    snapshot = {
        "probe": "openrouter_latency" + ("_realistic" if args.realistic else ""),
        "mode": "realistic" if args.realistic else "trivial",
        "base_url": base_url,
        "calls_per_model": args.calls,
        "probes": probes,
    }
    out_path = Path(args.out)
    out_path.mkdir(parents=True, exist_ok=True)
    suffix = "_realistic" if args.realistic else ""
    dest = out_path / f"latency_probe_openrouter{suffix}.json"
    dest.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    print(f"snapshot: {dest}")

    ranked = sorted(
        (p for p in probes if p.get("p50_s") is not None), key=lambda p: p["p50_s"]
    )
    print("\nranked by p50 latency:")
    for p in ranked:
        print(f"  {p['p50_s']:>6}s  {p['tier']:>4}  {p['model']}  ({p['ok']}/{p['calls']} ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
