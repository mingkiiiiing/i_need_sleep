"""NOAA/NCEP GFS backup adapter using the official NOMADS GRIB filter."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

from ..provenance import build_asset_manifest
from .common import download_asset
from .ecmwf_open_data import _bbox_mean, _iso, _lead_hours


UTC = timezone.utc
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)
DEFAULT_VARIABLES = ("TMP", "UGRD", "VGRD", "APCP", "DSWRF", "TCDC", "PRMSL")
GFS_PARAMETER_MAP: dict[str, tuple[str, str, str]] = {
    "TMP": ("air_temperature", "degC", "K_to_degC"),
    "T2M": ("air_temperature", "degC", "K_to_degC"),
    "UGRD": ("wind_u", "m/s", "identity"),
    "U10": ("wind_u", "m/s", "identity"),
    "VGRD": ("wind_v", "m/s", "identity"),
    "V10": ("wind_v", "m/s", "identity"),
    "APCP": ("precipitation", "mm", "kg_m2_to_mm"),
    "TP": ("precipitation", "mm", "kg_m2_to_mm"),
    "DSWRF": ("shortwave_radiation", "W/m2", "identity"),
    # NOMADS GFS exposes the surface-downward shortwave field with the
    # GRIB short name ``sdswrf`` even when the filter request uses DSWRF.
    # Keep both names so the source contract is stable across cfgrib/eccodes
    # versions and the field is not silently dropped during parsing.
    "SDSWRF": ("shortwave_radiation", "W/m2", "identity"),
    "TCDC": ("cloud_cover", "percent", "fraction_to_percent"),
    "PRMSL": ("air_pressure", "hPa", "Pa_to_hPa"),
}
_LEVELS = {
    "TMP": "lev_2_m_above_ground=on",
    "UGRD": "lev_10_m_above_ground=on",
    "VGRD": "lev_10_m_above_ground=on",
    "APCP": "lev_surface=on",
    "DSWRF": "lev_surface=on",
    "TCDC": "lev_entire_atmosphere=on",
    "PRMSL": "lev_mean_sea_level=on",
}


def build_gfs_filter_url(
    run_date: str,
    cycle: int,
    step: int,
    *,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    base_url: str = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl",
) -> str:
    """Build a NOMADS bbox/variable-filter URL for one GFS forecast step."""
    if cycle not in {0, 6, 12, 18}:
        raise ValueError("GFS cycle must be 0, 6, 12, or 18 UTC")
    if step < 0 or step > 384:
        raise ValueError("GFS step must be between 0 and 384 hours")
    variables = [str(variable).upper() for variable in variables]
    unknown = sorted(set(variables) - set(DEFAULT_VARIABLES))
    if unknown:
        raise ValueError(f"unsupported GFS variables: {unknown}")
    west, south, east, north = bbox
    date_compact = run_date.replace("-", "")
    filename = f"gfs.t{cycle:02d}z.pgrb2.0p25.f{step:03d}"
    params: list[tuple[str, Any]] = [
        ("file", filename),
        ("subregion", "on"),
        ("leftlon", west), ("rightlon", east), ("toplat", north), ("bottomlat", south),
    ]
    # Only activate requested levels and variables; never request all fields.
    for variable in variables:
        params.append((f"var_{variable}", "on"))
        level = _LEVELS.get(variable)
        if level:
            key, value = level.split("=", 1)
            params.append((key, value))
    params.append(("dir", f"/gfs.{date_compact}/{cycle:02d}/atmos"))
    return f"{base_url}?{urlencode(params)}"


def _convert(parameter: str, value: float) -> float:
    if parameter in {"TMP", "T2M"}:
        return value - 273.15
    if parameter in {"TCDC"}:
        return value * 100.0 if value <= 1.0 else value
    if parameter == "PRMSL":
        return value / 100.0
    return value


def _parameter_name(data: Any, variable_name: str) -> str | None:
    raw = str(data.attrs.get("GRIB_shortName") or variable_name).upper()
    aliases = {"2T": "TMP", "T2M": "T2M", "10U": "U10", "10V": "V10", "TP": "TP", "APCP": "APCP", "PRMSL": "PRMSL", "TCC": "TCDC"}
    return aliases.get(raw, raw) if raw in GFS_PARAMETER_MAP or raw in aliases else None


def parse_gfs_grib(
    grib_path: Path,
    *,
    run_time: str,
    fallback_lead_hours: float,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    output_csv: Path | None = None,
) -> dict[str, Any]:
    """Parse one filtered GFS GRIB file into NOAA-labelled area means."""
    try:
        import cfgrib
        import numpy as np
    except ImportError as exc:
        return {"status": "BLOCKED_DEPENDENCY", "error": f"GRIB parser unavailable: {exc}", "records": 0}
    reference = datetime.fromisoformat(run_time.replace("Z", "+00:00"))
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for dataset in cfgrib.open_datasets(str(grib_path), backend_kwargs={"indexpath": ""}):
        for name, data in dataset.data_vars.items():
            parameter = _parameter_name(data, name)
            if parameter is None:
                continue
            mean_data = _bbox_mean(data, bbox)
            dims = list(mean_data.dims)
            shape = mean_data.shape
            coords = {dim: mean_data[dim].values for dim in dims if dim in mean_data.coords}
            for index in np.ndindex(shape or (1,)):
                raw_value = float(np.asarray(mean_data.values)[index]) if shape else float(mean_data.values)
                step_value = coords.get("step", [fallback_lead_hours])[index[dims.index("step")]] if "step" in dims else fallback_lead_hours
                lead_hours = _lead_hours(step_value)
                if lead_hours == 0 and fallback_lead_hours:
                    lead_hours = fallback_lead_hours
                valid = reference + timedelta(hours=lead_hours)
                member = coords.get("number", [0])[index[dims.index("number")]] if "number" in dims else 0
                variable_code, unit, conversion_rule = GFS_PARAMETER_MAP[parameter]
                step_type = str(data.attrs.get("GRIB_stepType") or "unknown")
                rows.append({
                    "source_id": "noaa_gfs", "model_name": "NOAA_GFS", "model_variant": "GFS 0.25 degree",
                    "station_id": "TAIHU_AREA_MEAN", "forecast_reference_time": _iso(reference), "valid_time": _iso(valid),
                    "lead_hours": lead_hours, "ensemble_member": int(member) if member is not None else 0,
                    "variable_code": variable_code, "source_parameter": parameter, "value": _convert(parameter, raw_value),
                    "source_value": raw_value, "unit": unit, "source_unit": "K" if parameter in {"TMP", "T2M"} else "Pa" if parameter == "PRMSL" else "kg/m2" if parameter in {"APCP", "TP"} else unit,
                    "conversion_rule": conversion_rule, "bbox_west": bbox[0], "bbox_south": bbox[1], "bbox_east": bbox[2], "bbox_north": bbox[3],
                    "step_type": step_type, "raw_grib_path": str(grib_path), "value_origin": "forecast", "is_imputed": False,
                    "_priority": 0 if step_type == "instant" else 1,
                })
    # Some GFS files contain both instantaneous and averaged cloud cover
    # messages. Keep one value per variable/lead/member, preferring instant.
    unique: dict[tuple[str, float, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["variable_code"], float(row["lead_hours"]), int(row["ensemble_member"]))
        if key not in unique or row["_priority"] < unique[key]["_priority"]:
            unique[key] = row
    rows = list(unique.values())
    for row in rows:
        row.pop("_priority", None)
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        columns = list(rows[0]) if rows else ["source_id", "model_name", "forecast_reference_time", "valid_time", "lead_hours", "variable_code", "value"]
        with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    return {"status": "completed", "records": len(rows), "rows": rows, "output": str(output_csv) if output_csv else None,
            "variables": sorted({row["variable_code"] for row in rows}), "coverage_hours": max((row["lead_hours"] for row in rows), default=0)}


def download_gfs_run(
    run_date: str,
    cycle: int,
    *,
    steps: Iterable[int] = range(0, 73, 6),
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    raw_root: Path | None = None,
) -> dict[str, Any]:
    package_root = Path(__file__).resolve().parents[2]
    raw_root = Path(raw_root) if raw_root else package_root / "storage" / "raw" / "meteorology" / "noaa_gfs"
    raw_root.mkdir(parents=True, exist_ok=True)
    run_time = f"{run_date}T{cycle:02d}:00:00+00:00"
    assets: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for step in sorted({int(item) for item in steps}):
        url = build_gfs_filter_url(run_date, cycle, step, bbox=bbox, variables=variables)
        target = raw_root / f"gfs_{run_date}_{cycle:02d}z_f{step:03d}_taihu_subset.grib2"
        try:
            result = download_asset("noaa_gfs", target.stem, url, target, license_tag="NOAA-open-US-government-data", redistribution_allowed="review-NOAA-terms", commercial_use="review-NOAA-terms")
            assets.append({"step": step, "url": url, **result})
        except Exception as exc:
            errors.append({"step": step, "url": url, "error": str(exc)})
    return {"status": "completed" if assets and not errors else "BLOCKED_REMOTE", "run_time": run_time, "assets": assets, "errors": errors, "bbox": bbox, "variables": list(variables)}


def run_gfs(
    run_date: str,
    cycle: int,
    *,
    steps: Iterable[int] = range(0, 73, 6),
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    raw_root: Path | None = None,
    silver_root: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    download = download_gfs_run(run_date, cycle, steps=steps, bbox=bbox, variables=variables, raw_root=raw_root)
    rows: list[dict[str, Any]] = []
    if download["assets"]:
        silver_root = Path(silver_root) if silver_root else Path(__file__).resolve().parents[2] / "storage" / "silver" / "forecast" / "noaa_gfs"
        for asset in download["assets"]:
            parsed = parse_gfs_grib(Path(asset["path"]), run_time=download["run_time"], fallback_lead_hours=float(asset["step"]), bbox=bbox)
            if parsed["status"] != "completed":
                download["errors"].append({"step": asset["step"], "error": parsed.get("error")})
                continue
            rows.extend(parsed.pop("rows", []))
        output_csv = silver_root / f"noaa_gfs_{run_date}_{cycle:02d}z_area_mean.csv"
        if rows:
            output_csv.parent.mkdir(parents=True, exist_ok=True)
            columns = list(rows[0])
            with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        download["parsed_output"] = str(output_csv)
        download["records"] = len(rows)
        download["coverage_hours"] = max((row["lead_hours"] for row in rows), default=0)
    download["real_batch"] = bool(rows) and not download["errors"]
    path = Path(manifest_path) if manifest_path else Path(__file__).resolve().parents[2] / "storage" / "manifests" / f"noaa_gfs_{run_date}_{cycle:02d}z.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(download, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    download["manifest_path"] = str(path)
    return download


__all__ = ["DEFAULT_BBOX", "DEFAULT_VARIABLES", "GFS_PARAMETER_MAP", "build_gfs_filter_url", "parse_gfs_grib", "download_gfs_run", "run_gfs"]
