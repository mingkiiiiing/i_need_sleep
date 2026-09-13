"""江苏省控入湖河流逐月水质（静态官方数据档案）。

数据来自江苏省提供的《太湖7个省控主要入湖河流2022年以来逐月数据.xlsx》，
经 scripts/parse_inflow_rivers.py 一次性转换为 backend/app/data/inflow_rivers_monthly.json
（392 行 = 7 断面 × 56 个月，2022-01 ~ 2026-08，无缺失）。

口径说明（与系统诚实披露约定一致）：
- 这是静态官方档案数据，月度节奏，不是实时采集轨；end_month 即数据终点，
  之后月份不存在、不推演、不插补。
- record_source 区分「省内例行监测」（~2024-09）与「省控融合终审」（2024-10 起）两段口径。
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).resolve().parent / "data" / "inflow_rivers_monthly.json"

# 数据集版本三口径（数据文件内字段 / 成功信封 / 错误信封）的唯一代码来源；
# 须与 JSON 内 "dataset_version" 逐字一致，静态档案禁止借用观察轨 OBSERVATION_VERSION。
INFLOW_DATASET_VERSION = "JIANGSU_INFLOW_RIVERS_V1_20260913"

# 卡片重点参数与展示单位（完整参数集见 JSON parameters 字段）
_CARD_PARAMS: tuple[tuple[str, str], ...] = (("tp", "TP"), ("nh3n", "NH₃-N"))

_lock = threading.Lock()


class InflowDataUnavailable(RuntimeError):
    """静态入湖河流数据文件缺失或损坏（部署完整性问题，禁止静默降级）。"""


@lru_cache(maxsize=1)
def _dataset() -> dict[str, Any]:
    with _lock:
        if not _DATA_PATH.exists():
            raise InflowDataUnavailable(f"入湖河流静态数据文件缺失：{_DATA_PATH}")
        try:
            return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise InflowDataUnavailable(f"入湖河流静态数据不可读：{exc}") from exc


def dataset_meta() -> dict[str, Any]:
    """数据集元信息（版本 / 来源 / 覆盖窗口 / 断面清单）。"""
    ds = _dataset()
    return {
        "dataset_version": ds["dataset_version"],
        "description": ds["description"],
        "source": ds["source"],
        "cadence": ds["cadence"],
        "start_month": ds["start_month"],
        "end_month": ds["end_month"],
        "month_count": ds["month_count"],
        "record_count": len(ds["records"]),
        "sections": ds["sections"],
        "parameters": ds["parameters"],
    }


def _class_order(wq_class: str) -> int:
    """水质类别排序权重：Ⅰ最好、Ⅴ最差；未知类别按最差处理（宁紧勿松）。"""
    rank = "ⅠⅡⅢⅣⅤ".find(wq_class)
    return rank if rank >= 0 else len("ⅠⅡⅢⅣⅤ")


def _mean_or_none(values: list[float | None]) -> float | None:
    """最近12个月均值；窗口内全为缺失时返回 None（JSON null），禁止伪装成 0.0。"""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


def summary() -> dict[str, Any]:
    """驾驶舱卡片口径：逐断面最新月实测值 + 统计摘要 + 全期水质类别分布。

    统计均为对既有官方记录的直接聚合（均值 / 计数），不做任何外推。
    """
    ds = _dataset()
    records: list[dict[str, Any]] = ds["records"]
    months = sorted({r["ym"] for r in records})

    by_section: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_section.setdefault(rec["section"], []).append(rec)

    sections_out: list[dict[str, Any]] = []
    for meta in ds["sections"]:
        rows = sorted(by_section.get(meta["section"], []), key=lambda r: r["ym"])
        if not rows:
            continue
        latest = rows[-1]
        last12 = rows[-12:]
        class_counts: dict[str, int] = {}
        for r in rows:
            class_counts[r["wq_class"]] = class_counts.get(r["wq_class"], 0) + 1
        iv_plus = sum(c for k, c in class_counts.items() if _class_order(k) >= _class_order("Ⅳ"))
        sections_out.append(
            {
                **meta,
                "record_count": len(rows),
                "latest": {
                    "ym": latest["ym"],
                    "wq_class": latest["wq_class"],
                    **{k: latest[k] for k, _ in _CARD_PARAMS},
                },
                "mean_last12": {
                    k: _mean_or_none([r[k] for r in last12]) for k, _ in _CARD_PARAMS
                },
                "class_counts": class_counts,
                "iv_plus_count": iv_plus,
            }
        )

    overall_classes: dict[str, int] = {}
    for rec in records:
        overall_classes[rec["wq_class"]] = overall_classes.get(rec["wq_class"], 0) + 1

    return {
        "as_of": ds["end_month"],
        **dataset_meta(),
        "sections": sections_out,
        "overall_class_counts": overall_classes,
        "iv_plus_count": sum(
            c for k, c in overall_classes.items() if _class_order(k) >= _class_order("Ⅳ")
        ),
    }


def monthly(section: str | None = None) -> dict[str, Any]:
    """逐月全序列（可选按断面过滤）；供明细查询与联调，卡片不消费此端点。"""
    ds = _dataset()
    records = ds["records"]
    if section:
        if section not in {m["section"] for m in ds["sections"]}:
            raise KeyError(section)
        records = [r for r in records if r["section"] == section]
    return {"meta": dataset_meta(), "records": records, "count": len(records)}
