# -*- coding: utf-8 -*-
"""清洗器统一调度入口。

用法:
  python scripts/cleaner_cli.py clean_modis_ocean_color --workers 8 [--limit 50] [--dry-run]
  python scripts/clean_modis_ocean_color ...   # 各命名脚本是对本入口的薄封装
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib_final_clean import (  # noqa: E402
    MANIFESTS, RELEASE_ID, save_cleaner_output,
)
from final_cleaners import (  # noqa: E402
    run_clean_bloom_archive,
    run_clean_catalog_responses,
    run_clean_mee_monthly_pdf,
    run_clean_modis_land_surface,
    run_clean_modis_ocean_color,
    run_clean_sentinel3_status,
    run_clean_zip_wrapped_netcdf,
    run_classify_and_deduplicate_legacy,
    run_exception_lockfile,
    run_exception_temporary,
    run_exception_unreadable,
    run_exception_zero_byte,
    run_inspect_data_archive,
    run_review_quarantined_assets,
)

CLEANER_FUNCS = {
    "clean_modis_ocean_color": run_clean_modis_ocean_color,
    "clean_modis_land_surface": run_clean_modis_land_surface,
    "clean_mee_monthly_pdf": run_clean_mee_monthly_pdf,
    "review_quarantined_assets": run_review_quarantined_assets,
    "clean_catalog_responses": run_clean_catalog_responses,
    "clean_bloom_archive": run_clean_bloom_archive,
    "inspect_data_archive": run_inspect_data_archive,
    "clean_zip_wrapped_netcdf": run_clean_zip_wrapped_netcdf,
    "clean_sentinel3_status": run_clean_sentinel3_status,
    "classify_and_deduplicate_legacy": run_classify_and_deduplicate_legacy,
    "exception_zero_byte": run_exception_zero_byte,
    "exception_lockfile": run_exception_lockfile,
    "exception_unreadable": run_exception_unreadable,
    "exception_temporary": run_exception_temporary,
}


def run_cleaner(cleaner: str, workers: int = 8, limit: int = 0,
                release_id: str = RELEASE_ID) -> tuple[int, int]:
    assignment_path = MANIFESTS / "file_cleaner_assignment.csv"
    df = pd.read_csv(assignment_path, dtype={"extension": str})
    sub = df[df["cleaner_name"] == cleaner].copy()
    # 与总入口一致：非主副本不进入清洗器，避免独立运行时产生重复记录
    if "is_primary_copy" in sub.columns:
        primary = sub["is_primary_copy"].astype(bool)
        sub = sub[primary | (sub["duplicate_count"].fillna(1) <= 1)]
    if limit:
        sub = sub.head(limit)
    if sub.empty:
        print(f"[{cleaner}] 无待处理文件")
        return 0, 0
    run_id = str(df["run_id"].iloc[0]) if "run_id" in df.columns else ""
    fn = CLEANER_FUNCS[cleaner]
    t0 = time.time()
    if cleaner == "clean_modis_ocean_color":
        records, results = fn(sub, run_id, workers=workers)
    else:
        records, results = fn(sub, run_id)
    if limit:
        # 限定样本运行时不落盘，避免覆盖全量产物
        print(f"[{cleaner}] 样本运行 {len(sub)} 文件 -> {len(records)} 记录，不落盘")
        return len(sub), len(records)
    save_cleaner_output(cleaner, records, results)
    status_counts = results["status"].value_counts().to_dict()
    print(f"[{cleaner}] 文件 {len(sub)} -> 记录 {len(records)}，用时 {time.time()-t0:.0f}s，"
          f"结论分布 {status_counts}")
    return len(sub), len(records)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="清洗器统一调度")
    ap.add_argument("cleaner", choices=sorted(CLEANER_FUNCS))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--release-id", default=RELEASE_ID)
    args = ap.parse_args(argv)
    n_files, n_records = run_cleaner(args.cleaner, workers=args.workers,
                                     limit=args.limit, release_id=args.release_id)
    print(f"完成: {args.cleaner} 文件={n_files} 记录={n_records}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
