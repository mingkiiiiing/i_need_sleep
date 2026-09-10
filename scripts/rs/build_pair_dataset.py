"""遥感-地面配对数据集构建（field_samples × Sentinel-2 当月 / MODIS lwq300 ±3 天）。

配对规则（pair_rule_version=rs-pair-v1，写死在 pairs_manifest.json）：
- Sentinel-2 月度产品（30m CDSE / 20m）↔ 地面采样当月记录（月度聚合，天然 ±15 天内），
  空间取同代表点（IN_SITU_GROUP 样本在发布包中收敛为代表点 120.199083,31.247037，距离=0）；
- MODIS/CLMS lwq300 10 日产品（湖泊代表点 120.25,31.08~31.10）↔ 地面采样 ±3 天内最近过境；
  该产品为湖泊代表点口径，不做逐点距离筛除（距离如实记录并披露）；
- 地面 chla 为 ground_truth（μg/L）；反演值 provenance=remote_retrieval，永不成为观测真值。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "model_runtime_v0_3" / "code"))

from modeling_real.contracts_real import clean_tables_dir  # noqa: E402

PAIR_RULE_VERSION = "rs-pair-v1"
OUT_DIR = ROOT / "backend" / "model_runtime_v0_3" / "pair_dataset"
LAKE_CENTROID = (120.10, 31.20)
IN_SITU_REPRESENTATIVE = (120.199083, 31.247037)


def _aux_station(aux_value):
    if isinstance(aux_value, str):
        try:
            return json.loads(aux_value).get("station_id")
        except ValueError:
            return None
    return None


def haversine_km(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    d_lon = math.radians(lon_b - lon_a)
    d_lat = math.radians(lat_b - lat_a)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat_a)) * math.cos(math.radians(lat_b)) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def load_lwq_retrieval() -> pd.DataFrame:
    tables = clean_tables_dir()
    rs = pd.read_parquet(tables / "remote_sensing.parquet")
    ret = rs[rs["variable_code"] == "chla_retrieval"].copy()
    ret["observed_at"] = pd.to_datetime(ret["observed_at"])
    return ret.dropna(subset=["value"])


def load_s2_monthly() -> pd.DataFrame:
    tables = clean_tables_dir()
    md = pd.read_parquet(tables / "model_dataset.parquet")
    keep = md[["station_id", "month", "longitude", "latitude"]].copy()
    for col in (
        "rs_sentinel2_cdse_monthly_30m_MCI", "rs_sentinel2_cdse_monthly_30m_NDCI",
        "rs_sentinel2_monthly_20m_B04", "rs_sentinel2_monthly_20m_B05",
    ):
        keep[col] = pd.to_numeric(md[col], errors="coerce")
    return keep


def build_pairs() -> tuple[pd.DataFrame, dict]:
    tables = clean_tables_dir()
    wq = pd.read_parquet(tables / "water_quality.parquet")
    wq = wq[(wq["is_ground_truth"] == True) & (wq["variable_code"] == "chla")]  # noqa: E712
    wq = wq[wq["aux"].map(_aux_station).isin(("IN_SITU_GROUP", "S1"))]
    samples = pd.DataFrame({
        "station_id": wq["aux"].map(_aux_station),
        "observed_at": pd.to_datetime(wq["observed_at"]),
        "longitude": pd.to_numeric(wq["longitude"], errors="coerce"),
        "latitude": pd.to_numeric(wq["latitude"], errors="coerce"),
        "record_id": wq["record_id"],
        "label_chla_ug_l": pd.to_numeric(wq["value"], errors="coerce"),
    }).dropna(subset=["label_chla_ug_l"])
    samples["month"] = samples["observed_at"].dt.strftime("%Y-%m")
    lwq = load_lwq_retrieval()
    s2 = load_s2_monthly()

    pairs: list[dict] = []
    # ---- MODIS/CLMS lwq300：±3 天最近过境（湖泊代表点口径） ----
    for row in samples.itertuples(index=False):
        window = lwq[
            (lwq["observed_at"] >= row.observed_at - timedelta(days=3))
            & (lwq["observed_at"] <= row.observed_at + timedelta(days=3))
        ]
        if not len(window):
            continue
        nearest = window.iloc[
            (window["observed_at"] - row.observed_at).abs().argsort().iloc[0]
        ]
        lon_b = nearest["longitude"] if pd.notna(nearest["longitude"]) else LAKE_CENTROID[0]
        lat_b = nearest["latitude"] if pd.notna(nearest["latitude"]) else LAKE_CENTROID[1]
        lon_a = row.longitude if pd.notna(row.longitude) else IN_SITU_REPRESENTATIVE[0]
        lat_a = row.latitude if pd.notna(row.latitude) else IN_SITU_REPRESENTATIVE[1]
        pairs.append({
            "pair_id": f"modis-{row.record_id[:12]}",
            "sensor": "modis_lwq300_10daily",
            "retrieved_kind": "chla_retrieval_ug_l",
            "retrieved_value": float(nearest["value"]),
            "reference_value_ug_l": float(row.label_chla_ug_l),
            "station_id": row.station_id,
            "month": row.month,
            "sample_observed_at": row.observed_at.isoformat(),
            "rs_observed_at": nearest["observed_at"].isoformat(),
            "distance_km": round(haversine_km(lon_a, lat_a, lon_b, lat_b), 3),
            "pair_rule": "within_3d_nearest_pass_lake_representative_point",
            "pair_rule_version": PAIR_RULE_VERSION,
            "reference_provenance": "ground_truth",
            "retrieved_provenance": "remote_retrieval",
        })
    # ---- Sentinel-2 月度：当月记录（同代表点） ----
    for row in samples.itertuples(index=False):
        match = s2[(s2["station_id"] == row.station_id) & (s2["month"] == row.month)]
        if not len(match):
            continue
        entry = match.iloc[0]
        base = {
            "pair_id": f"s2-{row.record_id[:12]}",
            "sensor": None,
            "reference_value_ug_l": float(row.label_chla_ug_l),
            "station_id": row.station_id,
            "month": row.month,
            "sample_observed_at": row.observed_at.isoformat(),
            "rs_observed_at": f"{row.month}-01 (monthly composite)",
            "distance_km": 0.0,
            "pair_rule": "same_month_same_representative_station",
            "pair_rule_version": PAIR_RULE_VERSION,
            "reference_provenance": "ground_truth",
            "retrieved_provenance": "remote_retrieval",
        }
        mci = entry["rs_sentinel2_cdse_monthly_30m_MCI"]
        ndci = entry["rs_sentinel2_cdse_monthly_30m_NDCI"]
        b04, b05 = entry["rs_sentinel2_monthly_20m_B04"], entry["rs_sentinel2_monthly_20m_B05"]
        if pd.notna(mci):
            pairs.append({**base, "sensor": "s2_30m_mci", "retrieved_kind": "mci_index", "retrieved_value": float(mci)})
        if pd.notna(ndci):
            pairs.append({**base, "sensor": "s2_30m_ndci", "retrieved_kind": "ndci_index", "retrieved_value": float(ndci)})
        if pd.notna(b04) and pd.notna(b05) and (b05 + b04) != 0:
            ndci20 = (b05 - b04) / (b05 + b04)
            pairs.append({**base, "sensor": "s2_20m_ndci", "retrieved_kind": "ndci_index_20m", "retrieved_value": float(ndci20)})
    frame = pd.DataFrame(pairs)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT_DIR / "pairs.parquet", index=False)
    counts = frame.groupby("sensor").size().to_dict() if len(frame) else {}
    months = frame.groupby("sensor")["month"].nunique().to_dict() if len(frame) else {}
    manifest = {
        "pair_rule_version": PAIR_RULE_VERSION,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "rules": {
            "sentinel2_monthly": "S2 月度产品 ↔ 地面采样当月记录（月度聚合，天然 ±15 天内）；空间=同代表点（发布包中野外样本收敛为代表点，距离=0）",
            "modis_lwq300": "lwq300 10 日产品 ↔ 地面采样 ±3 天内最近过境；产品为湖泊代表点（120.25,31.08~31.10）口径，距离如实记录，不做逐点距离筛除",
        },
        "spatial_tolerance": "same_representative_station_or_lake_representative_point(distance_disclosed)",
        "reference_provenance": "ground_truth (water_quality.parquet chla, μg/L)",
        "retrieved_provenance": "remote_retrieval (never observed truth)",
        "field_sample_count": int(len(samples)),
        "pair_count_by_sensor": {k: int(v) for k, v in counts.items()},
        "distinct_months_by_sensor": {k: int(v) for k, v in months.items()},
        "pairs_sha256": hashlib.sha256(
            frame.to_csv(index=False).encode("utf-8")
        ).hexdigest() if len(frame) else None,
        "honesty_note": "配对数与月覆盖如实统计；S2 月度产品在航次月仅有单一合成值，跨月仿射拟合的自由度有限（见 calibration_manifest 披露）。",
    }
    (OUT_DIR / "pairs_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[pairs] rows={len(frame)} by_sensor={manifest['pair_count_by_sensor']}")
    return frame, manifest


if __name__ == "__main__":
    build_pairs()
