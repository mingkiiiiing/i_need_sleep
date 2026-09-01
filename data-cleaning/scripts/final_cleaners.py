# -*- coding: utf-8 -*-
"""TAIHU_CLEAN_FINAL_V1_20260831 全部新增清洗器与例外处理器。

每个 run_* 函数输入文件子集 DataFrame（来自 file_cleaner_assignment.csv），
输出 (records: DataFrame, results: DataFrame)：
  records  —— 进入主长表的标准化记录
  results  —— 每个文件的终态结论（CLEANED/METADATA_ONLY/DUPLICATE/QUARANTINED/
              REJECTED/BLOCKED_AUTH 之一）
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib_final_clean import (  # noqa: E402
    RAW_ROOT, TAIHU_BBOX, WORK_DIR, BEIJING,
    bbox_slice_indices, empty_file_result, file_results_frame, make_record,
    open_hdf5, records_frame, summarize,
)

LST_TILES_COVERING_TAIHU = {"h30v05"}  # 太湖位于 MODIS 正弦投影 h30v05 瓦片
BSDTAR = r"C:\Windows\System32\tar.exe"

# 子进程共享的 run_id（由各并行清洗器在派发前设置）
_RUN_ID = ""


def _abs(rel: str) -> Path:
    return RAW_ROOT / rel


# ============================================================ 例外处理器
def run_exception_zero_byte(files: pd.DataFrame, run_id: str):
    results, records = [], []
    for _, r in files.iterrows():
        results.append(empty_file_result(
            r["relative_path"], r["sha256"], "exception_zero_byte", "REJECTED",
            "零字节文件：无任何字节内容，禁止进入有效记录"))
    return records_frame(records), file_results_frame(results)


def run_exception_lockfile(files: pd.DataFrame, run_id: str):
    results, records = [], []
    for _, r in files.iterrows():
        results.append(empty_file_result(
            r["relative_path"], r["sha256"], "exception_lockfile", "REJECTED",
            "Excel 临时锁文件（~$ 前缀）：非数据，禁止进入有效记录"))
    return records_frame(records), file_results_frame(results)


def run_exception_unreadable(files: pd.DataFrame, run_id: str):
    results, records = [], []
    for _, r in files.iterrows():
        results.append(empty_file_result(
            r["relative_path"], r["sha256"], "exception_unreadable", "REJECTED",
            f"不可读或格式无法识别（sniffed_format={r['sniffed_format']}），禁止进入有效记录"))
    return records_frame(records), file_results_frame(results)


def run_exception_temporary(files: pd.DataFrame, run_id: str):
    results, records = [], []
    for _, r in files.iterrows():
        results.append(empty_file_result(
            r["relative_path"], r["sha256"], "exception_temporary", "REJECTED",
            "采集过程临时资料（验证码/隐藏文件/cookie），按规则不进入数据模型"))
    return records_frame(records), file_results_frame(results)


# ============================================================ MODIS 海色
_L3M_DATE = re.compile(r"(20\d{6})")
_CHLA_UNIT = "mg/m3"


def _clean_one_modis_oc(rel: str, sha: str, run_id: str):
    """单文件 MODIS 叶绿素清洗（L3m 网格或 L2 轨道）。

    返回 (records, results, extra)，extra 用于月度聚合：
      extra = None 或 {"month": "YYYY-MM", "values": [...], "date": "YYYY-MM-DD"}
    在子进程中执行。
    """
    path = RAW_ROOT / rel
    base = os.path.basename(rel)
    name = base.removesuffix(".0").removesuffix(".nc")
    date_m = _L3M_DATE.search(name)
    observed_at = ""
    if date_m:
        try:
            observed_at = pd.Timestamp(str(date_m.group(1))).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            observed_at = ""
    is_climatology = bool(re.search(r"\.(MC|CU|MO|YO)\.", name))

    records, results = [], []
    try:
        with open_hdf5(path) as h:
            acquired_at = ""
            attrs = h.attrs.get("date_created")
            if attrs is not None:
                acquired_at = str(np.atleast_1d(attrs)[0])[:19]

            if "chlor_a" in h and "lat" in h and "lon" in h:
                # L3m 网格产品
                lat = np.asarray(h["lat"][:], dtype="float64")
                lon = np.asarray(h["lon"][:], dtype="float64")
                data = h["chlor_a"]
                fill = float(np.asarray(data.attrs.get("_FillValue", [-32767.0])).ravel()[0])
                i, j = bbox_slice_indices(lat, lon)
                block = np.asarray(data[i, j], dtype="float64")
                valid_lat = lat[i]
                valid_lon = lon[j]
                mask = np.isfinite(block) & (block != fill) & (block > 0)
                values = block[mask]
                total = int(block.size)
                extra = None
                if not is_climatology and observed_at and values.size:
                    extra = {"month": observed_at[:7], "date": observed_at,
                             "rel": rel,
                             "values": [round(float(v), 4) for v in values]}
                if values.size == 0:
                    results.append(empty_file_result(
                        rel, sha, "clean_modis_ocean_color", "METADATA_ONLY",
                        "太湖范围内无有效像元（云掩膜/缺测），仅保留文件元数据", 0))
                    return records, results, extra
                st = summarize(values)
                ratio = st["value_count"] / max(1, total)
                flag = "Q00" if ratio >= 0.05 else "Q10"
                records.append(make_record(
                    source_id="modis_aqua_chla", source_file=rel, source_sha=sha,
                    source_locator=f"chlor_a[{i.start}:{i.stop},{j.start}:{j.stop}]",
                    observed_at=observed_at, acquired_at=acquired_at,
                    spatial_id="TAIHU_BBOX", longitude=float(valid_lon.mean()),
                    latitude=float(valid_lat.mean()),
                    variable_code="chla_retrieval", value=st["value"], unit=_CHLA_UNIT,
                    quality_flag=flag,
                    quality_status="valid" if flag == "Q00" else "review",
                    provenance_type="derived",
                    cleaner_name="clean_modis_ocean_color",
                    value_count=st["value_count"], value_min=st["value_min"],
                    value_max=st["value_max"], value_p50=st["value_p50"],
                    value_p90=st["value_p90"],
                    aux={"valid_ratio": round(ratio, 4),
                         "resolution": name.rsplit(".", 1)[-1],
                         "product": "L3m DAY CHL" if not is_climatology else "L3m climatology"},
                    run_id=run_id))
                results.append(empty_file_result(
                    rel, sha, "clean_modis_ocean_color", "CLEANED",
                    f"L3m 网格叶绿素提取：{st['value_count']} 有效像元", 1))
                return records, results, extra

            if "navigation_data" in h and "geophysical_data" in h:
                # L2 轨道产品（旧版 .0 扩展名）
                geo = h["geophysical_data"]
                var_name = next((k for k in ("chlor_a", "chl_oc3", "chl_oc4") if k in geo), None)
                nav = h["navigation_data"]
                if var_name is None or "longitude" not in nav or "latitude" not in nav:
                    results.append(empty_file_result(
                        rel, sha, "clean_modis_ocean_color", "METADATA_ONLY",
                        "L2 轨道产品缺少叶绿素或导航变量", 0))
                    return records, results, None
                lon2 = np.asarray(nav["longitude"][:], dtype="float64")
                lat2 = np.asarray(nav["latitude"][:], dtype="float64")
                data = np.asarray(geo[var_name][:], dtype="float64")
                fill = float(np.asarray(geo[var_name].attrs.get("_FillValue", [-32767.0])).ravel()[0])
                scale = float(np.asarray(geo[var_name].attrs.get("scale_factor", [1.0])).ravel()[0])
                offset = float(np.asarray(geo[var_name].attrs.get("add_offset", [0.0])).ravel()[0])
                inbbox = (
                    (lon2 >= TAIHU_BBOX["lon_min"]) & (lon2 <= TAIHU_BBOX["lon_max"]) &
                    (lat2 >= TAIHU_BBOX["lat_min"]) & (lat2 <= TAIHU_BBOX["lat_max"])
                )
                block = np.where(inbbox, data * scale + offset, np.nan)
                mask = np.isfinite(block) & (block != fill) & (block > 0)
                values = block[mask]
                if values.size == 0:
                    results.append(empty_file_result(
                        rel, sha, "clean_modis_ocean_color", "METADATA_ONLY",
                        "轨道未覆盖太湖或无有效像元", 0))
                    return records, results, None
                st = summarize(values)
                records.append(make_record(
                    source_id="modis_aqua_chla_l2", source_file=rel, source_sha=sha,
                    source_locator=f"geophysical_data/{var_name}",
                    observed_at=observed_at, acquired_at=acquired_at,
                    spatial_id="TAIHU_BBOX",
                    variable_code="chla_retrieval", value=st["value"], unit=_CHLA_UNIT,
                    quality_flag="Q00" if st["value_count"] >= 5 else "Q10",
                    quality_status="valid" if st["value_count"] >= 5 else "review",
                    provenance_type="derived",
                    cleaner_name="clean_modis_ocean_color",
                    value_count=st["value_count"], value_min=st["value_min"],
                    value_max=st["value_max"], value_p50=st["value_p50"],
                    value_p90=st["value_p90"],
                    aux={"orbit_pixels_in_bbox": int(inbbox.sum()), "scale": scale,
                         "offset": offset, "product": "L2 OC swath"},
                    run_id=run_id))
                results.append(empty_file_result(
                    rel, sha, "clean_modis_ocean_color", "CLEANED",
                    f"L2 轨道叶绿素提取：{st['value_count']} 有效像元", 1))
                return records, results, None

            results.append(empty_file_result(
                rel, sha, "clean_modis_ocean_color", "METADATA_ONLY",
                "未识别的 MODIS 产品结构（缺 chlor_a/lat/lon 或导航组）", 0))
            return records, results, None
    except OSError as exc:
        msg = str(exc)
        reason = "HDF5 文件截断（truncated file）" if "truncated" in msg else f"打开失败: {msg[:80]}"
        results.append(empty_file_result(
            rel, sha, "clean_modis_ocean_color", "REJECTED", reason, 0))
        return records, results, None
    except Exception as exc:  # noqa: BLE001 —— 单文件失败不得中断全量
        results.append(empty_file_result(
            rel, sha, "clean_modis_ocean_color", "REJECTED",
            f"{type(exc).__name__}: {exc}"[:120], 0))
        return records, results, None


def run_clean_modis_ocean_color(files: pd.DataFrame, run_id: str, workers: int = 8):
    global _RUN_ID
    _RUN_ID = run_id
    tasks = [(r["relative_path"], r["sha256"]) for _, r in files.iterrows()]
    records, results = [], []

    chunks = [tasks[i::workers] for i in range(min(workers, len(tasks)))] or []
    if not chunks:
        return records_frame(records), file_results_frame(results)
    extras = []
    with ProcessPoolExecutor(max_workers=len(chunks)) as ex:
        for rec_chunk, res_chunk, extra_chunk in ex.map(_worker_modis, chunks):
            records.extend(rec_chunk)
            results.extend(res_chunk)
            extras.extend(extra_chunk)

    # 月度聚合：把逐日太湖 bbox 有效像元合并为月均值（provenance=derived）
    monthly, lineage = _aggregate_monthly_chla(extras, run_id)
    records.extend(monthly)
    if lineage:
        lin_df = pd.DataFrame(lineage,
                              columns=["month", "n_source_files", "source_files"])
        out_dir = WORK_DIR / "clean_modis_ocean_color"
        out_dir.mkdir(parents=True, exist_ok=True)
        lin_df.to_csv(out_dir / "lineage_monthly.csv", index=False, encoding="utf-8-sig")
    return records_frame(records), file_results_frame(results)


def _worker_modis(chunk):
    import final_cleaners as fc
    records, results, extras = [], [], []
    for rel, sha in chunk:
        recs, res, extra = fc._clean_one_modis_oc(rel, sha, fc._RUN_ID)
        records.extend(recs)
        results.extend(res)
        extras.append(extra)
    return records, results, extras


def _aggregate_monthly_chla(extras: list[dict | None], run_id: str):
    by_month: dict[str, list[float]] = {}
    day_count: dict[str, set] = {}
    files_of: dict[str, list[str]] = {}
    for extra in extras:
        if not extra:
            continue
        month = extra["month"]
        by_month.setdefault(month, []).extend(extra["values"])
        day_count.setdefault(month, set()).add(extra["date"])
        files_of.setdefault(month, []).append(extra["rel"])
    out, lineage = [], []
    for month in sorted(by_month):
        values = np.asarray(by_month[month], dtype="float64")
        st = summarize(values)
        if st["value_count"] == 0:
            continue
        n_days = len(day_count[month])
        rels = files_of[month]
        # 聚合记录的哈希语义：AGGREGATE: 前缀 + 血缘表定位
        agg_sha = "AGGREGATE:" + hashlib.sha256(
            f"modis_monthly:{month}".encode("utf-8")).hexdigest()[:32]
        lineage_ref = f"work/clean_modis_ocean_color/lineage_monthly.csv#month={month}"
        out.append(make_record(
            source_id="modis_aqua_chla", source_file=lineage_ref,
            source_sha=agg_sha, run_id=run_id,
            source_locator=f"monthly_aggregate[{month}]",
            observed_at=f"{month}-01", spatial_id="TAIHU_BBOX",
            variable_code="chla_retrieval", value=st["value"], unit=_CHLA_UNIT,
            quality_flag="Q00" if n_days >= 3 else "Q10",
            quality_status="valid" if n_days >= 3 else "review",
            provenance_type="derived", cleaner_name="clean_modis_ocean_color",
            value_count=st["value_count"], value_min=st["value_min"],
            value_max=st["value_max"], value_p50=st["value_p50"],
            value_p90=st["value_p90"],
            aux={"aggregate": "monthly", "n_days": n_days,
                 "n_source_files": len(rels),
                 "lineage_file": "work/clean_modis_ocean_color/lineage_monthly.csv",
                 "month": month,
                 "note": "月度聚合记录，成员文件清单见 lineage_monthly.csv"},
            ))
        lineage.append([month, len(rels), "|".join(rels)])
    return out, lineage


# ============================================================ MODIS 地表温度
def run_clean_modis_land_surface(files: pd.DataFrame, run_id: str):
    """MOD11A1 地表温度。

    实测结论：全部 2043 个文件均为 h28v05 瓦片（正弦投影 100-110°E），
    不覆盖太湖（太湖需要 h30v05），因此无法产生湖面观测值。
    逐文件记 METADATA_ONLY，并把瓦片不匹配写入已知限制。
    """
    records, results = [], []
    tile_re = re.compile(r"\.(h\d{2}v\d{2})\.")
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        m = tile_re.search(rel)
        tile = m.group(1) if m else ""
        if tile in LST_TILES_COVERING_TAIHU:
            results.append(empty_file_result(
                rel, sha, "clean_modis_land_surface", "METADATA_ONLY",
                "瓦片覆盖太湖但当前环境缺少 HDF4 驱动，仅登记元数据", 0))
            continue
        results.append(empty_file_result(
            rel, sha, "clean_modis_land_surface", "METADATA_ONLY",
            f"瓦片 {tile or '未知'} 不覆盖研究区（太湖需 h30v05），不产生观测记录", 0))
    return records_frame(records), file_results_frame(results)


# ============================================================ MEE 月度 PDF
def run_clean_mee_monthly_pdf(files: pd.DataFrame, run_id: str):
    """生态环境部地表水月报（扫描 PDF）。

    162 份 PDF 与 05 区解析表 mee_taihu_monthly_2022_2026.csv 按 SHA-256 精确
    匹配 162 份，沿用其页数与结构化字段，全部记 METADATA_ONLY（文档元数据）。
    数值记录必须在 OCR 置信度达标后才能产生（规划第 3 节规则 9）。
    """
    parsed_path = _abs("05_旧版整理区_混合留存/reports/mee_taihu_monthly_parsed/mee_taihu_monthly_2022_2026.csv")
    parsed = pd.read_csv(parsed_path, encoding="utf-8-sig") if parsed_path.exists() else pd.DataFrame()
    parsed_by_sha = {}
    if not parsed.empty and "pdf_sha256" in parsed.columns:
        for _, row in parsed.iterrows():
            parsed_by_sha[str(row["pdf_sha256"]).strip().lower()] = row

    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        month_m = re.search(r"(\d{4})-(\d{2})", rel)
        year, month = (month_m.group(1), month_m.group(2)) if month_m else ("", "")
        info = parsed_by_sha.get(sha.lower())
        if info is not None:
            notes = (f"与历史解析表按 SHA-256 匹配：{int(info.get('pdf_pages', 0))} 页，"
                     f"{info.get('year')}-{int(info['month']):02d} 期，"
                     f"主要超标指标={info.get('main_exceedance_indicators', '')}，"
                     f"全湖水质={info.get('whole_lake_status', '')}")
            doc = {"matched_by": "pdf_sha256", "year": str(info.get("year", "")),
                   "month": str(info.get("month", "")),
                   "pages": None if pd.isna(info.get("pdf_pages")) else int(info["pdf_pages"]),
                   "main_exceedance_indicators": "" if pd.isna(info.get("main_exceedance_indicators")) else str(info["main_exceedance_indicators"]),
                   "whole_lake_status": "" if pd.isna(info.get("whole_lake_status")) else str(info["whole_lake_status"]),
                   "trophic_assessment": "" if pd.isna(info.get("trophic_assessment")) else str(info["trophic_assessment"]),
                   "monitoring_point_count": None if pd.isna(info.get("monitoring_point_count")) else int(info["monitoring_point_count"]),
                   "pdf_url": "" if pd.isna(info.get("pdf_url")) else str(info["pdf_url"])}
        else:
            notes = "扫描 PDF 无文本层且无匹配的历史解析记录，仅保留文档元数据"
            doc = {"matched_by": "none", "year": year, "month": month}
        results.append(empty_file_result(
            rel, sha, "clean_mee_monthly_pdf", "METADATA_ONLY", notes, 0))
        records.append(make_record(
            source_id="mee_surface_water_monthly", source_file=rel, source_sha=sha,
            source_locator="document", observed_at=f"{year}-{month}-01" if year and month else "",
            variable_code="document", value=None, unit="",
            quality_flag="Q00", quality_status="metadata_only",
            provenance_type="derived", cleaner_name="clean_mee_monthly_pdf",
            aux=doc, run_id=run_id))
    return records_frame(records), file_results_frame(results)


# ============================================================ 隔离栅格复核
def run_review_quarantined_assets(files: pd.DataFrame, run_id: str):
    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        try:
            import rasterio
            with rasterio.open(_abs(rel)) as src:
                arr = src.read(1)
                nodata = src.nodata
                valid = np.isfinite(arr) if nodata is None or (isinstance(nodata, float) and math.isnan(nodata)) \
                    else np.isfinite(arr) & (arr != nodata)
                n_valid = int(valid.sum())
            if n_valid == 0:
                results.append(empty_file_result(
                    rel, sha, "review_quarantined_assets", "QUARANTINED",
                    "复核确认：整幅无有效像元（CLMS v1 产品返回空栅格），维持隔离", 0))
            else:
                st = summarize(arr[valid])
                records.append(make_record(
                    source_id="clms_lwq_300m", source_file=rel, source_sha=sha,
                    source_locator="band1", observed_at="",
                    longitude=None, latitude=None,
                    variable_code="chla_retrieval", value=st["value"], unit="mg/m3",
                    quality_flag="Q10", quality_status="review",
                    provenance_type="derived", cleaner_name="review_quarantined_assets",
                    value_count=st["value_count"], value_min=st["value_min"],
                    value_max=st["value_max"],
                    aux={"repaired_from_quarantine": True}, run_id=run_id))
                results.append(empty_file_result(
                    rel, sha, "review_quarantined_assets", "CLEANED",
                    f"复核发现 {n_valid} 个有效像元，恢复入表", 1))
        except Exception as exc:  # noqa: BLE001
            results.append(empty_file_result(
                rel, sha, "review_quarantined_assets", "QUARANTINED",
                f"无法读取（{type(exc).__name__}），维持隔离", 0))
    return records_frame(records), file_results_frame(results)


# ============================================================ 目录响应
def run_clean_catalog_responses(files: pd.DataFrame, run_id: str):
    """公开数据目录检索响应与门户探测页 → 来源元数据，不产生观测记录。"""
    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        meta: dict = {"category": "catalog_response"}
        try:
            path = _abs(rel)
            if r["sniffed_format"] == "json":
                payload = json.loads(path.read_text(encoding="utf-8-sig", errors="ignore"))
                if isinstance(payload, dict):
                    meta["top_keys"] = sorted(payload.keys())[:12]
                    for k in ("total", "pageNo", "pageSize", "code"):
                        if k in payload:
                            meta[k] = payload[k]
                    items = payload.get("rows") or payload.get("data") or payload.get("items") or []
                    meta["item_count"] = len(items) if isinstance(items, list) else None
                elif isinstance(payload, list):
                    meta["item_count"] = len(payload)
            notes = "目录/探测响应解析成功，仅作来源元数据"
        except Exception as exc:  # noqa: BLE001
            notes = f"解析失败（{type(exc).__name__}），保留原始文件元数据"
            meta["error"] = type(exc).__name__
        results.append(empty_file_result(
            rel, sha, "clean_catalog_responses", "METADATA_ONLY", notes, 0))
        records.append(make_record(
            source_id="data_portal_catalog", source_file=rel, source_sha=sha,
            source_locator="response", variable_code="document", value=None, unit="",
            quality_status="metadata_only", provenance_type="derived",
            cleaner_name="clean_catalog_responses", aux=meta, run_id=run_id))
    return records_frame(records), file_results_frame(results)


# ============================================================ 压缩包
def _rar_listing(rel: str) -> tuple[list[str], str]:
    """安全列出 RAR 成员。

    bsdtar 输出按本机代码页编码（中文 Windows 为 GBK），text=True 用 UTF-8 解码
    会把部分 CJK 文件名变成替换字符 �。这里以原始字节读取，依次尝试
    gb18030 / utf-8 解码，尽量恢复原始文件名。
    """
    proc = subprocess.run([BSDTAR, "-tf", str(_abs(rel))], capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode("gb18030", errors="replace").strip()[:120]
        return [], err, ""
    raw = proc.stdout
    text, used = "", ""
    for enc in ("gb18030", "utf-8"):
        try:
            text = raw.decode(enc)
            used = enc
            break
        except UnicodeDecodeError:
            continue
    if not used:
        text = raw.decode("utf-8", errors="replace")
        used = "utf-8(replace)"
    members = [ln for ln in text.splitlines() if ln.strip()]
    return members, "", used


def run_clean_bloom_archive(files: pd.DataFrame, run_id: str):
    """蓝藻压缩包：安全清点 + 标签来源判定，不解包到原始目录。"""
    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        members, err, enc = _rar_listing(rel)
        if err:
            results.append(empty_file_result(
                rel, sha, "clean_bloom_archive", "METADATA_ONLY",
                f"压缩包清点失败（{err}），保留文档元数据", 0))
            continue
        label_source = ""
        sample = [m for m in members if re.search(r"bloom|蓝藻|水华", m)]
        if sample:
            label_source = "remote_sensing_derived_bloom_product"
        results.append(empty_file_result(
            rel, sha, "clean_bloom_archive", "METADATA_ONLY",
            f"安全清点 {len(members)} 个成员；标签来源判定={label_source or '未识别'}", 0))
        records.append(make_record(
            source_id="bloom_archive", source_file=rel, source_sha=sha,
            source_locator="archive", variable_code="document", value=None, unit="",
            quality_status="metadata_only", provenance_type="derived",
            cleaner_name="clean_bloom_archive",
            label_source=label_source,
            label_quality="sample_product" if label_source else "",
            aux={"members": members[:20], "member_count": len(members),
                 "member_encoding": enc}, run_id=run_id))
    return records_frame(records), file_results_frame(results)


def run_inspect_data_archive(files: pd.DataFrame, run_id: str):
    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        members, err, enc = _rar_listing(rel)
        if err:
            results.append(empty_file_result(
                rel, sha, "inspect_data_archive", "METADATA_ONLY",
                f"压缩包清点失败（{err}）", 0))
            continue
        results.append(empty_file_result(
            rel, sha, "inspect_data_archive", "METADATA_ONLY",
            f"安全清点 {len(members)} 个成员（解压内容已在 03 分区留存，不重复落盘）", 0))
        records.append(make_record(
            source_id="thqbca_archive", source_file=rel, source_sha=sha,
            source_locator="archive", variable_code="document", value=None, unit="",
            quality_status="metadata_only", provenance_type="derived",
            cleaner_name="inspect_data_archive",
            aux={"member_count": len(members),
                 "sample_members": members[:10], "member_encoding": enc}, run_id=run_id))
    return records_frame(records), file_results_frame(results)


# ============================================================ zip 包裹的 netCDF
def _clean_one_zip_nc(rel: str, sha: str, run_id: str):
    import h5py
    path = RAW_ROOT / rel
    records, results = [], []
    month_m = re.search(r"(\d{4})_(\d{2})\.nc$", rel)
    try:
        with zipfile.ZipFile(path) as zf:
            inner = [n for n in zf.namelist() if n.endswith(".nc")]
            if not inner:
                results.append(empty_file_result(
                    rel, sha, "clean_zip_wrapped_netcdf", "REJECTED",
                    "zip 内无 .nc 成员", 0))
                return records, results
            payload = zf.read(inner[0])
        with h5py.File(io.BytesIO(payload), "r") as h:
            lat = np.asarray(h["latitude"][:], dtype="float64")
            lon = np.asarray(h["longitude"][:], dtype="float64")
            i, j = bbox_slice_indices(lat, lon)
            time_d = h["valid_time"][:]
            raw_units = h["valid_time"].attrs.get("units", b"")
            if isinstance(raw_units, np.ndarray):
                raw_units = raw_units.ravel()[0]
            units = raw_units.decode() if isinstance(raw_units, bytes) else str(raw_units)
            if "since" not in units:
                raise ValueError(f"valid_time 缺少时间基准 units: {units!r}")
            epoch_text = units.split("since", 1)[1].strip().strip("'\" ")
            unit_word = units.split("since", 1)[0].strip().lower()
            base_ts = pd.Timestamp(epoch_text).tz_localize(None)
            if unit_word.startswith("second"):
                base_ts = base_ts + pd.to_timedelta(0, unit="s")
                offsets = pd.to_timedelta(np.asarray(time_d, dtype="int64"), unit="s")
            elif unit_word.startswith("hour"):
                offsets = pd.to_timedelta(np.asarray(time_d, dtype="int64"), unit="h")
            elif unit_word.startswith("day"):
                offsets = pd.to_timedelta(np.asarray(time_d, dtype="int64"), unit="D")
            else:
                raise ValueError(f"不支持的时间单位: {unit_word!r}")
            data = np.asarray(h["lmlt"][:], dtype="float64")  # 形状 (time, lat, lon)
            block = data[:, i, :]
            lat_i = lat[i]
            lon_j = lon[j]
            fill = float(np.asarray(h["lmlt"].attrs.get("_FillValue", [np.nan])).ravel()[0])
            count = 0
            for t_idx in range(block.shape[0]):
                grid = block[t_idx]
                mask = np.isfinite(grid) & (grid != fill)
                if not mask.any():
                    continue
                vals = grid[mask] - 273.15  # K -> degC
                st = summarize(vals)
                ts = (base_ts + offsets[t_idx]).strftime("%Y-%m-%dT%H:%M:%S")
                records.append(make_record(
                    source_id="era5_lake_temp", source_file=rel, source_sha=sha,
                    source_locator=f"lmlt[t={t_idx}]",
                    observed_at=ts, spatial_id="TAIHU_BBOX",
                    longitude=float(lon_j.mean()), latitude=float(lat_i.mean()),
                    variable_code="lake_surface_temperature", value=st["value"], unit="degC",
                    quality_flag="Q00", quality_status="valid",
                    provenance_type="derived",
                    cleaner_name="clean_zip_wrapped_netcdf",
                    value_count=st["value_count"], value_min=st["value_min"],
                    value_max=st["value_max"],
                    aux={"unwrap": "zip->data_0.nc", "grib_param": 228008,
                         "time_units": units},
                    run_id=run_id))
                count += 1
        observed_note = f"解包 {inner[0]}，提取 {count} 个时次的湖温记录"
        results.append(empty_file_result(
            rel, sha, "clean_zip_wrapped_netcdf", "CLEANED", observed_note, count))
        return records, results
    except Exception as exc:  # noqa: BLE001
        results.append(empty_file_result(
            rel, sha, "clean_zip_wrapped_netcdf", "REJECTED",
            f"{type(exc).__name__}: {exc}"[:120], 0))
        return records, results


def run_clean_zip_wrapped_netcdf(files: pd.DataFrame, run_id: str):
    global _RUN_ID
    _RUN_ID = run_id
    records, results = [], []
    for _, r in files.iterrows():
        recs, res = _clean_one_zip_nc(r["relative_path"], r["sha256"], run_id)
        records.extend(recs)
        results.extend(res)
    return records_frame(records), file_results_frame(results)


# ============================================================ Sentinel-3 状态
def run_clean_sentinel3_status(files: pd.DataFrame, run_id: str):
    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        scene_count, note = None, ""
        try:
            payload = json.loads(_abs(rel).read_text(encoding="utf-8-sig"))
            scene_count = len(payload) if isinstance(payload, list) else None
            note = f"清单含 {scene_count} 个 OLCI 场景元数据，未下载任何栅格资产"
        except Exception as exc:  # noqa: BLE001
            note = f"清单解析失败（{type(exc).__name__}）"
        results.append(empty_file_result(
            rel, sha, "clean_sentinel3_status", "BLOCKED_AUTH",
            note + "；按规则记 BLOCKED_AUTH，不伪造影像", 0))
        records.append(make_record(
            source_id="sentinel3_olci", source_file=rel, source_sha=sha,
            source_locator="manifest", variable_code="document", value=None, unit="",
            quality_status="blocked_auth", provenance_type="derived",
            cleaner_name="clean_sentinel3_status",
            aux={"scene_count": scene_count, "block_reason": "asset_download_unavailable"},
            run_id=run_id))
    return records_frame(records), file_results_frame(results)


# ============================================================ 旧版混合整理区
_DERIVED_MARKERS = ("standardized", "cleaned", "silver", "parsed", "ocr_", "monthly_cleaned")


def run_classify_and_deduplicate_legacy(files: pd.DataFrame, run_id: str):
    """旧版整理区：先分类（raw/derived/metadata），再决定是否可入表。

    与主分区内容完全一致的文件已由清单阶段标记 DUPLICATE；此处再处理：
      - 已标准化的中间产物 → METADATA_ONLY（血缘证据，不重复入表，避免双计）
      - 可解析的原始响应（NASA POWER JSON 等）→ 解析入表
      - 其余 → METADATA_ONLY，理由写入 notes
    """
    records, results = [], []
    for _, r in files.iterrows():
        rel, sha = r["relative_path"], r["sha256"]
        low = rel.lower()
        fmt = r["sniffed_format"]
        if r["duplicate_count"] > 1 and not r["is_primary_copy"]:
            results.append(empty_file_result(
                rel, sha, "classify_and_deduplicate_legacy", "DUPLICATE",
                f"与主副本 {r['primary_copy_path']} 内容一致（SHA-256 相同）", 0))
            continue
        if any(m in low for m in _DERIVED_MARKERS):
            results.append(empty_file_result(
                rel, sha, "classify_and_deduplicate_legacy", "METADATA_ONLY",
                "历史清洗/解析中间产物：仅作血缘证据，不再次当作原始观测清洗（规划规则 6）", 0))
            records.append(make_record(
                source_id="legacy_intermediate", source_file=rel, source_sha=sha,
                source_locator="file", variable_code="document", value=None, unit="",
                quality_status="metadata_only", provenance_type="derived",
                cleaner_name="classify_and_deduplicate_legacy",
                aux={"classified": "derived"}, run_id=run_id))
            continue
        if fmt == "json" and "nasa_power" in low:
            recs, note = _parse_nasa_power(rel, sha, run_id)
            records.extend(recs)
            results.append(empty_file_result(
                rel, sha, "classify_and_deduplicate_legacy",
                "CLEANED" if recs else "METADATA_ONLY", note, len(recs)))
            continue
        results.append(empty_file_result(
            rel, sha, "classify_and_deduplicate_legacy", "METADATA_ONLY",
            f"旧版区文件（{fmt}）：无可靠解析模式，保留元数据与分类结论", 0))
        records.append(make_record(
            source_id="legacy_unclassified", source_file=rel, source_sha=sha,
            source_locator="file", variable_code="document", value=None, unit="",
            quality_status="metadata_only", provenance_type="derived",
            cleaner_name="classify_and_deduplicate_legacy",
            aux={"classified": "metadata", "sniffed_format": fmt}, run_id=run_id))
    return records_frame(records), file_results_frame(results)


def _parse_nasa_power(rel: str, sha: str, run_id: str):
    try:
        payload = json.loads(_abs(rel).read_text(encoding="utf-8-sig"))
        props = payload.get("properties", {}).get("parameter", {})
        if not props:
            return [], "NASA POWER 响应无 parameter 字段"
        year = payload.get("header", {}).get("year") or ""
        recs = []
        lat = payload.get("geometry", {}).get("coordinates", [None, None])[1]
        lon = payload.get("geometry", {}).get("coordinates", [None, None])[0]
        var_map = {"T2M": "air_temperature", "PRECTOTCORR": "precipitation",
                   "WS2M": "wind_speed_10m_adj", "ALLSKY_SFC_SW_DWN": "shortwave_radiation",
                   "RH2M": "relative_humidity"}
        for param, series in props.items():
            code = var_map.get(param, param.lower())
            unit = {"air_temperature": "degC", "precipitation": "mm/day",
                    "wind_speed_10m_adj": "m/s", "shortwave_radiation": "kWh/m2/day",
                    "relative_humidity": "%"}.get(code, "")
            for day, val in sorted(series.items()):
                if val is None or (isinstance(val, float) and not math.isfinite(val)):
                    continue
                try:
                    ts = pd.Timestamp(f"{year}-{day[:2]}-{day[2:]}")
                except (ValueError, TypeError):
                    continue
                recs.append(make_record(
                    source_id="nasa_power_hourly", source_file=rel, source_sha=sha,
                    source_locator=f"properties.parameter.{param}.{day}",
                    observed_at=ts.strftime("%Y-%m-%d"), spatial_id="TAIHU_BBOX",
                    longitude=lon, latitude=lat, variable_code=code,
                    value=float(val), unit=unit, quality_flag="Q00", quality_status="valid",
                    provenance_type="derived",
                    cleaner_name="classify_and_deduplicate_legacy",
                    aux={"legacy_partition": True, "nasa_parameter": param}, run_id=run_id))
        return recs, f"NASA POWER 解析 {len(recs)} 条记录"
    except Exception as exc:  # noqa: BLE001
        return [], f"解析失败（{type(exc).__name__}），仅保留元数据"
