import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from .config import SimulationConfig


ANCHOR_COLUMNS = (
    "station_id",
    "month",
    "wq_tp",
    "wq_tn",
    "wq_do",
    "wq_ph",
    "wq_phyto_biomass",
)

POWER_COLUMN_MAP = {
    "T2M": "air_temperature_C",
    "PRECTOTCORR": "precipitation_mm_day",
    "WS10M": "wind_speed_m_s",
    "WD10M": "wind_direction_deg",
    "ALLSKY_SFC_SW_DWN": "solar_radiation_MJ_m2_day",
    "RH2M": "relative_humidity_pct",
    "PS": "surface_pressure_kPa",
}


ANCHOR_ASSETS = (
    "quarterly_tp",
    "quarterly_tn",
    "quarterly_do",
    "quarterly_phyto_biomass",
    "annual_cyanobacteria",
    "field_chla",
    "remote_chla",
)

QUARTERLY_TARGETS = {
    "quarterly_tp": ("target_tp", "total_phosphorus_mg_L", "mg/L"),
    "quarterly_tn": ("target_tn", "total_nitrogen_mg_L", "mg/L"),
    "quarterly_do": ("target_do", "dissolved_oxygen_mg_L", "mg/L"),
    "quarterly_phyto_biomass": (
        "wq_phyto_biomass",
        "phytoplankton_biomass_mg_L",
        "mg/L",
    ),
}

REQUIRED_PROFILE_VARIABLES = (
    "total_phosphorus_mg_L",
    "total_nitrogen_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
)

QUARTERLY_SOURCE_ROW_COUNT = 504

AUDITED_TRAINING_STATUS = {
    "annual_cyanobacteria": {"REVIEW_REQUIRED"},
    "field_chla": {"OBSERVATION_ONLY"},
    "remote_chla": {"PROXY_CANDIDATE", "REVIEW_REQUIRED"},
}

AUDITED_CLAIM_BOUNDARIES = {
    "quarterly_tp": "quarterly_proxy_forecast_only",
    "quarterly_tn": "quarterly_proxy_forecast_only",
    "quarterly_do": "quarterly_proxy_forecast_only",
    "quarterly_phyto_biomass": "quarterly_proxy_forecast_only",
    "annual_cyanobacteria": "annual_taxonomic_series_not_daily_or_spatial_label",
    "field_chla": "sparse_field_observation_not_daily_target",
    "remote_chla": "remote_sensing_proxy_not_field_ground_truth",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    if len(value) != 64:
        raise ValueError("computed source hash is not 64 characters")
    return value


def _anchor_input_paths(paths: dict) -> dict[str, Path]:
    supplied = set(paths)
    expected = set(ANCHOR_ASSETS)
    unrecognized = sorted(supplied - expected)
    missing = sorted(expected - supplied)
    if unrecognized:
        raise ValueError(f"unrecognized anchor asset keys: {unrecognized}")
    if missing:
        raise ValueError(f"missing required anchor asset keys: {missing}")
    result = {name: Path(paths[name]) for name in ANCHOR_ASSETS}
    for asset, path in result.items():
        if not path.is_file():
            raise FileNotFoundError(f"anchor file missing for {asset}: {path}")
        if "synthetic" in path.name.lower() or "synthetic" in {part.lower() for part in path.parts}:
            raise ValueError(f"synthetic output cannot be used as anchor: {path}")
    return result


def _read_anchor_source(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    if "is_synthetic" in frame.columns:
        values = frame["is_synthetic"]
        if values.astype(str).str.lower().isin(("true", "1", "yes")).any():
            raise ValueError(f"synthetic input cannot be used as anchor: {path}")
    declaration_columns = (
        "data_mode", "value_type", "provenance_type", "claim_boundary", "source_scope",
        "source_class", "provenance", "simulation_status",
    )
    for column in declaration_columns:
        if column not in frame.columns:
            continue
        values = frame[column].astype(str).str.lower()
        if values.str.contains(r"synthetic|simulat", regex=True, na=False).any():
            raise ValueError(f"synthetic declaration cannot be used as anchor: {path}")
    return frame


def _validate_audited_declarations(asset: str, frame: pd.DataFrame) -> None:
    if "claim_boundary" not in frame.columns:
        raise ValueError(f"anchor columns missing for {asset}: ['claim_boundary']")
    expected_boundary = AUDITED_CLAIM_BOUNDARIES[asset]
    if not frame["claim_boundary"].eq(expected_boundary).all():
        raise ValueError(f"audited claim_boundary mismatch for {asset}")
    if asset in AUDITED_TRAINING_STATUS:
        if "training_status" not in frame.columns:
            raise ValueError(f"anchor columns missing for {asset}: ['training_status']")
        if not frame["training_status"].isin(AUDITED_TRAINING_STATUS[asset]).all():
            raise ValueError(f"audited training_status mismatch for {asset}")
    elif "source_scope" not in frame.columns or not frame["source_scope"].eq("existing_release_only").all():
        raise ValueError(f"audited source_scope mismatch for {asset}")


def _validated_quarterly_sources(source_paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    """Read four parallel target views and freeze their shared 504-key contract."""
    frames: dict[str, pd.DataFrame] = {}
    reference_mapping: pd.DataFrame | None = None
    for asset, (target_column, _, _) in QUARTERLY_TARGETS.items():
        frame = _read_anchor_source(source_paths[asset])
        required = {"sample_id", "station_id", "month", target_column, "claim_boundary"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"anchor columns missing for {asset}: {missing}")
        _validate_audited_declarations(asset, frame)
        if len(frame) != QUARTERLY_SOURCE_ROW_COUNT:
            raise ValueError(
                f"quarterly asset {asset} must contain exactly {QUARTERLY_SOURCE_ROW_COUNT} rows"
            )
        if frame[["sample_id", "station_id", "month"]].isna().any().any():
            raise ValueError(f"quarterly asset {asset} has null sample_id/station_id/month mapping")
        if frame["sample_id"].duplicated().any():
            raise ValueError(f"quarterly asset {asset} must have unique sample_id")
        if frame.duplicated(["station_id", "month"]).any():
            raise ValueError(f"quarterly asset {asset} must have unique station_id/month")
        mapping = (
            frame.loc[:, ["sample_id", "station_id", "month"]]
            .assign(
                sample_id=lambda value: value["sample_id"].astype(str),
                station_id=lambda value: value["station_id"].astype(str),
                month=lambda value: value["month"].astype(str),
            )
            .set_index("sample_id")
            .sort_index()
        )
        if reference_mapping is None:
            reference_mapping = mapping
        elif not mapping.equals(reference_mapping):
            raise ValueError("quarterly sample_id/station_id/month mappings disagree across views")
        frames[asset] = frame
    return frames


def _parsed_dates(values: pd.Series, *, asset: str, format: str | None = None) -> pd.Series:
    dates = pd.to_datetime(values, format=format or "mixed", errors="coerce")
    if dates.isna().any():
        raise ValueError(f"malformed date in anchor asset {asset}")
    return dates


def _finite_values(values: pd.Series, *, asset: str, variable: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric).all():
        raise ValueError(f"non-finite value in anchor asset {asset}, variable {variable}")
    return numeric.astype(float)


def _registry_row(
    *,
    asset: str,
    source_row_id: str,
    spatial_id: str,
    observed_at: pd.Timestamp,
    variable_code: str,
    original_variable: str,
    original_value: float,
    original_unit: str,
    source_original_units: str | None,
    unit: str,
    training_status: str,
    claim_boundary: str,
    source_path: Path,
    source_sha256: str,
    approved_for_calibration: bool,
) -> dict:
    return {
        "anchor_id": f"{asset}:{source_row_id}:{variable_code}",
        "asset": asset,
        "source_row_id": str(source_row_id),
        "spatial_id": str(spatial_id),
        "observed_at": pd.Timestamp(observed_at),
        "variable_code": variable_code,
        "original_variable": original_variable,
        "original_value": float(original_value),
        "original_unit": original_unit,
        "source_original_units": source_original_units if source_original_units is not None else original_unit,
        "value": float(original_value),
        "unit": unit,
        "training_status": training_status,
        "claim_boundary": claim_boundary,
        "source_path": str(source_path.resolve()),
        "source_sha256": source_sha256,
        "data_mode": "observed_anchor",
        "is_synthetic": False,
        "approved_for_calibration": bool(approved_for_calibration),
    }


def build_anchor_registry(paths: dict, train_end) -> pd.DataFrame:
    """Return immutable, long-form records for the audited real observation assets.

    The registry deliberately records the four quarterly target views separately:
    they share sample keys but are distinct variable measurements.  The shared pH
    lag is retained once, from ``quarterly_tp``, to preserve its provenance without
    multiplying the same evidence four times.
    """
    source_paths = _anchor_input_paths(paths)
    train_end_timestamp = pd.to_datetime(train_end, errors="coerce")
    if pd.isna(train_end_timestamp):
        raise ValueError("train_end must be a valid date")

    records: list[dict] = []
    source_hashes = {asset: _sha256(path) for asset, path in source_paths.items()}
    quarterly_frames = _validated_quarterly_sources(source_paths)

    for asset, (target_column, variable_code, unit) in QUARTERLY_TARGETS.items():
        path = source_paths[asset]
        frame = quarterly_frames[asset]
        dates = _parsed_dates(frame["month"], asset=asset, format="%Y-%m")
        values = _finite_values(frame[target_column], asset=asset, variable=target_column)
        for index, row in frame.iterrows():
            records.append(
                _registry_row(
                    asset=asset,
                    source_row_id=row["sample_id"],
                    spatial_id=row["station_id"],
                    observed_at=dates.loc[index],
                    variable_code=variable_code,
                    original_variable=target_column,
                    original_value=values.loc[index],
                    original_unit=unit,
                    source_original_units=unit,
                    unit=unit,
                    training_status="CALIBRATION_APPROVED",
                    claim_boundary=str(row["claim_boundary"]),
                    source_path=path,
                    source_sha256=source_hashes[asset],
                    approved_for_calibration=True,
                )
            )
        if asset == "quarterly_tp":
            ph_required = {"lag_3m_wq_ph"}
            if missing_ph := sorted(ph_required - set(frame.columns)):
                raise ValueError(f"anchor columns missing for {asset}: {missing_ph}")
            ph_values = _finite_values(frame["lag_3m_wq_ph"], asset=asset, variable="lag_3m_wq_ph")
            for index, row in frame.iterrows():
                records.append(
                    _registry_row(
                        asset=asset,
                        source_row_id=row["sample_id"],
                        spatial_id=row["station_id"],
                        observed_at=dates.loc[index] - pd.DateOffset(months=3),
                        variable_code="ph",
                        original_variable="lag_3m_wq_ph",
                        original_value=ph_values.loc[index],
                        original_unit="dimensionless",
                        source_original_units="dimensionless",
                        unit="dimensionless",
                        training_status="CALIBRATION_APPROVED",
                        claim_boundary=str(row["claim_boundary"]),
                        source_path=path,
                        source_sha256=source_hashes[asset],
                        approved_for_calibration=True,
                    )
                )

    evidence_specs = {
        "annual_cyanobacteria": (
            "record_id", "aux_station_id", "observed_at", "cyanobacteria_density_cells_L",
            "unit", "cyanobacteria_density_cells_L",
        ),
        "field_chla": (
            "sample_key", "spatial_id", "observed_at", "chlorophyll_a_ug_L",
            "original_units", "chlorophyll_a_ug_L",
        ),
        "remote_chla": (
            "record_id", "spatial_id", "observed_at", "chlorophyll_a_ug_L",
            "unit", "chlorophyll_a_ug_L",
        ),
    }
    for asset, (id_column, spatial_column, date_column, value_column, unit_column, variable_code) in evidence_specs.items():
        path = source_paths[asset]
        frame = _read_anchor_source(path)
        required = {id_column, spatial_column, date_column, value_column, unit_column, "training_status", "claim_boundary"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"anchor columns missing for {asset}: {missing}")
        _validate_audited_declarations(asset, frame)
        dates = _parsed_dates(frame[date_column], asset=asset)
        values = _finite_values(frame[value_column], asset=asset, variable=value_column)
        canonical_unit = "cells/L" if asset == "annual_cyanobacteria" else "ug/L"
        for index, row in frame.iterrows():
            records.append(
                _registry_row(
                    asset=asset,
                    source_row_id=row[id_column],
                    spatial_id=row[spatial_column],
                    observed_at=dates.loc[index],
                    variable_code=variable_code,
                    original_variable=value_column,
                    original_value=values.loc[index],
                    original_unit="ug/L" if asset == "field_chla" else str(row[unit_column]),
                    source_original_units=str(row[unit_column]),
                    unit=canonical_unit,
                    training_status=str(row["training_status"]),
                    claim_boundary=str(row["claim_boundary"]),
                    source_path=path,
                    source_sha256=source_hashes[asset],
                    approved_for_calibration=False,
                )
            )

    registry = pd.DataFrame.from_records(records)
    if registry.empty:
        raise ValueError("anchor registry cannot be empty")
    if registry["anchor_id"].duplicated().any():
        raise ValueError("duplicate anchor_id in anchor registry")
    if not registry["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("invalid computed source hash in anchor registry")
    registry["used_for_fit"] = (
        registry["approved_for_calibration"] & (registry["observed_at"] <= train_end_timestamp)
    )
    return registry.sort_values(
        ["observed_at", "asset", "source_row_id", "variable_code", "anchor_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def profile_training_anchors(registry: pd.DataFrame) -> dict:
    """Calculate robust, training-only profiles from calibration-approved anchors."""
    required = {
        "anchor_id", "observed_at", "variable_code", "value", "spatial_id",
        "data_mode", "is_synthetic", "used_for_fit",
    }
    missing = sorted(required - set(registry.columns))
    if missing:
        raise ValueError(f"registry columns missing: {missing}")
    if registry["anchor_id"].duplicated().any():
        raise ValueError("duplicate anchor_id in registry")
    fit = registry.loc[registry["used_for_fit"]].copy()
    if fit.empty:
        raise ValueError("no usable training anchors")
    if fit["is_synthetic"].astype(bool).any() or not fit["data_mode"].eq("observed_anchor").all():
        raise ValueError("fit rows must be non-synthetic observed anchors")
    fit["observed_at"] = pd.to_datetime(fit["observed_at"], errors="coerce")
    if fit["observed_at"].isna().any():
        raise ValueError("malformed date in fit rows")
    fit["value"] = pd.to_numeric(fit["value"], errors="coerce")
    if fit["value"].isna().any() or not np.isfinite(fit["value"]).all():
        raise ValueError("fit rows contain no usable finite values")

    profile: dict[str, dict] = {}
    for variable_code, group in fit.groupby("variable_code", sort=True):
        values = group["value"].to_numpy(dtype=float)
        if len(values) == 0 or not np.isfinite(values).all():
            raise ValueError(f"variable {variable_code} has no usable finite values")
        median = float(np.median(values))
        month_profile = {
            str(int(month)): float(month_values.median())
            for month, month_values in group.groupby(group["observed_at"].dt.month, sort=True)["value"]
        }
        region_profile = {
            str(region): float(region_values.median())
            for region, region_values in group.groupby("spatial_id", sort=True)["value"]
            if pd.notna(region)
        }
        profile[variable_code] = {
            "count": int(len(values)),
            "median": median,
            "q05": float(np.quantile(values, 0.05)),
            "q25": float(np.quantile(values, 0.25)),
            "q75": float(np.quantile(values, 0.75)),
            "q95": float(np.quantile(values, 0.95)),
            "mad": float(np.median(np.abs(values - median))),
            "month_profile": month_profile,
            "region_profile": region_profile,
        }
    absent = sorted(set(REQUIRED_PROFILE_VARIABLES) - set(profile))
    if absent:
        raise ValueError(f"required training profile variables have no usable finite values: {absent}")
    return {key: profile[key] for key in sorted(profile)}


def load_quarterly_anchors(path: str | Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    missing = sorted(set(ANCHOR_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"anchor columns missing: {missing}")
    result = frame.loc[frame["station_id"] != "TAIHU_WHOLE", list(ANCHOR_COLUMNS)].copy()
    result["month"] = result["month"].astype(str)
    result["anchor_source_class"] = "observed_anchor"
    return result.sort_values(["station_id", "month"]).reset_index(drop=True)


def load_nasa_power(path: str | Path, config: SimulationConfig | None = None) -> pd.DataFrame:
    config = config or SimulationConfig()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    parameter = payload["properties"]["parameter"]
    fill_value = float(payload.get("header", {}).get("fill_value", -999.0))
    dates = sorted(set().union(*(series.keys() for series in parameter.values())))
    result = pd.DataFrame({"date": pd.to_datetime(dates, format="%Y%m%d")})
    for source_name, output_name in POWER_COLUMN_MAP.items():
        if source_name not in parameter:
            raise ValueError(f"NASA POWER parameter missing: {source_name}")
        values = pd.Series(parameter[source_name], dtype="float64")
        values.index = pd.to_datetime(values.index, format="%Y%m%d")
        result[output_name] = result["date"].map(values).replace(fill_value, np.nan)
    result["weather_source_class"] = "external_reanalysis"
    result["weather_time_standard"] = payload.get("header", {}).get("time_standard", "unknown")
    validate_weather_calendar(result, config)
    return result


def validate_weather_calendar(frame: pd.DataFrame, config: SimulationConfig) -> None:
    if "date" not in frame.columns:
        raise ValueError("weather date column missing")
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("unparseable weather dates")
    if dates.duplicated().any():
        raise ValueError("duplicate weather dates")
    expected = config.dates
    if len(dates) != len(expected) or not dates.sort_values().reset_index(drop=True).equals(
        pd.Series(expected)
    ):
        raise ValueError("weather calendar is incomplete")
    weather_columns = [column for column in POWER_COLUMN_MAP.values() if column in frame.columns]
    if weather_columns and frame[weather_columns].isna().any().any():
        raise ValueError("NASA POWER weather contains missing values")
