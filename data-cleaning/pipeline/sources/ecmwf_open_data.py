"""ECMWF Open Data IFS/AIFS adapter for a bounded Taihu forecast window.

The adapter uses the official ``ecmwf-opendata`` client when installed.  It
requests only the configured variables, bbox and forecast steps, stores the
original GRIB2 object, and produces area-mean rows with reference/valid time
kept separate.  Missing client/GRIB dependencies are reported explicitly;
Open-Meteo is never relabelled as ECMWF.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..provenance import build_asset_manifest


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)  # west, south, east, north
DEFAULT_PARAMS = ("2t", "10u", "10v", "tp", "ssrd", "tcc", "msl")
PARAMETER_MAP: dict[str, tuple[str, str, str]] = {
    "2t": ("air_temperature", "degC", "K_to_degC"),
    "10u": ("wind_u", "m/s", "identity"),
    "10v": ("wind_v", "m/s", "identity"),
    "tp": ("precipitation", "mm", "m_to_mm"),
    "ssrd": ("shortwave_radiation", "W/m2", "J_m2_to_W_m2_by_step"),
    "tcc": ("cloud_cover", "percent", "fraction_to_percent"),
    "msl": ("air_pressure", "hPa", "Pa_to_hPa"),
}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    # ``numpy.datetime64[ns].item()`` returns an integer nanosecond count on
    # some NumPy/Python combinations.  Passing that integer to
    # ``datetime.fromisoformat`` can be interpreted as a completely different
    # (but syntactically valid) year.  Preserve the ISO representation before
    # unboxing scalar NumPy values.
    try:
        import numpy as np
        if isinstance(value, np.datetime64):
            value = np.datetime_as_string(value, unit="us")
    except ImportError:
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _lead_hours(value: Any) -> float:
    try:
        import numpy as np
        if isinstance(value, np.timedelta64):
            return float(value / np.timedelta64(1, "h"))
    except (ImportError, TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, timedelta):
        return value.total_seconds() / 3600.0
    text = str(value)
    if text.startswith("P") and "T" in text:
        # Minimal ISO duration support for xarray/netCDF-like coordinates.
        hours = 0.0
        body = text.split("T", 1)[1]
        if body.endswith("H"):
            hours = float(body[:-1])
        elif body.endswith("M"):
            hours = float(body[:-1]) / 60.0
        return hours
    try:
        return float(value) / 3600.0 if abs(float(value)) > 1000 else float(value)
    except (TypeError, ValueError):
        return 0.0


def build_ecmwf_request(
    run_date: str,
    cycle: int,
    steps: Iterable[int],
    *,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    parameters: Iterable[str] = DEFAULT_PARAMS,
    model: str = "ifs",
    stream: str = "oper",
    ensemble_member: int | None = None,
) -> dict[str, Any]:
    """Create a bounded ecmwf-opendata request with auditable fields."""
    if cycle not in {0, 6, 12, 18}:
        raise ValueError("ECMWF cycle must be one of 0, 6, 12, 18 UTC")
    selected = sorted({int(step) for step in steps})
    if not selected or min(selected) < 0 or max(selected) > 360:
        raise ValueError("forecast steps must be within 0..360 hours")
    params = [str(param) for param in parameters]
    unknown = sorted(set(params) - set(PARAMETER_MAP))
    if unknown:
        raise ValueError(f"unsupported ECMWF parameters: {unknown}")
    west, south, east, north = bbox
    request: dict[str, Any] = {
        "date": run_date,
        # ecmwf-opendata canonicalizes this as an integer hour (00/06/12/18).
        "time": cycle,
        "type": "fc",
        "stream": stream,
        "step": selected,
        "param": params,
        "area": [north, west, south, east],
        "grid": [0.25, 0.25],
        "format": "grib2",
        "model": model,
    }
    if ensemble_member is not None:
        request["number"] = int(ensemble_member)
    return request


def _convert(parameter: str, value: float, lead_hours: float) -> float:
    if parameter == "2t":
        return value - 273.15
    if parameter == "tp":
        return value * 1000.0
    if parameter == "msl":
        return value / 100.0
    if parameter == "tcc":
        return value * 100.0
    if parameter == "ssrd":
        return value / max(lead_hours * 3600.0, 3600.0)
    return value


def _bbox_mean(data: Any, bbox: tuple[float, float, float, float]) -> Any:
    import numpy as np

    dims = set(getattr(data, "dims", ()))
    lat_name = next((name for name in ("latitude", "lat") if name in dims), None)
    lon_name = next((name for name in ("longitude", "lon") if name in dims), None)
    if not lat_name or not lon_name:
        return data
    west, south, east, north = bbox
    lat = data[lat_name]
    lon = data[lon_name]
    lon_values = lon.values
    if np.nanmax(lon_values) > 180 and west < 0:
        west %= 360
        east %= 360
    mask = (lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
    selected = data.where(mask, drop=True)
    return selected.mean(dim=(lat_name, lon_name), skipna=True)


def parse_ecmwf_grib(
    grib_path: Path,
    *,
    run_time: str,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    output_csv: Path | None = None,
    source_id: str = "ecmwf_open_ifs_aifs",
) -> dict[str, Any]:
    """Parse GRIB2 through cfgrib/xarray and calculate bounded area means."""
    try:
        import cfgrib
        import numpy as np
    except ImportError as exc:
        return {"status": "BLOCKED_DEPENDENCY", "error": f"GRIB parser unavailable: {exc}", "records": 0}
    datasets = cfgrib.open_datasets(str(grib_path), backend_kwargs={"indexpath": ""})
    rows: list[dict[str, Any]] = []
    reference = datetime.fromisoformat(run_time.replace("Z", "+00:00"))
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    for dataset in datasets:
        for name, data in dataset.data_vars.items():
            parameter = str(data.attrs.get("GRIB_shortName") or name)
            if parameter not in PARAMETER_MAP:
                continue
            mean_data = _bbox_mean(data, bbox)
            coords = {dim: mean_data[dim].values for dim in mean_data.dims if dim in mean_data.coords}
            shape = getattr(mean_data, "shape", ())
            for index in np.ndindex(shape or (1,)):
                if shape:
                    value = float(np.asarray(mean_data.values)[index])
                    lead_value = coords.get("step", [0])[index[mean_data.dims.index("step")]] if "step" in mean_data.dims else 0
                    member = coords.get("number", [0])[index[mean_data.dims.index("number")]] if "number" in mean_data.dims else 0
                else:
                    value = float(mean_data.values)
                    lead_value, member = 0, 0
                lead_hours = _lead_hours(lead_value)
                valid_time = reference + timedelta(hours=lead_hours)
                variable_code, unit, rule = PARAMETER_MAP[parameter]
                rows.append({
                    "source_id": source_id, "model_name": "ECMWF", "model_variant": "IFS/AIFS",
                    "forecast_reference_time": _iso(reference), "valid_time": _iso(valid_time), "lead_hours": lead_hours,
                    "ensemble_member": int(member) if member is not None else 0, "variable_code": variable_code,
                    "source_parameter": parameter, "value": _convert(parameter, value, lead_hours), "source_value": value,
                    "unit": unit, "source_unit": {"2t": "K", "tp": "m", "ssrd": "J/m2", "msl": "Pa", "tcc": "fraction"}.get(parameter, unit),
                    "conversion_rule": rule, "bbox_west": bbox[0], "bbox_south": bbox[1], "bbox_east": bbox[2], "bbox_north": bbox[3],
                    "raw_grib_path": str(grib_path), "value_origin": "forecast", "is_imputed": False,
                })
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        columns = list(rows[0]) if rows else ["source_id", "forecast_reference_time", "valid_time", "lead_hours", "variable_code", "value"]
        with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    return {"status": "completed", "records": len(rows), "output": str(output_csv) if output_csv else None,
            "variables": sorted({row["variable_code"] for row in rows}), "coverage_hours": max((row["lead_hours"] for row in rows), default=0)}


def download_ecmwf_open_data(
    run_date: str,
    cycle: int,
    *,
    steps: Iterable[int] = range(0, 73, 3),
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    parameters: Iterable[str] = DEFAULT_PARAMS,
    raw_root: Path | None = None,
    source: str = "ecmwf",
    model: str = "ifs",
) -> dict[str, Any]:
    """Download one bounded forecast run using the official open-data client."""
    request = build_ecmwf_request(run_date, cycle, steps, bbox=bbox, parameters=parameters, model=model)
    package_root = Path(__file__).resolve().parents[2]
    raw_root = raw_root or STORAGE / "raw" / "meteorology" / "ecmwf_open_data"
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / f"ecmwf_{run_date}_{cycle:02d}z_0-360h.grib2"
    if target.exists() and target.stat().st_size > 0:
        cached_at = datetime.now(UTC).isoformat()
        manifest = build_asset_manifest(source_id="ecmwf_open_ifs_aifs", asset_id=target.name, local_path=target,
                                        request_url="https://data.ecmwf.int/forecasts/", retrieved_at_utc=cached_at,
                                        license_tag="ECMWF-open-data-terms", redistribution_allowed="review-current-terms",
                                        commercial_use="review-current-terms", status="completed")
        manifest.update({"request": request, "run_date": run_date, "cycle": cycle, "member": "deterministic",
                         "cached_existing": True, "spatial_window": "applied_during_grib_parsing"})
        return {"status": "completed", "target": str(target), "manifest": manifest, "request": request,
                "run_time": f"{run_date}T{cycle:02d}:00:00+00:00", "cached_existing": True}
    try:
        from ecmwf.opendata import Client
    except ImportError as exc:
        return {"status": "BLOCKED_DEPENDENCY", "request": request, "error": f"ecmwf-opendata unavailable: {exc}", "target": str(target)}
    try:
        # Bound retries so an unavailable public endpoint cannot hang a batch
        # or the repository's full verification suite for many minutes.
        client = Client(source=source, model=model, maximum_retries=1, retry_after=1, use_server_retry_after=False)
        # The client performs parameter/step sub-selection from the rolling
        # index.  area/grid/format are not accepted MARS post-processing
        # keywords by the current open-data client, so retain them in the
        # audit request and apply the Taihu bbox during GRIB parsing.
        client_request = {key: value for key, value in request.items() if key not in {"area", "grid", "format"}}
        result = client.retrieve(request=client_request, target=str(target))
        retrieved_at = datetime.now(UTC).isoformat()
        manifest = build_asset_manifest(source_id="ecmwf_open_ifs_aifs", asset_id=target.name, local_path=target,
                                        retrieved_at_utc=retrieved_at, license_tag="ECMWF-open-data-terms",
                                        redistribution_allowed="review-current-terms", commercial_use="review-current-terms")
        manifest.update({"request": request, "client_request": client_request, "run_date": run_date, "cycle": cycle, "member": "deterministic", "spatial_window": "applied_during_grib_parsing", "client_result": str(result)})
        return {"status": "completed", "target": str(target), "manifest": manifest, "request": request, "run_time": f"{run_date}T{cycle:02d}:00:00+00:00"}
    except Exception as exc:
        return {"status": "BLOCKED_REMOTE", "request": request, "target": str(target), "error": str(exc)}


def run_ecmwf_open_data(
    run_date: str,
    cycle: int,
    *,
    steps: Iterable[int] = range(0, 73, 3),
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    parameters: Iterable[str] = DEFAULT_PARAMS,
    raw_root: Path | None = None,
    silver_root: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    result = download_ecmwf_open_data(run_date, cycle, steps=steps, bbox=bbox, parameters=parameters, raw_root=raw_root)
    if result["status"] != "completed":
        output = {**result, "real_batch": False}
    else:
        raw_path = Path(result["target"])
        silver_root = silver_root or STORAGE / "silver" / "forecast" / "ecmwf"
        parsed = parse_ecmwf_grib(raw_path, run_time=result["run_time"], bbox=bbox, output_csv=silver_root / f"ecmwf_{run_date}_{cycle:02d}z_area_mean.csv")
        output = {**result, "parsed": parsed, "real_batch": parsed.get("status") == "completed"}
    if manifest_path:
        path = Path(manifest_path)
    else:
        path = STORAGE / "manifests" / f"ecmwf_open_data_{run_date}_{cycle:02d}z.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    output["manifest_path"] = str(path)
    return output


__all__ = ["DEFAULT_BBOX", "DEFAULT_PARAMS", "PARAMETER_MAP", "build_ecmwf_request", "parse_ecmwf_grib", "download_ecmwf_open_data", "run_ecmwf_open_data"]
