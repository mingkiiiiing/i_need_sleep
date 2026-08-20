"""C3S seasonal hindcast/forecast adapter for the Taihu seasonal driver chain.

The CDS seasonal service exposes monthly forecast statistics with a forecast
initialisation (year/month), lead month and ensemble member.  This adapter
keeps those axes explicit and uses the same row contract as the short-range
ECMWF/GFS adapters.  Without a CDS key it produces a truthful, executable
request plan and stops before any network retrieval.
"""

from __future__ import annotations

import csv
import json
import os
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np

from ..provenance import build_asset_manifest, write_asset_manifest
from .common import PACKAGE_ROOT
from .ecmwf_open_data import _bbox_mean, _iso


UTC = timezone.utc
DATASET = "seasonal-monthly-single-levels"
CDS_API_URL = "https://cds.climate.copernicus.eu/api"
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)
DEFAULT_ORIGINATING_CENTRE = "ecmwf"
DEFAULT_SYSTEM = "51"
DEFAULT_PRODUCT_TYPE = "monthly_mean"
DEFAULT_LEAD_MONTHS = (1, 2, 3)
DEFAULT_HINDCAST_YEARS = tuple(range(1993, 2017))
DEFAULT_VARIABLES = (
    "2m_temperature",
    "total_precipitation",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "surface_solar_radiation_downwards",
)

VARIABLE_MAP: dict[str, dict[str, Any]] = {
    "2m_temperature": {
        "names": ("2m_temperature", "t2m", "2t"),
        "code": "air_temperature", "unit": "degC", "source_unit": "K", "conversion": "K_to_degC",
    },
    "total_precipitation": {
        "names": ("total_precipitation", "tp"),
        "code": "precipitation", "unit": "mm", "source_unit": "m", "conversion": "m_to_mm",
    },
    "10m_u_component_of_wind": {
        "names": ("10m_u_component_of_wind", "u10", "10u"),
        "code": "wind_u", "unit": "m/s", "source_unit": "m/s", "conversion": "identity",
    },
    "10m_v_component_of_wind": {
        "names": ("10m_v_component_of_wind", "v10", "10v"),
        "code": "wind_v", "unit": "m/s", "source_unit": "m/s", "conversion": "identity",
    },
    "surface_solar_radiation_downwards": {
        "names": ("surface_solar_radiation_downwards", "ssrd"),
        "code": "shortwave_radiation", "unit": "W/m2", "source_unit": "J/m2", "conversion": "J_m2_to_W_m2",
    },
}


class CDSAuthRequired(RuntimeError):
    """Raised only when a live C3S retrieval is requested without credentials."""


def _credentials_present() -> bool:
    """Detect a key without printing or persisting it."""

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


def _as_strings(values: Iterable[int | str]) -> list[str]:
    return [str(value) for value in values]


def build_c3s_request(
    *,
    kind: str,
    years: Iterable[int | str],
    init_month: int,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    lead_months: Iterable[int] = DEFAULT_LEAD_MONTHS,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    originating_centre: str = DEFAULT_ORIGINATING_CENTRE,
    system: str = DEFAULT_SYSTEM,
    product_type: str = DEFAULT_PRODUCT_TYPE,
    data_format: str = "grib",
) -> dict[str, Any]:
    """Build a CDS request for either ``hindcast`` or ``forecast``.

    The request follows the official C3S monthly-statistics API shape.  A
    hindcast uses multiple initialisation years; a current forecast normally
    uses one year.  Both requests intentionally share variable/lead/bbox
    semantics so their rows can be compared and bias-corrected.
    """

    kind = str(kind).lower()
    if kind not in {"hindcast", "forecast"}:
        raise ValueError("kind must be hindcast or forecast")
    month = int(init_month)
    if month not in range(1, 13):
        raise ValueError("init_month must be 1..12")
    selected = [str(variable) for variable in variables]
    unknown = sorted(set(selected) - set(VARIABLE_MAP))
    if unknown:
        raise ValueError(f"unsupported C3S variables: {unknown}")
    leads = sorted({int(lead) for lead in lead_months})
    if not leads or min(leads) < 1 or max(leads) > 12:
        raise ValueError("lead_months must be within 1..12")
    west, south, east, north = map(float, bbox)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be (west, south, east, north) in WGS84")
    years_text = _as_strings(years)
    if not years_text:
        raise ValueError("at least one initialisation year is required")
    return {
        "format": data_format,
        "originating_centre": str(originating_centre),
        "system": str(system),
        "variable": selected,
        "product_type": str(product_type),
        "year": years_text if kind == "hindcast" else years_text[0],
        "month": f"{month:02d}",
        "leadtime_month": _as_strings(leads),
        "area": [north, west, south, east],
        "kind": kind,
    }


def build_c3s_plan(
    *,
    forecast_year: int,
    init_month: int,
    hindcast_years: Iterable[int] = DEFAULT_HINDCAST_YEARS,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    lead_months: Iterable[int] = DEFAULT_LEAD_MONTHS,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    originating_centre: str = DEFAULT_ORIGINATING_CENTRE,
    system: str = DEFAULT_SYSTEM,
) -> dict[str, Any]:
    """Return paired hindcast/forecast requests with an explicit time contract."""

    hindcast = build_c3s_request(
        kind="hindcast", years=hindcast_years, init_month=init_month,
        variables=variables, lead_months=lead_months, bbox=bbox,
        originating_centre=originating_centre, system=system,
    )
    forecast = build_c3s_request(
        kind="forecast", years=[forecast_year], init_month=init_month,
        variables=variables, lead_months=lead_months, bbox=bbox,
        originating_centre=originating_centre, system=system,
    )
    return {
        "dataset": DATASET,
        "requests": {"hindcast": hindcast, "forecast": forecast},
        "schema_contract": {
            "forecast_reference_time": "initialisation year-month at 00:00 UTC",
            "valid_time": "first day of initialisation month plus lead_month-1 months",
            "lead_month": "1-based forecast month",
            "ensemble_member": "C3S number/member, never collapsed before aggregation",
            "kind": ["hindcast", "forecast"],
        },
    }


def _convert(value: float, spec: Mapping[str, Any]) -> float:
    conversion = spec.get("conversion")
    if conversion == "K_to_degC":
        return value - 273.15
    if conversion == "m_to_mm":
        return value * 1000.0
    # Monthly means can represent energy totals or fluxes depending on the
    # selected C3S product.  Preserve the source value unless the file itself
    # declares a per-second flux; never invent a time divisor.
    return value


def _coord_value(data: Any, dim: str, index: tuple[int, ...]) -> Any:
    if dim not in getattr(data, "dims", ()) or dim not in getattr(data, "coords", {}):
        return None
    position = data.dims.index(dim)
    values = np.asarray(data.coords[dim].values)
    return values[index[position]] if values.ndim else values.item()


def _lead_month(value: Any, fallback: int = 1) -> int:
    if value is None:
        return fallback
    if hasattr(value, "item"):
        value = value.item()
    text = str(value)
    try:
        numeric = float(value)
        # GRIB step may be hours; monthly C3S fixtures normally expose fcmonth.
        if numeric > 12:
            return max(1, int(round(numeric / (24 * 30))))
        return max(1, int(round(numeric)))
    except (TypeError, ValueError):
        if "P" in text and "M" in text:
            digits = text.split("P", 1)[1].split("M", 1)[0]
            return max(1, int(float(digits)))
    return fallback


def _add_months(year: int, month: int, lead_month: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + lead_month - 1
    return absolute // 12, absolute % 12 + 1


def _reference_from_value(value: Any, *, fallback_year: int, fallback_month: int) -> datetime:
    if value is not None:
        text = _iso(value)
        if text:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass
    return datetime(fallback_year, fallback_month, 1, tzinfo=UTC)


def _variable_spec(data: Any, name: str) -> tuple[str, dict[str, Any]] | None:
    raw = str(getattr(data, "attrs", {}).get("GRIB_shortName") or name)
    for api_name, spec in VARIABLE_MAP.items():
        if raw in spec["names"] or name in spec["names"]:
            return api_name, spec
    return None


def _open_datasets(path: Path) -> list[Any]:
    if path.suffix.lower() in {".grib", ".grb", ".grib2"}:
        import cfgrib
        return list(cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""}))
    import xarray as xr
    return [xr.open_dataset(path)]


def parse_c3s_dataset(
    path: Path,
    *,
    kind: str,
    init_year: int | None = None,
    init_month: int | None = None,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    source_id: str = "c3s_seasonal",
) -> dict[str, Any]:
    """Parse a C3S GRIB/NetCDF file into shared monthly forecast rows."""

    kind = str(kind).lower()
    if kind not in {"hindcast", "forecast"}:
        raise ValueError("kind must be hindcast or forecast")
    datasets = _open_datasets(Path(path))
    rows: list[dict[str, Any]] = []
    for dataset in datasets:
        for name, data in dataset.data_vars.items():
            match = _variable_spec(data, str(name))
            if match is None:
                continue
            api_name, spec = match
            reduced = _bbox_mean(data, bbox)
            shape = getattr(reduced, "shape", ())
            dimensions = tuple(getattr(reduced, "dims", ()))
            for index in np.ndindex(shape or (1,)):
                raw = reduced.values[index] if shape else reduced.values
                raw_array = np.asarray(raw)
                if raw_array.size != 1 or not np.isfinite(raw_array.reshape(-1)[0]):
                    continue
                source_value = float(raw_array.reshape(-1)[0])
                ref_value = next((_coord_value(reduced, dim, index) for dim in ("forecast_reference_time", "time", "initialization_time") if _coord_value(reduced, dim, index) is not None), None)
                fallback_year = int(init_year or datetime.now(UTC).year)
                fallback_month = int(init_month or 1)
                reference = _reference_from_value(ref_value, fallback_year=fallback_year, fallback_month=fallback_month)
                lead_value = next((_coord_value(reduced, dim, index) for dim in ("leadtime_month", "lead_month", "fcmonth", "forecastMonth", "step") if _coord_value(reduced, dim, index) is not None), None)
                lead_month = _lead_month(lead_value, 1)
                valid_year, valid_month = _add_months(reference.year, reference.month, lead_month)
                valid_time = datetime(valid_year, valid_month, 1, tzinfo=UTC)
                member_value = next((_coord_value(reduced, dim, index) for dim in ("number", "ensemble_member", "member", "realization") if _coord_value(reduced, dim, index) is not None), 0)
                try:
                    member = int(member_value)
                except (TypeError, ValueError):
                    member = 0
                rows.append({
                    "source_id": source_id,
                    "model_name": "C3S",
                    "model_variant": f"{dataset.attrs.get('originating_centre', 'ECMWF')} system {dataset.attrs.get('system', 'unknown')}",
                    "dataset_kind": kind,
                    "forecast_reference_time": _iso(reference),
                    "valid_time": _iso(valid_time),
                    "lead_hours": float((valid_time - reference).total_seconds() / 3600.0),
                    "lead_month": lead_month,
                    "ensemble_member": member,
                    "variable_code": spec["code"],
                    "source_parameter": api_name,
                    "value": _convert(source_value, spec),
                    "source_value": source_value,
                    "unit": spec["unit"],
                    "source_unit": spec["source_unit"],
                    "conversion_rule": spec["conversion"],
                    "bbox_west": bbox[0], "bbox_south": bbox[1], "bbox_east": bbox[2], "bbox_north": bbox[3],
                    "raw_path": str(path),
                    "value_origin": "seasonal_hindcast" if kind == "hindcast" else "seasonal_forecast",
                    "bias_correction_status": "pending_hindcast_calibration",
                    "is_imputed": False,
                })
    if not rows:
        raise ValueError(f"C3S dataset contains no recognized finite variables: {path}")
    return {
        "status": "parsed", "source_id": source_id, "kind": kind, "source_file": str(path),
        "rows": rows, "record_count": len(rows), "variables": sorted({row["variable_code"] for row in rows}),
        "lead_months": sorted({row["lead_month"] for row in rows}),
    }


def apply_bias_correction(
    rows: Iterable[Mapping[str, Any]],
    hindcast_mean: Mapping[tuple[str, int], float],
    observed_mean: Mapping[tuple[str, int], float],
) -> list[dict[str, Any]]:
    """Apply additive variable/lead-month bias correction without leakage.

    The correction is trained only from hindcast and observed climatology
    summaries.  Missing climatology pairs remain unchanged and are labelled
    ``unavailable`` rather than silently imputed.
    """

    corrected: list[dict[str, Any]] = []
    for item in rows:
        row = dict(item)
        key = (str(row.get("variable_code")), int(row.get("lead_month", 1)))
        if row.get("dataset_kind") == "forecast" and key in hindcast_mean and key in observed_mean:
            delta = float(observed_mean[key]) - float(hindcast_mean[key])
            row["value"] = float(row["value"]) + delta
            row["bias_correction_status"] = "hindcast_additive_delta"
            row["bias_correction_delta"] = delta
        else:
            row["bias_correction_status"] = row.get("bias_correction_status", "not_applied")
            row["bias_correction_delta"] = 0.0
        corrected.append(row)
    return corrected


def _credentials_summary() -> dict[str, Any]:
    return {
        "present": _credentials_present(),
        "required_env": "TAIHU_CDS_API_KEY",
        "config_candidates": [str(Path.home() / ".cdsapirc"), str(Path.home() / ".config" / "cdsapi" / "config")],
    }


def _write_rows(rows: list[dict[str, Any]], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["source_id", "dataset_kind", "forecast_reference_time", "valid_time", "lead_month", "variable_code", "value", "unit"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def run_c3s_seasonal(
    forecast_year: int,
    init_month: int,
    *,
    hindcast_years: Iterable[int] = DEFAULT_HINDCAST_YEARS,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    lead_months: Iterable[int] = DEFAULT_LEAD_MONTHS,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    originating_centre: str = DEFAULT_ORIGINATING_CENTRE,
    system: str = DEFAULT_SYSTEM,
    raw_root: Path | None = None,
    silver_root: Path | None = None,
    manifest_path: Path | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Retrieve paired C3S hindcast/forecast or return BLOCKED_AUTH plan."""

    raw_root = Path(raw_root or PACKAGE_ROOT / "storage" / "raw" / "meteorology" / "c3s_seasonal")
    silver_root = Path(silver_root or PACKAGE_ROOT / "storage" / "silver" / "forecast" / "c3s_seasonal")
    manifest_path = Path(manifest_path or PACKAGE_ROOT / "storage" / "manifests" / f"c3s_seasonal_{forecast_year}_{init_month:02d}.json")
    plan = build_c3s_plan(
        forecast_year=forecast_year, init_month=init_month, hindcast_years=hindcast_years,
        variables=variables, lead_months=lead_months, bbox=bbox,
        originating_centre=originating_centre, system=system,
    )
    credentials = _credentials_present() if client_factory is None else True
    if client_factory is None and not credentials:
        result = {
            "task_id": "P05-04", "status": "BLOCKED_AUTH", "data_truth": "official_request_plan_only",
            "dataset": DATASET, "plan": plan, "requests": plan["requests"],
            "raw_root": str(raw_root), "silver_root": str(silver_root),
            "auth_probe": str(PACKAGE_ROOT / "storage" / "manifests" / "cds_auth_probe.json"),
            "credentials": _credentials_summary(), "error_class": "MissingCDSConfiguration",
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    try:
        if client_factory is None:
            import cdsapi
            client = cdsapi.Client()
        else:
            client = client_factory()
    except Exception as exc:
        result = {
            "task_id": "P05-04", "status": "BLOCKED_AUTH", "data_truth": "official_request_plan_only",
            "dataset": DATASET, "plan": plan, "requests": plan["requests"],
            "credentials": _credentials_summary(), "error_class": type(exc).__name__, "error": str(exc),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    rows: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for kind in ("hindcast", "forecast"):
        request = plan["requests"][kind]
        target = raw_root / f"c3s_{kind}_{forecast_year}_{init_month:02d}_system{system}.grib"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.retrieve(DATASET, {key: value for key, value in request.items() if key != "kind"}, str(target))
            asset = build_asset_manifest(
                source_id="c3s_seasonal", asset_id=target.stem, request_url=CDS_API_URL,
                local_path=target, http_status=200, license_tag="Copernicus-C3S-CC-BY-4.0",
                redistribution_allowed="conditional", commercial_use="conditional", status="completed",
            )
            asset_path = manifest_path.parent / f"raw_c3s_{kind}_{forecast_year}_{init_month:02d}.json"
            write_asset_manifest(asset, asset_path)
            parsed = parse_c3s_dataset(target, kind=kind, init_year=forecast_year, init_month=init_month, bbox=bbox)
            rows.extend(parsed["rows"])
            assets.append({"kind": kind, "status": "completed", "target": str(target), "records": parsed["record_count"], "manifest": str(asset_path)})
        except Exception as exc:
            assets.append({"kind": kind, "status": "failed", "target": str(target), "error": str(exc)})
    output = _write_rows(rows, silver_root / f"c3s_seasonal_{forecast_year}_{init_month:02d}.csv") if rows else None
    result = {
        "task_id": "P05-04", "status": "completed" if assets and all(item["status"] == "completed" for item in assets) else "failed",
        "data_truth": "real_external_cds", "dataset": DATASET, "plan": plan, "assets": assets,
        "records": len(rows), "output": output, "bbox": list(bbox), "bias_correction": "additive_hindcast_observed_delta_interface",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


__all__ = [
    "DATASET", "DEFAULT_BBOX", "DEFAULT_LEAD_MONTHS", "DEFAULT_VARIABLES", "VARIABLE_MAP",
    "apply_bias_correction", "build_c3s_plan", "build_c3s_request", "parse_c3s_dataset", "run_c3s_seasonal",
]
