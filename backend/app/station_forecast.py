"""站点级蓝藻水华短期预测（机理 + AI 融合，v0.1 试点）。

接入成员C"机理+AI 融合建模"框架（里程碑7 blue_algae_m7 v0.1）的站点级适配：

- 数据：MEE 实时观测轨 silver 目录是唯一训练来源；目录缺失/为空 → 引擎不可用，
  绝不回退模拟数据（与实时轨同一原则）。
- 机理模块：logistic-monod 风险指数（成员C mechanism_risk_index 的变量适配版）。
  站点可测输入为水温/总磷/总氮/溶解氧；光照、风速无站点观测，不伪造输入，
  组件权重在四项上重归一，缺失项在 model_card 中披露。
- AI 模块：岭回归（numpy 实现，无新增依赖），目标 log1p(叶绿素a)，按提前期分模型；
  特征 = 滞后观测 + 机理指数 + 日内周期，全站合并训练（样本跨站共享）。
- 融合：cascade（0.4×机理 + 0.6×AI 严重度）+ 经验残差区间，沿用成员C
  cascade_fusion/residual_fusion 语义；融合分仅作 0—100 风险分展示，
  筛查档位判定始终来自叶绿素a 数值预测与 10/25 μg/L 阈值（与预警引擎同口径）。
- 诚实门槛（horizon gate）：某提前期必须同时满足
    ① 有效样本 ≥ MIN_SAMPLES_PER_HORIZON；
    ② 按目标日分块的时间交叉验证测试覆盖 ≥ MIN_CV_TEST_SAMPLES；
    ③ 交叉验证 MAE 不劣于持续性基线（ŷ = 当前实测值）；
  未达标提前期不提供数值预测并如实披露原因（2026-09 数据窗口下
  T+48h 样本不足且未过基线、T+72h 样本严重不足，均被自动阻塞）。

归因披露：特征贡献 = 标准化系数 × 标准化偏差（线性模型精确分解），
不是 SHAP / 注意力；解释文案不得使用"SHAP"表述。

边界：模型由官方站点观测训练（未经跨源验证），仅在已见站点上评估；
试点产出不用于监管决策。
"""
from __future__ import annotations

import math
import threading
from typing import Any

import numpy as np
import pandas as pd

MODEL_VERSION = "MHW-STATION-FC-V0.1"
MODEL_FAMILY = "mechanism_ai_fusion_station_v0.1"
CLAIM_BOUNDARY = "trained_on_official_observations_pilot_not_for_regulatory_use"

# 与 alerts.py 蓝藻筛查阈值同口径（μg/L）；改动必须两处同步
CHLA_LIGHT = 10.0
CHLA_MODERATE = 25.0

HORIZONS_H = (24, 48, 72)          # T+1/T+2/T+3 天
MIN_SAMPLES_PER_HORIZON = 60       # 门槛①：全窗口有效样本下限
MIN_CV_TEST_SAMPLES = 30           # 门槛②：分块交叉验证测试样本总量下限
MIN_FOLD_TEST = 5                  # 单折（单目标日）最少测试样本
FEATURE_LAG_WINDOW_H = 8           # 特征回看窗口（取窗口内最新观测）
TARGET_MATCH_TOL_H = 6             # 目标/滞后叶绿素匹配容差（±6h）

# 机理指数组件权重：成员C v0.1 五项（温0.30/磷0.22/氮0.16/光0.17/风0.15）中
# 无站点观测输入的光照/风速两项剔除，其余按原比例缩放至 0.86 并以 0.14 引入
# 溶解氧胁迫项（低氧指示藻类呼吸压力大），合计 1.00。
_MECH_WEIGHTS = {"temperature": 0.38, "phosphorus": 0.28, "nitrogen": 0.20, "dissolved_oxygen": 0.14}
_MECH_TEMPERATURE_OPT_C = 28.0
_MECH_TEMPERATURE_WIDTH_C = 12.0
_MECH_TP_HALF_SAT = 0.05           # mg/L
_MECH_TN_HALF_SAT = 0.50           # mg/L

RIDGE_LAMBDA = 1.0                 # 原型扫描（λ∈{1,3,10,30}×{全/精简特征}）后的固定选择
RESIDUAL_QUANTILES = (0.1, 0.9)    # 经验残差区间（log 空间，分块 CV 残差池）


class StationForecastNotAvailable(RuntimeError):
    """站点级预测不可用（该站在数据窗口内无叶绿素a 序列，或引擎未就绪）。"""


# ---------- 机理模块（logistic-monod 指数，成员C 框架适配） ----------

def _temperature_limit(temp_c: float) -> float:
    distance = (temp_c - _MECH_TEMPERATURE_OPT_C) / _MECH_TEMPERATURE_WIDTH_C
    return float(np.clip(math.exp(-(distance * distance)), 0.0, 1.0))


def _monod(value: float, half_saturation: float) -> float:
    if value <= 0:
        return 0.0
    return float(np.clip(value / (value + half_saturation), 0.0, 1.0))


def _do_stress(do_mg_l: float) -> float:
    return float(np.clip((8.0 - do_mg_l) / 6.0, 0.0, 1.0))


def mechanism_components(tp: float, tn: float, wt: float, do: float) -> dict[str, float]:
    return {
        "temperature": _temperature_limit(wt),
        "phosphorus": _monod(tp, _MECH_TP_HALF_SAT),
        "nitrogen": _monod(tn, _MECH_TN_HALF_SAT),
        "dissolved_oxygen": _do_stress(do),
    }


def mechanism_from_components(components: dict[str, float]) -> float:
    score = sum(_MECH_WEIGHTS[key] * components[key] for key in _MECH_WEIGHTS)
    return float(np.clip(score, 0.0, 1.0))


# ---------- 特征与样本表 ----------

_FEATURES_RAW = (
    "chlorophyll_a", "cyanobacteria_density", "water_temperature", "total_phosphorus",
    "total_nitrogen", "ammonia_nitrogen", "dissolved_oxygen", "pH", "turbidity",
    "conductivity", "cod_mn",
)

_FEATURE_COLUMNS = (
    "chla", "chla_lag24", "density", "water_temperature", "total_phosphorus",
    "total_nitrogen", "dissolved_oxygen", "pH", "turbidity_log", "conductivity",
    "cod_mn", "ammonia_nitrogen", "hod_sin", "hod_cos", "mechanism",
)

_FEATURE_LABELS = {
    "chla": "叶绿素a（当前）",
    "chla_lag24": "叶绿素a（24h前）",
    "density": "蓝藻密度",
    "water_temperature": "水温",
    "total_phosphorus": "总磷",
    "total_nitrogen": "总氮",
    "dissolved_oxygen": "溶解氧",
    "pH": "pH",
    "turbidity_log": "浊度（对数）",
    "conductivity": "电导率",
    "cod_mn": "高锰酸盐指数",
    "ammonia_nitrogen": "氨氮",
    "hod_sin": "日内周期（sin）",
    "hod_cos": "日内周期（cos）",
    "mechanism": "机理指数",
}

BAND_LABELS = {
    "none": "正常（<10 μg/L）",
    "light": "轻度筛查（10–25 μg/L）",
    "moderate": "中度筛查（≥25 μg/L）",
}


def band_of(chla: float) -> str:
    if chla >= CHLA_MODERATE:
        return "moderate"
    if chla >= CHLA_LIGHT:
        return "light"
    return "none"


def _latest_within(sub: pd.DataFrame, t: pd.Timestamp) -> dict[str, float]:
    window = sub[(sub["ts"] <= t) & (sub["ts"] >= t - pd.Timedelta(hours=FEATURE_LAG_WINDOW_H))]
    features: dict[str, float] = {}
    for code, group in window.groupby("variable_code"):
        value = group.sort_values("ts").iloc[-1]["value"]
        if value == value:  # NaN 防御
            features[code] = float(value)
    return features


def _chla_near(chla: pd.DataFrame, t_target: pd.Timestamp) -> float | None:
    window = chla[(chla["ts"] >= t_target - pd.Timedelta(hours=TARGET_MATCH_TOL_H))
                  & (chla["ts"] <= t_target + pd.Timedelta(hours=TARGET_MATCH_TOL_H))]
    if window.empty:
        return None
    return float(window.loc[(window["ts"] - t_target).abs().idxmin(), "value"])


def build_origin_table(frame: pd.DataFrame) -> pd.DataFrame:
    """从 silver observations 全量帧构建样本表（每站每叶绿素a 观测时点一行）。

    输入帧约定（MeeRealtimeObservationProvider.observation_history）：列
    station_entity_id / observed_at(ISO str) / variable_code / value / observation_status。
    同一站点同一时点的重复上报（跨快照订正）取最新版本。
    """
    if frame is None or frame.empty:
        raise StationForecastNotAvailable("实时观测帧为空，站点预测引擎无法构建样本")
    ok = frame[frame["observation_status"] == "ok"].copy()
    ok = ok.drop_duplicates(["station_entity_id", "observed_at", "variable_code"], keep="last")
    ok["ts"] = pd.to_datetime(ok["observed_at"], utc=True)
    rows: list[dict[str, Any]] = []
    for sid, sub in ok.groupby("station_entity_id"):
        chla = sub[sub["variable_code"] == "chlorophyll_a"][["ts", "value"]]
        if chla.empty:
            continue
        for t in sorted(chla["ts"].unique()):
            features = _latest_within(sub, pd.Timestamp(t))
            if "chlorophyll_a" not in features:
                continue
            rec: dict[str, Any] = {
                "sid": sid,
                "t": pd.Timestamp(t),
                "chla_lag24": _chla_near(chla, pd.Timestamp(t) - pd.Timedelta(hours=24)),
            }
            rec.update({code: features.get(code) for code in _FEATURES_RAW})
            rows.append(rec)
    table = pd.DataFrame(rows)
    if table.empty:
        raise StationForecastNotAvailable("实时观测帧中无叶绿素a 观测序列，站点预测引擎无法训练")
    return table


def feature_frame(table: pd.DataFrame) -> pd.DataFrame:
    """样本表 → 特征矩阵（列顺序 = _FEATURE_COLUMNS；缺失中位数填充）。

    填充先于机理指数计算，保证机理组件永远可计算。
    """
    filled: dict[str, pd.Series] = {}
    for code in _FEATURES_RAW + ("chla_lag24",):
        median = table[code].median()
        filled[code] = table[code].fillna(median if median == median else 0.0)
    out = pd.DataFrame(index=table.index)
    out["chla"] = np.log1p(filled["chlorophyll_a"])
    out["chla_lag24"] = np.log1p(filled["chla_lag24"])
    out["density"] = np.log1p(filled["cyanobacteria_density"])
    out["water_temperature"] = filled["water_temperature"]
    out["total_phosphorus"] = filled["total_phosphorus"]
    out["total_nitrogen"] = filled["total_nitrogen"]
    out["dissolved_oxygen"] = filled["dissolved_oxygen"]
    out["pH"] = filled["pH"]
    out["turbidity_log"] = np.log1p(filled["turbidity"])
    out["conductivity"] = filled["conductivity"]
    out["cod_mn"] = filled["cod_mn"]
    out["ammonia_nitrogen"] = filled["ammonia_nitrogen"]
    hours = table["t"].dt.hour
    out["hod_sin"] = np.sin(2 * np.pi * hours / 24)
    out["hod_cos"] = np.cos(2 * np.pi * hours / 24)
    out["mechanism"] = [
        mechanism_from_components(mechanism_components(tp, tn, wt, do))
        for tp, tn, wt, do in zip(
            filled["total_phosphorus"], filled["total_nitrogen"],
            filled["water_temperature"], filled["dissolved_oxygen"],
        )
    ]
    return out[list(_FEATURE_COLUMNS)]


# ---------- 岭回归（numpy，无新增依赖） ----------

class RidgeModel:
    """标准化岭回归（截距不正则）。系数用于线性归因。"""

    def __init__(self, lam: float = RIDGE_LAMBDA) -> None:
        self.lam = lam
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.coef_: np.ndarray | None = None   # 标准化空间系数
        self.intercept_: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RidgeModel":
        self.mean_ = X.mean(axis=0)
        std = X.std(axis=0)
        std[std == 0] = 1.0
        self.std_ = std
        Z = (X - self.mean_) / std
        design = np.hstack([Z, np.ones((len(Z), 1))])
        penalty = np.eye(design.shape[1]) * self.lam
        penalty[-1, -1] = 0.0
        weights = np.linalg.solve(design.T @ design + penalty, design.T @ y)
        self.coef_ = weights[:-1]
        self.intercept_ = float(weights[-1])
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.mean_) / self.std_
        return Z @ self.coef_ + self.intercept_

    def contributions(self, X: np.ndarray) -> np.ndarray:
        """每个样本的特征贡献（log 空间）= 标准化系数 × 标准化偏差。"""
        Z = (X - self.mean_) / self.std_
        return Z * self.coef_


def _band_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    true_bands = np.array([band_of(v) for v in y_true])
    pred_bands = np.array([band_of(v) for v in y_pred])
    return float((true_bands == pred_bands).mean())


# ---------- 引擎 ----------

class StationForecastEngine:
    """按实时目录签名懒构建/重建的站点级预测引擎。forecast() 返回 API data 部分。"""

    def __init__(self, provider) -> None:
        self._provider = provider
        self._lock = threading.RLock()
        self._signature: tuple[int, int] | None = None
        self._built = False
        self._build_error: str | None = None
        self._table: pd.DataFrame | None = None
        self._features: pd.DataFrame | None = None
        self._models: dict[int, RidgeModel] = {}
        self._evaluations: dict[int, dict[str, Any]] = {}
        self._residuals: dict[int, np.ndarray] = {}
        self._served_horizons: list[int] = []
        self._blocked_horizons: list[dict[str, Any]] = []
        self._card: dict[str, Any] = {}

    # ---- 构建 ----

    def _ensure_built(self) -> None:
        signature = self._provider.catalog_signature()
        if self._built and signature == self._signature:
            return
        with self._lock:
            signature = self._provider.catalog_signature()
            if self._built and signature == self._signature:
                return
            self._build_error = None
            try:
                self._rebuild()
            except StationForecastNotAvailable as exc:
                self._built = False
                self._build_error = str(exc)
                raise
            self._signature = signature
            self._built = True

    def _rebuild(self) -> None:
        table = build_origin_table(self._provider.observation_history())
        features = feature_frame(table)
        X = features.to_numpy(dtype=float)

        # 目标列：逐站匹配 t+H 的最近叶绿素a（±6h），不跨站取数
        chla_by_sid: dict[str, pd.DataFrame] = {}
        for sid, sub in table.groupby("sid"):
            chla_by_sid[sid] = pd.DataFrame({"ts": sub["t"], "value": sub["chlorophyll_a"]})

        models: dict[int, RidgeModel] = {}
        evaluations: dict[int, dict[str, Any]] = {}
        residuals: dict[int, np.ndarray] = {}
        served: list[int] = []
        blocked: list[dict[str, Any]] = []
        for horizon in HORIZONS_H:
            target = [
                _chla_near(chla_by_sid[row.sid], row.t + pd.Timedelta(hours=horizon))
                for row in table.itertuples()
            ]
            y_raw = pd.array([np.nan if v is None else v for v in target], dtype=float)
            valid_mask = ~np.isnan(np.asarray(y_raw, dtype=float))
            n_valid = int(valid_mask.sum())
            if n_valid < MIN_SAMPLES_PER_HORIZON:
                blocked.append({
                    "horizon_days": horizon // 24,
                    "reason": "insufficient_samples",
                    "detail": f"有效样本 {n_valid} 条 < 门槛 {MIN_SAMPLES_PER_HORIZON} 条",
                })
                continue
            X_valid = X[valid_mask]
            y_log = np.log1p(np.asarray(y_raw, dtype=float)[valid_mask])
            valid_table = table.loc[valid_mask].reset_index(drop=True)
            evaluation, fold_residuals = self._blocked_cv(X_valid, y_log, valid_table)
            n_cv_test = sum(entry["n_test"] for entry in evaluation["folds"])
            if n_cv_test < MIN_CV_TEST_SAMPLES:
                blocked.append({
                    "horizon_days": horizon // 24,
                    "reason": "insufficient_cv_coverage",
                    "detail": f"交叉验证测试样本 {n_cv_test} 条 < 门槛 {MIN_CV_TEST_SAMPLES} 条",
                })
                continue
            if evaluation["mae_ugl"] > evaluation["mae_persistence_ugl"]:
                blocked.append({
                    "horizon_days": horizon // 24,
                    "reason": "no_skill_vs_persistence",
                    "detail": (
                        f"交叉验证 MAE {evaluation['mae_ugl']:.2f} μg/L 劣于持续性基线 "
                        f"{evaluation['mae_persistence_ugl']:.2f} μg/L，按诚实门槛不提供数值预测"
                    ),
                })
                continue
            models[horizon] = RidgeModel().fit(X_valid, y_log)
            evaluations[horizon] = evaluation
            residuals[horizon] = fold_residuals
            served.append(horizon // 24)
        if not served:
            raise StationForecastNotAvailable(
                "所有提前期未通过样本量/基线门槛：" + "；".join(b["detail"] for b in blocked)
            )
        self._table = table
        self._features = features
        self._models = models
        self._evaluations = evaluations
        self._residuals = residuals
        self._served_horizons = served
        self._blocked_horizons = blocked
        self._card = self._build_card(table, served, blocked, evaluations)

    def _blocked_cv(self, X: np.ndarray, y_log: np.ndarray, valid: pd.DataFrame) -> tuple[dict[str, Any], np.ndarray]:
        """按目标日分块的时间交叉验证；返回汇总指标 + 折外残差池（log 空间）。"""
        days = valid["t"].dt.date.to_numpy()
        fold_rows: list[dict[str, Any]] = []
        residual_pool: list[np.ndarray] = []
        mae_list, mae_persist_list, band_list, r2_list = [], [], [], []
        for day in sorted(set(days)):
            test = days == day
            train = ~test
            if test.sum() < MIN_FOLD_TEST or train.sum() < 20:
                continue
            model = RidgeModel().fit(X[train], y_log[train])
            pred = model.predict(X[test])
            residual_pool.append(y_log[test] - pred)
            y_true = np.expm1(y_log[test])
            y_hat = np.expm1(pred)
            persistence = valid.loc[test, "chlorophyll_a"].to_numpy(dtype=float)
            mae_list.append(float(np.mean(np.abs(y_true - y_hat))))
            mae_persist_list.append(float(np.mean(np.abs(y_true - persistence))))
            band_list.append(_band_accuracy(y_true, y_hat))
            var = float(np.var(y_log[test]))
            r2_list.append(1.0 - float(np.mean((y_log[test] - pred) ** 2)) / var if var > 0 else 0.0)
            fold_rows.append({
                "target_day": day.isoformat(),
                "n_test": int(test.sum()),
                "mae_ugl": round(mae_list[-1], 3),
            })
        pooled = np.concatenate(residual_pool) if residual_pool else np.array([0.0])
        summary = {
            "protocol": "blocked_temporal_cv_by_target_day",
            "folds": fold_rows,
            "mae_ugl": round(float(np.mean(mae_list)), 3),
            "mae_persistence_ugl": round(float(np.mean(mae_persist_list)), 3),
            "band_accuracy": round(float(np.mean(band_list)), 3),
            "r2_log": round(float(np.mean(r2_list)), 3),
        }
        return summary, pooled

    def _build_card(
        self,
        table: pd.DataFrame,
        served: list[int],
        blocked: list[dict[str, Any]],
        evaluations: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        coverage = self._provider.chla_daily_coverage()
        sparse_days = sorted(day for day, count in coverage.items() if count < 5)
        return {
            "model_version": MODEL_VERSION,
            "model_family": MODEL_FAMILY,
            "claim_boundary": CLAIM_BOUNDARY,
            "target": "chlorophyll_a（log1p 空间岭回归）",
            "features": [{"name": name, "label": _FEATURE_LABELS[name]} for name in _FEATURE_COLUMNS],
            "mechanism_module": {
                "model": "logistic_monod_mechanism_station_adapted_v0.1",
                "components": _MECH_WEIGHTS,
                "excluded_inputs": ["光照（无站点观测）", "风速（无站点观测）"],
            },
            "fusion": "cascade(0.4×机理 + 0.6×AI严重度) + 经验残差区间（成员C v0.1 语义）",
            "training": {
                "origin_from": table["t"].min().isoformat(),
                "origin_to": table["t"].max().isoformat(),
                "n_origins": int(len(table)),
                "stations": int(table["sid"].nunique()),
                "sparse_days_utc": sparse_days,
                "sparse_days_note": "叶绿素a 有效报数 <5 条/日的日期（上游断报），该日样本自然缺失",
            },
            "served_horizons_days": served,
            "blocked_horizons": blocked,
            "evaluations": {f"{horizon // 24}d": metrics for horizon, metrics in evaluations.items()},
            "notes": [
                "模型由 MEE 官方站点观测训练，观测未经跨源验证；产出不用于监管决策。",
                "评估为已见站点的时间外推（按目标日分块）；对新站点外推能力有限。",
                "特征贡献为线性模型归因（标准化系数×偏差），非 SHAP / 注意力。",
            ],
        }

    # ---- 查询 ----

    def forecast(self, entity_id: str) -> dict[str, Any]:
        self._ensure_built()
        table = self._table
        features = self._features
        station_mask = (table["sid"] == entity_id).to_numpy()
        if not station_mask.any():
            raise StationForecastNotAvailable(
                f"站点 {entity_id} 在当前数据窗口内无叶绿素a 观测序列；"
                f"站点级预测试点仅覆盖有叶绿素a 序列的 {table['sid'].nunique()} 个站点"
            )
        position = int(np.nonzero(station_mask)[0][-1])   # 时间升序的最后一行 = 最新可预测时点
        origin = table.iloc[position]
        x = features.to_numpy(dtype=float)[position:position + 1]
        mech_score = float(features.iloc[position]["mechanism"])
        mech_components = mechanism_components(
            float(features.iloc[position]["total_phosphorus"]),
            float(features.iloc[position]["total_nitrogen"]),
            float(features.iloc[position]["water_temperature"]),
            float(features.iloc[position]["dissolved_oxygen"]),
        )
        forecasts = []
        for horizon_days in self._served_horizons:
            horizon = horizon_days * 24
            model = self._models[horizon]
            pred_log = float(model.predict(x)[0])
            low_q, high_q = (float(q) for q in np.quantile(self._residuals[horizon], RESIDUAL_QUANTILES))
            value = float(np.expm1(pred_log))
            lower = float(max(0.0, np.expm1(pred_log + low_q)))
            upper = float(np.expm1(pred_log + high_q))
            ranking = sorted(
                zip(_FEATURE_COLUMNS, model.contributions(x)[0]),
                key=lambda item: abs(item[1]),
                reverse=True,
            )[:4]
            fusion_score = float(np.clip(0.4 * mech_score + 0.6 * min(1.0, value / CHLA_MODERATE), 0.0, 1.0))
            forecasts.append({
                "horizon_days": horizon_days,
                "target_time": (origin["t"] + pd.Timedelta(hours=horizon)).isoformat(),
                "chlorophyll_a": {
                    "value": round(value, 2),
                    "unit": "μg/L",
                    "lower_bound": round(lower, 2),
                    "upper_bound": round(upper, 2),
                    "interval_method": "cv_residual_quantile_10_90_log_space",
                },
                "band": band_of(value),
                "band_label": BAND_LABELS[band_of(value)],
                "band_conservative": band_of(upper),
                "risk_score": round(fusion_score * 100),
                "fusion_formula": "0.4×机理指数 + 0.6×min(1, 预测值/25)，×100",
                "mechanism": {
                    "model": "logistic_monod_mechanism_station_adapted_v0.1",
                    "score": round(mech_score, 4),
                    "components": {key: round(val, 4) for key, val in mech_components.items()},
                    "excluded_inputs": ["光照（无站点观测）", "风速（无站点观测）"],
                },
                "drivers": [
                    {
                        "feature": name,
                        "label": _FEATURE_LABELS[name],
                        "contribution_log": round(float(contribution), 4),
                        "direction": "raise" if contribution >= 0 else "lower",
                        "method": "linear_model_attribution",
                    }
                    for name, contribution in ranking
                ],
                "evaluation": self._evaluations[horizon],
            })
        return {
            "station_id": entity_id,
            "origin_time": origin["t"].isoformat(),
            "as_of": self._provider.as_of() or origin["t"].isoformat(),
            "model_card": self._card,
            "forecasts": forecasts,
        }

    def status(self) -> dict[str, Any]:
        """能力披露用摘要；引擎不可用时如实返回原因，不抛错。"""
        try:
            self._ensure_built()
        except StationForecastNotAvailable:
            return {
                "status": "unavailable",
                "model_version": MODEL_VERSION,
                "reason": self._build_error,
            }
        return {
            "status": "pilot_v0.1",
            "model_version": MODEL_VERSION,
            "covered_stations": int(self._table["sid"].nunique()),
            "n_origins": int(len(self._table)),
            "served_horizons_days": list(self._served_horizons),
            "blocked_horizons": self._blocked_horizons,
            "training_window": [self._table["t"].min().isoformat(), self._table["t"].max().isoformat()],
        }
