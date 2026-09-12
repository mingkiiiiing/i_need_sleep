# -*- coding: utf-8 -*-
"""K2 任务1：校准段（OOF+validation） vs 测试段 分布差异对比。

维度：季节（目标月月序）、湖区/站点、目标幅度（actual 分位）、特征缺失率、标签来源。
输出：k2_distribution_compare.json（对比表 + 检验 + 可视化数据）。
只读；不用于选新分位数（红线 4）。测试段分布差异仅作原因诊断。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

import k2_common as K

OUT = K.CALW / "analysis" / "k2_distribution_compare.json"
SERVING_FEATS = None


def _cramers_v(chi2: float, n: int, r: int, c: int) -> float:
    if n == 0 or min(r - 1, c - 1) <= 0:
        return float("nan")
    return float(np.sqrt(chi2 / (n * min(r - 1, c - 1))))


def _cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    """Cliff's delta = P(x>y) - P(x<y)，由 Mann-Whitney U 换算。"""
    if len(x) == 0 or len(y) == 0:
        return float("nan")
    u = stats.mannwhitneyu(x, y, alternative="two-sided").statistic
    return float(2.0 * u / (len(x) * len(y)) - 1.0)


def _mdd_proportion(n1: int, n2: int, p: float = 0.88, alpha: float = 0.05, power: float = 0.8) -> float:
    """两比例检验最小可检出差异（绝对值，百分点）。"""
    if n1 <= 0 or n2 <= 0:
        return float("nan")
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return float((z_a + z_b) * se)


def _se_coverage(p: float, n: int) -> float:
    return float(np.sqrt(p * (1 - p) / n)) if n > 0 else float("nan")


def _ks(x: np.ndarray, y: np.ndarray) -> dict:
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    x = x[np.isfinite(x)]
    y = y[np.isfinite(y)]
    if len(x) < 2 or len(y) < 2:
        return {"ks_stat": None, "p_value": None, "n1": int(len(x)), "n2": int(len(y))}
    r = stats.ks_2samp(x, y)
    return {
        "ks_stat": float(r.statistic),
        "p_value": float(r.pvalue),
        "n1": int(len(x)),
        "n2": int(len(y)),
        "cliffs_delta": _cliffs_delta(x, y),
        "median_x": float(np.median(x)),
        "median_y": float(np.median(y)),
    }


def _categorical(a: pd.Series, b: pd.Series, label: str) -> dict:
    cats = sorted(set(a.dropna().unique()) | set(b.dropna().unique()))
    ca = a.value_counts().reindex(cats, fill_value=0)
    cb = b.value_counts().reindex(cats, fill_value=0)
    table = np.vstack([ca.to_numpy(), cb.to_numpy()])
    # 期望频数 <5 的类别过多会使卡方不可靠；同时给 Fisher/置换结论
    try:
        chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
        v = _cramers_v(chi2, table.sum(), table.shape[0], table.shape[1])
        min_exp = float((np.outer(table.sum(1), table.sum(0)) / table.sum()).min())
    except Exception:  # noqa: BLE001
        chi2, p, dof, v, min_exp = None, None, None, None, None
    # 置换检验（对稀疏类别更稳健）：固定 seed 可复跑，H0 为两段同分布
    try:
        rng = np.random.default_rng(20260912)
        cat_idx = np.concatenate([
            np.repeat(np.arange(len(cats)), ca.to_numpy()),
            np.repeat(np.arange(len(cats)), cb.to_numpy()),
        ])
        n_a = int(ca.sum())
        obs_tab = table / table.sum(1, keepdims=True)
        obs = float(np.sum((obs_tab[0] - obs_tab[1]) ** 2))
        cnt = 0
        for _ in range(2000):
            perm = rng.permutation(cat_idx)
            a_cnt = np.bincount(perm[:n_a], minlength=len(cats)).astype(float)
            b_cnt = np.bincount(perm[n_a:], minlength=len(cats)).astype(float)
            sh_a = a_cnt / max(n_a, 1)
            sh_b = b_cnt / max(len(perm) - n_a, 1)
            if float(np.sum((sh_a - sh_b) ** 2)) >= obs:
                cnt += 1
        perm_p = float((cnt + 1) / (2000 + 1))
    except Exception:  # noqa: BLE001
        perm_p = None
    row = {
        "permutation_p_value": perm_p,
        "n_cal": int(ca.sum()),
        "n_test": int(cb.sum()),
        "share_cal": {c: round(float(x), 4) for c, x in (ca / max(ca.sum(), 1)).items()},
        "share_test": {c: round(float(x), 4) for c, x in (cb / max(cb.sum(), 1)).items()},
        "chi2": None if chi2 is None else float(chi2),
        "dof": None if dof is None else int(dof),
        "p_value": None if p is None else float(p),
        "cramers_v": None if v is None else float(v),
        "min_expected_count": min_exp,
        "max_abs_share_diff": float(np.max(np.abs(
            (ca / max(ca.sum(), 1)).to_numpy() - (cb / max(cb.sum(), 1)).to_numpy()
        ))),
    }
    row["conclusion"] = (
        "分布差异显著(α=0.05)" if (row["p_value"] is not None and row["p_value"] < 0.05)
        else "未见显著差异(α=0.05)"
    )
    if perm_p is not None and perm_p < 0.05 and (row["p_value"] is None or row["p_value"] >= 0.05):
        row["conclusion"] = "卡方不显著但置换检验显著(α=0.05)，按置换结论记为分布差异"
    if min_exp is not None and min_exp < 5:
        row["conclusion"] += "；存在期望频数<5的类别，卡方近似不可靠，以置换检验为准"
    return row


def _q_row(v: np.ndarray) -> dict:
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return {
        "n": int(len(v)),
        "mean": float(np.mean(v)) if len(v) else None,
        "std": float(np.std(v, ddof=1)) if len(v) > 1 else None,
        **{f"p{int(q*100):02d}": float(np.quantile(v, q)) if len(v) else None
           for q in (0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)},
    }


def analyse(case_key: str) -> dict:
    cfg = K.CASES[case_key]
    table, feature_columns = K.build_supervised_table(cfg["offset"])
    bounds = K.cv_split_bounds(table, cfg["split_key"])
    pool = K.load_residual_pool(case_key)
    test, actual_diff = K.load_test_predictions(case_key, table)

    # 特征缺失率：pool 行按 row_id 取回监督表特征；test 行同理
    feats = list(feature_columns)
    feat_idx = table.set_index("row_id")
    pool_feat = feat_idx.reindex(pool["row_id"])[feats]
    test_feat = feat_idx.reindex(test["row_id"])[feats]
    miss = {}
    for c in feats:
        mc = float(pd.to_numeric(pool_feat[c], errors="coerce").isna().mean())
        mt = float(pd.to_numeric(test_feat[c], errors="coerce").isna().mean())
        n1, n2 = len(pool_feat), len(test_feat)
        # 两比例 z 检验
        p_pool = mc if n1 else np.nan
        denom = np.sqrt(max(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2), 1e-12)) if n1 and n2 else np.nan
        z = (mt - mc) / denom if denom and np.isfinite(denom) else None
        pval = float(2 * (1 - stats.norm.cdf(abs(z)))) if z is not None and np.isfinite(z) else None
        miss[c] = {
            "missing_rate_cal": round(mc, 4), "missing_rate_test": round(mt, 4),
            "diff": round(mt - mc, 4), "z": None if z is None else round(float(z), 3),
            "p_value": None if pval is None else float(pval),
        }
    miss_any_cal = float(pd.to_numeric(pool_feat.stack(), errors="coerce").isna().mean())
    miss_any_test = float(pd.to_numeric(test_feat.stack(), errors="coerce").isna().mean())

    p05, p95 = cfg["bundle_p05"], cfg["bundle_p95"]
    test = test.assign(
        covered=(test["residual"] >= p05) & (test["residual"] <= p95),
        low_break=test["residual"] < p05,
        high_break=test["residual"] > p95,
    )

    # 季节/湖区/幅度
    season = _categorical(pool["season"], test["season"], "season")
    zone = _categorical(pool["zone"], test["zone"], "zone")
    actual_ks = _ks(pool["actual"], test["actual"])
    resid_ks = _ks(pool["residual"], test["residual"])
    pred_ks = _ks(pool["prediction"], test["prediction"])

    # 分段覆盖率（测试段），标注 n
    def cov_by(col: str) -> dict:
        out = {}
        for val, g in test.groupby(col):
            out[str(val)] = {
                "n": int(len(g)),
                "covered": int(g["covered"].sum()),
                "coverage": float(g["covered"].mean()),
                "se": _se_coverage(float(g["covered"].mean()), len(g)),
                "residual_median": float(g["residual"].median()),
                "actual_median": float(g["actual"].median()),
                "low_breaks": int(g["low_break"].sum()),
                "high_breaks": int(g["high_break"].sum()),
            }
        return out

    # 校准段分段残差统计（用于对照）
    def res_by(col: str, frame: pd.DataFrame) -> dict:
        out = {}
        for val, g in frame.groupby(col):
            out[str(val)] = {
                "n": int(len(g)),
                "residual_median": float(g["residual"].median()),
                "residual_mean": float(g["residual"].mean()),
                "residual_std": float(g["residual"].std(ddof=1)) if len(g) > 1 else None,
                "actual_median": float(g["actual"].median()),
            }
        return out

    power = {
        "n_cal": int(len(pool)), "n_test": int(len(test)),
        "se_coverage_test_at_0.80": round(_se_coverage(0.80, len(test)), 4),
        "se_coverage_test_at_0.90": round(_se_coverage(0.90, len(test)), 4),
        "mdd_vs_0.88_two_proportion": round(_mdd_proportion(len(pool), len(test)), 4),
        "note": "n<30 的分组其覆盖率 95%CI 半径 >±10pp，单组结论统计效力低，不得据此裁决定根因",
    }

    return {
        "case": case_key,
        "protocol": cfg,
        "split_bounds": bounds,
        "n": {"cal": int(len(pool)), "test": int(len(test))},
        "sanity": {
            "test_actual_vs_supervised_max_abs_diff": actual_diff,
            "test_source_counts": test["source"].value_counts().to_dict() if "source" in test else None,
        },
        "label_provenance": {
            "cal": pool["actual_provenance"].value_counts().to_dict(),
            "test": test["actual_provenance"].value_counts().to_dict(),
            "note": "T+1 测试段含 ground_truth 野外样本，校准池 100% 代理；T+90 两段同为全代理",
        },
        "season": season,
        "zone": zone,
        "target_amplitude": {
            "cal_quantiles": _q_row(pool["actual"]), "test_quantiles": _q_row(test["actual"]),
            "ks": actual_ks,
        },
        "prediction_level": {"cal_quantiles": _q_row(pool["prediction"]),
                             "test_quantiles": _q_row(test["prediction"]), "ks": pred_ks},
        "residual": {
            "cal_quantiles": _q_row(pool["residual"]), "test_quantiles": _q_row(test["residual"]),
            "ks": resid_ks,
            "cal_by_source": {s: _q_row(g["residual"]) for s, g in pool.groupby("source")},
        },
        "missing_rate": {
            "per_feature": miss,
            "overall_missing_rate_cal": round(miss_any_cal, 4),
            "overall_missing_rate_test": round(miss_any_test, 4),
        },
        "coverage_test_by_season": cov_by("season"),
        "coverage_test_by_zone": cov_by("zone"),
        "coverage_test_by_provenance": cov_by("actual_provenance"),
        "coverage_test_overall": {
            "n": int(len(test)), "covered": int(test["covered"].sum()),
            "coverage": float(test["covered"].mean()),
            "low_breaks": int(test["low_break"].sum()),
            "high_breaks": int(test["high_break"].sum()),
        },
        "cal_residual_by_season": res_by("season", pool),
        "cal_residual_by_zone": res_by("zone", pool),
        "power": power,
        "viz": {
            "cal_actual_sorted": np.sort(pool["actual"].to_numpy(float)).round(4).tolist(),
            "test_actual_sorted": np.sort(test["actual"].to_numpy(float)).round(4).tolist(),
            "cal_residual_sorted": np.sort(pool["residual"].to_numpy(float)).round(4).tolist(),
            "test_residual_sorted": np.sort(test["residual"].to_numpy(float)).round(4).tolist(),
            "cal_month_counts": pool.groupby("target_month").size().to_dict(),
            "test_month_counts": test.groupby("target_month").size().to_dict(),
        },
    }


def main() -> None:
    out = {ck: analyse(ck) for ck in K.CASES}
    K.write_json(out, OUT)
    for ck, r in out.items():
        print(f"=== {ck} n_cal={r['n']['cal']} n_test={r['n']['test']}")
        print(f"  season chi2 p={r['season']['p_value']} perm_p={r['season'].get('permutation_p_value')} V={r['season']['cramers_v']}")
        print(f"  zone chi2 p={r['zone']['p_value']} perm_p={r['zone'].get('permutation_p_value')} V={r['zone']['cramers_v']}")
        print("  actual KS:", r["target_amplitude"]["ks"])
        print("  residual KS:", r["residual"]["ks"])
        print("  overall missing cal/test:", r["missing_rate"]["overall_missing_rate_cal"],
              r["missing_rate"]["overall_missing_rate_test"])
        print("  coverage overall:", r["coverage_test_overall"])
    print("[written]", OUT)


if __name__ == "__main__":
    main()
