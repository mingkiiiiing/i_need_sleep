"""Year-chunked NASA POWER history ingestion for the Taihu training window."""

from __future__ import annotations

import calendar
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from ..normalize import normalize_nasa_payload
from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest
from .common import PACKAGE_ROOT, request_json, utc_now


POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_PARAMETERS = ("T2M", "WS10M", "WD10M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN")
EXPECTED_UNITS = {
    "T2M": "C",
    "WS10M": "m/s",
    "WD10M": "Degrees",
    "PRECTOTCORR": "mm/day",
    "ALLSKY_SFC_SW_DWN": "Wh/m^2",
}


def _url(start: str, end: str, longitude: float, latitude: float) -> str:
    params = {
        "parameters": ",".join(NASA_PARAMETERS),
        "community": "RE",
        "longitude": f"{longitude:.6f}",
        "latitude": f"{latitude:.6f}",
        "start": start.replace("-", ""),
        "end": end.replace("-", ""),
        "time-standard": "UTC",
        "format": "JSON",
    }
    return POWER_URL + "?" + urlencode(params)


def _year_windows(start_year: int, end_year: int) -> list[tuple[int, str, str, int]]:
    if start_year > end_year:
        raise ValueError("start_year must be <= end_year")
    return [(year, f"{year}-01-01", f"{year}-12-31", (366 if calendar.isleap(year) else 365) * 24) for year in range(start_year, end_year + 1)]


def _expected_keys(year: int) -> list[str]:
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    hours = (366 if calendar.isleap(year) else 365) * 24
    return [start.replace(hour=0) + timedelta(hours=index) for index in range(hours)]


def _expected_compact_keys(year: int) -> list[str]:
    return [moment.strftime("%Y%m%d%H") for moment in _expected_keys(year)]


def _write_envelope(path: Path, url: str, status: int, content_type: str, payload: Any, retrieved_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "request_url": url,
        "retrieved_at": retrieved_at,
        "http_status": status,
        "content_type": content_type,
        "payload": payload,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_year(
    year: int,
    start: str,
    end: str,
    expected_hours: int,
    *,
    longitude: float,
    latitude: float,
    raw_root: Path,
    manifest_dir: Path,
    requester: Callable[[str], tuple[int, str, Any]],
) -> dict[str, Any]:
    url = _url(start, end, longitude, latitude)
    output = raw_root / f"history_{year}.json"
    asset_manifest_path = manifest_dir / f"raw_nasa_power_hourly_history_{year}.json"
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if existing.get("request_url") == url and int(existing.get("http_status", 0)) == 200:
            payload = existing.get("payload", {})
            reused = True
            status = 200
            content_type = str(existing.get("content_type") or "application/json")
            retrieved_at = str(existing.get("retrieved_at") or utc_now())
        else:
            reused = False
            status, content_type, payload = requester(url)
            retrieved_at = utc_now()
            _write_envelope(output, url, status, content_type, payload, retrieved_at)
    else:
        reused = False
        status, content_type, payload = requester(url)
        retrieved_at = utc_now()
        _write_envelope(output, url, status, content_type, payload, retrieved_at)

    asset = build_asset_manifest(
        source_id="nasa_power_hourly",
        asset_id=f"history_{year}",
        request_url=url,
        local_path=output,
        retrieved_at_utc=retrieved_at,
        http_status=status,
        response_headers={"Content-Type": content_type},
        license_tag="NASA-data-policy",
        redistribution_allowed="conditional",
        commercial_use="conditional",
        status="skipped_existing" if reused else "completed" if status == 200 else "failed",
    )
    write_asset_manifest(asset, asset_manifest_path)

    parameters = payload.get("properties", {}).get("parameter", {}) if isinstance(payload, dict) else {}
    header = payload.get("header", {}) if isinstance(payload, dict) else {}
    timestamp_keys = sorted(parameters.get("T2M", {}).keys())
    expected_keys = _expected_compact_keys(year)
    continuity = timestamp_keys == expected_keys
    units = payload.get("parameters", {}) if isinstance(payload, dict) else {}
    unit_values = {key: str((units.get(key) or {}).get("units") or "") for key in NASA_PARAMETERS}
    missing_by_parameter = {
        key: sum(1 for value in (parameters.get(key) or {}).values() if value in (None, -999, -999.0))
        for key in NASA_PARAMETERS
    }
    return {
        "year": year,
        "request_url": url,
        "raw_path": str(output),
        "asset_manifest": str(asset_manifest_path),
        "status": "reused" if reused else "downloaded" if status == 200 else "failed",
        "http_status": status,
        "records": len(timestamp_keys),
        "expected_records": expected_hours,
        "all_parameters_present": all(key in parameters for key in NASA_PARAMETERS),
        "timestamp_continuous": continuity,
        "time_standard": header.get("time_standard"),
        "units": unit_values,
        "units_match_expected": unit_values == EXPECTED_UNITS,
        "missing_by_parameter": missing_by_parameter,
    }


def _write_silver(raw_files: list[Path], output_csv: Path) -> dict[str, Any]:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "source_id", "source_file", "source_row", "station_id", "scene_id", "observed_at",
        "observed_at_utc", "observed_at_local", "time_status", "source_timezone", "longitude",
        "latitude", "variable_code", "source_parameter", "observed_value", "clean_value", "unit",
        "source_unit", "value_origin", "conversion_rule", "is_imputed", "imputation_method",
        "imputation_confidence", "quality_flags",
    ]
    row_count = 0
    time_status_counts: dict[str, int] = {}
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for path in raw_files:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            for row in normalize_nasa_payload(path, envelope):
                writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row.get(key), (list, dict)) else row.get(key) for key in fields})
                row_count += 1
                status = str(row.get("time_status") or "")
                time_status_counts[status] = time_status_counts.get(status, 0) + 1
    return {"output_csv": str(output_csv), "rows": row_count, "time_status_counts": time_status_counts}


def ingest_nasa_power_history(
    start_year: int = 2005,
    end_year: int = 2020,
    longitude: float = 120.30,
    latitude: float = 31.20,
    *,
    raw_root: Path | None = None,
    output_root: Path | None = None,
    manifest_path: Path | None = None,
    requester: Callable[[str], tuple[int, str, Any]] = request_json,
) -> dict[str, Any]:
    """Fetch one NASA POWER UTC JSON response per training year and build Silver CSV."""

    raw_root = Path(raw_root or PACKAGE_ROOT / "storage" / "raw" / "nasa_power_hourly")
    output_root = Path(output_root or PACKAGE_ROOT / "storage" / "silver" / "nasa_power")
    manifest_path = Path(manifest_path or PACKAGE_ROOT / "storage" / "manifests" / f"nasa_power_history_{start_year}_{end_year}.json")
    windows = _year_windows(int(start_year), int(end_year))
    years: list[dict[str, Any]] = []
    raw_files: list[Path] = []
    for year, start, end, expected_hours in windows:
        try:
            result = _fetch_year(
                year, start, end, expected_hours,
                longitude=longitude, latitude=latitude, raw_root=raw_root, manifest_dir=manifest_path.parent, requester=requester,
            )
        except Exception as exc:
            result = {"year": year, "status": "failed", "error": str(exc), "request_url": _url(start, end, longitude, latitude)}
        years.append(result)
        if result.get("status") != "failed":
            raw_files.append(Path(result["raw_path"]))
    silver = _write_silver(raw_files, output_root / f"nasa_power_hourly_{start_year}_{end_year}.csv") if raw_files else {"output_csv": None, "rows": 0, "time_status_counts": {}}
    successful = [item for item in years if item.get("status") != "failed"]
    checks = {
        "year_count": len(successful) == len(windows),
        "all_http_200": all(item.get("http_status") == 200 for item in successful),
        "all_parameters_present": all(item.get("all_parameters_present") for item in successful),
        "all_years_continuous": all(item.get("timestamp_continuous") for item in successful),
        "all_units_match_expected": all(item.get("units_match_expected") for item in successful),
        "all_time_standard_utc": all(item.get("time_standard") == "UTC" for item in successful),
        "silver_rows_expected": silver["rows"] == sum(item.get("records", 0) for item in successful) * len(NASA_PARAMETERS),
        "silver_timestamps_accepted": silver["time_status_counts"].get("accepted", 0) == silver["rows"],
    }
    result = {
        "task_id": "P04-03",
        "status": "completed" if all(checks.values()) else "failed",
        "data_truth": "real_external" if all(item.get("http_status") == 200 for item in successful) else "partial_real_external",
        "training_window": {
            "start_year": start_year,
            "end_year": end_year,
            "basis": "THQBCA water-quality and phytoplankton target coverage 2005-2020",
        },
        "coordinates": {"longitude": longitude, "latitude": latitude},
        "parameters": list(NASA_PARAMETERS),
        "years": years,
        "silver": silver,
        "checks": checks,
        "raw_root": str(raw_root),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
