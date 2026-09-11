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

# MEE 实时字段 → 特征契约 v2 真实列名（氨氮 P0-1 达标点；水温 2026-09-11 对齐入约）
OBSERVED_FEATURE_MAP_V2 = {
    "total_phosphorus": "wq_tp",
    "total_nitrogen": "wq_tn",
    "dissolved_oxygen": "wq_do",
    "pH": "wq_ph",
    "ammonia_nitrogen": "wq_nh4_n",
    "chlorophyll_a": "wq_chla",  # MEE 为 μg/L；训练面板回填后 wq_chla 同为 μg/L 口径，直喂
    "water_temperature": "wq_water_temp",  # MEE 为 ℃；训练面板 ERA5 湖表温度同为 ℃，直喂
}
# wq_chla 单位对齐（2026-09-11 面板重建后）：训练面板 wq_chla 由 label_chla_ug_l
# 同源回填，口径为 μg/L；推理时 MEE 实测（μg/L）直接进入特征，不再 ÷1000。
# 此前的 μg/L→mg/L 换算把逐站叶绿素压到训练分布之外（训练列恒为常数中位数），
# 是"79 站输入不同、预测同值"的直接根因之一。其它水质特征训练/推理同为 mg/L，无需换算。
UNIT_CONVERTED_FEATURES: dict[str, tuple[str, str, float]] = {}

V3_SENSITIVITY_FEATURES: tuple[tuple[str, str], ...] = (
    ("wq_tp", "总磷"),
    ("wq_tn", "总氮"),
    ("wq_nh4_n", "氨氮"),
    ("wq_do", "溶解氧"),
    ("wq_ph", "pH"),
    ("wq_chla", "叶绿素 a"),
    ("wq_water_temp", "水温"),
    ("met_air_temperature_c", "气温"),
    ("met_shortwave_radiation_wm2", "光照"),
    ("hydro_water_level_m", "水位"),
)

# ---------------------------------------------------------------- 不确定性合同
# 区间按三层独立报告，禁止用单一布尔量把三层含义压成一句"校准有效"：
#   ① structural_valid  —— 上下界自洽（点预测落在区间内、非零宽、有限）
#   ② calibration_evidence —— 冻结测试集是否提供足够经验覆盖率证据
#   ③ decision_usable   —— 是否足以支撑页面展示与业务判断（= ① ∧ ②）
UNCERTAINTY_SEMANTICS = "prediction_interval_not_parameter_confidence_interval"

# 经验覆盖率的最小测试样本量：低于该阈值（尤其 test_n=0/1）时覆盖率非 0 即 1，
# 不构成校准证据，不得判定为"校准有效"。T5-chla test_n=1、T3/T4 test_n=0 均属此列。
MIN_CALIBRATION_TEST_N = 15

# 区间覆盖率的验收线：标称 90% 预测区间在留出段的实测经验覆盖率允许有限样本容差（2 个百分点，
# 约合 n≈117 时的一个二项标准误），低于 88% 即判定欠覆盖。
# 只有"结构自洽 ∧ 样本充分 ∧ 覆盖率有记录 ∧ 覆盖率达标"四条同时成立才允许
# decision_usable=true。此前只查了前两条与"覆盖率非空"，于是 T+1（80.30%）、
# T+90（85.47%）这种明显欠覆盖的区间也被标成"决策可用"——那是不成立的判定。
COVERAGE_TARGET = 0.90
COVERAGE_TOLERANCE = 0.02
COVERAGE_ACCEPTANCE_MIN = round(COVERAGE_TARGET - COVERAGE_TOLERANCE, 6)

# 校准状态枚举（写进 uncertainty.calibration_status）
CALIBRATION_VALIDATED = "validated"
CALIBRATION_UNDERCOVERED = "undercovered"
CALIBRATION_NO_TEST_EVIDENCE = "no_test_evidence"
CALIBRATION_INSUFFICIENT_TEST_EVIDENCE = "insufficient_test_evidence"
# 单一类别测试段（审计整改 2026-09-12）：二分类/概率任务的独立测试段只含正例或只含
# 负例时，无论覆盖率多高都只反映该类覆盖，不构成事件判别力或概率校准证据。
CALIBRATION_SINGLE_CLASS_TEST = "single_class_test"
CALIBRATION_UNAVAILABLE = "unavailable"

CALIBRATION_STATUS_LABELS = {
    CALIBRATION_VALIDATED: "经验覆盖率已由留出段核算且达到验收线",
    CALIBRATION_UNDERCOVERED: "留出段经验覆盖率低于验收线，区间宽度不足以覆盖实际误差",
    CALIBRATION_NO_TEST_EVIDENCE: "冻结测试集无该任务标签，经验覆盖率无法核算",
    CALIBRATION_INSUFFICIENT_TEST_EVIDENCE: "冻结测试集样本过少，经验覆盖率不具统计意义",
    CALIBRATION_SINGLE_CLASS_TEST: "独立测试段只含单一类别样本，覆盖率不构成判别力证据，仅反映该类覆盖",
    CALIBRATION_UNAVAILABLE: "该任务未提供 conformal 区间",
}


def _calibration_verdict(
    empirical_coverage: Any, test_n: Any, *, source_label: str,
    class_support: dict[str, Any] | None = None,
) -> tuple[str, str, float | None]:
    """统一的覆盖率验收判定（模型区间与季节基线区间共用同一条规则）。

    返回 (status, reason, coverage_gap)。四步顺序不可交换：
      ① 无测试样本        → no_test_evidence
      ② 样本少于阈值      → insufficient_test_evidence
      ③ 覆盖率未核算      → insufficient_test_evidence（"没算过"不等于"算过了且合格"）
      ④ 覆盖率低于验收线  → undercovered
    class_support（审计整改 2026-09-12）：二分类/概率任务须同时提供测试段正负例
    支持；单一类别测试段无论覆盖率多高都只反映该类覆盖 → single_class_test。
    """
    if test_n is None or (isinstance(test_n, (int, float)) and not isinstance(test_n, bool) and int(test_n) == 0):
        return CALIBRATION_NO_TEST_EVIDENCE, CALIBRATION_STATUS_LABELS[CALIBRATION_NO_TEST_EVIDENCE], None
    if not isinstance(test_n, (int, float)) or isinstance(test_n, bool):
        return (
            CALIBRATION_INSUFFICIENT_TEST_EVIDENCE,
            f"{CALIBRATION_STATUS_LABELS[CALIBRATION_INSUFFICIENT_TEST_EVIDENCE]}（test_n 缺失）",
            None,
        )
    n = int(test_n)
    if n < MIN_CALIBRATION_TEST_N:
        return (
            CALIBRATION_INSUFFICIENT_TEST_EVIDENCE,
            f"{CALIBRATION_STATUS_LABELS[CALIBRATION_INSUFFICIENT_TEST_EVIDENCE]}"
            f"（test_n={n}，阈值 {MIN_CALIBRATION_TEST_N}）",
            None,
        )
    if class_support is not None and class_support.get("applicable"):
        pos = class_support.get("test_positive_n")
        neg = class_support.get("test_negative_n")
        if not class_support.get("class_support_sufficient"):
            return (
                CALIBRATION_SINGLE_CLASS_TEST,
                f"{CALIBRATION_STATUS_LABELS[CALIBRATION_SINGLE_CLASS_TEST]}"
                f"（正例 {pos if pos is not None else '—'}、负例 {neg if neg is not None else '—'}，n={n}）",
                None,
            )
    if empirical_coverage is None or isinstance(empirical_coverage, bool):
        return (
            CALIBRATION_INSUFFICIENT_TEST_EVIDENCE,
            f"{source_label}未核算经验覆盖率，无法判定区间是否达标（test_n={n}）",
            None,
        )
    try:
        coverage = float(empirical_coverage)
    except (TypeError, ValueError):
        return CALIBRATION_INSUFFICIENT_TEST_EVIDENCE, f"{source_label}经验覆盖率不是数值", None
    gap = coverage - COVERAGE_ACCEPTANCE_MIN
    if gap < 0:
        return (
            CALIBRATION_UNDERCOVERED,
            f"{CALIBRATION_STATUS_LABELS[CALIBRATION_UNDERCOVERED]}"
            f"（留出段经验覆盖率 {coverage:.2%} < 验收线 {COVERAGE_ACCEPTANCE_MIN:.0%}"
            f"（标称 {COVERAGE_TARGET:.0%} − 容差 {COVERAGE_TOLERANCE:.0%}），"
            f"缺口 {abs(gap):.2%}，n={n}）",
            gap,
        )
    return (
        CALIBRATION_VALIDATED,
        f"留出段经验覆盖率 {coverage:.2%} 达标"
        f"（验收线 {COVERAGE_ACCEPTANCE_MIN:.0%} = 标称 {COVERAGE_TARGET:.0%} − 容差 "
        f"{COVERAGE_TOLERANCE:.0%}，n={n}）",
        gap,
    )

# ---------------------------------------------------------------- 季节气候态基线
# 中长期（30/60 天）在真实标签上不存在可训练的逐站模型（历史面板为季度采样，
# offset=1/2 与季度网格不同余，标签配对为空）。唯一能在真实数据上成立的回退是
# 按目标月的历史同期值。产物路径/版本与训练侧 modeling_real.seasonal_climatology 对齐，
# 版本不符即视为不可用（不猜测新字段语义）。
SEASONAL_CLIMATOLOGY_PATH_FRAGMENT = "evaluation/seasonal_climatology.json"

# 口径标签（API 披露字段，前端不消费；锁定语义不变，仅表述与事实对齐）。
# 30/60/90 天此前统称"情景推演"，现在这三档有真实来源与留出回测（90 天为逐站模型、
# 30/60 天为季节气候态基线），沿用旧称会低报证据强度；但"不得当作逐站实测预测"
# 的边界依旧成立，故 locked 保持 True，并把粒度写进标签本身。
LONG_TERM_COMPLIANCE_LABEL = "中长期月度趋势"
SHORT_TERM_COMPLIANCE_LABEL = "短期预测（月度标签粒度）"
SEASONAL_CLIMATOLOGY_VERSION = "seasonal_climatology_v4"
SEASONAL_CLIMATOLOGY_PROTOCOL = "seasonal_climatology_baseline_v1"

# 中长期交付路由策略（写进中长期结果的 long_term_route，供页面与验收引用）
LONG_TERM_ROUTE_POLICY = (
    "① 评估充分的模型（留出测试样本 ≥ "
    f"{MIN_CALIBRATION_TEST_N}）→ ② 有留出评估的季节气候态基线 → ③ 明确不可用；"
    "模型文件存在但评估样本不足时不作为交付口径"
)


def _count_origin(counts: dict[str, int], item: dict[str, Any]) -> None:
    """把一个任务结果归入来源桶。

    季节气候态基线必须单列，不得混进 real_data_v0_3：它是真实数据派生的历史同期值，
    但没有站点分辨、不是训练模型输出。混进去会把"全湖同值"低报成"逐站模型输出"，
    而来源桶正是页面上唯一能区分这两者的地方。
    """
    if item.get("value") is None or item.get("status") == "not_applicable":
        counts["not_applicable"] += 1
    elif item.get("value_origin") == "legacy_v0_2_synthetic_fallback":
        counts["legacy_v0_2_synthetic_fallback"] += 1
    elif item.get("value_origin") == "seasonal_climatology_baseline":
        counts["seasonal_climatology_baseline"] += 1
    elif item.get("value_origin") == "derived_from_chla_v0_3_risk_bands":
        counts["derived_from_chla"] += 1
    elif item.get("value_origin") == "derived_from_monthly_retrieval_field":
        # 月度反演基底边界面积：真实反演产物派生，但不是逐站训练模型输出，单列披露
        counts["derived_from_retrieval_field"] += 1
    else:
        counts["real_data_v0_3"] += 1

# ---------------------------------------------------------------- 输入指纹合同
# 两类指纹必须同时保存，二者证明的事情不同：
#   observed_input_fingerprint    —— 站点实测原文是否随实体变化
#   transformed_model_input_fingerprint —— 模型最终接收的矩阵是否随实体/时效变化
# 后者覆盖缺失标记、中位数插补、列序与具体 bundle，是"模型输入是否真的不同"的唯一凭据。
FINGERPRINT_SCHEMA = "dual_fingerprint_v1"


class AlgorithmModelServiceV3:
    """V0.3 真实数据模型族运行适配层（月度标签粒度 + conformal 区间 + 动态门禁）。"""

    def __init__(self, realtime_provider: Any, package_dir: Path | str | None = None,
                 legacy_service: Any = None) -> None:
        self.package_dir = Path(package_dir or V3_PACKAGE_DIR).resolve()
        self.realtime = realtime_provider
        self.legacy = legacy_service
        self._bundles: dict[tuple[str, str, int], Any] = {}
        self._context_frame: Any = None
        self._feature_scales: dict[str, float] | None = None
        self._load_lock = threading.RLock()
        # 实测快照内的热点缓存。热启动单次 predict_suite 约 4.6s，其中真正的
        # bundle 推理不足 0.4s，其余都是与实测快照绑定、可整批复用的周边计算：
        # legacy 回退 ~1.4s、局部敏感性解释 ~1.1s、实时输入 ~0.9s、机理分解 ~0.9s。
        # 缓存不改变任何计算口径，只在同一实测快照内复用，签名变化即整体失效。
        self._obs_cache: dict[str, tuple[dict[str, float], dict[str, Any]]] = {}
        self._mech_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._legacy_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self._legacy_inputs_cache: dict[str, tuple[dict[str, float], dict[str, Any], dict[str, float]]] = {}
        self._explain_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        # 全湖汇总（summary 内部是全湖 pandas 聚合，实测约 1.0s）：站点批量预生成时
        # 逐站重算同一份聚合毫无意义，按实测快照签名缓存，不改变任何口径。
        self._summary_cache: tuple[Any, dict[str, Any]] | None = None
        # 初值用唯一哨兵对象，保证首次调用必然触发一次对齐。
        self._cache_epoch_key: Any = object()
        # 世代序号：每次实测快照（或实时数据源实例）变化 +1。所有缓存读取前都必须
        # 先经 _cache_epoch() 对齐，否则会把上一世代的聚合结果留给新数据（曾出现
        # 替换实时源后机理分解仍返回旧氨氮 0.0646 的隔离缺口）。
        self._cache_epoch_serial: int = 0
        self._epoch_provider: Any = realtime_provider
        # bundle 文件哈希缓存：键 = (路径, 大小, mtime_ns)，只在文件真正变化时重算 SHA256
        self._artifact_hash_cache: dict[tuple[str, int, int], str] = {}

    def _realtime_signature(self) -> Any:
        """实测目录签名（status.json 的 mtime+size）。

        实测目录每次成功发布都会重写 status.json，因此该签名与
        「最新实测快照」同生命周期，且读取成本远低于 summary() 的全量 pandas 计算。
        """
        getter = getattr(self.realtime, "catalog_signature", None)
        if callable(getter):
            try:
                return getter()
            except Exception:  # noqa: BLE001 — 签名不可得时退化为逐次计算，不影响正确性
                return None
        try:
            return self.realtime.summary().get("latest_snapshot_id")
        except Exception:  # noqa: BLE001
            return None

    def _cache_epoch(self) -> int:
        """把缓存对齐到当前实测快照：签名变化即整体失效，绝不把旧快照的预测喂给新数据。

        同时把实时数据源本身的实例身份纳入判据：测试或运维替换 provider（即使新源
        恰好回报同一个 snapshot_id）也必须整体失效，否则缓存会跨数据源串味。
        返回当前世代序号，调用方可据此构造带世代的缓存键。
        """
        signature = self._realtime_signature()
        provider = self.realtime
        if provider is not self._epoch_provider or signature != self._cache_epoch_key:
            with self._load_lock:
                if provider is not self._epoch_provider or signature != self._cache_epoch_key:
                    self._obs_cache.clear()
                    self._mech_cache.clear()
                    self._legacy_cache.clear()
                    self._legacy_inputs_cache.clear()
                    self._explain_cache.clear()
                    self._summary_cache = None
                    self._cache_epoch_key = signature
                    self._epoch_provider = provider
                    self._cache_epoch_serial += 1
        return self._cache_epoch_serial

    def _realtime_summary(self) -> dict[str, Any]:
        """全湖实时汇总，按实测快照签名缓存（同一快照内结果必然相同）。"""
        epoch = self._cache_epoch()
        cached = self._summary_cache
        if cached is not None and cached[0] == epoch:
            return cached[1]
        summary = self.realtime.summary()
        self._summary_cache = (self._cache_epoch(), summary)
        return summary

    def cache_stats(self) -> dict[str, int]:
        """缓存规模（运维与验收观测用，不参与业务口径）。"""
        return {
            "observed_inputs": len(self._obs_cache),
            "mechanism_drivers": len(self._mech_cache),
            "legacy_fallback": len(self._legacy_cache),
            "legacy_inputs": len(self._legacy_inputs_cache),
            "explainability": len(self._explain_cache),
        }

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

    def _model_artifacts(self) -> dict[str, Any]:
        """模型产物摘要：manifest 摘要 + bundle 哈希集合 + 训练数据/预处理器版本。

        预测快照的版本键必须包含这些内容，否则"同一版本号下替换模型文件"不会让旧快照
        自动失效（这是本轮要求修补的缺口）。bundle 哈希按 (size, mtime_ns) 缓存，
        只在文件真正变化时重算 SHA256。
        """
        manifest_path = self.package_dir / "manifest.json"
        try:
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        except OSError:
            manifest_sha = None

        bundle_hashes: dict[str, str] = {}
        for path in sorted(self.model_dir.glob("*.joblib")):
            try:
                stat = path.stat()
            except OSError:
                continue
            key = (str(path), stat.st_size, stat.st_mtime_ns)
            digest = self._artifact_hash_cache.get(key)
            if digest is None:
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    digest = "unreadable"
                self._artifact_hash_cache[key] = digest
            bundle_hashes[path.name] = digest
        bundle_digest = (
            hashlib.sha256(json.dumps(bundle_hashes, sort_keys=True).encode("utf-8")).hexdigest()
            if bundle_hashes else None
        )

        preprocessor_source = self.package_dir / "code" / "modeling_real" / "data_real.py"
        try:
            preprocessor_source_sha = hashlib.sha256(preprocessor_source.read_bytes()).hexdigest()
        except OSError:
            preprocessor_source_sha = None
        try:
            contract = (json.loads(manifest_path.read_text(encoding="utf-8")).get("feature_contract") or {})
        except Exception:  # noqa: BLE001
            contract = {}

        return {
            "manifest_sha256": manifest_sha,
            "bundle_hashes": bundle_hashes,
            "bundle_digest": bundle_digest,
            "bundle_count": len(bundle_hashes),
            # 训练数据版本 + 预处理器版本：同版本号下替换模型文件/预处理器也必须换代
            "training_data_version": DATA_VERSION_V3,
            "preprocessor": {
                "implementation": "RealPreprocessor(train_median_fillna + missing_indicator)",
                "source_sha256": preprocessor_source_sha,
                "feature_contract_version": contract.get("version"),
                "feature_contract_sha256": contract.get("sha256"),
            },
        }

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
                RISK_BANDS_UG_L,
                SCENARIO_HORIZONS_V3,
            )
            from modeling_real.data_real import load_bundle
        except Exception as exc:  # noqa: BLE001
            raise AlgorithmModelUnavailable(f"V0.3 模型运行依赖不可用: {exc}") from exc
        return (
            pd,
            load_bundle,
            HORIZON_MAP_V3,
            SCENARIO_HORIZONS_V3,
            HORIZON_GRANULARITY_TIER_V3,
            FEATURE_COLUMNS_V2,
            RISK_BANDS_UG_L,
        )

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
        # wq_water_temp 不在冻结 78 列契约内（serving 子契约扩展列），显式放行
        allowed = set(FEATURE_COLUMNS_V2) | {"wq_water_temp"}
        return {name: float(row[name]) for name in frame.columns if name in allowed and pd.notna(row[name])}

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
        protocol_counts: dict[str, int] = {}
        for model in manifest.get("models", []):
            protocol = (model.get("uncertainty") or {}).get("split_protocol") or "frozen_split"
            protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1
        return {
            "status": "ready" if ready else "unavailable",
            "package_generation": "v0_3",
            "package_version": str(manifest.get("version")),
            "model_count": len(files),
            "expected_model_count": expected,
            "training_protocols": protocol_counts,
            "horizons": list(manifest.get("horizons", SUPPORTED_HORIZONS)),
            "training_window": "2005-02..2026-08（按时间冻结划分 train≤2021 / val 2022-2023 / test≥2024）",
            "data_version": manifest.get("data_version"),
            "claim_boundary": manifest.get("claim_boundary", CLAIM_BOUNDARY_V3),
            "feature_contract": manifest.get("feature_contract"),
            "feature_contract_mode": manifest.get("feature_contract_mode"),
            "serving_contract_note": manifest.get("serving_contract_note"),
            "granularity_tier": manifest.get("horizon_granularity_tier"),
            "granularity_disclosure": manifest.get("granularity_disclosure"),
            # 模型产物摘要：快照版本键据此判断"模型文件是否已变化"
            "model_artifacts": self._model_artifacts(),
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

    def _model_entry(
        self, task_id: str, variant: str, month_offset: int, horizon_days: int
    ) -> dict[str, Any] | None:
        """从 manifest 定位该 (任务, 变体, 月偏移, 时效) 的交付产物条目。

        为什么必须查清单而不是拼文件名（2026-09-11 修）：run_id 不含时效，
        "T5-chla-0m-s20260907-cv" 同时对应 T+1/3/7/15 四份文件；接口按 run_id 拼出
        "T5-chla-0m-s20260907-cv-1d.joblib" 在磁盘上根本不存在（真实名是
        "T5-chla-0m-s20260907-1d.joblib"）。清单里的 file/sha256 才是产物事实。
        """
        cached = getattr(self, "_model_index_cache", None)
        manifest = self._manifest()
        key = (task_id, variant, int(month_offset), int(horizon_days))
        if cached is None or cached[0] is not manifest.get("generated_at"):
            index: dict[tuple[str, str, int, int], dict[str, Any]] = {}
            for entry in manifest.get("models") or []:
                etask = entry.get("task_id")
                evariant = entry.get("variant")
                if not etask or not evariant:
                    # 旧清单无显式任务字段：从 run_id 前缀解析（T5-chla-0m-s20260907[-cv]）
                    parts = str(entry.get("run_id") or "").rsplit("-s", 1)[0].split("-")
                    if len(parts) < 3:
                        continue
                    etask, evariant = parts[0], parts[1]
                if entry.get("month_offset") is None or entry.get("horizon_days") is None:
                    continue
                index[(etask, evariant, int(entry["month_offset"]), int(entry["horizon_days"]))] = entry
            self._model_index_cache = (manifest.get("generated_at"), index)
            cached = self._model_index_cache
        return cached[1].get(key)

    def _model_artifact_meta(
        self, task_id: str, variant: str, month_offset: int, horizon_days: int
    ) -> dict[str, Any]:
        """清单里的真实产物身份：artifact_id / 相对路径 / SHA256 / 协议。缺字段即空值。"""
        entry = self._model_entry(task_id, variant, month_offset, horizon_days)
        if entry is None:
            return {}
        relative = entry.get("file")
        return {
            "artifact_id": entry.get("artifact_id"),
            "model_file": (
                str(relative).split("/")[-1] if relative else None
            ),
            "model_file_path": relative,
            "model_sha256": entry.get("sha256"),
            "protocol": entry.get("protocol"),
        }

    def _bundle(self, task_id: str, variant: str, month_offset: int, horizon_days: int) -> Any:
        key = (task_id, variant, month_offset, horizon_days)
        cached = self._bundles.get(key)
        if cached is not None:
            return cached
        with self._load_lock:
            cached = self._bundles.get(key)
            if cached is not None:
                return cached
            _, load_bundle, _, _, _, _, _ = self._runtime_imports()
            entry = self._model_entry(task_id, variant, month_offset, horizon_days)
            if entry is None or not entry.get("file"):
                return None
            path = self.package_dir / entry["file"]
            if not path.is_file():
                return None
            try:
                # 与 legacy loader 相同：joblib 反序列化旧 NumPy 数组时会触发 NumPy 2.5
                # shape 弃用警告；模型内容不变，而测试策略会将所有警告升级为异常。
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="Setting the shape on a NumPy array has been deprecated.*",
                        category=DeprecationWarning,
                    )
                    bundle = load_bundle(path)
            except Exception as exc:  # noqa: BLE001 — 损坏 bundle 归一为包不可用（409），不让调用方收到 500
                raise AlgorithmModelUnavailable(f"V0.3 模型加载失败 {path.name}: {exc}") from exc
            self._bundles[key] = bundle
            return bundle

    def model_artifact_audit(self) -> dict[str, Any]:
        """门禁—模型文件—线上预测的一一对应核查（验收证据）。

        逐条检查 manifest.models 声明的 file 是否真实存在、SHA256 是否与磁盘一致，
        以及 artifact_id 是否唯一覆盖 (task, variant, protocol, month_offset, horizon, seed)。
        """
        manifest = self._manifest()
        rows: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        missing_files: list[str] = []
        digest_mismatch: list[str] = []
        for entry in manifest.get("models") or []:
            relative = entry.get("file")
            artifact_id = entry.get("artifact_id")
            if artifact_id:
                seen[artifact_id] = seen.get(artifact_id, 0) + 1
            exists = False
            actual_sha = None
            if relative:
                path = self.package_dir / relative
                exists = path.is_file()
                if exists:
                    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    missing_files.append(str(relative))
            declared_sha = entry.get("sha256")
            if declared_sha and actual_sha and declared_sha != actual_sha:
                digest_mismatch.append(str(relative))
            rows.append({
                "task_id": entry.get("task_id"),
                "variant": entry.get("variant"),
                "horizon_days": entry.get("horizon_days"),
                "month_offset": entry.get("month_offset"),
                "run_id": entry.get("run_id"),
                "artifact_id": artifact_id,
                "file": relative,
                "file_exists": exists,
                "sha256_matches": bool(declared_sha and actual_sha and declared_sha == actual_sha),
            })
        duplicated = sorted([key for key, count in seen.items() if count > 1])
        total = len(rows)
        return {
            "checked": total,
            "artifact_id_present": len(seen),
            "artifact_id_unique": not duplicated,
            "duplicated_artifact_ids": duplicated,
            "missing_files": missing_files,
            "sha256_mismatch": digest_mismatch,
            "status": "PASS" if (
                total and not missing_files and not digest_mismatch and not duplicated
            ) else "FAIL",
            "rule": (
                "API 只返回清单里的真实 file 与 sha256；artifact_id 必须唯一标识"
                "(task, variant, protocol, month_offset, horizon, seed)。"
            ),
            "rows": rows,
        }

    def _observed_inputs_v2(self, entity_id: str) -> tuple[dict[str, float], dict[str, Any]]:
        """同一实测快照内按实体复用：summary() 是全湖 pandas 聚合，重复调用纯属浪费。"""
        self._cache_epoch()
        cached = self._obs_cache.get(entity_id)
        if cached is not None:
            return dict(cached[0]), dict(cached[1])
        observed, scope_context = self._observed_inputs_v2_uncached(entity_id)
        self._obs_cache[entity_id] = (dict(observed), dict(scope_context))
        return observed, scope_context

    def _observed_inputs_v2_uncached(self, entity_id: str) -> tuple[dict[str, float], dict[str, Any]]:
        summary = self._realtime_summary()
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

    def _monthly_field_area_result(self, horizon_days: int) -> dict[str, Any] | None:
        """月度反演基底场的水华边界面积（全湖量，公示口径）。

        面积 = 最新月度校准场按 20 μg/L 阈值分割的边界区域面积（rs_overlays 预计算）。
        它是"当前月度水华面积现值"，不随预测时效外推；30/60/90 天仍属情景口径。
        """
        try:
            raster = RasterFieldService().get_raster_layer()
        except Exception:  # noqa: BLE001 — 栅格缺失时回到 legacy 合成回退
            return None
        boundary = raster.get("boundary") or {}
        area = boundary.get("area_km2")
        if not isinstance(area, (int, float)) or isinstance(area, bool) or area <= 0:
            return None
        scenario = horizon_days >= 30
        return {
            "task_id": "T2",
            "variant": "area",
            "label": "水华面积",
            "value": round(float(area), 4),
            "probability": None,
            "predicted_class": None,
            "target": "area",
            "unit": "km²",
            "status": "ok",
            "value_origin": "derived_from_monthly_retrieval_field",
            "value_origin_note": (
                "月度反演重建基底场按 "
                f"{boundary.get('threshold_ug_l') or 20} μg/L 阈值分割的边界面积（{raster.get('month')} 月场）；"
                "月度现值口径，不随预测时效外推"
            ),
            "issued_month": raster.get("month"),
            "boundary_threshold_ug_l": boundary.get("threshold_ug_l"),
            "model_file": None,
            "model_run_id": None,
            "selected_family": None,
            "model_family": None,
            "static_baseline_model": False,
            "granularity_tier": "month_retrieval_base",
            "label_provenance": "derived_from_calibrated_retrieval_field",
            "status_note": "全湖量指标：不逐站变化，不作站点间比较",
            "training_protocol": None,
            "uncertainty": None,
            "uncertainty_available": False,
            "compliance": {
                "label": LONG_TERM_COMPLIANCE_LABEL if scenario else "月度反演基底",
                "locked": scenario,
                "granularity_tier": "month_retrieval_base",
            },
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
    def _calendar_features(observed_at: str | None, month_shift: int = 0) -> dict[str, float]:
        """日历正余弦；month_shift>0 时取「签发月 + shift」的目标月季节（与训练侧一致）。"""
        if not observed_at:
            return {}
        try:
            dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return {}
        month = ((dt.month - 1 + int(month_shift)) % 12) + 1
        angle = 2 * math.pi * (month - 1) / 12.0
        return {"calendar_month_sin": math.sin(angle), "calendar_month_cos": math.cos(angle)}

    @staticmethod
    def _target_month(observed_at: str | None, month_shift: int = 0) -> int | None:
        """签发时刻 + 月偏移对应的目标月份（1-12）；无签发时刻时返回 None。"""
        if not observed_at:
            return None
        try:
            dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        return ((dt.month - 1 + int(month_shift)) % 12) + 1

    @staticmethod
    def _clip_interval(value: float, output_key: str, *, lower: bool) -> float:
        """按输出物理边界裁剪区间端点（与 _build_uncertainty 同一裁剪口径）。"""
        bounded_upper = output_key in {"bloom", "coverage", "density", "probability", "spatial"}
        if lower:
            return float(max(value, 0.0))
        return float(min(value, 1.0)) if bounded_upper else float(value)

    # -------------------------------------------------------- 双指纹（P0.5）
    @staticmethod
    def _observed_fingerprint(observed: dict[str, float]) -> str:
        """站点实测原文指纹：证明"站点观测确实不同"，但不证明模型最终输入不同。"""
        return hashlib.sha1(
            json.dumps({k: observed[k] for k in sorted(observed)}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

    def _transformed_fingerprint(self, bundle: Any, frame: Any) -> str | None:
        """模型实际接收的变换后输入矩阵指纹。

        覆盖「原始行 → 预处理器 transform（缺失标记 + 训练期中位数插补）→ 最终列序」，
        因此它才是"该 bundle 在该时效上看到的输入是否随实体变化"的凭据。
        按模型/指标/时效分别计算（调用方各自传入自己的 bundle 与 frame）。
        """
        try:
            transformed = bundle.preprocessor.transform(frame)
        except Exception:  # noqa: BLE001 — 指纹不可得不应使预测失败
            return None
        try:
            from modeling_real.data_real import frame_digest

            return str(frame_digest(transformed))[:16]
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------- 不确定性三层合同
    def _build_uncertainty(
        self, bundle: Any, value: Any, output_key: str, training_protocol: str
    ) -> dict[str, Any] | None:
        """conformal 区间 → 三层结论（结构自洽 / 校准证据 / 决策可用）。

        predict_suite 与 predict_suite_batch 共用本函数，保证两条路径给出一致结论。
        """
        if bundle.intervals is None:
            return None
        point = float(value) if value is not None else 0.0
        raw_p05 = point + bundle.intervals.residual_p05
        raw_p95 = point + bundle.intervals.residual_p95
        lower_bound = 0.0
        upper_bound = 1.0 if output_key in {"bloom", "coverage", "density", "probability", "spatial"} else None
        p05 = max(raw_p05, lower_bound)
        p95 = min(raw_p95, upper_bound) if upper_bound is not None else raw_p95

        # ① 结构自洽：与模型判别力、校准证据无关，只回答"这组上下界本身是否成立"。
        finite = bool(math.isfinite(float(p05)) and math.isfinite(float(p95)))
        point_in_interval = bool(
            value is not None and finite and float(p05) - 1e-12 <= float(value) <= float(p95) + 1e-12
        )
        degenerate = bool(finite and float(p05) == float(p95))
        structural_valid = bool(finite and point_in_interval and not degenerate)
        structural_reason = None
        if not finite:
            structural_reason = "区间上下界非有限值，无法作为区间解读"
        elif degenerate:
            structural_reason = (
                "区间宽度退化为 0（校准残差分位数恒为常数并被物理边界裁剪），该区间不具信息量"
            )
        elif not point_in_interval:
            structural_reason = "点预测落在预测区间之外，区间与点预测不自洽"

        # ② 校准证据：样本量足够 ∧ 经验覆盖率确实核算过 ∧ 覆盖率达到验收线。三条缺一不可。
        test_n_raw = bundle.uncertainty_meta.get("test_n")
        test_n = int(test_n_raw) if isinstance(test_n_raw, (int, float)) and not isinstance(test_n_raw, bool) else None
        empirical_coverage = bundle.uncertainty_meta.get("empirical_coverage_test")
        calibration_n = bundle.intervals.calibration_n
        calibration_status, calibration_reason, coverage_gap = _calibration_verdict(
            empirical_coverage, test_n, source_label="模型留出测试集",
        )

        calibration_evidence = {
            "status": calibration_status,
            "reason": calibration_reason,
            "calibration_n": calibration_n,
            "test_n": test_n,
            "empirical_coverage": empirical_coverage,
            "coverage_target": COVERAGE_TARGET,
            "coverage_tolerance": COVERAGE_TOLERANCE,
            "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
            "coverage_gap": coverage_gap,
            "min_test_n": MIN_CALIBRATION_TEST_N,
        }
        calibration_ok = calibration_status == CALIBRATION_VALIDATED

        # ③ 决策可用：结构自洽 ∧ 校准证据充分。任一不满足即不得作为决策依据展示。
        decision_usable = bool(structural_valid and calibration_ok)
        if not structural_valid:
            decision_reason = structural_reason
        elif not calibration_ok:
            decision_reason = calibration_reason
        else:
            decision_reason = None

        return {
            "method": "split_conformal_residual_quantiles",
            # 语义声明：这是"单次预测"的预测区间，不是参数置信区间。
            "is_prediction_interval": True,
            "interval_semantics": UNCERTAINTY_SEMANTICS,
            "p05": _json_scalar(p05),
            "p95": _json_scalar(p95),
            "point_value": _json_scalar(value),
            # ① 结构层
            "structural_valid": structural_valid,
            "structural_reason": structural_reason,
            # ② 校准证据层
            "calibration_status": calibration_status,
            "calibration_evidence": calibration_evidence,
            "test_n": test_n,
            "empirical_coverage": empirical_coverage,
            "calibration_n": calibration_n,
            # ③ 决策层
            "decision_usable": decision_usable,
            "decision_reason": decision_reason,
            # 兼容字段：区间自洽性结论（等价于 structural_valid），页面与旧消费者继续可用
            "interval_valid": structural_valid,
            "interval_degenerate": degenerate,
            "point_in_interval": point_in_interval,
            "invalid_reason": structural_reason or (None if calibration_ok else calibration_reason),
            "bounds": {"lower": lower_bound, "upper": upper_bound},
            "clipped_to_physical_bounds": bool(p05 != raw_p05 or p95 != raw_p95),
            "training_protocol": training_protocol,
            "coverage": {
                "target": COVERAGE_TARGET,
                "acceptance_min": COVERAGE_ACCEPTANCE_MIN,
                "gap": coverage_gap,
                "calibration_n": calibration_n,
                "empirical_coverage_test": empirical_coverage,
                "test_n": test_n,
            },
        }

    def predict_suite(self, horizon_days: int, entity_id: str = "lake", focus_metric: str = "risk",
                      *, explain: bool = True) -> dict[str, Any]:
        """explain=False 用于批量预生成：局部敏感性要额外跑约 19 次推理，
        而预测快照并不承载解释（解释与 focus_metric 绑定），批量生成时可安全跳过。"""
        pd, _, horizon_map, scenario_horizons, tiers, _, risk_bands = self._runtime_imports()
        # 先把热点缓存对齐到当前实测快照，保证同一次推理内的输入、机理与解释同源。
        self._cache_epoch()
        if horizon_days not in horizon_map.month_map:
            raise ValueError(f"horizon_days must be one of {sorted(horizon_map.month_map)}")
        month_offset = horizon_map.month_offset(horizon_days)
        tier = tiers[horizon_days]
        focus_map = {"risk": "probability", "chla": "chla", "area": "area", "biomass": "biomass", "density": "density"}
        if focus_metric not in focus_map:
            raise ValueError(f"focus_metric must be one of {sorted(focus_map)}")
        manifest = self._manifest()
        # 各 bundle 的留出测试集指标（roc_auc / pr_auc / n 等）随交付包冻结，用于在结果侧
        # 如实披露模型判别力：ROC AUC 接近 0.5 的模型不具备站点区分能力，不得被当作有效依据。
        model_quality = {
            entry.get("run_id"): {
                "selected_family": entry.get("selected_family"),
                "test_metrics": entry.get("test_metrics"),
                "validation_metrics": entry.get("validation_metrics"),
                "validation_metric_source": entry.get("validation_metric_source"),
                "train_rows": entry.get("train_rows"),
                "test_rows": entry.get("test_rows"),
            }
            for entry in (manifest.get("models") or [])
            if entry.get("run_id")
        }
        availability = {
            (entry["task_id"], entry["variant"]): entry
            for entry in manifest.get("availability_matrix", [])
            if entry.get("horizon_days") == horizon_days
        }
        observed, scope_context = self._observed_inputs_v2(entity_id)
        context = self._context()
        # 日历取「签发月 + 月偏移」的目标月：与训练侧 target-month 口径、以及批量站点
        # 路径（predict_suite_batch）一致。此前单实体路径漏传 month_shift，导致全湖卡片
        # 的 30/60/90 用签发月季节、站点聚合层用目标月季节，同一时效两套日历。
        calendar = self._calendar_features(scope_context.get("observed_at"), month_shift=month_offset)
        context = {**context, **calendar}
        legacy_box: dict[str, Any] = {}
        results: dict[str, Any] = {}
        all_feature_columns: set[str] = set()
        for output_key, task_id, variant, label in TASKS:
            compliance = {
                "label": LONG_TERM_COMPLIANCE_LABEL if horizon_days in scenario_horizons else SHORT_TERM_COMPLIANCE_LABEL,
                "locked": horizon_days in scenario_horizons,
                "granularity_tier": tier,
            }
            bundle = self._bundle(task_id, variant, month_offset, horizon_days)
            entry = availability.get((task_id, variant), {})
            # 中长期路由（2026-09-11）：文件存在 ≠ 可以交付。T+30/T+60 的持久性模型只有
            # 5 条留出测试样本，属 insufficient_test_evidence；按
            # 「评估充分的模型 → 有留出评估的季节基线 → 明确不可用」的顺序重选，
            # 不得因为"有模型文件"就把它的输出当成中长期趋势。
            route = self._long_term_route(
                task_id, variant, month_offset, horizon_days, bundle, scenario_horizons,
            )
            if route["use_bundle"]:
                route = None
            else:
                bundle = None
            if bundle is None:
                # 水华面积：无训练模型时改用「月度反演重建基底场 20μg/L 阈值边界的实测面积」
                # （面积本就是全湖量，不存在"逐站训练"问题），替代 V0.2 合成回退；
                # 栅格场缺失时才回退 legacy，且两种来源都如实标注。
                if output_key == "area":
                    field_area = self._monthly_field_area_result(horizon_days)
                    if field_area is not None:
                        results[output_key] = field_area
                        continue
                # 中长期（30/60/90 天）：不再用 V0.2 合成数据模型自动补位——合成结果
                # "看起来有站点差异"但无任何真实依据，只会被误读为真实趋势。
                # 先试真实季节气候态基线（历史同期值，可回测）；它也不适用才 not_applicable。
                clim_result = None
                if horizon_days in scenario_horizons:
                    clim_result = self._climatology_result(
                        task_id, variant, label, output_key, horizon_days, month_offset,
                        scope_context, compliance, entry,
                        route=route,
                        allow_any_scenario=bool(route and route.get("model_rejected")),
                    )
                if clim_result is not None:
                    results[output_key] = clim_result
                    continue
                fallback = None
                if horizon_days not in scenario_horizons:
                    fallback = self._legacy_fallback_result(
                        task_id, variant, horizon_days, output_key, label, entity_id, legacy_box
                    )
                if fallback is not None:
                    fallback["label_provenance"] = entry.get("label_provenance")
                    fallback["compliance"] = compliance
                    fallback["not_applicable_reason"] = entry.get("reason") or "model_bundle_missing"
                    results[output_key] = fallback
                else:
                    results[output_key] = {
                        "task_id": task_id, "variant": variant, "label": label,
                        "value": None, "probability": None, "unit": None,
                        "status": "not_applicable",
                        "value_origin": None,
                        "not_applicable_reason": (
                            (route or {}).get("reason")
                            or "scenario_horizon_synthetic_fallback_removed"
                            if horizon_days in scenario_horizons and not entry.get("reason")
                            else entry.get("reason") or "model_bundle_missing"
                        ),
                        "long_term_route": route,
                        "label_provenance": entry.get("label_provenance"),
                        "uncertainty_available": False,
                        "compliance": compliance,
                    }
                continue
            frame = self._raw_frame(pd, bundle, observed, context)
            raw = bundle.predict_point(frame).iloc[0].to_dict()
            value = _json_scalar(raw.get("prediction"))
            probability = _json_scalar(raw.get("probability"))
            predicted_class = None
            if bundle.problem_type in {"binary", "probability"} and probability is not None:
                # 概率任务的 value 语义 = 概率本身；0/1 分类决策另存 predicted_class。
                # 修正旧版把类别标签（如 0）当概率展示、导致风险得分恒为 0 的语义错误。
                predicted_class = value
                value = probability
            training_protocol = (bundle.uncertainty_meta or {}).get("split_protocol") or "frozen_split"
            uncertainty = self._build_uncertainty(bundle, value, output_key, training_protocol)
            transformed_fingerprint = self._transformed_fingerprint(bundle, frame)
            # 产物身份一律来自清单的真实记录（file / sha256 / artifact_id），不再用 run_id 拼名。
            artifact = self._model_artifact_meta(task_id, variant, month_offset, horizon_days)
            result = {
                "task_id": task_id,
                "variant": variant,
                "label": label,
                "value": value,
                "probability": probability,
                "predicted_class": predicted_class,
                "target": bundle.target,
                "unit": {
                    "area": "km²", "coverage": "ratio", "density": "rank",
                    "biomass": "mg/L", "chla": "μg/L", "probability": "ratio", "spatial": "ratio",
                }.get(output_key),
                "model_file": artifact.get("model_file"),
                "model_file_path": artifact.get("model_file_path"),
                "model_sha256": artifact.get("model_sha256"),
                "artifact_id": artifact.get("artifact_id"),
                "model_run_id": bundle.run_id,
                "selected_family": bundle.selected_family,
                # 静态基线模型（simple_baseline）不依赖输入，逐站点输出必然相同；
                # 此处只标注模型族事实，是否真的对站点无响应由快照层的实测离散度判定。
                "model_family": bundle.selected_family,
                "static_baseline_model": bundle.selected_family == "simple_baseline",
                "granularity_tier": bundle.granularity_tier,
                "label_provenance": entry.get("label_provenance"),
                "status": "ok",
                "value_origin": "v0_3_real_bundle",
                "training_protocol": training_protocol,
                "uncertainty": uncertainty,
                "uncertainty_available": uncertainty is not None,
                # 该 (任务, 时效) 下模型实际接收的输入矩阵指纹：证明"模型输入是否随实体变化"
                "transformed_model_input_fingerprint": transformed_fingerprint,
                "compliance": compliance,
            }
            if explain and output_key == focus_map[focus_metric]:
                # 局部敏感性要额外跑 ~19 次 bundle 推理，是单次 predict_suite 的大头；
                # 输入仅由 (任务, 实体, 时效, 实测快照) 决定，因此按同一键复用。
                explain_key = (output_key, entity_id, month_offset, horizon_days)
                explainability = self._explain_cache.get(explain_key)
                if explainability is None:
                    explainability = self._explain(bundle, frame, observed)
                    self._explain_cache[explain_key] = explainability
                result["explainability"] = explainability
            results[output_key] = result
            all_feature_columns.update(bundle.feature_columns)
        # 风险等级：训练期标签单类，无独立可训练模型；由 T5 叶绿素 a 真实数据模型（公示代理标签）预测值按
        # 冻结风险带推导（与 20 μg/L 水华阈值同源），绝不伪造独立等级模型输出。
        # 推导不可行（无叶绿素值）时保留上方 legacy 回退或 not_applicable 原状。
        risk_level_result = results.get("risk_level") or {}
        if risk_level_result.get("value_origin") != "derived_from_chla_v0_3_risk_bands":
            derived = self._derive_risk_level(results.get("chla"), risk_bands)
            if derived is not None:
                derived["compliance"] = {
                    "label": LONG_TERM_COMPLIANCE_LABEL if horizon_days in scenario_horizons else SHORT_TERM_COMPLIANCE_LABEL,
                    "locked": horizon_days in scenario_horizons,
                    "granularity_tier": tier,
                }
                results["risk_level"] = derived
        origin_counts = {
            "real_data_v0_3": 0,
            "seasonal_climatology_baseline": 0,
            "derived_from_chla": 0,
            "derived_from_retrieval_field": 0,
            "legacy_v0_2_synthetic_fallback": 0,
            "not_applicable": 0,
        }
        for item in results.values():
            _count_origin(origin_counts, item)
        probability_result = results.get("probability") or {}
        probability_value = probability_result.get("probability")
        if probability_value is None:
            probability_value = probability_result.get("value")
        risk_score = round(float(probability_value) * 100, 1) if isinstance(probability_value, (int, float)) else None
        focus_result = results.get(focus_map[focus_metric]) or {}
        quality_gate = self._quality_gate(focus_result, origin_counts, focus_metric, horizon_days in scenario_horizons)
        # 双指纹：observed 证明"站点实测不同"，transformed 证明"模型最终输入矩阵不同"。
        observed_fingerprint = self._observed_fingerprint(observed)
        transformed_fingerprints = {
            key: item["transformed_model_input_fingerprint"]
            for key, item in results.items()
            if item.get("transformed_model_input_fingerprint")
        }
        # 顶层指纹必须随焦点指标切换：合成回退 / 无真实 bundle 的焦点任务没有
        # 真实模型输入矩阵，指纹必须显式置空并说明原因，而不是回落到别的任务的指纹。
        focus_fp = transformed_fingerprints.get(focus_map[focus_metric])
        if focus_fp:
            fp_unavailable_reason = None
        else:
            focus_origin = focus_result.get("value_origin") or focus_result.get("status")
            fp_unavailable_reason = {
                "legacy_v0_2_synthetic_fallback": "synthetic_fallback_no_real_model_inputs",
                "not_applicable": "no_real_bundle_for_task_horizon",
            }.get(focus_origin, "transformed_frame_not_recorded")
        return {
            "prediction_run_id": f"ALG-V0.3-{scope_context.get('snapshot_id') or 'no-snapshot'}-{entity_id}-{horizon_days}d",
            "entity_id": entity_id,
            # 兼容字段：等价于 observed_input_fingerprint（旧消费者仍可读）
            "input_fingerprint": observed_fingerprint,
            "fingerprint_schema": FINGERPRINT_SCHEMA,
            "observed_input_fingerprint": observed_fingerprint,
            "transformed_model_input_fingerprint": focus_fp,
            "transformed_model_input_fingerprint_unavailable_reason": fp_unavailable_reason,
            "transformed_model_input_fingerprints": transformed_fingerprints,
            "horizon_days": horizon_days,
            "month_offset": month_offset,
            "granularity_tier": tier,
            "granularity_disclosure": manifest.get("granularity_disclosure"),
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
            "mechanism_drivers": self._mechanism_drivers_cached(entity_id, observed, context),
            "quality_gate": quality_gate,
            # 按 model_run_id 索引的模型健康度（留出集指标），供结果侧如实披露判别力。
            "model_quality": model_quality,
        }

    def predict_suite_batch(
        self, horizon_days: int, entity_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """批量预测：同一 (task, variant, horizon) 的全部实体合并为一次推理。

        与逐实体 predict_suite 口径完全一致（同一 bundle、同一 frame 构造方式、同一
        conformal 区间、同一风险带推导与动态门禁），只把 N 次单行推理合并成一次 N 行
        推理。实测单行推理约 0.28s 而 20 行批量仅 0.20s，因此站点批量预生成由
        「每站点数十秒」降为毫秒级。

        不做局部敏感性解释：解释与 focus_metric 绑定且不随预测快照落盘。
        落盘的顶层指纹口径固定为 risk；快照 serve 时按请求的 focus_metric 重新解析
        顶层指纹（见 prediction_snapshot.assemble），前端也可直接读按任务的指纹表。
        """
        if not entity_ids:
            return {}
        pd, _, horizon_map, scenario_horizons, tiers, _, risk_bands = self._runtime_imports()
        if horizon_days not in horizon_map.month_map:
            raise ValueError(f"horizon_days must be one of {sorted(horizon_map.month_map)}")
        month_offset = horizon_map.month_offset(horizon_days)
        tier = tiers[horizon_days]
        is_scenario = horizon_days in scenario_horizons
        focus_map = {"risk": "probability", "chla": "chla", "area": "area", "biomass": "biomass", "density": "density"}
        self._cache_epoch()
        manifest = self._manifest()
        availability = {
            (entry["task_id"], entry["variant"]): entry
            for entry in manifest.get("availability_matrix", [])
            if entry.get("horizon_days") == horizon_days
        }
        base_context = self._context()
        observed_by_entity: dict[str, dict[str, float]] = {}
        context_by_entity: dict[str, dict[str, float]] = {}
        scopes: dict[str, dict[str, Any]] = {}
        for entity_id in entity_ids:
            observed, scope = self._observed_inputs_v2(entity_id)
            # month_offset≥1：日历取目标月季节（训练侧监督表同口径）
            calendar = self._calendar_features(scope.get("observed_at"), month_shift=month_offset)
            observed_by_entity[entity_id] = observed
            context_by_entity[entity_id] = {**base_context, **calendar}
            scopes[entity_id] = scope

        results_by_entity: dict[str, dict[str, Any]] = {entity_id: {} for entity_id in entity_ids}
        transformed_fingerprints_by_entity: dict[str, dict[str, str | None]] = {
            entity_id: {} for entity_id in entity_ids
        }
        legacy_box: dict[str, Any] = {}
        for output_key, task_id, variant, label in TASKS:
            compliance = {
                "label": LONG_TERM_COMPLIANCE_LABEL if is_scenario else SHORT_TERM_COMPLIANCE_LABEL,
                "locked": is_scenario,
                "granularity_tier": tier,
            }
            bundle = self._bundle(task_id, variant, month_offset, horizon_days)
            entry = availability.get((task_id, variant), {})
            # 中长期路由：与单条路径同一策略（评估不足的模型不作为交付口径）
            route = self._long_term_route(
                task_id, variant, month_offset, horizon_days, bundle, scenario_horizons,
            )
            if route["use_bundle"]:
                route = None
            else:
                bundle = None
            if bundle is None:
                # 水华面积：与单条口径一致，优先月度反演基底边界面积（见 _monthly_field_area_result）
                field_area = None
                if output_key == "area":
                    field_area = self._monthly_field_area_result(horizon_days)
                    if field_area is not None:
                        for entity_id in entity_ids:
                            results_by_entity[entity_id][output_key] = dict(field_area)
                if not (output_key == "area" and field_area is not None):
                    # 中长期（30/60/90 天）先试真实季节气候态基线（与单条路径同口径）；
                    # 该基线不含站点分辨，逐站取同一目标月值——这正是它必须被标注的原因。
                    if is_scenario:
                        for entity_id in entity_ids:
                            clim_result = self._climatology_result(
                                task_id, variant, label, output_key, horizon_days, month_offset,
                                scopes.get(entity_id) or {}, compliance, entry,
                                route=route,
                                allow_any_scenario=bool(route and route.get("model_rejected")),
                            )
                            if clim_result is not None:
                                results_by_entity[entity_id][output_key] = clim_result
                        if all(output_key in results_by_entity[eid] for eid in entity_ids):
                            continue
                    # 中长期不再用 V0.2 合成数据模型自动补位（与单条路径同口径）
                    bulk = {} if is_scenario else self._legacy_fallback_batch(
                        task_id, variant, horizon_days, output_key, label, entity_ids, legacy_box
                    )
                    for entity_id in entity_ids:
                        if output_key in results_by_entity[entity_id]:
                            continue
                        fallback = bulk.get(entity_id)
                        if fallback is not None:
                            fallback["label_provenance"] = entry.get("label_provenance")
                            fallback["compliance"] = compliance
                            fallback["not_applicable_reason"] = entry.get("reason") or "model_bundle_missing"
                            results_by_entity[entity_id][output_key] = fallback
                        else:
                            results_by_entity[entity_id][output_key] = {
                                "task_id": task_id, "variant": variant, "label": label,
                                "value": None, "probability": None, "unit": None,
                                "status": "not_applicable",
                                "value_origin": None,
                                "not_applicable_reason": (
                                    (route or {}).get("reason")
                                    or "scenario_horizon_synthetic_fallback_removed"
                                    if is_scenario and not entry.get("reason")
                                    else entry.get("reason") or "model_bundle_missing"
                                ),
                                "long_term_route": route,
                                "label_provenance": entry.get("label_provenance"),
                                "uncertainty_available": False,
                                "compliance": compliance,
                            }
                continue
            frames_by_entity = {
                eid: self._raw_frame(pd, bundle, observed_by_entity[eid], context_by_entity[eid])
                for eid in entity_ids
            }
            batch_frame = pd.concat([frames_by_entity[eid] for eid in entity_ids], ignore_index=True)
            raw_all = bundle.predict_point(batch_frame)
            training_protocol = (bundle.uncertainty_meta or {}).get("split_protocol") or "frozen_split"
            artifact = self._model_artifact_meta(task_id, variant, month_offset, horizon_days)
            unit_map = {
                "area": "km²", "coverage": "ratio", "density": "rank",
                "biomass": "mg/L", "chla": "μg/L", "probability": "ratio", "spatial": "ratio",
            }
            for index, entity_id in enumerate(entity_ids):
                raw = raw_all.iloc[index].to_dict()
                value = _json_scalar(raw.get("prediction"))
                probability = _json_scalar(raw.get("probability"))
                predicted_class = None
                if bundle.problem_type in {"binary", "probability"} and probability is not None:
                    predicted_class = value
                    value = probability
                uncertainty = self._build_uncertainty(bundle, value, output_key, training_protocol)
                transformed_fingerprints_by_entity[entity_id][output_key] = self._transformed_fingerprint(
                    bundle, frames_by_entity[entity_id]
                )
                results_by_entity[entity_id][output_key] = {
                    "task_id": task_id,
                    "variant": variant,
                    "label": label,
                    "value": value,
                    "probability": probability,
                    "predicted_class": predicted_class,
                    "target": bundle.target,
                    "unit": unit_map.get(output_key),
                    "model_file": artifact.get("model_file"),
                    "model_file_path": artifact.get("model_file_path"),
                    "model_sha256": artifact.get("model_sha256"),
                    "artifact_id": artifact.get("artifact_id"),
                    "model_run_id": bundle.run_id,
                    "selected_family": bundle.selected_family,
                    "model_family": bundle.selected_family,
                    "static_baseline_model": bundle.selected_family == "simple_baseline",
                    "granularity_tier": bundle.granularity_tier,
                    "label_provenance": entry.get("label_provenance"),
                    "status": "ok",
                    "value_origin": "v0_3_real_bundle",
                    "training_protocol": training_protocol,
                    "uncertainty": uncertainty,
                    "uncertainty_available": uncertainty is not None,
                    # 与 predict_suite 同口径：该 (任务, 时效) 下模型实际接收的输入矩阵指纹
                    "transformed_model_input_fingerprint": transformed_fingerprints_by_entity[entity_id][output_key],
                    "compliance": compliance,
                }

        # ---- 逐实体后置：风险等级推导、来源计数、风险得分与动态门禁 ----
        model_quality = {
            entry.get("run_id"): {
                "selected_family": entry.get("selected_family"),
                "test_metrics": entry.get("test_metrics"),
                "validation_metrics": entry.get("validation_metrics"),
                "validation_metric_source": entry.get("validation_metric_source"),
                "train_rows": entry.get("train_rows"),
                "test_rows": entry.get("test_rows"),
            }
            for entry in (manifest.get("models") or [])
            if entry.get("run_id")
        }
        assembled: dict[str, dict[str, Any]] = {}
        for entity_id in entity_ids:
            results = results_by_entity[entity_id]
            risk_level_result = results.get("risk_level") or {}
            if risk_level_result.get("value_origin") != "derived_from_chla_v0_3_risk_bands":
                derived = self._derive_risk_level(results.get("chla"), risk_bands)
                if derived is not None:
                    # 结果被风险带推导覆盖后，序数模型自身的输入指纹不再代表所呈现结果，
                    # 与单条路径同口径：不输出 risk_level 的指纹（derived 无模型输入）。
                    transformed_fingerprints_by_entity.get(entity_id, {}).pop("risk_level", None)
                if derived is not None:
                    derived["compliance"] = {
                        "label": LONG_TERM_COMPLIANCE_LABEL if is_scenario else SHORT_TERM_COMPLIANCE_LABEL,
                        "locked": is_scenario,
                        "granularity_tier": tier,
                    }
                    results["risk_level"] = derived
            origin_counts = {
                "real_data_v0_3": 0,
                "seasonal_climatology_baseline": 0,
                "derived_from_chla": 0,
                "derived_from_retrieval_field": 0,
                "legacy_v0_2_synthetic_fallback": 0,
                "not_applicable": 0,
            }
            for item in results.values():
                _count_origin(origin_counts, item)
            probability_result = results.get("probability") or {}
            probability_value = probability_result.get("probability")
            if probability_value is None:
                probability_value = probability_result.get("value")
            risk_score = round(float(probability_value) * 100, 1) if isinstance(probability_value, (int, float)) else None
            focus_result = results.get(focus_map["risk"]) or {}
            quality_gate = self._quality_gate(focus_result, origin_counts, "risk", is_scenario)
            scope_context = scopes[entity_id]
            observed = observed_by_entity[entity_id]
            context = context_by_entity[entity_id]
            observed_fingerprint = self._observed_fingerprint(observed)
            transformed_fingerprints = {
                key: value
                for key, value in (transformed_fingerprints_by_entity.get(entity_id) or {}).items()
                if value
            }
            # 与 predict_suite 同口径：顶层指纹为 risk 任务自己的；合成/缺失时置空并说明原因。
            # （快照 serve 时会按请求的 focus_metric 重新解析顶层指纹，见 prediction_snapshot.assemble。）
            risk_fp = transformed_fingerprints.get(focus_map["risk"])
            if risk_fp:
                fp_unavailable_reason = None
            else:
                risk_origin = focus_result.get("value_origin") or focus_result.get("status")
                fp_unavailable_reason = {
                    "legacy_v0_2_synthetic_fallback": "synthetic_fallback_no_real_model_inputs",
                    "not_applicable": "no_real_bundle_for_task_horizon",
                }.get(risk_origin, "transformed_frame_not_recorded")
            assembled[entity_id] = {
                "prediction_run_id": f"ALG-V0.3-{scope_context.get('snapshot_id') or 'no-snapshot'}-{entity_id}-{horizon_days}d",
                "entity_id": entity_id,
                # 兼容字段：等价于 observed_input_fingerprint（旧消费者仍可读）
                "input_fingerprint": observed_fingerprint,
                "fingerprint_schema": FINGERPRINT_SCHEMA,
                "observed_input_fingerprint": observed_fingerprint,
                "transformed_model_input_fingerprint": risk_fp,
                "transformed_model_input_fingerprint_unavailable_reason": fp_unavailable_reason,
                "transformed_model_input_fingerprints": transformed_fingerprints,
                "horizon_days": horizon_days,
                "month_offset": month_offset,
                "granularity_tier": tier,
                "granularity_disclosure": manifest.get("granularity_disclosure"),
                "issued_at": scope_context.get("observed_at"),
                "scope": scope_context,
                "results": results,
                "risk_score": risk_score,
                "analysis_focus": {"requested_metric": "risk", "result_key": focus_map["risk"]},
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
                "mechanism_drivers": self._mechanism_drivers_cached(entity_id, observed, context),
                "quality_gate": quality_gate,
                "model_quality": model_quality,
            }
        return assembled

    def _legacy_fallback_batch(
        self,
        task_id: str,
        variant: str,
        horizon_days: int,
        output_key: str,
        label: str,
        entity_ids: list[str],
        legacy_box: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """legacy V0.2 回退的批量版本：全部实体一次推理，逐实体拆分。"""
        legacy = self.legacy
        if legacy is None:
            return {}
        try:
            bundle = legacy._bundle(task_id, variant, horizon_days)
            legacy_pd, _, predict_batch, _ = legacy._runtime_imports()
            frames = []
            for entity_id in entity_ids:
                observed, context, calendar = self._legacy_inputs(entity_id)
                frames.append(legacy._raw_frame(legacy_pd, bundle, observed, calendar))
            raw_all = predict_batch(bundle, legacy_pd.concat(frames, ignore_index=True))
        except Exception:  # noqa: BLE001 — 回退链任何一步失败都不得伪造结果
            return {}
        model_name = getattr(bundle.model, "name", type(bundle.model).__name__)
        out: dict[str, dict[str, Any]] = {}
        for index, entity_id in enumerate(entity_ids):
            raw = raw_all.iloc[index].to_dict()
            value = _json_scalar(raw.get("prediction"))
            probability = _json_scalar(raw.get("probability"))
            if output_key in {"bloom", "probability"} and probability is not None:
                value = probability
            out[entity_id] = {
                "task_id": task_id,
                "variant": variant,
                "label": label,
                "value": value,
                "probability": probability,
                "unit": self.LEGACY_UNIT_MAP.get(output_key),
                "status": "ok",
                "value_origin": "legacy_v0_2_synthetic_fallback",
                "model_file": f"{task_id}-{variant}-{horizon_days}d-s{MODEL_SEED}.joblib",
                "selected_model": model_name,
                "training_protocol": "synthetic_augmented_legacy_v0_2",
                "uncertainty": None,
                "uncertainty_available": False,
            }
        return out

    def _mechanism_drivers_cached(
        self, entity_id: str, observed: dict[str, float], context: dict[str, float]
    ) -> dict[str, Any]:
        """机理分解仅依赖「实测输入 + 上下文月 + 冻结上下文表」，同一实测快照内按实体复用。

        该分解与模型无关、恒可用，重复计算不产生任何新信息。
        """
        self._cache_epoch()
        cached = self._mech_cache.get((entity_id,))
        if cached is None:
            cached = self._mechanism_drivers(entity_id, observed, context)
            self._mech_cache[(entity_id,)] = cached
        return cached

    def _mechanism_drivers(
        self, entity_id: str, observed: dict[str, float], context: dict[str, float]
    ) -> dict[str, Any]:
        """机理净生长率分解（运行时展示口径，与特征契约 mech_* 同一公式，模型无关、恒可用）。

        温度口径（2026-09-11 对齐）：优先本站 MEE 实测水温（一站一值）→ ERA5 湖表温度
        网格月度值 → 上下文气象气温（明确标"气温，非水温"）→ 全湖 MEE 水温均值代理；
        与训练端 _mechanism_columns 的水温优先口径一致。光照取气象网格值或签发月气候态，
        全部按代理口径披露（全湖单一气象网格，不构成站间差异）。磷/氮条件优先 MEE 实测。
        """
        def clip01(value: float) -> float:
            return float(min(max(value, 0.0), 1.0))

        # ---- 温度：本站实测水温优先 ----
        temp = None
        temp_proxy = True
        temp_source = "缺测"
        station_water_temp = observed.get("wq_water_temp")
        if station_water_temp is not None:
            temp = float(station_water_temp)
            temp_proxy = False
            temp_source = (
                "全湖 MEE 均值·水温" if entity_id == "lake" else "本站实测·MEE 水温"
            )
        elif context.get("wq_water_temp") is not None:
            temp = float(context["wq_water_temp"])
            temp_source = "ERA5 湖表温度网格·月度（全湖同一网格，非站间分辨）"
        elif context.get("met_air_temperature_c") is not None:
            temp = float(context["met_air_temperature_c"])
            temp_source = "上下文气象·气温（非水温，回退口径）"
        else:
            summary = self._realtime_summary()
            water_temp = (summary.get("means", {}).get("water_temperature") or {}).get("value")
            if water_temp is not None:
                temp = float(water_temp)
                temp_source = "全湖 MEE 水温均值代理（本站缺测回退）"
        # ---- 光照：气象网格值或签发月气候态，一律代理口径 ----
        met_month = None
        light = context.get("met_shortwave_radiation_wm2")
        light_source = "气象网格值（NASA_POWER，非本站实测）" if light is not None else None
        if light is None and self._context_frame is not None and len(self._context_frame):
            import pandas as pd

            whole = self._context_frame[self._context_frame["station_id"] == "TAIHU_WHOLE"]
            met_rows = whole.dropna(subset=["met_shortwave_radiation_wm2"]).sort_values("month")
            if len(met_rows):
                row = met_rows.iloc[-1]
                met_month = str(row["month"])
                light = float(row["met_shortwave_radiation_wm2"])
                light_source = f"气象网格值（NASA_POWER {met_month}，非本站实测）"
        if light is None:
            try:
                issuing_month = int((context.get("observed_at") or datetime.now().isoformat())[5:7])
            except (ValueError, TypeError, IndexError):
                issuing_month = datetime.now().month
            if self._context_frame is not None and len(self._context_frame):
                import pandas as pd

                met_rows = self._context_frame[
                    self._context_frame["met_shortwave_radiation_wm2"].notna()
                    & (self._context_frame["month"].str[5:7].astype(int) == issuing_month)
                ]
                if len(met_rows):
                    light = float(met_rows["met_shortwave_radiation_wm2"].median())
                    light_source = f"{issuing_month} 月气候态·NASA POWER 网格（非实测）"
        air_temp = context.get("met_air_temperature_c")
        tp = observed.get("wq_tp", context.get("wq_tp"))
        tn = observed.get("wq_tn", context.get("wq_tn"))
        nh4 = observed.get("wq_nh4_n", context.get("wq_nh4_n"))

        f_temp = clip01((temp - 10.0) / 18.0) if temp is not None else None
        if f_temp is not None and (temp <= 4.0 or temp >= 38.0):
            f_temp = 0.0
        f_light = clip01(light / 18.0) if light is not None else None
        f_phos = clip01(tp / (tp + 0.02)) if tp else None
        f_nitro = clip01(tn / (tn + 0.6)) if tn else None
        f_nutr = min((x for x in (f_phos, f_nitro) if x is not None), default=None)
        net = 0.9 * f_temp * f_light * f_nutr - 0.16 if None not in (f_temp, f_light, f_nutr) else None
        factors = [
            {"key": "temperature", "label": "温度适合度", "value": f_temp,
             "source_value": temp, "unit": "℃", "proxy": temp_proxy,
             "station_resolution": temp_proxy is False,
             "source": temp_source},
            {"key": "air_temperature", "label": "气温（参考）", "value": None,
             "source_value": air_temp, "unit": "℃", "proxy": True, "state_only": True,
             "station_resolution": False,
             "source": ("上下文气象·气温网格值（不进入温度适合度）" if air_temp is not None
                        else "缺测·不进入温度适合度")},
            {"key": "light", "label": "光照适合度", "value": f_light,
             "source_value": light, "unit": "W/m²", "proxy": True,
             "station_resolution": False,
             # 光照适合度 = clip(光照/18, 0, 1)，18 W/m² 即饱和；太湖月均光照远高于此，
             # 故该因子常年恒为 1.0。这不是"光照条件完美"，是公式在其区间上取到了上界。
             "saturated": light is not None and light >= 18.0,
             "saturation_value": 18.0,
             "source": light_source or "缺测"},
            {"key": "phosphorus", "label": "磷条件", "value": f_phos,
             "source_value": tp, "unit": "mg/L", "proxy": False,
             "station_resolution": "wq_tp" in observed,
             "source": "MEE 实测" if "wq_tp" in observed else "上下文"},
            {"key": "nitrogen", "label": "氮条件", "value": f_nitro,
             "source_value": tn, "unit": "mg/L", "proxy": False,
             "station_resolution": "wq_tn" in observed,
             "source": "MEE 实测" if "wq_tn" in observed else "上下文"},
            {"key": "ammonia", "label": "氨氮输入", "value": None,
             "source_value": nh4, "unit": "mg/L", "proxy": False, "state_only": True,
             "station_resolution": "wq_nh4_n" in observed,
             "source": ("MEE 实测·未纳入当前机理公式" if "wq_nh4_n" in observed
                        else "上下文·未纳入当前机理公式" if nh4 is not None else "缺测·未纳入当前机理公式")},
            {"key": "flow", "label": "流速输入", "value": None,
             "source_value": None, "unit": "m/s", "proxy": False, "state_only": True,
             "station_resolution": False,
             "source": "当前 V0.3 特征契约无流速字段·不可用"},
        ]
        known = [f for f in factors if f["value"] is not None]
        limiting = min(known, key=lambda f: f["value"])["key"] if known else None
        # 来源分组（结构化，供前端直接渲染，不靠字符串匹配）：
        # 逐站可得 vs 全湖同一值。光照与气温来自单一气象网格，物理上不存在站间差异；
        # 全湖实体的水温/营养盐本身即 79 站聚合，可回溯到逐站实测。
        per_station = [f["key"] for f in factors if f.get("station_resolution")]
        lake_wide = [f["key"] for f in factors if not f.get("station_resolution")]
        return {
            "factors": factors,
            "nutrient_factor": f_nutr,
            "limiting_factor": limiting,
            "net_growth_rate_d": _json_scalar(net) if net is not None else None,
            "net_growth_range": [-0.16, 0.6],
            "station_resolution_scope": "lake_aggregate" if entity_id == "lake" else "station",
            "source_groups": {
                "per_station": per_station,
                "lake_wide": lake_wide,
                "lake_wide_note": (
                    "光照与气温取自单一气象网格，物理上全湖同值，不构成站间差异；"
                    "温度与营养盐为逐站实测（全湖视图下为 79 站聚合，可回溯到站）。"
                ),
            },
            "formula": "net = 0.9·f_T·f_I·min(f_P, f_N) − 0.16（与特征契约 mech_* 同式）",
            "note": (
                "机理净生长率分解：反映当前环境对藻类生长的适合度与限制因子，公式与训练特征一致、"
                "不依赖任何训练模型，模型敏感性不可用时恒可用。温度优先本站 MEE 实测水温（一站一值），"
                "缺测时依次回退 ERA5 湖表温度网格、上下文气温、全湖均值代理；光照取气象网格值或签发月"
                "气候态（全湖单一气象网格，不构成站间差异）；适合度为 0-1 计算值，非观测百分比。"
                "光照适合度 = clip(光照/18, 0, 1)，18 W/m² 即取到上界、常年恒为 1.0，"
                "这是公式在其区间上取到上界，而非「光照理想」。氨氮仅展示输入状态，流速因当前契约缺字段显示不可用；"
                "两者均不伪装成机理贡献。"
            ),
        }

    # ---- 单任务 legacy V0.2 合成数据回退（缺失 (task, horizon) 的对照链） ----

    LEGACY_UNIT_MAP = {
        "area": "km²", "coverage": "ratio", "density": "cells/L",
        "biomass": "mg/L", "chla": "μg/L", "probability": "ratio", "spatial": "ratio",
    }

    def _legacy_fallback_result(
        self,
        task_id: str,
        variant: str,
        horizon_days: int,
        output_key: str,
        label: str,
        entity_id: str,
        legacy_box: dict[str, Any],
    ) -> dict[str, Any] | None:
        """同一实测快照内复用 legacy 回退结果。

        单次 predict_suite 会为 v0.3 缺失 (task, horizon) 各跑一次 legacy 模型推理，
        而 legacy 输入与实测快照一一对应，故整批复用不改变任何口径。
        调用方会补写 label_provenance/compliance，因此必须返回副本而非缓存对象本身。
        """
        cache_key = (task_id, variant, horizon_days, entity_id)
        self._cache_epoch()
        if cache_key in self._legacy_cache:
            cached = self._legacy_cache[cache_key]
            return dict(cached) if cached is not None else None
        result = self._legacy_fallback_result_uncached(
            task_id, variant, horizon_days, output_key, label, entity_id, legacy_box
        )
        self._legacy_cache[cache_key] = result
        return dict(result) if result is not None else None

    def _legacy_inputs(
        self, entity_id: str
    ) -> tuple[dict[str, float], dict[str, Any], dict[str, float]]:
        """legacy 回退输入（V0.2 特征契约）：同一实测快照内按实体复用。

        原实现把 legacy 输入放在每次 predict_suite 各自的局部 legacy_box 中，
        于是七个时效会把同一实体的 V0.2 输入（含全湖聚合）各算一遍，
        这是站点批量预生成最主要的耗时来源。
        """
        self._cache_epoch()
        cached = self._legacy_inputs_cache.get(entity_id)
        if cached is None:
            legacy = self.legacy
            observed, context = legacy._observed_inputs(entity_id)
            calendar = legacy._calendar_features(context.get("observed_at"))
            cached = (observed, context, calendar)
            self._legacy_inputs_cache[entity_id] = cached
        return cached

    def _legacy_fallback_result_uncached(
        self,
        task_id: str,
        variant: str,
        horizon_days: int,
        output_key: str,
        label: str,
        entity_id: str,
        legacy_box: dict[str, Any],
    ) -> dict[str, Any] | None:
        """缺失 (task, horizon) 时回退 legacy V0.2 合成数据模型：单任务推理，如实标注 provenance。

        legacy 观测输入与 V0.2 特征契约（非 v2 契约）配套，独立于本服务的 v2 输入。
        回退失败时返回 None，由调用方记 not_applicable；绝不静默丢弃或改用其他口径顶替。
        """
        legacy = self.legacy
        if legacy is None:
            return None
        try:
            if "inputs" not in legacy_box:
                legacy_box["inputs"] = self._legacy_inputs(entity_id)
            observed, context, calendar = legacy_box["inputs"]
            bundle = legacy._bundle(task_id, variant, horizon_days)
            legacy_pd, _, predict_batch, _ = legacy._runtime_imports()
            frame = legacy._raw_frame(legacy_pd, bundle, observed, calendar)
            raw = predict_batch(bundle, frame).iloc[0].to_dict()
        except Exception:  # noqa: BLE001 — 回退链任何一步失败都不得伪造结果
            return None
        value = _json_scalar(raw.get("prediction"))
        probability = _json_scalar(raw.get("probability"))
        if output_key in {"bloom", "probability"} and probability is not None:
            value = probability
        return {
            "task_id": task_id,
            "variant": variant,
            "label": label,
            "value": value,
            "probability": probability,
            "unit": self.LEGACY_UNIT_MAP.get(output_key),
            "status": "ok",
            "value_origin": "legacy_v0_2_synthetic_fallback",
            "model_file": f"{task_id}-{variant}-{horizon_days}d-s{MODEL_SEED}.joblib",
            "selected_model": getattr(bundle.model, "name", type(bundle.model).__name__),
            "training_protocol": "synthetic_augmented_legacy_v0_2",
            "uncertainty": None,
            "uncertainty_available": False,
        }

    @staticmethod
    def _band_of(value: float, risk_bands: dict[str, tuple[float, float]]) -> str | None:
        for name, (low, high) in risk_bands.items():
            if low <= value < high:
                return name
        return None

    def _derive_risk_level(
        self, chla_result: dict[str, Any] | None, risk_bands: dict[str, tuple[float, float]]
    ) -> dict[str, Any] | None:
        """由叶绿素 a 真实数据模型（公示代理标签）预测值推导风险等级（冻结 risk_bands_ug_l 阈值映射）。"""
        if not chla_result or chla_result.get("value") is None:
            return None
        value = float(chla_result["value"])
        band = self._band_of(value, risk_bands)
        if band is None:
            return None
        chla_uncertainty = chla_result.get("uncertainty") or {}
        p05_band = p95_band = None
        # 只有"决策可用"的区间才允许映射等级范围：结构自洽但缺乏校准证据的区间
        # （如 test_n=1 的叶绿素 a）不足以支撑等级范围结论。
        if chla_uncertainty.get("decision_usable") and chla_uncertainty.get("p05") is not None and chla_uncertainty.get("p95") is not None:
            p05_band = self._band_of(float(chla_uncertainty["p05"]), risk_bands)
            p95_band = self._band_of(float(chla_uncertainty["p95"]), risk_bands)
        band_range = p05_band is not None and p95_band is not None
        # 等级范围缺失时必须给出明确原因，不能只留一个空态。判据按三层合同同序给出，
        # 让页面能说清"是被结构否掉、被校准否掉，还是被验收线否掉"。
        if band_range:
            band_range_blocked = None
        else:
            if chla_result.get("uncertainty") is None:
                blocked_reason = "source_interval_unavailable"
            elif not chla_uncertainty.get("structural_valid"):
                blocked_reason = "source_interval_structurally_invalid"
            elif chla_uncertainty.get("calibration_status") != CALIBRATION_VALIDATED:
                blocked_reason = f"source_interval_{chla_uncertainty.get('calibration_status') or CALIBRATION_UNAVAILABLE}"
            else:
                blocked_reason = "source_interval_band_mapping_failed"
            band_range_blocked = {
                "reason": blocked_reason,
                "calibration_status": chla_uncertainty.get("calibration_status"),
                "calibration_reason": chla_uncertainty.get("calibration_reason"),
                "empirical_coverage": chla_uncertainty.get("empirical_coverage"),
                "coverage_target": COVERAGE_TARGET,
                "coverage_tolerance": COVERAGE_TOLERANCE,
                "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
                "structural_valid": chla_uncertainty.get("structural_valid"),
                "test_n": chla_uncertainty.get("test_n"),
                "source_interval": {
                    "task": "T5-chla",
                    "p05": chla_uncertainty.get("p05"),
                    "p95": chla_uncertainty.get("p95"),
                },
                "note": (
                    "风险等级范围由叶绿素 a 的预测区间映射得到；该源区间未达决策可用"
                    "（覆盖率未达标 / 未核算 / 结构不自洽），因此不给出等级范围，"
                    "更不得反向用于决策。"
                ),
            }
        return {
            "task_id": "T6",
            "variant": "risk_level",
            "label": "风险等级",
            "value": band,
            "probability": None,
            "predicted_class": None,
            "unit": None,
            "status": "ok",
            "value_origin": "derived_from_chla_v0_3_risk_bands",
            "derived_from": {
                "task_id": "T5",
                "variant": "chla",
                "chla_value_ug_l": chla_result.get("value"),
                "rule": "冻结风险带 risk_bands_ug_l（none<10≤low<20≤medium<30≤high<50≤severe，μg/L；与 20 μg/L 水华阈值同源）",
            },
            "model_file": chla_result.get("model_file"),
            "model_file_path": chla_result.get("model_file_path"),
            "model_sha256": chla_result.get("model_sha256"),
            "artifact_id": chla_result.get("artifact_id"),
            "label_provenance": chla_result.get("label_provenance"),
            "derived_is_proxy": str(chla_result.get("label_provenance") or "").startswith(
                ("chla_station_proxy", "mixed", "proxy")
            ),
            "selected_family": chla_result.get("selected_family"),
            "granularity_tier": chla_result.get("granularity_tier"),
            "training_protocol": chla_result.get("training_protocol"),
            "uncertainty": (
                {
                    "method": "derived_band_range_from_chla_conformal_interval",
                    "is_prediction_interval": True,
                    # 这是"区间 → 等级范围"的映射，不是数值区间本身：前端按 band_range 分支
                    # 渲染等级范围条，不走 P05—点—P95 刻度尺。structural_valid / decision_usable
                    # 继承源区间，保证三层合同在本任务上语义完整、不必让前端猜缺字段的含义。
                    "band_range": True,
                    "interval_semantics": UNCERTAINTY_SEMANTICS,
                    "structural_valid": bool(chla_uncertainty.get("structural_valid")),
                    "calibration_status": chla_uncertainty.get("calibration_status") or CALIBRATION_UNAVAILABLE,
                    "decision_usable": bool(chla_uncertainty.get("decision_usable")),
                    "decision_reason": chla_uncertainty.get("decision_reason"),
                    "point_band": band,
                    "p05_band": p05_band,
                    "p95_band": p95_band,
                    "source_interval": {
                        "task": "T5-chla",
                        "p05": chla_uncertainty.get("p05"),
                        "p95": chla_uncertainty.get("p95"),
                        "test_n": chla_uncertainty.get("test_n"),
                        "empirical_coverage": chla_uncertainty.get("empirical_coverage"),
                        "training_protocol": chla_uncertainty.get("training_protocol"),
                    },
                    "note": "等级范围由叶绿素 a 的预测区间映射到冻结风险带；等级本身不是经校准的概率输出。",
                }
                if band_range
                else None
            ),
            "uncertainty_available": band_range,
            # 无法给出等级范围时的显式原因（供页面如实展示，而不是留空态让人猜）
            "band_range_blocked": band_range_blocked,
        }

    @staticmethod
    def _quality_gate(
        focus_result: dict[str, Any],
        origin_counts: dict[str, int],
        focus_metric: str,
        scenario: bool,
    ) -> dict[str, Any]:
        """质量门按实际输出计算：ok / partial / degraded / unavailable，禁止无结果时返回 ok。"""
        counts = {"value_origin_counts": origin_counts}
        focus_origin = focus_result.get("value_origin")
        if focus_result.get("value") is None:
            return {
                "status": "unavailable",
                "decision": "no_valid_prediction",
                "reason": (
                    f"当前时效的 {focus_metric} 指标没有可用模型输出："
                    "该任务/时效在真实标签下不可训练，legacy 回退也不可用；页面必须显示空态，不得展示替代数值。"
                ),
                **counts,
            }
        if focus_origin == "legacy_v0_2_synthetic_fallback":
            return {
                "status": "degraded",
                "decision": "legacy_synthetic_fallback_scenario",
                "reason": (
                    f"当前指标（{focus_metric}）在 V0.3 真实数据包下不可训练（对应标签缺失），"
                    "展示值为 legacy V0.2 合成数据模型的对照输出，仅用于情景推演与系统联调；"
                    "不得表述为真实太湖预测精度。"
                ),
                **counts,
            }
        if focus_origin == "seasonal_climatology_baseline":
            return {
                "status": "partial",
                "decision": "seasonal_climatology_baseline",
                "reason": (
                    f"当前指标（{focus_metric}）在该时效没有可用的逐站模型：历史标签为季度采样，"
                    "(输入月, 目标月) 配对不足以训练逐站模型。展示值为季节气候态基线"
                    "——按目标月给出历史同期值，真实、可留出回测，但全湖同值、不含站点分辨，"
                    "不得用于站间比较。"
                ),
                **counts,
            }
        if origin_counts["legacy_v0_2_synthetic_fallback"] > 0:
            return {
                "status": "partial",
                "decision": "real_data_with_legacy_supplement",
                "reason": (
                    "当前焦点指标来自 V0.3 真实数据模型；同时效内另有任务因标签缺失以 legacy V0.2 合成数据"
                    "对照输出补位（逐任务见 value_origin），仅作对照展示。"
                ),
                **counts,
            }
        if origin_counts["seasonal_climatology_baseline"] > 0:
            return {
                "status": "partial",
                "decision": "real_data_with_climatology_supplement",
                "reason": (
                    "当前焦点指标来自 V0.3 逐站模型；同时效内另有任务以季节气候态基线给出"
                    "（全湖同值，不含站点分辨，逐任务见 value_origin）。"
                ),
                **counts,
            }
        return {
            "status": "ok",
            "decision": "real_data_v0_3",
            "reason": (
                "当前结果由 V0.3 真实清洗数据模型生成（月度标签粒度）；精度表述以冻结测试集与门禁"
                "评估为准。30/60/90 天为中长期月度趋势口径：90 天为逐站模型、30/60 天为季节气候态基线。"
            ),
            **counts,
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
                "注意：MEE 叶绿素 a（wq_chla）在 v2 契约中仅以滞后/滚动列形式存在（防同月泄漏），"
                "当月实测值不直接进入模型。"
            ),
        }

    def _feature_scales_map(self) -> dict[str, float]:
        """训练期特征标准差（来自监督底表全体站点-月），用作敏感性步长下限。

        树模型在 ±10%（绝对最小 0.01）的微扰下常跨不过任何分裂阈值，导致敏感性
        恒为 0；步长取 max(10% 基线, 0.5σ, 0.01) 才能反映模型对特征的真实局部响应。
        """
        if self._feature_scales is not None:
            return self._feature_scales
        scales: dict[str, float] = {}
        try:
            frame = self._context_frame
            if frame is None:
                self._context()
                frame = self._context_frame
            if frame is not None and len(frame):
                import pandas as pd

                for name in frame.columns:
                    values = pd.to_numeric(frame[name], errors="coerce").dropna()
                    if len(values) >= 10:
                        scales[name] = float(values.std())
        except Exception:  # noqa: BLE001 — 步长表缺失时退回原 ±10% 规则
            scales = {}
        self._feature_scales = scales
        return scales

    def _explain(self, bundle: Any, frame: Any, observed: dict[str, float]) -> dict[str, Any]:
        scales = self._feature_scales_map()
        factors = []
        base_output = bundle.predict_point(frame).iloc[0]
        base_value = float(base_output.get("probability", base_output.get("prediction")))
        for feature, label in V3_SENSITIVITY_FEATURES:
            if feature not in frame.columns:
                continue
            raw_baseline = float(frame.iloc[0][feature])
            input_source = "observed" if feature in observed else "month_context_or_imputed"
            baseline = raw_baseline
            if math.isnan(baseline):
                # 缺测字段模型实际看到的是冻结中位数插补值：围绕有效输入扰动才有意义
                median = (bundle.preprocessor.medians or {}).get(feature)
                if median is None:
                    continue
                baseline = float(median)
                input_source = "frozen_train_median_baseline"
            step = max(abs(baseline) * 0.10, 0.5 * scales.get(feature, 0.0), 0.01)
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
                "raw_value": None if math.isnan(raw_baseline) else raw_baseline,
                "perturbation": "plus_minus_10_percent_or_half_sigma_local",
                "step": step,
                "effect": effect,
                "direction": "increase" if effect > 0 else "decrease" if effect < 0 else "neutral",
                "input_source": input_source,
            })
        total = sum(abs(item["effect"]) for item in factors)
        for item in factors:
            item["contribution_percent"] = round(abs(item["effect"]) / total * 100, 2) if total else 0.0
        factors.sort(key=lambda item: abs(item["effect"]), reverse=True)
        # 常数基线或在小样本上退化为常数输出的树模型：全部效应为 0 时如实标记，
        # 前端据此不把全 0 贡献度排序当作有效解释展示。
        effective = any(abs(item["effect"]) > 0.0 for item in factors)
        if effective:
            ineffective_reason = None
        elif bundle.selected_family == "simple_baseline" or getattr(bundle.model, "constant", None) is not None \
                or getattr(bundle.model, "single_class_value", None) is not None:
            ineffective_reason = "selected_model_constant_baseline_not_input_sensitive"
        else:
            ineffective_reason = "trained_model_zero_response_in_perturbation_range"
        return {
            "method": "local_one_at_a_time_sensitivity",
            "is_shap": False,
            "effective": effective,
            "ineffective_reason": ineffective_reason,
            "selected_family": bundle.selected_family,
            "baseline": base_value,
            "factors": factors[:8],
            "unavailable_factors": [],
            "note": (
                "贡献度为局部单因素敏感性归一化结果（步长 = max(±10% 基线, 0.5×训练期σ, 0.01)），"
                "缺测字段围绕冻结中位数插补值计算；不是因果贡献，也不是 SHAP 值。"
            ),
        }

    # ---- 门禁（唯一来源：evaluation/gate_table.json；无硬编码比较数） ----

    def _gate_table(self) -> dict[str, Any]:
        path = self.package_dir / "evaluation" / "gate_table.json"
        if not path.is_file():
            raise AlgorithmModelUnavailable(f"门禁表不存在: {path}（请先运行 cli_real.py gate）")
        return json.loads(path.read_text(encoding="utf-8"))

    def _seasonal_climatology(self) -> dict[str, Any]:
        """季节气候态基线产物（按文件 stat 缓存，与实测快照无关的包内产物）。

        产物版本不符或缺失时返回空 dict——调用方按"无该基线"处理，绝不猜测新字段语义。
        """
        path = self.package_dir / SEASONAL_CLIMATOLOGY_PATH_FRAGMENT
        try:
            stat = path.stat()
            key = (str(path), stat.st_size, stat.st_mtime_ns)
        except OSError:
            return {}
        cached = getattr(self, "_clim_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        payload: dict[str, Any] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if loaded.get("artifact_version") == SEASONAL_CLIMATOLOGY_VERSION:
                payload = loaded
        except Exception:  # noqa: BLE001 — 产物损坏即视为不可用，不静默降级成别的口径
            payload = {}
        self._clim_cache = (key, payload)
        return payload

    def _climatology_entry(self, task_id: str, variant: str) -> dict[str, Any] | None:
        payload = self._seasonal_climatology()
        for entry in payload.get("tasks") or []:
            if entry.get("task_id") == task_id and entry.get("variant") == variant:
                return entry
        return None

    def _long_term_route(
        self, task_id: str, variant: str, month_offset: int, horizon_days: int,
        bundle: Any, scenario_horizons: Any,
    ) -> dict[str, Any]:
        """中长期（30/60/90 天）交付路由：先看模型评估是否充分，再谈用不用它。

        路由顺序（2026-09-11 立）：
            ① 评估充分的逐站模型（留出测试样本 ≥ MIN_CALIBRATION_TEST_N）
            ② 有留出评估的季节气候态基线
            ③ 明确不可用
        "文件存在"不构成①：T+30/T+60 的持久性模型只有 5 条测试样本，
        brier=0 是在 5 行上算出来的，把它当默认中长期风险概率是虚假精确。
        """
        if bundle is None:
            return {
                "use_bundle": False, "model_rejected": False,
                "reason": "model_artifact_missing", "evidence": None,
                "policy": LONG_TERM_ROUTE_POLICY,
            }
        if horizon_days not in scenario_horizons:
            return {"use_bundle": True, "model_rejected": False, "reason": None, "evidence": None,
                    "policy": LONG_TERM_ROUTE_POLICY}
        meta = bundle.uncertainty_meta or {}
        test_n_raw = meta.get("test_n")
        test_n = (
            int(test_n_raw)
            if isinstance(test_n_raw, (int, float)) and not isinstance(test_n_raw, bool)
            else None
        )
        adequate = test_n is not None and test_n >= MIN_CALIBRATION_TEST_N
        evidence = {
            "selected_family": bundle.selected_family,
            "test_n": test_n,
            "min_test_n": MIN_CALIBRATION_TEST_N,
            "empirical_coverage": meta.get("empirical_coverage_test"),
            "training_protocol": meta.get("split_protocol") or "frozen_split",
        }
        if adequate:
            return {"use_bundle": True, "model_rejected": False, "reason": None,
                    "evidence": evidence, "policy": LONG_TERM_ROUTE_POLICY}
        return {
            "use_bundle": False,
            "model_rejected": True,
            "reason": (
                f"long_term_model_evaluation_insufficient(n_test={test_n}<{MIN_CALIBRATION_TEST_N})"
            ),
            "evidence": evidence,
            "policy": LONG_TERM_ROUTE_POLICY,
        }

    @staticmethod
    def _climatology_has_holdout(clim: dict[str, Any]) -> bool:
        """季节基线是否真有留出段评估（样本量达标 + 残差分位数已核算）。"""
        backtest = clim.get("backtest") or {}
        n = backtest.get("n")
        if not isinstance(n, (int, float)) or isinstance(n, bool) or int(n) < MIN_CALIBRATION_TEST_N:
            return False
        if clim.get("problem_type") == "ordinal":
            return backtest.get("metrics") is not None
        return bool(backtest.get("residual_quantiles"))

    def _climatology_result(
        self, task_id: str, variant: str, label: str, output_key: str,
        horizon_days: int, month_offset: int, scope_context: dict[str, Any],
        compliance: dict[str, Any], entry: dict[str, Any],
        route: dict[str, Any] | None = None,
        allow_any_scenario: bool = False,
    ) -> dict[str, Any] | None:
        """季节气候态基线结果（中长期无交付模型时的真实回退）。

        为什么可以这么给：历史水质面板是季度采样，offset=1/2 与季度网格不同余，
        (M, M+offset) 标签配对为空——该 (任务, 时效) 不存在可训练的逐站模型。
        能在真实数据上成立的只有按目标月的历史同期值；它逐月变化、可用留出段回测，
        但不含站点分辨，必须如实标注，不得与逐站模型结果混同。

        allow_any_scenario（2026-09-11 加）：模型被评估门槛否决时，只要基线本身
        有真实留出评估，就允许该时效回退到基线——否则"模型不够格"会直接退化成空白，
        而基线恰恰是这一档唯一有证据的答案。
        """
        clim = self._climatology_entry(task_id, variant)
        if clim is None:
            return None
        fallback_horizons = clim.get("fallback_horizons") or []
        if horizon_days not in fallback_horizons:
            if not allow_any_scenario or not self._climatology_has_holdout(clim):
                return None
        target_month = self._target_month(scope_context.get("observed_at"), month_offset)
        if target_month is None:
            return None
        key = str(target_month)
        by_month = clim.get("by_month") or {}
        is_ordinal = clim.get("problem_type") == "ordinal"
        # 季节表只含季度采样月（2/5/8/11）；目标月缺同期样本时回退全拟合段总体均值，
        # 必须如实披露 lookup 口径，不得让"按目标月历史同期值"的表述覆盖全局回退。
        lookup_mode = "target_month_climatology" if key in by_month else "global_fallback"
        value = by_month.get(key, clim.get("fallback"))
        if value is None:
            return None
        if not is_ordinal:
            numeric = float(value)
            if output_key in {"bloom", "coverage", "density", "probability", "spatial"}:
                numeric = float(min(max(numeric, 0.0), 1.0))
            value = numeric
        backtest = clim.get("backtest") or {}
        residuals = backtest.get("residual_quantiles")
        uncertainty = None
        if not is_ordinal and isinstance(value, (int, float)) and residuals:
            # 覆盖率必须来自产物里真实核算过的留出段记录（artifact v2 起才有该字段）。
            # 此前这里硬编码 empirical_coverage=None，却按"样本量≥15"判成 validated、
            # 进而 decision_usable=true——"没核算过覆盖率"被当成了"覆盖率合格"。
            empirical_coverage = backtest.get("empirical_coverage")
            coverage_n = backtest.get("coverage_n")
            # 类别支持（v4 产物）：二分类/概率任务的独立测试段须同时含正负例，
            # 否则覆盖率只反映单一类别覆盖，按 single_class_test 处理、不开放决策。
            problem_type = clim.get("problem_type")
            class_support = None
            if problem_type in {"binary", "probability"}:
                class_support = {
                    "applicable": True,
                    "test_positive_n": backtest.get("test_positive_n"),
                    "test_negative_n": backtest.get("test_negative_n"),
                    "class_support_sufficient": backtest.get("class_support_sufficient"),
                }
            calibration_status, calibration_reason, coverage_gap = _calibration_verdict(
                empirical_coverage, coverage_n if coverage_n is not None else backtest.get("n"),
                source_label="季节基线独立测试段",
                class_support=class_support,
            )
            interval_calibration_n = backtest.get("interval_calibration_n")
            uncertainty = {
                "method": "seasonal_climatology_backtest_residual_quantiles",
                "is_prediction_interval": True,
                "interval_semantics": UNCERTAINTY_SEMANTICS,
                "p05": self._clip_interval(float(value) + float(residuals.get("p05", 0.0)), output_key, lower=True),
                "p95": self._clip_interval(float(value) + float(residuals.get("p95", 0.0)), output_key, lower=False),
                "point_value": float(value),
                "calibration_status": calibration_status,
                "calibration_reason": calibration_reason,
                # calibration_n = 区间校准段样本数；test_n = 独立测试段样本数。二者
                # 来自互不重叠的时间段，绝不能互相顶替（审计整改 2026-09-12）。
                "calibration_n": int(interval_calibration_n) if isinstance(interval_calibration_n, (int, float)) else None,
                "test_n": int(backtest.get("n") or 0),
                "empirical_coverage": empirical_coverage,
                "coverage_target": COVERAGE_TARGET,
                "coverage_tolerance": COVERAGE_TOLERANCE,
                "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
                "coverage_gap": coverage_gap,
                "coverage_n": int(coverage_n) if isinstance(coverage_n, (int, float)) else None,
                "test_positive_n": backtest.get("test_positive_n"),
                "test_negative_n": backtest.get("test_negative_n"),
                "class_support_sufficient": backtest.get("class_support_sufficient"),
                "training_protocol": SEASONAL_CLIMATOLOGY_PROTOCOL,
                "note": (
                    "区间为气候态基线残差分位数（来自区间校准段），非逐站模型残差；"
                    f"经验覆盖率在与校准段不重叠的独立测试段核算：n={int(backtest.get('n') or 0)}"
                    f"（{backtest.get('test_min_month')} 起），"
                    f"校准段 n={interval_calibration_n}"
                    f"（{backtest.get('interval_calibration_min_month')}..{backtest.get('interval_calibration_max_month')}），"
                    f"经验覆盖率 {empirical_coverage if empirical_coverage is None else f'{float(empirical_coverage):.2%}'}。"
                    + (
                        f"当前目标月（{int(key)} 月）无同期样本，数值为全拟合段总体均值基线。"
                        if lookup_mode == "global_fallback"
                        else ""
                    )
                ),
            }
            if uncertainty["p05"] == uncertainty["p95"]:
                # 退化区间即使覆盖率达标也不得标记决策可用；decision_reason 与结构原因
                # 同步给出，保证"不可用"永远带可解释的原因（与下方非退化分支同约定）。
                degenerate_reason = "残差分位数退化，区间无信息量"
                uncertainty.update({
                    "structural_valid": False,
                    "structural_reason": degenerate_reason,
                    "decision_usable": False,
                    "decision_reason": degenerate_reason,
                })
            else:
                structural = bool(uncertainty["p05"] <= float(value) <= uncertainty["p95"])
                decision_usable = bool(structural and calibration_status == CALIBRATION_VALIDATED)
                if not structural:
                    decision_reason = uncertainty["structural_reason"] or "区间结构不自洽"
                elif not decision_usable:
                    decision_reason = calibration_reason
                else:
                    decision_reason = None
                uncertainty.update({
                    "structural_valid": structural,
                    "structural_reason": None if structural else "点值落在残差区间之外",
                    "decision_usable": decision_usable,
                    "decision_reason": decision_reason,
                    "calibration_evidence": {
                        "status": calibration_status,
                        "reason": calibration_reason,
                        "empirical_coverage": empirical_coverage,
                        "coverage_target": COVERAGE_TARGET,
                        "coverage_tolerance": COVERAGE_TOLERANCE,
                        "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
                        "coverage_gap": coverage_gap,
                        "test_n": int(backtest.get("n") or 0),
                        "min_test_n": MIN_CALIBRATION_TEST_N,
                    },
                })
        return {
            "task_id": task_id, "variant": variant, "label": label,
            "value": value,
            "probability": float(value) if (not is_ordinal and output_key in {"bloom", "probability", "coverage", "spatial"}) else None,
            "predicted_class": None,
            "unit": {
                "area": "km²", "coverage": "ratio", "density": "rank",
                "biomass": "mg/L", "chla": "μg/L", "probability": "ratio", "spatial": "ratio",
            }.get(output_key),
            "status": "ok",
            "value_origin": "seasonal_climatology_baseline",
            "seasonal_lookup_mode": lookup_mode,
            "model_family": "seasonal_climatology",
            "selected_family": "seasonal_climatology",
            "static_baseline_model": True,
            "station_resolution": False,
            "station_resolution_note": clim.get("station_resolution_note") or "同一目标月全湖同值，不做站间比较",
            "target_month": key,
            "granularity_tier": entry.get("granularity_tier") or "month_granularity",
            "label_provenance": clim.get("label_provenance"),
            "label_provenance_declared": clim.get("label_provenance_declared"),
            "label_provenance_breakdown": clim.get("label_provenance_breakdown"),
            "training_protocol": SEASONAL_CLIMATOLOGY_PROTOCOL,
            "history": clim.get("history"),
            "long_term_route": (
                route if route else {
                    "use_bundle": False, "model_rejected": False,
                    "reason": "long_term_model_not_delivered",
                    "evidence": clim.get("slot_evidence", {}).get(str(horizon_days)),
                    "policy": LONG_TERM_ROUTE_POLICY,
                }
            ),
            "backtest": {
                "protocol": backtest.get("protocol"),
                "n": backtest.get("n"),
                "train_max_month": backtest.get("train_max_month"),
                "test_min_month": backtest.get("test_min_month"),
                "metrics": backtest.get("metrics"),
                "primary_metric": clim.get("primary_metric"),
                "empirical_coverage": backtest.get("empirical_coverage"),
                "coverage_n": backtest.get("coverage_n"),
                "coverage_target": COVERAGE_TARGET,
                "coverage_tolerance": COVERAGE_TOLERANCE,
                "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
            },
            "uncertainty": uncertainty,
            "uncertainty_available": uncertainty is not None,
            "compliance": compliance,
        }

    def gate_rows_index(self) -> dict[tuple[str, str, int], dict[str, Any]]:
        """按 (task_id, variant, horizon_days) 索引门禁行，供可比较性判定消费。

        绑定规则（2026-09-11）：同一 (任务, 时效) 历史上可能有多条评估记录（旧模型
        FAIL、补训 NA 等），只有 run_id 与当前交付包 manifest 中该时效模型一致的
        记录才参与当前状态判断；历史记录保留在门禁表中但不索引。门禁表缺失或当前
        模型无对应记录时返回空索引（调用方按"无门禁评估记录"处理，不得放行站点比较）。
        """
        try:
            gate = self._gate_table()
        except Exception:  # noqa: BLE001 — 门禁证据缺失必须收敛为"不可比较"
            return {}
        try:
            manifest = self._manifest()
        except Exception:  # noqa: BLE001
            manifest = {}
        current_run_by_horizon: dict[tuple[str, str, int], str] = {}
        for model in manifest.get("models") or []:
            run_id = model.get("run_id") or ""
            parts = run_id.rsplit("-s", 1)[0].split("-")
            if len(parts) < 3 or model.get("horizon_days") is None:
                continue
            current_run_by_horizon[(parts[0], parts[1], int(model["horizon_days"]))] = run_id
        index: dict[tuple[str, str, int], dict[str, Any]] = {}
        for row in gate.get("rows") or []:
            key = (row.get("task_id"), row.get("variant"), row.get("horizon_days"))
            if key[0] is None or key[2] is None:
                continue
            expected_run = current_run_by_horizon.get((key[0], key[1], int(key[2])))
            if expected_run is None:
                continue  # 当前交付包无该 (任务, 时效) 模型：记录不索引
            if row.get("run_id") and row.get("run_id") != expected_run:
                continue  # 历史记录：保留在表中，不参与当前状态判断
            index[key] = row
        return index

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
        """区间与校准证据清单：按"结构自洽 / 校准证据 / 决策可用"三层如实披露。

        不再使用模型清单里恒为 true 的 is_calibrated_confidence_interval 布尔量，
        而是直接由 test_n 与经验覆盖率判定校准状态。
        """
        manifest = self._manifest()
        items = []
        reviewed = 0
        for model in manifest.get("models", []):
            uncertainty = model.get("uncertainty") or {}
            if not uncertainty:
                continue
            reviewed += 1
            test_n_raw = uncertainty.get("test_n")
            test_n = int(test_n_raw) if isinstance(test_n_raw, (int, float)) and not isinstance(test_n_raw, bool) else None
            empirical = uncertainty.get("empirical_coverage_test")
            status, reason, gap = _calibration_verdict(
                empirical, test_n, source_label="模型留出测试集",
            )
            items.append({
                "task_id": model["run_id"].split("-")[0],
                "run_id": model["run_id"],
                "artifact_id": model.get("artifact_id"),
                "model_file": model.get("file"),
                "horizon_days": model.get("horizon_days"),
                "month_offset": model.get("month_offset"),
                "calibration_status": status,
                "calibration_reason": reason,
                "is_prediction_interval": True,
                "coverage_target": COVERAGE_TARGET,
                "coverage_tolerance": COVERAGE_TOLERANCE,
                "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
                "coverage_gap": gap,
                "empirical_coverage": empirical,
                "calibration_n": uncertainty.get("calibration_n"),
                "test_n": test_n,
                "min_test_n": MIN_CALIBRATION_TEST_N,
                "decision_usable": status == CALIBRATION_VALIDATED,
            })
        validated = [item for item in items if item["calibration_status"] == CALIBRATION_VALIDATED]
        undercovered = [item for item in items if item["calibration_status"] == CALIBRATION_UNDERCOVERED]
        insufficient = [item for item in items if item["calibration_status"] == CALIBRATION_INSUFFICIENT_TEST_EVIDENCE]
        without = [item for item in items if item["calibration_status"] == CALIBRATION_NO_TEST_EVIDENCE]
        return {
            "items": items,
            "method": "split_conformal_residual_quantiles",
            "interval_semantics": UNCERTAINTY_SEMANTICS,
            "coverage_acceptance_rule": (
                f"标称 {COVERAGE_TARGET:.0%} 区间只有在留出段实测经验覆盖率 ≥ "
                f"{COVERAGE_ACCEPTANCE_MIN:.0%} 时才判为 validated；低于验收线记 undercovered，"
                "未核算覆盖率记 insufficient_test_evidence。"
            ),
            "summary": {
                "reviewed": reviewed,
                "calibration_validated": len(validated),
                "undercovered": len(undercovered),
                "without_test_evidence": len(without),
                "insufficient_test_evidence": len(insufficient),
            },
            "honesty_note": (
                "结构自洽不等于校准有效：经验覆盖率需要留出段样本支撑，且必须达到验收线。"
                f"当前 {len(validated)}/{reviewed} 个模型同时满足样本量与覆盖率验收；"
                f"{len(undercovered)} 个区间实测覆盖率低于标称值，"
                f"{len(insufficient)} 个样本不足或未核算覆盖率——这些在页面上不得表述为"
                "\u201c可用于决策的区间\u201d。"
            ),
        }

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

    def spatial_field(
        self,
        horizon_days: int,
        metric: str = "chla",
        layer: str = "raster",
        prediction_run_id: str | None = None,
    ) -> dict[str, Any]:
        if horizon_days not in SUPPORTED_HORIZONS:
            raise ValueError(f"horizon_days must be one of {SUPPORTED_HORIZONS}")
        raster_service = RasterFieldService()
        if layer == "raster" and metric == "chla":
            try:
                raster = raster_service.get_raster_layer()
                month = raster["month"]
                compliance = (
                    {"label": LONG_TERM_COMPLIANCE_LABEL, "locked": True}
                    if horizon_days in (30, 60, 90)
                    else {"label": "月度反演基底", "locked": False}
                )
                raster_run_id = (
                    f"{prediction_run_id}-RASTER-CHLA"
                    if prediction_run_id
                    else f"ALG-V0.3-RASTER-{month}-{horizon_days}d-chla"
                )
                return {
                    "prediction_run_id": raster_run_id,
                    "horizon_days": horizon_days,
                    "metric": "chla",
                    "unit": raster["unit"],
                    "layer": "raster",
                    "layer_semantics": "monthly_reconstruction_base_not_horizon_forecast",
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
                        "它是最新月度反演重建基底，不随预测时效生成未来空间场；"
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
            {"label": LONG_TERM_COMPLIANCE_LABEL, "locked": True}
            if horizon_days in (30, 60, 90)
            else {"label": "站点样点对照", "locked": False}
        )
        return legacy_field

    def acceptance_overview(self) -> dict[str, Any]:
        manifest = self._manifest()
        contract = manifest.get("feature_contract") or {}
        p0_1 = "达标" if contract.get("n_features") == 78 else "未达标"
        models = manifest.get("models", [])
        # 覆盖有效性分层：校准器存在 ≠ 已验证 ≠ 可决策。判据 = 样本量 + 覆盖率已核算 + 覆盖率达标，
        # 与 calibration_coverage() 共用 _calibration_verdict，避免两处口径漂移。
        calibrated = [
            m for m in models
            if (m.get("uncertainty") or {}).get("test_n") is not None
            or (m.get("uncertainty") or {}).get("calibration_n")
        ]
        verdicts = []
        for model in calibrated:
            uncertainty = model.get("uncertainty") or {}
            status, _, _ = _calibration_verdict(
                uncertainty.get("empirical_coverage_test"),
                uncertainty.get("test_n"),
                source_label="模型留出测试集",
            )
            verdicts.append(status)
        validated = [s for s in verdicts if s == CALIBRATION_VALIDATED]
        undercovered = [s for s in verdicts if s == CALIBRATION_UNDERCOVERED]
        if validated and len(validated) == len(calibrated):
            p0_2 = "达标"
        elif calibrated:
            p0_2 = "部分达标"
        else:
            p0_2 = "未达标"
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
        # P0-7 标签来源对账：声明值与逐行 actual_provenance 汇总必须一致（混合来源允许落在允许集内）
        provenance_audit = manifest.get("label_provenance_audit") or {}
        mismatch_count = provenance_audit.get("mismatch_count")
        provenance_rows = provenance_audit.get("rows") or []
        provenance_status = (
            "未达标" if mismatch_count is None
            else ("达标" if int(mismatch_count) == 0 else "未达标")
        )
        provenance_detail = (
            "清单缺少 label_provenance_audit 段（尚未重新生成产物）。"
            if mismatch_count is None
            else (
                f"已对账 {len(provenance_rows)} 条 (任务, 时效) 记录，"
                f"声明与观测不一致 {mismatch_count} 条。"
                + (
                    "T5-chla 与 T6-risk_level 按逐行 actual_provenance 汇总披露为 ground_truth_or_proxy 混合来源。"
                )
            )
        )
        artifact_audit = self.model_artifact_audit()
        artifact_status = "达标" if artifact_audit["status"] == "PASS" else "未达标"
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
                    "detail": (
                        f"{len(calibrated)}/{len(models)} 个 bundle 带 conformal 校准器；"
                        f"{len(validated)}/{len(calibrated)} 同时满足样本量与覆盖率验收线"
                        f"（标称 {COVERAGE_TARGET:.0%}，验收线 {COVERAGE_ACCEPTANCE_MIN:.0%}）；"
                        f"{len(undercovered)} 个实测覆盖率低于验收线，不得标为决策可用。"
                        if calibrated else "无带校准器的 bundle。"
                    ),
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
                    "id": "P0-6", "title": "30/60/90 天“中长期月度趋势”合规边界保留",
                    "status": p0_6,
                    "evidence": [{"label": "预测接口（compliance 字段）", "href": "/api/v1/model/v3/predictions?horizon_days=30"}],
                    "detail": (
                        f"30/60/90 天输出（API+前端）固定携带 compliance.label='{LONG_TERM_COMPLIANCE_LABEL}'，"
                        "locked=true，不可移除。该档来源为逐站模型（90 天）或季节气候态基线（30/60 天），"
                        "均为月度粒度、不得当作逐站实测预测。"
                    ),
                },
                {
                    "id": "P0-7", "title": "标签来源逐行继承（禁止任务配置统一声明 ground_truth）",
                    "status": provenance_status,
                    "evidence": [{"label": "模型清单（label_provenance_audit）", "href": "/api/v1/model/status"}],
                    "detail": provenance_detail,
                },
                {
                    "id": "P0-8", "title": "模型身份一一对应（artifact_id + 真实路径 + SHA256）",
                    "status": artifact_status,
                    "evidence": [{"label": "产物核查", "href": "/api/v1/model/artifacts"}],
                    "detail": (
                        f"清单声明 {artifact_audit['checked']} 份产物，"
                        f"artifact_id 唯一={artifact_audit['artifact_id_unique']}，"
                        f"缺失文件 {len(artifact_audit['missing_files'])} 个，"
                        f"SHA256 不一致 {len(artifact_audit['sha256_mismatch'])} 个。"
                        "接口返回的 model_file / model_sha256 全部取自本清单，不再由 run_id 拼接。"
                    ),
                },
            ],
        }
