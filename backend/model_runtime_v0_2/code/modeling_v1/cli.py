"""Command-line entry points for verify/train/evaluate run lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import (
    DEFAULT_SEED,
    ENRICHED_FEATURE_COLUMNS,
    MODEL_FEATURE_COLUMNS,
    RunSpec,
    build_run_matrix,
    task_spec,
)
from .data import V04TaskSource, verify_package_layout
from .training import train_run, train_run_rolling, verify_run


def _parse_run_selector(args) -> RunSpec:
    spec = task_spec(args.task_id, args.variant)
    return RunSpec(task=spec, horizon_days=args.horizon_days, seed=args.seed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taihu modeling V1 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--data", required=True)
    verify.add_argument("--runs", nargs="*", default=[])

    train = subparsers.add_parser("train")
    train.add_argument("--data", required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--task-id", required=True)
    train.add_argument("--variant", required=True)
    train.add_argument("--horizon-days", type=int, required=True)
    train.add_argument("--seed", type=int, default=20260907)
    train.add_argument("--stop-after", choices=("selection", "full"), default="full")
    train.add_argument("--history-days", type=int, default=0)
    train.add_argument("--sample-rows", type=int, default=200_000)
    train.add_argument("--max-train-rows", type=int, default=200_000)
    train.add_argument("--max-validation-rows", type=int, default=100_000)
    train.add_argument("--max-test-rows", type=int, default=100_000)
    train.add_argument("--rolling", action="store_true")

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--runs", nargs="*", required=True)

    matrix = subparsers.add_parser("run-matrix")
    matrix.add_argument("--data", required=True)
    matrix.add_argument("--runs-root", required=True)
    matrix.add_argument("--sample-rows", type=int, default=500_000)
    matrix.add_argument("--max-train-rows", type=int, default=500_000)
    matrix.add_argument("--max-validation-rows", type=int, default=200_000)
    matrix.add_argument("--max-test-rows", type=int, default=200_000)
    matrix.add_argument("--seeds", nargs="*", type=int, default=[DEFAULT_SEED])
    matrix.add_argument("--start-at", default="")
    matrix.add_argument("--only", nargs="*", default=[])
    matrix.add_argument("--chunk-index", type=int, default=0)
    matrix.add_argument("--chunk-total", type=int, default=1)
    matrix.add_argument("--progress-file", default="")
    matrix.add_argument("--history-days", type=int, default=0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        result = verify_package_layout(args.data)
        run_results = [verify_run(path) for path in args.runs]
        if run_results:
            result["runs"] = run_results
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "train":
        run_spec = _parse_run_selector(args)
        if args.rolling:
            def source_builder(window):
                return V04TaskSource(
                    args.data,
                    run_spec,
                    sample_rows=args.sample_rows,
                    window=window,
                    history_days=args.history_days,
                )

            test_source = V04TaskSource(
                args.data,
                run_spec,
                sample_rows=args.sample_rows,
                history_days=args.history_days,
            )
            result = train_run_rolling(
                run_spec,
                source_builder,
                test_source,
                args.output,
                feature_columns=(
                    ENRICHED_FEATURE_COLUMNS
                    if args.history_days > 0
                    else MODEL_FEATURE_COLUMNS
                ),
                sample_rows=args.max_train_rows,
                validation_rows=args.max_validation_rows,
                test_rows=args.max_test_rows,
                stop_after=args.stop_after,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        source = V04TaskSource(
            args.data,
            run_spec,
            sample_rows=args.sample_rows,
        )
        result = train_run(
            run_spec,
            source,
            args.output,
            stop_after=args.stop_after,
            max_train_rows=args.max_train_rows,
            max_validation_rows=args.max_validation_rows,
            max_test_rows=args.max_test_rows,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "evaluate":
        results = [verify_run(path) for path in args.runs]
        print(json.dumps({"status": "PASS", "runs": results}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run-matrix":
        return _run_full_matrix(args)
    return 2


def _run_full_matrix(args) -> int:
    matrix = build_run_matrix()
    root = Path(args.runs_root)
    root.mkdir(parents=True, exist_ok=True)
    started = False
    summary_path = (
        Path(args.progress_file)
        if args.progress_file
        else root / "matrix_progress.json"
    )
    progress = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else {"completed": [], "failed": []}
    )
    global_index = 0
    for _, row in matrix.iterrows():
        spec = task_spec(str(row["task_id"]), str(row["variant"]))
        for seed in args.seeds:
            run_spec = RunSpec(task=spec, horizon_days=int(row["horizon_days"]), seed=int(seed))
            run_id = run_spec.run_id
            global_index += 1
            if args.chunk_total > 1 and global_index % args.chunk_total != args.chunk_index:
                continue
            if args.only and run_id not in args.only:
                continue
            if run_id in progress["completed"]:
                continue
            if args.start_at and not started:
                if run_id == args.start_at:
                    started = True
                else:
                    continue
            output = root / run_id
            def source_builder(window, _run_spec=run_spec):
                return V04TaskSource(
                    args.data,
                    _run_spec,
                    sample_rows=args.sample_rows,
                    window=window,
                    history_days=args.history_days,
                )
            test_source = V04TaskSource(
                args.data,
                run_spec,
                sample_rows=args.sample_rows,
                history_days=args.history_days,
            )
            try:
                result = train_run_rolling(
                    run_spec,
                    source_builder,
                    test_source,
                    output,
                    feature_columns=(
                        ENRICHED_FEATURE_COLUMNS
                        if args.history_days > 0
                        else MODEL_FEATURE_COLUMNS
                    ),
                    sample_rows=args.max_train_rows,
                    validation_rows=args.max_validation_rows,
                    test_rows=args.max_test_rows,
                )
            except Exception as exc:
                progress["failed"].append({"run_id": run_id, "error": str(exc)})
                summary_path.write_text(
                    json.dumps(progress, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"FAILED {run_id}: {exc}")
                return 1
            progress["completed"].append(run_id)
            progress["failed"] = [
                item
                for item in progress["failed"]
                if item.get("run_id") != run_id
            ]
            summary_path.write_text(
                json.dumps(progress, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(result, ensure_ascii=False))
    print(json.dumps({"status": "DONE", "completed": len(progress["completed"]), "failed": len(progress["failed"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
