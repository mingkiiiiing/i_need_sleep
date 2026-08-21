from __future__ import annotations

"""GloFAS hydrological proxy adapter for Taihu inflow context.

GloFAS is a modelled river-discharge forecast, not a Taihu in-lake gauge.  All
records emitted here carry ``proxy_flag=1`` and ``value_origin=forecast_proxy``.
The adapter builds the official EWDS request plan and parses a legally obtained
NetCDF/GRIB/CSV/JSON export; without CDS/EWDS credentials it stops at the plan.
"""

import csv
import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .common import PACKAGE_ROOT, RAW_ROOT, utc_now
from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest


DATASET = "cems-glofas-forecast"
SOURCE_ID = "glofas_forecast"
EWDS_URL = "https://ewds.climate.copernicus.eu/datasets/cems-glofas-forecast?tab=download"
DEFAULT_AREA = (31.65, 119.00, 30.90, 121.00)  # north, west, south, east; Taihu vicinity, not a basin boundary
DEFAULT_VARIABLE = "river_discharge_in_the_last_24_hours"
DEFAULT_LEAD_HOURS = tuple(range(24, 745, 24))
DISCHARGE_NAMES = {"river_discharge_in_the_last_24_hours", "average_river_discharge_in_the_last_24_hours", "river_discharge", "discharge", "dis24", "streamflow"}
RUNOFF_NAMES = {"runoff", "surface_runoff", "ro", "total_runoff"}


def _validate_area(area: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if len(area) != 4:
        raise ValueError("area must be north,west,south,east")
    north, west, south, east = map(float, area)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("area must be north,west,south,east in WGS84")
    return north, west, south, east


def build_glofas_request(
    run_date: str | datetime,
    *,
    area: tuple[float, float, float, float] = DEFAULT_AREA,
    lead_hours: Iterable[int] = DEFAULT_LEAD_HOURS,
    variable: str = DEFAULT_VARIABLE,
    product_type: str = "control_forecast",
    system_version: str = "operational",
    data_format: str = "grib2",
    download_format: str = "zip",
    timespan: str | None = None,
) -> dict[str, Any]:
    """Build the EWDS/CDS API request shown by the official GloFAS docs."""

    if isinstance(run_date, datetime):
        parsed = run_date
    else:
        parsed = datetime.fromisoformat(str(run_date).replace("Z", "+00:00"))
    north, west, south, east = _validate_area(area)
    leads = [int(value) for value in lead_hours]
    if not leads or any(value < 0 for value in leads):
        raise ValueError("lead_hours must contain non-negative integers")
    if data_format not in {"grib", "grib2", "netcdf"}:
        raise ValueError("data_format must be grib, grib2 or netcdf")
    if download_format not in {"zip", "unarchived"}:
        raise ValueError("download_format must be zip or unarchived")
    request: dict[str, Any] = {
        "system_version": system_version,
        "hydrological_model": "lisflood",
        "product_type": product_type,
        "variable": variable,
        "year": parsed.strftime("%Y"),
        "month": parsed.strftime("%m"),
        "day": parsed.strftime("%d"),
        "leadtime_hour": [str(value) for value in leads],
        "area": [north, west, south, east],
        "data_format": data_format,
        "download_format": download_format,
    }
    if timespan:
        request["timespan"] = timespan
    return request


def _credentials_present() -> bool:
    if os.environ.get("TAIHU_CDS_API_KEY"):
        return True
    candidates = [Path.home() / ".cdsapirc", Path.home() / ".config" / "cdsapi" / "config"]
    for path in candidates:
        try:
            if path.is_file() and "key:" in path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _normalize_long_records(records: list[dict[str, Any]], *, source_file: str, data_truth: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(records, start=2):
        variable_raw = raw.get("variable") or raw.get("variable_code") or raw.get("parameter") or "river_discharge"
        variable_key = str(variable_raw).strip()
        if variable_key in RUNOFF_NAMES or variable_key.casefold() in RUNOFF_NAMES:
            variable_code, unit = "runoff", raw.get("unit") or "mm"
        elif variable_key in DISCHARGE_NAMES or variable_key.casefold() in {item.casefold() for item in DISCHARGE_NAMES}:
            variable_code, unit = "river_discharge", raw.get("unit") or "m3/s"
        else:
            variable_code, unit = variable_key, raw.get("unit")
        value = _as_float(raw.get("value") if raw.get("value") is not None else raw.get("clean_value"))
        if value is None:
            continue
        valid_time = raw.get("valid_time") or raw.get("observed_at") or raw.get("time")
        reference_time = raw.get("forecast_reference_time") or raw.get("reference_time") or raw.get("run_time")
        valid_text = str(valid_time).replace(" ", "T") if valid_time not in (None, "") else None
        reference_text = str(reference_time).replace(" ", "T") if reference_time not in (None, "") else None
        lead_hours = _as_float(raw.get("lead_hours"))
        if lead_hours is None and valid_text and reference_text:
            try:
                valid_dt = datetime.fromisoformat(valid_text.replace("Z", "+00:00"))
                ref_dt = datetime.fromisoformat(reference_text.replace("Z", "+00:00"))
                lead_hours = (valid_dt - ref_dt).total_seconds() / 3600.0
            except ValueError:
                lead_hours = None
        rows.append({
            "source_id": SOURCE_ID,
            "source_file": source_file,
            "source_row": f"{index}:{variable_raw}",
            "forecast_reference_time": reference_text,
            "valid_time": valid_text,
            "lead_hours": lead_hours,
            "ensemble_member": raw.get("ensemble_member") if raw.get("ensemble_member") not in (None, "") else raw.get("member"),
            "latitude": _as_float(raw.get("latitude") if raw.get("latitude") is not None else raw.get("lat")),
            "longitude": _normalize_longitude(_as_float(raw.get("longitude") if raw.get("longitude") is not None else raw.get("lon"))),
            "variable_code": variable_code,
            "source_parameter": variable_raw,
            "value": value,
            "unit": unit,
            "value_origin": "forecast_proxy",
            "proxy_flag": 1,
            "data_truth": data_truth,
            "quality_flags": [],
        })
    return rows


def _normalize_longitude(value: float | None) -> float | None:
    if value is None:
        return None
    return value - 360.0 if value > 180.0 else value


def parse_glofas_tabular(path: Path | str) -> dict[str, Any]:
    """Parse a user-supplied long CSV/JSON GloFAS export."""

    path = Path(path)
    raw = path.read_bytes()
    if path.suffix.casefold() == ".json":
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("records") or payload.get("data") or payload.get("rows") or []
        records = [dict(item) for item in payload if isinstance(item, dict)]
    else:
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(text.splitlines())
        records = [dict(row) for row in reader]
    rows = _normalize_long_records(records, source_file=str(path), data_truth="user_supplied_glofas_export")
    return {"status": "parsed", "source_id": SOURCE_ID, "rows": rows, "record_count": len(rows), "input_path": str(path), "data_truth": "user_supplied_glofas_export"}


def _find_coord(dataset: Any, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in dataset.coords or name in dataset.dims:
            return name
    return None


def _time_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        text = value.isoformat()
    else:
        text = str(value)
    return text.replace(" ", "T")


def parse_glofas_dataset(path: Path | str, *, area: tuple[float, float, float, float] = DEFAULT_AREA) -> dict[str, Any]:
    """Parse NetCDF/GRIB exports and keep grid/ensemble dimensions explicit."""

    import numpy as np
    import xarray as xr

    path = Path(path)
    open_kwargs: dict[str, Any] = {}
    if path.suffix.casefold() in {".grib", ".grib2", ".grb", ".grb2"}:
        open_kwargs["engine"] = "cfgrib"
    dataset = xr.open_dataset(path, **open_kwargs)
    try:
        lat_dim = _find_coord(dataset, ("latitude", "lat"))
        lon_dim = _find_coord(dataset, ("longitude", "lon"))
        time_dim = _find_coord(dataset, ("valid_time", "time"))
        if lat_dim is None or lon_dim is None or time_dim is None:
            raise ValueError("GloFAS export requires latitude/longitude/time or valid_time coordinates")
        north, west, south, east = _validate_area(area)
        variables = [name for name in dataset.data_vars if name in DISCHARGE_NAMES or name.casefold() in {item.casefold() for item in DISCHARGE_NAMES} or name in RUNOFF_NAMES or name.casefold() in {item.casefold() for item in RUNOFF_NAMES}]
        if not variables:
            raise ValueError("GloFAS export has no recognized discharge/runoff variable")
        rows: list[dict[str, Any]] = []
        for variable in variables:
            data = dataset[variable]
            frame = data.to_dataframe(name="value").reset_index()
            for index, raw in frame.iterrows():
                lat = _as_float(raw.get(lat_dim))
                lon = _normalize_longitude(_as_float(raw.get(lon_dim)))
                if lat is None or lon is None or not (south <= lat <= north and west <= lon <= east):
                    continue
                value = _as_float(raw.get("value"))
                if value is None:
                    continue
                valid = raw.get("valid_time") if "valid_time" in frame.columns else raw.get(time_dim)
                reference = raw.get("forecast_reference_time") if "forecast_reference_time" in frame.columns else raw.get("time")
                if "step" in frame.columns and reference is not None and "valid_time" not in frame.columns:
                    try:
                        valid = reference + raw.get("step")
                    except TypeError:
                        pass
                lead = None
                try:
                    if reference is not None and valid is not None:
                        lead = (valid - reference).total_seconds() / 3600.0
                except (AttributeError, TypeError):
                    pass
                attrs = dataset[variable].attrs
                unit = attrs.get("units") or ("mm" if variable.casefold() in {item.casefold() for item in RUNOFF_NAMES} else "m3/s")
                member = next((raw.get(name) for name in ("number", "ensemble_member", "member") if name in frame.columns), None)
                rows.append({
                    "source_id": SOURCE_ID,
                    "source_file": str(path),
                    "source_row": f"{index}:{variable}",
                    "forecast_reference_time": _time_string(reference),
                    "valid_time": _time_string(valid),
                    "lead_hours": lead,
                    "ensemble_member": member,
                    "latitude": lat,
                    "longitude": lon,
                    "variable_code": "runoff" if variable.casefold() in {item.casefold() for item in RUNOFF_NAMES} else "river_discharge",
                    "source_parameter": variable,
                    "value": value,
                    "unit": unit,
                    "value_origin": "forecast_proxy",
                    "proxy_flag": 1,
                    "data_truth": "real_external_netcdf_or_official_schema_fixture",
                    "quality_flags": [],
                })
        return {"status": "parsed", "source_id": SOURCE_ID, "rows": rows, "record_count": len(rows), "input_path": str(path), "area": list(area), "data_truth": "real_external_netcdf_or_official_schema_fixture"}
    finally:
        dataset.close()


def aggregate_glofas_ensemble(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Produce one proxy summary per valid time/grid/variable."""

    groups: dict[tuple[Any, ...], list[float]] = {}
    member_values: dict[tuple[Any, ...], list[Any]] = {}
    for row in rows:
        key = (row.get("valid_time"), row.get("latitude"), row.get("longitude"), row.get("variable_code"), row.get("unit"))
        value = _as_float(row.get("value"))
        if value is None:
            continue
        groups.setdefault(key, []).append(value)
        member_values.setdefault(key, []).append(row.get("ensemble_member"))
    summaries: list[dict[str, Any]] = []
    for key, values in sorted(groups.items(), key=lambda item: tuple(str(x) for x in item[0])):
        values = sorted(values)
        count = len(values)
        mean = sum(values) / count
        p10 = values[max(0, min(count - 1, math.ceil(0.10 * count) - 1))]
        p50 = values[max(0, min(count - 1, math.ceil(0.50 * count) - 1))]
        p90 = values[max(0, min(count - 1, math.ceil(0.90 * count) - 1))]
        variance = sum((value - mean) ** 2 for value in values) / count
        summaries.append({
            "source_id": SOURCE_ID,
            "valid_time": key[0],
            "latitude": key[1],
            "longitude": key[2],
            "variable_code": key[3],
            "unit": key[4],
            "value": mean,
            "ensemble_mean": mean,
            "ensemble_std": math.sqrt(variance),
            "ensemble_p10": p10,
            "ensemble_p50": p50,
            "ensemble_p90": p90,
            "ensemble_min": values[0],
            "ensemble_max": values[-1],
            "ensemble_count": count,
            "proxy_flag": 1,
            "value_origin": "forecast_proxy",
            "ensemble_members_seen": json.dumps(member_values[key], ensure_ascii=False),
        })
    return summaries


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_glofas(
    *,
    run_date: str | datetime,
    input_path: Path | str | None = None,
    area: tuple[float, float, float, float] = DEFAULT_AREA,
    lead_hours: Iterable[int] = DEFAULT_LEAD_HOURS,
    output_root: Path | str | None = None,
    raw_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
    authorization_evidence_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create an official request plan or parse an authorized local export."""

    output_dir = Path(output_root) if output_root else PACKAGE_ROOT / "storage" / "silver" / "glofas"
    manifest = Path(manifest_path) if manifest_path else PACKAGE_ROOT / "storage" / "manifests" / "glofas_p07_03.json"
    evidence = Path(authorization_evidence_path) if authorization_evidence_path else None
    request = build_glofas_request(run_date, area=area, lead_hours=lead_hours)
    result: dict[str, Any] = {
        "task_id": "P07-03",
        "source_id": SOURCE_ID,
        "status": "BLOCKED_AUTH",
        "data_truth": "official_request_plan_only",
        "dataset": DATASET,
        "ewds_url": EWDS_URL,
        "request": request,
        "area_role": "Taihu vicinity grid proxy; not an observed inflow basin boundary",
        "proxy_flag_policy": 1,
        "value_origin_policy": "forecast_proxy",
        "credentials_present": _credentials_present(),
        "authorization_evidence_path": str(evidence) if evidence else None,
        "input_path": str(input_path) if input_path else None,
        "output_root": str(output_dir),
        "records": 0,
        "ensemble_summary_records": 0,
        "raw_asset_path": None,
        "asset_manifest": None,
        "proxy_values_csv": None,
        "ensemble_stats_csv": None,
        "warnings": [],
        "retrieved_at_utc": utc_now(),
        "manifest": str(manifest),
    }
    if input_path is None:
        result["next_action"] = "配置CDS/EWDS凭证并按官方request下载区域GloFAS文件；或提供合法NetCDF/GRIB/CSV/JSON导出并登记授权"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    source_path = Path(input_path)
    suffix = source_path.suffix.casefold()
    if suffix in {".nc", ".nc4", ".netcdf", ".grib", ".grib2", ".grb", ".grb2"}:
        parsed = parse_glofas_dataset(source_path, area=area)
    elif suffix in {".csv", ".json"}:
        parsed = parse_glofas_tabular(source_path)
    else:
        raise ValueError(f"unsupported GloFAS export: {suffix}")
    raw_dir = (Path(raw_root) if raw_root else RAW_ROOT) / "glofas_forecast"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = raw_dir / f"{stamp}{suffix}"
    shutil.copyfile(source_path, raw_path)
    asset = build_asset_manifest(
        source_id=SOURCE_ID,
        asset_id=raw_path.stem,
        request_url=EWDS_URL,
        local_path=raw_path,
        retrieved_at_utc=utc_now(),
        http_status=None,
        response_headers={},
        license_tag="CEMS_FLOODS_LICENSE_PENDING_REVIEW",
        redistribution_allowed="conditional",
        commercial_use="conditional",
        status="completed" if evidence and evidence.exists() else "blocked",
    )
    asset_manifest_path = manifest_root(PACKAGE_ROOT) / f"raw_glofas_{stamp}.json"
    write_asset_manifest(asset, asset_manifest_path)
    rows = parsed["rows"]
    summaries = aggregate_glofas_ensemble(rows)
    authorized = bool(evidence and evidence.exists())
    values_path = output_dir / f"glofas_proxy_values_{stamp}.csv"
    stats_path = output_dir / f"glofas_ensemble_stats_{stamp}.csv"
    if authorized:
        _write_csv(values_path, rows)
        _write_csv(stats_path, summaries)
    result.update({
        "status": "completed" if authorized and rows else "BLOCKED_AUTH" if not authorized else "BLOCKED_DATA",
        "data_truth": "authorized_glofas_export" if authorized else "user_supplied_glofas_export_pending_authorization",
        "raw_asset_path": str(raw_path),
        "asset_manifest": str(asset_manifest_path),
        "records": len(rows),
        "ensemble_summary_records": len(summaries),
        "proxy_values_csv": str(values_path) if authorized else None,
        "ensemble_stats_csv": str(stats_path) if authorized else None,
        "warnings": ([] if authorized else ["GLOFAS_AUTHORIZATION_NOT_VERIFIED"]),
        "next_action": None if authorized else "登记EWDS/CDS条款或授权凭证后再发布代理CSV；代理值仍不得标成实测入湖流量",
    })
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


__all__ = [
    "DATASET",
    "DEFAULT_AREA",
    "DEFAULT_LEAD_HOURS",
    "DEFAULT_VARIABLE",
    "EWDS_URL",
    "SOURCE_ID",
    "aggregate_glofas_ensemble",
    "build_glofas_request",
    "parse_glofas_dataset",
    "parse_glofas_tabular",
    "run_glofas",
]
