"""栅格场服务：读 monthly_v3/raster_manifest.json，返回图层/边界/校准元数据。

数据来自离线脚本 scripts/rs/build_raster_field.py 的预生成产物；
spatial_method = calibrated_annual_product_plus_station_residual。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RasterFieldUnavailable(RuntimeError):
    """栅格产物缺失或不可读。"""


class RasterFieldService:
    def __init__(self, overlays_dir: Path | str | None = None) -> None:
        base = Path(__file__).resolve().parents[1] / "rs_overlays"
        self.overlays_dir = Path(overlays_dir) if overlays_dir else base
        self.manifest_path = self.overlays_dir / "monthly_v3" / "raster_manifest.json"

    def _manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            raise RasterFieldUnavailable(f"栅格场清单不存在: {self.manifest_path}")
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RasterFieldUnavailable(f"栅格场清单无法读取: {exc}") from exc

    def list_layers(self) -> list[dict[str, Any]]:
        manifest = self._manifest()
        return [
            {
                "month": layer["month"],
                "boundary_area_km2": layer["boundary"]["area_km2"],
                "calibration_status": layer["calibration"]["status"],
                "anchor_count": layer["anchor_count"],
            }
            for layer in manifest.get("layers", [])
        ]

    def get_raster_layer(self, month: str | None = None) -> dict[str, Any]:
        manifest = self._manifest()
        layers = manifest.get("layers", [])
        if not layers:
            raise RasterFieldUnavailable("栅格场清单无图层")
        layer = next((l for l in layers if l["month"] == month), None) if month else layers[-1]
        if layer is None:
            raise RasterFieldUnavailable(f"指定月份图层不存在: {month}")
        return {
            "month": layer["month"],
            "metric": "chla",
            "unit": layer["unit"],
            "png_url": f"/rs/{layer['png']}",
            "boundary_geojson_url": f"/rs/{layer['boundary_geojson']}",
            "bounds": layer["bounds"],
            "vmin": layer["vmin"],
            "vmax": layer["vmax"],
            "year_base": layer["year_base"],
            "issued_month": layer["month"],
            "calibration": layer["calibration"],
            "boundary": layer["boundary"],
            "spatial_method": layer["spatial_method"],
            "claim_boundary": manifest.get("claim_boundary"),
            "colorbar_inversion_note": manifest.get("colorbar_inversion_note"),
        }

    def get_boundary_geojson(self, month: str) -> dict[str, Any]:
        manifest = self._manifest()
        layer = next((l for l in manifest.get("layers", []) if l["month"] == month), None)
        if layer is None:
            raise RasterFieldUnavailable(f"指定月份图层不存在: {month}")
        path = self.overlays_dir / layer["boundary_geojson"]
        if not path.is_file():
            raise RasterFieldUnavailable(f"边界文件不存在: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
