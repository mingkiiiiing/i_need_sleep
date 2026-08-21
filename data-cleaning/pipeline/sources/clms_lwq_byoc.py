from __future__ import annotations

"""Bounded Sentinel Hub BYOC request for the CLMS Taihu LWQ product.

The adapter builds a reproducible Process API request for the frozen Taihu
boundary and selected CLMS catalogue interval.  Without a CDSE OAuth token it
stops before the POST and records BLOCKED_AUTH; it never fabricates a raster.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..provenance import build_asset_manifest, write_asset_manifest
from .common import PACKAGE_ROOT, sha256_file, utc_now


BYOC_COLLECTION_ID = "5c2c9b2c-2893-41d9-b2bc-fbd6e5b8b31d"
BYOC_DATA_TYPE = f"byoc-{BYOC_COLLECTION_ID}"
PROCESS_API_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
TOKEN_ENDPOINT = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
TARGET_BANDS = ("CHLAMEAN", "CHLAUNC", "FCBPROB", "FOBS", "LOBS", "NOBS", "QFLAG")
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 320
BOUNDARY_PATH = PACKAGE_ROOT / "storage" / "silver" / "geo" / "taihu_boundary.gpkg"
AUTH_PROBE_PATH = PACKAGE_ROOT / "storage" / "manifests" / "cdse_auth_probe.json"

EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["CHLAMEAN", "CHLAUNC", "FCBPROB", "FOBS", "LOBS", "NOBS", "QFLAG"]}],
    output: {bands: 7, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(sample) {
  return [sample.CHLAMEAN, sample.CHLAUNC, sample.FCBPROB, sample.FOBS, sample.LOBS, sample.NOBS, sample.QFLAG];
}
"""


def _iso_z(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_taihu_geometry(path: Path | str = BOUNDARY_PATH) -> dict[str, Any] | None:
    """Read the frozen WGS84 lake polygon when Fiona is available."""

    try:
        import fiona

        with fiona.open(Path(path), layer="taihu_boundary_wgs84") as layer:
            feature = next(iter(layer), None)
            return dict(feature["geometry"]) if feature else None
    except (ImportError, OSError, StopIteration, KeyError):
        return None


def build_clms_process_request(
    *,
    start: str | datetime,
    end: str | datetime,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    geometry: Mapping[str, Any] | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    evalscript: str = EVALSCRIPT,
) -> dict[str, Any]:
    """Build the bounded Process API JSON body without credentials."""

    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise ValueError("bbox must be west,south,east,north")
    if width < 1 or height < 1:
        raise ValueError("width and height must be positive")
    bounds: dict[str, Any] = {
        "bbox": [float(value) for value in bbox],
        "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
    }
    if geometry:
        bounds["geometry"] = dict(geometry)
    return {
        "input": {
            "bounds": bounds,
            "data": [
                {
                    "type": BYOC_DATA_TYPE,
                    "dataFilter": {"timeRange": {"from": _iso_z(start), "to": _iso_z(end)}},
                }
            ],
        },
        "output": {
            "width": int(width),
            "height": int(height),
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": evalscript,
    }


def _credentials() -> dict[str, bool]:
    return {
        "access_token": bool(os.getenv("TAIHU_CDSE_ACCESS_TOKEN") or os.getenv("TAIHU_CDSE_TOKEN")),
        "client_id": bool(os.getenv("TAIHU_CDSE_CLIENT_ID")),
        "client_secret": bool(os.getenv("TAIHU_CDSE_CLIENT_SECRET")),
    }


def _request_token(*, opener: Callable[..., Any] | None = None, timeout: int = 30) -> str | None:
    direct = os.getenv("TAIHU_CDSE_ACCESS_TOKEN") or os.getenv("TAIHU_CDSE_TOKEN")
    if direct:
        return direct
    if not (os.getenv("TAIHU_CDSE_CLIENT_ID") and os.getenv("TAIHU_CDSE_CLIENT_SECRET")):
        return None
    payload = urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["TAIHU_CDSE_CLIENT_ID"],
        "client_secret": os.environ["TAIHU_CDSE_CLIENT_SECRET"],
    }).encode("utf-8")
    request = Request(TOKEN_ENDPOINT, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with (urlopen if opener is None else opener)(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        token = body.get("access_token")
        return str(token) if token else None
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError):
        return None


def _write_output_manifest(path: Path, result: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def run_clms_lwq_byoc(
    *,
    selected_product: Path | str | Mapping[str, Any] | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    output_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Submit a bounded CLMS BYOC request when OAuth is available."""

    if selected_product is None:
        selected_product = PACKAGE_ROOT / "storage" / "staging" / "clms_lwq_catalog" / "lwq-nrt_global_300m_10daily_v2_cog_selected_latest.json"
    if isinstance(selected_product, Mapping):
        product = dict(selected_product)
        product_input = "mapping"
    else:
        product_path = Path(selected_product)
        product = json.loads(product_path.read_text(encoding="utf-8"))
        product_input = str(product_path)
    start = start or product.get("content_date_start") or product.get("nominal_date")
    end = end or product.get("content_date_end") or product.get("nominal_date")
    if not start or not end:
        raise ValueError("selected CLMS product lacks start/end date")
    geometry = load_taihu_geometry()
    request_body = build_clms_process_request(start=start, end=end, bbox=bbox, geometry=geometry, width=width, height=height)
    output = Path(output_path) if output_path else PACKAGE_ROOT / "storage" / "rasters" / "clms_lwq" / f"{product.get('name', 'taihu_lwq')}.tif"
    manifest = Path(manifest_path) if manifest_path else PACKAGE_ROOT / "storage" / "manifests" / "clms_lwq_byoc.json"
    credentials = _credentials()
    result: dict[str, Any] = {
        "task_id": "P06-06",
        "source_id": "clms_lwq_byoc_taihu",
        "status": "BLOCKED_AUTH",
        "retrieved_at_utc": utc_now(),
        "data_truth": "official_clms_catalogue_plus_process_request_plan",
        "selected_product_input": product_input,
        "selected_product": product,
        "collection_id": BYOC_COLLECTION_ID,
        "process_api_url": PROCESS_API_URL,
        "bbox": list(bbox),
        "geometry_included": geometry is not None,
        "request_body": request_body,
        "output_path": str(output),
        "credentials_present": credentials,
        "auth_probe": str(AUTH_PROBE_PATH) if AUTH_PROBE_PATH.exists() else None,
        "token_requested": False,
        "token_received": False,
        "checksum_sha256": None,
        "warnings": [],
        "manifest": str(manifest),
    }
    token = _request_token(opener=opener)
    result["token_requested"] = bool(credentials["client_id"] and credentials["client_secret"] and not credentials["access_token"])
    result["token_received"] = bool(token)
    if not token:
        result["next_action"] = "配置CDSE OAuth access token或client credentials后重跑；当前仅保存真实产品和请求计划"
        _write_output_manifest(manifest, result)
        return result

    request = Request(
        PROCESS_API_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "image/tiff"},
        method="POST",
    )
    try:
        with (urlopen if opener is None else opener)(request, timeout=180) as response:
            status_value = getattr(response, "status", None)
            if status_value is None:
                status_value = response.getcode()
            status = int(status_value)
            content_type = response.headers.get("Content-Type", "")
            payload = response.read()
        if status < 200 or status >= 300:
            result.update(status="BLOCKED_AUTH" if status in {401, 403} else "FAILED", http_status=status, error_class="ProcessAPIHTTPError")
        elif not payload:
            result.update(status="FAILED", http_status=status, error_class="EmptyRasterResponse")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(payload)
            asset_manifest = build_asset_manifest(
                source_id="clms_lwq_byoc_taihu",
                asset_id=product.get("name", "taihu_lwq"),
                request_url=PROCESS_API_URL,
                local_path=output,
                retrieved_at_utc=utc_now(),
                http_status=status,
                response_headers={"Content-Type": content_type},
                license_tag="COPERNICUS_CLMS_TERMS",
                redistribution_allowed="conditional",
                commercial_use="conditional",
                status="completed",
            )
            asset_manifest_path = manifest.with_name(manifest.stem + "_asset.json")
            write_asset_manifest(asset_manifest, asset_manifest_path)
            result.update(status="completed", data_truth="real_clms_taihu_raster", http_status=status, content_type=content_type, checksum_sha256=sha256_file(output), asset_manifest=str(asset_manifest_path), next_action="进入P06-08跨源一致性")
    except HTTPError as exc:
        result.update(status="BLOCKED_AUTH" if exc.code in {401, 403} else "FAILED", http_status=int(exc.code), error_class="ProcessAPIHTTPError")
    except (URLError, TimeoutError) as exc:
        result.update(status="FAILED", error_class=type(exc).__name__)
    _write_output_manifest(manifest, result)
    return result


__all__ = [
    "AUTH_PROBE_PATH",
    "BYOC_COLLECTION_ID",
    "BYOC_DATA_TYPE",
    "DEFAULT_BBOX",
    "EVALSCRIPT",
    "PROCESS_API_URL",
    "TARGET_BANDS",
    "build_clms_process_request",
    "load_taihu_geometry",
    "run_clms_lwq_byoc",
]
