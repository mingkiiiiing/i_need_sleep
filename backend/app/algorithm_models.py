"""算法模型交付包 V0.2 的平台运行适配层。

模型使用合成增强数据训练；运行时仅把 MEE 最新快照中语义一致的水质字段
写入特征，其余字段保留 NaN 并由 bundle 内冻结的训练期预处理器插补。
这使结果可复现且可追踪，同时不把不完整输入包装成真实业务精度。
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import sys
import threading
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


from .rs_raster import RasterFieldService, RasterFieldUnavailable

MODEL_PACKAGE_ENV = "TAIHU_MODEL_PACKAGE_DIR"
DEFAULT_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "model_runtime_v0_2"
MODEL_SEED = 20260907
SUPPORTED_HORIZONS = (1, 3, 7, 15, 30, 60, 90)
DATA_VERSION = "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.4"
CLAIM_BOUNDARY = "synthetic_development_only"
MODEL_PACKAGE_VERSION = "0.2"

TASKS: tuple[tuple[str, str, str, str], ...] = (
    ("bloom", "T1", "bloom", "水华发生"),
    ("area", "T2", "area", "水华面积"),
    ("coverage", "T2", "coverage", "水华覆盖率"),
    ("density", "T3", "density", "蓝藻密度"),
    ("biomass", "T4", "biomass", "蓝藻生物量"),
    ("chla", "T5", "chla", "叶绿素 a"),
    ("risk_level", "T6", "risk_level", "风险等级"),
    ("probability", "T6", "probability", "风险概率"),
    ("spatial", "T7", "spatial", "空间范围"),
)

OBSERVED_FEATURE_MAP = {
    "water_temperature": "water_temperature_C",
    "total_phosphorus": "total_phosphorus_mg_L",
    "total_nitrogen": "total_nitrogen_mg_L",
    "dissolved_oxygen": "dissolved_oxygen_mg_L",
    "pH": "ph",
}

SENSITIVITY_FEATURES: tuple[tuple[str, str], ...] = (
    ("water_temperature_C", "水温"),
    ("total_phosphorus_mg_L", "总磷"),
    ("total_nitrogen_mg_L", "总氮"),
    ("flow_speed_m_s", "流速"),
    ("solar_radiation_MJ_m2_day", "光照"),
    ("dissolved_oxygen_mg_L", "溶解氧"),
    ("ph", "pH"),
    ("remote_chlorophyll_a_ug_L", "遥感叶绿素 a"),
    ("remote_cyanobacteria_density_cells_L", "遥感蓝藻密度"),
)

UNCERTAINTY_SIGMA = {
    "water_temperature_C": 0.05,
    "total_phosphorus_mg_L": 0.12,
    "total_nitrogen_mg_L": 0.10,
    "flow_speed_m_s": 0.15,
    "solar_radiation_MJ_m2_day": 0.15,
    "dissolved_oxygen_mg_L": 0.08,
    "ph": 0.03,
    "remote_chlorophyll_a_ug_L": 0.15,
    "remote_cyanobacteria_density_cells_L": 0.20,
}


class AlgorithmModelUnavailable(RuntimeError):
    """运行包缺失、依赖缺失或模型加载失败。"""


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


class AlgorithmModelService:
    def __init__(self, realtime_provider: Any, package_dir: Path | str | None = None) -> None:
        configured = os.environ.get(MODEL_PACKAGE_ENV, "").strip()
        self.package_dir = Path(package_dir or configured or DEFAULT_PACKAGE_DIR).resolve()
        self.realtime = realtime_provider
        self._bundles: dict[tuple[str, str, int], Any] = {}
        self._load_lock = threading.RLock()

    @property
    def model_dir(self) -> Path:
        return self.package_dir / "models"

    @property
    def code_dir(self) -> Path:
        return self.package_dir / "code"

    def _manifest(self) -> dict[str, Any]:
        path = self.package_dir / "manifest.json"
        if not path.is_file():
            raise AlgorithmModelUnavailable(f"模型清单不存在: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AlgorithmModelUnavailable(f"模型清单无法读取: {exc}") from exc

    def _runtime_imports(self):
        code_path = str(self.code_dir)
        if code_path not in sys.path:
            sys.path.insert(0, code_path)
        try:
            import pandas as pd
            from modeling_v1.data import transform_batch
            from modeling_v1.predict import load_bundle, predict_batch
        except Exception as exc:  # noqa: BLE001
            raise AlgorithmModelUnavailable(f"模型运行依赖不可用: {exc}") from exc
        return pd, load_bundle, predict_batch, transform_batch

    def status(self) -> dict[str, Any]:
        manifest = self._manifest()
        files = list(self.model_dir.glob("*.joblib"))
        dependency_status = "ready"
        dependency_error = None
        try:
            self._runtime_imports()
        except AlgorithmModelUnavailable as exc:
            dependency_status = "unavailable"
            dependency_error = str(exc)
        expected = int(manifest.get("model_count") or 0)
        ready = dependency_status == "ready" and expected == 63 and len(files) == expected
        return {
            "status": "ready" if ready else "unavailable",
            "package_generation": "v0_2_legacy",
            "package_version": str(manifest.get("version") or MODEL_PACKAGE_VERSION),
            "model_count": len(files),
            "expected_model_count": expected,
            "horizons": list(manifest.get("horizons") or SUPPORTED_HORIZONS),
            "training_window": manifest.get("training_window"),
            "data_version": manifest.get("data_version"),
            "claim_boundary": manifest.get("claim_boundary"),
            "successor_package": {
                "package_generation": "v0_3",
                "endpoints": [
                    "/api/v1/model/v3/status",
                    "/api/v1/model/v3/predictions",
                    "/api/v1/model/v3/acceptance",
                    "/api/v1/model/acceptance/detail",
                    "/api/v1/model/calibration/coverage",
                    "/api/v1/rs/retrieval/validation",
                    "/api/v1/acceptance/overview",
                ],
                "note": "V0.3 真实数据包（月度标签粒度 + conformal 区间 + 动态门禁）走 v3 端点；本包保留为 legacy 对照。",
            },
            "dependency_status": dependency_status,
            "dependency_error": dependency_error,
            "package_dir": str(self.package_dir),
        }

    def _bundle(self, task_id: str, variant: str, horizon_days: int) -> Any:
        key = (task_id, variant, horizon_days)
        cached = self._bundles.get(key)
        if cached is not None:
            return cached
        with self._load_lock:
            cached = self._bundles.get(key)
            if cached is not None:
                return cached
            _, load_bundle, _, _ = self._runtime_imports()
            path = self.model_dir / f"{task_id}-{variant}-{horizon_days}d-s{MODEL_SEED}.joblib"
            if not path.is_file():
                raise AlgorithmModelUnavailable(f"模型文件不存在: {path.name}")
            try:
                # joblib 1.5 在 NumPy 2.5 反序列化旧数组时会触发已知 shape
                # 弃用警告；它不改变数组内容，且项目测试把所有警告升级为异常。
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="Setting the shape on a NumPy array has been deprecated.*",
                        category=DeprecationWarning,
                    )
                    bundle = load_bundle(path)
            except Exception as exc:  # noqa: BLE001
                raise AlgorithmModelUnavailable(f"模型加载失败 {path.name}: {exc}") from exc
            self._bundles[key] = bundle
            return bundle

    @staticmethod
    def _calendar_features(observed_at: str | None) -> dict[str, float]:
        if not observed_at:
            return {}
        try:
            dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return {}
        day = dt.timetuple().tm_yday
        weekday = dt.weekday()
        return {
            "calendar_day_of_year_sin": math.sin(2 * math.pi * day / 365.25),
            "calendar_day_of_year_cos": math.cos(2 * math.pi * day / 365.25),
            "calendar_day_of_week_sin": math.sin(2 * math.pi * weekday / 7),
            "calendar_day_of_week_cos": math.cos(2 * math.pi * weekday / 7),
        }

    def _observed_inputs(self, entity_id: str) -> tuple[dict[str, float], dict[str, Any]]:
        summary = self.realtime.summary()
        observed_at = summary.get("latest_observed_at")
        snapshot_id = summary.get("latest_snapshot_id")
        source_values: dict[str, Any] = {}
        if entity_id == "lake":
            for source_code in OBSERVED_FEATURE_MAP:
                if source_code == "pH":
                    values = [
                        marker.get("metrics", {}).get("pH")
                        for marker in summary.get("markers", [])
                    ]
                    values = [float(value) for value in values if value is not None]
                    source_values[source_code] = sum(values) / len(values) if values else None
                else:
                    source_values[source_code] = (summary.get("means", {}).get(source_code) or {}).get("value")
            scope_name = "全湖 MEE 最新快照均值"
        else:
            station = self.realtime.station(entity_id)
            if station is None:
                raise KeyError(entity_id)
            rows = self.realtime.observations(entity_id, window="latest") or []
            latest: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row.get("observation_status") != "ok" or row.get("value") is None:
                    continue
                code = str(row.get("variable_code"))
                previous = latest.get(code)
                if previous is None or str(row.get("observed_at") or "") > str(previous.get("observed_at") or ""):
                    latest[code] = row
            source_values = {code: (latest.get(code) or {}).get("value") for code in OBSERVED_FEATURE_MAP}
            times = [row.get("observed_at") for row in latest.values() if row.get("observed_at")]
            observed_at = max(times) if times else observed_at
            snapshot_ids = [row.get("snapshot_id") for row in latest.values() if row.get("snapshot_id")]
            snapshot_id = snapshot_ids[0] if snapshot_ids else snapshot_id
            scope_name = station.get("source_station_name") or entity_id

        observed_features = {
            OBSERVED_FEATURE_MAP[code]: float(value)
            for code, value in source_values.items()
            if value is not None
        }
        return observed_features, {
            "entity_id": entity_id,
            "scope_name": scope_name,
            "snapshot_id": snapshot_id,
            "observed_at": observed_at,
            "source_dataset_version": "MEE-RT-V1",
            "observed_fields": sorted(observed_features),
        }

    @staticmethod
    def _raw_frame(pd: Any, bundle: Any, observed: dict[str, float], calendar: dict[str, float]):
        row = {name: float("nan") for name in bundle.feature_columns}
        for name, value in {**observed, **calendar}.items():
            if name in row:
                row[name] = value
        return pd.DataFrame([row], columns=list(bundle.feature_columns))

    @staticmethod
    def _model_values(model_output: Any, output_key: str) -> tuple[np.ndarray | None, np.ndarray | None]:
        labels = None
        if output_key == "risk_level":
            labels = model_output["prediction"].astype(str).to_numpy()
            return None, labels
        value_column = "probability" if output_key == "bloom" and "probability" in model_output else "prediction"
        values = np.asarray(model_output[value_column], dtype=float).ravel()
        return values, labels

    def _explain_and_quantify(
        self,
        bundle: Any,
        raw_frame: Any,
        output_key: str,
        observed: dict[str, float],
        seed_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Local one-at-a-time sensitivity plus an input-perturbation distribution.

        This is deliberately not labelled SHAP or a calibrated confidence interval:
        the delivered bundles contain neither SHAP background data nor residual
        interval calibrators.
        """
        _, _, _, transform_batch = self._runtime_imports()
        if bundle.preprocessor is not None:
            transformed = transform_batch(bundle.preprocessor, raw_frame)
            frame = transformed.loc[:, list(bundle.preprocessor.output_columns)]
        else:
            frame = raw_frame.loc[:, list(bundle.feature_columns)].copy()

        base_output = bundle.model.predict_frame(frame)
        base_values, base_labels = self._model_values(base_output, output_key)
        factors: list[dict[str, Any]] = []
        if base_values is not None:
            for feature, label in SENSITIVITY_FEATURES:
                if feature not in frame.columns:
                    continue
                baseline = float(frame.iloc[0][feature])
                step = max(abs(baseline) * 0.10, 0.01)
                low = frame.copy()
                high = frame.copy()
                low.loc[:, feature] = baseline - step
                high.loc[:, feature] = baseline + step
                low_values, _ = self._model_values(bundle.model.predict_frame(low), output_key)
                high_values, _ = self._model_values(bundle.model.predict_frame(high), output_key)
                effect = float((high_values[0] - low_values[0]) / 2.0)
                factors.append(
                    {
                        "feature": feature,
                        "label": label,
                        "baseline": baseline,
                        "perturbation": "plus_minus_10_percent_local",
                        "effect": effect,
                        "direction": "increase" if effect > 0 else "decrease" if effect < 0 else "neutral",
                        "input_source": "observed" if feature in observed else "frozen_train_median",
                    }
                )
            total = sum(abs(item["effect"]) for item in factors)
            for item in factors:
                item["contribution_percent"] = round(abs(item["effect"]) / total * 100, 2) if total else 0.0
            factors.sort(key=lambda item: abs(item["effect"]), reverse=True)

        # The current feature contract contains TN/TP but not ammonia nitrogen.
        unavailable = [
            {
                "feature": "ammonia_nitrogen_mg_L",
                "label": "氨氮",
                "status": "not_in_frozen_bundle_feature_contract",
                "action": "加入训练数据契约后重新训练并独立验证",
            }
        ]
        explanation = {
            "method": "local_one_at_a_time_sensitivity",
            "is_shap": False,
            "baseline": _json_scalar(base_values[0]) if base_values is not None else _json_scalar(base_labels[0]),
            "factors": factors,
            "unavailable_factors": unavailable,
            "note": "贡献度为冻结输入空间内的局部单因素敏感性归一化结果，不是因果贡献，也不是 SHAP 值。缺测字段围绕训练期中位数计算。",
        }

        digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        sample_count = 64
        scenarios = frame.iloc[[0] * sample_count].reset_index(drop=True)
        perturbed_features: list[dict[str, Any]] = []
        for feature, sigma in UNCERTAINTY_SIGMA.items():
            if feature not in scenarios.columns:
                continue
            baseline = float(frame.iloc[0][feature])
            scale = max(abs(baseline) * sigma, 0.01)
            scenarios.loc[:, feature] = rng.normal(baseline, scale, sample_count)
            perturbed_features.append(
                {
                    "feature": feature,
                    "relative_sigma": sigma,
                    "input_source": "observed" if feature in observed else "frozen_train_median",
                }
            )
        scenario_output = bundle.model.predict_frame(scenarios)
        values, labels = self._model_values(scenario_output, output_key)
        if values is not None:
            uncertainty = {
                "method": "input_perturbation_scenario_distribution",
                "sample_count": sample_count,
                "p05": _json_scalar(float(np.quantile(values, 0.05))),
                "p50": _json_scalar(float(np.quantile(values, 0.50))),
                "p95": _json_scalar(float(np.quantile(values, 0.95))),
                "mean": _json_scalar(float(np.mean(values))),
                "std": _json_scalar(float(np.std(values))),
                "perturbed_features": perturbed_features,
                "is_calibrated_confidence_interval": False,
                "note": "这是输入扰动情景分布，用于量化输入变化下的模型响应；尚无真实测试残差校准，不能称为统计置信区间。",
            }
        else:
            counts = {name: int(np.sum(labels == name)) for name in sorted(set(labels.tolist()))}
            uncertainty = {
                "method": "input_perturbation_scenario_distribution",
                "sample_count": sample_count,
                "class_probability": {name: round(count / sample_count, 4) for name, count in counts.items()},
                "perturbed_features": perturbed_features,
                "is_calibrated_confidence_interval": False,
                "note": "等级概率为输入扰动情景频率，并非经真实样本校准的概率。",
            }
        return explanation, uncertainty

    def acceptance(self) -> dict[str, Any]:
        return {
            "requirement": "融合模型相对最强单一数据驱动模型提升不低于10%",
            "status": "FAIL",
            "target": 0.10,
            "comparison_rows": 189,
            "pass": 0,
            "fail": 175,
            "not_applicable": 14,
            "baseline": "同一任务和时效下 Random Forest 与 XGBoost 的较优者",
            "evidence": "企业提交材料/算法组提交材料_V0.1/06_融合策略对比分析_V0.1.md",
            "action": "补充真实标签、氨氮/水动力/气象预报驱动并重训；测试集冻结后重新运行同口径门禁。",
        }

    def retrieval_status(self) -> dict[str, Any]:
        return {
            "status": "experimental_not_operational",
            "parameters": {
                "chlorophyll_a": "historical_product_and_partial_sentinel2_experimental_retrieval",
                "cyanobacteria_density": "proxy_feature_contract_only",
                "bloom_area": "suspected_pixel_area_supported_when_valid_water_cloud_mask_exists",
            },
            "calibration": {
                "runtime_pair_calibration_endpoint": True,
                "independent_operational_validation": False,
                "reason": "现有 Sentinel-2 实验反演校准 R² 为负且样本超出训练域，不能作为业务真值。",
            },
            "value_origin_rule": "retrieved/calibrated values remain derived and never become observed truth",
        }

    def spatial_field(self, horizon_days: int, metric: str = "risk") -> dict[str, Any]:
        """Predict a station-conditioned spatial sample field over the Taihu vicinity."""
        if horizon_days not in SUPPORTED_HORIZONS:
            raise ValueError(f"horizon_days must be one of {SUPPORTED_HORIZONS}")
        task_map = {
            "risk": ("T6", "probability", "probability", "ratio"),
            "chla": ("T5", "chla", "chla", "μg/L"),
            "area": ("T2", "area", "area", "km²"),
            "biomass": ("T4", "biomass", "biomass", "mg/L"),
        }
        if metric not in task_map:
            raise ValueError(f"metric must be one of {sorted(task_map)}")
        task_id, variant, output_key, unit = task_map[metric]
        bundle = self._bundle(task_id, variant, horizon_days)
        pd, _, predict_batch, _ = self._runtime_imports()
        summary = self.realtime.summary()
        calendar = self._calendar_features(summary.get("latest_observed_at"))
        rows = []
        markers = []
        for marker in summary.get("markers", []):
            lat = marker.get("lat")
            lon = marker.get("lon")
            if lat is None or lon is None or not (30.8 <= float(lat) <= 31.7 and 119.7 <= float(lon) <= 120.8):
                continue
            metrics = marker.get("metrics") or {}
            observed = {
                OBSERVED_FEATURE_MAP[code]: float(metrics[code])
                for code in OBSERVED_FEATURE_MAP
                if metrics.get(code) is not None
            }
            raw = self._raw_frame(pd, bundle, observed, calendar).iloc[0].to_dict()
            rows.append(raw)
            markers.append(marker)
        if not rows:
            raise AlgorithmModelUnavailable("太湖范围内没有具备已核验坐标的实时站点")
        frame = pd.DataFrame(rows, columns=list(bundle.feature_columns))
        output = predict_batch(bundle, frame)
        value_column = "probability" if metric == "risk" and "probability" in output else "prediction"
        values = np.asarray(output[value_column], dtype=float)
        finite = values[np.isfinite(values)]
        low = float(np.min(finite)) if len(finite) else 0.0
        high = float(np.max(finite)) if len(finite) else 1.0
        span = high - low
        points = []
        for marker, value in zip(markers, values, strict=True):
            normalized = float(value) if metric == "risk" else (float(value) - low) / span if span > 0 else 0.5
            points.append(
                {
                    "entity_id": marker.get("id"),
                    "name": marker.get("name"),
                    "lat": marker.get("lat"),
                    "lon": marker.get("lon"),
                    "value": _json_scalar(float(value)),
                    "normalized": round(float(np.clip(normalized, 0.0, 1.0)), 4),
                    "observed_at": marker.get("observed_at"),
                }
            )
        return {
            "horizon_days": horizon_days,
            "metric": metric,
            "unit": unit,
            "points": points,
            "point_count": len(points),
            "selected_model": getattr(bundle.model, "name", type(bundle.model).__name__),
            "prediction_run_id": f"ALG-SPATIAL-V0.2-{summary.get('latest_snapshot_id')}-{horizon_days}d-{metric}",
            "spatial_method": "station_conditioned_model_samples",
            "interpolation_status": "not_continuous_raster",
            "claim_boundary": CLAIM_BOUNDARY,
            "note": "地图展示太湖附近已核验站点输入下的模型空间样点；点间颜色场仅作视觉辅助，不等于卫星像元反演或经验证的连续风险网格。",
        }

    @staticmethod
    def calibrate_retrieval(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "chlorophyll_a": "μg/L",
            "cyanobacteria_density": "cells/L",
            "bloom_area": "km²",
        }
        parameter = str(payload.get("parameter") or "")
        if parameter not in allowed:
            raise ValueError(f"parameter must be one of {sorted(allowed)}")
        pairs = payload.get("pairs")
        if not isinstance(pairs, list) or len(pairs) < 3:
            raise ValueError("pairs 至少需要 3 组 retrieved/reference 同期配对")
        retrieved = np.asarray([float(item["retrieved"]) for item in pairs], dtype=float)
        reference = np.asarray([float(item["reference"]) for item in pairs], dtype=float)
        if not np.isfinite(retrieved).all() or not np.isfinite(reference).all():
            raise ValueError("pairs 包含非有限数值")
        design = np.column_stack([retrieved, np.ones(len(retrieved))])
        slope, intercept = np.linalg.lstsq(design, reference, rcond=None)[0]
        calibrated = np.maximum(0.0, slope * retrieved + intercept)
        residual = reference - calibrated
        ss_tot = float(np.sum((reference - reference.mean()) ** 2))
        metrics = {
            "r2": None if ss_tot == 0 else float(1.0 - np.sum(residual**2) / ss_tot),
            "rmse": float(np.sqrt(np.mean(residual**2))),
            "mae": float(np.mean(np.abs(residual))),
            "pair_count": len(pairs),
        }
        apply_values = payload.get("values") or []
        output = [max(0.0, float(slope) * float(value) + float(intercept)) for value in apply_values]
        return {
            "parameter": parameter,
            "unit": allowed[parameter],
            "method": "affine_ground_pair_calibration",
            "coefficients": {"slope": float(slope), "intercept": float(intercept)},
            "metrics": metrics,
            "calibrated_values": output,
            "value_origin": "derived_calibrated_retrieval",
            "quality_gate": "development_only" if len(pairs) < 20 else "requires_independent_holdout_validation",
            "note": "拟合指标仅描述本次输入配对；未提供独立留出集时不得作为业务精度证明。",
        }

    def predict_suite(self, horizon_days: int, entity_id: str = "lake", focus_metric: str = "risk") -> dict[str, Any]:
        if horizon_days not in SUPPORTED_HORIZONS:
            raise ValueError(f"horizon_days must be one of {SUPPORTED_HORIZONS}")
        focus_map = {"risk": "probability", "chla": "chla", "area": "area", "biomass": "biomass", "density": "density"}
        if focus_metric not in focus_map:
            raise ValueError(f"focus_metric must be one of {sorted(focus_map)}")
        analysis_key = focus_map[focus_metric]
        status = self.status()
        if status["status"] != "ready":
            raise AlgorithmModelUnavailable(status.get("dependency_error") or "63 模型运行包不完整")
        pd, _, predict_batch, _ = self._runtime_imports()
        observed, context = self._observed_inputs(entity_id)
        calendar = self._calendar_features(context.get("observed_at"))
        results: dict[str, Any] = {}
        all_feature_columns: set[str] = set()
        for output_key, task_id, variant, label in TASKS:
            bundle = self._bundle(task_id, variant, horizon_days)
            frame = self._raw_frame(pd, bundle, observed, calendar)
            try:
                raw = predict_batch(bundle, frame).iloc[0].to_dict()
            except Exception as exc:  # noqa: BLE001
                raise AlgorithmModelUnavailable(f"{task_id}-{variant}-{horizon_days}d 推理失败: {exc}") from exc
            result = {
                "task_id": task_id,
                "variant": variant,
                "label": label,
                "value": _json_scalar(raw.get("prediction")),
                "probability": _json_scalar(raw.get("probability")),
                "target": raw.get("target"),
                "unit": {
                    "area": "km²",
                    "coverage": "ratio",
                    "density": "cells/L",
                    "biomass": "mg/L",
                    "chla": "μg/L",
                    "probability": "ratio",
                    "spatial": "ratio",
                }.get(output_key),
                "model_file": f"{task_id}-{variant}-{horizon_days}d-s{MODEL_SEED}.joblib",
                "uncertainty_available": False,
                "selected_model": getattr(bundle.model, "name", type(bundle.model).__name__),
                "selected_model_family": type(bundle.model).__name__,
            }
            if output_key == analysis_key:
                explanation, uncertainty = self._explain_and_quantify(
                    bundle,
                    frame,
                    output_key,
                    observed,
                    f"{context.get('snapshot_id')}|{entity_id}|{horizon_days}|{output_key}",
                )
                result["explainability"] = explanation
                result["uncertainty"] = uncertainty
                result["uncertainty_available"] = True
            results[output_key] = result
            all_feature_columns.update(bundle.feature_columns)

        used = sorted(set(observed) & all_feature_columns)
        derived = sorted(set(calendar) & all_feature_columns)
        imputed = sorted(all_feature_columns - set(used) - set(derived))
        probability = results["probability"].get("value")
        risk_score = round(float(probability) * 100, 1) if isinstance(probability, (int, float)) else None
        run_id = f"ALG-V0.2-{context.get('snapshot_id') or 'no-snapshot'}-{entity_id}-{horizon_days}d"
        return {
            "prediction_run_id": run_id,
            "horizon_days": horizon_days,
            "issued_at": context.get("observed_at"),
            "scope": context,
            "results": results,
            "risk_score": risk_score,
            "analysis_focus": {"requested_metric": focus_metric, "result_key": analysis_key},
            "model": {
                "package_version": MODEL_PACKAGE_VERSION,
                "model_count": 63,
                "training_window": status.get("training_window"),
                "data_version": DATA_VERSION,
                "claim_boundary": CLAIM_BOUNDARY,
                "mechanism_modules": ["藻类生长动力学", "营养盐限制", "光照限制", "混合损失/水动力代理"],
                "ai_algorithms": ["Random Forest", "XGBoost"],
                "fusion_algorithms": ["机理特征融合", "残差融合", "约束加权融合"],
            },
            "acceptance": self.acceptance(),
            "retrieval_and_calibration": self.retrieval_status(),
            "input_provenance": {
                "mode": "observed_plus_frozen_imputation",
                "observed_dataset_version": "MEE-RT-V1",
                "observed_features": used,
                "derived_time_features": derived,
                "imputed_by_frozen_preprocessor": imputed,
                "observed_feature_count": len(used),
                "imputed_feature_count": len(imputed),
                "note": "仅语义一致的 MEE 水质字段进入模型；缺失气象、遥感、机理和空间字段由 bundle 冻结预处理器按训练期中位数插补并保留缺失标记。",
            },
            "quality_gate": {
                "status": "warning",
                "decision": "scenario_assessment_only",
                "reason": "模型由合成增强数据训练，且实时输入字段不完整；当前结果用于系统联调和情景推演，不代表真实太湖预测精度。",
            },
        }


# ==================== V0.3 真实数据模型族（默认服务） ====================

V3_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "model_runtime_v0_3"
MODEL_SEED_V3 = 20260907
CLAIM_BOUNDARY_V3 = "real_data_monthly_station_v0_3"
DATA_VERSION_V3 = "TAIHU_CLEAN_FINAL_V1_20260831/model_dataset.parquet"

# MEE 实时字段 → 特征契约 v2 真实列名（氨氮 P0-1 达标点）
OBSERVED_FEATURE_MAP_V2 = {
    "total_phosphorus": "wq_tp",
    "total_nitrogen": "wq_tn",
    "dissolved_oxygen": "wq_do",
    "pH": "wq_ph",
    "ammonia_nitrogen": "wq_nh4_n",
    "chlorophyll_a": "wq_chla",  # MEE 为 μg/L，契约特征为 mg/L，写入时 ÷1000
}
UNIT_CONVERTED_FEATURES = {"wq_chla": ("μg/L", "mg/L", 0.001)}

V3_SENSITIVITY_FEATURES: tuple[tuple[str, str], ...] = (
    ("wq_tp", "总磷"),
    ("wq_tn", "总氮"),
    ("wq_nh4_n", "氨氮"),
    ("wq_do", "溶解氧"),
    ("wq_ph", "pH"),
    ("wq_chla", "叶绿素 a"),
    ("met_air_temperature_c", "气温"),
    ("met_shortwave_radiation_wm2", "光照"),
    ("hydro_water_level_m", "水位"),
)


class AlgorithmModelServiceV3:
    """V0.3 真实数据模型族运行适配层（月度标签粒度 + conformal 区间 + 动态门禁）。"""

    def __init__(self, realtime_provider: Any, package_dir: Path | str | None = None,
                 legacy_service: Any = None) -> None:
        self.package_dir = Path(package_dir or V3_PACKAGE_DIR).resolve()
        self.realtime = realtime_provider
        self.legacy = legacy_service
        self._bundles: dict[tuple[str, str, int], Any] = {}
        self._context_frame: Any = None
        self._load_lock = threading.RLock()

    @property
    def model_dir(self) -> Path:
        return self.package_dir / "models"

    def _manifest(self) -> dict[str, Any]:
        path = self.package_dir / "manifest.json"
        if not path.is_file():
            raise AlgorithmModelUnavailable(f"V0.3 模型清单不存在: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AlgorithmModelUnavailable(f"V0.3 模型清单无法读取: {exc}") from exc

    def _runtime_imports(self):
        code_path = str(self.package_dir / "code")
        if code_path not in sys.path:
            sys.path.insert(0, code_path)
        try:
            import pandas as pd
            from modeling_real.contracts_real import (
                FEATURE_COLUMNS_V2,
                HORIZON_GRANULARITY_TIER_V3,
                HORIZON_MAP_V3,
                SCENARIO_HORIZONS_V3,
            )
            from modeling_real.data_real import load_bundle
        except Exception as exc:  # noqa: BLE001
            raise AlgorithmModelUnavailable(f"V0.3 模型运行依赖不可用: {exc}") from exc
        return pd, load_bundle, HORIZON_MAP_V3, SCENARIO_HORIZONS_V3, HORIZON_GRANULARITY_TIER_V3, FEATURE_COLUMNS_V2

    def _context(self) -> dict[str, float]:
        """站点-月度上下文：全湖代表站（TAIHU_WHOLE）最近月特征记录。"""
        import pandas as pd

        path = self.package_dir / "supervised" / "features_base.parquet"
        if not path.is_file():
            return {}
        code_path = str(self.package_dir / "code")
        if code_path not in sys.path:
            sys.path.insert(0, code_path)
        from modeling_real.contracts_real import FEATURE_COLUMNS_V2

        with self._load_lock:
            if self._context_frame is None:
                try:
                    self._context_frame = pd.read_parquet(path)
                except Exception:  # noqa: BLE001
                    self._context_frame = pd.DataFrame()
        frame = self._context_frame
        if not len(frame):
            return {}
        whole = frame[frame["station_id"] == "TAIHU_WHOLE"].sort_values("month")
        if not len(whole):
            return {}
        row = whole.iloc[-1]
        return {name: float(row[name]) for name in frame.columns if name in FEATURE_COLUMNS_V2 and pd.notna(row[name])}

    def status(self) -> dict[str, Any]:
        manifest = self._manifest()
        files = list(self.model_dir.glob("*.joblib"))
        expected = len(manifest.get("models", []))
        dependency_status = "ready"
        dependency_error = None
        try:
            self._runtime_imports()
        except AlgorithmModelUnavailable as exc:
            dependency_status = "unavailable"
            dependency_error = str(exc)
        ready = dependency_status == "ready" and expected > 0 and len(files) == expected
        availability = manifest.get("availability_matrix", [])
        trainable = [entry for entry in availability if entry.get("trainable")]
        return {
            "status": "ready" if ready else "unavailable",
            "package_generation": "v0_3",
            "package_version": str(manifest.get("version")),
            "model_count": len(files),
            "expected_model_count": expected,
            "horizons": list(manifest.get("horizons", SUPPORTED_HORIZONS)),
            "training_window": "2005-02..2026-08（按时间冻结划分 train≤2021 / val 2022-2023 / test≥2024）",
            "data_version": manifest.get("data_version"),
            "claim_boundary": manifest.get("claim_boundary", CLAIM_BOUNDARY_V3),
            "feature_contract": manifest.get("feature_contract"),
            "granularity_tier": manifest.get("horizon_granularity_tier"),
            "granularity_disclosure": manifest.get("granularity_disclosure"),
            "availability_summary": {
                "trainable": len(trainable),
                "not_applicable": len(availability) - len(trainable),
                "total": len(availability),
            },
            "legacy_package": {
                "legacy": True,
                "package": "model_runtime_v0_2",
                "package_version": "0.2",
                "claim_boundary": CLAIM_BOUNDARY,
                "model_count": 63,
                "note": "保留作对照与回退（env TAIHU_MODEL_PACKAGE_DIR=model_runtime_v0_2）",
            },
            "dependency_status": dependency_status,
            "dependency_error": dependency_error,
            "package_dir": str(self.package_dir),
        }

    def _bundle(self, task_id: str, variant: str, month_offset: int) -> Any:
        key = (task_id, variant, month_offset)
        cached = self._bundles.get(key)
        if cached is not None:
            return cached
        with self._load_lock:
            cached = self._bundles.get(key)
            if cached is not None:
                return cached
            _, load_bundle, _, _, _, _ = self._runtime_imports()
            path = self.model_dir / f"{task_id}-{variant}-{month_offset}m-s{MODEL_SEED_V3}.joblib"
            if not path.is_file():
                return None
            bundle = load_bundle(path)
            self._bundles[key] = bundle
            return bundle

    def _observed_inputs_v2(self, entity_id: str) -> tuple[dict[str, float], dict[str, Any]]:
        summary = self.realtime.summary()
        context = self._context()
        observed: dict[str, float] = {}
        unit_notes: list[str] = []
        if entity_id == "lake":
            means = summary.get("means", {})
            for code, feature in OBSERVED_FEATURE_MAP_V2.items():
                value = (means.get(code) or {}).get("value")
                if value is not None:
                    observed[feature] = float(value)
        else:
            station = self.realtime.station(entity_id)
            if station is None:
                raise KeyError(entity_id)
            rows = self.realtime.observations(entity_id, window="latest") or []
            latest: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row.get("observation_status") != "ok" or row.get("value") is None:
                    continue
                code = str(row.get("variable_code"))
                previous = latest.get(code)
                if previous is None or str(row.get("observed_at") or "") > str(previous.get("observed_at") or ""):
                    latest[code] = row
            for code, feature in OBSERVED_FEATURE_MAP_V2.items():
                value = (latest.get(code) or {}).get("value")
                if value is not None:
                    observed[feature] = float(value)
        for feature, value in list(observed.items()):
            if feature in UNIT_CONVERTED_FEATURES:
                _, _, factor = UNIT_CONVERTED_FEATURES[feature]
                observed[feature] = value * factor
                unit_notes.append(feature)
        scope_name = "全湖 MEE 最新快照" if entity_id == "lake" else (self.realtime.station(entity_id) or {}).get("source_station_name") or entity_id
        return observed, {
            "entity_id": entity_id,
            "scope_name": scope_name,
            "snapshot_id": summary.get("latest_snapshot_id"),
            "observed_at": summary.get("latest_observed_at"),
            "source_dataset_version": "MEE-RT-V1",
            "observed_fields": sorted(observed),
            "unit_converted_features": unit_notes,
            "month_context_station": "TAIHU_WHOLE",
            "month_context_note": "月度上下文取清洗包特征底表 TAIHU_WHOLE 最近月记录（历史观测/遥感聚合值）",
        }

    def _raw_frame(self, pd: Any, bundle: Any, observed: dict[str, float], context: dict[str, float]) -> Any:
        row = {name: float("nan") for name in bundle.feature_columns}
        for name, value in context.items():
            if name in row:
                row[name] = value
        for name, value in observed.items():
            if name in row:
                row[name] = value
        return pd.DataFrame([row], columns=list(bundle.feature_columns))

    @staticmethod
    def _calendar_features(observed_at: str | None) -> dict[str, float]:
        if not observed_at:
            return {}
        try:
            dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return {}
        month = dt.month
        angle = 2 * math.pi * (month - 1) / 12.0
        return {"calendar_month_sin": math.sin(angle), "calendar_month_cos": math.cos(angle)}

    def predict_suite(self, horizon_days: int, entity_id: str = "lake", focus_metric: str = "risk") -> dict[str, Any]:
        pd, _, horizon_map, scenario_horizons, tiers, _ = self._runtime_imports()
        if horizon_days not in horizon_map.month_map:
            raise ValueError(f"horizon_days must be one of {sorted(horizon_map.month_map)}")
        month_offset = horizon_map.month_offset(horizon_days)
        tier = tiers[horizon_days]
        focus_map = {"risk": "probability", "chla": "chla", "area": "area", "biomass": "biomass", "density": "density"}
        if focus_metric not in focus_map:
            raise ValueError(f"focus_metric must be one of {sorted(focus_map)}")
        manifest = self._manifest()
        availability = {
            (entry["task_id"], entry["variant"]): entry
            for entry in manifest.get("availability_matrix", [])
            if entry.get("horizon_days") == horizon_days
        }
        observed, scope_context = self._observed_inputs_v2(entity_id)
        context = self._context()
        calendar = self._calendar_features(scope_context.get("observed_at"))
        context = {**context, **calendar}
        results: dict[str, Any] = {}
        all_feature_columns: set[str] = set()
        for output_key, task_id, variant, label in TASKS:
            bundle = self._bundle(task_id, variant, month_offset)
            entry = availability.get((task_id, variant), {})
            if bundle is None:
                result = {
                    "task_id": task_id, "variant": variant, "label": label,
                    "value": None, "probability": None, "unit": None,
                    "status": "not_applicable",
                    "not_applicable_reason": entry.get("reason") or "model_bundle_missing",
                    "label_provenance": entry.get("label_provenance"),
                    "uncertainty_available": False,
                }
                if horizon_days in scenario_horizons:
                    result["compliance"] = {"label": "情景推演", "locked": True, "granularity_tier": tier}
                results[output_key] = result
                continue
            frame = self._raw_frame(pd, bundle, observed, context)
            raw = bundle.predict_point(frame).iloc[0].to_dict()
            value = _json_scalar(raw.get("prediction"))
            probability = _json_scalar(raw.get("probability"))
            uncertainty = None
            if bundle.intervals is not None:
                point = float(probability if probability is not None else (value or 0.0))
                p05, p95 = point + bundle.intervals.residual_p05, point + bundle.intervals.residual_p95
                uncertainty = {
                    "method": "split_conformal_residual_quantiles",
                    "p05": _json_scalar(max(p05, 0.0)),
                    "p95": _json_scalar(p95),
                    "is_calibrated_confidence_interval": True,
                    "coverage": {
                        "target": 0.90,
                        "calibration_n": bundle.intervals.calibration_n,
                        "empirical_coverage_test": bundle.uncertainty_meta.get("empirical_coverage_test"),
                        "test_n": bundle.uncertainty_meta.get("test_n"),
                    },
                }
            result = {
                "task_id": task_id,
                "variant": variant,
                "label": label,
                "value": value,
                "probability": probability,
                "target": bundle.target,
                "unit": {
                    "area": "km²", "coverage": "ratio", "density": "cells/L",
                    "biomass": "mg/L", "chla": "μg/L", "probability": "ratio", "spatial": "ratio",
                }.get(output_key),
                "model_file": f"{bundle.run_id}.joblib",
                "selected_family": bundle.selected_family,
                "granularity_tier": bundle.granularity_tier,
                "label_provenance": entry.get("label_provenance"),
                "uncertainty": uncertainty,
                "uncertainty_available": uncertainty is not None,
            }
            if output_key == focus_map[focus_metric]:
                result["explainability"] = self._explain(bundle, frame, observed)
            if horizon_days in scenario_horizons:
                result["compliance"] = {"label": "情景推演", "locked": True, "granularity_tier": tier}
            results[output_key] = result
            all_feature_columns.update(bundle.feature_columns)
        probability_value = results.get("probability", {}).get("value")
        risk_score = round(float(probability_value) * 100, 1) if isinstance(probability_value, (int, float)) else None
        return {
            "prediction_run_id": f"ALG-V0.3-{scope_context.get('snapshot_id') or 'no-snapshot'}-{entity_id}-{horizon_days}d",
            "horizon_days": horizon_days,
            "month_offset": month_offset,
            "granularity_tier": tier,
            "issued_at": scope_context.get("observed_at"),
            "scope": scope_context,
            "results": results,
            "risk_score": risk_score,
            "analysis_focus": {"requested_metric": focus_metric, "result_key": focus_map[focus_metric]},
            "model": {
                "package_generation": "v0_3",
                "package_version": "0.3",
                "model_count": len(list(self.model_dir.glob('*.joblib'))),
                "training_data": DATA_VERSION_V3,
                "claim_boundary": CLAIM_BOUNDARY_V3,
                "granularity_disclosure": manifest.get("granularity_disclosure"),
                "mechanism_modules": ["真实驱动机理因子（温度/光照/磷/氮限制）", "营养盐限制", "净生长率代理"],
                "ai_algorithms": ["Random Forest", "XGBoost"],
                "fusion_algorithms": ["机理特征融合", "残差融合", "约束加权融合"],
            },
            "acceptance": self.acceptance(),
            "retrieval_and_calibration": self.retrieval_status(),
            "input_provenance": self._provenance_bundle(observed, context),
            "quality_gate": {
                "status": "ok",
                "decision": "real_data_scenario_assessment",
                "reason": "模型由真实清洗数据训练（月度标签粒度）；结果用于业务研判与情景推演，精度表述以冻结测试集评估为准。",
            },
        }

    def _provenance_bundle(self, observed: dict[str, float], context: dict[str, float]) -> dict[str, Any]:
        remote = [c for c in context if c.startswith("rs_")]
        static = [c for c in context if c.startswith("static_")]
        derived = sorted((set(context) - set(observed)) - set(remote) - set(static))
        return {
            "mode": "observed_plus_month_context_plus_frozen_imputation",
            "observed_dataset_version": "MEE-RT-V1",
            "observed_features": sorted(observed),
            "derived_month_context_features": derived,
            "remote_retrieval_features": remote,
            "static_features": static,
            "proxy_derived_features": [],
            "imputed_by_frozen_preprocessor": "由各 bundle 冻结预处理器按训练期中位数插补（逐字段清单见 results）",
            "observed_feature_count": len(observed),
            "imputed_feature_count": None,
            "note": (
                "MEE 实时水质字段（含氨氮 wq_nh4_n）直接写入；其余字段取 TAIHU_WHOLE 最近月上下文，"
                "仍缺失者由 bundle 冻结预处理器按训练期中位数插补；遥感字段均为 remote_retrieval 口径。"
            ),
        }

    def _explain(self, bundle: Any, frame: Any, observed: dict[str, float]) -> dict[str, Any]:
        factors = []
        base_output = bundle.predict_point(frame).iloc[0]
        base_value = float(base_output.get("probability", base_output.get("prediction")))
        for feature, label in V3_SENSITIVITY_FEATURES:
            if feature not in frame.columns:
                continue
            baseline = float(frame.iloc[0][feature])
            step = max(abs(baseline) * 0.10, 0.01)
            low, high = frame.copy(), frame.copy()
            low.loc[:, feature] = baseline - step
            high.loc[:, feature] = baseline + step
            try:
                low_out = bundle.predict_point(low).iloc[0]
                high_out = bundle.predict_point(high).iloc[0]
            except Exception:  # noqa: BLE001
                continue
            low_value = float(low_out.get("probability", low_out.get("prediction")))
            high_value = float(high_out.get("probability", high_out.get("prediction")))
            effect = (high_value - low_value) / 2.0
            factors.append({
                "feature": feature, "label": label, "baseline": baseline,
                "perturbation": "plus_minus_10_percent_local",
                "effect": effect,
                "direction": "increase" if effect > 0 else "decrease" if effect < 0 else "neutral",
                "input_source": "observed" if feature in observed else "month_context_or_imputed",
            })
        total = sum(abs(item["effect"]) for item in factors)
        for item in factors:
            item["contribution_percent"] = round(abs(item["effect"]) / total * 100, 2) if total else 0.0
        factors.sort(key=lambda item: abs(item["effect"]), reverse=True)
        return {
            "method": "local_one_at_a_time_sensitivity",
            "is_shap": False,
            "baseline": base_value,
            "factors": factors[:8],
            "unavailable_factors": [],
            "note": "贡献度为冻结输入空间内的局部单因素敏感性归一化结果，不是因果贡献，也不是 SHAP 值。",
        }

    # ---- 门禁（唯一来源：evaluation/gate_table.json；无硬编码比较数） ----

    def _gate_table(self) -> dict[str, Any]:
        path = self.package_dir / "evaluation" / "gate_table.json"
        if not path.is_file():
            raise AlgorithmModelUnavailable(f"门禁表不存在: {path}（请先运行 cli_real.py gate）")
        return json.loads(path.read_text(encoding="utf-8"))

    def acceptance(self) -> dict[str, Any]:
        gate = self._gate_table()
        summary = gate["summary"]
        return {
            "requirement": "融合模型相对最强单一数据驱动模型提升不低于10%",
            "status": summary["status"],
            "target": gate["uplift_threshold"],
            "comparison_rows": summary["comparison_rows"],
            "evaluable_comparisons": summary["evaluable_comparisons"],
            "pass": summary["pass"],
            "fail": summary["fail"],
            "not_applicable": summary["not_applicable"],
            "baseline": "同一任务和时效下 Random Forest 与 XGBoost 的较优者（validation 选族、冻结测试集同口径）",
            "min_test_rows": gate.get("min_test_rows"),
            "evidence": "/api/v1/model/acceptance/detail",
            "honesty_note": gate.get("honesty_note"),
            "note": summary.get("note"),
            "action": (
                "真实数据可评估比较数以 gate_table.json 为准；N.A. 行须补足真实标签后重训再评。"
                if summary["status"] == "NOT_APPLICABLE"
                else "如未达标，须补足真实标签与驱动数据后重训，禁止调整口径。"
            ),
        }

    def acceptance_detail(self) -> dict[str, Any]:
        gate = self._gate_table()
        manifest = self._manifest()
        covered = {
            (row["task_id"], row["variant"], row["horizon_days"]) for row in gate.get("rows", [])
        }
        rows = list(gate.get("rows", []))
        for entry in manifest.get("availability_matrix", []):
            key = (entry["task_id"], entry["variant"], entry["horizon_days"])
            if entry.get("trainable") or key in covered:
                continue
            rows.append({
                "task_id": entry["task_id"],
                "task_label": None,
                "variant": entry["variant"],
                "horizon_days": entry["horizon_days"],
                "month_offset": entry.get("month_offset"),
                "n_test": entry.get("test_rows", 0),
                "status": "NA",
                "na_reason": entry.get("reason") or "not_trainable",
                "primary_metric": None,
                "fusion_value": None,
                "best_single_value": None,
                "uplift": None,
            })
        return {
            "gate_version": gate.get("gate_version"),
            "generated_at": gate.get("generated_at"),
            "comparison_rule": gate.get("comparison_rule"),
            "uplift_threshold": gate.get("uplift_threshold"),
            "min_test_rows": gate.get("min_test_rows"),
            "summary": gate.get("summary"),
            "rows": rows,
            "honesty_note": gate.get("honesty_note"),
        }

    def calibration_coverage(self) -> dict[str, Any]:
        manifest = self._manifest()
        items = []
        for model in manifest.get("models", []):
            uncertainty = model.get("uncertainty") or {}
            if not uncertainty.get("is_calibrated_confidence_interval"):
                continue
            items.append({
                "task_id": model["run_id"].split("-")[0],
                "run_id": model["run_id"],
                "horizon_days": model.get("horizon_days"),
                "coverage_target": uncertainty.get("coverage_target", 0.90),
                "empirical_coverage": uncertainty.get("empirical_coverage_test"),
                "calibration_n": uncertainty.get("calibration_n"),
                "test_n": uncertainty.get("test_n"),
            })
        return {"items": items, "method": "split_conformal_residual_quantiles"}

    def retrieval_validation(self) -> dict[str, Any]:
        path = self.package_dir / "evaluation" / "calibration_manifest.json"
        if not path.is_file():
            raise AlgorithmModelUnavailable(f"遥感校准清单不存在: {path}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        scatter = self.package_dir / "evaluation" / "calibration_scatter.csv"
        pairs = []
        if scatter.is_file():
            import pandas as pd

            frame = pd.read_csv(scatter)
            pairs = frame.to_dict(orient="records")
        chosen = manifest.get("s2_group_choice", {}).get("chosen")
        sensors = manifest.get("sensors", {})
        return {
            "split": "holdout",
            "holdout_definition": manifest.get("holdout_definition"),
            "pairs": pairs,
            "metrics": {
                name: payload.get("holdout_metrics") for name, payload in sensors.items()
            },
            "s2_group_choice": manifest.get("s2_group_choice"),
            "modis_holdout_metrics": manifest.get("modis_holdout_metrics"),
            "manifest_ref": str(path),
            "honesty_note": manifest.get("honesty_note"),
        }

    def retrieval_status(self) -> dict[str, Any]:
        try:
            manifest = json.loads(
                (self.package_dir / "evaluation" / "calibration_manifest.json").read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            return {"status": "calibration_evidence_missing", "reason": "calibration_manifest.json 不存在"}
        modis = manifest.get("modis_holdout_metrics") or {}
        r2 = modis.get("r2")
        return {
            "status": "ground_pair_calibrated_holdout_validated",
            "parameters": {
                "chlorophyll_a": "annual_product_plus_monthly_station_residual_field",
                "cyanobacteria_density": "proxy_feature_contract_only",
                "bloom_area": "threshold_20_ug_l_on_calibrated_field",
            },
            "calibration": {
                "runtime_pair_calibration_endpoint": True,
                "independent_holdout_validation": True,
                "holdout_pair_count": modis.get("n"),
                "holdout_r2": r2,
                "s2_group_choice": manifest.get("s2_group_choice"),
                "reason": "留出集 R²/RMSE 如实披露（可为负/偏低）；反演值永不成为观测真值。",
            },
            "value_origin_rule": "retrieved/calibrated values remain derived and never become observed truth",
        }

    def spatial_field(self, horizon_days: int, metric: str = "chla", layer: str = "raster") -> dict[str, Any]:
        if horizon_days not in SUPPORTED_HORIZONS:
            raise ValueError(f"horizon_days must be one of {SUPPORTED_HORIZONS}")
        raster_service = RasterFieldService()
        if layer == "raster" and metric == "chla":
            try:
                raster = raster_service.get_raster_layer()
                month = raster["month"]
                compliance = (
                    {"label": "情景推演", "locked": True}
                    if horizon_days in (30, 60, 90)
                    else {"label": "月度反演基底", "locked": False}
                )
                return {
                    "prediction_run_id": f"ALG-V0.3-RASTER-{month}-{horizon_days}d-chla",
                    "horizon_days": horizon_days,
                    "metric": "chla",
                    "unit": raster["unit"],
                    "layer": "raster",
                    "png_url": raster["png_url"],
                    "bounds": raster["bounds"],
                    "vmin": raster["vmin"],
                    "vmax": raster["vmax"],
                    "issued_month": raster["issued_month"],
                    "year_base": raster["year_base"],
                    "calibration": raster["calibration"],
                    "boundary": raster["boundary"],
                    "boundary_geojson_url": raster["boundary_geojson_url"],
                    "spatial_method": raster["spatial_method"],
                    "claim_boundary": raster["claim_boundary"],
                    "colorbar_inversion_note": raster["colorbar_inversion_note"],
                    "compliance": compliance,
                    "note": (
                        "连续栅格 = 年度反演产品（固定色标反解）× 地面/CLMS 月度锚点残差 IDW 修正；"
                        f"水华边界为 {raster['boundary']['threshold_ug_l']} μg/L 阈值分割。"
                    ),
                }
            except RasterFieldUnavailable:
                pass
        # 回退：站点条件化样点场（legacy V0.2 链路，如实标注）
        fallback_metric = "chla" if metric not in {"risk", "chla", "area", "biomass"} else metric
        legacy_field = self.legacy.spatial_field(horizon_days, fallback_metric) if self.legacy is not None else None
        if legacy_field is None:
            raise AlgorithmModelUnavailable("栅格图层缺失且 legacy 站点场服务不可用")
        legacy_field["layer"] = "station"
        legacy_field["fallback_used"] = True
        legacy_field["fallback_reason"] = "requested_raster_layer_unavailable_for_metric"
        legacy_field["compliance"] = (
            {"label": "情景推演", "locked": True}
            if horizon_days in (30, 60, 90)
            else {"label": "站点样点对照", "locked": False}
        )
        return legacy_field

    def acceptance_overview(self) -> dict[str, Any]:
        manifest = self._manifest()
        contract = manifest.get("feature_contract") or {}
        p0_1 = "达标" if contract.get("n_features") == 78 else "未达标"
        models = manifest.get("models", [])
        calibrated = [m for m in models if (m.get("uncertainty") or {}).get("is_calibrated_confidence_interval")]
        p0_2 = "达标" if calibrated else "未达标"
        try:
            calibration = json.loads(
                (self.package_dir / "evaluation" / "calibration_manifest.json").read_text(encoding="utf-8")
            )
            holdout = [payload["holdout_metrics"] for payload in calibration.get("sensors", {}).values() if payload.get("holdout_metrics", {}).get("n")]
            best_r2 = max((m.get("r2") or -9e9) for m in holdout) if holdout else None
            if best_r2 is None:
                p0_3 = "未达标"
            elif best_r2 >= 0.5:
                p0_3 = "达标"
            else:
                p0_3 = "部分达标"
        except Exception:  # noqa: BLE001
            p0_3 = "未达标"
            calibration = None
        try:
            raster_service = RasterFieldService()
            layers = raster_service.list_layers()
            p0_4 = "达标" if layers else "未达标"
        except Exception:  # noqa: BLE001
            p0_4 = "未达标"
            layers = []
        gate = self._gate_table()
        gate_status = gate["summary"]["status"]
        p0_5 = {"PASS": "达标", "FAIL": "未达标"}.get(gate_status, "部分达标")
        p0_6 = "达标" if manifest.get("scenario_horizons") == [30, 60, 90] else "未达标"
        return {
            "claim_boundary": CLAIM_BOUNDARY_V3,
            "items": [
                {
                    "id": "P0-1", "title": "氨氮入特征契约（78 字段契约 v2.0）",
                    "status": p0_1,
                    "evidence": [
                        {"label": "特征契约（/model/status）", "href": "/api/v1/model/status"},
                        {"label": "manifest.json", "href": "/rs/../model_runtime_v0_3/manifest.json"},
                    ],
                    "detail": f"契约版本 {contract.get('version')}，字段数 {contract.get('n_features')}，含 wq_nh4_n / met_shortwave_radiation_wm2。",
                },
                {
                    "id": "P0-2", "title": "残差校准置信区间（split-conformal P05/P95）",
                    "status": p0_2,
                    "evidence": [{"label": "覆盖率元数据", "href": "/api/v1/model/calibration/coverage"}],
                    "detail": f"{len(calibrated)}/{len(models)} 个可训练 bundle 带 conformal 校准器；覆盖率经冻结测试集经验核算。",
                },
                {
                    "id": "P0-3", "title": "遥感反演地面配对校准（留出验证）",
                    "status": p0_3,
                    "evidence": [{"label": "校准证据", "href": "/api/v1/rs/retrieval/validation"}],
                    "detail": (
                        f"留出集最佳 R²={best_r2:.3f}（如实披露，可为负）；配对规则与月覆盖见 manifest。"
                        if holdout and best_r2 is not None and best_r2 > -9e8 else "无可用留出配对。"
                    ),
                },
                {
                    "id": "P0-4", "title": "连续栅格空间场 + 水华边界",
                    "status": p0_4,
                    "evidence": [{"label": "栅格图层", "href": "/api/v1/model/spatial-field?horizon_days=3&metric=chla&layer=raster"}],
                    "detail": f"{len(layers)} 个月度栅格图层（含 20 μg/L 边界 GeoJSON）。",
                },
                {
                    "id": "P0-5", "title": "10% 提升门禁（真实冻结测试集，实时生成）",
                    "status": p0_5,
                    "evidence": [{"label": "门禁明细", "href": "/api/v1/model/acceptance/detail"}],
                    "detail": gate["summary"].get("note"),
                },
                {
                    "id": "P0-6", "title": "30/60/90 天“情景推演”合规边界保留",
                    "status": p0_6,
                    "evidence": [{"label": "预测接口（compliance 字段）", "href": "/api/v1/model/v3/predictions?horizon_days=30"}],
                    "detail": "30/60/90 天输出（API+前端）固定携带 compliance.label='情景推演'，locked=true，不可移除。",
                },
            ],
        }
