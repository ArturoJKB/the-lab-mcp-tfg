from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .context import cli as context_cli


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thelab",
        description="The Lab — local Data-to-Model Factory",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a pipeline")
    run_subparsers = run_parser.add_subparsers(dest="subcommand", required=True)

    model_parser = run_subparsers.add_parser("model", help="Train a model from a dataset")
    model_parser.add_argument("--dataset", required=True, help="Relative path to the dataset CSV")
    model_parser.add_argument("--target", required=True, help="Name of the target column")
    model_parser.add_argument("--model", required=True, help="Model name (e.g., logistic_regression)")
    model_parser.add_argument("--seed", required=True, type=int, help="Random seed")
    model_parser.add_argument("--output", required=True, help="Output directory (e.g., runs/)")
    model_parser.add_argument("--dry-run", action="store_true", help="Train in-memory and print metrics without persisting artifacts")
    model_parser.add_argument(
        "--task-type",
        choices=["auto", "classification", "regression"],
        default="auto",
        help="Task type (default: auto-infer from target column)",
    )
    model_parser.add_argument("--try-all", action="store_true", help="Train every registered model and print a comparison table")

    batch_parser = run_subparsers.add_parser("batch", help="Run a batch of experiments from a JSON config")
    batch_parser.add_argument("--config", required=True, help="Path to batch JSON config")
    batch_parser.add_argument("--output", required=True, help="Output directory (e.g., runs/)")
    batch_parser.add_argument("--report", help="Optional Markdown report path")

    inspect_parser = subparsers.add_parser("inspect", help="Quickly inspect a dataset without training")
    inspect_parser.add_argument("--dataset", required=True, help="Relative path to the dataset CSV")
    inspect_parser.add_argument("--target", help="Optional target column name")

    predict_parser = subparsers.add_parser("predict", help="Run a one-off prediction from an approved run")
    predict_parser.add_argument("--run-id", required=True, help="Run ID of the approved model")
    predict_parser.add_argument("--features", required=True, help="Feature row as comma-separated values or JSON list")
    predict_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    compare_parser = subparsers.add_parser("compare", help="Compare metrics across completed runs")
    compare_parser.add_argument("--output", default="runs", help="Directory containing run outputs")

    context_parser = subparsers.add_parser("context", help="Local context store commands")
    context_cli.build_parser_with_parent(context_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run" and args.subcommand == "model":
        from .run.runner import run_model, try_all_models

        try:
            if args.try_all:
                results = try_all_models(
                    dataset=args.dataset,
                    target=args.target,
                    seed=args.seed,
                    output=args.output,
                    workspace_root=Path.cwd(),
                    dry_run=args.dry_run,
                    task_type=args.task_type,
                )
                completed = [r for r in results if r["status"] == "completed"]
                print(f"\nTrained {len(results)} models, {len(completed)} completed.")
                print("| Model | Test Accuracy | Test F1 Macro |")
                print("|---|---|---|")
                for r in results:
                    metrics = r.get("metrics", {})
                    acc = f"{metrics.get('test_accuracy', 0):.6f}" if metrics.get("test_accuracy") is not None else "N/A"
                    f1 = f"{metrics.get('test_f1_macro', 0):.6f}" if metrics.get("test_f1_macro") is not None else "N/A"
                    status = "OK" if r["status"] == "completed" else r["status"]
                    print(f"| {r.get('model', 'unknown')} | {acc} | {f1} | ({status})")
                return 0 if completed else 1

            result = run_model(
                dataset=args.dataset,
                target=args.target,
                model=args.model,
                seed=args.seed,
                output=args.output,
                workspace_root=Path.cwd(),
                dry_run=args.dry_run,
                task_type=args.task_type,
            )
            return 0 if result["status"] == "completed" else 1
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "run" and args.subcommand == "batch":
        from .run.batch import BatchRunner, write_markdown_report

        try:
            runner = BatchRunner(workspace_root=Path.cwd())
            entries = runner.load_config(Path(args.config))
            batch_results = runner.run(entries, output=args.output)
            summary_path = Path(args.output) / "batch_summary.json"
            runner.write_summary(batch_results, summary_path)
            print(f"Batch summary written to: {summary_path}")
            if args.report:
                report_path = Path(args.report)
                write_markdown_report(batch_results, report_path)
                print(f"Batch report written to: {report_path}")
            return 0 if all(r.status == "completed" for r in batch_results) else 1
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "inspect":
        from .run.inspect import format_inspect, inspect_dataset

        try:
            result = inspect_dataset(Path(args.dataset), args.target)
            print(format_inspect(result))
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "predict":
        from .run.prediction import predict_cli

        try:
            return predict_cli(args.run_id, args.features, json_output=args.json)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "compare":
        from .run.compare import compare_runs, format_comparison

        try:
            runs = compare_runs(Path(args.output))
            print(format_comparison(runs))
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "context" and hasattr(args, "func"):
        func: Callable[[Any], int] = args.func
        try:
            return func(args)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
