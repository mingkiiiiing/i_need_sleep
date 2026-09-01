# -*- coding: utf-8 -*-
"""阶段B：清洗器注册表与覆盖审计。

把 source_file_inventory.csv 中的每个文件映射到唯一清洗器，并审计覆盖率。

规则按 priority 升序求值，第一个命中的规则胜出。
标记 fallback=True 的规则是兜底规则：仅当没有任何常规规则命中时才生效，
因此不参与多重匹配冲突判定。

同时统计"所有命中的常规规则"，若同一文件被多个不同清洗器命中，
记为 MULTI_MATCH（审计告警，不静默通过）。

输出:
  <release>/manifests/cleaner_registry.csv          规则表
  <release>/manifests/cleaner_coverage.csv          按清洗器汇总覆盖
  <release>/manifests/file_cleaner_assignment.csv   逐文件指派
  <release>/manifests/coverage_summary.json         覆盖结论

用法:
  python scripts/build_cleaner_registry.py
  python scripts/build_cleaner_registry.py --require-full-coverage
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RELEASE_BASE = HERE.parent / "storage" / "final_cleaned"
BEIJING = timezone(timedelta(hours=8))

ANY = None  # 表示该匹配条件不限制

# ------------------------------------------------------------------ 守卫
# 压缩包规则的守卫：排除分区级专属分区（04/06/07）与隔离区
GA = (r"^(?!04_公开数据目录检索原始响应)(?!06_主数据采集与来源清单)"
      r"(?!07_采集过程临时资料)(?!.*/quarantine/)")

# 主题规则的守卫：在 GA 基础上再排除压缩包、Excel 锁文件、隐藏文件。
# 这些形态已由前置规则（R010-R013/R050-R052）专属处理，避免重复命中。
G = (r"^(?!04_公开数据目录检索原始响应)(?!06_主数据采集与来源清单)"
     r"(?!07_采集过程临时资料)(?!.*/quarantine/)(?!.*/~\$)"
     r"(?!.*\.(rar|7z)$)(?!.*/\.)")

# 07 分区整体交给分区级临时资料规则，前置例外规则需排除该分区
P07 = ("07_采集过程临时资料",)

# ------------------------------------------------------------------ 规则表
RULES: list[dict] = [
    # ---------- 前置例外（必须最先命中，杜绝脏数据进入有效记录） ----------
    dict(rule_id="R010", priority=10, partitions=ANY, path_regex=ANY,
         exclude_partitions=P07, formats={"empty"}, extensions=ANY, fallback=False,
         cleaner="exception_zero_byte", output_table="rejections",
         cleaner_status="EXCEPTION", terminal_status="REJECTED",
         notes="零字节文件，禁止进入有效数据"),
    dict(rule_id="R011", priority=11, partitions=ANY, path_regex=r"(^|/)~\$",
         exclude_partitions=P07, formats=ANY, extensions=ANY, fallback=False,
         cleaner="exception_lockfile", output_table="rejections",
         cleaner_status="EXCEPTION", terminal_status="REJECTED",
         notes="Excel 临时锁文件（~$ 前缀），非数据"),
    dict(rule_id="R012", priority=12, partitions=ANY, path_regex=r"^(?!.*/~\$)",
         exclude_partitions=P07,
         formats={"unreadable", "probe_failed", "unknown_binary"}, extensions=ANY, fallback=False,
         cleaner="exception_unreadable", output_table="rejections",
         cleaner_status="EXCEPTION", terminal_status="REJECTED",
         notes="打不开或格式无法识别，禁止进入有效数据"),
    dict(rule_id="R013", priority=13, partitions=ANY, path_regex=r"(^|/)\.[^/]+$",
         exclude_partitions=P07, formats=ANY, extensions=ANY, fallback=False,
         cleaner="exception_temporary", output_table="rejections",
         cleaner_status="EXCEPTION", terminal_status="REJECTED",
         notes="隐藏文件与采集临时产物（如 .curl_cookies），非数据"),

    # ---------- 分区级规则 ----------
    dict(rule_id="R020", priority=20, partitions=("07_采集过程临时资料",), path_regex=ANY,
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="exception_temporary", output_table="rejections",
         cleaner_status="EXCEPTION", terminal_status="REJECTED",
         notes="验证码与采集临时资料，不进入数据模型"),
    dict(rule_id="R030", priority=30, partitions=("04_公开数据目录检索原始响应",), path_regex=ANY,
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_catalog_responses", output_table="source_registry",
         cleaner_status="NEW", terminal_status="METADATA_ONLY",
         notes="公开数据目录检索响应，只作目录元数据，不冒充观测值"),
    dict(rule_id="R031", priority=31, partitions=("06_主数据采集与来源清单",), path_regex=ANY,
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_source_registry", output_table="source_registry",
         cleaner_status="EXISTING", terminal_status="METADATA_ONLY",
         notes="采集与来源清单，形成来源/授权/下载血缘表"),

    # ---------- 隔离区（优先于同名数据源规则） ----------
    dict(rule_id="R040", priority=40, partitions=ANY, path_regex=r"/quarantine/",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="review_quarantined_assets", output_table="remote_sensing",
         cleaner_status="NEW", terminal_status="QUARANTINED",
         notes="隔离栅格复核：可修复则回表，否则 REJECTED"),

    # ---------- 压缩包优先：必须先解包才能判定主题归属 ----------
    dict(rule_id="R050", priority=50, partitions=ANY, path_regex=GA + r".*/bloom/",
         formats={"rar", "7z", "zip_container"}, extensions=ANY, fallback=False,
         cleaner="clean_bloom_archive", output_table="labels",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="蓝藻压缩包，先安全解包与模式识别再判定标签来源"),
    dict(rule_id="R051", priority=51, partitions=ANY, path_regex=GA + r"(?!.*/bloom/)",
         formats={"rar", "7z"}, extensions=ANY, fallback=False,
         cleaner="inspect_data_archive", output_table="source_registry",
         cleaner_status="NEW", terminal_status="METADATA_ONLY",
         notes="其余 RAR/7Z 数据包（如 THQBCA-V2.rar），安全清点后登记内容与来源"),
    dict(rule_id="R052", priority=52, partitions=ANY,
         path_regex=GA + r"(?!.*\.(xlsx|xlsm|zip|docx|gpkg|shp)$)",
         formats={"zip_container"}, extensions=ANY, fallback=False,
         cleaner="clean_zip_wrapped_netcdf", output_table="observations",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="扩展名是数据格式但实为 zip 容器（如 CDS 异步下载的 .nc），安全解包后再按内容清洗"),

    # ---------- 主数据：MODIS 遥感 ----------
    dict(rule_id="R100", priority=100, partitions=ANY, path_regex=G + r".*/ocean_color/",
         formats={"hdf5", "netcdf3_classic", "netcdf3_64bit_offset", "netcdf3_64bit_data"},
         extensions=ANY, fallback=False,
         cleaner="clean_modis_ocean_color", output_table="remote_sensing",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="MODIS 海色叶绿素 nc，需校验缩放系数/填充值/QA/太湖裁剪"),
    dict(rule_id="R101", priority=101, partitions=ANY,
         path_regex=G + r".*/(modis_aqua_extended|modis_l2_2020)/",
         formats={"hdf5", "hdf4"}, extensions=ANY, fallback=False,
         cleaner="clean_modis_ocean_color", output_table="remote_sensing",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="MODIS L2/L3 扩展数据（含旧版 .0 扩展名），先判真实格式"),
    dict(rule_id="R110", priority=110, partitions=ANY,
         path_regex=G + r".*/(land_surface|modis_lst)/",
         formats={"hdf4"}, extensions=ANY, fallback=False,
         cleaner="clean_modis_land_surface", output_table="surface_features",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="MODIS 地表温度 HDF4 子数据集，应用 scale/offset 与质量位"),

    # ---------- 主数据：Sentinel / CLMS ----------
    dict(rule_id="R120", priority=120, partitions=ANY,
         path_regex=G + r".*/(earth_search_sentinel2|copernicus_sentinel2_stac|sentinel2_monthly)",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_sentinel2_assets", output_table="remote_sensing",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="Sentinel-2 影像与年度镶嵌，校验波段/云量/范围/日期"),
    dict(rule_id="R121", priority=121, partitions=ANY, path_regex=G + r".*/clms_lwq",
         formats={"tiff_le", "tiff_be", "json", "html", "delimited_text"}, extensions=ANY,
         fallback=False,
         cleaner="clean_clms_lwq", output_table="remote_sensing",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="CLMS 湖泊水质产品与目录，保留产品版本与反演属性"),
    dict(rule_id="R130", priority=130, partitions=ANY, path_regex=G + r".*/sentinel3_olci",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_sentinel3_status", output_table="source_registry",
         cleaner_status="NEW", terminal_status="BLOCKED_AUTH",
         notes="Sentinel-3 仅清单无栅格时记 BLOCKED_AUTH，不伪造影像"),

    # ---------- 主数据：气象 / 水文 / 水质 ----------
    dict(rule_id="R141", priority=141, partitions=ANY,
         path_regex=G + r".*/(meteorology|mwr_hfc|nasa_power|open_meteo|era5_land)",
         formats={"grib", "hdf5", "netcdf3_classic", "netcdf3_64bit_offset", "netcdf3_64bit_data",
                  "json", "delimited_text", "text", "parquet"}, extensions=ANY, fallback=False,
         cleaner="clean_meteorology", output_table="observations",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="气象统一清洗：统一时区/单位，区分历史观测与预报输入"),
    dict(rule_id="R150", priority=150, partitions=ANY,
         path_regex=G + r"(?!.*/mwr_hfc).*/(tba_hydrology|hydrology)",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_hydrology", output_table="observations",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="太湖流域管理局水文资料，仅有元数据时转 METADATA_ONLY"),
    dict(rule_id="R151", priority=151, partitions=ANY,
         path_regex=G + r".*/(water_quality|authorized_waterstation|water_station)",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_water_quality", output_table="observations",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="水质站与授权数据；授权失败单独登记 BLOCKED_AUTH"),
    dict(rule_id="R152", priority=152, partitions=ANY,
         path_regex=G + r".*/(zenodo_taihu_insitu|field_samples)",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_field_samples", output_table="observations",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="太湖现场样本，稀疏且必须标记 ground_truth"),

    # ---------- THQBCA ----------
    dict(rule_id="R160", priority=160, partitions=ANY,
         path_regex=G + r".*/(taihu_thqbca_zenodo|THQBCA|解压内容)",
         formats={"tiff_le", "tiff_be"}, extensions=ANY, fallback=False,
         cleaner="clean_thqbca_raster", output_table="remote_sensing",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="THQBCA 生物光学与人类活动栅格，保留版本来源"),
    dict(rule_id="R161", priority=161, partitions=ANY,
         path_regex=G + r".*/(taihu_thqbca_zenodo|THQBCA|解压内容)",
         formats={"zip_container", "delimited_text", "text", "json", "html", "sqlite"},
         extensions=ANY, fallback=False,
         cleaner="clean_thqbca_tables", output_table="observations",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="THQBCA 水质/藻类表格（xlsx 为 zip 容器；txt/csv 为表格）"),

    # ---------- 静态地理 ----------
    dict(rule_id="R170", priority=170, partitions=ANY,
         path_regex=G + r".*/(static_geo|hydrobasins|geo|static_features)",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_static_features", output_table="static_features",
         cleaner_status="EXISTING", terminal_status="CLEANED",
         notes="静态地理、湖界、HydroBASINS，统一 CRS/像元/空间 ID"),

    # ---------- 专项：PDF / 压缩包 / 探测页 ----------
    dict(rule_id="R180", priority=180, partitions=ANY,
         path_regex=G + r".*/mee_surface_water_monthly/",
         formats={"pdf"}, extensions=ANY, fallback=False,
         cleaner="clean_mee_monthly_pdf", output_table="observations",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="生态环境部月度地表水扫描 PDF；OCR 低置信度只入 document_metadata"),
    dict(rule_id="R182", priority=182, partitions=ANY, path_regex=G + r".*/lake_geodata_probe/",
         formats=ANY, extensions=ANY, fallback=False,
         cleaner="clean_catalog_responses", output_table="source_registry",
         cleaner_status="NEW", terminal_status="METADATA_ONLY",
         notes="数据门户探测页，仅登记来源可达性元数据"),

    # ---------- 旧版混合整理区：兜底规则 ----------
    dict(rule_id="R900", priority=900, partitions=("05_旧版整理区_混合留存",),
         path_regex=r"/remote_sensing/", formats=ANY, extensions=ANY, fallback=True,
         cleaner="classify_and_deduplicate_legacy", output_table="remote_sensing",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="旧版遥感整理区兜底：先判原始/派生/重复再分流"),
    dict(rule_id="R901", priority=901, partitions=("05_旧版整理区_混合留存",),
         path_regex=r"/reports/", formats=ANY, extensions=ANY, fallback=True,
         cleaner="classify_and_deduplicate_legacy", output_table="document_metadata",
         cleaner_status="NEW", terminal_status="METADATA_ONLY",
         notes="旧版报告区兜底：PDF 原件与已解析文本分开处理"),
    dict(rule_id="R902", priority=902, partitions=("05_旧版整理区_混合留存",),
         path_regex=ANY, formats=ANY, extensions=ANY, fallback=True,
         cleaner="classify_and_deduplicate_legacy", output_table="mixed",
         cleaner_status="NEW", terminal_status="CLEANED",
         notes="旧版混合区兜底：分类去重后按类别分流"),
]

# 现有清洗器对应的真实脚本（用于覆盖率审计）
EXISTING_SCRIPT_MAP = {
    "clean_meteorology": "scripts/clean_meteorology.py",
    "clean_hydrology": "scripts/clean_hydrology.py",
    "clean_water_quality": "scripts/clean_water_quality.py",
    "clean_field_samples": "scripts/clean_field_samples.py",
    "clean_static_features": "scripts/clean_static_features.py",
    "clean_sentinel2_assets": "scripts/build_remote_sensing.py",
    "clean_clms_lwq": "scripts/clean_latest_public_data.py",
    "clean_thqbca_raster": "scripts/build_remote_sensing.py",
    "clean_thqbca_tables": "scripts/build_remote_sensing.py",
    "clean_source_registry": "scripts/audit_manifests.py",
}


def _match(rule: dict, row) -> bool:
    if rule["partitions"] is not ANY and row["source_partition"] not in rule["partitions"]:
        return False
    if row["source_partition"] in rule.get("exclude_partitions", ()):
        return False
    if rule["formats"] is not ANY and row["sniffed_format"] not in rule["formats"]:
        return False
    if rule["extensions"] is not ANY and row["extension"] not in rule["extensions"]:
        return False
    if rule["path_regex"] is not ANY:
        if not re.search(rule["path_regex"], row["relative_path"]):
            return False
    return True


def assign(df: pd.DataFrame) -> pd.DataFrame:
    """为每个文件指派唯一清洗器：常规规则优先，兜底规则仅在无命中时生效。"""
    ordered = sorted(RULES, key=lambda r: r["priority"])
    specific = [r for r in ordered if not r.get("fallback")]
    fallbacks = [r for r in ordered if r.get("fallback")]

    chosen_rule, chosen_cleaner, chosen_table, chosen_status, chosen_term = [], [], [], [], []
    all_cleaners, match_counts, used_fallback = [], [], []

    for _, row in df.iterrows():
        hits = [r for r in specific if _match(r, row)]
        fb = False
        if not hits:
            hits = [r for r in fallbacks if _match(r, row)]
            fb = bool(hits)
        cleaners = []
        for r in hits:
            if r["cleaner"] not in cleaners:
                cleaners.append(r["cleaner"])
        all_cleaners.append("|".join(cleaners))
        match_counts.append(len(hits))
        used_fallback.append(fb)
        if hits:
            win = hits[0]  # priority 最小者
            chosen_rule.append(win["rule_id"])
            chosen_cleaner.append(win["cleaner"])
            chosen_table.append(win["output_table"])
            chosen_status.append(win["cleaner_status"])
            chosen_term.append(win["terminal_status"])
        else:
            chosen_rule.append("")
            chosen_cleaner.append("UNMATCHED")
            chosen_table.append("")
            chosen_status.append("MISSING")
            chosen_term.append("UNRESOLVED")

    out = df.copy()
    out["rule_id"] = chosen_rule
    out["cleaner_name"] = chosen_cleaner
    out["output_table"] = chosen_table
    out["cleaner_status"] = chosen_status
    out["expected_terminal_status"] = chosen_term
    out["all_matched_cleaners"] = all_cleaners
    out["match_count"] = match_counts
    out["used_fallback_rule"] = used_fallback
    out["is_multi_match"] = out["all_matched_cleaners"].str.contains(r"\|", na=False)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段B：清洗器注册表与覆盖审计")
    ap.add_argument("--release-id", default="TAIHU_CLEAN_FINAL_V1_20260831")
    ap.add_argument("--release-base", default=str(RELEASE_BASE))
    ap.add_argument("--require-full-coverage", action="store_true",
                    help="存在 UNMATCHED 或多重匹配时以非零码退出")
    args = ap.parse_args()

    out_dir = Path(args.release_base) / args.release_id / "manifests"
    inv_path = out_dir / "source_file_inventory.csv"
    if not inv_path.exists():
        print(f"[错误] 缺少清单文件，请先运行 build_full_source_inventory.py: {inv_path}")
        return 2

    df = pd.read_csv(inv_path, dtype={"extension": str})
    df["extension"] = df["extension"].fillna("")
    df["sniffed_format"] = df["sniffed_format"].fillna("")
    df["source_partition"] = df["source_partition"].fillna("")

    assigned = assign(df)

    reg = pd.DataFrame([{
        "rule_id": r["rule_id"], "priority": r["priority"],
        "partitions": "*" if r["partitions"] is ANY else "|".join(r["partitions"]),
        "exclude_partitions": "|".join(r.get("exclude_partitions", ())),
        "path_regex": r["path_regex"] or "",
        "formats": "*" if r["formats"] is ANY else "|".join(sorted(r["formats"])),
        "is_fallback": bool(r.get("fallback")),
        "cleaner_name": r["cleaner"], "output_table": r["output_table"],
        "cleaner_status": r["cleaner_status"], "expected_terminal_status": r["terminal_status"],
        "notes": r["notes"],
    } for r in sorted(RULES, key=lambda x: x["priority"])])
    reg.to_csv(out_dir / "cleaner_registry.csv", index=False, encoding="utf-8-sig")

    keep = ["file_index", "run_id", "relative_path", "source_partition", "sniffed_format",
            "extension", "size_bytes", "sha256", "is_zero_byte", "is_readable",
            "duplicate_count", "is_primary_copy", "primary_copy_path", "file_role",
            "rule_id", "cleaner_name", "output_table", "cleaner_status",
            "expected_terminal_status", "all_matched_cleaners", "match_count",
            "used_fallback_rule", "is_multi_match"]
    # 兼容旧清单/测试清单：缺失列自动补空值，保证 keep 选择不抛 KeyError
    if "run_id" not in assigned.columns:
        assigned["run_id"] = df["run_id"] if "run_id" in df.columns else ""
    for col in keep:
        if col not in assigned.columns:
            assigned[col] = ""
    assigned[keep].to_csv(out_dir / "file_cleaner_assignment.csv", index=False, encoding="utf-8-sig")

    cov = assigned.groupby(["cleaner_name", "cleaner_status", "output_table"]).agg(
        files=("file_index", "count"),
        gb=("size_bytes", lambda s: round(s.clip(lower=0).sum() / 2 ** 30, 3)),
        partitions=("source_partition", lambda s: "|".join(sorted(s.unique())[:4])),
        formats=("sniffed_format", lambda s: "|".join(sorted(s.unique())[:5])),
    ).reset_index().sort_values("files", ascending=False)
    cov["reuse_script"] = cov["cleaner_name"].map(EXISTING_SCRIPT_MAP).fillna("")

    def _script_state(row) -> str:
        if row["cleaner_status"] != "EXISTING":
            return "TO_BE_DEVELOPED"
        rel = EXISTING_SCRIPT_MAP.get(row["cleaner_name"], "")
        return "AVAILABLE" if rel and (HERE.parent / rel).exists() else "MISSING_SCRIPT"

    cov["script_state"] = cov.apply(_script_state, axis=1)
    cov["test_status"] = cov["cleaner_name"].apply(
        lambda c: "EXISTING_REGRESSION" if c in EXISTING_SCRIPT_MAP else "PENDING_NEW_TEST"
    )
    cov.to_csv(out_dir / "cleaner_coverage.csv", index=False, encoding="utf-8-sig")

    n_unmatched = int((assigned["cleaner_name"] == "UNMATCHED").sum())
    n_multi = int(assigned["is_multi_match"].sum())
    n_new = int((assigned["cleaner_status"] == "NEW").sum())
    n_exc = int((assigned["cleaner_status"] == "EXCEPTION").sum())

    summary = {
        "release_id": args.release_id,
        "generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "total_files": int(len(assigned)),
        "unmatched_files": n_unmatched,
        "multi_match_files": n_multi,
        "files_needing_new_cleaner": n_new,
        "files_handled_by_exception": n_exc,
        "cleaner_count": int(assigned["cleaner_name"].nunique()),
        "coverage_ok": bool(n_unmatched == 0 and n_multi == 0),
    }
    (out_dir / "coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("===== 阶段B 覆盖审计 =====")
    print(f"文件总数            : {summary['total_files']}")
    print(f"未匹配文件          : {n_unmatched}")
    print(f"多重匹配文件        : {n_multi}")
    print(f"需新增清洗器的文件  : {n_new}")
    print(f"例外处理器的文件    : {n_exc}")
    print(f"清洗器数量          : {summary['cleaner_count']}")
    print()
    print(cov[["cleaner_name", "cleaner_status", "files", "gb", "output_table",
               "script_state", "test_status"]].to_string(index=False))

    if n_unmatched:
        print("\n[未匹配样例]")
        print(assigned.loc[assigned["cleaner_name"] == "UNMATCHED", "relative_path"]
              .head(20).to_string(index=False))
    if n_multi:
        print("\n[多重匹配样例]")
        print(assigned.loc[assigned["is_multi_match"],
                           ["relative_path", "cleaner_name", "all_matched_cleaners"]]
              .head(20).to_string(index=False))

    print(f"\n输出目录: {out_dir}")
    print("  cleaner_registry.csv / cleaner_coverage.csv / file_cleaner_assignment.csv")

    if args.require_full_coverage and not summary["coverage_ok"]:
        print("\n[阻断] --require-full-coverage 生效：存在未匹配或多重匹配，禁止进入全量运行。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
