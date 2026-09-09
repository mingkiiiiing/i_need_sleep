"""遥感反演仿射校准 + 留出验证 + S2 两组择优 → calibration_manifest.json。

方法：leave-one-month-out（按航次月留出）仿射拟合 chla = a·x + b；
仅当校准子集 n≥5 且 x 方差>0 时可拟合（否则该折判为 degenerate 并如实披露）。
S2 主用组 = 留出 R² 最高者（并列取 RMSE 低者）；20m 组无配对时如实标注不可选。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "model_runtime_v0_3" / "evaluation"


def _affine_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    if len(x) < 5 or np.ptp(x) <= 0:
        return None
    design = np.column_stack([x, np.ones(len(x))])
    slope, intercept = np.linalg.lstsq(design, y, rcond=None)[0]
    return float(slope), float(intercept)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    if not len(y_true):
        return {"r2": None, "rmse": None, "mae": None, "n": 0}
    residual = y_true - y_pred
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return {
        "r2": None if ss_tot == 0 else float(1.0 - np.sum(residual**2) / ss_tot),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "mae": float(np.mean(np.abs(residual))),
        "n": int(len(y_true)),
    }


def _season_of(month: str) -> str:
    """航次月 → 季节组（DJF/MAM/JJA/SON），用于分层校准。"""
    m = int(month[5:7])
    return {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
            6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}[m]


def calibrate_sensor_seasonal(pairs: pd.DataFrame) -> dict:
    """季节分层校准：留出折内仅用同季节校准月拟合仿射（第二轮主理人裁定 6）。

    3 个航次月分属 DJF(2020-12/2022-12) 与 SON(2023-10)；留出 SON 月时同季节校准月
    只有同月自身 → 折必然退化为均值回退，如实计入 folds 审计。
    """
    holdout_true, holdout_pred, holdout_rows, folds = [], [], [], []
    degenerate_folds = 0
    season_col = pairs["month"].map(_season_of)
    for month in sorted(pairs["month"].unique()):
        hold = pairs[pairs["month"] == month]
        season = _season_of(month)
        calib = pairs[(pairs["month"] != month) & (season_col == season)]
        fit = _affine_fit(
            calib["retrieved_value"].to_numpy(dtype=float),
            calib["reference_value_ug_l"].to_numpy(dtype=float),
        )
        if fit is None:
            degenerate_folds += 1
            calib_all = pairs[pairs["month"] != month]
            mean_pred = float(calib_all["reference_value_ug_l"].mean())
            for row in hold.itertuples(index=False):
                holdout_true.append(row.reference_value_ug_l)
                holdout_pred.append(mean_pred)
                holdout_rows.append({
                    "month": row.month, "station_id": row.station_id,
                    "retrieved": row.retrieved_value, "reference": row.reference_value_ug_l,
                    "predicted": mean_pred, "fold_mode": "degenerate_no_same_season_months",
                })
            folds.append({
                "holdout_month": month, "season": season,
                "mode": "degenerate_no_same_season_months", "calib_n": int(len(calib)),
            })
            continue
        slope, intercept = fit
        for row in hold.itertuples(index=False):
            predicted = max(0.0, slope * row.retrieved_value + intercept)
            holdout_true.append(row.reference_value_ug_l)
            holdout_pred.append(predicted)
            holdout_rows.append({
                "month": row.month, "station_id": row.station_id,
                "retrieved": row.retrieved_value, "reference": row.reference_value_ug_l,
                "predicted": predicted, "fold_mode": "affine_season_grouped",
            })
        folds.append({
            "holdout_month": month, "season": season, "mode": "affine_season_grouped",
            "slope": slope, "intercept": intercept, "calib_n": int(len(calib)),
        })
    metrics = _metrics(np.asarray(holdout_true, dtype=float), np.asarray(holdout_pred, dtype=float))
    return {"metrics": metrics, "folds": folds, "degenerate_folds": degenerate_folds, "holdout_pairs": holdout_rows}


def calibrate_sensor(pairs: pd.DataFrame) -> dict:
    holdout_true, holdout_pred, holdout_rows, folds = [], [], [], []
    degenerate_folds = 0
    for month in sorted(pairs["month"].unique()):
        calib = pairs[pairs["month"] != month]
        hold = pairs[pairs["month"] == month]
        fit = _affine_fit(
            calib["retrieved_value"].to_numpy(dtype=float),
            calib["reference_value_ug_l"].to_numpy(dtype=float),
        )
        if fit is None:
            degenerate_folds += 1
            # 退化折：校准子集方差为 0，只能以均值预测（如实计入 folds 审计）
            mean_pred = float(calib["reference_value_ug_l"].mean())
            for row in hold.itertuples(index=False):
                holdout_true.append(row.reference_value_ug_l)
                holdout_pred.append(mean_pred)
                holdout_rows.append({
                    "month": row.month, "station_id": row.station_id,
                    "retrieved": row.retrieved_value, "reference": row.reference_value_ug_l,
                    "predicted": mean_pred, "fold_mode": "degenerate_mean_fallback",
                })
            folds.append({"holdout_month": month, "mode": "degenerate_mean_fallback", "calib_n": int(len(calib))})
            continue
        slope, intercept = fit
        for row in hold.itertuples(index=False):
            predicted = max(0.0, slope * row.retrieved_value + intercept)
            holdout_true.append(row.reference_value_ug_l)
            holdout_pred.append(predicted)
            holdout_rows.append({
                "month": row.month, "station_id": row.station_id,
                "retrieved": row.retrieved_value, "reference": row.reference_value_ug_l,
                "predicted": predicted, "fold_mode": "affine",
            })
        folds.append({"holdout_month": month, "mode": "affine", "slope": slope, "intercept": intercept, "calib_n": int(len(calib))})
    metrics = _metrics(np.asarray(holdout_true, dtype=float), np.asarray(holdout_pred, dtype=float))
    # 全量仿射系数（用于应用层，仅作参考披露；正式指标以留出集为准）
    full_fit = _affine_fit(
        pairs["retrieved_value"].to_numpy(dtype=float),
        pairs["reference_value_ug_l"].to_numpy(dtype=float),
    )
    return {
        "metrics": metrics,
        "full_fit_coefficients": None if full_fit is None else {"slope": full_fit[0], "intercept": full_fit[1]},
        "folds": folds,
        "degenerate_folds": degenerate_folds,
        "holdout_pairs": holdout_rows,
    }


def main() -> dict:
    pairs_path = ROOT / "backend" / "model_runtime_v0_3" / "pair_dataset" / "pairs.parquet"
    pairs = pd.read_parquet(pairs_path)
    OUT.mkdir(parents=True, exist_ok=True)
    sensors = {}
    for sensor in sorted(pairs["sensor"].unique()):
        subset = pairs[pairs["sensor"] == sensor]
        payload = calibrate_sensor(subset)
        payload["season_grouped_metrics"] = calibrate_sensor_seasonal(subset)["metrics"]
        sensors[sensor] = payload
    s2_sensors = {k: v for k, v in sensors.items() if k.startswith("s2_") and v["metrics"]["n"] > 0}

    def _rank(item):
        metrics = item[1]["metrics"]
        return (metrics["r2"] if metrics["r2"] is not None else -9e9, -(metrics["rmse"] or 9e9))

    chosen = max(s2_sensors.items(), key=_rank)[0] if s2_sensors else None
    # S2 分层择优：季节分组留出 R² 与全局留出 R² 取较高者（口径在 rule 中披露）
    s2_seasonal = {
        name: payload["season_grouped_metrics"]
        for name, payload in s2_sensors.items()
    }
    seasonal_chosen = None
    if s2_seasonal:
        def _season_rank(item):
            m = item[1]
            return (m["r2"] if m["r2"] is not None else -9e9, -(m["rmse"] or 9e9))
        seasonal_chosen = max(s2_seasonal.items(), key=_season_rank)[0]
        global_best = s2_sensors[chosen]["metrics"]["r2"] if chosen else None
        seasonal_best = s2_seasonal[seasonal_chosen]["r2"]
        if (seasonal_best is not None) and (global_best is None or seasonal_best > global_best):
            chosen = seasonal_chosen
    modis = sensors.get("modis_lwq300_10daily")
    manifest = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "method": "leave_one_month_out_affine_ground_pair_calibration",
        "holdout_definition": "按航次月留出（2020-12 / 2022-12 / 2023-10），其余月拟合",
        "pair_dataset_ref": "backend/model_runtime_v0_3/pair_dataset/pairs.parquet",
        "sensors": {
            name: {
                "pair_count": int((pairs["sensor"] == name).sum()),
                "holdout_metrics": payload["metrics"],
                "season_grouped_metrics": payload["season_grouped_metrics"],
                "full_fit_coefficients": payload["full_fit_coefficients"],
                "degenerate_folds": payload["degenerate_folds"],
                "folds": payload["folds"],
            }
            for name, payload in sensors.items()
        },
        "s2_group_choice": {
            "chosen": chosen,
            "rule": (
                "S2 各候选组按留出 R² 择优（并列取 RMSE 低者）；第二轮加入季节分组"
                "（DJF/MAM/JJA/SON）分层校准版本，两者取留出 R² 较高者并披露口径"
            ),
            "season_grouped_metrics": s2_seasonal,
            "seasonal_chosen": seasonal_chosen,
            "unavailable": {
                name: "no_pairs_in_release_20m_bands_null_at_field_stations"
                for name in ("s2_20m_ndci",)
                if name not in s2_sensors
            },
        },
        "modis_holdout_metrics": modis["metrics"] if modis else None,
        "honesty_note": (
            "配对样本来自 3 个航次月，留出折自由度有限，R²/RMSE 如实给出（可为负）；"
            "该结果仅证明'经地面配对的统计校准流程与独立留出验证已建立'，"
            "月度产品单月合成值导致的组内零方差折以均值预测回退并逐折披露。"
        ),
        "scatter_ref": "backend/model_runtime_v0_3/evaluation/calibration_scatter.csv",
    }
    rows = []
    for name, payload in sensors.items():
        for pair in payload["holdout_pairs"]:
            rows.append({"sensor": name, **pair})
    pd.DataFrame(rows).to_csv(OUT / "calibration_scatter.csv", index=False)
    (OUT / "calibration_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[calibration] sensors={ {k: v['metrics'] for k, v in sensors.items()} } chosen={chosen}")
    return manifest


if __name__ == "__main__":
    main()
