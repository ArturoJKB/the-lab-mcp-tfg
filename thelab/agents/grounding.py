"""Shared grounding primitives for agent surfaces.

One implementation for run-id and metric-claim verification so the extraction
rules and tolerance cannot drift between the harness, chat agent, and global
agents. A claim is *grounded* only when every cited run_id exists and every
metric claim matches the corresponding metrics.json within tolerance.
"""

from __future__ import annotations

import re
from typing import Any

RUN_ID_RE = re.compile(r"run-\d{8}-\d{6}-[0-9a-f]{8}")

METRIC_KEYS = [
    "test_accuracy",
    "test_f1_macro",
    "train_accuracy",
    "train_f1_macro",
    "test_rmse",
    "test_mae",
    "test_r2",
    "train_rmse",
    "train_mae",
    "train_r2",
]

METRIC_TOLERANCE = 1e-3


def extract_run_ids(text: str) -> list[str]:
    """Return all run-id-like substrings found in *text*."""
    return RUN_ID_RE.findall(text)


def extract_metric_claims(text: str) -> dict[str, float]:
    """Scan *text* for numeric claims tied to known metric keys."""
    claims: dict[str, float] = {}
    for key in METRIC_KEYS:
        pattern = rf"{re.escape(key)}" + r"[^0-9\n]{0,30}(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
        match = re.search(pattern, text)
        if match:
            try:
                claims[key] = float(match.group(1))
            except ValueError:
                continue
    return claims


def metric_mismatches(text: str, metrics: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Return ``{key: (claimed, actual)}`` for claims contradicting *metrics*.

    Keys absent from *metrics* are ignored (unknown-metric claims are not
    verifiable here and are handled by the callers' citation policies).
    """
    mismatches: dict[str, tuple[float, float]] = {}
    for key, claimed in extract_metric_claims(text).items():
        actual = metrics.get(key)
        if isinstance(actual, (int, float)) and abs(claimed - float(actual)) > METRIC_TOLERANCE:
            mismatches[key] = (claimed, float(actual))
    return mismatches
