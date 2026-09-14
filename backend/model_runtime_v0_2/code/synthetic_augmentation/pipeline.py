from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from synthetic_augmentation.config import SimulationConfig
    from synthetic_augmentation.forecast import build_forecast_samples
    from synthetic_augmentation.lineage import build_lineage, lineage_record, sha256_file
    from synthetic_augmentation.quality import assert_quality_gates, profile_quality
    from synthetic_augmentation.simulator import aggregate_lake_daily, generate_region_daily
    from synthetic_augmentation.sources import load_nasa_power, load_quarterly_anchors
else:
    from .config import SimulationConfig
    from .forecast import build_forecast_samples
    from .lineage import build_lineage, lineage_record, sha256_file
    from .quality import assert_quality_gates, profile_quality
    from .simulator import aggregate_lake_daily, generate_region_daily
    from .sources import load_nasa_power, load_quarterly_anchors


NASA_POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/daily/point?"
    "parameters=T2M,PRECTOTCORR,WS10M,WD10M,ALLSKY_SFC_SW_DWN,RH2M,PS&"
    "community=AG&longitude=120.20&latitude=31.20&start=20050101&end=20251231&"
    "format=JSON&time-standard=LST"
)

PUBLIC_SOURCES = [
    {
        "title": "NASA POWER Daily API",
        "url": "https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        "access_status": "downloaded",
        "use": "Daily lake-scale meteorological driver",
    },
    {
        "title": "Taihu water-quality monitoring dataset (2000-2020)",
        "url": "https://www.geodata.cn/main/face_science_detail?guid=30292244868129&publisherGuid=29987510602686",
        "access_status": "local_cleaned_anchor_available",
        "use": "Quarterly TN/TP/DO/pH/biomass distribution anchors",
    },
    {
        "title": "Taihu cyanobacterial bloom remote-sensing products",
        "url": "https://lake.geodata.cn/feature.html",
        "access_status": "not_downloaded_reference_only",
        "use": "Product-scope and realism reference; no raster values ingested",
    },
    {
        "title": "2024 China Ecological Meteorological Bulletin",
        "url": "https://www.cma.gov.cn/zfxxgk/gknr/qxbg/202507/W020250723534606038596.pdf",
        "access_status": "reference_only",
        "use": "Independent annual Taihu climate reasonableness anchors",
    },
]


UNITS = {
    "date": "date",
    "region_area_km2": "km2",
    "air_temperature_C": "degC",
    "precipitation_mm_day": "mm/day",
    "wind_speed_m_s": "m/s",
    "wind_direction_deg": "degree",
    "solar_radiation_MJ_m2_day": "MJ/m2/day",
    "relative_humidity_pct": "%",
    "surface_pressure_kPa": "kPa",
    "water_temperature_C": "degC",
    "water_level_m": "m",
    "flow_speed_m_s": "m/s",
    "total_phosphorus_mg_L": "mg/L",
    "total_nitrogen_mg_L": "mg/L",
    "dissolved_oxygen_mg_L": "mg/L",
    "ph": "dimensionless",
    "phytoplankton_biomass_mg_L": "mg/L",
    "chlorophyll_a_ug_L": "ug/L",
    "blue_algae_biomass_mg_L": "mg/L",
    "cyanobacteria_density_cells_L": "cells/L",
    "fai_proxy": "dimensionless",
    "ndci_proxy": "dimensionless",
    "bloom_probability": "probability",
    "bloom_area_km2": "km2",
}

SOURCE_CLASS_BY_COLUMN = {
    "air_temperature_C": "external_reanalysis_plus_derived_microclimate",
    "precipitation_mm_day": "external_reanalysis_plus_derived_microclimate",
    "wind_speed_m_s": "external_reanalysis_plus_derived_microclimate",
    "wind_direction_deg": "external_reanalysis_plus_derived_microclimate",
    "solar_radiation_MJ_m2_day": "external_reanalysis_plus_derived_microclimate",
    "relative_humidity_pct": "external_reanalysis_plus_derived_microclimate",
    "surface_pressure_kPa": "external_reanalysis_plus_derived_microclimate",
    "total_phosphorus_mg_L": "synthetic_conditioned_on_observed_anchor",
    "total_nitrogen_mg_L": "synthetic_conditioned_on_observed_anchor",
    "dissolved_oxygen_mg_L": "synthetic_conditioned_on_observed_anchor",
    "ph": "synthetic_conditioned_on_observed_anchor",
    "phytoplankton_biomass_mg_L": "synthetic_conditioned_on_observed_anchor",
}


def _atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _atomic_write_text(text: str, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _feature_dictionary(columns: list[str]) -> pd.DataFrame:
    rows = []
    for column in columns:
        if column.startswith("target_"):
            role = "future_target"
            source_class = "synthetic_future_shift"
        elif column in {
            "bloom_label",
            "bloom_probability",
            "bloom_area_km2",
            "blue_algae_biomass_mg_L",
            "bloom_risk_level",
        }:
            role = "current_state_or_label"
            source_class = "synthetic_mechanism"
        elif column in {"sample_id", "date", "spatial_id", "spatial_type", "dataset_split"}:
            role = "key_or_split"
            source_class = "derived_identifier"
        else:
            role = "model_feature_or_audit"
            source_class = SOURCE_CLASS_BY_COLUMN.get(column, "derived_simulation")
        rows.append(
            {
                "field_name": column,
                "role": role,
                "unit": UNITS.get(column, "text_or_flag"),
                "source_class": source_class,
                "allowed_for_real_effect_claim": False,
                "description": column.replace("_", " "),
            }
        )
    return pd.DataFrame(rows)


def _anchor_comparison(region_daily: pd.DataFrame, anchors: pd.DataFrame) -> dict[str, object]:
    mapping = {
        "wq_tp": "total_phosphorus_mg_L",
        "wq_tn": "total_nitrogen_mg_L",
        "wq_do": "dissolved_oxygen_mg_L",
        "wq_ph": "ph",
        "wq_phyto_biomass": "phytoplankton_biomass_mg_L",
    }
    result = {}
    for anchor_column, generated_column in mapping.items():
        anchor_values = anchors[anchor_column].dropna().astype(float)
        generated_values = region_daily[generated_column].dropna().astype(float)
        result[generated_column] = {
            "anchor_count": int(len(anchor_values)),
            "anchor_median": float(anchor_values.median()),
            "anchor_q05": float(anchor_values.quantile(0.05)),
            "anchor_q95": float(anchor_values.quantile(0.95)),
            "synthetic_median": float(generated_values.median()),
            "synthetic_q05": float(generated_values.quantile(0.05)),
            "synthetic_q95": float(generated_values.quantile(0.95)),
        }
    return result


def _weather_2024_summary(weather: pd.DataFrame) -> dict[str, object]:
    subset = weather.loc[pd.DatetimeIndex(weather["date"]).year == 2024]
    return {
        "source": "NASA_POWER_point_120.20E_31.20N_LST",
        "mean_air_temperature_C": float(subset["air_temperature_C"].mean()),
        "total_precipitation_mm": float(subset["precipitation_mm_day"].sum()),
        "mean_wind_speed_m_s": float(subset["wind_speed_m_s"].mean()),
        "mean_solar_radiation_MJ_m2_day": float(subset["solar_radiation_MJ_m2_day"].mean()),
        "official_reference": {
            "mean_air_temperature_C": 18.1,
            "total_precipitation_mm": 1564.7,
            "mean_wind_speed_m_s": 1.8,
            "note": "CMA regional bulletin values are comparison anchors, not forced calibration targets.",
        },
    }


def _forecast_leakage_count(forecast: pd.DataFrame, horizons: tuple[int, ...]) -> int:
    issues = 0
    for horizon in horizons:
        date_column = f"target_date_{horizon}d"
        target_column = f"target_bloom_{horizon}d"
        valid = forecast[date_column].notna()
        issues += int((forecast.loc[valid, date_column] <= forecast.loc[valid, "date"]).sum())
        issues += int((forecast.loc[~valid, target_column].notna()).sum())
    return issues


def _known_limitations() -> str:
    return """# Known Limitations V0.2

1. This package is transparent synthetic augmentation for development only. It is not field-observed bloom truth.
2. NASA POWER is a coarse-grid external reanalysis/analysis-ready product; regional microclimate differences are simulated and labelled accordingly.
3. Daily TP, TN, DO, pH and biomass states are conditioned on quarterly anchors but are not observed daily measurements.
4. Bloom labels, areas, blue-algae biomass, Chl-a and cyanobacteria density are mechanism-informed simulations; synthetic test metrics do not estimate real Taihu forecast accuracy.
5. `TAIHU_WHOLE` is a separate derived aggregate and must not be mixed with the eight regional training rows.
6. Remote-sensing reference products requiring order approval were not downloaded or treated as ingested values.
7. Real-effect claims remain blocked until audited positive/negative field or full-coverage remote-sensing labels and an independent real temporal test set are available.
"""


def run_pipeline(
    anchor_path: str | Path,
    weather_path: str | Path,
    output_dir: str | Path,
    config: SimulationConfig | None = None,
) -> dict[str, object]:
    config = config or SimulationConfig()
    anchor_path = Path(anchor_path)
    weather_path = Path(weather_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    anchors = load_quarterly_anchors(anchor_path)
    weather = load_nasa_power(weather_path, config)
    region_daily = generate_region_daily(weather, anchors, config)
    lake_daily = aggregate_lake_daily(region_daily)
    forecast_samples = build_forecast_samples(region_daily, config.horizons)

    region_quality = profile_quality(region_daily)
    lake_quality = profile_quality(lake_daily)
    assert_quality_gates(region_quality)
    assert_quality_gates(lake_quality)
    forecast_leakage_count = _forecast_leakage_count(forecast_samples, config.horizons)
    if forecast_leakage_count:
        raise ValueError(f"forecast leakage checks failed: {forecast_leakage_count}")

    region_parquet = output_dir / "taihu_region_daily_synthetic_V0.2.parquet"
    region_csv = output_dir / "taihu_region_daily_synthetic_V0.2.csv"
    lake_parquet = output_dir / "taihu_lake_daily_aggregate_V0.2.parquet"
    forecast_parquet = output_dir / "taihu_forecast_samples_synthetic_V0.2.parquet"
    dictionary_path = output_dir / "synthetic_feature_dictionary_V0.2.csv"
    quality_path = output_dir / "data_quality_report_V0.2.json"
    lineage_path = output_dir / "source_lineage_V0.2.csv"
    limitations_path = output_dir / "known_limitations_V0.2.md"
    manifest_path = output_dir / "generation_manifest_V0.2.json"

    _atomic_write_parquet(region_daily, region_parquet)
    _atomic_write_csv(region_daily, region_csv)
    _atomic_write_parquet(lake_daily, lake_parquet)
    _atomic_write_parquet(forecast_samples, forecast_parquet)
    _atomic_write_csv(_feature_dictionary(list(forecast_samples.columns)), dictionary_path)
    _atomic_write_text(_known_limitations(), limitations_path)

    quality_report = {
        "status": "PASS",
        "result_scope": "synthetic_development_only",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "region_daily": region_quality,
        "lake_daily": lake_quality,
        "forecast": {
            "row_count": int(len(forecast_samples)),
            "horizons_days": list(config.horizons),
            "leakage_issue_count": int(forecast_leakage_count),
            "split_counts": {
                str(key): int(value)
                for key, value in forecast_samples["dataset_split"].value_counts().items()
            },
        },
        "anchor_distribution_comparison": _anchor_comparison(region_daily, anchors),
        "weather_2024_reasonableness": _weather_2024_summary(weather),
        "claim_boundary": config.claim_boundary,
    }
    _atomic_write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), quality_path)

    input_records = [
        lineage_record(
            weather_path,
            role="input_weather",
            source_class="external_reanalysis",
            source_url=NASA_POWER_URL,
        ),
        lineage_record(
            anchor_path,
            role="input_water_quality_anchor",
            source_class="observed_anchor_from_formal_cleaned_package",
        ),
    ]
    output_paths = [
        region_parquet,
        region_csv,
        lake_parquet,
        forecast_parquet,
        dictionary_path,
        quality_path,
        limitations_path,
    ]
    output_records = [
        lineage_record(path, role="generated_output", source_class="synthetic_or_derived")
        for path in output_paths
    ]
    lineage = build_lineage(input_records + output_records)
    _atomic_write_csv(lineage, lineage_path)

    output_hashes = {
        path.name: {"sha256": sha256_file(path), "byte_size": path.stat().st_size}
        for path in [*output_paths, lineage_path]
    }
    manifest = {
        "data_version": config.data_version,
        "generator_version": config.generator_version,
        "random_seed": config.random_seed,
        "data_mode": "simulation",
        "is_ground_truth": 0,
        "claim_boundary": config.claim_boundary,
        "date_start": config.start_date,
        "date_end": config.end_date,
        "timezone": "NASA POWER Local Solar Time (LST) aligned to Taihu natural date",
        "region_ids": list(config.region_ids),
        "region_row_count": int(len(region_daily)),
        "lake_aggregate_row_count": int(len(lake_daily)),
        "forecast_row_count": int(len(forecast_samples)),
        "horizons_days": list(config.horizons),
        "splits": {"train": "2005-2017", "validation": "2018-2021", "test": "2022-2025"},
        "public_sources": PUBLIC_SOURCES,
        "input_hashes": {
            weather_path.name: sha256_file(weather_path),
            anchor_path.name: sha256_file(anchor_path),
        },
        "output_files": output_hashes,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_text(json.dumps(manifest, ensure_ascii=False, indent=2), manifest_path)

    return {
        "quality_status": quality_report["status"],
        "region_row_count": len(region_daily),
        "lake_row_count": len(lake_daily),
        "forecast_row_count": len(forecast_samples),
        "output_dir": str(output_dir.resolve()),
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_pipeline(
        anchor_path=project_root / "训练准备" / "outputs" / "monthly_tp_training_candidate.parquet",
        weather_path=project_root
        / "训练准备"
        / "synthetic_augmentation"
        / "inputs"
        / "nasa_power_taihu_2005_2025.json",
        output_dir=project_root
        / "训练准备"
        / "outputs"
        / "taihu_synthetic_augmentation_V0.2",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
