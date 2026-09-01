# -*- coding: utf-8 -*-
"""发布完整性回归测试。

可独立运行的单元测试（校验和清单往返、篡改检出）在任意环境执行；
依赖真实发布目录的断言在发布未构建时自动跳过（pytest.skip）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PACKAGE_ROOT))

from scripts.validate_final_release import (  # noqa: E402
    collect_release_files,
    regenerate_checksums,
    sha256_file,
    verify_checksums,
)

RELEASE_DIR = PACKAGE_ROOT / "storage" / "final_cleaned" / "TAIHU_CLEAN_FINAL_V1_20260831"


def _has_release() -> bool:
    return (RELEASE_DIR / "tables" / "taihu_clean_final_long.parquet").exists()


# ---------------------------------------------------------------- 单元测试
def test_checksum_manifest_roundtrip(tmp_path: Path) -> None:
    """重建清单后逐个复核，不匹配数必须为 0。"""
    (tmp_path / "tables").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "tables" / "a.parquet").write_bytes(b"abc")
    (tmp_path / "docs" / "b.md").write_text("hello", encoding="utf-8")
    regenerate_checksums(tmp_path)
    ok, mismatches = verify_checksums(tmp_path)
    assert ok, mismatches
    # 反向：新增未登记文件必须被检出
    (tmp_path / "docs" / "c.txt").write_text("new", encoding="utf-8")
    ok, mismatches = verify_checksums(tmp_path)
    assert not ok
    assert any("未登记" in m for m in mismatches)


def test_checksum_manifest_detects_tampering(tmp_path: Path) -> None:
    """篡改已登记文件必须被逐个复核检出（避免假阳性）。"""
    (tmp_path / "tables").mkdir()
    f = tmp_path / "tables" / "x.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    regenerate_checksums(tmp_path)
    ok, mismatches = verify_checksums(tmp_path)
    assert ok
    f.write_text("a,b\n9,9\n", encoding="utf-8")  # 篡改
    ok, mismatches = verify_checksums(tmp_path)
    assert not ok
    assert any("哈希不一致" in m for m in mismatches)
    # 篡改后重新登记校验和，必须能通过（自洽性）
    regenerate_checksums(tmp_path)
    ok, _ = verify_checksums(tmp_path)
    assert ok


def test_checksum_excludes_dynamic_and_flag_files(tmp_path: Path) -> None:
    """SHA256SUMS.txt / RELEASED / FAILED_QA / release_validation.json / attestation 不纳入校验和。"""
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "a.parquet").write_bytes(b"x")
    for name in ["SHA256SUMS.txt", "RELEASED", "FAILED_QA",
                 "release_validation.json", "RELEASE_ATTESTATION_SHA256.txt"]:
        (tmp_path / name).write_text("dummy", encoding="utf-8")
    regenerate_checksums(tmp_path)
    registered = {ln.strip().split("  ")[-1] for ln in
                  (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines() if ln.strip()}
    for name in ["SHA256SUMS.txt", "RELEASED", "FAILED_QA",
                 "release_validation.json", "RELEASE_ATTESTATION_SHA256.txt"]:
        assert name not in registered, f"{name} 不应进入校验和"


# ---------------------------------------------------------------- 发布断言
@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_release_checksums_verify_clean() -> None:
    ok, mismatches = verify_checksums(RELEASE_DIR)
    assert ok, mismatches
    assert len(mismatches) == 0


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_remote_sensing_thematic_coverage() -> None:
    """指定遥感来源在主表与专题表数量一致；专题表 = 247+14+70+504+72 = 907。"""
    main = pd.read_parquet(RELEASE_DIR / "tables" / "taihu_clean_final_long.parquet")
    rs_sources = ["modis_aqua_chla", "modis_aqua_chla_l2", "clms_lwq_300m",
                  "clms_lwq_300m_v2", "clms_lwq_300m_10daily_v2",
                  "sentinel2_cdse_monthly_30m"]
    main_rs = main[main["source_id"].isin(rs_sources)]
    rs_table = pd.read_parquet(RELEASE_DIR / "tables" / "remote_sensing.parquet")
    assert len(rs_table) == len(main_rs)
    assert len(rs_table) == 907, f"remote_sensing.parquet 应为 907 行，实际 {len(rs_table)}"
    for src in rs_sources:
        assert int(main[main["source_id"] == src].shape[0]) == int(rs_table[rs_table["source_id"] == src].shape[0]), \
            f"来源 {src} 主表与专题表数量不一致"


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_quality_summary_identity_and_fields() -> None:
    summary = json.loads(
        (RELEASE_DIR / "quality" / "data_quality_summary.json").read_text(encoding="utf-8"))
    assert summary["record_with_value"] + summary["record_missing_value"] == summary["record_count"]
    assert summary["record_with_value"] == 152575
    assert summary["record_missing_value"] == 205
    assert summary["time_validation_record_count"] == 151468
    assert summary["static_record_count"] == 1107
    assert summary["identity_check"] == "152575 + 205 = 152780"


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_single_valid_status_flag() -> None:
    flags = [p.name for p in RELEASE_DIR.iterdir() if p.name in {"RELEASED", "FAILED_QA"}]
    assert len(flags) == 1, f"根目录应只有一个状态标志，实际 {flags}"


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_modis_monthly_aggregates_use_agg_prefix() -> None:
    main = pd.read_parquet(RELEASE_DIR / "tables" / "taihu_clean_final_long.parquet")
    monthly = main[main["source_locator"].astype(str).str.startswith("monthly_aggregate[")]
    assert len(monthly) == 90, f"MODIS 月度聚合应为 90 条，实际 {len(monthly)}"
    assert monthly["source_file_sha256"].astype(str).str.startswith("AGGREGATE:").all(), \
        "月度聚合记录必须使用 AGGREGATE: 前缀"
    assert monthly["source_locator"].astype(str).str.fullmatch(
        r"monthly_aggregate\[\d{4}-\d{2}\]").all()


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_archive_aux_free_of_replacement_chars() -> None:
    """发布级回归：压缩包来源记录的 aux 不得含 Unicode 替换字符 U+FFFD。

    只验证清理函数是不够的——必须确认最终发布数据确实已被更新。
    """
    main = pd.read_parquet(RELEASE_DIR / "tables" / "taihu_clean_final_long.parquet")
    arch = main[main["source_id"].isin(["bloom_archive", "thqbca_archive"])]
    assert len(arch) == 2, f"应有 2 条压缩包记录，实际 {len(arch)}"
    for _, r in arch.iterrows():
        aux = str(r["aux"] or "")
        assert "\ufffd" not in aux, f"{r['source_id']} 的 aux 仍含替换字符"
        assert json.loads(aux).get("member_encoding"), f"{r['source_id']} 缺少 member_encoding"
    dirty = sum(1 for a in main["aux"] if "\ufffd" in str(a or ""))
    assert dirty == 0, f"主表仍有 {dirty} 条记录的 aux 含替换字符"


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_work_products_aux_free_of_replacement_chars() -> None:
    """工作产物（work/<cleaner>/records.parquet）同样不得含替换字符。"""
    for cleaner in ["clean_bloom_archive", "inspect_data_archive"]:
        path = RELEASE_DIR / "work" / cleaner / "records.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        dirty = sum(1 for a in df["aux"] if "\ufffd" in str(a or ""))
        assert dirty == 0, f"{cleaner} 工作产物有 {dirty} 条含替换字符"
        for aux in df["aux"]:
            assert json.loads(aux).get("member_encoding"), f"{cleaner} 缺少 member_encoding"


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_work_outputs_are_integrated_into_main_table() -> None:
    """工作产物的每条记录都必须出现在最终主表中，防止中间产物更新却未回灌。"""
    main = pd.read_parquet(RELEASE_DIR / "tables" / "taihu_clean_final_long.parquet")
    main_ids = set(main["record_id"].astype(str))
    checked = 0
    for cleaner_dir in sorted((RELEASE_DIR / "work").iterdir()):
        path = cleaner_dir / "records.parquet"
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_parquet(path)
        if df.empty:
            continue
        missing = set(df["record_id"].astype(str)) - main_ids
        assert not missing, f"{cleaner_dir.name} 有 {len(missing)} 条记录未进入主表"
        checked += len(df)
    assert checked > 0, "未检查到任何工作产物记录"


@pytest.mark.skipif(not _has_release(), reason="发布目录尚未构建")
def test_release_attestation_matches_validation_report() -> None:
    attest = (RELEASE_DIR / "RELEASE_ATTESTATION_SHA256.txt")
    report = (RELEASE_DIR / "quality" / "release_validation.json")
    assert attest.exists() and report.exists()
    line = next(ln for ln in attest.read_text(encoding="utf-8").splitlines()
                if ln.startswith("release_validation.json"))
    registered_hash = line.split()[-1]
    assert registered_hash == sha256_file(report)
