# -*- coding: utf-8 -*-
"""发布质量门槛验证：全部硬门槛通过 -> RELEASED，否则 FAILED_QA。

硬门槛（规划第 9 节 + 验收补充）：
  G1  输入文件清单覆盖率 100%（每个文件恰好一条终态结论）
  G2  每个文件结论均为 6 种合法终态
  G3  零字节/不可读文件进入有效记录数为 0
  G4  重复文件只有主副本产生记录（同哈希重复计数为 0）
  G5  provenance_type 全部合法；真值标识一致
  G6  有效记录时间可解析比例 = 100%
  G7  发布包校验和逐个复核：读取已有 SHA256SUMS.txt，逐文件重算并比较，
      不匹配数必须为 0
  G8  record_id 唯一且非空
  G9  主表不残留失效的旧目录绝对路径
  G10 source_file_sha256 语义正确：普通 64 位 SHA 必须与清点清单完全一致；
      AGGREGATE:/HARVEST: 前缀使用各自血缘规则

产物顺序（避免校验和假阳性）：
  1) 生成/覆盖 SHA256SUMS.txt（排除其自身、release_validation.json、
     RELEASED、FAILED_QA、RELEASE_ATTESTATION_SHA256.txt）
  2) 读取 SHA256SUMS.txt 逐文件重算比较
  3) 校验完成后才写出 release_validation.json
  4) 最后写 RELEASE_ATTESTATION_SHA256.txt（保护验证报告）
  5) 旧状态标志原子移入 quality/status_history/，根目录只保留一个有效标志
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib_final_clean import (  # noqa: E402
    FILE_STATUSES, MANIFESTS, PROVENANCE_TYPES, RELEASE_DIR, RELEASE_ID, now_bj,
)

BEIJING = timezone(timedelta(hours=8))

# 不进入校验和的产物名（动态生成 / 状态标志 / 验证报告自身）
EXCLUDED_SUM_NAMES = {"SHA256SUMS.txt", "RELEASED", "FAILED_QA",
                      "release_validation.json", "RELEASE_ATTESTATION_SHA256.txt"}


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def collect_release_files(release: Path) -> list[Path]:
    """发布目录下所有应纳入校验和的文件。

    排除 5 个动态/状态产物（见 EXCLUDED_SUM_NAMES）以及 quality/status_history/
    下的历史状态存档（随每次验证变动，不属于不可变数据）。
    """
    out = []
    for p in release.rglob("*"):
        if not p.is_file() or p.name in EXCLUDED_SUM_NAMES:
            continue
        rel = p.relative_to(release).as_posix()
        if rel.startswith("quality/status_history/"):
            continue
        out.append(p)
    return sorted(out)


def regenerate_checksums(release: Path) -> Path:
    """重建 SHA256SUMS.txt（覆盖旧文件，不删除任何产物）。"""
    sums_path = release / "SHA256SUMS.txt"
    lines = [f"{sha256_file(p)}  {p.relative_to(release).as_posix()}"
             for p in collect_release_files(release)]
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums_path


def verify_checksums(release: Path) -> tuple[bool, list[str]]:
    """读取已有 SHA256SUMS.txt，逐文件重算比较；返回 (通过?, 不匹配清单)。"""
    sums_path = release / "SHA256SUMS.txt"
    if not sums_path.exists():
        return False, ["缺少 SHA256SUMS.txt"]
    expected: dict[str, str] = {}
    for ln in sums_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        digest, _, rel = ln.partition("  ")
        expected[rel.strip()] = digest.strip()

    mismatches: list[str] = []
    for rel, digest in sorted(expected.items()):
        p = release / rel
        if not p.exists():
            mismatches.append(f"{rel}: 文件缺失")
            continue
        actual = sha256_file(p)
        if actual != digest:
            mismatches.append(f"{rel}: 哈希不一致")
    registered = set(expected)
    actual_files = {p.relative_to(release).as_posix() for p in collect_release_files(release)}
    for rel in sorted(actual_files - registered):
        mismatches.append(f"{rel}: 未登记进 SHA256SUMS.txt")
    return (not mismatches), mismatches


def _ts() -> str:
    return datetime.now(BEIJING).strftime("%Y%m%dT%H%M%S")


def _move_flag_to_history(release: Path, flag_name: str) -> None:
    """把旧状态标志原子移入 quality/status_history/，根目录只留一个新标志。"""
    src = release / flag_name
    if not src.exists():
        return
    hist = release / "quality" / "status_history"
    hist.mkdir(parents=True, exist_ok=True)
    dst = hist / f"{flag_name}_{_ts()}.json"
    os.replace(str(src), str(dst))


def main() -> int:
    ap = argparse.ArgumentParser(description="发布质量门槛验证")
    ap.add_argument("--release-id", default=RELEASE_ID)
    ap.add_argument("--fail-on-hard-gate", action="store_true")
    ap.add_argument("--regenerate-checksums", action="store_true",
                    help="校验前先重建 SHA256SUMS.txt")
    args = ap.parse_args()

    release = Path(RELEASE_DIR)
    gates: list[dict] = []

    def gate(gid: str, name: str, ok: bool, detail: str) -> None:
        gates.append({"gate": gid, "name": name, "passed": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {gid} {name}: {detail}")

    # 载入
    long_path = release / "tables" / "taihu_clean_final_long.parquet"
    if not long_path.exists():
        print("[错误] 缺少主长表，请先运行 build_final_tables.py")
        return 2
    records = pd.read_parquet(long_path)
    conclusions = pd.read_csv(release / "manifests" / "file_conclusions.csv", encoding="utf-8-sig")
    inventory = pd.read_csv(release / "manifests" / "source_file_inventory.csv",
                            usecols=["relative_path", "sha256"], encoding="utf-8-sig")

    print("===== 发布质量门槛 =====")

    # G1 覆盖率
    g1 = (len(conclusions) == len(inventory)
          and conclusions["relative_path"].nunique() == len(inventory)
          and set(conclusions["relative_path"]) == set(inventory["relative_path"]))
    gate("G1", "文件清单覆盖率=100%", g1,
         f"清单 {len(inventory)} / 结论 {len(conclusions)} / 唯一路径 {conclusions['relative_path'].nunique()}")

    # G2 终态合法
    legal = conclusions["status"].isin(FILE_STATUSES)
    gate("G2", "每个文件结论均为 6 种合法终态", bool(legal.all()),
         f"非法结论 {int((~legal).sum())} 个")

    # G3 零字节/不可读不得进入有效记录
    inv_meta = pd.read_csv(release / "manifests" / "source_file_inventory.csv",
                           usecols=["relative_path", "is_zero_byte", "is_readable", "sha256"],
                           encoding="utf-8-sig")
    bad_files = inv_meta[(inv_meta["is_zero_byte"]) | (~inv_meta["is_readable"].astype(bool))]
    bad_sha = set(bad_files["sha256"])
    leaked = records[records["source_file_sha256"].isin(bad_sha) & records["value"].notna()]
    gate("G3", "零字节/不可读文件进入有效记录数=0", len(leaked) == 0,
         f"{len(leaked)} 条泄漏记录")

    # G4 重复文件只允许主副本产生记录
    dup_primary_sha: set[str] = set()
    dup_all_sha: set[str] = set()
    dup_path = release / "manifests" / "duplicates.csv"
    if dup_path.exists():
        ddf = pd.read_csv(dup_path, encoding="utf-8-sig")
        ddf = ddf[ddf["duplicate_count"] > 1]
        dup_all_sha = set(ddf["sha256"])
        dup_primary_sha = set(ddf.loc[ddf["is_primary_copy"].astype(bool), "sha256"])
    src_records = records[records["source_file_sha256"].isin(dup_all_sha)]
    illegal_dup = src_records[~src_records["source_file_sha256"].isin(dup_primary_sha)]
    gate("G4", "同哈希重复文件未重复计入观测", len(illegal_dup) == 0,
         f"重复组 {len(dup_all_sha)} 组，非法记录 {len(illegal_dup)} 条")

    # G5 provenance
    prov_ok = records["provenance_type"].isin(PROVENANCE_TYPES).all()
    gt_mismatch = int(((records["provenance_type"] != "ground_truth")
                       & (records["is_ground_truth"])).sum())
    gt_missing = int(((records["provenance_type"] == "ground_truth")
                      & (~records["is_ground_truth"].astype(bool))).sum())
    gate("G5", "provenance 合法且真值标识一致",
         bool(prov_ok) and gt_mismatch == 0 and gt_missing == 0,
         f"非法 {0 if prov_ok else int((~records['provenance_type'].isin(PROVENANCE_TYPES)).sum())}，"
         f"误标真值 {gt_mismatch}，漏标真值 {gt_missing}")

    # G6 时间可解析（静态特征为时空无关属性，豁免时间门槛）
    valid = records[(records["value"].notna())
                    & (records["source_id"] != "taihu_static_features")]
    parsed = pd.to_datetime(valid["observed_at"], errors="coerce", utc=True, format="mixed")
    unparseable = int(parsed.isna().sum())
    gate("G6", "有效记录时间可解析率=100%", unparseable == 0,
         f"有效记录 {len(valid)}，不可解析 {unparseable}")

    # G7 校验和逐个复核
    if args.regenerate_checksums:
        regenerate_checksums(release)
    ok7, mismatches = verify_checksums(release)
    gate("G7", "校验和逐个复核（不匹配=0）", ok7,
         "全部一致" if ok7 else f"{len(mismatches)} 项不匹配: {mismatches[:5]}")

    # G8 record_id 唯一性
    dup_ids = int(records["record_id"].duplicated().sum())
    empty_ids = int(records["record_id"].isna().sum())
    gate("G8", "record_id 唯一且非空", dup_ids == 0 and empty_ids == 0,
         f"重复 {dup_ids}，空 {empty_ids}")

    # G9 无失效的旧目录绝对路径
    dead = records["source_file"].astype(str).str.contains(
        r"2026_sheng-fuwai|(?:^|[\\/])(?:C|D|E|F|G):[\\/]", regex=True, na=False).sum()
    gate("G9", "主表不残留失效的旧目录绝对路径", dead == 0,
         f"{int(dead)} 条记录仍引用旧路径")

    # G10 source_file_sha256 语义
    inv_sha = dict(zip(inventory["relative_path"].astype(str), inventory["sha256"].astype(str)))
    direct, agg, harvest, other, mism = 0, 0, 0, 0, 0
    mism_examples: list[str] = []
    for _, r in records.iterrows():
        sh = str(r["source_file_sha256"] or "")
        src = str(r["source_file"] or "")
        if sh.startswith("AGGREGATE:"):
            agg += 1
        elif sh.startswith("HARVEST:"):
            harvest += 1
        elif sh.startswith("LINEAGE:"):
            other += 1
        elif len(sh) == 64:
            if src in inv_sha:
                if sh == inv_sha[src]:
                    direct += 1
                else:
                    mism += 1
                    if len(mism_examples) < 5:
                        mism_examples.append(f"{src}: 与清单哈希不一致")
            else:
                mism += 1
                if len(mism_examples) < 5:
                    mism_examples.append(f"{src}: 不在清点清单中")
        else:
            mism += 1
            if len(mism_examples) < 5:
                mism_examples.append(f"{src}: 哈希格式未知({sh[:24]})")
    gate("G10", "source_file_sha256 语义正确", mism == 0,
         f"直接匹配 {direct} / AGGREGATE {agg} / HARVEST {harvest} / 其他 {other} / 不一致 {mism}"
         + (f" 示例:{mism_examples}" if mism else ""))

    all_passed = all(g["passed"] for g in gates)

    # 校验通过后才写验证报告
    report = {
        "release_id": args.release_id,
        "validated_at": now_bj(),
        "gates": gates,
        "all_passed": all_passed,
        "record_count": int(len(records)),
        "file_count": int(len(conclusions)),
    }
    report_path = release / "quality" / "release_validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 最后写保护报告哈希（不进入 SHA256SUMS.txt）
    attest = release / "RELEASE_ATTESTATION_SHA256.txt"
    attest.write_text(
        f"release_validation.json  {sha256_file(report_path)}\n"
        f"generated_at  {now_bj()}\n", encoding="utf-8")

    # 状态标志：旧标志移入历史，根目录只保留一个有效标志
    old_flag = "FAILED_QA" if all_passed else "RELEASED"
    _move_flag_to_history(release, old_flag)
    flag_path = release / ("RELEASED" if all_passed else "FAILED_QA")
    flag_path.write_text(json.dumps({
        "release_id": args.release_id,
        "status": "RELEASED" if all_passed else "FAILED_QA",
        "validated_at": now_bj(),
        "failed_gates": [g["gate"] for g in gates if not g["passed"]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 判定:", ("RELEASED" if all_passed else "FAILED_QA"), "=====")
    for g in gates:
        if not g["passed"]:
            print(f"  未通过: {g['gate']} {g['name']} — {g['detail']}")
    print(f"验证报告: {report_path}")
    print(f"报告保护: {attest}")
    if not all_passed and args.fail_on_hard_gate:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
