#!/usr/bin/env python3
"""Generate thesis evidence artifacts (LaTeX tables + vector figures) from
recorded data.

P6.D.0 — every artifact is produced by this committed script from recorded
JSON snapshots in ``thesis/evidence/raw/``. Re-running is byte-stable: no
timestamps inside artifacts, deterministic matplotlib output. Provenance per
artifact is written to ``thesis/evidence/MANIFEST.md`` (artifact -> source ->
generator). The thesis chapters consume the tables via ``\\input``.

Usage:
    python scripts/thesis/generate_evidence.py                # regenerate all
    python scripts/thesis/generate_evidence.py --from-log <log> --name <id>
                                                              # new evaluator log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW = REPO_ROOT / "thesis" / "evidence" / "raw"
DEFAULT_OUT = REPO_ROOT / "thesis" / "evidence"

# OKabe-Ito colorblind-safe palette
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]


# ---------------------------------------------------------------------------
# Input classification
# ---------------------------------------------------------------------------

def is_evaluator_report(data: dict[str, Any]) -> bool:
    return isinstance(data.get("mode"), str) and isinstance(data.get("results"), list)


def is_round_record(data: dict[str, Any]) -> bool:
    return "round_id" in data and "experiment_id" in data


def extract_report_from_log(log_text: str) -> dict[str, Any] | None:
    """Pull the final JSON report out of an evaluator console log."""
    marker = '{\n  "mode"'
    idx = log_text.rfind(marker)
    if idx < 0:
        return None
    try:
        return json.loads(log_text[idx:])
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Booktabs emission
# ---------------------------------------------------------------------------

def _label_safe(text: str) -> str:
    """Labels must be plain tokens (no TeX escapes): keep [A-Za-z0-9-]."""
    return re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-")


def _tex_escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("#", "\\#")
    )


def _booktabs_table(
    caption: str, label: str, header: list[str], rows: list[list[str]]
) -> str:
    """Emit a standalone booktabs table float ready for \\input."""
    col_spec = "l" * len(header)
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        f"\\caption{{{_tex_escape(caption)}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{col_spec}}}",
        "\\toprule",
        " & ".join(header) + " \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(_tex_escape(cell) for cell in row) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Table 1: RQ x dataset evaluation matrix
# ---------------------------------------------------------------------------

def _key_result(result: dict[str, Any]) -> str:
    """Compact human-readable highlight per check (for the matrix table)."""
    if result.get("status") != "PASS":
        return str(result.get("reason", ""))[:40]
    if "validity_rate" in result:
        total = result.get("agentic_total")
        return f"validity {result['validity_rate']} ({result.get('agentic_completed', '?')}/{total})"
    if "grounded_verified_rate" in result:
        return (
            f"grounded {result['grounded_verified_rate']}"
            f" vs ungrounded {result.get('ungrounded_verified_rate')}"
        )
    if result.get("multi_mode"):
        return f"multi: {result['multi_mode']} / single: {result['single_mode']}"
    if result.get("metrics"):
        metrics = result["metrics"]
        return ", ".join(
            f"{k}={v:.4f}" if isinstance(v, (int, float)) else f"{k}={v}"
            for k, v in list(metrics.items())[:2]
        )
    if result.get("predictions") is not None:
        return f"predictions: {result['predictions'][:2]}"
    if result.get("hits") is not None:
        return f"hits: {result['hits']}"
    return ""


def build_rq_matrix(report: dict[str, Any], source_stem: str) -> str:
    source_mode = report.get("mode", "")
    rows: list[list[str]] = []
    for result in report["results"]:
        rq = result["rq"]
        dataset = "—"
        for name in ("iris", "housing"):
            if f"[{name}]" in rq:
                dataset = name
                rq = rq.split("[", 1)[0]
                break
        rows.append([rq, dataset, result["status"], _key_result(result)])
    caption = (
        f"RQ1--RQ6 evaluation matrix ({_tex_escape(source_mode)}). "
        "Agentic checks RQ4--RQ6 run per dataset arm; RQ3 is dataset-independent."
    )
    return _booktabs_table(
        caption,
        f"tab:rq-matrix-{_label_safe(source_stem)}",
        ["RQ", "Dataset", "Verdict", "Key result"],
        rows,
    )


# ---------------------------------------------------------------------------
# Table 2: agentic vs deterministic comparison (round records)
# ---------------------------------------------------------------------------

def _round_comparison_rows(data: dict[str, Any]) -> list[list[str]] | None:
    comparison = (data.get("execution") or {}).get("comparison") or {}
    if not comparison:
        return None
    det = (comparison.get("deterministic_best") or {}).get("metrics") or {}
    ag = (comparison.get("agentic_best") or {}).get("metrics") or {}
    delta = comparison.get("metric_delta") or {}
    if "test_accuracy" in delta:
        metric, det_v, ag_v, d = (
            "accuracy",
            det.get("test_accuracy"),
            ag.get("test_accuracy"),
            delta["test_accuracy"],
        )
    elif "test_rmse" in delta:
        metric, det_v, ag_v, d = (
            "RMSE",
            det.get("test_rmse"),
            ag.get("test_rmse"),
            delta["test_rmse"],
        )
    else:
        return None

    def fmt(value: Any) -> str:
        return f"{float(value):.4f}" if value is not None else "--"

    round_id = data.get("round_id", "round")
    mode = data.get("mode", "")
    return [
        [
            str(round_id),
            str(data.get("experiment_id", "")),
            metric,
            fmt(det_v),
            fmt(ag_v),
            f"{d:+.4f}",
            str(comparison.get("validity_rate")),
            str(mode),
        ]
    ]


def build_agentic_comparison(rounds: list[dict[str, Any]]) -> str:
    rows: list[list[str]] = []
    for data in rounds:
        rows.extend(_round_comparison_rows(data) or [])
    caption = (
        "Agentic round vs deterministic baseline per recorded journey. "
        "Delta is agentic minus deterministic on the headline metric; validity "
        "is the fraction of agentic batch entries that completed training."
    )
    return _booktabs_table(
        caption,
        "tab:agentic-comparison",
        ["Round", "Experiment", "Metric", "Det.", "Agentic", "Delta", "Validity", "Mode"],
        rows,
    )


# ---------------------------------------------------------------------------
# Figure: validity story (pre/post fix + journeys)
# ---------------------------------------------------------------------------

def collect_validity_points(
    reports: list[dict[str, Any]], rounds: list[dict[str, Any]]
) -> list[tuple[str, float]]:
    """(label, validity_rate) points across all recorded sources."""
    points: list[tuple[str, float]] = []
    for report in reports:
        for result in report["results"]:
            if result["rq"].startswith("RQ5") and result.get("validity_rate") is not None:
                label = f"{result['rq']} ({report.get('mode', '')[:20]})"
                points.append((label, float(result["validity_rate"])))
    for data in rounds:
        comparison = (data.get("execution") or {}).get("comparison") or {}
        if comparison.get("validity_rate") is not None:
            points.append(
                (f"journey {data.get('experiment_id', '')[-8:]}",
                 float(comparison["validity_rate"]))
            )
    return points


def build_validity_figure(points: list[tuple[str, float]], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    labels = [p[0] for p in points]
    values = [p[1] for p in points]
    colors = ["#D55E00" if v < 0.5 else "#0072B2" for v in values]
    fig, ax = plt.subplots(figsize=(6.0, 2.8))
    bars = ax.barh(range(len(values)), values, color=colors, height=0.55)
    ax.set_yticks(range(len(values)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Agentic batch validity rate (completed / total)")
    for bar, value in zip(bars, values, strict=True):
        ax.text(value + 0.02, bar.get_y() + bar.get_height() / 2, f"{value:.2f}", va="center")
    fig.tight_layout()
    fig.savefig(
        out_path,
        format="pdf",
        metadata={"CreationDate": None, "ModDate": None, "Creator": "", "Producer": ""},
    )
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate thesis evidence artifacts")
    parser.add_argument(
        "--raw-dir", type=Path, default=DEFAULT_RAW, help="Directory of recorded JSON snapshots"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="Output directory (thesis/evidence)"
    )
    parser.add_argument(
        "--from-log",
        type=Path,
        default=None,
        help="Optional evaluator console log: extract its JSON report into --raw-dir first",
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help="Snapshot name for --from-log (default: evaluator log file stem)",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    raw_dir = args.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.from_log is not None:
        report = extract_report_from_log(args.from_log.read_text(encoding="utf-8"))
        if report is None:
            print(f"no JSON report found in {args.from_log}", file=sys.stderr)
            return 1
        name = args.source_name or args.from_log.stem
        (raw_dir / f"{name}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"snapshot: {raw_dir / (name + '.json')}")

    reports: list[tuple[str, dict[str, Any]]] = []
    rounds: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"skipping malformed snapshot: {path}", file=sys.stderr)
            continue
        if is_evaluator_report(data):
            reports.append((path.stem, data))
        elif is_round_record(data):
            rounds.append((path.stem, data))

    manifest: list[str] = [
        "# Thesis Evidence Manifest",
        "",
        "Every artifact below is generated by `scripts/thesis/generate_evidence.py`",
        "from the recorded JSON snapshots in `raw/`. Re-running the script is",
        "byte-stable. Chapters consume tables via `\\input{evidence/<file>}`.",
        "",
    ]

    for stem, report in reports:
        tex = build_rq_matrix(report, stem)
        out_file = args.out / f"rq_matrix_{stem}.tex"
        out_file.write_text(tex, encoding="utf-8")
        manifest += [
            f"- `rq_matrix_{stem}.tex` — table `tab:rq-matrix-{stem}` from `raw/{stem}.json`"
            f" (evaluator mode: `{report.get('mode', '')}`).",
        ]

    comparison_tex = build_agentic_comparison([data for _, data in rounds])
    if rounds:
        (args.out / "agentic_comparison.tex").write_text(comparison_tex, encoding="utf-8")
        manifest += [
            "- `agentic_comparison.tex` — table `tab:agentic-comparison` from "
            + ", ".join(f"`raw/{stem}.json`" for stem, _ in rounds)
            + ".",
        ]

    points = collect_validity_points([data for _, data in reports], [data for _, data in rounds])
    if points:
        fig_path = args.out / "validity_rates.pdf"
        build_validity_figure(points, fig_path)
        manifest += [
            "- `validity_rates.pdf` — figure from the validity rates of all recorded"
            " RQ5 results and journeys (orange = below 0.5).",
        ]

    (args.out / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"evidence generated in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
