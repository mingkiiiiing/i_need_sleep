"""数据工厂 CLI (设计 §13)：11 条子命令。退出码 0=成功 1=校验失败 2=受阻/需确认。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.response_contract import contract_response

from data_factory.contracts.constants import (
    BOUNDARY_GPKG,
    DEFAULT_RELEASE_TABLES,
    RAW_ROOT,
    TAIHUGURAD_STATIONS,
    run_dir,
    yaml_path,
)
from data_factory.contracts.enums import Track

DEFAULT_SEED = 20260904
VALID_SOURCES = ("mee", "qweather", "gee")
VALID_TRACKS = (Track.SIM_V1.value, Track.HYBRID_V1.value, Track.REAL_V1.value)


def _load_yaml(name: str) -> dict[str, Any]:
    from data_factory.simulation.engine import load_yaml

    return load_yaml(yaml_path(name))


def _load_config() -> dict[str, Any]:
    config = _load_yaml("generation_config.yaml")
    config["realtime_sources"] = _load_yaml("realtime_sources.yml")
    return config


def _resolve_sim_dir(args: argparse.Namespace, base_dir: Path) -> Path:
    if getattr(args, "sim_dir", None):
        return Path(args.sim_dir)
    from data_factory.lineage.manifest import _latest_sim_dir

    sim_dir = _latest_sim_dir(base_dir)
    if sim_dir is None:
        raise SystemExit("no simulation run found under storage/runs/data_factory; run `python -m data_factory simulate` first")
    return sim_dir


def cmd_freeze_grid(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.contracts.spatial import run_freeze_grid

    config = _load_config()
    manifest = run_freeze_grid(
        config,
        boundary_gpkg=Path(args.boundary) if args.boundary else BOUNDARY_GPKG,
        out_dir=run_dir(args.dataset) / "grid",
        stations_json=Path(args.stations) if args.stations else TAIHUGURAD_STATIONS,
    )
    return manifest, 0


def cmd_ingest_history(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.ingestion.history_ingest import run_ingest_history

    config = _load_config()
    manifest = run_ingest_history(
        config,
        release_dir=Path(args.release_dir) if args.release_dir else DEFAULT_RELEASE_TABLES,
        out_dir=run_dir(args.dataset) / "history",
    )
    return manifest, 0


def cmd_collect_realtime(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    config = _load_config()
    if args.source == "mee":
        from data_factory.ingestion.mee_realtime import run_collect_mee

        manifest = run_collect_mee(config, out_dir=run_dir(args.dataset) / "realtime", raw_root=RAW_ROOT)
        if "BLOCKED" not in str(manifest.get("status", "")).upper() and "blocked" not in str(manifest.get("status", "")).lower():
            from data_factory.contracts.constants import SOURCE_REGISTRY_CSV, STORAGE
            from data_factory.ingestion.registry_updater import update_automation_status

            log_path = STORAGE / "manifests" / "registry_changes.jsonl"
            changed = update_automation_status(
                "mee_surface_water_realtime",
                "implemented_realtime_snapshot",
                registry_csv=SOURCE_REGISTRY_CSV,
                log=log_path,
            )
            manifest["registry_update"] = {
                "source_id": "mee_surface_water_realtime",
                "automation_status": "implemented_realtime_snapshot",
                "changed": changed,
                "log": str(log_path),
            }
    elif args.source == "qweather":
        from data_factory.ingestion.qweather_realtime import run_qweather

        manifest = run_qweather(config, raw_root=RAW_ROOT, out_dir=run_dir(args.dataset) / "realtime")
    elif args.source == "gee":
        from data_factory.ingestion.gee_remote import run_gee_plan

        manifest = run_gee_plan(config, start=args.start, end=args.end, out_dir=run_dir(args.dataset) / "realtime" / "gee_plan")
    else:
        return {"status": "blocked", "message": f"unknown source: {args.source} (available: {', '.join(VALID_SOURCES)})"}, 2
    if "BLOCKED" in str(manifest.get("status", "")).upper() or "blocked" in str(manifest.get("status", "")).lower():
        return manifest, 2
    return manifest, 0


def cmd_lock_splits(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.contracts.splits import run_lock_splits

    manifest = run_lock_splits(_load_config(), out_dir=run_dir(args.dataset) / "splits")
    return manifest, 0


def cmd_fit(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.split != "train":
        return {
            "status": "blocked",
            "message": f"拟合只允许 train split（先 lock-splits 再 fit --split train），收到: {args.split}",
        }, 2
    from data_factory.calibration.fitter import run_fit

    base = run_dir(args.dataset)
    manifest = run_fit(
        _load_config(),
        history_dir=base / "history",
        splits_dir=base / "splits",
        mechanism=_load_yaml("mechanism_parameters.yaml"),
        out_dir=base / "fit",
    )
    return manifest, 0


def cmd_simulate(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.simulation.engine import run_simulation

    manifest = run_simulation(_load_config(), scenario_id=args.scenario, seed=args.seed, dataset=args.dataset)
    return manifest, 0


def cmd_build_observations(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.simulation.observation import run_build_observations

    base = run_dir(args.dataset)
    manifest = run_build_observations(
        _load_config(),
        base_dir=base,
        sim_dir=_resolve_sim_dir(args, base),
        mechanism=_load_yaml("mechanism_parameters.yaml"),
        dataset=args.dataset,
    )
    return manifest, 0


def cmd_build_labels(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.labeling.tasks import build_labels

    base = run_dir(args.dataset)
    manifest = build_labels(
        _load_config(),
        base_dir=base,
        sim_dir=_resolve_sim_dir(args, base),
        thresholds=_load_yaml("label_thresholds.yaml"),
        dataset=args.dataset,
    )
    return manifest, 0


def cmd_assemble(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.track not in VALID_TRACKS:
        return {"status": "blocked", "message": f"unknown track: {args.track} (available: {', '.join(VALID_TRACKS)})"}, 2
    from data_factory.assembly.tracks import run_assemble

    base = run_dir(args.dataset)
    manifest = run_assemble(
        _load_config(),
        base_dir=base,
        sim_dir=_resolve_sim_dir(args, base),
        labels_dir=base / "labels",
        track=args.track,
        dataset=args.dataset,
    )
    return manifest, 0


def cmd_validate(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.lineage.row_lineage import write_row_lineage
    from data_factory.quality.reports import run_quality

    base = run_dir(args.dataset)
    sim_dir = _resolve_sim_dir(args, base)
    manifest = run_quality(
        _load_config(),
        base_dir=base,
        sim_dir=sim_dir,
        mechanism=_load_yaml("mechanism_parameters.yaml"),
    )
    lineage = write_row_lineage(base, sim_dir)
    manifest["row_lineage"] = lineage.get("output") or lineage.get("outputs")
    exit_code = 1 if (manifest.get("acceptance_fail", 0) or manifest.get("veto_fail", 0)) else 0
    return manifest, exit_code


def cmd_release(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from data_factory.lineage.manifest import build_release

    manifest = build_release(_load_config(), dataset=args.dataset)
    # DG-009/DG-011：质量门禁未过或缺必需交付 → 退出码 1
    exit_code = 0 if manifest.get("status") == "completed" else 1
    return manifest, exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data_factory",
        description="数据生成与处理工厂 (SIM-V1)；详见 reports/data-generation-system-design-2026-09-04",
    )
    parser.add_argument("--dataset", default=None, help="数据集标识，默认取 generation_config.yaml: dataset_id")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("freeze-grid", help="冻结 1km 网格、湖区扇区、站点注册与映射")
    p.add_argument("--boundary", default=None, help="湖界 gpkg，默认 storage/silver/geo/taihu_boundary.gpkg")
    p.add_argument("--stations", default=None, help="taihugurad stations.json，缺省自动解析")

    p = sub.add_parser("ingest-history", help="发布表 TAIHU_CLEAN_FINAL + NASA POWER → history parquet")
    p.add_argument("--release-dir", default=None, help="清洗发布表目录，默认 TAIHU_CLEAN_FINAL_V1_20260831/tables")

    p = sub.add_parser("collect-realtime", help="实时源采集（mee 实跑；qweather/gee 门控）")
    p.add_argument("--source", required=True, choices=VALID_SOURCES)
    p.add_argument("--start", default="2024-01-01", help="gee 计划窗口起点")
    p.add_argument("--end", default="2024-12-31", help="gee 计划窗口终点")

    sub.add_parser("lock-splits", help="锁定 70/15/15 + 隔离窗切分")

    p = sub.add_parser("fit", help="仅用 train 真值拟合校准参数")
    p.add_argument("--split", default="train", choices=["train"], help="固定 train（设计 §7）")

    p = sub.add_parser("simulate", help="两层世界仿真（情景×种子确定性）")
    p.add_argument("--scenario", default="baseline")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)

    p = sub.add_parser("build-observations", help="真实过境/采样日历驱动的观测层")
    p.add_argument("--sim-dir", default=None, help="默认取最新 simulation/<scenario>_seed<seed>")

    p = sub.add_parser("build-labels", help="T1–T7 三态标签（云遮/缺测=unknown）")
    p.add_argument("--sim-dir", default=None)

    p = sub.add_parser("assemble", help="T+1/3/7/15/30 样本装配 + member C 适配")
    p.add_argument("--track", default=Track.SIM_V1.value)
    p.add_argument("--sim-dir", default=None)

    p = sub.add_parser("validate", help="A01–A21 验收 + V01–V12 一票否决 + 九件套报告")
    p.add_argument("--sim-dir", default=None)

    sub.add_parser("release", help="组装 data_factory_release/SIM-V1 发布包")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _load_config()
    if not args.dataset:
        args.dataset = config.get("dataset_id", "mvp_meiliangwan_2024")

    handlers = {
        "freeze-grid": cmd_freeze_grid,
        "ingest-history": cmd_ingest_history,
        "collect-realtime": cmd_collect_realtime,
        "lock-splits": cmd_lock_splits,
        "fit": cmd_fit,
        "simulate": cmd_simulate,
        "build-observations": cmd_build_observations,
        "build-labels": cmd_build_labels,
        "assemble": cmd_assemble,
        "validate": cmd_validate,
        "release": cmd_release,
    }
    handler = handlers[args.command]
    try:
        payload, exit_code = handler(args)
    except SystemExit as exc:  # 上游 runner 的显式受阻（缺前置产物、未知情景等）
        payload = {"status": "blocked", "message": str(exc)}
        exit_code = 2
    envelope = contract_response(payload, command=f"data_factory.{args.command}")
    text = json.dumps(envelope, ensure_ascii=False, indent=2, default=str)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
