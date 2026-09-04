"""网格输运：扩散 + 风漂移 + 边界流出 (设计 §6.9).

扩散用 rook 邻接的显式松弛（邻域均值−当前值）；风漂移按主导风向把质量
向下风向邻居搬运，无下风向邻居的边缘单元按 boundary_outflow 损失。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

from data_factory.contracts.spatial import cell_indices


class TransportOperator:
    def __init__(self, grid_metadata: pd.DataFrame, mechanism: dict[str, Any]):
        cfg = mechanism.get("transport", {})
        self.diffusion = float(cfg.get("diffusion_m2_s", 1.0))
        self.drift_fraction = float(cfg.get("wind_drift_fraction", 0.02))
        self.boundary_outflow = float(cfg.get("boundary_outflow_per_day", 0.03))

        cells = grid_metadata.reset_index(drop=True).copy()
        self.grid_ids = cells["grid_id"].to_numpy()
        self.index_of = {g: i for i, g in enumerate(self.grid_ids)}
        ix, iy = cell_indices(cells["grid_id"])
        self.ix = np.asarray(ix, dtype=int)
        self.iy = np.asarray(iy, dtype=int)
        n = len(cells)
        # rook 邻接（中心距恰为 1 个网格步长）
        rows, cols, weights = [], [], []
        pos = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(ix, iy))}
        for i in range(n):
            x, y = int(ix[i]), int(iy[i])
            count = 0
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                j = pos.get((x + dx, y + dy))
                if j is not None:
                    rows.append(i)
                    cols.append(j)
                    weights.append(1.0)
                    count += 1
            rows.append(i)
            cols.append(i)
            weights.append(float(count))
        adj = sparse.csr_matrix((weights, (rows, cols)), shape=(n, n))
        # 行归一化 → 邻域均值算子（自身对角存邻居数，除以 (自身+邻居数) 后即加权均值）
        row_sum = np.asarray(adj.sum(axis=1)).ravel()
        row_sum[row_sum == 0.0] = 1.0
        self._neighbor_mean = sparse.diags(1.0 / row_sum) @ adj
        self.has_neighbor = np.asarray((adj - sparse.identity(n)).sum(axis=1)).ravel() > 0

    def diffuse(self, field: np.ndarray) -> np.ndarray:
        """field: (N,) 或 (T,N) 的当日切片 (N,)。返回平滑后的 (N,)。"""
        if self.diffusion <= 0.0:
            return field
        # 显式松弛系数：单步最多向邻域均值移动 diffusion/2（m2/s→无量纲保守取 0.05 上限）
        rate = min(self.diffusion / 20.0, 0.05)
        return field + rate * (np.asarray(self._neighbor_mean @ field).ravel() - field)

    def advect_wind(self, field: np.ndarray, wind_direction_deg: float) -> tuple[np.ndarray, float]:
        """把 field 向下风向邻居搬运 drift_fraction×(Fi−Fj)；返回 (新场, 边界流出总量)。"""
        rad = np.deg2rad(float(wind_direction_deg))
        u, v = float(np.sin(rad)), float(np.cos(rad))
        new = field.copy()
        outflow_total = 0.0
        if abs(u) >= abs(v):
            dx, dy = int(np.sign(u)), 0
        else:
            dx, dy = 0, int(np.sign(v))
        if dx == 0 and dy == 0:
            return new, 0.0
        # grid_id 编码 G{ix:04d}{iy:04d} 反查邻居
        for i in range(len(self.grid_ids)):
            j = self.index_of.get(f"G{int(self.ix[i]) + dx:04d}{int(self.iy[i]) + dy:04d}")
            if j is None:
                outflow_total += float(field[i]) * self.boundary_outflow
                new[i] = field[i] * (1.0 - self.boundary_outflow)
                continue
            delta = self.drift_fraction * (field[i] - field[j])
            new[i] -= max(delta, 0.0)
            new[j] += max(delta, 0.0)
        return np.clip(new, 0.0, None), max(outflow_total, 0.0)


def step_transport(field: np.ndarray, operator: TransportOperator, wind_direction_deg: float | None = None) -> tuple[np.ndarray, float]:
    smoothed = operator.diffuse(field)
    if wind_direction_deg is None:
        return smoothed, 0.0
    return operator.advect_wind(smoothed, wind_direction_deg)
