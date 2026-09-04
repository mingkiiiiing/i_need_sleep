"""正网格连通域与水华范围几何 (设计 §9 T7 空间范围).

rook 邻接连通域统计（BFS），正网格 GeoJSON 证据导出。
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from data_factory.contracts.spatial import cell_indices


def rook_components(positive_mask: np.ndarray, grid_ids: pd.Series | list[str]) -> tuple[int, int]:
    """返回 (连通域个数, 最大连通域网格数)。"""

    ix, iy = cell_indices(grid_ids)
    index_of = {f"G{int(a):04d}{int(b):04d}": i for i, (a, b) in enumerate(zip(ix, iy))}
    visited = np.zeros(len(positive_mask), dtype=bool)
    n_components = 0
    largest = 0
    for start in range(len(positive_mask)):
        if not positive_mask[start] or visited[start]:
            continue
        n_components += 1
        size = 0
        stack = [start]
        visited[start] = True
        while stack:
            node = stack.pop()
            size += 1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = index_of.get(f"G{int(ix[node]) + dx:04d}{int(iy[node]) + dy:04d}")
                if neighbor is not None and positive_mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)
        largest = max(largest, size)
    return n_components, largest


def spatial_extent_label(positive_mask: np.ndarray, grid_ids: pd.Series | list[str], min_cluster: int = 2) -> int:
    """T7：存在 ≥min_cluster 连片正网格 → 1，否则 0。"""

    if not positive_mask.any():
        return 0
    _, largest = rook_components(positive_mask, grid_ids)
    return int(largest >= min_cluster)


def positive_cells_geojson(
    cells: pd.DataFrame,
    bloom_fraction_by_grid: pd.Series,
    threshold: float,
    cell_size_m: int = 1000,
    crs: str = "EPSG:32651",
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """导出当日正网格 FeatureCollection（UTM 方块近似，网格版本内坐标确定）。"""

    from shapely.geometry import mapping, box

    features = []
    for row in cells.itertuples(index=False):
        fraction = float(bloom_fraction_by_grid.get(row.grid_id, 0.0))
        if fraction < threshold:
            continue
        ix, iy = cell_indices(pd.Series([row.grid_id]))
        x0, y0 = int(ix[0]) * cell_size_m, int(iy[0]) * cell_size_m
        geom = box(x0, y0, x0 + cell_size_m, y0 + cell_size_m)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {"grid_id": row.grid_id, "bloom_fraction": round(fraction, 6), **(properties or {})},
            }
        )
    return {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": crs}}, "features": features}


def write_geojson(payload: dict[str, Any], path) -> str:
    path = __import__("pathlib").Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)
