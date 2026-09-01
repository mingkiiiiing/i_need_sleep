from __future__ import annotations

"""Monthly full-lake Sentinel-2 L2A mosaics through the official CDSE Process API."""

import csv
import hashlib
import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import requests

from .clms_lwq_byoc import PROCESS_API_URL, TOKEN_ENDPOINT
from .sentinel2_monthly import DEFAULT_BOUNDARY, PACKAGE_ROOT, TARGET_CRS, _target_grid, build_monthly_plan

STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
DEFAULT_OUTPUT = STORAGE / "rasters" / "sentinel2_monthly_30m_cdse"
DEFAULT_MANIFEST = STORAGE / "manifests" / "sentinel2_monthly_2022_2026_cdse.json"
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "SCL", "dataMask"], units: "DN"}],
    output: {bands: 11, sampleType: "UINT16"}
  };
}
function evaluatePixel(s) { return [s.B02, s.B03, s.B04, s.B05, s.B06, s.B07, s.B08, s.B8A, s.B11, s.SCL, s.dataMask]; }
"""
MONTHLY_COMPOSITE_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "SCL", "dataMask"], units: "DN"}],
    output: {bands: 11, sampleType: "UINT16"},
    mosaicking: "ORBIT"
  };
}
function clear(s) { return s.dataMask && ![0, 1, 3, 7, 8, 9, 10, 11].includes(s.SCL); }
function values(s) { return [s.B02, s.B03, s.B04, s.B05, s.B06, s.B07, s.B08, s.B8A, s.B11, s.SCL, s.dataMask]; }
function evaluatePixel(samples) {
  for (let i = 0; i < samples.length; i++) if (clear(samples[i])) return values(samples[i]);
  for (let i = 0; i < samples.length; i++) if (samples[i].dataMask) return values(samples[i]);
  return [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
}
"""
BAND_ORDER = ("blue", "green", "red", "rededge1", "rededge2", "rededge3", "nir", "nirnarrow", "swir16", "scl", "dataMask")
BAND_FILE_NAMES = {
    "blue": "B02", "green": "B03", "red": "B04", "rededge1": "B05", "rededge2": "B06",
    "rededge3": "B07", "nir": "B08", "nirnarrow": "B8A", "swir16": "B11", "scl": "SCL",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _token() -> str:
    direct = os.getenv("TAIHU_CDSE_ACCESS_TOKEN") or os.getenv("TAIHU_CDSE_TOKEN")
    if direct:
        return direct
    client_id, secret = os.getenv("TAIHU_CDSE_CLIENT_ID"), os.getenv("TAIHU_CDSE_CLIENT_SECRET")
    if not (client_id and secret):
        raise RuntimeError("CDSE OAuth client is not configured")
    response = requests.post(
        TOKEN_ENDPOINT,
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def build_request(selected_date: str, bounds: tuple[float, float, float, float], width: int, height: int, end_date: str | None = None, pixel_composite: bool = False) -> dict[str, Any]:
    end_date = end_date or selected_date
    return {
        "input": {
            "bounds": {"bbox": list(bounds), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/32651"}},
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": f"{selected_date}T00:00:00Z", "to": f"{end_date}T23:59:59Z"},
                    "mosaickingOrder": "leastCC",
                },
                "processing": {"upsampling": "BILINEAR", "downsampling": "BILINEAR", "harmonizeValues": True},
            }],
        },
        "output": {"width": width, "height": height, "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": MONTHLY_COMPOSITE_EVALSCRIPT if pixel_composite else EVALSCRIPT,
    }


def _post_process(body: dict[str, Any], token: str) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.post(PROCESS_API_URL, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=300)
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            last_error = requests.HTTPError(f"transient HTTP {response.status_code}")
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
            last_error = exc
        time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def _plan_from_manifest(manifest_path: Path, start: date, end: date) -> list[dict[str, Any]] | None:
    """Reuse the catalogue selection of a previous run instead of querying Earth Search.

    The Earth Search STAC API is only needed to pick the monthly scene date; the
    previous manifest already recorded that decision, so re-runs (e.g. after a
    band-set change) stay offline and reproducible.
    """

    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    months = payload.get("months") if isinstance(payload, dict) else None
    if not months:
        return None
    plan: list[dict[str, Any]] = []
    for item in months:
        month = str(item.get("month"))
        if not (start.isoformat()[:7] <= month <= end.isoformat()[:7]):
            continue
        selected = item.get("selected_date")
        range_value = item.get("range") or (item.get("acquisition_window") or [selected, selected])
        if not selected or not range_value:
            return None
        plan.append({
            "month": month,
            "range": list(range_value),
            "cloud_threshold": item.get("cloud_threshold", 30.0),
            "candidate_scenes": item.get("candidate_scenes", 0),
            "selected_date": selected,
            "selected": [],
        })
    return plan if plan else None


def run_cdse_monthly(
    start: date = date(2022, 1, 1),
    end: date = date(2026, 8, 23),
    *,
    output_root: Path = DEFAULT_OUTPUT,
    manifest_path: Path = DEFAULT_MANIFEST,
    boundary_path: Path = DEFAULT_BOUNDARY,
    monthly_composite: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    import rasterio
    from rasterio.io import MemoryFile

    load_env_file(PACKAGE_ROOT / ".env.cdse")
    affine, width, height, lake_mask, bounds = _target_grid(Path(boundary_path), resolution=30.0)
    if width > 2500 or height > 2500:
        raise ValueError(f"CDSE Process API output exceeds 2500 px: {width}x{height}")
    plan = _plan_from_manifest(manifest_path, start, end) or build_monthly_plan(start, end)
    output_root, manifest_path = Path(output_root), Path(manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    token = _token()
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(plan, start=1):
        scenes = item.pop("selected")
        month, selected_date = item["month"], item.get("selected_date")
        print(f"[{index}/{len(plan)}] CDSE {month} {selected_date}", flush=True)
        row: dict[str, Any] = {**item, "scene_ids": [scene.get("id") for scene in scenes]}
        if not selected_date:
            row["status"] = "missing_catalogue_scene"
            rows.append(row)
            continue
        month_root = output_root / month
        raw_path = month_root / f"taihu_s2_l2a_{month}_multiband_30m.tif"
        try:
            month_root.mkdir(parents=True, exist_ok=True)
            if force or not raw_path.exists() or raw_path.stat().st_size == 0:
                request_start, request_end = item["range"] if monthly_composite else (selected_date, selected_date)
                body = build_request(request_start, bounds, width, height, end_date=request_end, pixel_composite=monthly_composite)
                response = _post_process(body, token)
                if response.status_code == 401:
                    token = _token()
                    response = _post_process(body, token)
                response.raise_for_status()
                raw_path.write_bytes(response.content)
            with rasterio.open(raw_path) as source:
                data = source.read()
                source_profile = source.profile.copy()
            if data.shape != (11, height, width):
                raise ValueError(f"unexpected Process API raster shape {data.shape}")
            combined_mask = lake_mask & (data[10] > 0)
            outputs: dict[str, Any] = {}
            for band_index, asset in enumerate(BAND_ORDER[:9]):
                output = month_root / f"taihu_s2_l2a_{month}_{BAND_FILE_NAMES[asset]}_30m.tif"
                values = data[band_index].copy()
                values[~combined_mask] = 0
                profile = source_profile.copy()
                profile.update(count=1, dtype="uint16", nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512)
                with rasterio.open(output, "w", **profile) as target:
                    target.write(values.astype("uint16"), 1)
                outputs[asset] = {"path": str(output), "bytes": output.stat().st_size, "sha256": _sha256(output)}
            scl = data[9]
            cloudy = np.isin(scl, [0, 1, 3, 7, 8, 9, 10, 11])
            row.update(
                status="completed",
                raw_path=str(raw_path),
                raw_bytes=raw_path.stat().st_size,
                raw_sha256=_sha256(raw_path),
                outputs=outputs,
                data_mask_fraction=float(combined_mask.sum() / lake_mask.sum()),
                clear_lake_fraction=float((combined_mask & ~cloudy).sum() / lake_mask.sum()),
                acquisition_window=item["range"] if monthly_composite else [selected_date, selected_date],
                composite_mode="monthly_least_cloud" if monthly_composite else "exact_day",
            )
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"status": "running", "months": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    inventory = output_root / "sentinel2_monthly_inventory.csv"
    with inventory.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["month", "selected_date", "status", "candidate_scenes", "cloud_threshold", "data_mask_fraction", "clear_lake_fraction", "error"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in writer.fieldnames})
    manifest = {
        "run_id": f"sentinel2_monthly_cdse_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "completed" if all(row["status"] == "completed" for row in rows) else "completed_with_gaps",
        "source_id": "copernicus_sentinel2_l2a_cdse_process_api",
        "period": [start.isoformat(), end.isoformat()],
        "process_api": PROCESS_API_URL,
        "oauth_secret_recorded": False,
        "composite_mode": "monthly_least_cloud" if monthly_composite else "exact_day",
        "bands": list(BAND_ORDER),
        "band_file_names": BAND_FILE_NAMES,
        "grid": {"crs": TARGET_CRS, "resolution_m": 30.0, "width": width, "height": height, "bounds": bounds},
        "month_count": len(rows),
        "completed_months": sum(row["status"] == "completed" for row in rows),
        "failed_months": [row["month"] for row in rows if row["status"] != "completed"],
        "inventory_csv": str(inventory),
        "months": rows,
        "license_note": "Contains modified Copernicus Sentinel data.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


__all__ = ["build_request", "load_env_file", "run_cdse_monthly"]
