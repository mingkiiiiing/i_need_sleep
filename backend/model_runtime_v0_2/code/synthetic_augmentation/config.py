from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SimulationConfig:
    start_date: str = "2005-01-01"
    end_date: str = "2025-12-31"
    random_seed: int = 20260901
    region_ids: tuple[str, ...] = (
        "TAIHU_CT",
        "TAIHU_ET",
        "TAIHU_GH",
        "TAIHU_ML",
        "TAIHU_ST",
        "TAIHU_WT",
        "TAIHU_XK",
        "TAIHU_ZS",
    )
    horizons: tuple[int, ...] = (1, 3, 7, 15, 30, 90)
    data_version: str = "TAIHU_SYNTHETIC_AUGMENTATION_V0.2"
    generator_version: str = "V0.2"
    claim_boundary: str = "synthetic_development_only"

    @property
    def dates(self):
        return pd.date_range(self.start_date, self.end_date, freq="D")


@dataclass(frozen=True)
class GridSimulationConfig:
    """Frozen V0.3 configuration for grid-level synthetic simulation."""

    start_date: str = "2005-01-01"
    end_date: str = "2025-12-31"
    base_seed: int = 20260906
    expected_grid_count: int = 1520
    horizons: tuple[int, ...] = (1, 3, 7, 15, 30)
    data_version: str = "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.3"
    generator_version: str = "V0.3"
    claim_boundary: str = "synthetic_development_only"

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.date_range(self.start_date, self.end_date, freq="D")

    @property
    def expected_grid_day_count(self) -> int:
        return self.expected_grid_count * len(self.dates)


@dataclass(frozen=True)
class GridSimulationConfigV04(GridSimulationConfig):
    """Non-destructive V0.4 extension with seven forecast horizons."""

    horizons: tuple[int, ...] = (1, 3, 7, 15, 30, 60, 90)
    data_version: str = "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.4"
    generator_version: str = "V0.4"
