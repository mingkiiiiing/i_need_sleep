"""Process-aware mechanism predictions exposed to the training layer.

The adapter uses the compact cyanobacteria growth/loss module as a
causality-safe prior: it starts from issue-time visible drivers/state and, when
the issue-time phytoplankton state is available, advances the biomass under
persistent environmental drivers for the requested horizon.  It never reads
future drivers, target rows, latent truth, or label-derived values.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.linear_model import LinearRegression

from synthetic_augmentation.mechanism import (
    limitation_factors,
    persistence_projection,
)

from .contracts import RISK_CLASSES, TaskSpec
from .models import BaseCandidate


VISIBLE_FACTOR_COLUMNS = (
    "water_temperature_C",
    "total_nitrogen_mg_L",
    "total_phosphorus_mg_L",
    "solar_radiation_MJ_m2_day",
    "mixing_index",
)

OPTIONAL_STATE_COLUMNS = (
    "phytoplankton_biomass_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
    "wind_speed_m_s",
    "water_level_m",
)

OPTIONAL_REMOTE_COLUMNS = (
    "remote_chlorophyll_a_ug_L",
    "remote_phycocyanin_ug_L",
    "remote_cyanobacteria_density_cells_L",
    "remote_fai_proxy",
    "remote_ndci_proxy",
)

OPTIONAL_AUXILIARY_COLUMNS = (
    "air_temperature_C",
    "precipitation_mm_day",
    "wind_direction_deg",
    "relative_humidity_pct",
    "surface_pressure_kPa",
    "flow_speed_m_s",
    "cloud_fraction",
    "valid_pixel_ratio",
    "calendar_day_of_year_sin",
    "calendar_day_of_year_cos",
)


def _finite_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().all():
        raise ValueError(f"mechanism state column {column} has no finite values")
    return values


def _mechanism_score(frame: pd.DataFrame) -> np.ndarray:
    missing = [name for name in VISIBLE_FACTOR_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"mechanism frame missing visible drivers: {missing}")
    factor_input = frame.loc[:, list(VISIBLE_FACTOR_COLUMNS)]
    if "phytoplankton_biomass_mg_L" in frame.columns:
        factor_input = factor_input.copy()
        factor_input["phytoplankton_biomass_mg_L"] = _finite_numeric(
            frame, "phytoplankton_biomass_mg_L"
        )
    factors = limitation_factors(factor_input)
    temperature = factors["temperature_factor"].to_numpy(dtype=float)
    nitrogen = factors["nitrogen_factor"].to_numpy(dtype=float)
    phosphorus = factors["phosphorus_factor"].to_numpy(dtype=float)
    light = factors["light_factor"].to_numpy(dtype=float)
    mixing = _finite_numeric(factor_input, "mixing_index").to_numpy(dtype=float)
    raw = (
        0.34 * temperature
        + 0.20 * np.minimum(nitrogen, phosphorus)
        + 0.18 * light
        - 0.16 * mixing
    )
    return np.clip(raw, 0.0, 1.0)


def _mechanism_design(
    frame: pd.DataFrame,
    horizon_days: int,
) -> pd.DataFrame:
    """Build physically motivated process/state features for calibration."""
    missing = [name for name in VISIBLE_FACTOR_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"mechanism training frame missing visible drivers: {missing}")
    design = pd.DataFrame(index=frame.index)
    factors = limitation_factors(frame)
    design["score"] = _mechanism_score(frame)
    design["temperature_factor"] = factors["temperature_factor"].to_numpy(dtype=float)
    design["nutrient_factor"] = factors["nutrient_factor"].to_numpy(dtype=float)
    design["light_factor"] = factors["light_factor"].to_numpy(dtype=float)
    design["capacity_factor"] = factors["capacity_factor"].to_numpy(dtype=float)
    design["net_growth_rate_d"] = factors["net_growth_rate_d"].to_numpy(dtype=float)

    state_present = "phytoplankton_biomass_mg_L" in frame.columns
    if state_present:
        state = np.maximum(
            _finite_numeric(frame, "phytoplankton_biomass_mg_L").to_numpy(dtype=float),
            0.0,
        )
        projected = persistence_projection(frame, horizon_days)
        design["log1p_biomass_state"] = np.log1p(state)
        design["log1p_biomass_projection"] = np.log1p(
            np.maximum(projected, 0.0)
        )
        design["state_times_net_growth"] = (
            np.log1p(state) * design["net_growth_rate_d"].to_numpy(dtype=float)
        )

    for column in OPTIONAL_STATE_COLUMNS:
        if column == "phytoplankton_biomass_mg_L" or column not in frame.columns:
            continue
        design[column] = _finite_numeric(frame, column).to_numpy(dtype=float)

    for column in OPTIONAL_REMOTE_COLUMNS:
        if column not in frame.columns:
            continue
        values = _finite_numeric(frame, column)
        design[column] = values.to_numpy(dtype=float)
        design[f"log1p_{column}"] = np.log1p(
            np.maximum(values.to_numpy(dtype=float), 0.0)
        )
    for column in OPTIONAL_AUXILIARY_COLUMNS:
        if column not in frame.columns:
            continue
        values = _finite_numeric(frame, column)
        design[column] = values.to_numpy(dtype=float)
    if design.empty or not np.isfinite(design.to_numpy(dtype=float)).all():
        raise ValueError("mechanism design matrix is empty or non-finite")
    return design


@dataclass
class MechanismCandidate(BaseCandidate):
    name: str
    spec: TaskSpec
    feature_columns: tuple[str, ...]
    model: object
    classes: tuple[str, ...] = ()
    horizon_days: int = 1

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        design = _mechanism_design(frame, self.horizon_days)
        x = design.loc[:, list(self.feature_columns)].to_numpy(dtype=float)
        out = pd.DataFrame(index=frame.index)
        if self.spec.problem_type == "binary":
            probability = self.model.predict_proba(x)[:, 1]
            out["probability"] = np.clip(probability, 0.0, 1.0)
            out["prediction"] = (out["probability"] >= 0.5).astype("int8")
        elif self.spec.problem_type == "ordinal":
            ranks = np.rint(self.model.predict(x)).astype(int)
            ranks = np.clip(ranks, 0, len(self.classes) - 1)
            out["prediction"] = pd.Series(
                [self.classes[int(value)] for value in ranks],
                index=frame.index,
            )
        else:
            raw = self.model.predict(x)
            if self.spec.primary_metric == "log1p_mae":
                raw = np.expm1(raw)
            raw = np.maximum(raw, 0.0)
            if self.spec.problem_type in {"probability", "binary"}:
                raw = np.clip(raw, 0.0, 1.0)
            out["prediction"] = raw
            if self.spec.problem_type == "probability":
                out["probability"] = out["prediction"]
        return out


def fit_mechanism(
    train: pd.DataFrame,
    spec: TaskSpec,
    *,
    horizon_days: int = 1,
    name: str = "mechanism",
) -> MechanismCandidate:
    """Calibrate a state/process-aware mechanism prior to one target."""
    if isinstance(horizon_days, bool) or int(horizon_days) <= 0:
        raise ValueError("horizon_days must be a positive integer")
    design = _mechanism_design(train, horizon_days)
    x = design.to_numpy(dtype=float)
    if spec.problem_type == "ordinal":
        actual = train["actual"].astype(str)
        valid = actual.notna() & actual.str.strip().ne("")
        if not valid.any():
            raise ValueError("mechanism calibration has no finite ordinal rows")
        y = actual.loc[valid].to_numpy()
        present = [name for name in RISK_CLASSES if name in set(y)]
        classes = tuple(present if present else (RISK_CLASSES[0],))
        encoder = {name: index for index, name in enumerate(classes)}
        target = np.asarray([encoder[value] for value in y], dtype=float)
        model = LinearRegression().fit(x[valid.to_numpy()], target)
    else:
        actual = pd.to_numeric(train["actual"], errors="coerce")
        valid = actual.notna() & np.isfinite(design.to_numpy(dtype=float)).all(axis=1)
        if not valid.any():
            raise ValueError("mechanism calibration has no finite train samples")
        y = actual.loc[valid].to_numpy()
        x = x[valid.to_numpy()]
        if spec.problem_type == "binary":
            if not np.isin(y, (0.0, 1.0)).all():
                raise ValueError("binary mechanism labels must be 0 or 1")
            model = HistGradientBoostingClassifier(
                max_iter=240,
                learning_rate=0.04,
                max_leaf_nodes=15,
                min_samples_leaf=60,
                class_weight="balanced",
                random_state=20260907,
            ).fit(x, y)
            classes: tuple[str, ...] = ()
        else:
            if spec.primary_metric == "log1p_mae":
                if (y < 0).any():
                    raise ValueError("log1p mechanism targets must be non-negative")
                target = np.log1p(y)
            else:
                target = y
            model = HistGradientBoostingRegressor(
                max_iter=300,
                learning_rate=0.04,
                max_leaf_nodes=15,
                min_samples_leaf=60,
                random_state=20260907,
            ).fit(x, target)
            classes = ()
    return MechanismCandidate(
        name=name,
        spec=spec,
        feature_columns=tuple(design.columns),
        model=model,
        classes=classes,
        horizon_days=int(horizon_days),
    )


def mechanism_feature_frame(
    frame: pd.DataFrame,
    mechanism: MechanismCandidate,
    spec: TaskSpec,
) -> pd.DataFrame:
    """Append a frozen mechanism prediction to model-visible features."""
    result = frame.copy()
    mechanism_output = mechanism.predict_frame(frame)
    if "probability" in mechanism_output.columns:
        result["mechanism_prediction"] = mechanism_output[
            "probability"
        ].to_numpy()
    elif "prediction" in mechanism_output.columns:
        result["mechanism_prediction"] = mechanism_output["prediction"].to_numpy()
    else:
        raise ValueError("mechanism output has no prediction column")
    return result
