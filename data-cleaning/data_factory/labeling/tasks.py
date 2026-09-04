"""标签生成 `build-labels` (设计 §6.13/§9 T1–T7 + 三态).

- SIM 真值标签：潜在真值层逐日逐任务（simulation_positive/negative 或 measured_value）
- REAL 观测标签：卫星/站点真实观测日生成（observed_* 或 unknown；缺证据不造负样本）
task_labels 为逐目标日真值表（horizon_days=0），装配阶段再按 T+h 展开样本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_factory.contracts.constants import utc_now_iso
from data_factory.contracts.enums import LAKE_ZONE_CODES, TASK_UNITS, LabelStatus
from data_factory.labeling.geometry import positive_cells_geojson, spatial_extent_label, write_geojson
from data_factory.labeling.thresholds import load_thresholds, risk_level_series, satellite_bloom_label

SIM_STATUS_BINARY = {1: LabelStatus.SIMULATION_POSITIVE.value, 0: LabelStatus.SIMULATION_NEGATIVE.value}
ZONES_IN_LAKE = [z for z in LAKE_ZONE_CODES if z != "TAIHU_WHOLE"]


def _base_row(task_id: str, spatial_id: str, spatial_type: str, target_date, th_id: str, batch_id: str, dataset: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "spatial_id": spatial_id,
        "spatial_type": spatial_type,
        "issue_date": target_date,
        "target_date": target_date,
        "label_status": None,
        "label_source_type": "simulation_truth",
        "label_quality": "pass",
        "horizon_days": 0,
        "is_ground_truth": False,
        "is_synthetic": True,
        "method_version": th_id,
        "domain_coverage_fraction": 1.0,
        "is_partial_domain": False,
        "evidence_record_ids": batch_id,
        "dataset_version": dataset,
    }


def _finish(rows: list[dict[str, Any]], label_value: Any, unit: str, status: str, source_type: str = "simulation_truth", quality: str = "pass", is_gt: bool = False, is_syn: bool = True) -> None:
    row = rows[-1]
    row["label_value"] = label_value
    row["label_unit"] = unit
    row["label_status"] = status
    row["label_source_type"] = source_type
    row["label_quality"] = quality
    row["is_ground_truth"] = is_gt
    row["is_synthetic"] = is_syn


def build_labels(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
    thresholds: dict[str, Any],
    dataset: str | None = None,
) -> dict[str, Any]:
    dataset = dataset or config.get("dataset_id", "mvp_meiliangwan_2024")
    th = load_thresholds(thresholds)
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))
    batch_id = sim_manifest["generation_batch_id"]
    zone_codes = list(sim_manifest["zones"])

    cells = pd.read_csv(base_dir / "grid" / "grid_metadata.csv")
    cells = cells[cells["zone_code"].isin(zone_codes)].sort_values("grid_id").reset_index(drop=True)
    grid_ids = cells["grid_id"].tolist()

    bloom_grid = pd.read_parquet(sim_dir / "bloom_grid_daily.parquet")
    bloom_lake = pd.read_parquet(sim_dir / "bloom_lake_daily.parquet")
    bloom_lake["date"] = pd.to_datetime(bloom_lake["date"])
    wq = pd.read_parquet(sim_dir / "latent" / f"water_quality_grid_daily_{zone_codes[0]}.parquet")
    wq["date"] = pd.to_datetime(wq["date"])
    bio = pd.read_parquet(sim_dir / "latent" / f"biomass_grid_daily_{zone_codes[0]}.parquet")
    bio["date"] = pd.to_datetime(bio["date"])

    dates = sorted(bloom_grid["date"].unique())
    frac = bloom_grid.pivot(index="date", columns="grid_id", values="bloom_fraction").reindex(columns=grid_ids)
    area_grid_km2 = bloom_grid.pivot(index="date", columns="grid_id", values="bloom_area_m2").reindex(columns=grid_ids) / 1.0e6
    chla = wq[wq["variable_code"] == "chlorophyll_a"].pivot(index="date", columns="grid_id", values="value").reindex(index=frac.index, columns=grid_ids)
    density = wq[wq["variable_code"] == "cyanobacteria_density"].pivot(index="date", columns="grid_id", values="value").reindex(index=frac.index, columns=grid_ids)
    biomass = bio.pivot(index="date", columns="grid_id", values="surface_biomass_mg_l").reindex(index=frac.index, columns=grid_ids)

    zone_area_km2 = {z: float(cells.loc[cells["zone_code"] == z, "effective_water_area_m2"].sum()) / 1.0e6 for z in zone_codes}
    lake_area_km2 = float(cells["effective_water_area_m2"].sum()) / 1.0e6
    zone_of_grid = cells.set_index("grid_id")["zone_code"]

    grid_tasks = list(config.get("assembly", {}).get("grid_tasks", ["T1", "T2", "T5"]))
    rows: list[dict[str, Any]] = []

    # ---- 网格级 SIM 真值 ----
    for date in frac.index:
        for grid_id in grid_ids:
            f = float(frac.at[date, grid_id])
            if "T1" in grid_tasks:
                binary = int(f >= th["grid_fraction_positive"])
                row = _base_row("T1", grid_id, "grid", date, th["threshold_set_id"], batch_id, dataset)
                rows.append(row)
                _finish(rows, binary, TASK_UNITS["T1"], SIM_STATUS_BINARY[binary])
            if "T2" in grid_tasks:
                value = round(float(area_grid_km2.at[date, grid_id]), 6)
                row = _base_row("T2", grid_id, "grid", date, th["threshold_set_id"], batch_id, dataset)
                rows.append(row)
                _finish(rows, value, TASK_UNITS["T2"], LabelStatus.MEASURED_VALUE.value)
            if "T5" in grid_tasks:
                value = round(float(chla.at[date, grid_id]), 6)
                row = _base_row("T5", grid_id, "grid", date, th["threshold_set_id"], batch_id, dataset)
                rows.append(row)
                _finish(rows, value, TASK_UNITS["T5"], LabelStatus.MEASURED_VALUE.value)

    # ---- 湖区/全湖 SIM 真值 ----
    zone_rows = bloom_lake[~bloom_lake["spatial_id"].isin(["TAIHU_WHOLE"])]
    lake_rows = bloom_lake[bloom_lake["spatial_id"] == "TAIHU_WHOLE"]
    zone_frac_mean = {z: g.set_index("date")["bloom_fraction_mean"] for z, g in zone_rows.groupby("spatial_id")}

    for level, area_series, area_threshold, spatial_type in (("zone", zone_rows, th["zone_area_km2_positive"], "zone"), ("lake", lake_rows, th["lake_area_km2_positive"], "lake")):
        if area_series.empty:
            continue
        area_by_date = area_series.set_index("date")["bloom_area_km2"]
        for date in frac.index:
            area_value = float(area_by_date.get(date, np.nan))
            if not np.isfinite(area_value):
                continue
            spatial_id = "TAIHU_WHOLE" if level == "lake" else zone_codes[0]
            binary = int(area_value >= area_threshold)
            row = _base_row("T1", spatial_id, spatial_type, date, th["threshold_set_id"], batch_id, dataset)
            rows.append(row)
            _finish(rows, binary, TASK_UNITS["T1"], SIM_STATUS_BINARY[binary])
            row = _base_row("T2", spatial_id, spatial_type, date, th["threshold_set_id"], batch_id, dataset)
            rows.append(row)
            _finish(rows, round(area_value, 6), TASK_UNITS["T2"], LabelStatus.MEASURED_VALUE.value)

            mean_of = lambda frame: float(frame.loc[date].mean()) if date in frame.index else np.nan
            for task_id, frame, unit in (("T3", density, TASK_UNITS["T3"]), ("T4", biomass, TASK_UNITS["T4"]), ("T5", chla, TASK_UNITS["T5"])):
                value = round(mean_of(frame), 6)
                row = _base_row(task_id, spatial_id, spatial_type, date, th["threshold_set_id"], batch_id, dataset)
                rows.append(row)
                _finish(rows, value, unit, LabelStatus.MEASURED_VALUE.value)

            if level == "zone":
                chla_series = chla.loc[date].mean()
                frac_series = float(zone_frac_mean.get(spatial_id, pd.Series(dtype=float)).get(date, np.nan))
            else:
                chla_series = float(chla.loc[date].mean())
                frac_series = float(area_value / max(lake_area_km2, 1e-9))
            risk = int(risk_level_series(np.array([chla_series]), np.array([frac_series]))[0])
            row = _base_row("T6", spatial_id, spatial_type, date, th["threshold_set_id"], batch_id, dataset)
            rows.append(row)
            _finish(rows, risk, TASK_UNITS["T6"], LabelStatus.MEASURED_VALUE.value, source_type="threshold_rule")

            mask = np.array([zone_of_grid.get(g) == spatial_id for g in grid_ids]) if level == "zone" else np.ones(len(grid_ids), dtype=bool)
            positive_mask = frac.loc[date].to_numpy() >= th["grid_fraction_positive"]
            extent = spatial_extent_label(positive_mask & mask, grid_ids)
            row = _base_row("T7", spatial_id, spatial_type, date, th["threshold_set_id"], batch_id, dataset)
            rows.append(row)
            _finish(rows, extent, TASK_UNITS["T7"], SIM_STATUS_BINARY[extent])

    # ---- REAL 观测标签（卫星 T1 / 站点 T3/T4/T5）----
    # DG-003：is_synthetic 必须从源观测传播（仿真卫星检索 → simulation_observed_* + is_synthetic=true），
    # 绝不硬编码身份
    satellite_path = base_dir / "observations" / "satellite_observations.parquet"
    n_sat_labels = 0
    if satellite_path.exists():
        satellite = pd.read_parquet(satellite_path)
        if "is_synthetic" not in satellite.columns:
            satellite["is_synthetic"] = False
        chla_sat = satellite[satellite["variable_code"] == "chla_retrieval"]
        joined = chla_sat.merge(cells[["grid_id", "zone_code"]], on="grid_id", how="left")
        joined["date"] = pd.to_datetime(joined["observed_time"]).dt.normalize()
        for spatial_type, group_key in (("zone", "zone_code"), ("lake", None)):
            if group_key is None:
                joined["spatial_id"] = "TAIHU_WHOLE"
            else:
                joined["spatial_id"] = joined[group_key]
            for (spatial_id, date), group in joined.groupby(["spatial_id", "date"]):
                binary = satellite_bloom_label(group["value"], th)
                source_syn = bool(group["is_synthetic"].fillna(False).astype(bool).any())
                if source_syn:
                    status = {1: LabelStatus.SIMULATION_OBSERVED_POSITIVE.value, 0: LabelStatus.SIMULATION_OBSERVED_NEGATIVE.value}.get(binary, LabelStatus.UNKNOWN.value)
                else:
                    status = {1: LabelStatus.OBSERVED_POSITIVE.value, 0: LabelStatus.OBSERVED_NEGATIVE.value}.get(binary, LabelStatus.UNKNOWN.value)
                row = _base_row("T1", spatial_id, spatial_type, date, th["threshold_set_id"], batch_id, dataset)
                rows.append(row)
                _finish(rows, binary if binary is not None else None, TASK_UNITS["T1"], status, source_type="satellite_observation", quality="warning", is_gt=False, is_syn=source_syn)
                n_sat_labels += 1

    station_path = base_dir / "observations" / "station_observations.parquet"
    n_station_labels = 0
    if station_path.exists():
        station = pd.read_parquet(station_path)
        if "is_synthetic" not in station.columns:
            station["is_synthetic"] = False
        real = station[(station["value_type"] == "observed") & station["value"].notna()]
        task_for_variable = {"chlorophyll_a": "T5", "cyanobacteria_density": "T3", "phytoplankton_biomass": "T4"}
        for variable, task_id in task_for_variable.items():
            subset = real[real["variable_code"] == variable]
            for row_obs in subset.itertuples(index=False):
                date = pd.Timestamp(row_obs.observed_time).normalize()
                row = _base_row(task_id, row_obs.station_id, "station", date, th["threshold_set_id"], batch_id, dataset)
                rows.append(row)
                # DG-003：身份从源观测传播；仿真站点观测不得标为真实 ground_truth
                source_syn = bool(row_obs.is_synthetic) if row_obs.is_synthetic is not None else False
                _finish(
                    rows,
                    round(float(row_obs.value), 6),
                    TASK_UNITS[task_id],
                    LabelStatus.MEASURED_VALUE.value,
                    source_type="station_observation",
                    quality="pass" if not source_syn else "warning",
                    is_gt=not source_syn,
                    is_syn=source_syn,
                )
                n_station_labels += 1

    labels = pd.DataFrame(rows)
    labels["issue_date"] = pd.to_datetime(labels["issue_date"])
    labels["target_date"] = pd.to_datetime(labels["target_date"])

    # DG-001：lake 粒度行的部分域覆盖率显式标注（grid/zone/station 行保持默认 1.0）
    if lake_rows.empty or "domain_coverage_fraction" not in lake_rows.columns:
        grid_manifest = json.loads((base_dir / "grid" / "grid_manifest.json").read_text(encoding="utf-8"))
        frozen = float(grid_manifest.get("lake_area_km2_frozen") or 0.0)
        lake_coverage = min(lake_area_km2 / frozen, 1.0) if frozen else 1.0
        lake_partial = lake_coverage < 0.9999
    else:
        lake_coverage = float(lake_rows["domain_coverage_fraction"].iloc[0])
        lake_partial = bool(lake_rows["is_partial_domain"].iloc[0])
    lake_mask = labels["spatial_type"] == "lake"
    labels.loc[lake_mask, "domain_coverage_fraction"] = round(lake_coverage, 6)
    labels.loc[lake_mask, "is_partial_domain"] = lake_partial

    out_dir = base_dir / "labels"
    out_dir.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(out_dir / "task_labels.parquet", index=False)

    # 几何证据：水华峰值日正网格 GeoJSON
    peak_date = frac.mean(axis=1).idxmax()
    evidence_path = None
    try:
        geo = positive_cells_geojson(cells, frac.loc[peak_date], th["grid_fraction_positive"], properties={"date": str(peak_date), "threshold_set_id": th["threshold_set_id"]})
        evidence_path = write_geojson(geo, out_dir / f"bloom_extent_{pd.Timestamp(peak_date).date()}.geojson")
    except Exception as exc:  # noqa: BLE001 - 证据导出失败不阻断标签
        evidence_path = f"failed: {exc}"

    status_counts = labels.groupby(["task_id", "label_status"]).size().to_dict()
    manifest = {
        "status": "completed",
        "command": "build-labels",
        "threshold_set_id": th["threshold_set_id"],
        "generation_batch_id": batch_id,
        "scenario_id": sim_manifest["scenario_id"],
        "random_seed": sim_manifest["random_seed"],
        "rows_written": int(len(labels)),
        "labels_by_task": {k: int(v) for k, v in labels.groupby("task_id").size().items()},
        "status_counts": {" | ".join(k): int(v) for k, v in status_counts.items()},
        "satellite_real_labels": int(n_sat_labels),
        "station_real_labels": int(n_station_labels),
        "lake_domain_coverage_fraction": round(lake_coverage, 6),
        "is_partial_domain": lake_partial,
        "peak_bloom_date": str(pd.Timestamp(peak_date).date()),
        "bloom_extent_geojson": evidence_path,
        "unknown_rule": "云遮/无过境/无采样 → unknown，绝不写负样本 (设计 §6.13)",
        "outputs": {"task_labels": str(out_dir / "task_labels.parquet")},
        "next_action": "python -m data_factory assemble --track SIM-V1",
    }
    (out_dir / "labels_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
