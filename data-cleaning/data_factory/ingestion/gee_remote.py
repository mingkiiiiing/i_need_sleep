"""GEE 遥感特征提取 — 可选，auth 门控；首期为请求计划器 (taihugurad gee_extractor.py 重写式适配)。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SOURCE_ID = "gee_remote_features"


def build_plan(cfg: dict[str, Any], *, start: str, end: str) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    s2 = cfg.get("sentinel2", {})
    plan.append(
        {
            "task": "sentinel2_monthly_indices",
            "collection": s2.get("collection", "COPERNICUS/S2_SR_HARMONIZED"),
            "cloud_pct_max": s2.get("cloud_pct_max", 30),
            "buffer_m": s2.get("buffer_m", 500),
            "scale_m": s2.get("scale_m", 10),
            "indices": s2.get("indices", ["NDCI", "FAI"]),
            "date_range": [start, end],
            "note": "站点 500m 缓冲逐月中值合成；NDCI=(B5-B4)/(B5+B4)",
        }
    )
    lst = cfg.get("modis_lst", {})
    plan.append(
        {
            "task": "modis_lst_weekly",
            "collection": lst.get("collection", "MODIS/061/MOD11A1"),
            "band": lst.get("band", "LST_Day_1km"),
            "buffer_m": lst.get("buffer_m", 1000),
            "scale_m": lst.get("scale_m", 1000),
            "date_range": [start, end],
            "note": "按周均值，×0.02-273.15 转摄氏度",
        }
    )
    return plan


def run_gee_plan(config: dict[str, Any], *, start: str, end: str, out_dir: Path | None = None) -> dict[str, Any]:
    cfg = (config.get("realtime_sources") or {}).get("gee") or {}
    if not cfg.get("enabled", False):
        return {
            "status": "BLOCKED_AUTH",
            "command": "collect-realtime",
            "source_id": SOURCE_ID,
            "message": "gee.enabled=false（首期为计划器）。启用需 earthengine authenticate 并置 GEE_PROJECT_ID。",
            "plan": build_plan(cfg, start=start, end=end),
        }
    project = os.environ.get(cfg.get("project_env", "GEE_PROJECT_ID"), cfg.get("default_project", ""))
    if not project:
        return {"status": "BLOCKED_AUTH", "command": "collect-realtime", "source_id": SOURCE_ID, "message": "GEE_PROJECT_ID 未设置"}
    try:
        import ee  # noqa: F401 — 延迟导入，未安装/未认证时降级为 BLOCKED_AUTH

        ee.Initialize(project=project)
    except Exception as exc:  # noqa: BLE001
        return {"status": "BLOCKED_AUTH", "command": "collect-realtime", "source_id": SOURCE_ID, "message": f"earthengine 初始化失败: {exc}"}
    # 实际提取在后续版本实现；当前返回执行计划
    return {
        "status": "completed_plan_only",
        "command": "collect-realtime",
        "source_id": SOURCE_ID,
        "project": project,
        "plan": build_plan(cfg, start=start, end=end),
    }
