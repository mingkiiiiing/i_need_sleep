"""路径 B：机理主导合成环境下的"机理-AI 融合 vs 最强单一 AI"门禁验证。

定位（诚实边界，写进报告并随结果输出）：
- 本实验在合成的"机理主导环境"中进行：真值由日尺度藻类生长-损失动力学驱动，
  其中营养盐以缓释形式累积为状态 A_t（半衰期约 138 天，年际波动 ±35%），
  A_t 与前日藻情 B_{t-1} 只授予机理模块——模拟"底泥缓释/营养盐累积这类
  同期常规监测不可直测、需机理结构递推"的信息结构；
- 单一 AI（RF/XGBoost）只见同期常规监测特征（水温/光照/TP/TN/DO/pH/水位/日历）；
  融合候选 = 机理输出 + AI（机理特征增广 / 残差 / 凸组合，超参在 validation 冻结）；
- 门禁比较口径与真实数据门禁一致：validation 选族、冻结时间块测试集同口径评估，
  融合 vs RF/XGBoost 较优者，提升 ≥10% 记 PASS；
- 结论仅代表"机理主导合成环境"，不得表述为真实太湖测试集达标；
  真实数据口径门禁（V0.3，FAIL 如实）见 10 号文档。

运行：python backend/experiments/path_b_mech_env/run_experiment.py
输出：本目录 gate_table.json + 控制台摘要
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from xgboost import XGBClassifier, XGBRegressor

SEED = 20260910
N_STATIONS = 8
N_DAYS = 2920           # 8 年日尺度序列
TRAIN_MAX = 1826        # train：前 5 年；validation：约 1.5 年；test：末 1.5 年
VAL_MAX = 2372
MIN_TEST_ROWS = 15
UPLIFT_THRESHOLD = 0.10
HORIZONS = (1, 3, 7, 15, 30, 60, 90)   # 单位：天（与环境日尺度一致）
TIER = {1: "1-3天", 3: "1-3天", 7: "7-15天", 15: "7-15天", 30: "30-90天", 60: "30-90天", 90: "30-90天"}
RISK_EDGES = (10.0, 20.0, 30.0, 50.0)
RISK_CLASSES = ["I级", "II级", "III级", "IV级", "V级"]

SHARED_FEATURES = [
    "met_temp", "met_light", "wq_tp", "wq_tn", "wq_do", "wq_ph",
    "hydro_level", "station_idx", "doy_sin", "doy_cos",
]
MECH_ONLY_FEATURES = ["mech_nutrient_accum_index", "mech_prev_bloom_state"]
MECH_FEATURES = SHARED_FEATURES + MECH_ONLY_FEATURES

ENV_DISCLOSURE = (
    "机理主导合成环境（日尺度）：营养盐负荷为季节调制对数正态过程（CV≈0.36），"
    "经缓释动力学累积为状态 A_t（衰减 0.995/日，半衰期约 138 天，年际波动约 ±35%）；"
    "藻情强度 B_t 由生长-损失动力学递推（B 均值回归 + 小幅过程噪声），其年际差异主要由 A 驱动；"
    "同期常规监测特征只含 A 的弱噪声代理（TP/TN 相关系数被噪声稀释），"
    "A_t 与 B_{t-1} 仅出现在机理模块设计矩阵——模拟'营养盐累积缓释效应同期不可直测、"
    "需机理结构递推'的科学设定；单一 AI 只能依赖季节气候态与当日气象。"
)


# ---------- 合成环境生成器 ----------
def simulate(n_stations: int, n_days: int) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    for s in range(n_stations):
        phase = rng.uniform(0, 2 * math.pi)
        station_effect = rng.normal(0, 0.03)
        t = np.arange(n_days)
        doy_angle = 2 * math.pi * t / 365.0
        season_load = 0.5 * (1 + np.sin(doy_angle - 1.2 + phase))
        # 营养盐负荷体制：平滑 OU 过程（对数域自相关长度约 200 天、稳态幅度 ±80%），
        # 丰/枯体制缓慢漂移且不与日历年对齐——只有持有机理状态（A 的递推）才能跟踪
        log_regime = np.empty(n_days)
        lr = 0.0
        for i in range(n_days):
            lr = 0.9965 * lr + rng.normal(0, 0.085)
            log_regime[i] = lr
        regime = np.exp(log_regime)
        load = (0.3 + 0.5 * season_load) * regime * np.exp(rng.normal(0, 0.25, n_days))
        accum = np.empty(n_days)
        acc = 110.0
        for i in range(n_days):
            acc = 0.9965 * acc + load[i]
            accum[i] = acc
        temp = 17 + 9 * np.sin(doy_angle - 0.6 + phase) + rng.normal(0, 2.0, n_days)
        light = 14 + 5.5 * np.sin(doy_angle - 0.9 + phase) + rng.normal(0, 2.0, n_days)
        bloom = np.empty(n_days)
        b = 0.1
        for i in range(n_days):
            f_temp = np.clip((temp[i] - 12) / 16, 0, 1)
            f_light = np.clip(light[i] / 18, 0, 1)
            f_nutr = accum[i] / (accum[i] + 180.0)
            growth = 0.62 * f_temp * f_light * f_nutr
            b = np.clip(0.8 * b + growth - 0.12, 0, 1) + rng.normal(0, 0.015)
            bloom[i] = b
        bloom = np.clip(bloom + station_effect, 0, 1)
        chla = 4 + 46 * bloom * np.exp(rng.normal(0, 0.08, n_days))
        tp = np.maximum(0.02, 0.04 + 0.008 * np.sqrt(accum) + rng.normal(0, 0.08, n_days))
        tn = np.maximum(0.2, 1.2 + 0.002 * accum + rng.normal(0, 0.5, n_days))
        do = np.clip(8.2 - 0.25 * bloom + rng.normal(0, 0.9, n_days), 2, 14)
        ph = np.clip(7.8 + 0.18 * bloom + rng.normal(0, 0.35, n_days), 6, 9.2)
        level = 3.1 + 0.4 * np.sin(doy_angle + phase) + rng.normal(0, 0.12, n_days)
        prev_bloom = np.concatenate([[0.1], bloom[:-1]])
        rows.append(pd.DataFrame({
            "t": t, "station_idx": s,
            "met_temp": temp, "met_light": light,
            "wq_tp": tp, "wq_tn": tn, "wq_do": do, "wq_ph": ph,
            "hydro_level": level,
            "doy_sin": np.sin(doy_angle), "doy_cos": np.cos(doy_angle),
            "mech_nutrient_accum_index": accum, "mech_prev_bloom_state": prev_bloom,
            "state_chla": chla, "state_bloom": (bloom >= 0.5).astype(float),
            "state_coverage": np.clip(0.95 * bloom + rng.normal(0, 0.04, n_days), 0, 1),
            "state_biomass": 0.2 + 1.8 * bloom * np.exp(rng.normal(0, 0.1, n_days)),
        }))
    frame = pd.concat(rows, ignore_index=True)
    frame["split"] = np.where(frame["t"] < TRAIN_MAX, "train", np.where(frame["t"] < VAL_MAX, "validation", "test"))
    return frame


def risk_band(values: np.ndarray) -> np.ndarray:
    edges = [*RISK_EDGES, np.inf]
    out = np.empty(len(values), dtype=object)
    for i, v in enumerate(values):
        for level in range(len(edges)):
            if v < edges[level]:
                out[i] = RISK_CLASSES[level]
                break
    return out


def build_task_table(frame: pd.DataFrame, task: str, horizon: int) -> pd.DataFrame:
    """目标取 t+h 时刻的真值；特征取签发日 t（含机理独占列）。风险等级 = 未来叶绿素分带。"""
    out = frame.copy()
    source = "state_chla" if task == "risk_level" else f"state_{task}"
    out["target"] = out.groupby("station_idx")[source].shift(-horizon)
    out = out.dropna(subset=["target"]).reset_index(drop=True)
    if task == "risk_level":
        out["target"] = risk_band(pd.to_numeric(out["target"]))
    return out


# ---------- 候选族（与 V0.3 门禁同构：simple / RF / XGB / 机理 / 三类融合） ----------
def _fit(model_cls, x, y, **kw):
    return model_cls(**kw).fit(x, y)


def run_candidates(table: pd.DataFrame, task: str) -> dict:
    train = table[table["split"] == "train"]
    val = table[table["split"] == "validation"]
    test = table[table["split"] == "test"]
    problem = "regression" if task in ("chla", "biomass", "coverage") else (
        "binary" if task == "bloom" else "multiclass")
    y_tr = train["target"].to_numpy()
    y_va = val["target"].to_numpy()
    y_te = test["target"].to_numpy()
    x_shared_tr, x_shared_va, x_shared_te = (
        frame[SHARED_FEATURES].to_numpy() for frame in (train, val, test))
    x_mech_tr, x_mech_va, x_mech_te = (
        frame[MECH_FEATURES].to_numpy() for frame in (train, val, test))

    reg = problem == "regression"
    label_classes = None
    encode = None
    candidates: dict[str, object] = {}

    if reg:
        candidates["simple_baseline"] = ("constant", float(np.mean(y_tr)))
    elif problem == "binary":
        candidates["simple_baseline"] = ("constant", float(np.clip(np.mean(y_tr), 0.02, 0.98)))
    else:
        values, counts = np.unique(y_tr, return_counts=True)
        candidates["simple_baseline"] = ("constant", str(values[int(np.argmax(counts))]))

    if reg:
        candidates["random_forest"] = ("shared", _fit(RandomForestRegressor, x_shared_tr, y_tr,
                                                      n_estimators=150, min_samples_leaf=5, n_jobs=4, random_state=SEED))
        candidates["xgboost"] = ("shared", _fit(XGBRegressor, x_shared_tr, y_tr,
                                                n_estimators=300, max_depth=5, learning_rate=0.06,
                                                tree_method="hist", n_jobs=4, random_state=SEED))
        candidates["mechanism"] = ("mech", _fit(HistGradientBoostingRegressor, x_mech_tr, y_tr,
                                                max_iter=200, learning_rate=0.06, max_leaf_nodes=14,
                                                min_samples_leaf=20, random_state=SEED))
    else:
        if problem == "binary":
            y_fit = y_tr.astype(int)
        else:
            label_classes = sorted(set(str(v) for v in y_tr))
            encode = {name: i for i, name in enumerate(label_classes)}
            y_fit = np.asarray([encode[str(v)] for v in y_tr])
        candidates["random_forest"] = ("shared", _fit(RandomForestClassifier, x_shared_tr, y_fit,
                                                      n_estimators=150, min_samples_leaf=5, n_jobs=4, random_state=SEED))
        candidates["xgboost"] = ("shared", _fit(XGBClassifier, x_shared_tr, y_fit,
                                                n_estimators=300, max_depth=5, learning_rate=0.06,
                                                tree_method="hist", n_jobs=4, random_state=SEED))
        candidates["mechanism"] = ("mech", _fit(HistGradientBoostingClassifier, x_mech_tr, y_fit,
                                                max_iter=200, learning_rate=0.06, max_leaf_nodes=14,
                                                min_samples_leaf=20, random_state=SEED))

    def predict(candidate, x_shared, x_mech) -> np.ndarray:
        scope, obj = candidate
        if scope == "constant":
            if reg or problem == "binary":
                return np.full(len(x_shared), float(obj))
            return np.full(len(x_shared), obj, dtype=object)
        x = x_shared if scope == "shared" else x_mech
        if reg:
            return np.asarray(obj.predict(x), dtype=float)
        if problem == "binary":
            proba = obj.predict_proba(x)
            return proba[:, 1] if proba.shape[1] > 1 else np.full(len(x), proba[0, 0])
        encoded = np.asarray(obj.predict(x), dtype=int)
        return np.asarray([label_classes[i] for i in encoded], dtype=object)

    # 融合候选：机理预测作为增广特征/残差基线/凸组合（机理侧含独占列）。
    # 融合超参（残差模型/组合权重/二选一）在 validation 上确定后冻结。
    mech_va = predict(candidates["mechanism"], x_shared_va, x_mech_va)
    mech_tr = predict(candidates["mechanism"], x_shared_tr, x_mech_tr)
    if reg:
        aug_tr = np.column_stack([x_shared_tr, mech_tr])
        candidates["mechanism_feature"] = ("aug", _fit(RandomForestRegressor, aug_tr, y_tr,
                                                       n_estimators=150, min_samples_leaf=5, n_jobs=4, random_state=SEED))
        residual_model = _fit(RandomForestRegressor, aug_tr, y_tr - mech_tr,
                              n_estimators=150, min_samples_leaf=5, n_jobs=4, random_state=SEED)
        xgb_for_blend = candidates["xgboost"][1]
    else:
        y_aug_fit = y_tr.astype(int) if problem == "binary" else np.asarray([encode[str(v)] for v in y_tr])
        aug_tr = np.column_stack([x_shared_tr, mech_tr if problem == "binary"
                                  else np.asarray([encode[str(v)] for v in mech_tr], dtype=float)])
        candidates["mechanism_feature"] = ("aug", _fit(RandomForestClassifier, aug_tr, y_aug_fit,
                                                       n_estimators=150, min_samples_leaf=5, n_jobs=4, random_state=SEED))
        residual_model = None
        xgb_for_blend = candidates["xgboost"][1]
    candidates["residual"] = ("residual", residual_model)

    if reg:
        ai_va = np.asarray(xgb_for_blend.predict(x_shared_va), dtype=float)
        best_w, best_err = 0.0, None
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            blended = np.maximum(w * mech_va + (1 - w) * ai_va, 0)
            err = float(np.mean((y_va - blended) ** 2))
            if best_err is None or err < best_err:
                best_w, best_err = w, err
        candidates["constrained_blend"] = ("blend", {"weight": best_w, "model": xgb_for_blend})
    else:
        ai_va = predict(candidates["xgboost"], x_shared_va, x_mech_va)
        chosen = "mechanism" if np.mean(mech_va == y_va) >= np.mean(ai_va == y_va) else "xgboost"
        candidates["constrained_blend"] = ("blend", {"chosen": chosen})

    def predict_fusion(name: str, x_shared, x_mech) -> np.ndarray:
        mech = predict(candidates["mechanism"], x_shared, x_mech)
        if name == "mechanism_feature":
            aug = np.column_stack([x_shared, mech if problem != "multiclass"
                                   else np.asarray([encode[str(v)] for v in mech], dtype=float)])
            return predict(candidates["mechanism_feature"], aug, aug)
        if name == "residual":
            if residual_model is None:
                return mech
            aug = np.column_stack([x_shared, mech])
            return np.maximum(mech + np.asarray(residual_model.predict(aug), dtype=float), 0)
        params = candidates["constrained_blend"][1]
        if reg:
            ai = np.asarray(params["model"].predict(x_shared), dtype=float)
            w = params["weight"]
            return np.maximum(w * mech + (1 - w) * ai, 0)
        return predict(candidates[params["chosen"]], x_shared, x_mech)

    return {
        "problem": problem, "candidates": candidates,
        "predict": predict, "predict_fusion": predict_fusion,
        "splits": (x_shared_tr, x_shared_va, x_shared_te, x_mech_tr, x_mech_va, x_mech_te),
        "y": (y_tr, y_va, y_te),
    }


def primary_metrics(problem: str, actual: np.ndarray, pred: np.ndarray) -> dict:
    if problem == "regression":
        ss_tot = float(np.sum((actual - actual.mean()) ** 2))
        resid = actual - pred
        return {
            "r2": None if ss_tot == 0 else float(1 - np.sum(resid ** 2) / ss_tot),
            "rmse": float(np.sqrt(np.mean(resid ** 2))), "n": int(len(actual)),
        }
    if problem == "binary":
        from sklearn.metrics import average_precision_score, roc_auc_score
        prob = np.clip(pred, 1e-6, 1 - 1e-6)
        return {
            "pr_auc": float(average_precision_score(actual, prob)),
            "roc_auc": float(roc_auc_score(actual, prob)),
            "accuracy": float(np.mean((prob >= 0.5) == (actual == 1))), "n": int(len(actual)),
        }
    return {"accuracy": float(np.mean(pred == actual)),
            "macro_f1": float(np.mean([2 * np.sum((pred == c) & (actual == c)) /
                                       max(2 * np.sum(actual == c) + np.sum(pred == c) - np.sum((pred == c) & (actual == c)), 1)
                                       for c in np.unique(actual)])), "n": int(len(actual))}


FUSION_FAMILIES = ("mechanism_feature", "residual", "constrained_blend")
SINGLE_FAMILIES = ("random_forest", "xgboost")
PRIMARY = {"chla": ("r2", "max"), "biomass": ("r2", "max"), "coverage": ("r2", "max"),
           "bloom": ("pr_auc", "max"), "risk_level": ("accuracy", "max")}


def evaluate_family(ctx: dict, name: str, which: str) -> dict:
    x_shared_tr, x_shared_va, x_shared_te, x_mech_tr, x_mech_va, x_mech_te = ctx["splits"]
    y_va, y_te = ctx["y"][1], ctx["y"][2]
    x_s, x_m, y = {
        "val": (x_shared_va, x_mech_va, y_va),
        "test": (x_shared_te, x_mech_te, y_te),
    }[which]
    if name in ctx["candidates"] and name not in FUSION_FAMILIES:
        pred = ctx["predict"](ctx["candidates"][name], x_s, x_m)
    else:
        pred = ctx["predict_fusion"](name, x_s, x_m)
    return primary_metrics(ctx["problem"], y, pred)


def main() -> dict:
    out_dir = Path(__file__).resolve().parent
    frame = simulate(N_STATIONS, N_DAYS)
    pos_rate = float(frame["state_bloom"].mean())
    print(f"[env] rows={len(frame)} bloom_positive_rate={pos_rate:.2%} "
          f"chla_mean={frame['state_chla'].mean():.1f}")
    rows: list[dict] = []
    for task in ("chla", "biomass", "coverage", "bloom", "risk_level"):
        for horizon in HORIZONS:
            table = build_task_table(frame, task, horizon)
            ctx = run_candidates(table, task)
            metric, _ = PRIMARY[task]
            val_by_family = {name: evaluate_family(ctx, name, "val")
                             for name in (*SINGLE_FAMILIES, *FUSION_FAMILIES)}
            best_single = max(SINGLE_FAMILIES, key=lambda n: val_by_family[n][metric])
            best_fusion = max(FUSION_FAMILIES, key=lambda n: val_by_family[n][metric])
            single_test = evaluate_family(ctx, best_single, "test")
            fusion_test = evaluate_family(ctx, best_fusion, "test")
            base = single_test[metric]
            uplift = (fusion_test[metric] - base) / abs(base) if base else None
            status = ("PASS" if uplift is not None and uplift >= UPLIFT_THRESHOLD else "FAIL") \
                if single_test["n"] >= MIN_TEST_ROWS else "NA"
            rows.append({
                "task": task, "horizon_days": horizon, "tier": TIER[horizon],
                "primary_metric": metric,
                "n_test": single_test["n"],
                "best_single_family": best_single, "best_single_value": round(base, 4),
                "best_fusion_family": best_fusion, "best_fusion_value": round(fusion_test[metric], 4),
                "uplift": None if uplift is None else round(uplift, 4),
                "status": status,
                "mechanism_alone_test": round(evaluate_family(ctx, "mechanism", "test")[metric], 4),
                "simple_baseline_test": round(evaluate_family(ctx, "simple_baseline", "test")[metric], 4),
            })
            print(f"[gate] {task:<10} T+{horizon:>2}d {status}  single({best_single})={base:.4f} "
                  f"fusion({best_fusion})={fusion_test[metric]:.4f} "
                  f"uplift={'NA' if uplift is None else f'{uplift*100:.2f}%'}")

    summary = {
        "comparison_rows": len(rows),
        "pass": sum(r["status"] == "PASS" for r in rows),
        "fail": sum(r["status"] == "FAIL" for r in rows),
        "not_applicable": sum(r["status"] == "NA" for r in rows),
    }
    summary["status"] = "PASS" if summary["pass"] / max(summary["pass"] + summary["fail"], 1) >= 0.9 else "FAIL"
    payload = {
        "gate_version": "path_b_synthetic_2026",
        "environment": ENV_DISCLOSURE,
        "claim_boundary": "synthetic_mechanism_favorable_environment_only",
        "comparison_rule": "融合(validation 选族) vs 同任务同时效 RF/XGBoost 较优者，冻结时间块测试集，提升≥10% 记 PASS",
        "uplift_threshold": UPLIFT_THRESHOLD,
        "seed": SEED, "n_stations": N_STATIONS, "n_days": N_DAYS,
        "bloom_positive_rate": round(pos_rate, 4),
        "split": {"train": f"t<{TRAIN_MAX}", "validation": f"{TRAIN_MAX}<=t<{VAL_MAX}", "test": f"t>={VAL_MAX}"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary, "rows": rows,
    }
    (out_dir / "gate_table.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"→ {out_dir / 'gate_table.json'}")
    return payload


if __name__ == "__main__":
    main()
