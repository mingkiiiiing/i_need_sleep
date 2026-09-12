# -*- coding: utf-8 -*-
"""K2 任务3：候选校准方案【离线】评估 —— 事先固定的外层时间回测协议。

红线遵守（本脚本三条硬约束，任何一条违反即产物无效）：
  1. 绝不接入 serving、不改模型：本脚本只读 K1 残差池，输出仅为离线评估表。
  2. 绝不读测试段：本脚本不 import test_predictions.csv，不碰 CV test 块；
     选型与评估只用训练/校准数据（OOF + validation）。
  3. 回测段事先固定：validation 块内最后 BACKTEST_K_MONTHS 个日历月，协议常量
     在运行前写死，不做迭代调参；所有候选分位数只在"内层校准数据"上估计。

回测协议（本文件即协议记录）：
  - 外层回测段 = K1 池中 source==validation 且 target_month 落在
    [validation_max_month - (K-1) 月, validation_max_month] 的行。
    T+1 → 2017-06~2018-05；T+90 → 2016-09~2017-08。
  - 内层校准数据 = OOF 全部 + validation 减去回测段（val_inner）。
    所有候选分位数【只】在内层校准数据上估计，然后在回测段评分。
  - 主回测 K=12（完整季节轮转 1 轮，n≈36）；敏感性 K=24（n≈72）。
  - 如实披露：回测段属 validation 块，该块曾参与族选择与现行池化分位数，
    因此这是"弱外层"验证；完全干净的外层验证只能靠未来冻结段（2024+）。

候选（全部事先固定，无迭代调参）：
  BASE  现行方法在信息受限下的复现：inner 混池有符号分位（无有限样本修正）
  A1    OOF-only 分位
  A2    val_inner-only 分位
  A3    时间加权混池（权重=0.5^(月龄/24)，参考点=回测段首月前一个月）
  B1    inner 混池 + conformal 有限样本修正 k=ceil((n+1)q)
  B2    val_inner + 有限样本修正
  C     位置-尺度标准化：sigma_hat(pred)=OLS(|r|~pred)@inner池，z 分位+FS 修正
  D1    季节分层（inner 池；层内 n<MIN_LAYER_N 回退 B1）
  D2    湖区分层（inner 池；层内 n<MIN_LAYER_N 回退 B1 —— 预期全部回退，仅示范"不强行"）
  X115  B1 分位双侧×1.15 —— 手工放大对照（宽度换覆盖，禁止接入）
  X130  B1 分位双侧×1.30 —— 同上
  BUNDLE 参考（含泄漏）：现行模型内嵌分位数（由全 validation 估出，含回测段自身信息）
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import k2_common as K

OUT = K.CALW / "analysis" / "k2_candidate_backtest.json"

# ---- 协议常量（运行前固定，不做迭代） ----
BACKTEST_K_MONTHS = 12
SENSITIVITY_K_MONTHS = 24
MIN_LAYER_N = 40          # 分层估计最小层内样本；不足回退 B1
HALF_LIFE_MONTHS = 24     # A3 时间加权半衰期
SCALE_UPS = (1.15, 1.30)  # 手工放大对照倍数
ACCEPT = 0.88


def month_ord(m: str) -> int:
    y, mm = str(m).split("-")
    return int(y) * 12 + int(mm)


def fs_quantile(v: np.ndarray, q: float) -> float:
    """conformal 有限样本修正分位：sorted 第 k=ceil((n+1)q) 个。k>n 时外推为 ±inf 的截断。"""
    v = np.sort(np.asarray(v, float))
    n = len(v)
    k = int(np.ceil((n + 1) * q))
    k = min(max(k, 1), n)
    return float(v[k - 1])


def wq_quantile(v: np.ndarray, w: np.ndarray, q: float) -> float:
    """加权分位（累计权重插值）。"""
    order = np.argsort(v)
    v, w = np.asarray(v, float)[order], np.asarray(w, float)[order]
    cw = np.cumsum(w) - 0.5 * w
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def split_backtest(pool: pd.DataFrame, k_months: int) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """返回 (inner, backtest, backtest_start_ord)。"""
    val = pool[pool["source"] == "validation"].copy()
    oof = pool[pool["source"] == "oof"].copy()
    val_max_ord = max(month_ord(m) for m in val["target_month"])
    start_ord = val_max_ord - k_months + 1
    bt = val[val["target_month"].map(month_ord) >= start_ord]
    inner_val = val[val["target_month"].map(month_ord) < start_ord]
    inner = pd.concat([oof, inner_val], ignore_index=True)
    return inner, bt, start_ord


def make_candidates(inner: pd.DataFrame, bt: pd.DataFrame, start_ord: int) -> dict:
    """构造候选 → 每个候选是 row-level (p05,p95) 提供器。"""
    r_inner = inner["residual"].to_numpy(float)
    oof = inner.loc[inner["source"] == "oof", "residual"].to_numpy(float)
    vin = inner.loc[inner["source"] == "validation", "residual"].to_numpy(float)

    # A3 权重：月龄相对回测段开始前 1 个月
    age = inner["target_month"].map(lambda m: max(start_ord - 1 - month_ord(m), 0)).to_numpy(float)
    w = 0.5 ** (age / HALF_LIFE_MONTHS)

    # C：sigma 回归（inner 池）
    x = inner["prediction"].to_numpy(float)
    absr = np.abs(r_inner)
    b1, b0 = np.polyfit(x, absr, 1)  # absr ≈ b0 + b1*pred

    def sigma(pred: np.ndarray) -> np.ndarray:
        return np.maximum(b0 + b1 * np.asarray(pred, float), 0.5)

    z = r_inner / sigma(x)
    z05, z95 = fs_quantile(z, 0.05), fs_quantile(z, 0.95)

    # D1/D2 层估计
    def layered(col: str) -> dict:
        layers = {}
        for key, g in inner.groupby(col):
            if len(g) >= MIN_LAYER_N:
                layers[str(key)] = (fs_quantile(g["residual"].to_numpy(float), 0.05),
                                    fs_quantile(g["residual"].to_numpy(float), 0.95), int(len(g)))
            else:
                layers[str(key)] = None  # 样本不足 → 回退
        return layers

    d1_layers = layered("season")
    d2_layers = layered("zone")
    b1_q = (fs_quantile(r_inner, 0.05), fs_quantile(r_inner, 0.95))

    def global_q(p05: float, p95: float):
        return lambda row: (p05, p95)

    def c_provider(row: pd.Series):
        # 与全局候选一致：返回【残差偏移】，绝对界由 evaluate 统一加 prediction
        s = float(sigma([row["prediction"]])[0])
        return (float(z05 * s), float(z95 * s))

    def layered_provider(layers: dict, col: str):
        n_fallback = sum(1 for v in layers.values() if v is None)
        def f(row: pd.Series):
            lay = layers.get(str(row[col]))
            if lay is None:
                return b1_q
            return lay[0], lay[1]
        f.n_fallback_rows = n_fallback  # 记录回退层数（诊断）
        return f

    cand = {
        "BASE_inner_pooled": global_q(float(np.quantile(r_inner, 0.05)), float(np.quantile(r_inner, 0.95))),
        "A1_oof_only": global_q(float(np.quantile(oof, 0.05)), float(np.quantile(oof, 0.95))),
        "A2_val_inner_only": global_q(float(np.quantile(vin, 0.05)), float(np.quantile(vin, 0.95))),
        "A3_time_weighted": global_q(wq_quantile(r_inner, w, 0.05), wq_quantile(r_inner, w, 0.95)),
        "B1_pooled_fs": global_q(*b1_q),
        "B2_val_inner_fs": global_q(fs_quantile(vin, 0.05), fs_quantile(vin, 0.95)),
        "C_location_scale": c_provider,
        "D1_season_layered": layered_provider(d1_layers, "season"),
        "D2_zone_layered": layered_provider(d2_layers, "zone"),
    }
    meta = {
        "D1_layers": {k: (None if v is None else {"p05": v[0], "p95": v[1], "n": v[2]}) for k, v in d1_layers.items()},
        "D2_layers": {k: (None if v is None else {"p05": v[0], "p95": v[1], "n": v[2]}) for k, v in d2_layers.items()},
        "C_sigma_fit": {"intercept": float(b0), "slope": float(b1),
                        "z_q05_q95": [z05, z95]},
    }
    return cand, meta, b1_q


def evaluate(bt: pd.DataFrame, provider, trim_lower_zero: bool = True) -> dict:
    """回测段评估：覆盖率 / 宽度 / 分段季节覆盖 / 破界方向。"""
    p05s, p95s = [], []
    for _, row in bt.iterrows():
        a, b = provider(row)
        p05s.append(a)
        p95s.append(b)
    p05s = np.asarray(p05s, float)
    p95s = np.asarray(p95s, float)
    lo = p05s + bt["prediction"].to_numpy(float)
    hi = p95s + bt["prediction"].to_numpy(float)
    if trim_lower_zero:
        lo = np.maximum(lo, 0.0)  # 与 serving 口径一致（chla 仅下界 0）
    r = bt["residual"].to_numpy(float)
    covered = (r >= p05s) & (r <= p95s)
    width = hi - lo
    out = {
        "n": int(len(bt)),
        "covered": int(covered.sum()),
        "coverage": float(covered.mean()),
        "width_median": float(np.median(width)),
        "width_mean": float(np.mean(width)),
        "low_breaks": int((r < p05s).sum()),
        "high_breaks": int((r > p95s).sum()),
    }
    by_season = {}
    for s, g in bt.groupby("season"):
        m = covered[bt.index.get_indexer(g.index)]
        by_season[str(s)] = {"n": int(len(g)), "covered": int(m.sum()),
                             "coverage": float(m.mean()) if len(g) else None}
    out["coverage_by_season"] = by_season
    return out


def analyse(case_key: str, k_months: int) -> dict:
    cfg = K.CASES[case_key]
    pool = K.load_residual_pool(case_key)
    inner, bt, start_ord = split_backtest(pool, k_months)
    cand, meta, b1_q = make_candidates(inner, bt, start_ord)

    rows = {"candidates": {}, "meta": meta,
            "protocol": {
                "backtest_k_months": k_months,
                "backtest_target_month_span": [bt["target_month"].min(), bt["target_month"].max()],
                "inner_target_month_span": [inner["target_month"].min(), inner["target_month"].max()],
                "n_inner": int(len(inner)),
                "n_inner_oof": int((inner["source"] == "oof").sum()),
                "n_inner_validation": int((inner["source"] == "validation").sum()),
                "n_backtest": int(len(bt)),
                "min_layer_n": MIN_LAYER_N, "half_life_months": HALF_LIFE_MONTHS,
                "physical_trim": "lower bound clipped to 0 (chla), consistent with serving",
                "leakage_note": "回测段属 validation 块（曾参与族选择与现行池化），属弱外层验证；BUNDLE 行含回测段自身信息，仅参考",
            }}
    for name, provider in cand.items():
        rows["candidates"][name] = evaluate(bt, provider)
        if hasattr(provider, "n_fallback_rows"):
            rows["candidates"][name]["fallback_rows"] = int(provider.n_fallback_rows)
    # BUNDLE 参考（含泄漏）
    rows["candidates"]["BUNDLE_reference_leaky"] = {
        **evaluate(bt, lambda row: (cfg["bundle_p05"], cfg["bundle_p95"])),
        "note": "现行模型内嵌分位（全 validation 估出，含回测段信息）——仅参考，不作选型",
    }
    # 手工放大对照（基于 B1，禁止接入）
    for s in SCALE_UPS:
        rows["candidates"][f"X{int(round(s * 100))}_manual_widening"] = {
            **evaluate(bt, lambda row, s=s: (b1_q[0] * s, b1_q[1] * s)),
            "note": f"手工放大对照 ×{s}：宽度换覆盖，业务信息损失，红线5禁止接入",
        }
    # 选型规则（事先固定）：主回测段覆盖率 ≥ 88% 的候选中宽度中位最小者；
    # 若无候选达 88%，报告最接近者并明确"不满足验收线，不建议接入"
    scores = {n: v for n, v in rows["candidates"].items()
              if not n.startswith("BUNDLE") and not n.startswith("X")}
    passing = {n: v for n, v in scores.items() if v["coverage"] >= ACCEPT}
    if passing:
        best = min(passing, key=lambda n: passing[n]["width_median"])
        rows["selection"] = {"rule": "回测段覆盖率≥88% 中宽度中位最小", "best": best,
                             "passing": sorted(passing), "verdict": "有候选通过"}
    else:
        closest = max(scores, key=lambda n: scores[n]["coverage"])
        rows["selection"] = {"rule": "无候选≥88% → 报告最接近者", "best": closest,
                             "passing": [], "verdict": "无候选达到验收线 → 不建议接入，维持现有限制"}
    return rows


def main() -> None:
    out = {}
    for ck in K.CASES:
        out[ck] = {
            "primary_K12": analyse(ck, BACKTEST_K_MONTHS),
            "sensitivity_K24": analyse(ck, SENSITIVITY_K_MONTHS),
        }
    K.write_json(out, OUT)
    for ck, blk in out.items():
        for tag, run in blk.items():
            print(f"===== {ck} [{tag}] n_bt={run['protocol']['n_backtest']} "
                  f"span={run['protocol']['backtest_target_month_span']}")
            for name, v in run["candidates"].items():
                fb = f" fallback_rows={v['fallback_rows']}" if "fallback_rows" in v else ""
                print(f"  {name:26s} cov={v['coverage']:.4f} ({v['covered']}/{v['n']}) "
                      f"width_med={v['width_median']:.2f} mean={v['width_mean']:.2f} "
                      f"lo/hi={v['low_breaks']}/{v['high_breaks']}{fb}")
            print("  selection:", run["selection"]["verdict"], "→", run["selection"]["best"])
    print("[written]", OUT)


if __name__ == "__main__":
    main()
