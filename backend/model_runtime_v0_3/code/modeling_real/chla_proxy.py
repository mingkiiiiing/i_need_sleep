"""站点叶绿素代理标签生成器（公示可复核口径，2026-09-11 主理人授权补档）。

背景：整包数据中「叶绿素实测 × 站点水质实测」共存行数为零（地面 chla 仅 4 个
航次月 + S1 单样本，且这些行不带 TP/TN），导致 T5/T1/T6 无法训练出站点响应。
本模块用「公开文献公式结构 + 本地实测锚点 + 固定种子随机残差」生成站点-月度
chla 代理标签，公式、锚点、残差口径与种子全部公示（写入 manifest），可复核。

公式（对数空间，_public constants 即合同）：
    ln(chla_ug_l) = a + B_TP·ln(TP/TP_ref) + B_TN·ln(TN/TN_ref)
                    + A_SEAS·cos(2π(month - MONTH_PEAK)/12) + ε
    ε ~ N(0, SIGMA)，SIGMA 取「锚点航次样本对数残差标准差」与下限的最大值。
    截距 a 由锚点唯一确定：a = ln(chla_anchor) − 其余各项在锚点处的取值。

锚点（唯一实测营养盐×chla 配对月）：
    2020-12 野外航次 chla 均值（10 样本）↔ 分区站 2020-11 实测 TP/TN 中位数
    （航次为月内混合样，水质取相邻月，披露为 1 个月滞后口径）。

诚实边界（必须随标签落盘并写入 manifest）：
* 这是 proxy_derived 代理标签：站点差异来自「实测 TP/TN 的空间差异经过公示
  响应曲线的传导」，不是独立观测的站点叶绿素；
* 斜率 B_TP/B_TN 与季节振幅取公开文献常用口径，本地仅锚定截距，n_anchor=1，
  绝对水平的不确定性以 SIGMA 兜底；
* 随机性完全由 SEED 决定，重跑可复现（公示的随机）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SCHEMA = "chla_station_proxy_v1"
SEED = 20260911

# ---- 公示公式常数 ----
B_TP = 0.74          # ln-chla 对 ln-TP 弹性（太湖公开研究常用 0.5–1.0 取中值偏上）
B_TN = 0.25          # ln-chla 对 ln-TN 弹性（共限制修正，弱于 TP）
A_SEAS = 0.35        # 季节振幅（ln 单位，≈±42%），峰在 8 月
MONTH_PEAK = 8
TP_REF = 0.0671      # 锚点月（2020-11）分区站 TP 中位数，mg/L
TN_REF = 1.012       # 锚点月（2020-11）分区站 TN 中位数，mg/L
ANCHOR_MONTH_NUTRIENT = "2020-11"
ANCHOR_MONTH_CHLA = "2020-12"
CHLA_MIN_UG_L = 0.5
CHLA_MAX_UG_L = 120.0
SIGMA_FLOOR = 0.35   # 残差下限（ln 单位），锚点样本过少时兜底

PROVENANCE = "chla_station_proxy_v1"
DISCLOSURE = (
    "站点 chla 代理标签（公示口径）：ln(chla)=a+0.74·ln(TP/0.0671)+0.25·ln(TN/1.012)"
    "+0.35·cos(2π(month-8)/12)+ε，ε~N(0,σ)，seed=20260911；截距由 2020-12 航次实测 "
    "chla 均值 × 2020-11 分区站实测 TP/TN 中位数唯一锚定；斜率/季节振幅取公开文献"
    "常用口径。站点差异来自实测营养盐经公示响应曲线的传导，不是独立观测；"
    "消费方必须按 proxy_derived 口径披露。"
)


def _season_term(month: str) -> float:
    m = int(str(month)[5:7])
    return A_SEAS * float(np.cos(2.0 * np.pi * (m - MONTH_PEAK) / 12.0))


def calibrate(base: pd.DataFrame, labels: pd.DataFrame) -> dict:
    """从监督底表 + 标签宽表标定锚点与 σ；返回公示参数（含截距）。"""
    zone_mask = base["station_id"].str.startswith("TAIHU_") & (base["station_id"] != "TAIHU_WHOLE")
    zone_nut = base[zone_mask & (base["month"] == ANCHOR_MONTH_NUTRIENT)]
    tp_ref = float(zone_nut["wq_tp"].median())
    tn_ref = float(zone_nut["wq_tn"].median())
    anchor_chla = labels[
        (labels["station_id"] == "IN_SITU_GROUP") & (labels["month"] == ANCHOR_MONTH_CHLA)
    ]["label_chla_ug_l"].dropna()
    chla_anchor = float(anchor_chla.mean())
    # σ：锚点航次样本在 ln 空间的离散 + 下限兜底
    if len(anchor_chla) >= 3:
        sigma = float(np.std(np.log(anchor_chla.to_numpy(dtype=float)), ddof=1))
    else:
        sigma = SIGMA_FLOOR
    sigma = max(sigma, SIGMA_FLOOR)
    a = float(np.log(chla_anchor) - _season_term(ANCHOR_MONTH_CHLA))
    params = {
        "schema": SCHEMA,
        "seed": SEED,
        "a": round(a, 6),
        "b_tp": B_TP,
        "b_tn": B_TN,
        "a_season": A_SEAS,
        "month_peak": MONTH_PEAK,
        "tp_ref_mg_l": tp_ref,
        "tn_ref_mg_l": tn_ref,
        "sigma_ln": round(sigma, 6),
        "anchor": {
            "chla_month": ANCHOR_MONTH_CHLA,
            "chla_mean_ug_l": round(chla_anchor, 4),
            "chla_n_samples": int(anchor_chla.notna().sum()),
            "nutrient_month": ANCHOR_MONTH_NUTRIENT,
            "tp_mg_l": round(tp_ref, 6),
            "tn_mg_l": round(tn_ref, 6),
            "nutrient_lag_note": "航次为 2020-12 混合样，水质取相邻 2020-11 月，1 个月滞后口径",
        },
        "disclosure": DISCLOSURE,
    }
    return params


def fill_station_chla_proxy(base: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """给「有实测 TP/TN 但无 chla 标签」的常规站行回填代理标签与溯源列。

    只填 label_chla_ug_l 缺失且有实测 wq_tp 的行；已有实测标签的行（航次/S1）不动。
    返回 (base', params)。随机流由固定 SEED 驱动，按行序可复现。
    """
    params = calibrate(base, labels)
    rng = np.random.default_rng(params["seed"])
    base = base.copy()
    if "label_chla_provenance" not in base.columns:
        base["label_chla_provenance"] = None

    tp = pd.to_numeric(base["wq_tp"], errors="coerce")
    tn = pd.to_numeric(base["wq_tn"], errors="coerce")
    # 仅「有实测 TP+TN 且无实测 chla 标签」的行需要补档；IN_SITU/S1 等无水质行
    # 天然被 tp.notna() 排除，已有实测标签的行绝不被覆盖。
    need = base["label_chla_ug_l"].isna() & tp.notna() & tn.notna() & base["month"].notna()
    months = base.loc[need, "month"]
    season = months.map(_season_term).to_numpy(dtype=float)
    mean_ln = (
        params["a"]
        + B_TP * np.log(tp.loc[need].to_numpy(dtype=float) / params["tp_ref_mg_l"])
        + B_TN * np.log(tn.loc[need].to_numpy(dtype=float) / params["tn_ref_mg_l"])
        + season
    )
    sigma = params["sigma_ln"]
    noise = rng.normal(0.0, sigma, size=mean_ln.shape[0])
    chla = np.clip(np.exp(mean_ln + noise), CHLA_MIN_UG_L, CHLA_MAX_UG_L)
    base.loc[need, "label_chla_ug_l"] = np.round(chla, 4)
    base.loc[need, "label_chla_provenance"] = PROVENANCE
    params["filled_rows"] = int(need.sum())
    return base, params
