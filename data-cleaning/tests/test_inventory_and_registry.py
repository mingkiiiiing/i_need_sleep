# -*- coding: utf-8 -*-
"""阶段A/B 基础程序测试：全量清单与清洗器覆盖审计。

覆盖：正常样本、零字节、损坏文件、格式伪装、重复文件、临时文件、
锁文件、边界路径，以及覆盖率门槛（未匹配/多重匹配必须为 0）。
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PACKAGE_ROOT / "scripts"
INVENTORY = SCRIPTS / "build_full_source_inventory.py"
REGISTRY = SCRIPTS / "build_cleaner_registry.py"

HDF5 = b"\x89HDF\r\n\x1a\n" + b"\x00" * 64
HDF4 = b"\x0e\x03\x13\x01" + b"\x00" * 64
NC3 = b"CDF\x01" + b"\x00" * 64
TIFF = b"II*\x00" + b"\x00" * 64
GRIB = b"GRIB" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"%" * 64
RAR = b"Rar!\x1a\x07" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
ZIP = b"PK\x03\x04" + b"\x00" * 64


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def sample_raw_root(tmp_path: Path) -> Path:
    """构造一个覆盖各类边界情况的最小原始数据集。"""
    root = tmp_path / "02_全部原始数据"
    main = root / "01_当前主原始数据"
    # 正常 MODIS 海色 / 地表 / 气象 / 遥感
    (main / "ocean_color" / "modis_aqua_chla").mkdir(parents=True)
    (main / "ocean_color" / "modis_aqua_chla" / "A.20200101.L3m.nc").write_bytes(HDF5)
    (main / "land_surface" / "modis_lst").mkdir(parents=True)
    (main / "land_surface" / "modis_lst" / "MOD11A1.2020.hdf").write_bytes(HDF4)
    (main / "meteorology" / "noaa_gfs").mkdir(parents=True)
    (main / "meteorology" / "noaa_gfs" / "gfs_2020.grib").write_bytes(GRIB)
    (main / "earth_search_sentinel2" / "S2A_x").mkdir(parents=True)
    (main / "earth_search_sentinel2" / "S2A_x" / "B04.tif").write_bytes(TIFF)
    (main / "mee_surface_water_monthly").mkdir(parents=True)
    (main / "mee_surface_water_monthly" / "mee_2023-01.pdf").write_bytes(PDF)
    (main / "bloom" / "taihu_2019_rf").mkdir(parents=True)
    (main / "bloom" / "taihu_2019_rf" / "data.rar").write_bytes(RAR)
    (main / "meteorology" / "era5_lake_temp").mkdir(parents=True)
    (main / "meteorology" / "era5_lake_temp" / "era5_2020_01.nc").write_bytes(ZIP)
    (main / "static_geo").mkdir(parents=True)
    (main / "static_geo" / "dem.tif").write_bytes(TIFF)

    # 边界：零字节 / 格式伪装 / 损坏 / 重复 / 隐藏临时文件 / 锁文件
    (main / "ocean_color" / "modis_aqua_chla" / "broken.nc").write_bytes(b"")
    (main / "ocean_color" / "modis_aqua_chla" / "fake.nc").write_bytes(ZIP)
    (main / "ocean_color" / "modis_aqua_chla" / "corrupt.nc").write_bytes(b"\x01\x02\x03\x04\x05")
    dup_src = main / "earth_search_sentinel2" / "S2A_x" / "B04.tif"
    (main / "earth_search_sentinel2" / "S2A_x" / "B04_copy.tif").write_bytes(dup_src.read_bytes())
    (main / "land_surface" / "modis_lst" / ".curl_cookies").write_text("a\tb\n1\t2\n", encoding="utf-8")

    legacy = root / "05_旧版整理区_混合留存"
    (legacy / "water_quality").mkdir(parents=True)
    (legacy / "water_quality" / "~$book.xlsx").write_bytes(b"\x01" * 165)
    (legacy / "unknown" / "unclassified").mkdir(parents=True)
    (legacy / "unknown" / "unclassified" / "notes.txt").write_text("一些说明", encoding="utf-8")

    # 07 采集过程临时资料
    cap = root / "07_采集过程临时资料"
    cap.mkdir(parents=True)
    (cap / "captcha.jpg").write_bytes(JPEG)
    (cap / "captcha_empty.png").write_bytes(b"")

    # 04 / 06 分区
    cat = root / "04_公开数据目录检索原始响应"
    cat.mkdir(parents=True)
    (cat / "search_p1.json").write_text('{"total":1,"items":[]}', encoding="utf-8")
    src = root / "06_主数据采集与来源清单"
    src.mkdir(parents=True)
    (src / "sentinel2_cdse_2022.json").write_text('{"features":[]}', encoding="utf-8")

    return root


def test_inventory_covers_all_files_and_flags_anomalies(sample_raw_root: Path, tmp_path: Path) -> None:
    release_base = tmp_path / "release"
    proc = _run(INVENTORY, "--raw-root", str(sample_raw_root),
                "--release-base", str(release_base), "--workers", "2")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    out = release_base / "TAIHU_CLEAN_FINAL_V1_20260831" / "manifests"
    rows = _read_csv(out / "source_file_inventory.csv")
    by_rel = {r["relative_path"]: r for r in rows}

    # 全部文件都被清点（含隐藏文件与锁文件）
    assert len(rows) == 19, f"期望 19 个文件，实际 {len(rows)}"

    # 正常样本：格式识别正确、哈希非空、可读
    good = by_rel["01_当前主原始数据/ocean_color/modis_aqua_chla/A.20200101.L3m.nc"]
    assert good["sniffed_format"] == "hdf5"
    assert good["is_readable"] == "True"
    assert len(good["sha256"]) == 64

    # HDF4 / GRIB / PDF / RAR / TIFF 识别
    assert by_rel["01_当前主原始数据/land_surface/modis_lst/MOD11A1.2020.hdf"]["sniffed_format"] == "hdf4"
    assert by_rel["01_当前主原始数据/meteorology/noaa_gfs/gfs_2020.grib"]["sniffed_format"] == "grib"
    assert by_rel["01_当前主原始数据/mee_surface_water_monthly/mee_2023-01.pdf"]["sniffed_format"] == "pdf"
    assert by_rel["01_当前主原始数据/bloom/taihu_2019_rf/data.rar"]["sniffed_format"] == "rar"

    # 零字节必须被标记且不可读
    broken = by_rel["01_当前主原始数据/ocean_color/modis_aqua_chla/broken.nc"]
    assert broken["is_zero_byte"] == "True"
    assert broken["is_readable"] == "False"

    # 格式伪装：扩展名 nc 实为 zip 必须被识别为不一致
    fake = by_rel["01_当前主原始数据/ocean_color/modis_aqua_chla/fake.nc"]
    assert fake["sniffed_format"] == "zip_container"
    assert fake["ext_matches_sniff"] == "False"

    # 重复文件：同哈希成组（tif 三副本 / zip 双副本 / 空文件双副本），每组主副本唯一
    dups = _read_csv(out / "duplicates.csv")
    assert len(dups) == 7
    groups = {d["duplicate_group_id"] for d in dups}
    assert len(groups) == 3
    for gid in groups:
        members = [d for d in dups if d["duplicate_group_id"] == gid]
        assert sum(1 for m in members if m["is_primary_copy"] == "True") == 1

    tiff_primary = next(d for d in dups if d["relative_path"].endswith("B04.tif"))
    tiff_copy = next(d for d in dups if d["relative_path"].endswith("B04_copy.tif"))
    assert tiff_copy["duplicate_group_id"] == tiff_primary["duplicate_group_id"]
    assert tiff_copy["is_primary_copy"] == "False"
    assert tiff_copy["primary_copy_path"].endswith("B04.tif")

    # 零字节之间也按同哈希成组，但仍须全部标记为不可读
    empty_group = [d for d in dups if d["relative_path"].endswith("captcha_empty.png")]
    assert empty_group, "零字节文件应参与重复分组"

    # 汇总 JSON 字段齐全
    summary = json.loads((out / "inventory_summary.json").read_text(encoding="utf-8"))
    assert summary["file_count"] == 19
    assert summary["zero_byte_count"] == 2          # broken.nc + captcha_empty.png
    assert summary["duplicate_file_count"] == 7
    assert summary["duplicate_group_count"] == 3
    assert summary["hash_error_count"] == 0


def test_registry_assigns_unique_cleaner_and_blocks_on_gap(sample_raw_root: Path, tmp_path: Path) -> None:
    release_base = tmp_path / "release"
    assert _run(INVENTORY, "--raw-root", str(sample_raw_root),
                "--release-base", str(release_base), "--workers", "2").returncode == 0

    proc = _run(REGISTRY, "--release-base", str(release_base), "--require-full-coverage")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    out = release_base / "TAIHU_CLEAN_FINAL_V1_20260831" / "manifests"
    assign = {r["relative_path"]: r for r in _read_csv(out / "file_cleaner_assignment.csv")}

    assert len(assign) == 19
    # 每个文件都有清洗器，且无多重匹配
    assert all(r["cleaner_name"] != "UNMATCHED" for r in assign.values())
    assert all(r["is_multi_match"] == "False" for r in assign.values()), [
        r["relative_path"] for r in assign.values() if r["is_multi_match"] != "False"
    ]

    # 关键指派校验
    assert assign["01_当前主原始数据/ocean_color/modis_aqua_chla/A.20200101.L3m.nc"]["cleaner_name"] == "clean_modis_ocean_color"
    assert assign["01_当前主原始数据/land_surface/modis_lst/MOD11A1.2020.hdf"]["cleaner_name"] == "clean_modis_land_surface"
    assert assign["01_当前主原始数据/meteorology/era5_lake_temp/era5_2020_01.nc"]["cleaner_name"] == "clean_zip_wrapped_netcdf"
    assert assign["01_当前主原始数据/bloom/taihu_2019_rf/data.rar"]["cleaner_name"] == "clean_bloom_archive"
    assert assign["06_主数据采集与来源清单/sentinel2_cdse_2022.json"]["cleaner_name"] == "clean_source_registry"
    assert assign["04_公开数据目录检索原始响应/search_p1.json"]["cleaner_name"] == "clean_catalog_responses"

    # 例外：零字节 / 锁文件 / 临时资料 / 隐藏文件
    assert assign["01_当前主原始数据/ocean_color/modis_aqua_chla/broken.nc"]["cleaner_name"] == "exception_zero_byte"
    assert assign["01_当前主原始数据/ocean_color/modis_aqua_chla/broken.nc"]["expected_terminal_status"] == "REJECTED"
    # 不可识别的损坏文件不得进入有效数据
    assert assign["01_当前主原始数据/ocean_color/modis_aqua_chla/corrupt.nc"]["cleaner_name"] == "exception_unreadable"
    # zip 伪装的 .nc 归入解包流程，而非当作 netCDF 直接读取
    assert assign["01_当前主原始数据/ocean_color/modis_aqua_chla/fake.nc"]["cleaner_name"] == "clean_zip_wrapped_netcdf"
    assert assign["05_旧版整理区_混合留存/water_quality/~$book.xlsx"]["cleaner_name"] == "exception_lockfile"
    assert assign["01_当前主原始数据/land_surface/modis_lst/.curl_cookies"]["cleaner_name"] == "exception_temporary"
    assert assign["07_采集过程临时资料/captcha.jpg"]["cleaner_name"] == "exception_temporary"
    assert assign["07_采集过程临时资料/captcha_empty.png"]["cleaner_name"] == "exception_temporary"

    # 覆盖率汇总通过
    summary = json.loads((out / "coverage_summary.json").read_text(encoding="utf-8"))
    assert summary["coverage_ok"] is True
    assert summary["unmatched_files"] == 0
    assert summary["multi_match_files"] == 0

    # 规则表与覆盖表已生成
    rules = _read_csv(out / "cleaner_registry.csv")
    assert len(rules) >= 20
    assert _read_csv(out / "cleaner_coverage.csv")


def test_registry_reports_unmatched_as_failure(tmp_path: Path) -> None:
    """清单中出现无法匹配的文件时，--require-full-coverage 必须非零退出。"""
    release_base = tmp_path / "release"
    out = release_base / "TAIHU_CLEAN_FINAL_V1_20260831" / "manifests"
    out.mkdir(parents=True)
    with (out / "source_file_inventory.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "file_index", "relative_path", "source_partition", "sniffed_format",
            "extension", "size_bytes", "sha256", "is_zero_byte", "is_readable",
            "duplicate_count", "is_primary_copy", "file_role"])
        writer.writeheader()
        writer.writerow(dict(file_index=1, relative_path="09_未知分区/weird.xyz",
                             source_partition="09_未知分区", sniffed_format="sqlite",
                             extension="xyz", size_bytes=10, sha256="a" * 64,
                             is_zero_byte=False, is_readable=True,
                             duplicate_count=1, is_primary_copy=True, file_role="raw"))

    proc = _run(REGISTRY, "--release-base", str(release_base), "--require-full-coverage")
    assert proc.returncode == 1
    assert "UNMATCHED" in proc.stdout
