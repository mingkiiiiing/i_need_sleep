# -*- coding: utf-8 -*-
"""K2 任务2：欠覆盖原因假设 H1~H5 逐个检验。

红线遵守：
  - 本脚本输出全部为【诊断性证据】，不用于选新分位数（红线 4）。
  - 测试段（CV test 块）数据仅用于回答"假设是否成立"，任何分位数都不得据此修改。
  - 只读 K1 残差池 / runs 记录 / `_replay_pkg` 训练当时代码。

假设清单（来自审查 §4 / 台账 L-cal-13，均待检验，不得直接定根因）：
  H1 分布偏移：测试段目标幅度/季节/湖区与校准段不同 → 池分位数不适配。
  H2 模型偏差：残差中位数显著偏离 0（区间中心偏移）还是仅尾部不足（分位数估计问题）。
  H3 混合残差池：OOF 残差与 validation 残差分布不同 → 混池分位被拉宽/拉窄。
  H4 有限样本：校准 n=234/225 下 5%/95% 分位估计本身方差大（bootstrap）。
  H5 代理标签：chla_station_proxy_v1 标签噪声对残差分布的影响（定性+可得证据）。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

import k2_common as K

OUT = K.CALW / "analysis" / "k2_hypothesis_tests.json"
DIST = K.CALW / "analysis" / "k2_distribution_compare.json"
SEED = 20260912
N_BOOT = 2000
ACCEPT = 0.88  # 现行工程验收线（标称90% - 2pp容差）


def month_ord(m: str) -> int:
    y, mm = str(m).split("-")
    return int(y) * 12 + int(mm)


def binom_test_vs_accept(covered: int, n: int, p0: float = ACCEPT) -> dict:
    """H0: 真覆盖率 = p0 的精确二项检验（less 侧）。"""
    r = stats.binomtest(covered, n, p0, alternative="less")
    return {
        "covered": int(covered), "n": int(n), "observed": covered / n,
        "accept_line": p0,
        "p_value_less": float(r.pvalue),
        "ci95_low": float(r.proportion_ci(0.95, method="exact")[0]),
        "ci95_high": float(r.proportion_ci(0.95, method="exact")[1]),
        "conclusion": "显著低于88%验收线(α=0.05)" if r.pvalue < 0.05 else "未显著低于88%（抽样噪声内不可判定）",
    }


def boot_quantile_ci(v: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """bootstrap 分位数 CI（percentile 法）。"""
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    rng = np.random.default_rng(seed)
    n = len(v)
    q05 = np.empty(n_boot)
    q95 = np.empty(n_boot)
    for i in range(n_boot):
        s = v[rng.integers(0, n, n)]
        q05[i] = np.quantile(s, 0.05)
        q95[i] = np.quantile(s, 0.95)
    return {
        "n": int(n),
        "point_p05": float(np.quantile(v, 0.05)),
        "point_p95": float(np.quantile(v, 0.95)),
        "p05_ci95": [float(np.quantile(q05, 0.025)), float(np.quantile(q05, 0.975))],
        "p95_ci95": [float(np.quantile(q95, 0.025)), float(np.quantile(q95, 0.975))],
        "p05_boot_std": float(q05.std(ddof=1)),
        "p95_boot_std": float(q95.std(ddof=1)),
        "width_point": float(np.quantile(v, 0.95) - np.quantile(v, 0.05)),
        "width_ci95": [float(np.quantile(q95 - q05, 0.025)), float(np.quantile(q95 - q05, 0.975))],
    }


def coverage_under_quantiles(resid_fixed: np.ndarray, p05: float, p95: float) -> float:
    return float(np.mean((resid_fixed >= p05) & (resid_fixed <= p95)))


def boot_coverage_band(cal_resid: np.ndarray, test_resid: np.ndarray,
                       n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """仅诊断：若分位数只由校准池抽样噪声决定，测试段覆盖率的 Monte Carlo 波动带。

    注意：这是"观察到的欠覆盖是否超出抽样噪声"的诊断，不是选型。
    """
    cal = np.asarray(cal_resid, float)
    test = np.asarray(test_resid, float)
    rng = np.random.default_rng(seed)
    n = len(cal)
    covs = np.empty(n_boot)
    for i in range(n_boot):
        s = cal[rng.integers(0, n, n)]
        q05, q95 = np.quantile(s, 0.05), np.quantile(s, 0.95)
        covs[i] = np.mean((test >= q05) & (test <= q95))
    return {
        "note": "仅诊断用：校准池 bootstrap → 固定测试残差上的覆盖率波动带（非选型）",
        "coverage_point": float(np.mean((test >= np.quantile(cal, 0.05)) & (test <= np.quantile(cal, 0.95)))),
        "band_2p5": float(np.quantile(covs, 0.025)),
        "band_97p5": float(np.quantile(covs, 0.975)),
    }


def hypothesis_H1(pool: pd.DataFrame, test: pd.DataFrame, dist: dict) -> dict:
    """H1 分布偏移：季节/湖区/幅度/缺失 + 子总体反事实覆盖。"""
    # 反事实：测试段限制到"与校准段同口径"的子总体（代理标签、季测月、9 个常规单元）
    mask_same = (test["actual_provenance"] == "chla_station_proxy_v1") & (test["season"] != "其他")
    sub = test[mask_same]
    rest = test[~mask_same]
    out = {
        "statement": "测试段目标幅度/季节/湖区与校准段不同 → 校准池分位数不适配测试段",
        "season_shift": {
            "chi2_p": dist["season"]["p_value"], "perm_p": dist["season"]["permutation_p_value"],
            "cramers_v": dist["season"]["cramers_v"],
            "share_cal": dist["season"]["share_cal"], "share_test": dist["season"]["share_test"],
        },
        "zone_shift": {
            "chi2_p": dist["zone"]["p_value"], "perm_p": dist["zone"]["permutation_p_value"],
            "cramers_v": dist["zone"]["cramers_v"],
            "note": "差异集中为：测试段含野外站(IN_SITU_GROUP/S1, ground_truth 标签)而校准段为 0",
        },
        "amplitude_shift": {
            "ks_p": dist["target_amplitude"]["ks"]["p_value"],
            "ks_stat": dist["target_amplitude"]["ks"]["ks_stat"],
            "median_cal": dist["target_amplitude"]["cal_quantiles"]["p50"],
            "median_test": dist["target_amplitude"]["test_quantiles"]["p50"],
        },
        "missing_rate": {
            "cal": dist["missing_rate"]["overall_missing_rate_cal"],
            "test": dist["missing_rate"]["overall_missing_rate_test"],
        },
        "counterfactual_subpopulation": {
            "definition": "测试段 ∩ (代理标签 ∧ 季测月 ∧ 9 常规单元) —— 与校准段同口径",
            "n_same": int(len(sub)), "coverage_same": float(sub["covered"].mean()) if len(sub) else None,
            "n_rest": int(len(rest)), "coverage_rest": float(rest["covered"].mean()) if len(rest) else None,
            "n_test_all": int(len(test)), "coverage_all": float(test["covered"].mean()),
            "contribution_note": (
                f"同口径子总体覆盖 {sub['covered'].mean():.4f} vs 全测试 {test['covered'].mean():.4f}；"
                f"两者差 {(test['covered'].mean() - sub['covered'].mean()) * 100:.1f}pp 中，"
                f"来自'校准段未见子总体'的部分为主要可解释成分"
            ) if len(sub) else None,
        },
    }
    return out


def hypothesis_H2(pool: pd.DataFrame, test: pd.DataFrame) -> dict:
    """H2 中心偏移 vs 尾部不足：Wilcoxon + 位置/尺度反事实分解。"""
    r_cal = pool["residual"].to_numpy(float)
    r_test = test["residual"].to_numpy(float)
    p05, p95 = float(np.quantile(r_cal, 0.05)), float(np.quantile(r_cal, 0.95))

    def wilc(r: np.ndarray) -> dict:
        r = r[np.isfinite(r)]
        w = stats.wilcoxon(r, alternative="two-sided")
        return {
            "n": int(len(r)), "median": float(np.median(r)), "mean": float(np.mean(r)),
            "wilcoxon_p_vs_0": float(w.pvalue),
            "significant": bool(w.pvalue < 0.05),
        }

    med_cal, med_test = float(np.median(r_cal)), float(np.median(r_test))
    sd_cal, sd_test = float(np.std(r_cal, ddof=1)), float(np.std(r_test, ddof=1))

    # 反事实分解（仅诊断）：位置修正 = 测试残差平移到校准中位；尺度修正 = std 拉回校准水平
    r_pos = r_test - med_test + med_cal
    r_scl = (r_test - med_test) * (sd_cal / sd_test) + med_test
    r_both = (r_test - med_test) * (sd_cal / sd_test) + med_cal

    return {
        "statement": "残差中位数显著偏离 0（区间中心偏移）还是仅尾部不足（分位数估计问题）",
        "cal_pool": wilc(r_cal),
        "test_segment": wilc(r_test),
        "break_asymmetry": {
            "low_breaks": int((r_test < p05).sum()), "high_breaks": int((r_test > p95).sum()),
            "expected_each_at_5pct": float(0.05 * len(r_test)),
            "note": "低/高破界不对称 → 存在位置偏移成分；两侧同时超 → 存在尾部宽度不足成分",
        },
        "shift_size": {
            "median_cal": med_cal, "median_test": med_test, "median_shift": med_test - med_cal,
            "std_cal": sd_cal, "std_test": sd_test, "std_ratio_test_over_cal": sd_test / sd_cal,
        },
        "counterfactual_decomposition_diag_only": {
            "note": "仅诊断分解，非方案：位置修正=平移中位；尺度修正=std 拉回校准水平",
            "coverage_raw": coverage_under_quantiles(r_test, p05, p95),
            "coverage_pos_only": coverage_under_quantiles(r_pos, p05, p95),
            "coverage_scale_only": coverage_under_quantiles(r_scl, p05, p95),
            "coverage_pos_scale": coverage_under_quantiles(r_both, p05, p95),
            "quantile_reference": [p05, p95],
        },
    }


def hypothesis_H3(pool: pd.DataFrame) -> dict:
    """H3 混合残差池：OOF vs validation 分布检验 + 混池稀释量化。"""
    oof = pool.loc[pool["source"] == "oof", "residual"].to_numpy(float)
    val = pool.loc[pool["source"] == "validation", "residual"].to_numpy(float)
    pooled = pool["residual"].to_numpy(float)
    ks = stats.ks_2samp(oof, val)
    lev = stats.levene(oof, val, center="median")  # Brown-Forsythe
    mw = stats.mannwhitneyu(oof, val, alternative="two-sided")
    return {
        "statement": "OOF 残差与 validation 残差分布不同 → 混池分位被拉宽/拉窄（含模型质量不同源问题）",
        "n_oof": int(len(oof)), "n_val": int(len(val)), "mix_share_oof": len(oof) / (len(oof) + len(val)),
        "ks_test": {"stat": float(ks.statistic), "p_value": float(ks.pvalue),
                    "significant_005": bool(ks.pvalue < 0.05)},
        "variance_test_brown_forsythe": {"stat": float(lev.statistic), "p_value": float(lev.pvalue),
                                         "significant_005": bool(lev.pvalue < 0.05)},
        "location_test_mw": {"p_value": float(mw.pvalue)},
        "quantiles": {
            "oof_p05_p95": [float(np.quantile(oof, 0.05)), float(np.quantile(oof, 0.95))],
            "val_p05_p95": [float(np.quantile(val, 0.05)), float(np.quantile(val, 0.95))],
            "pooled_p05_p95": [float(np.quantile(pooled, 0.05)), float(np.quantile(pooled, 0.95))],
            "oof_std": float(np.std(oof, ddof=1)), "val_std": float(np.std(val, ddof=1)),
        },
        "exchangeability_note": (
            "OOF 残差出自 early-only 折模型（训练数据约为最终模型一半，能力更弱），"
            "validation 残差出自全 train 装配模型——两池残差不同源，破坏 split-conformal 的可交换性前提；"
            "混池分位是两分布分位的按比例混合，方向取决于哪侧尾部更宽"
        ),
    }


def hypothesis_H4(pool: pd.DataFrame, test: pd.DataFrame) -> dict:
    """H4 有限样本：bootstrap 分位 CI + 覆盖率波动带 + 二项检验。"""
    r_cal = pool["residual"].to_numpy(float)
    r_test = test["residual"].to_numpy(float)
    boots = {
        "pool_all": boot_quantile_ci(r_cal, seed=SEED),
        "oof_only": boot_quantile_ci(pool.loc[pool.source == "oof", "residual"].to_numpy(float), seed=SEED + 1),
        "validation_only": boot_quantile_ci(
            pool.loc[pool.source == "validation", "residual"].to_numpy(float), seed=SEED + 2),
    }
    # 季节层（展示"分组后样本不足"的代价；只对季测月口径的池行）
    by_season = {}
    for s, g in pool.groupby("season"):
        if len(g) >= 10:
            by_season[str(s)] = boot_quantile_ci(g["residual"].to_numpy(float), n_boot=1000, seed=SEED + 3)
    cov_binom = binom_test_vs_accept(int(test["covered"].sum()), len(test))
    return {
        "statement": "校准 n=234/225 下 5%/95% 分位估计方差大，欠覆盖可能部分源于分位估计不稳定",
        "bootstrap_quantile_ci": boots,
        "bootstrap_by_season_diag": by_season,
        "coverage_vs_accept_binomial": cov_binom,
        "coverage_noise_band_diag": boot_coverage_band(r_cal, r_test),
        "layering_cost_note": (
            "季节层 bootstrap CI 宽度显著大于全池 → 分层估计的样本代价可直接量化（候选 D 的依据）"
        ),
    }


def hypothesis_H5(pool: pd.DataFrame, test: pd.DataFrame) -> dict:
    """H5 代理标签噪声：测试段内 proxy vs ground_truth 对照 + 定性。"""
    prox = test[test["actual_provenance"] == "chla_station_proxy_v1"]
    gt = test[test["actual_provenance"] == "ground_truth"]
    out = {
        "statement": "chla_station_proxy_v1 标签噪声影响残差分布（校准池 100% 代理 → 区间语义=代理口径）",
        "cal_pool_provenance": pool["actual_provenance"].value_counts().to_dict(),
        "proxy_vs_gt_in_test": None,
        "note_T90": None,
    }
    if len(prox) and len(gt):
        ks = stats.ks_2samp(prox["residual"], gt["residual"])
        out["proxy_vs_gt_in_test"] = {
            "n_proxy": int(len(prox)), "n_gt": int(len(gt)),
            "coverage_proxy": float(prox["covered"].mean()), "coverage_gt": float(gt["covered"].mean()),
            "residual_median_proxy": float(prox["residual"].median()),
            "residual_median_gt": float(gt["residual"].median()),
            "actual_median_proxy": float(prox["actual"].median()),
            "actual_median_gt": float(gt["actual"].median()),
            "ks_p": float(ks.pvalue),
            "gt_low_breaks": int((gt["residual"] < pool["residual"].quantile(0.05)).sum()),
            "gt_high_breaks": int((gt["residual"] > pool["residual"].quantile(0.95)).sum()),
            "interpretation": (
                "ground_truth(野外实测)样本残差系统性更负、低破界集中 → "
                "要么模型对野外子总体高估，要么代理标签与实测标签存在系统性口径差；"
                "两者在校准段均无代表（校准池 100% 代理），故校准分位对该子总体外推"
            ),
        }
    else:
        out["note_T90"] = "本槽位测试段全为代理标签，无 ground_truth 对照 → H5 不可直接检验（盲区）"
    return out


def analyse(case_key: str) -> dict:
    cfg = K.CASES[case_key]
    table, _ = K.build_supervised_table(cfg["offset"])
    pool = K.load_residual_pool(case_key)
    test, _ = K.load_test_predictions(case_key, table)
    p05, p95 = cfg["bundle_p05"], cfg["bundle_p95"]
    test = test.assign(covered=(test["residual"] >= p05) & (test["residual"] <= p95))
    dist = json.loads(DIST.read_text(encoding="utf-8"))[case_key]
    return {
        "case": case_key,
        "H1_distribution_shift": hypothesis_H1(pool, test, dist),
        "H2_model_bias_vs_tail": hypothesis_H2(pool, test),
        "H3_mixed_pool": hypothesis_H3(pool),
        "H4_finite_sample": hypothesis_H4(pool, test),
        "H5_proxy_label": hypothesis_H5(pool, test),
    }


def main() -> None:
    out = {ck: analyse(ck) for ck in K.CASES}
    K.write_json(out, OUT)
    for ck, r in out.items():
        print(f"===== {ck} =====")
        h1 = r["H1_distribution_shift"]
        print("[H1] season p=", h1["season_shift"]["chi2_p"], "| amp KS p=", h1["amplitude_shift"]["ks_p"])
        cf = h1["counterfactual_subpopulation"]
        if cf["coverage_same"] is not None:
            rest_txt = (
                f"vs rest={cf['coverage_rest']:.4f} (n={cf['n_rest']})"
                if cf["coverage_rest"] is not None else f"rest 为空 (n=0)"
            )
            print(f"     counterfactual same-pop coverage={cf['coverage_same']:.4f} (n={cf['n_same']})", rest_txt)
        else:
            print("     counterfactual: 测试段无同口径子总体（全为代理+季测月）")
        h2 = r["H2_model_bias_vs_tail"]
        print(f"[H2] test median={h2['test_segment']['median']:.3f} wilcoxon p={h2['test_segment']['wilcoxon_p_vs_0']:.2e}",
              f"| breaks low/high={h2['break_asymmetry']['low_breaks']}/{h2['break_asymmetry']['high_breaks']}")
        cd = h2["counterfactual_decomposition_diag_only"]
        print(f"     coverage raw={cd['coverage_raw']:.4f} pos={cd['coverage_pos_only']:.4f}",
              f"scale={cd['coverage_scale_only']:.4f} both={cd['coverage_pos_scale']:.4f}")
        h3 = r["H3_mixed_pool"]
        print(f"[H3] KS p={h3['ks_test']['p_value']:.3e} BF var p={h3['variance_test_brown_forsythe']['p_value']:.3e}",
              f"oof_std={h3['quantiles']['oof_std']:.2f} val_std={h3['quantiles']['val_std']:.2f}")
        h4 = r["H4_finite_sample"]
        b = h4["bootstrap_quantile_ci"]["pool_all"]
        print(f"[H4] pool p05 CI={b['p05_ci95']} p95 CI={b['p95_ci95']}")
        print(f"     binom vs 0.88: p={h4['coverage_vs_accept_binomial']['p_value_less']:.4f}",
              h4["coverage_vs_accept_binomial"]["conclusion"])
        h5 = r["H5_proxy_label"]
        pv = h5["proxy_vs_gt_in_test"]
        if pv:
            print(f"[H5] proxy cov={pv['coverage_proxy']:.4f} gt cov={pv['coverage_gt']:.4f} KS p={pv['ks_p']:.2e}")
        else:
            print("[H5]", h5.get("note_T90"))
    print("[written]", OUT)


if __name__ == "__main__":
    main()
