"""仿真编排器 `simulate` (设计 §6 两层世界·潜在真值层).

单次前向：气象 → 水温/水量 → 2-pass 营养盐⇄藻类耦合 → 输运 → 水华 → 落盘。
确定性：单 seed → SeedSequence 逐流派生（zone 维再派生）；浮点 round(6) 落盘。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_factory import CONTRACT_VERSION, GENERATOR_VERSION
from data_factory.contracts.constants import run_dir, yaml_path
from data_factory.contracts.spatial import load_grid
from data_factory.lineage.hashing import content_hash
from data_factory.simulation import algae, bloom, hydrology, nutrients, transport, weather
from data_factory.simulation.rng import STREAM_KEYS, spatial_modes

WATER_VARIABLES = [
    "total_phosphorus",
    "total_nitrogen",
    "ammonia_nitrogen",
    "phosphate_phosphorus",
    "nitrate_nitrogen",
    "nitrite_nitrogen",
    "dissolved_oxygen",
    "pH",
    "turbidity",
    "secchi_depth",
    "cod_mn",
    "chlorophyll_a",
    "cyanobacteria_density",
    "water_temperature",
]


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def zone_rngs(seed: int, zone_index: int) -> dict[str, np.random.Generator]:
    return {
        key: np.random.default_rng(np.random.SeedSequence([int(seed), int(zone_index), i]))
        for i, key in enumerate(STREAM_KEYS)
    }


def _round6(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in frame.columns:
            frame[col] = frame[col].astype(float).round(6)
    return frame


def run_simulation(
    config: dict[str, Any],
    *,
    scenario_id: str,
    seed: int,
    dataset: str | None = None,
    mechanism: dict[str, Any] | None = None,
    scenario_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = dataset or config.get("dataset_id", "mvp_meiliangwan_2024")
    mechanism = mechanism or load_yaml(yaml_path("mechanism_parameters.yaml"))
    catalog = scenario_catalog or load_yaml(yaml_path("scenario_catalog.yaml"))
    scenarios = catalog.get("scenarios", {})
    if scenario_id not in scenarios:
        raise SystemExit(f"unknown scenario: {scenario_id} (available: {', '.join(scenarios)})")
    scenario = dict(scenarios[scenario_id])
    scenario["scenario_id"] = scenario_id
    scenario.setdefault("load_multiplier", 1.0)
    if scenario.get("extremes") == "none":
        scenario["extremes"] = {}

    sim_cfg = config["simulation"]
    if sim_cfg.get("full_lake"):
        start, end = sim_cfg["full_lake_start_date"], sim_cfg["full_lake_end_date"]
        target_zones = [z for z in config["grid"].get("zone_order", [])] or None
    else:
        start, end = sim_cfg["start_date"], sim_cfg["end_date"]
        target_zones = sim_cfg.get("mvp_zones") or ["TAIHU_ML"]
    dates = pd.date_range(start, end, freq="D", tz=None)

    base = run_dir(dataset)
    cells, grid_manifest = load_grid(base / "grid")
    parameter_sets = pd.read_parquet(base / "fit" / "parameter_sets.parquet")
    from data_factory.calibration.fitter import load_param_lookup

    lookup = load_param_lookup(parameter_sets)
    parameter_set_id = str(parameter_sets["parameter_set_id"].iloc[0])

    grid_version = str(cells["grid_version"].iloc[0])
    zone_list = sorted(set(cells["zone_code"].dropna().tolist()))
    if not sim_cfg.get("full_lake"):
        missing = [z for z in target_zones if z not in zone_list]
        if missing:
            raise SystemExit(f"zones not in frozen grid: {missing}; available: {zone_list}")
    zones = target_zones if not sim_cfg.get("full_lake") else zone_list

    length_km = float(config.get("grid", {}).get("spatial_length_km", 7.0))
    out_dir = base / "simulation" / f"{scenario_id}_seed{int(seed)}"
    latent_dir = out_dir / "latent"
    latent_dir.mkdir(parents=True, exist_ok=True)

    generation_batch_id = "batch-" + content_hash(json.dumps({"dataset": dataset, "scenario": scenario_id, "seed": int(seed), "parameter_set_id": parameter_set_id, "grid_version": grid_version}, sort_keys=True))[:16]
    meta = {
        "dataset_version": dataset,
        "generator_version": GENERATOR_VERSION,
        "generation_batch_id": generation_batch_id,
    }

    diagnostics: dict[str, Any] = {"zones": {}}
    bloom_grid_frames: list[pd.DataFrame] = []
    bloom_lake_frames: list[pd.DataFrame] = []

    for zi, zone_code in enumerate(zones):
        zcells = cells[cells["zone_code"] == zone_code].sort_values("grid_id").reset_index(drop=True)
        if zcells.empty:
            continue
        grid_ids = zcells["grid_id"].tolist()
        n = len(grid_ids)
        coords = zcells[["utm_x", "utm_y"]].to_numpy(dtype=float)
        modes = spatial_modes(coords, length_km=length_km)
        rngs = zone_rngs(seed, zi)

        arrays, lake_mean = weather.simulate_weather(dates, modes, lookup, mechanism, rngs, scenario)
        ta_grid = arrays["air_temperature"]
        ws_grid = arrays["wind_speed"]
        rad_grid = arrays["shortwave_radiation"]
        precip_lake = arrays["precipitation"].mean(axis=1)
        wind_dir = lake_mean["wind_direction"].to_numpy(dtype=float)

        tw, tw_diag = hydrology.simulate_water_temperature(dates, ta_grid, rad_grid, ws_grid, zcells["depth_mean_m"].to_numpy(dtype=float), lookup, mechanism, rngs["hydrology"])
        level, level_diag = hydrology.simulate_water_balance(dates, precip_lake, lookup, mechanism, rngs["hydrology"])
        depth_m = np.maximum(zcells["depth_mean_m"].to_numpy(dtype=float)[None, :] + level_diag["depth_anomaly"][:, None], 0.5)

        # 营养盐⇄藻类 2-pass Gauss-Seidel 耦合（无循环依赖，确定性）
        empty_prev = np.zeros_like(tw)
        nut1 = nutrients.simulate_nutrients(dates, tw, ws_grid, rad_grid, precip_lake[:, None] * np.ones((1, n)), empty_prev, empty_prev, depth_m, zone_code, lookup, mechanism, rngs, scenario)
        bio1 = algae.simulate_biomass(dates, tw, ws_grid, rad_grid, nut1, lookup, mechanism, rngs, scenario, zone_code)
        nut2 = nutrients.simulate_nutrients(dates, tw, ws_grid, rad_grid, precip_lake[:, None] * np.ones((1, n)), bio1["phytoplankton_biomass"], bio1["growth_rate"], depth_m, zone_code, lookup, mechanism, rngs, scenario)
        bio2 = algae.simulate_biomass(dates, tw, ws_grid, rad_grid, nut2, lookup, mechanism, rngs, scenario, zone_code)

        # 输运：扩散 + 风漂移（逐日，作用于生物量）
        operator = transport.TransportOperator(zcells, mechanism)
        biomass = bio2["phytoplankton_biomass"]
        surface = bio2["surface_biomass"]
        outflow_total = 0.0
        for t in range(len(dates)):
            biomass[t], out_b = transport.step_transport(biomass[t], operator, float(wind_dir[t]))
            surface[t], out_s = transport.step_transport(surface[t], operator, float(wind_dir[t]))
            outflow_total += out_b + out_s

        pigment_ratio = algae.resolve_pigment_ratio(lookup, mechanism)
        optics = algae.derive_chla_density(surface, pigment_ratio, mechanism, rngs)

        effective_area = zcells["effective_water_area_m2"].to_numpy(dtype=float)
        bloom_out = bloom.simulate_bloom_fraction(surface, tw, ws_grid, effective_area, zcells, mechanism)
        frozen_lake_area = float(grid_manifest.get("lake_area_km2_frozen") or 0.0) or None
        lake_bloom_df, zone_bloom_df = bloom.aggregate_bloom(dates, bloom_out["bloom_fraction"], bloom_out["bloom_area_grid_km2"], effective_area, zcells["zone_code"].to_numpy(), frozen_lake_area_km2=frozen_lake_area)

        # ---- 落盘（潜在真值层）----
        lake_mean.round(6).to_parquet(latent_dir / f"weather_daily_{zone_code}.parquet", index=False)
        hydro_df = pd.DataFrame(
            {
                "date": dates,
                "zone_code": zone_code,
                "water_temperature_lake_mean": tw.mean(axis=1),
                "water_level_m": level,
                "depth_anomaly_m": level_diag["depth_anomaly"],
                "air_temperature_lake_mean": ta_grid.mean(axis=1),
                "precipitation_lake_mean": precip_lake,
            }
        ).round(6)
        hydro_df.to_parquet(latent_dir / f"hydrology_daily_{zone_code}.parquet", index=False)

        latent_records = {"date": [], "grid_id": [], "variable_code": [], "value": []}
        date_strs = dates.strftime("%Y-%m-%d").to_numpy()
        grid_arr = np.array(grid_ids)
        source_by_variable = {**{v: nut2[v] for v in WATER_VARIABLES if v in nut2}, "water_temperature": tw, "chlorophyll_a": optics["chlorophyll_a"], "cyanobacteria_density": optics["cyanobacteria_density"]}
        for variable in WATER_VARIABLES:
            values = source_by_variable[variable]
            latent_records["date"].append(np.repeat(date_strs, n))
            latent_records["grid_id"].append(np.tile(grid_arr, len(dates)))
            latent_records["variable_code"].append(np.full(len(dates) * n, variable))
            latent_records["value"].append(values.round(6).ravel())
        wq_df = pd.DataFrame({k: np.concatenate(v) for k, v in latent_records.items()})
        wq_df.to_parquet(latent_dir / f"water_quality_grid_daily_{zone_code}.parquet", index=False)

        bio_df = pd.DataFrame(
            {
                "date": np.repeat(dates.strftime("%Y-%m-%d").to_numpy(), n),
                "grid_id": np.tile(np.array(grid_ids), len(dates)),
                "phytoplankton_biomass_mg_l": biomass.round(6).ravel(),
                "surface_biomass_mg_l": surface.round(6).ravel(),
                "growth_rate_per_day": bio2["growth_rate"].round(6).ravel(),
            }
        )
        bio_df.to_parquet(latent_dir / f"biomass_grid_daily_{zone_code}.parquet", index=False)

        bg = pd.DataFrame(
            {
                "grid_id": np.tile(np.array(grid_ids), len(dates)),
                "date": np.repeat(dates, n),
                "bloom_fraction": bloom_out["bloom_fraction"].round(6).ravel(),
                "bloom_area_m2": (bloom_out["bloom_area_grid_km2"].ravel() * 1.0e6).round(3),
                "surface_biomass_mg_l": surface.round(6).ravel(),
                "dataset_version": dataset,
                "source_type": "simulated",
                "is_ground_truth": False,
                "scenario_id": scenario_id,
                "random_seed": int(seed),
                "parameter_set_id": parameter_set_id,
                "generator_version": GENERATOR_VERSION,
                "generation_batch_id": generation_batch_id,
            }
        )
        bloom_grid_frames.append(bg)

        for frame in (lake_bloom_df, zone_bloom_df):
            frame["dataset_version"] = dataset
            frame["source_type"] = "simulated"
            frame["is_ground_truth"] = False
            frame["scenario_id"] = scenario_id
            frame["random_seed"] = int(seed)
            frame["parameter_set_id"] = parameter_set_id
            frame["generator_version"] = GENERATOR_VERSION
            frame["generation_batch_id"] = generation_batch_id
        zone_part = zone_bloom_df.rename(columns={"zone_code": "spatial_id", "bloom_fraction_zone": "bloom_fraction_mean", "zone_area_km2": "effective_water_area_km2"})
        lake_part = lake_bloom_df.assign(spatial_id="TAIHU_WHOLE", bloom_fraction_mean=lake_bloom_df["bloom_fraction_lake"], effective_water_area_km2=lake_bloom_df["lake_area_km2"])
        both = pd.concat([zone_part, lake_part], ignore_index=True)
        bloom_lake_frames.append(both)

        # DG-005：pre-clip 越界命中率逐变量落 manifest，供 A07 门禁
        cell_days = max(tw.shape[0] * tw.shape[1], 1)
        bound_rates = {
            "water_temperature": round((tw_diag["range_clamps"] + tw_diag.get("rate_clamps", 0)) / cell_days, 6),
            "water_level": round(level_diag.get("clamps", 0) / max(len(dates), 1), 6),
        }
        for source in (nut2, bio2, optics):
            for variable, hits in (source.get("_bound_hits") or {}).items():
                bound_rates[variable] = round(hits / cell_days, 6)

        diagnostics["zones"][zone_code] = {
            "n_cells": n,
            "water_temp_clamps": tw_diag,
            "level_clamps": level_diag.get("clamps"),
            "biomass_clamps": bio2["_diagnostics"]["clamp_count"],
            "bound_hit_rate": bound_rates,
            "transport_outflow_total": round(outflow_total, 6),
            "pigment_ratio": pigment_ratio,
            "bloom_days_fraction_ge5pct": round(float((bloom_out["bloom_fraction"] >= 0.05).mean()), 4),
        }

    bloom_grid = pd.concat(bloom_grid_frames, ignore_index=True) if bloom_grid_frames else pd.DataFrame()
    bloom_lake = pd.concat(bloom_lake_frames, ignore_index=True) if bloom_lake_frames else pd.DataFrame()
    bloom_grid = _round6(bloom_grid, ["bloom_fraction", "surface_biomass_mg_l", "bloom_area_m2"])
    bloom_lake = _round6(bloom_lake, ["bloom_area_km2", "bloom_fraction_zone", "bloom_fraction_lake", "bloom_fraction_mean", "zone_area_km2", "lake_area_km2", "effective_water_area_km2", "domain_coverage_km2", "domain_coverage_fraction"])
    # bloom_lake_daily 统一列：date, spatial_id, bloom_area_km2, bloom_fraction_mean, effective_water_area_km2, domain_coverage_*
    lake_mask = bloom_lake["spatial_id"] == "TAIHU_WHOLE"
    bloom_lake.loc[lake_mask, "effective_water_area_km2"] = bloom_lake.loc[lake_mask, "lake_area_km2"]
    keep = ["date", "spatial_id", "bloom_area_km2", "bloom_fraction_mean", "effective_water_area_km2", "domain_coverage_km2", "domain_coverage_fraction", "is_partial_domain", "dataset_version", "source_type", "is_ground_truth", "scenario_id", "random_seed", "parameter_set_id", "generator_version", "generation_batch_id"]
    for col in keep:
        if col not in bloom_lake.columns:
            bloom_lake[col] = None
    bloom_lake = bloom_lake[keep]
    bloom_lake = bloom_lake.drop(columns=[c for c in ("lake_area_km2", "zone_area_km2", "bloom_fraction_lake", "bloom_fraction_zone") if c in bloom_lake.columns])
    bloom_grid.to_parquet(out_dir / "bloom_grid_daily.parquet", index=False)
    bloom_lake.to_parquet(out_dir / "bloom_lake_daily.parquet", index=False)

    manifest = {
        "status": "completed",
        "command": "simulate",
        "dataset_id": dataset,
        "scenario_id": scenario_id,
        "random_seed": int(seed),
        "parameter_set_id": parameter_set_id,
        "grid_version": grid_version,
        "grid_manifest_version": grid_manifest.get("grid_version"),
        "generation_batch_id": generation_batch_id,
        "generator_version": GENERATOR_VERSION,
        "contract_version": CONTRACT_VERSION,
        "rng": {"root": "SeedSequence([seed, zone_index, stream_index])", "streams": STREAM_KEYS, "coupling": "nutrients⇄algae 2-pass Gauss-Seidel"},
        "dates": {"start": str(dates[0].date()), "end": str(dates[-1].date()), "days": int(len(dates))},
        "zones": zones,
        "diagnostics": diagnostics,
        "bound_hit_rate": {
            variable: max(float(zone_diag.get("bound_hit_rate", {}).get(variable, 0.0)) for zone_diag in diagnostics["zones"].values())
            for variable in sorted({key for zone_diag in diagnostics["zones"].values() for key in zone_diag.get("bound_hit_rate", {})})
        },
        "rows_written": int(len(bloom_grid) + len(bloom_lake)),
        "outputs": {
            "bloom_grid_daily": str(out_dir / "bloom_grid_daily.parquet"),
            "bloom_lake_daily": str(out_dir / "bloom_lake_daily.parquet"),
            "latent_dir": str(latent_dir),
        },
        "limitations": [
            "营养盐-藻类耦合用 2-pass 代替逐日迭代（吸取滞后生物量）",
            "VAR 相关创新简化为对角 AR + 静态残差相关（未用于逐日驱动）",
            "水位为湖区标量，深度距平按静压近似分配",
            "风向为逐日标量随机场，未解析湖风环流",
        ],
        "next_action": "python -m data_factory build-observations",
    }
    (out_dir / "sim_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
