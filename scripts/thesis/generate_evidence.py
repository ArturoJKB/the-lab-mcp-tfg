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


def is_latency_probe(data: dict[str, Any]) -> bool:
    return isinstance(data.get("probe"), str) and isinstance(data.get("probes"), list)


def is_generation_ledger(data: dict[str, Any]) -> bool:
    return isinstance(data.get("slug"), str) and isinstance(data.get("generations"), list)


def is_model_comparison(data: dict[str, Any]) -> bool:
    return isinstance(data.get("dataset"), str) and isinstance(data.get("rows"), list) and isinstance(data.get("baseline"), dict)


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


def build_latency_table(snapshot: dict[str, Any], source_stem: str) -> str:
    rows: list[list[str]] = []
    for probe in snapshot["probes"]:
        rows.append(
            [
                probe.get("model", ""),
                probe.get("tier", ""),
                str(probe.get("ok", 0)) + "/" + str(probe.get("calls", 0)),
                _fmt_s(probe.get("p50_s")),
                _fmt_s(probe.get("p90_s")),
                _fmt_s(probe.get("mean_s")),
                str(probe.get("completion_tokens_avg") or "--"),
            ]
        )
    caption = (
        f"Model latency probe ({_tex_escape(snapshot.get('mode', 'trivial'))} "
        "generation, " + _tex_escape(source_stem) + "). p50/p90 completion "
        "latency in seconds; round-stage calls are generation-length-bound, so "
        "trivial-ping latency alone underestimates round cost."
    )
    return _booktabs_table(
        caption,
        f"tab:latency-{_label_safe(source_stem)}",
        ["Model", "Tier", "OK", "p50 (s)", "p90 (s)", "mean (s)", "avg out tokens"],
        rows,
    )


def _fmt_s(value: Any) -> str:
    return f"{float(value):.2f}" if isinstance(value, (int, float)) else "--"


# ---------------------------------------------------------------------------
# Ratchet ledger: generation + per-round capability tables
# ---------------------------------------------------------------------------

def build_model_comparison_table(data: dict[str, Any], source_stem: str) -> str:
    baseline = data.get("baseline") or {}
    base_model = baseline.get("model", "")
    base_val = baseline.get("test_accuracy")
    rows: list[list[str]] = []
    for r in data.get("rows") or []:
        model = str(r.get("model", "")).split("/")[-1][:30]
        if model.startswith("{"):
            model = "mixed team"
        delta = r.get("delta_vs_baseline")
        rows.append(
            [
                str(r.get("configuration", "")),
                model,
                str(r.get("mode", "")),
                _fmt_v(r.get("validity_rate")),
                _fmt_v(r.get("best_test_accuracy")),
                f"{float(delta):+.4f}" if isinstance(delta, (int, float)) else "--",
                "yes" if r.get("absorbed") else "no",
            ]
        )
    caption = (
        f"Model comparison on {_tex_escape(data['dataset'])}: deterministic "
        f"try-all baseline {_tex_escape(base_model)} {_fmt_v(base_val)} vs "
        "agentic team configurations. Delta = agentic best minus baseline."
    )
    return _booktabs_table(
        caption,
        f"tab:model-comparison-{_label_safe(source_stem)}",
        ["Config", "Model", "Mode", "Validity", "Best acc", "Delta", "Absorbed"],
        rows,
    )


def _fmt_v(value: Any) -> str:
    return f"{float(value):.4f}" if isinstance(value, (int, float)) else "--"


def _round_rows(ledger: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for gen_index, generation in enumerate(ledger.get("generations") or []):
        for cell in generation.get("cells") or []:
            for r in cell.get("rounds") or []:
                best = r.get("agentic_best") or {}
                metrics = best.get("metrics") or {}
                best_metric = metrics.get("test_accuracy", metrics.get("test_r2"))
                rows.append(
                    [
                        f"g{gen_index} r{r.get('round', '-')}",
                        str(r.get("provider", "")),
                        str(r.get("model", ""))[:34],
                        str(r.get("mode", "")),
                        _fmt_v(r.get("validity_rate")),
                        f"{r.get('agentic_completed', '-')}/{r.get('agentic_total', '-')}",
                        (
                            f"{best.get('model')} {_fmt_v(best_metric)}"
                            if best.get("model")
                            else "--"
                        ),
                    ]
                )
    return rows


def build_ratchet_generation_table(ledger: dict[str, Any], source_stem: str) -> str:
    rows: list[list[str]] = []
    for gen_index, generation in enumerate(ledger.get("generations") or []):
        base = generation.get("baseline") or {}
        base_metrics = base.get("metrics") or {}
        base_value = base_metrics.get("test_accuracy", base_metrics.get("test_r2"))
        absorption = generation.get("absorption") or {}
        champion = absorption.get("champion") or {}
        validities = []
        best_model, best_value = None, None
        for cell in generation.get("cells") or []:
            for r in cell.get("rounds") or []:
                if r.get("validity_rate") is not None:
                    validities.append(f"{float(r['validity_rate']):.2f}")
                best = r.get("agentic_best") or {}
                metrics = best.get("metrics") or {}
                value = metrics.get("test_accuracy", metrics.get("test_r2"))
                if value is not None and (
                    best_value is None or float(value) > float(best_value)
                ):
                    best_value, best_model = float(value), best.get("model")
        hp = champion.get("hyperparameters") or {}
        champion_cfg = (
            f"{champion.get('model')} s{champion.get('seed')}"
            + (" " + " ".join(f"{k}={v}" for k, v in list(hp.items())[:2]) if hp else "")
            if champion
            else "--"
        )
        rows.append(
            [
                f"g{gen_index}",
                f"{base.get('model')} {_fmt_v(base_value)}",
                f"{best_model} {_fmt_v(best_value)}" if best_model else "--",
                (
                    f"{float(absorption['delta']):+.4f}"
                    if isinstance(absorption.get("delta"), (int, float))
                    else "--"
                ),
                "/".join(validities) or "--",
                str(absorption.get("absorbed", False)),
                champion_cfg,
            ]
        )
    caption = (
        "Ratchet loop per generation: deterministic try-all baseline vs best "
        "agentic round; absorption requires the champion config to replay "
        "exactly through the deterministic factory (same seed)."
    )
    return _booktabs_table(
        caption,
        f"tab:ratchet-generations-{_label_safe(source_stem)}",
        ["Gen", "Baseline", "Agentic best", "Delta", "Validity", "Absorbed", "Champion"],
        rows,
    )


def build_ratchet_rounds_table(ledger: dict[str, Any], source_stem: str) -> str:
    caption = (
        "Per-round capability matrix for the ratchet loop: which provider/model "
        "produced valid, factory-safe agentic rounds (per-stage capability "
        "discovery)."
    )
    return _booktabs_table(
        caption,
        f"tab:ratchet-rounds-{_label_safe(source_stem)}",
        ["Gen/round", "Provider", "Model", "Mode", "Validity", "Entries", "Best"],
        _round_rows(ledger),
    )


# ---------------------------------------------------------------------------
# Table 1: RQ x dataset evaluation matrix
# ---------------------------------------------------------------------------

def collect_validity_points(
    reports: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    ledgers: list[dict[str, Any]] | None = None,
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
    for ledger in ledgers or []:
        for gen_index, generation in enumerate(ledger.get("generations") or []):
            for cell in generation.get("cells") or []:
                for r in cell.get("rounds") or []:
                    if r.get("validity_rate") is not None:
                        points.append(
                            (
                                f"ratchet {ledger['slug']} g{gen_index}r{r.get('round', '-')}",
                                float(r["validity_rate"]),
                            )
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
    probes: list[tuple[str, dict[str, Any]]] = []
    ledgers: list[tuple[str, dict[str, Any]]] = []
    comparisons: list[tuple[str, dict[str, Any]]] = []
    rounds: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"skipping malformed snapshot: {path}", file=sys.stderr)
            continue
        if is_evaluator_report(data):
            reports.append((path.stem, data))
        elif is_latency_probe(data):
            probes.append((path.stem, data))
        elif is_generation_ledger(data):
            ledgers.append((path.stem, data))
        elif is_model_comparison(data):
            comparisons.append((path.stem, data))
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

    for stem, probe in probes:
        tex = build_latency_table(probe, stem)
        out_file = args.out / f"model_latency_{stem}.tex"
        out_file.write_text(tex, encoding="utf-8")
        manifest += [
            f"- `model_latency_{stem}.tex` — table `tab:latency-{_label_safe(stem)}`"
            f" from `raw/{stem}.json` (probe mode: `{probe.get('mode', '')}`).",
        ]

    for stem, ledger in ledgers:
        gen_tex = build_ratchet_generation_table(ledger, stem)
        (args.out / f"ratchet_generations_{stem}.tex").write_text(gen_tex, encoding="utf-8")
        rounds_tex = build_ratchet_rounds_table(ledger, stem)
        (args.out / f"ratchet_rounds_{stem}.tex").write_text(rounds_tex, encoding="utf-8")
        manifest += [
            f"- `ratchet_generations_{stem}.tex` — table `tab:ratchet-generations-{_label_safe(stem)}`"
            f" + `ratchet_rounds_{stem}.tex` (`tab:ratchet-rounds-{_label_safe(stem)}`)"
            f" from `raw/{stem}.json` (ratchet loop ledger).",
        ]

    for stem, data in comparisons:
        tex = build_model_comparison_table(data, stem)
        (args.out / f"model_comparison_{stem}.tex").write_text(tex, encoding="utf-8")
        manifest += [
            f"- `model_comparison_{stem}.tex` — table `tab:model-comparison-{_label_safe(stem)}`"
            f" from `raw/{stem}.json` ({len(data.get('rows', []))} configurations).",
        ]

    comparison_tex = build_agentic_comparison([data for _, data in rounds])
    if rounds:
        (args.out / "agentic_comparison.tex").write_text(comparison_tex, encoding="utf-8")
        manifest += [
            "- `agentic_comparison.tex` — table `tab:agentic-comparison` from "
            + ", ".join(f"`raw/{stem}.json`" for stem, _ in rounds)
            + ".",
        ]

    points = collect_validity_points(
        [data for _, data in reports],
        [data for _, data in rounds],
        [data for _, data in ledgers],
    )
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
