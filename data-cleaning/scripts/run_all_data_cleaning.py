# -*- coding: utf-8 -*-
"""TAIHU_CLEAN_FINAL_V1_20260831 全量清洗总入口。

执行顺序：
  1) 复用既有清洗器的产物核对（逐文件按 basename 与既有清洗表对账）
  2) 运行全部新增清洗器与例外处理器（work/<cleaner>/records.parquet）
  3) 合并所有文件级结论 -> file_conclusions.csv（每个文件恰好一条）
  4) rejections.csv（REJECTED / BLOCKED_AUTH / QUARANTINED 明细）
  5) run_summary.json（每个清洗器的文件数 / 记录数 / 结论分布）

用法:
  python scripts/run_all_data_cleaning.py [--release-id TAIHU_CLEAN_FINAL_V1_20260831] [--workers 8]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib_final_clean import (  # noqa: E402
    FILE_STATUSES, MANIFESTS, RELEASE_ID, WORK_DIR,
    empty_file_result, file_results_frame, load_cleaner_output, now_bj,
    records_frame, save_cleaner_output,
)
from cleaner_cli import CLEANER_FUNCS, run_cleaner  # noqa: E402

PACKAGE_ROOT = HERE.parent
CLEANED_DIR = PACKAGE_ROOT / "storage" / "cleaned"

# 既有清洗器 -> (清洗表文件, 文件名列) 的对账映射
EXISTING_HARVEST: dict[str, list[tuple[str, str]]] = {
    "clean_meteorology": [("c3s_seasonal_cleaned.csv", "source_file"),
                          ("noaa_gfs_cleaned.csv", "raw_grib_path")],
    "clean_hydrology": [("hydrology_cleaned.csv", "source_file")],
    "clean_water_quality": [("water_quality_cleaned.csv", "source_file")],
    "clean_field_samples": [("field_samples_cleaned.csv", "source_file")],
    "clean_static_features": [("static_features_cleaned.csv", "source_file")],
    "clean_thqbca_tables": [("water_quality_cleaned.csv", "source_file")],
    "clean_sentinel2_assets": [("remote_sensing_inventory.csv", "file_path")],
    "clean_clms_lwq": [("clms_lwq_10daily_cleaned.csv", "source_file"),
                       ("clms_lwq_asset_audit.csv", "file_path")],
    "clean_thqbca_raster": [],
    "clean_source_registry": [],
}

_EXISTING_BASENAMES: dict[str, set[str]] = {}


def _basenames(cleaner: str) -> set[str]:
    if cleaner in _EXISTING_BASENAMES:
        return _EXISTING_BASENAMES[cleaner]
    names: set[str] = set()
    for csv_name, col in EXISTING_HARVEST.get(cleaner, []):
        path = CLEANED_DIR / csv_name
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, usecols=[col])
        except (ValueError, FileNotFoundError):
            continue
        vals = df[col].dropna().astype(str)
        names |= {v.replace("\\", "/").split("/")[-1].strip().lower() for v in vals}
    _EXISTING_BASENAMES[cleaner] = names
    return names


def run_existing_cleaner(cleaner: str, files: pd.DataFrame) -> pd.DataFrame:
    """既有清洗器：按 basename 对账给出文件级结论，不重跑网络流程。"""
    known = _basenames(cleaner)
    results = []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        base = rel.replace("\\", "/").split("/")[-1].strip().lower()
        ext = (r.get("extension") or "").lower()
        if cleaner == "clean_source_registry":
            results.append(empty_file_result(
                rel, sha, cleaner, "METADATA_ONLY",
                "来源清单/授权回执本身即 source_registry 证据，登记元数据"))
        elif cleaner == "clean_thqbca_raster":
            results.append(empty_file_result(
                rel, sha, cleaner, "METADATA_ONLY",
                "THQBCA 栅格由机理建模流程按原始格式使用；本发布登记哈希与元数据"))
        elif base in known:
            results.append(empty_file_result(
                rel, sha, cleaner, "CLEANED",
                f"既有清洗产物中逐文件对账通过（basename={base}）"))
        elif ext in {"tif", "tiff"}:
            results.append(empty_file_result(
                rel, sha, cleaner, "METADATA_ONLY",
                "既有流程以月度聚合形式消费影像，未保留逐文件登记；本发布登记元数据"))
        else:
            results.append(empty_file_result(
                rel, sha, cleaner, "METADATA_ONLY",
                "既有清洗产物中未检索到该文件名，登记文件元数据并留待人工核查"))
    return file_results_frame(results)


def main() -> int:
    ap = argparse.ArgumentParser(description="全量清洗总入口")
    ap.add_argument("--release-id", default=RELEASE_ID)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", default="", help="仅运行指定清洗器（逗号分隔，调试用）")
    args = ap.parse_args()

    assignment = pd.read_csv(MANIFESTS / "file_cleaner_assignment.csv", dtype={"extension": str})
    full_assignment = assignment.copy()          # 合并结论时必须覆盖全部文件
    run_id = str(full_assignment["run_id"].iloc[0]) if "run_id" in full_assignment.columns and full_assignment["run_id"].notna().any() else ""
    if not run_id:
        # 兜底：沿用清点阶段的 run_id，保证全链路一致
        inv = pd.read_csv(MANIFESTS / "source_file_inventory.csv", usecols=["run_id"], nrows=1)
        run_id = str(inv["run_id"].iloc[0]) if len(inv) else ""
    only = {c for c in args.only.split(",") if c}
    cleaner_stats: list[dict] = []
    t0 = time.time()

    # ---------- 统一去重闸门：非主副本不进入任何清洗器 ----------
    is_primary = assignment["is_primary_copy"].astype(bool)
    dup_mask = (assignment["duplicate_count"] > 1) & (~is_primary)
    non_primary = assignment[dup_mask]
    if len(non_primary):
        dedup_results = file_results_frame([
            empty_file_result(r["relative_path"], r["sha256"], str(r["cleaner_name"]),
                              "DUPLICATE",
                              f"与主副本 {r['primary_copy_path']} 内容一致（SHA-256 相同），"
                              "不重复计入观测")
            for _, r in non_primary.iterrows()])
        out = WORK_DIR / "dedup_non_primary"
        out.mkdir(parents=True, exist_ok=True)
        dedup_results.to_parquet(out / "file_results.parquet", index=False)
        (out / "records.parquet").touch()
        cleaner_stats.append({"cleaner": "dedup_non_primary", "files": int(len(non_primary)),
                              "records": 0,
                              "statuses": dedup_results["status"].value_counts().to_dict()})
        print(f"[dedup_non_primary] {len(non_primary)} 个非主副本 -> DUPLICATE", flush=True)
        assignment = assignment[~dup_mask].copy()

    # ---------- 既有清洗器对账 ----------
    for cleaner in EXISTING_HARVEST:
        if only and cleaner not in only:
            continue
        sub = assignment[assignment["cleaner_name"] == cleaner]
        if sub.empty:
            continue
        results = run_existing_cleaner(cleaner, sub)
        out = WORK_DIR / cleaner
        out.mkdir(parents=True, exist_ok=True)
        results.to_parquet(out / "file_results.parquet", index=False)
        (out / "records.parquet").touch()
        cleaner_stats.append({"cleaner": cleaner, "files": int(len(sub)), "records": 0,
                              "statuses": results["status"].value_counts().to_dict()})
        print(f"[{cleaner}] 对账 {len(sub)} 文件 -> {results['status'].value_counts().to_dict()}",
              flush=True)

    # ---------- 新增清洗器与例外处理器 ----------
    for cleaner, fn in CLEANER_FUNCS.items():
        if only and cleaner not in only:
            continue
        sub = assignment[assignment["cleaner_name"] == cleaner]
        if sub.empty:
            continue
        t1 = time.time()
        if cleaner == "clean_modis_ocean_color":
            records, results = fn(sub, run_id, workers=args.workers)
        else:
            records, results = fn(sub, run_id)
        save_cleaner_output(cleaner, records, results)
        cleaner_stats.append({"cleaner": cleaner, "files": int(len(sub)),
                              "records": int(len(records)),
                              "statuses": results["status"].value_counts().to_dict(),
                              "seconds": round(time.time() - t1, 1)})
        print(f"[{cleaner}] {len(sub)} 文件 -> {len(records)} 记录 "
              f"({results['status'].value_counts().to_dict()}) {time.time()-t1:.0f}s",
              flush=True)

    if only:  # 调试模式不合并
        return 0

    # ---------- 合并文件级结论 ----------
    conclusion_rows = []
    for cleaner in set(EXISTING_HARVEST) | set(CLEANER_FUNCS) | {"dedup_non_primary"}:
        out = WORK_DIR / cleaner
        if not (out / "file_results.parquet").exists():
            continue
        results = pd.read_parquet(out / "file_results.parquet")
        records_n = 0
        if (out / "records.parquet").exists() and (out / "records.parquet").stat().st_size:
            try:
                records_n = len(pd.read_parquet(out / "records.parquet"))
            except Exception:  # noqa: BLE001
                records_n = 0
        for _, r in results.iterrows():
            conclusion_rows.append({
                "relative_path": r["relative_path"], "sha256": r["sha256"],
                "cleaner_name": r["cleaner_name"], "status": r["status"],
                "record_count": int(r.get("record_count", 0) or 0),
                "notes": r.get("notes", ""),
            })
    conclusions = pd.DataFrame(conclusion_rows)

    # 校验：每个文件恰好一条结论
    assignment["relative_path"] = assignment["relative_path"].astype(str)
    conclusions["relative_path"] = conclusions["relative_path"].astype(str)
    merged = full_assignment[["file_index", "relative_path", "source_partition", "sniffed_format",
                              "size_bytes", "sha256", "cleaner_name"]].merge(
        conclusions.drop(columns=["cleaner_name", "sha256"], errors="ignore"),
        on="relative_path", how="left")
    missing = merged["status"].isna()
    if missing.any():
        print(f"[阻断] {int(missing.sum())} 个文件没有结论，前 10 个：")
        print(merged.loc[missing, "relative_path"].head(10).to_string(index=False))
        return 1
    dup_conc = merged["relative_path"].duplicated().sum()
    if dup_conc:
        print(f"[阻断] {dup_conc} 个文件出现多条结论")
        return 1

    merged.to_csv(MANIFESTS / "file_conclusions.csv", index=False, encoding="utf-8-sig")

    # 拒绝 / 阻塞 / 隔离明细
    rej = merged[merged["status"].isin(["REJECTED", "BLOCKED_AUTH", "QUARANTINED"])][
        ["relative_path", "source_partition", "sniffed_format", "size_bytes", "sha256",
         "cleaner_name", "status", "notes"]]
    rej.to_csv(MANIFESTS / "rejections.csv", index=False, encoding="utf-8-sig")

    status_counts = merged["status"].value_counts().to_dict()
    all_concluded = bool(len(merged) == len(full_assignment)
                         and merged["relative_path"].nunique() == len(full_assignment)
                         and merged["status"].notna().all())
    summary = {
        "release_id": args.release_id,
        "run_id": run_id,
        "finished_at": now_bj(),
        "elapsed_seconds": round(time.time() - t0, 1),
        "file_count": int(len(merged)),
        "status_counts": status_counts,
        "cleaner_stats": cleaner_stats,
        "all_files_concluded": all_concluded,
    }
    (MANIFESTS / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 全量清洗完成 =====")
    print(f"文件总数: {summary['file_count']}  用时 {summary['elapsed_seconds']}s")
    for status in FILE_STATUSES:
        print(f"  {status:14s}: {status_counts.get(status, 0)}")
    print(f"明细: {MANIFESTS / 'file_conclusions.csv'}")
    print(f"拒绝: {MANIFESTS / 'rejections.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
