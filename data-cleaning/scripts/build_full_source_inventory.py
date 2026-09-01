# -*- coding: utf-8 -*-
"""阶段A：全量原始文件清点清单。

递归扫描原始数据根目录，对每个文件记录路径、大小、修改时间、全量 SHA-256、
magic bytes 真实格式、扩展名一致性、零字节、可读性、重复组与文件角色。

输出:
  <release>/manifests/source_file_inventory.csv
  <release>/manifests/duplicates.csv
  <release>/manifests/inventory_summary.json

用法:
  python scripts/build_full_source_inventory.py --release-id TAIHU_CLEAN_FINAL_V1_20260831
  python scripts/build_full_source_inventory.py --raw-root <路径> --workers 12
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]          # 项目完整汇总_2026-08-31/
DEFAULT_RAW_ROOT = PROJECT_ROOT / "02_全部原始数据"
RELEASE_BASE = HERE.parent / "storage" / "final_cleaned"

BEIJING = timezone(timedelta(hours=8))

# ----------------------------- 格式嗅探 -----------------------------
# (magic, 偏移, 格式名)
_BINARY_MAGIC = [
    (b"\x89HDF\r\n\x1a\n", 0, "hdf5"),
    (b"\x0e\x03\x13\x01", 0, "hdf4"),
    (b"CDF\x01", 0, "netcdf3_classic"),
    (b"CDF\x02", 0, "netcdf3_64bit_offset"),
    (b"CDF\x05", 0, "netcdf3_64bit_data"),
    (b"GRIB", 0, "grib"),
    (b"BUFR", 0, "bufr"),
    (b"II*\x00", 0, "tiff_le"),
    (b"MM\x00*", 0, "tiff_be"),
    (b"%PDF-", 0, "pdf"),
    (b"PK\x03\x04", 0, "zip_container"),
    (b"PK\x05\x06", 0, "zip_empty"),
    (b"PK\x07\x08", 0, "zip_spanned"),
    (b"Rar!\x1a\x07", 0, "rar"),
    (b"7z\xbc\xaf\x27\x1c", 0, "7z"),
    (b"\x89PNG\r\n\x1a\n", 0, "png"),
    (b"\xff\xd8\xff", 0, "jpeg"),
    (b"GIF8", 0, "gif"),
    (b"BM", 0, "bmp"),
    (b"SQLite format 3\x00", 0, "sqlite"),
    (b"PAR1", 0, "parquet"),
    (b"ARROW1", 0, "arrow_ipc"),
    (b"\x00\x00'\x0a", 0, "shapefile_shp"),
    (b"\x00\x00'\x0d", 0, "shapefile_shp"),
    (b"\x1f\x8b", 0, "gzip"),
    (b"BZh", 0, "bzip2"),
    (b"\xfd7zXZ\x00", 0, "xz"),
    (b"\xd0\xcf\x11\xe0", 0, "ole2_compound"),   # 旧版 xls/doc
]

# 扩展名 -> 期望的嗅探格式集合
_EXPECTED_FORMAT = {
    "nc": {"hdf5", "netcdf3_classic", "netcdf3_64bit_offset", "netcdf3_64bit_data"},
    "hdf": {"hdf4", "hdf5"},
    "h5": {"hdf5"},
    "he5": {"hdf5"},
    "hdf4": {"hdf4"},
    "tif": {"tiff_le", "tiff_be"},
    "tiff": {"tiff_le", "tiff_be"},
    "grib": {"grib"},
    "grib2": {"grib"},
    "grb": {"grib"},
    "grb2": {"grib"},
    "pdf": {"pdf"},
    "xlsx": {"zip_container"},
    "xlsm": {"zip_container"},
    "zip": {"zip_container", "zip_empty"},
    "rar": {"rar"},
    "7z": {"7z"},
    "png": {"png"},
    "jpg": {"jpeg"},
    "jpeg": {"jpeg"},
    "gif": {"gif"},
    "bmp": {"bmp"},
    "sqlite": {"sqlite"},
    "db": {"sqlite"},
    "gpkg": {"sqlite"},
    "parquet": {"parquet"},
    "shp": {"shapefile_shp"},
    "gz": {"gzip"},
    "bz2": {"bzip2"},
    "xz": {"xz"},
    "xls": {"ole2_compound"},
    "doc": {"ole2_compound"},
}

# 文本类扩展名，需用内容二次判定
_TEXT_EXT = {"json", "html", "htm", "xml", "csv", "txt", "md", "js", "yml", "yaml", "log", "curl_cookies"}

# 角色判定：路径关键字 -> 角色
_ROLE_RULES = [
    # (优先级, 关键字元组, 角色)
    (10, ("captcha", "验证码"), "temporary"),
    (10, ("quarantine", "隔离"), "quarantined"),
    (20, ("manifest", "inventory", "catalog", "index", "清单", "目录", "检索"), "metadata"),
    (20, ("readme", "说明", "字典", "报告", "report"), "metadata"),
    (30, ("cleaned", "clean", "silver", "gold", "processed", "derived", "outputs", "exports", "results"), "derived"),
    (40, (".tmp", "tmp", "temp", "~$", ".cache", "__pycache__", ".pytest_cache"), "temporary"),
]


def _long(p: str) -> str:
    """Windows 长路径前缀，避免超过 MAX_PATH 报错。"""
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(p)
    return p


def _sniff(head: bytes, ext: str) -> tuple[str, str]:
    """返回 (嗅探格式, 备注)。"""
    if not head:
        return "empty", "空文件或无法读取首字节"

    for magic, off, name in _BINARY_MAGIC:
        if head[off:off + len(magic)] == magic:
            return name, ""

    # 尝试按文本解析
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            text = head.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        return "unknown_binary", "既非已知二进制魔数也非可解码文本"

    stripped = text.lstrip("\ufeff").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json", ""
    low = stripped[:64].lower()
    if stripped.startswith("<") or "<html" in low or "<!doctype" in low:
        if stripped.startswith("<?xml") or low.startswith("<xml"):
            return "xml", ""
        return "html", ""
    # 表格文本：出现分隔符且有换行
    if ("," in text or "\t" in text or ";" in text) and "\n" in text:
        return "delimited_text", ""
    if text.isprintable() or text.replace("\n", "").replace("\r", "").replace("\t", "").isprintable():
        return "text", ""
    return "unknown_binary", "含不可打印字节且非已知格式"


def _sha256(path: str, chunk: int = 1 << 22) -> tuple[str, str]:
    h = hashlib.sha256()
    try:
        with open(_long(path), "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
    except Exception as exc:
        return "", f"HASH_ERROR:{type(exc).__name__}:{exc}"
    return h.hexdigest(), ""


def _probe_file(task: tuple[str, str]) -> dict:
    """单文件探测，供进程池调用。task=(rel_path, abs_path)。"""
    rel, abs_path = task
    rec = {
        "relative_path": rel,
        "file_name": os.path.basename(rel),
        "extension": "",
        "size_bytes": -1,
        "modified_at": "",
        "sha256": "",
        "sniffed_format": "",
        "ext_matches_sniff": "",
        "is_zero_byte": False,
        "is_readable": False,
        "file_role": "raw",
        "notes": "",
    }
    name = rec["file_name"]
    if "." in name:
        rec["extension"] = name.rsplit(".", 1)[1].lower()

    try:
        st = os.stat(_long(abs_path))
        rec["size_bytes"] = st.st_size
        rec["modified_at"] = datetime.fromtimestamp(st.st_mtime, BEIJING).isoformat(timespec="seconds")
    except Exception as exc:
        rec["notes"] = f"STAT_ERROR:{type(exc).__name__}"
        return rec

    if st.st_size == 0:
        rec["is_zero_byte"] = True
        rec["sniffed_format"] = "empty"
        rec["ext_matches_sniff"] = False
        rec["is_readable"] = False
        rec["notes"] = "零字节文件"
        rec["sha256"] = hashlib.sha256(b"").hexdigest()
        return rec

    # 读首字节嗅探
    try:
        with open(_long(abs_path), "rb") as f:
            head = f.read(8192)
        rec["is_readable"] = True
    except Exception as exc:
        rec["sniffed_format"] = "unreadable"
        rec["ext_matches_sniff"] = False
        rec["is_readable"] = False
        rec["notes"] = f"OPEN_ERROR:{type(exc).__name__}"
        return rec

    fmt, note = _sniff(head, rec["extension"])
    rec["sniffed_format"] = fmt
    if note:
        rec["notes"] = note

    # 扩展名一致性
    ext = rec["extension"]
    if ext in _EXPECTED_FORMAT:
        ok = fmt in _EXPECTED_FORMAT[ext]
    elif ext in _TEXT_EXT:
        ok = fmt in {"json", "html", "xml", "delimited_text", "text"}
    elif ext == "":
        ok = False
    else:
        ok = None  # 未知扩展名，不做判定
    rec["ext_matches_sniff"] = ok
    if ok is False:
        rec["notes"] = (rec["notes"] + "; " if rec["notes"] else "") + f"扩展名({ext or '无'})与真实格式({fmt})不一致"

    digest, herr = _sha256(abs_path)
    rec["sha256"] = digest
    if herr:
        rec["is_readable"] = False
        rec["notes"] = (rec["notes"] + "; " if rec["notes"] else "") + herr

    return rec


def _classify_role(rel: str, rec: dict) -> str:
    low = rel.lower()
    best = ("raw", 0)
    for prio, keys, role in _ROLE_RULES:
        for k in keys:
            if k in low:
                if prio > best[1]:
                    best = (role, prio)
                break
    return best[0]


def walk_files(raw_root: Path):
    """递归收集全部文件，返回 [(rel, abs)]。"""
    tasks = []
    root = str(raw_root)
    for dirpath, dirnames, filenames in os.walk(_long(root)):
        dirnames.sort()
        for fn in sorted(filenames):
            abs_p = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_p, _long(root))
            tasks.append((rel.replace("\\", "/"), abs_p.replace("\\\\?\\", "") if abs_p.startswith("\\\\?\\") else abs_p))
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段A：全量原始文件清点清单")
    ap.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT), help="原始数据根目录")
    ap.add_argument("--release-id", default="TAIHU_CLEAN_FINAL_V1_20260831")
    ap.add_argument("--release-base", default=str(RELEASE_BASE))
    ap.add_argument("--workers", type=int, default=0, help="并行进程数，0=自动")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 个文件（调试用）")
    args = ap.parse_args()

    raw_root = Path(args.raw_root)
    if not raw_root.exists():
        print(f"[错误] 原始数据根目录不存在: {raw_root}")
        return 2

    run_id = "TAIHU_CLEAN_RUN_" + datetime.now(BEIJING).strftime("%Y%m%dT%H%M%S%z")
    out_dir = Path(args.release_base) / args.release_id / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[阶段A] 原始数据根目录: {raw_root}")
    print(f"[阶段A] run_id = {run_id}")
    t0 = time.time()

    tasks = walk_files(raw_root)
    total = len(tasks)
    if args.limit:
        tasks = tasks[: args.limit]
        total = len(tasks)
    print(f"[阶段A] 发现文件 {total} 个，开始计算 SHA-256 …")

    workers = args.workers or max(4, min(16, (os.cpu_count() or 4)))
    records = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe_file, t): t for t in tasks}
        for fut in as_completed(futs):
            try:
                records.append(fut.result())
            except Exception as exc:
                rel = futs[fut][0]
                records.append({
                    "relative_path": rel, "file_name": os.path.basename(rel), "extension": "",
                    "size_bytes": -1, "modified_at": "", "sha256": "", "sniffed_format": "probe_failed",
                    "ext_matches_sniff": False, "is_zero_byte": False, "is_readable": False,
                    "file_role": "raw", "notes": f"PROBE_ERROR:{type(exc).__name__}:{exc}",
                })
            done += 1
            if done % 500 == 0 or done == total:
                el = time.time() - t0
                print(f"  进度 {done}/{total}  用时 {el:.0f}s", flush=True)

    # 分区与角色
    for r in records:
        parts = r["relative_path"].split("/")
        r["source_partition"] = parts[0] if len(parts) > 1 else ""
        r["file_role"] = _classify_role(r["relative_path"], r)

    # 重复组（按 sha256，跳过空哈希）
    from collections import Counter, defaultdict
    hash_counts = Counter(r["sha256"] for r in records if r["sha256"])
    dup_groups = {h for h, c in hash_counts.items() if c > 1}
    group_of = {}
    for h in sorted(dup_groups):
        group_of[h] = "DUP_" + h[:12]

    by_hash_first = {}
    for r in records:
        h = r["sha256"]
        if h in dup_groups:
            r["duplicate_group_id"] = group_of[h]
            r["duplicate_count"] = hash_counts[h]
            if h not in by_hash_first:
                by_hash_first[h] = r["relative_path"]
                r["is_primary_copy"] = True
            else:
                r["is_primary_copy"] = False
            r["primary_copy_path"] = by_hash_first[h]
        else:
            r["duplicate_group_id"] = ""
            r["duplicate_count"] = 1
            r["is_primary_copy"] = True
            r["primary_copy_path"] = r["relative_path"]

    cols = [
        "release_id", "run_id", "source_partition", "relative_path", "file_name", "extension",
        "size_bytes", "modified_at", "sha256", "sniffed_format", "ext_matches_sniff",
        "is_zero_byte", "is_readable", "duplicate_group_id", "duplicate_count",
        "is_primary_copy", "primary_copy_path", "file_role", "notes",
    ]
    for r in records:
        r["release_id"] = args.release_id
        r["run_id"] = run_id

    import pandas as pd
    df = pd.DataFrame(records)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols].sort_values(["source_partition", "relative_path"]).reset_index(drop=True)
    df.insert(0, "file_index", range(1, len(df) + 1))

    inv_path = out_dir / "source_file_inventory.csv"
    df.to_csv(inv_path, index=False, encoding="utf-8-sig")

    dup_df = df[df["duplicate_count"] > 1][
        ["duplicate_group_id", "sha256", "duplicate_count", "size_bytes",
         "is_primary_copy", "primary_copy_path", "relative_path", "source_partition", "file_role"]
    ].sort_values(["duplicate_group_id", "relative_path"])
    dup_path = out_dir / "duplicates.csv"
    dup_df.to_csv(dup_path, index=False, encoding="utf-8-sig")

    total_bytes = int(df["size_bytes"].clip(lower=0).sum())
    summary = {
        "release_id": args.release_id,
        "run_id": run_id,
        "raw_root": str(raw_root),
        "generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.time() - t0, 1),
        "file_count": int(len(df)),
        "total_bytes": total_bytes,
        "total_gb": round(total_bytes / (1024 ** 3), 2),
        "zero_byte_count": int(df["is_zero_byte"].sum()),
        "unreadable_count": int((~df["is_readable"].astype(bool)).sum()),
        "hash_error_count": int(df["sha256"].eq("").sum()),
        "duplicate_file_count": int((df["duplicate_count"] > 1).sum()),
        "duplicate_group_count": int(df.loc[df["duplicate_count"] > 1, "duplicate_group_id"].nunique()),
        "duplicate_wasted_bytes": int(
            df.loc[~df["is_primary_copy"].astype(bool), "size_bytes"].clip(lower=0).sum()
        ),
        "ext_mismatch_count": int(df["ext_matches_sniff"].eq(False).sum()),
        "by_partition": df.groupby("source_partition").agg(
            files=("file_index", "count"),
            bytes=("size_bytes", lambda s: int(s.clip(lower=0).sum())),
        ).reset_index().to_dict("records"),
        "by_format": df["sniffed_format"].value_counts().to_dict(),
        "by_extension": df["extension"].value_counts().head(40).to_dict(),
        "by_role": df["file_role"].value_counts().to_dict(),
        "by_partition_format": df.groupby(["source_partition", "sniffed_format"]).size()
        .reset_index(name="files").to_dict("records"),
    }
    sum_path = out_dir / "inventory_summary.json"
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 阶段A 完成 =====")
    print(f"文件总数        : {summary['file_count']}")
    print(f"总体积          : {summary['total_gb']} GB")
    print(f"零字节          : {summary['zero_byte_count']}")
    print(f"不可读          : {summary['unreadable_count']}")
    print(f"哈希失败        : {summary['hash_error_count']}")
    print(f"重复文件        : {summary['duplicate_file_count']} (共 {summary['duplicate_group_count']} 组)")
    print(f"扩展名不一致    : {summary['ext_mismatch_count']}")
    print(f"用时            : {summary['elapsed_seconds']}s")
    print(f"清单            : {inv_path}")
    print(f"重复清单        : {dup_path}")
    print(f"汇总            : {sum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
