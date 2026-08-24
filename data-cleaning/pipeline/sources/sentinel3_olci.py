from __future__ import annotations

"""Sentinel-3 OLCI L2 water-quality adapter for the Taihu workflow.

The adapter targets the official Copernicus Data Space Ecosystem Sentinel Hub
Process API collection ``sentinel-3-olci-l2``.  It deliberately separates an
auditable request plan from an authenticated raster download: when CDSE OAuth
credentials are absent, only the request/manifest is written and the status is
``BLOCKED_AUTH``.  No water-quality value or quality flag is fabricated.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..provenance import build_asset_manifest, write_asset_manifest
from .common import PACKAGE_ROOT, sha256_file, utc_now


PROCESS_API_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
TOKEN_ENDPOINT = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
DATA_TYPE = "sentinel-3-olci-l2"
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 320
DEFAULT_MAX_CLOUD_COVERAGE = 80.0
DEFAULT_MOSAICKING_ORDER = "mostRecent"
DEFAULT_UPSAMPLING = "BILINEAR"
AUTH_PROBE_PATH = PACKAGE_ROOT / "storage" / "manifests" / "cdse_auth_probe.json"

# The list follows the official Sentinel-3 OLCI L2 WATER band catalogue.  The
# dataMask band is retained as the machine-readable validity/data-presence
# indicator.  B13/B14/B15/B19/B20 are intentionally excluded because CDSE
# documents them as unavailable for this collection.
TARGET_BANDS = (
    "CHL_OC4ME",
    "CHL_NN",
    "TSM_NN",
    "KD490_M07",
    "PAR",
    "A865",
    "T865",
    "ADG443_NN",
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "B06",
    "B07",
    "B08",
    "B09",
    "B10",
    "B11",
    "B12",
    "B16",
    "B17",
    "B18",
    "B21",
    "dataMask",
)

EVALSCRIPT = f"""//VERSION=3
function setup() {{
  return {{
    input: [{{bands: {json.dumps(list(TARGET_BANDS))}}}],
    output: {{bands: {len(TARGET_BANDS)}, sampleType: "FLOAT32"}}
  }};
}}
function evaluatePixel(sample) {{
  return [{', '.join(f'sample.{band}' for band in TARGET_BANDS)}];
}}
"""


def _iso_z(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_sentinel3_process_request(
    *,
    start: str | datetime,
    end: str | datetime,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    max_cloud_coverage: float = DEFAULT_MAX_CLOUD_COVERAGE,
    mosaicking_order: str = DEFAULT_MOSAICKING_ORDER,
    upsampling: str = DEFAULT_UPSAMPLING,
    evalscript: str = EVALSCRIPT,
) -> dict[str, Any]:
    """Build a CDSE Process API body without contacting the service."""

    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise ValueError("bbox must be west,south,east,north")
    if width < 1 or height < 1:
        raise ValueError("width and height must be positive")
    if not 0 <= float(max_cloud_coverage) <= 100:
        raise ValueError("max_cloud_coverage must be between 0 and 100")
    if mosaicking_order not in {"mostRecent", "leastRecent", "leastCC"}:
        raise ValueError("mosaicking_order must be mostRecent, leastRecent or leastCC")
    if upsampling not in {"NEAREST", "BILINEAR", "BICUBIC"}:
        raise ValueError("upsampling must be NEAREST, BILINEAR or BICUBIC")
    return {
        "input": {
            "bounds": {
                "bbox": [float(value) for value in bbox],
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [
                {
                    "type": DATA_TYPE,
                    "dataFilter": {
                        "timeRange": {"from": _iso_z(start), "to": _iso_z(end)},
                        "mosaickingOrder": mosaicking_order,
                        "maxCloudCoverage": float(max_cloud_coverage),
                    },
                    "processing": {"upsampling": upsampling},
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
    client_id = os.getenv("TAIHU_CDSE_CLIENT_ID")
    client_secret = os.getenv("TAIHU_CDSE_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None
    payload = urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    request = Request(TOKEN_ENDPOINT, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with (urlopen if opener is None else opener)(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        token = body.get("access_token")
        return str(token) if token else None
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_manifest(path: Path, result: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def run_sentinel3_olci(
    *,
    start: str | datetime,
    end: str | datetime,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    output_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    max_cloud_coverage: float = DEFAULT_MAX_CLOUD_COVERAGE,
    mosaicking_order: str = DEFAULT_MOSAICKING_ORDER,
    upsampling: str = DEFAULT_UPSAMPLING,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Plan and, when authorized, execute one bounded OLCI Process API call."""

    request_body = build_sentinel3_process_request(
        start=start,
        end=end,
        bbox=bbox,
        width=width,
        height=height,
        max_cloud_coverage=max_cloud_coverage,
        mosaicking_order=mosaicking_order,
        upsampling=upsampling,
    )
    output = Path(output_path) if output_path else PACKAGE_ROOT / "storage" / "rasters" / "sentinel3_olci" / "taihu_olci.tif"
    manifest = Path(manifest_path) if manifest_path else PACKAGE_ROOT / "storage" / "manifests" / "sentinel3_olci.json"
    credentials = _credentials()
    result: dict[str, Any] = {
        "task_id": "P06-07",
        "source_id": "cdse_sentinel3_olci_l2",
        "status": "BLOCKED_AUTH",
        "retrieved_at_utc": utc_now(),
        "data_truth": "official_process_request_plan",
        "data_type": DATA_TYPE,
        "process_api_url": PROCESS_API_URL,
        "bbox": list(bbox),
        "request_body": request_body,
        "target_bands": list(TARGET_BANDS),
        "quality_indicator": "dataMask",
        "credentials_present": credentials,
        "auth_probe": str(AUTH_PROBE_PATH) if AUTH_PROBE_PATH.exists() else None,
        "token_requested": False,
        "token_received": False,
        "raster_written": False,
        "output_path": str(output),
        "checksum_sha256": None,
        "warnings": [],
        "manifest": str(manifest),
    }
    token = _request_token(opener=opener)
    result["token_requested"] = bool(credentials["client_id"] and credentials["client_secret"] and not credentials["access_token"])
    result["token_received"] = bool(token)
    if not token:
        result["next_action"] = "配置CDSE OAuth access token或client credentials后重跑；当前仅保存官方请求计划"
        _write_manifest(manifest, result)
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
            status = int(status_value if status_value is not None else response.getcode())
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
                source_id="cdse_sentinel3_olci_l2",
                asset_id=f"taihu_olci_{_iso_z(start).replace(':', '').replace('-', '')}_{_iso_z(end).replace(':', '').replace('-', '')}",
                request_url=PROCESS_API_URL,
                local_path=output,
                retrieved_at_utc=utc_now(),
                http_status=status,
                response_headers={"Content-Type": content_type},
                license_tag="COPERNICUS_DATA_SPACE_TERMS",
                redistribution_allowed="conditional",
                commercial_use="conditional",
                status="completed",
            )
            asset_manifest_path = manifest.with_name(manifest.stem + "_asset.json")
            write_asset_manifest(asset_manifest, asset_manifest_path)
            result.update(
                status="completed",
                data_truth="real_sentinel3_olci_taihu_raster",
                http_status=status,
                content_type=content_type,
                raster_written=True,
                checksum_sha256=sha256_file(output),
                asset_manifest=str(asset_manifest_path),
                next_action="进入后续水色质量控制与跨源一致性检查",
            )
    except HTTPError as exc:
        result.update(status="BLOCKED_AUTH" if exc.code in {401, 403} else "FAILED", http_status=int(exc.code), error_class="ProcessAPIHTTPError")
    except (URLError, TimeoutError) as exc:
        result.update(status="FAILED", error_class=type(exc).__name__)
    _write_manifest(manifest, result)
    return result


__all__ = [
    "AUTH_PROBE_PATH",
    "DATA_TYPE",
    "DEFAULT_BBOX",
    "DEFAULT_HEIGHT",
    "DEFAULT_MAX_CLOUD_COVERAGE",
    "DEFAULT_MOSAICKING_ORDER",
    "DEFAULT_UPSAMPLING",
    "DEFAULT_WIDTH",
    "EVALSCRIPT",
    "PROCESS_API_URL",
    "TARGET_BANDS",
    "TOKEN_ENDPOINT",
    "build_sentinel3_process_request",
    "run_sentinel3_olci",
]
