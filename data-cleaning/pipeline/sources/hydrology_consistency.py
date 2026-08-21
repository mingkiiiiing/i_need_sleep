from __future__ import annotations

"""Cross-variable hydrology consistency checks for the Taihu workflow.

The checker deliberately keeps three value classes separate: historical/field
observations, public-page values, and model/forecast proxies.  It never turns a
blocked TBA/MWR/GloFAS source into a synthetic observation; unavailable sources
are represented by explicit inventory rows in the output CSV and report.
"""

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .common import PACKAGE_ROOT, utc_now


DEFAULT_INPUT = PACKAGE_ROOT / "storage" / "raw" / "taihu_thqbca_parsed" / "thqbca_observations.csv"
DEFAULT_OUTPUT_CSV = PACKAGE_ROOT / "storage" / "reports" / "hydrology_consistency.csv"
DEFAULT_REPORT = PACKAGE_ROOT / "storage" / "reports" / "hydrology_consistency.json"
DEFAULT_MANIFEST = PACKAGE_ROOT / "storage" / "manifests" / "hydrology_consistency_p07_06.json"
DEFAULT_TBA_MANIFEST = PACKAGE_ROOT / "storage" / "manifests" / "tba_hydrology_p07_01.json"
DEFAULT_MWR_MANIFEST = PACKAGE_ROOT / "storage" / "manifests" / "mwr_hfc_probe.json"
DEFAULT_GLOFAS_MANIFEST = PACKAGE_ROOT / "storage" / "manifests" / "glofas_p07_03.json"

UNIT_ALIASES = {
    "m": "m",
    "meter": "m",
    "meters": "m",
    "米": "m",
    "cm": "cm",
    "厘米": "cm",
    "mm": "mm",
    "毫米": "mm",
    "m3/s": "m3/s",
    "m³/s": "m3/s",
    "m^3/s": "m3/s",
    "立方米每秒": "m3/s",
}
CANONICAL_UNITS = {
    "water_level": "m",
    "precipitation": "mm",
    "discharge": "m3/s",
    "inflow_discharge": "m3/s",
    "outflow_discharge": "m3/s",
}
SOURCE_INVENTORY = {
    "taihu_thqbca_history": {"source_class": "observed", "proxy_flag": 0, "default_status": "available", "default_reason": "historical THQBCA observation file"},
    "tba_current_level": {"source_class": "web", "proxy_flag": 0, "default_status": "BLOCKED_POLICY", "default_reason": "TBA page snapshot or export not authorized"},
    "mwr_hfc": {"source_class": "web", "proxy_flag": 0, "default_status": "BLOCKED_POLICY", "default_reason": "MWR machine endpoint/export not authorized"},
    "glofas_forecast": {"source_class": "proxy", "proxy_flag": 1, "default_status": "BLOCKED_AUTH", "default_reason": "EWDS credentials absent; request plan only"},
}


def _normalise_unit(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().casefold().replace(" ", "")
    return UNIT_ALIASES.get(text, text or None)


def _convert_value(variable: str, value: Any, unit: Any) -> tuple[float | None, str | None, str, str]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None, CANONICAL_UNITS.get(variable), "invalid", "non_numeric"
    source_unit = _normalise_unit(unit)
    target = CANONICAL_UNITS.get(variable)
    if target is None:
        return numeric, source_unit, "unknown_variable", "not_converted"
    if source_unit is None:
        return numeric, target, "missing_source_unit", "unit_not_verified"
    if source_unit == target:
        return numeric, target, "ok", "identity"
    if variable == "water_level" and source_unit == "cm":
        return numeric / 100.0, target, "ok", "cm_to_m"
    if variable == "water_level" and source_unit == "mm":
        return numeric / 1000.0, target, "ok", "mm_to_m"
    if variable == "precipitation" and source_unit == "m":
        return numeric * 1000.0, target, "ok", "m_to_mm"
    return numeric, target, "unit_mismatch", f"unsupported_{source_unit}_to_{target}"


def _source_meta(source_id: str, manifests: dict[str, Path]) -> dict[str, Any]:
    base = dict(SOURCE_INVENTORY.get(source_id, {"source_class": "unknown", "proxy_flag": 0, "default_status": "unknown", "default_reason": "source not registered"}))
    manifest_path = manifests.get(source_id)
    if manifest_path and manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            base["status"] = payload.get("status", base["default_status"])
            base["reason"] = payload.get("next_action") or payload.get("browser_observation") or base["default_reason"]
            base["manifest"] = str(manifest_path)
        except (OSError, ValueError):
            base["status"] = "manifest_unreadable"
            base["reason"] = "source manifest could not be parsed"
    else:
        base["status"] = base["default_status"]
        base["reason"] = base["default_reason"]
    return base


def _read_input(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    aliases = {
        "time": "observed_at",
        "timestamp": "observed_at",
        "datetime": "observed_at",
        "value": "clean_value",
        "observed_value": "clean_value",
        "variable": "variable_code",
        "unit_code": "unit",
    }
    for old, new in aliases.items():
        if old in frame.columns and new not in frame.columns:
            frame[new] = frame[old]
    required = {"observed_at", "variable_code", "clean_value"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"hydrology input missing columns: {sorted(missing)}")
    for column in ("source_id", "station_id", "unit", "source_unit", "value_origin"):
        if column not in frame.columns:
            frame[column] = None
    frame["source_id"] = frame["source_id"].fillna("unknown_source")
    frame["station_id"] = frame["station_id"].fillna("unknown_station")
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True, errors="coerce")
    frame = frame[frame["observed_at"].notna()].copy()
    return frame


def _water_level_checks(frame: pd.DataFrame, jump_threshold_m_per_day: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    water = frame[frame["variable_code"] == "water_level"].copy()
    if water.empty:
        return water, {"status": "not_available", "rows": 0, "jump_flags": 0}
    water = water.sort_values(["station_id", "observed_at"])
    water["delta_hours"] = water.groupby("station_id")["observed_at"].diff().dt.total_seconds() / 3600.0
    water["delta_m"] = water.groupby("station_id")["canonical_value"].diff()
    water["delta_m_per_day"] = water["delta_m"] / (water["delta_hours"] / 24.0)
    water["water_level_jump_flag"] = water["delta_m_per_day"].abs() > float(jump_threshold_m_per_day)
    return water, {"status": "available", "rows": int(len(water)), "jump_flags": int(water["water_level_jump_flag"].sum()), "threshold_m_per_day": float(jump_threshold_m_per_day)}


def _lag_summary(frame: pd.DataFrame, max_lag_days: int) -> dict[str, Any]:
    rain = frame[frame["variable_code"] == "precipitation"].copy()
    level = frame[frame["variable_code"] == "water_level"].copy()
    if rain.empty or level.empty:
        return {"status": "not_available", "reason": "precipitation and water_level overlap required", "best_lag_days": None, "best_correlation": None, "sample_count": 0}
    rain_daily = rain.set_index("observed_at")["canonical_value"].resample("1D").mean()
    level_daily = level.set_index("observed_at")["canonical_value"].resample("1D").mean().diff()
    candidates: list[tuple[int, float, int]] = []
    for lag in range(0, int(max_lag_days) + 1):
        paired = pd.concat([rain_daily.shift(lag), level_daily], axis=1).dropna()
        if len(paired) < 10 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
            continue
        correlation = float(paired.iloc[:, 0].corr(paired.iloc[:, 1]))
        if np.isfinite(correlation):
            candidates.append((lag, correlation, len(paired)))
    if not candidates:
        return {"status": "insufficient_overlap", "reason": "fewer than 10 paired daily samples or zero variance", "best_lag_days": None, "best_correlation": None, "sample_count": 0}
    best = max(candidates, key=lambda item: abs(item[1]))
    return {"status": "available", "best_lag_days": best[0], "best_correlation": best[1], "sample_count": best[2], "tested_lag_days": int(max_lag_days)}


def _flow_sign_summary(frame: pd.DataFrame) -> dict[str, Any]:
    flow = frame[frame["variable_code"].isin({"discharge", "inflow_discharge", "outflow_discharge"})].copy()
    if flow.empty:
        return {"status": "not_available", "rows": 0, "sign_flags": 0, "policy": "inflow positive; outflow negative in signed canonical representation"}
    flags: list[bool] = []
    for _, row in flow.iterrows():
        value = row["canonical_value"]
        variable = row["variable_code"]
        if variable == "inflow_discharge":
            flags.append(value < 0)
        elif variable == "outflow_discharge":
            flags.append(value > 0)
        else:
            flags.append(False)
    return {"status": "available", "rows": int(len(flow)), "sign_flags": int(sum(flags)), "policy": "inflow positive; outflow negative in signed canonical representation"}


def _inventory_rows(meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_id, item in meta.items():
        rows.append({
            "check_type": "source_availability",
            "source_id": source_id,
            "source_class": item["source_class"],
            "source_status": item["status"],
            "source_status_reason": item["reason"],
            "proxy_flag": item["proxy_flag"],
            "observed_value": None,
            "web_value": None,
            "proxy_value": None,
            "unit_status": "not_applicable",
            "water_level_datum_status": "not_applicable",
        })
    return rows


def run_hydrology_consistency(
    *,
    input_paths: Iterable[Path | str] = (DEFAULT_INPUT,),
    output_csv: Path | str = DEFAULT_OUTPUT_CSV,
    report_path: Path | str = DEFAULT_REPORT,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    tba_manifest: Path | str = DEFAULT_TBA_MANIFEST,
    mwr_manifest: Path | str = DEFAULT_MWR_MANIFEST,
    glofas_manifest: Path | str = DEFAULT_GLOFAS_MANIFEST,
    jump_threshold_m_per_day: float = 0.3,
    max_lag_days: int = 30,
) -> dict[str, Any]:
    """Run unit, datum, jump, sign, and rainfall-lag checks."""

    paths = [Path(path) for path in input_paths]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        result = {"task_id": "P07-06", "status": "BLOCKED_DATA", "data_truth": "input_plan_only", "missing_inputs": missing, "next_action": "provide a normalized historical or authorized hydrology CSV"}
        target = Path(manifest_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    frame = pd.concat([_read_input(path) for path in paths], ignore_index=True)
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        variable = str(row["variable_code"])
        source_unit = row.get("source_unit") or row.get("unit")
        canonical, target_unit, unit_status, conversion_rule = _convert_value(variable, row["clean_value"], source_unit)
        source_id = str(row["source_id"])
        meta = SOURCE_INVENTORY.get(source_id, {"source_class": "observed" if row.get("value_origin") == "observed" else "unknown", "proxy_flag": int(row.get("proxy_flag", 0) or 0), "default_status": "unknown", "default_reason": "unregistered source"})
        origin = str(row.get("value_origin") or meta.get("source_class") or "unknown")
        observed_value = canonical if origin == "observed" else None
        web_value = canonical if origin in {"web", "web_snapshot"} else None
        proxy_value = canonical if origin in {"proxy", "forecast_proxy"} else None
        records.append({
            "check_type": "observation",
            "observed_at": row["observed_at"].isoformat(),
            "station_id": row["station_id"],
            "variable_code": variable,
            "source_id": source_id,
            "source_class": meta.get("source_class", "unknown"),
            "source_status": "available",
            "source_status_reason": "value present in input file",
            "source_unit": source_unit,
            "unit": target_unit,
            "unit_status": unit_status,
            "conversion_rule": conversion_rule,
            "canonical_value": canonical,
            "observed_value": observed_value,
            "web_value": web_value,
            "proxy_value": proxy_value,
            "proxy_flag": int(meta.get("proxy_flag", 0)),
            "water_level_datum_status": "unknown_not_inferred" if variable == "water_level" else "not_applicable",
            "water_level_jump_flag": None,
            "delta_m": None,
            "delta_hours": None,
            "delta_m_per_day": None,
            "flow_sign_flag": None,
        })
    observation_frame = pd.DataFrame(records)
    numeric_frame = frame.copy()
    numeric_frame["canonical_value"] = [record["canonical_value"] for record in records]
    water, jump_summary = _water_level_checks(numeric_frame, jump_threshold_m_per_day)
    if not water.empty:
        for _, check in water.iterrows():
            matches = (observation_frame["source_id"] == check["source_id"]) & (observation_frame["station_id"] == check["station_id"]) & (observation_frame["variable_code"] == "water_level") & (observation_frame["observed_at"] == check["observed_at"].isoformat())
            observation_frame.loc[matches, ["water_level_jump_flag", "delta_m", "delta_hours", "delta_m_per_day"]] = [bool(check["water_level_jump_flag"]), check["delta_m"], check["delta_hours"], check["delta_m_per_day"]]
    lag_summary = _lag_summary(numeric_frame, max_lag_days)
    flow_summary = _flow_sign_summary(numeric_frame)
    summary_rows = [
        {"check_type": "rainfall_lag_summary", "source_id": "taihu_thqbca_history", "source_class": "observed", "source_status": lag_summary["status"], "lag_days": lag_summary.get("best_lag_days"), "lag_correlation": lag_summary.get("best_correlation"), "lag_sample_count": lag_summary.get("sample_count")},
        {"check_type": "flow_sign_summary", "source_id": "taihu_thqbca_history", "source_class": "observed", "source_status": flow_summary["status"], "flow_sign_flags": flow_summary.get("sign_flags"), "flow_sign_policy": flow_summary["policy"]},
    ]
    manifests = {"tba_current_level": Path(tba_manifest), "mwr_hfc": Path(mwr_manifest), "glofas_forecast": Path(glofas_manifest)}
    inventory = {source_id: _source_meta(source_id, manifests) for source_id in ("taihu_thqbca_history", "tba_current_level", "mwr_hfc", "glofas_forecast")}
    output_frame = pd.concat([observation_frame, pd.DataFrame(summary_rows), pd.DataFrame(_inventory_rows(inventory))], ignore_index=True, sort=False)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    output_frame.to_csv(output, index=False, encoding="utf-8-sig")
    report = {
        "task_id": "P07-06",
        "status": "completed",
        "data_truth": "real_external_historical_observations_plus_explicit_blocked_source_inventory",
        "input_paths": [str(path) for path in paths],
        "output_csv": str(output),
        "rows": int(len(output_frame)),
        "observation_rows": int(len(observation_frame)),
        "source_inventory": inventory,
        "checks": {"water_level_jump": jump_summary, "rainfall_to_water_level_lag": lag_summary, "flow_sign": flow_summary},
        "datum_policy": "vertical datum is never inferred; TBA/web values remain pending confirmation",
        "flow_sign_policy": flow_summary["policy"],
        "proxy_policy": "GloFAS remains proxy_flag=1 and is never placed in observed_value",
        "unit_policy": CANONICAL_UNITS,
        "retrieved_at_utc": utc_now(),
    }
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest_file = Path(manifest_path)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps({**report, "manifest": str(manifest_file)}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return {**report, "manifest": str(manifest_file), "report": str(report_file)}


__all__ = ["DEFAULT_INPUT", "DEFAULT_MANIFEST", "DEFAULT_OUTPUT_CSV", "DEFAULT_REPORT", "run_hydrology_consistency"]
