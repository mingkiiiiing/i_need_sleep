"""为 MEE 实时站点生成湖区归属映射（公示口径）。

MEE 站点目录没有湖区字段；本脚本按太湖八个惯用分区的公开参考质心做最近邻归属，
分区面积取公开常用口径并归一到太湖总面积 2338.4 km²（后续生物量面积加权使用）。
产物 backend/app/data/mee_station_zones.json 供预测快照层消费；
无可信坐标的站不归属（zone=null），在快照侧按"未归属"披露。

用法：python scripts/build_station_zones.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parents[1]
STATIONS_PATH = ROOT / "data-cleaning" / "storage" / "silver" / "mee_realtime" / "stations.json"
OUT_PATH = ROOT / "backend" / "app" / "data" / "mee_station_zones.json"

# 八个惯用分区：清洗包分区站代码同源；质心/面积为公开常用口径（四舍五入），
# 面积按太湖总面积 2338.4 km² 归一，仅用于面积加权，不用于边界判定。
LAKE_TOTAL_KM2 = 2338.4
LAKE_ZONES = {
    "TAIHU_ML": {"name": "梅梁湾", "lon": 120.155, "lat": 31.415, "area_km2": 124},
    "TAIHU_ZS": {"name": "竺山湖", "lon": 119.925, "lat": 31.395, "area_km2": 68},
    "TAIHU_GH": {"name": "贡湖", "lon": 120.345, "lat": 31.445, "area_km2": 147},
    "TAIHU_ET": {"name": "东太湖", "lon": 120.475, "lat": 31.195, "area_km2": 131},
    "TAIHU_CT": {"name": "东部沿岸", "lon": 120.475, "lat": 31.315, "area_km2": 268},
    "TAIHU_XK": {"name": "湖心区", "lon": 120.185, "lat": 31.235, "area_km2": 971},
    "TAIHU_ST": {"name": "南部沿岸", "lon": 120.135, "lat": 31.075, "area_km2": 279},
    "TAIHU_WT": {"name": "西部沿岸", "lon": 119.985, "lat": 31.295, "area_km2": 199},
}
PLOTTABLE_STATUS = {"verified", "metadata_only"}


def _distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """等距圆柱近似（太湖尺度足够）：纬度差 ×111.32，经度差 ×111.32×cos(31°)。"""
    klat = 111.32
    klon = 111.32 * math.cos(math.radians(31.0))
    return math.hypot((lon1 - lon2) * klon, (lat1 - lat2) * klat)


def main() -> int:
    raw = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    stations = raw if isinstance(raw, list) else raw.get("stations", [])
    area_sum = sum(z["area_km2"] for z in LAKE_ZONES.values())
    zones_out = {
        code: {
            "name": z["name"],
            "centroid": {"lon": z["lon"], "lat": z["lat"]},
            "area_km2_published": z["area_km2"],
            "area_km2_normalized": round(z["area_km2"] / area_sum * LAKE_TOTAL_KM2, 2),
        }
        for code, z in LAKE_ZONES.items()
    }
    assignments: dict[str, dict] = {}
    for st in stations:
        loc = st.get("location") or {}
        lon, lat = loc.get("lon"), loc.get("lat")
        entity_id = st.get("entity_id")
        if loc.get("location_status") not in PLOTTABLE_STATUS or lon is None or lat is None:
            assignments[entity_id] = {"zone_code": None, "zone_name": None, "reason": "missing_verified_coords"}
            continue
        best_code, best_dist = None, None
        for code, z in LAKE_ZONES.items():
            d = _distance_km(lon, lat, z["lon"], z["lat"])
            if best_dist is None or d < best_dist:
                best_code, best_dist = code, d
        assignments[entity_id] = {
            "zone_code": best_code,
            "zone_name": LAKE_ZONES[best_code]["name"],
            "distance_km": round(best_dist, 2),
        }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "nearest_published_subregion_centroid",
        "disclosure": (
            "MEE 站点目录无湖区字段；按公开常用分区质心最近邻归属（公示口径），"
            "分区面积按太湖总面积 2338.4 km² 归一，仅用于面积加权。无可信坐标的站不归属。"
        ),
        "lake_total_km2": LAKE_TOTAL_KM2,
        "zones": zones_out,
        "assignments": assignments,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    grouped: dict[str, int] = {}
    for a in assignments.values():
        grouped[a["zone_code"] or "unassigned"] = grouped.get(a["zone_code"] or "unassigned", 0) + 1
    print(f"[zones] {len(assignments)} stations → {OUT_PATH}")
    print(f"[zones] 分组: {grouped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
