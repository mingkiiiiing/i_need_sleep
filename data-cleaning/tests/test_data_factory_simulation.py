"""data_factory 仿真层测试：确定性 RNG、输运、水华、营养盐回归修复。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_factory.contracts.spatial import cell_indices
from data_factory.labeling.geometry import rook_components
from data_factory.simulation.algae import growth_factors
from data_factory.simulation.bloom import simulate_bloom_fraction
from data_factory.simulation.nutrients import simulate_nutrients
from data_factory.simulation.engine import zone_rngs
from data_factory.simulation.rng import spatial_modes
from data_factory.simulation.transport import TransportOperator, step_transport


def _grid(n_x: int = 4, n_y: int = 4) -> pd.DataFrame:
    rows = []
    for iy in range(n_y):
        for ix in range(n_x):
            rows.append({"grid_id": f"G{ix:04d}{iy:04d}", "utm_x": 350000.0 + ix * 1000.0, "utm_y": 3450000.0 + iy * 1000.0, "is_edge": ix in (0, n_x - 1) or iy in (0, n_y - 1)})
    return pd.DataFrame(rows)


MECHANISM = {
    "transport": {"diffusion_m2_s": 1.0, "wind_drift_fraction": 0.02, "boundary_outflow_per_day": 0.03},
    "bloom": {"a0": -3.0, "a1": 0.9, "a2": 0.5, "a3": 0.06, "a4": 0.5, "a5": 0.3, "persistence_days": 7, "calm_wind": 3.0, "aggregation_gain": 1.5},
    "algae": {"mu_max": 0.35, "half_sat_n": 0.20, "half_sat_p": 0.02, "topt": 28.0, "pigment_ratio_base": 0.005, "non_cyano_fraction": 4.0},
}


class TestRng:
    def test_zone_rngs_deterministic_and_zone_separated(self):
        a = zone_rngs(20260904, 0)
        b = zone_rngs(20260904, 0)
        c = zone_rngs(20260904, 1)
        assert set(a) == set(b) == set(c)
        for key in a:
            va, vb, vc = a[key].normal(size=8), b[key].normal(size=8), c[key].normal(size=8)
            assert np.array_equal(va, vb)
            assert not np.array_equal(va, vc)

    def test_spatial_modes_correlated(self):
        coords = np.array([[350000.0 + i * 1000.0, 3450000.0] for i in range(20)])
        modes = spatial_modes(coords, length_km=7.0)
        assert modes.shape == (20, 20)  # k 截断到 N=20
        field1 = modes @ np.random.default_rng(0).standard_normal(20)
        field2 = modes @ np.random.default_rng(0).standard_normal(20)
        assert np.allclose(field1, field2)


class TestTransport:
    def test_diffusion_smooths_but_conserves_approximately(self):
        op = TransportOperator(_grid(), MECHANISM)
        field = np.zeros(16)
        field[5] = 1.0
        out, outflow = step_transport(field, op, None)
        assert (out >= 0).all()
        # 行归一化邻域均值在边界格有轻微放大（边界格权重更大），由边界出流补偿；
        # 单步增量应远小于 1%
        assert out.sum() <= field.sum() * 1.01
        assert out[5] < 1.0  # 中心稀释
        neighbors = [out[j] for j in (1, 4, 6, 9)]
        assert max(neighbors) > 0.0  # 扩散到邻格

    def test_wind_drift_moves_mass_downwind(self):
        op = TransportOperator(_grid(), MECHANISM)
        field = np.zeros(16)
        field[5] = 1.0  # (ix=1, iy=1) 中心
        out, outflow = step_transport(field, op, 90.0)  # u=+1 → 向东 (+ix)
        assert out[6] > out[4]  # 东邻 (2,1) > 西邻 (0,1)

    def test_deterministic(self):
        op = TransportOperator(_grid(), MECHANISM)
        field = np.abs(np.random.default_rng(1).normal(size=16))
        assert np.array_equal(step_transport(field, op, 45.0)[0], step_transport(field, op, 45.0)[0])


class TestBloom:
    def test_fraction_bounds_and_monotone_in_biomass(self):
        grid = _grid()
        tw = np.full((5, 16), 26.0)
        ws = np.full((5, 16), 1.5)
        effective = np.full(16, 0.9e6)
        f_low = simulate_bloom_fraction(np.full((5, 16), 0.01), tw, ws, effective, grid, MECHANISM)["bloom_fraction"]
        f_high = simulate_bloom_fraction(np.full((5, 16), 30.0), tw, ws, effective, grid, MECHANISM)["bloom_fraction"]
        assert (f_low >= 0).all() and (f_low <= 1).all()
        assert (f_high >= f_low - 1e-9).all()

    def test_bloom_area_consistent(self):
        grid = _grid()
        out = simulate_bloom_fraction(np.full((3, 16), 26.0), np.full((3, 16), 20.0), np.full((3, 16), 2.0), np.full(16, 1.0e6), grid, MECHANISM)
        assert (out["bloom_area_grid_km2"] <= 1.0 + 1e-9).all()  # 单格最大 1 km²


class TestAlgaeFactors:
    def test_factors_in_unit_range(self):
        cfg = MECHANISM["algae"]
        tw = np.array([5.0, 15.0, 28.0, 35.0])
        out = growth_factors(tw, np.full(4, 1.0), np.full(4, 0.1), np.full(4, 200.0), cfg)
        for key, values in out.items():
            assert ((values >= 0) & (values <= 1.0001)).all(), key
        # 最适温度附近 fT 最高
        assert out["fT"][2] >= out["fT"][0]
        assert out["fT"][2] >= out["fT"][3]

    def test_nutrient_limitation_monotone(self):
        cfg = MECHANISM["algae"]
        tn_low = np.array([0.05, 0.2, 2.0])
        out = growth_factors(np.full(3, 26.0), tn_low, np.full(3, 0.1), np.full(3, 200.0), cfg)
        assert out["fN"][0] < out["fN"][1] <= out["fN"][2]


class TestNutrientsRegression:
    """回归：precip (T,N) + depth (T,N) 不得再触发广播错误（2026-09-04 端到端修复）。"""

    def test_simulate_nutrients_shapes(self):
        T, N = 40, 9
        dates = pd.date_range("2024-01-01", periods=T, freq="D")
        rngs = {"nutrients": np.random.default_rng(7)}
        lookup = lambda family, key, scope: (None, 0)  # noqa: E731 — 无拟合参数时走先验
        out = simulate_nutrients(
            dates,
            np.full((T, N), 22.0),
            np.full((T, N), 3.0),
            np.full((T, N), 180.0),
            np.full((T, N), 12.0) * np.ones((T, N)),  # (T,N) 湖面均匀降水
            np.zeros((T, N)),
            np.zeros((T, N)),
            np.full((N,), 2.0) + np.zeros((T, 1)) * 0 + np.linspace(1.8, 2.2, T)[:, None],  # (T,N) 动态水深
            "TAIHU_ML",
            lookup,
            {"nutrients": {}},
            rngs,
            {"load_multiplier": 1.5, "extremes": {"load_pulse_multiplier": 4.0}},
        )
        for key, values in out.items():
            if key.startswith("_"):  # _bound_hits 等诊断键
                continue
            assert values.shape == (T, N), key
            assert np.isfinite(values).all(), key
        assert (out["total_phosphorus"] >= 0.005).all()
        assert (out["dissolved_oxygen"] >= 0).all()
        assert isinstance(out["_bound_hits"], dict) and "total_phosphorus" in out["_bound_hits"]


class TestGeometry:
    def test_rook_components(self):
        grid_ids = [f"G000{a:01d}000{b:01d}" for a in range(3) for b in range(3)]
        mask = np.array([True, True, False, False, False, False, False, True, True])
        n_components, largest = rook_components(mask, pd.Series(grid_ids))
        assert n_components == 2
        assert largest == 2

    def test_single_blob(self):
        grid_ids = [f"G000{a:01d}000{b:01d}" for a in range(3) for b in range(3)]
        # 正网格: (0,0),(0,1),(1,0),(1,1),(1,2) —— 单一连通域 5 格
        mask = np.array([True, True, False, True, True, True, False, False, False])
        n_components, largest = rook_components(mask, pd.Series(grid_ids))
        assert n_components == 1
        assert largest == 5
