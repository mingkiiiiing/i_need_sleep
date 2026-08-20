from __future__ import annotations

"""Sentinel-2 target-asset planning and resumable download helpers.

The CDSE STAC catalogue exposes many assets per scene, including the large
SAFE product.  This module deliberately selects only the bands required by
the Taihu water-quality workflow and never downloads the ``Product`` archive.
Metadata-only runs remain useful when CDSE credentials are unavailable: they
produce an auditable plan and a BLOCKED_AUTH manifest rather than pretending a
remote JP2 was downloaded.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from ..provenance import write_asset_manifest
from .common import PACKAGE_ROOT, download_asset, sha256_file, utc_now


TARGET_ASSETS: tuple[str, ...] = ("B02", "B03", "B04", "B05", "B08", "B8A", "B11", "SCL")
CDSE_S3_ENDPOINT = "https://eodata.dataspace.copernicus.eu"
CDSE_AUTH_PROBE = PACKAGE_ROOT / "storage" / "manifests" / "cdse_auth_probe.json"


def _scene_from_input(scene: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept either a STAC Feature or the lightweight STAC summary."""

    if "assets" not in scene:
        raise ValueError("Sentinel-2 scene must contain an assets mapping")
    return scene


def load_stac_scenes(path: Path) -> list[dict[str, Any]]:
    """Load scenes from a raw STAC response envelope or a FeatureCollection."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("payload"), dict):
        payload = payload["payload"]
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        return [dict(feature) for feature in payload.get("features", []) if isinstance(feature, Mapping)]
    if isinstance(payload, dict) and payload.get("type") == "Feature":
        return [payload]
    if isinstance(payload, dict) and isinstance(payload.get("scenes"), list):
        return [dict(scene) for scene in payload["scenes"] if isinstance(scene, Mapping)]
    raise ValueError("input is not a STAC Feature, FeatureCollection, or scene summary list")


def _asset_base(key: str) -> str:
    return str(key).split("_", 1)[0].upper()


def _asset_size(asset: Mapping[str, Any]) -> int | None:
    value = asset.get("file:size", asset.get("size"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _asset_checksum(asset: Mapping[str, Any]) -> str | None:
    for key in ("checksum:sha256", "sha256", "file:checksum"):
        value = asset.get(key)
        if not value:
            continue
        text = str(value)
        if text.lower().startswith("sha256:"):
            text = text.split(":", 1)[1]
        if len(text) == 64:
            return text.lower()
    return None


def _preferred_asset_key(
    assets: Mapping[str, Any], band: str, *, prefer_cog: bool = True
) -> tuple[str, Mapping[str, Any], str] | None:
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    for key, value in assets.items():
        if not isinstance(value, Mapping) or _asset_base(str(key)) != band:
            continue
        if not value.get("href"):
            continue
        candidates.append((str(key), value))
    if not candidates:
        return None

    def is_cog(item: tuple[str, Mapping[str, Any]]) -> bool:
        key, asset = item
        text = f"{key} {asset.get('type', '')} {asset.get('href', '')}".lower()
        return "cog" in text or "cloud-optimized" in text or "geotiff" in text or ".tif" in text

    if prefer_cog:
        cog = next((item for item in candidates if is_cog(item)), None)
        if cog:
            return cog[0], cog[1], "cog_preferred"
    # Stable ordering avoids a different asset being selected after a STAC
    # response reorders its dictionary.
    candidates.sort(key=lambda item: item[0])
    return candidates[0][0], candidates[0][1], "jp2_fallback_no_cog_asset"


def select_sentinel2_assets(
    scene: Mapping[str, Any],
    bands: Sequence[str] = TARGET_ASSETS,
    *,
    prefer_cog: bool = True,
) -> list[dict[str, Any]]:
    """Select only requested Sentinel-2 bands/SCL from a STAC scene.

    The returned records retain the original asset descriptors.  Missing
    requested bands are reported by ``build_download_plan`` rather than being
    silently substituted with a different wavelength.
    """

    scene = _scene_from_input(scene)
    assets = scene.get("assets") or {}
    selected: list[dict[str, Any]] = []
    for requested in bands:
        band = str(requested).upper()
        if band not in TARGET_ASSETS:
            raise ValueError(f"unsupported Sentinel-2 target asset: {requested}")
        match = _preferred_asset_key(assets, band, prefer_cog=prefer_cog)
        if not match:
            continue
        key, descriptor, reason = match
        selected.append(
            {
                "band": band,
                "asset_key": key,
                "href": str(descriptor["href"]),
                "type": descriptor.get("type"),
                "title": descriptor.get("title"),
                "roles": descriptor.get("roles"),
                "file_size": _asset_size(descriptor),
                "expected_sha256": _asset_checksum(descriptor),
                "selection_reason": reason,
            }
        )
    return selected


def s3_href_to_https(href: str, endpoint: str = CDSE_S3_ENDPOINT) -> str:
    """Convert the public STAC ``s3://eodata/key`` URI to CDSE HTTPS form."""

    parsed = urlsplit(href)
    if parsed.scheme.lower() != "s3":
        return href
    if parsed.netloc != "eodata":
        raise ValueError(f"unsupported CDSE S3 bucket: {parsed.netloc}")
    return endpoint.rstrip("/") + "/" + parsed.path.lstrip("/")


def _extension(href: str, asset_key: str) -> str:
    suffix = Path(urlsplit(href).path).suffix
    return suffix if suffix else (".tif" if "cog" in asset_key.lower() else ".jp2")


def build_download_plan(
    scene: Mapping[str, Any],
    bands: Sequence[str] = TARGET_ASSETS,
    *,
    output_root: Path | str | None = None,
    prefer_cog: bool = True,
) -> dict[str, Any]:
    """Build an 8-band bounded plan, including sizes and checksum expectations."""

    scene = _scene_from_input(scene)
    scene_id = str(scene.get("scene_id") or scene.get("id") or "unknown_scene")
    root = Path(output_root) if output_root is not None else PACKAGE_ROOT / "storage" / "raw" / "remote_sensing" / "sentinel2"
    records = select_sentinel2_assets(scene, bands, prefer_cog=prefer_cog)
    selected_bands = {record["band"] for record in records}
    missing = [str(band).upper() for band in bands if str(band).upper() not in selected_bands]
    assets: list[dict[str, Any]] = []
    for record in records:
        href = record["href"]
        request_url = s3_href_to_https(href) if href.startswith("s3://") else href
        output_path = root / scene_id / f"{record['asset_key']}{_extension(href, record['asset_key'])}"
        assets.append(
            {
                **record,
                "request_url": request_url,
                "storage_scheme": urlsplit(href).scheme.lower(),
                "requires_auth": urlsplit(href).scheme.lower() in {"s3", "https"},
                "output_path": str(output_path),
            }
        )
    return {
        "scene_id": scene_id,
        "collection": scene.get("collection") or ((scene.get("collections") or [None])[0]),
        "acquisition_at": (scene.get("acquisition_at") or (scene.get("properties") or {}).get("datetime")),
        "cloud_percent": scene.get("cloud_percent") or (scene.get("properties") or {}).get("eo:cloud_cover"),
        "requested_bands": [str(band).upper() for band in bands],
        "selected_count": len(assets),
        "missing_bands": missing,
        "assets": assets,
        "bounded_download": True,
        "product_archive_selected": False,
        "window_read": any(item["selection_reason"] == "cog_preferred" for item in assets),
    }


def cdse_credentials_present() -> dict[str, bool]:
    """Report presence only; never include credential values in a manifest."""

    return {
        "access_token": bool(os.getenv("TAIHU_CDSE_ACCESS_TOKEN") or os.getenv("TAIHU_CDSE_TOKEN")),
        "s3_access_key": bool(os.getenv("TAIHU_CDSE_S3_ACCESS_KEY")),
        "s3_secret_key": bool(os.getenv("TAIHU_CDSE_S3_SECRET_KEY")),
        "client_id": bool(os.getenv("TAIHU_CDSE_CLIENT_ID")),
        "client_secret": bool(os.getenv("TAIHU_CDSE_CLIENT_SECRET")),
    }


def _auth_available(plan: Mapping[str, Any]) -> tuple[bool, str]:
    credentials = cdse_credentials_present()
    schemes = {item.get("storage_scheme") for item in plan.get("assets", [])}
    if "s3" in schemes and credentials["s3_access_key"] and credentials["s3_secret_key"]:
        return True, "cdse_s3_credentials"
    if schemes <= {"https"} and credentials["access_token"]:
        return True, "cdse_bearer_token"
    return False, "missing_cdse_s3_credentials_or_access_token"


def _write_plan_manifest(path: Path, result: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def run_sentinel2_asset_download(
    stac_input: Path | str,
    *,
    scene_id: str | None = None,
    output_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
    bands: Sequence[str] = TARGET_ASSETS,
    prefer_cog: bool = True,
    downloader: Callable[[Mapping[str, Any], Path], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan and, when authorized, download the selected scene assets.

    ``downloader`` is intentionally injectable for offline contract tests. In
    production, the default path uses the shared resumable HTTP downloader;
    S3 URLs still require CDSE S3 credentials and are not silently fetched as
    anonymous HTTP.
    """

    scenes = load_stac_scenes(Path(stac_input))
    scene = next((item for item in scenes if str(item.get("id") or item.get("scene_id")) == scene_id), None) if scene_id else scenes[0]
    if scene is None:
        raise ValueError(f"scene_id not found: {scene_id}")
    plan = build_download_plan(scene, bands, output_root=output_root, prefer_cog=prefer_cog)
    credentials = cdse_credentials_present()
    auth_ok, auth_method = _auth_available(plan)
    manifest = Path(manifest_path) if manifest_path else PACKAGE_ROOT / "storage" / "manifests" / "sentinel2_assets.json"
    base: dict[str, Any] = {
        "task_id": "P06-02",
        "source_id": "copernicus_sentinel2_assets",
        "retrieved_at_utc": utc_now(),
        "data_truth": "real_stac_asset_metadata",
        "stac_input": str(Path(stac_input)),
        "credentials_present": credentials,
        "auth_method": auth_method if auth_ok else None,
        "auth_probe": str(CDSE_AUTH_PROBE) if CDSE_AUTH_PROBE.exists() else None,
        "plan": plan,
        "downloaded": [],
        "failed": [],
        "manifest": str(manifest),
    }
    if plan["missing_bands"]:
        base["status"] = "BLOCKED_DATA"
        base["next_action"] = "重新检索包含全部目标波段的L2A场景或确认缺失波段是否可接受"
        _write_plan_manifest(manifest, base)
        return base
    if downloader is None and not auth_ok:
        base["status"] = "BLOCKED_AUTH"
        base["next_action"] = "配置CDSE S3 access/secret key（或已授权Bearer token）后重跑同一manifest计划"
        _write_plan_manifest(manifest, base)
        return base

    for item in plan["assets"]:
        target = Path(item["output_path"])
        try:
            if downloader is not None:
                result = dict(downloader(item, target))
            elif item["storage_scheme"] == "s3":
                # urllib cannot sign S3 requests. Keeping this explicit avoids
                # an unauthenticated request that would look like a download.
                raise RuntimeError("CDSE S3 download requires an S3-aware authorized client")
            else:
                headers = {}
                token = os.getenv("TAIHU_CDSE_ACCESS_TOKEN") or os.getenv("TAIHU_CDSE_TOKEN")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                result = download_asset(
                    "copernicus_sentinel2_assets",
                    f"{plan['scene_id']}_{item['asset_key']}",
                    item["request_url"],
                    target,
                    expected_sha256=item.get("expected_sha256"),
                    headers=headers,
                    license_tag="CDSE_TERMS_REVIEW_REQUIRED",
                    redistribution_allowed="unknown",
                    commercial_use="unknown",
                )
            if item.get("file_size") is not None and target.exists() and target.stat().st_size != item["file_size"]:
                raise ValueError(f"size mismatch for {item['asset_key']}: expected {item['file_size']}, got {target.stat().st_size}")
            if target.exists():
                result.setdefault("checksum_sha256", sha256_file(target))
                result["checksum_status"] = "verified" if item.get("expected_sha256") else "computed_not_verified"
            base["downloaded"].append({**item, **result})
        except Exception as exc:
            base["failed"].append({"asset_key": item["asset_key"], "error": str(exc)})
    base["status"] = "completed" if not base["failed"] and len(base["downloaded"]) == plan["selected_count"] else "failed"
    base["data_truth"] = "real_stac_metadata_plus_downloaded_assets" if base["status"] == "completed" else "real_stac_metadata"
    base["next_action"] = "进入P06-03预处理" if base["status"] == "completed" else "修复失败资产后重跑"
    _write_plan_manifest(manifest, base)
    return base


__all__ = [
    "TARGET_ASSETS",
    "build_download_plan",
    "cdse_credentials_present",
    "load_stac_scenes",
    "run_sentinel2_asset_download",
    "s3_href_to_https",
    "select_sentinel2_assets",
]
