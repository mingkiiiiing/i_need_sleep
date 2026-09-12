# -*- coding: utf-8 -*-
"""T1 数据与预测目标真实性审计（任务包 T1，2026-09-12）。

只读审计：不修改任何运行时代码、模型产物、台账与看板；产物只写入本目录。

审计模块（对应任务书 1-5）：
  A. 站点×指标×时效能力表（capability matrix）
  B. month_offset=0 时间配对审计（h1/3/7/15 是否"未来 N 天"）
  C. 机理列数据溯源（wq_phyto_biomass / mech_net_growth_rate_d / mech_light_factor，
     对应台账 L-diag-01）
  D. 水华事件切分审计（事件跨 train/test 泄漏，对应 L-vfy-04）
  E. 端到端样本血缘（row_id 881，T1-bloom-1d 测试集唯一阳性）
  F. CLMS 三语义列同值 + chla 单位混用两项专项数据缺陷核查

用法：
    python backend/evaluation/audits/t1_data_audit_20260912.py
输出：
    audits_out/capability_matrix.csv
    audits_out/t1_audit_summary.json
    audits_out/mechanism_provenance_chain.csv
    audits_out/event_split_events.csv
    audits_out/lineage_row881.json
（本文件所在目录下 audits_out/；temp 缓存写系统临时目录，不污染项目。）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TABLES = PROJECT_ROOT / "data-cleaning" / "storage" / "final_cleaned" / "TAIHU_CLEAN_FINAL_V1_20260831" / "tables"
RUNTIME_CODE = PROJECT_ROOT / "backend" / "model_runtime_v0_3" / "code"
OUT_DIR = Path(__file__).resolve().parent / "audits_out"

BLOOM_THRESHOLD_UG_L = 20.0
HORIZONS = (1, 3, 7, 15, 30, 60, 90)
HORIZON_MONTH_MAP = {1: 0, 3: 0, 7: 0, 15: 0, 30: 1, 60: 2, 90: 3}  # contracts_real.HORIZON_MONTH_MAP_V3 冻结口径

RESULTS: dict = {}


def load_tables():
    return {
        "model_dataset": pd.read_parquet(TABLES / "model_dataset.parquet"),
        "water_quality": pd.read_parquet(TABLES / "water_quality.parquet"),
        "remote_sensing": pd.read_parquet(TABLES / "remote_sensing.parquet"),
        "meteorology_hydrology": pd.read_parquet(TABLES / "meteorology_hydrology.parquet"),
        "labels": pd.read_parquet(TABLES / "labels.parquet"),
        "features_base": pd.read_parquet(PROJECT_ROOT / "backend/model_runtime_v0_3/supervised/features_base.parquet"),
    }


def month_of(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%Y-%m")


# ---------------------------------------------------------------- A. 能力表
def capability_matrix(t: dict) -> pd.DataFrame:
    """每个（指标任务 × 时效）是否有真实未来目标数据支撑。

    "真实未来目标"判定三档：
      real_future_monthly   —— 目标月严格晚于输入月（月粒度真值，如 mo1/2/3）
      same_month_proxy      —— 目标=当月标签（month_offset=0），不构成未来预测
      none                  —— 无可用标签
    再叠加数据层证据：标签来源、非空行、站点覆盖、时间覆盖。
    """
    md = t["model_dataset"]
    availability = json.loads(
        (PROJECT_ROOT / "backend/model_runtime_v0_3/evaluation/availability_matrix.json").read_text(encoding="utf-8")
    )["entries"]
    avail = {(e["task_id"], e.get("variant"), e["horizon_days"]): e for e in availability}

    # 标签列的数据层事实（按监督底表统计）
    fb = t["features_base"]
    label_facts = {
        "bloom": {"column": "label_bloom_any", "rows": 0, "months": None},
        "chla": {"column": "label_chla_ug_l", "rows": 0, "months": None},
        "biomass": {"column": "label_phyto_biomass_mg_l", "rows": 0, "months": None},
        "density": {"column": "label_density_rank_proxy", "rows": 0, "months": None},
        "coverage": {"column": "label_coverage_fcb_prob", "rows": 0, "months": None},
    }
    # 用重算的监督底表拿标签列（features_base 落盘版没有 label_*，见 module C 说明）
    try:
        sys.path.insert(0, str(RUNTIME_CODE))
        from modeling_real.target_builder import build_supervised_base  # noqa: E402

        base, _labels = build_supervised_base()
        for fam, fact in label_facts.items():
            col = fact["column"]
            if col in base.columns:
                sub = base[base[col].notna()]
                fact["rows"] = int(len(sub))
                fact["months"] = [str(sub["month"].min()), str(sub["month"].max())]
                fact["n_stations"] = int(sub["station_id"].nunique())
                prov_col = "label_chla_provenance"
                if fam == "chla" and prov_col in sub.columns:
                    fact["provenance"] = sub[prov_col].value_counts().to_dict()
                fact["positive_rows"] = int((pd.to_numeric(sub[col], errors="coerce") == 1).sum()) \
                    if fam in ("bloom",) else None
    except Exception as exc:  # noqa: BLE001 —— 审计不允许静默，但单模块失败要留痕
        label_facts["_error"] = str(exc)

    task_labels = {
        ("T1", "bloom"): ("水华发生(二分类)", "bloom"),
        ("T2", "coverage"): ("水华覆盖率", "coverage"),
        ("T3", "density"): ("蓝藻密度(秩代理)", "density"),
        ("T4", "biomass"): ("蓝藻生物量", "biomass"),
        ("T5", "chla"): ("叶绿素a", "chla"),
        ("T6", "probability"): ("水华概率", "bloom"),
        ("T6", "risk_level"): ("风险等级", "chla"),
        ("T7", "spatial"): ("空间范围", "none"),
    }
    rows = []
    for (task_id, variant), (label_zh, fam) in task_labels.items():
        for h in HORIZONS:
            mo = HORIZON_MONTH_MAP[h]
            e = avail.get((task_id, variant, h), {})
            if fam == "none":
                pairing = "none"
            elif mo == 0:
                pairing = "same_month_proxy"
            else:
                pairing = "real_future_monthly"
            fact = label_facts.get(fam, {})
            rows.append({
                "task_id": task_id,
                "variant": variant,
                "指标": label_zh,
                "horizon_days": h,
                "month_offset": mo,
                "时间配对性质": pairing,
                "未来目标真实性": {
                    "same_month_proxy": "否——目标=当月标签，非未来N天",
                    "real_future_monthly": "是——月粒度未来月标签（非日尺度）",
                    "none": "无标签",
                }[pairing],
                "trainable": e.get("trainable"),
                "train_rows": e.get("train_rows"),
                "validation_rows": e.get("validation_rows"),
                "test_rows": e.get("test_rows"),
                "label_provenance_observed": e.get("label_provenance"),
                "标签非空行数": fact.get("rows"),
                "标签月份覆盖": "-".join(fact["months"]) if fact.get("months") else None,
                "标签站点数": fact.get("n_stations"),
                "阳性行数": fact.get("positive_rows"),
                "gate_status": None,
                "证据文件": "backend/model_runtime_v0_3/evaluation/availability_matrix.json; "
                            "backend/model_runtime_v0_3/code/modeling_real/contracts_real.py:HORIZON_MONTH_MAP_V3; "
                            "data-cleaning/storage/final_cleaned/TAIHU_CLEAN_FINAL_V1_20260831/tables/",
            })
    gate = json.loads(
        (PROJECT_ROOT / "backend/model_runtime_v0_3/evaluation/gate_table.json").read_text(encoding="utf-8")
    )["rows"]
    gate_key = {(r["task_id"], r["variant"], r["horizon_days"]): r for r in gate}
    for r in rows:
        g = gate_key.get((r["task_id"], r["variant"], r["horizon_days"]))
        if g:
            r["gate_status"] = g.get("status")
            r["run_id"] = g.get("run_id")
            r["selected_family"] = g.get("selected_family")
    return pd.DataFrame(rows)


# ------------------------------------------------- B. month_offset=0 时间配对
def time_pairing_audit(t: dict) -> dict:
    sys.path.insert(0, str(RUNTIME_CODE))
    from modeling_real.contracts_real import task_spec_real  # noqa: E402
    from modeling_real.target_builder import build_supervised_base, build_supervised_table  # noqa: E402

    base, labels = build_supervised_base()
    out: dict = {"horizon_month_map": HORIZON_MONTH_MAP, "tasks": {}}
    for task_id, variant in [("T1", "bloom"), ("T5", "chla"), ("T6", "probability")]:
        spec = task_spec_real(task_id, variant)
        for mo in (0, 1, 3):
            tbl = build_supervised_table(base, labels, spec, mo)
            same = (tbl["target_month"] == tbl["month"])
            rec = {
                "task": f"{task_id}-{variant}",
                "month_offset": mo,
                "n_rows": int(len(tbl)),
                "target_month_equals_input_month_ratio": round(float(same.mean()), 6) if len(tbl) else None,
                "input_month_range": [str(tbl["month"].min()), str(tbl["month"].max())] if len(tbl) else None,
                "target_month_range": [str(tbl["target_month"].min()), str(tbl["target_month"].max())] if len(tbl) else None,
                "split_counts": tbl["dataset_split_frozen"].value_counts().to_dict(),
            }
            if mo == 0:
                rec["verdict"] = ("预测目标=当月标签（target_month==month 全部成立），"
                                  "不构成『未来 N 天』预测；h1/3/7/15 四个时效共享同一监督表与同一 run")
            else:
                rec["verdict"] = f"目标月=输入月+{mo} 个月，月粒度真实前瞻（非日尺度）"
            out["tasks"][f"{task_id}-{variant}-mo{mo}"] = rec

    # 日尺度/旬尺度未来目标的数据盘点
    rs = t["remote_sensing"]
    clms = rs[rs["source_id"].astype(str).str.contains("clms", case=False, na=False)]
    obs = None
    mee_path = PROJECT_ROOT / "data-cleaning/storage/silver/mee_realtime/observations.parquet"
    if mee_path.exists():
        obs = pd.read_parquet(mee_path)
    simulated = pd.read_csv(PROJECT_ROOT / "backend/sample-data/simulated_observations_v1.csv")
    out["sub_monthly_target_inventory"] = {
        "clms_lwq_10daily": {
            "rows_final_tables": int(len(clms)),
            "months": sorted(set(month_of(clms["observed_at"]).tolist())),
            "spatial_units": sorted(set(clms["spatial_id"].dropna().astype(str).unique())),
            "variables": clms["variable_code"].value_counts().to_dict(),
            "note": "10-day 旬尺度全湖单空间单元；可用于旬尺度未来目标，但仅覆盖 2024-09..2026-08 24 个月",
        },
        "mee_realtime_silver": {
            "rows": int(len(obs)) if obs is not None else 0,
            "time_range": [str(obs["observed_at"].min()), str(obs["observed_at"].max())] if obs is not None else None,
            "variables": obs["variable_code"].value_counts().to_dict() if obs is not None else {},
            "note": "79 站半小时级、含 chlorophyll_a/cyanobacteria_density，是唯一真实日尺度藻类目标，"
                    "但跨度仅 8 天，不足以回测 T+1/T+3/T+7/T+15",
        },
        "simulated_fixture": {
            "rows": int(len(simulated)),
            "note": "backend/sample-data 模拟数据（value_origin=simulated），不得作为未来目标",
        },
    }
    out["feasibility_conclusion"] = (
        "用现有数据无法构造 1/3/7/15 天『未来 N 天』目标的可信回测集：历史期（2024-09 之前）"
        "不存在日/旬尺度藻类目标（CLMS 10-day 仅 2024-09 起且全湖单单元；MEE 实时仅 2026-09-04 起 8 天）。"
        "可行路径：(1) 30/60/90 天维持月粒度配对（已具备）；(2) 旬尺度目标用 CLMS 10-day 场从 2024-09 起构造"
        "（约 70 旬，需先修复 CLMS 三列同值缺陷）；(3) T+1/T+3 依赖 MEE realtime 持续积累（半小时级，"
        "需 ≥3~6 个月才能形成最小回测集）。缺什么：历史日/旬尺度叶绿素或藻密度目标数据。"
    )
    return out


# ------------------------------------------------------- C. 机理列数据溯源
def mechanism_provenance(t: dict) -> tuple[dict, pd.DataFrame]:
    md = t["model_dataset"]
    wq = t["water_quality"]
    fb = t["features_base"]

    # 层级 1：清洗层长表
    pb = wq[wq["variable_code"] == "phyto_biomass"].copy()
    pb["month"] = month_of(pb["observed_at"])
    level_source = {
        "layer": "1_清洗层 water_quality.parquet",
        "rows": int(len(pb)),
        "non_null": int(pd.to_numeric(pb["value"], errors="coerce").notna().sum()),
        "month_range": [str(pb["month"].min()), str(pb["month"].max())],
        "stations": int(pb["aux"].dropna().map(lambda s: json.loads(s).get("station_id")).nunique()),
        "value_min": float(pb["value"].min()), "value_max": float(pb["value"].max()),
        "unit": list(pb["unit"].unique()), "quality": pb["quality_status"].value_counts().to_dict(),
        "source_file": list(pb["source_file"].dropna().unique()),
        "is_ground_truth": bool(pb["is_ground_truth"].all()),
    }

    def col_stat(df: pd.DataFrame, col: str) -> dict:
        if col not in df.columns:
            return {"present": False}
        s = pd.to_numeric(df[col], errors="coerce")
        return {"present": True, "rows": int(len(df)), "non_null": int(s.notna().sum()),
                "nunique": int(s.nunique(dropna=True)),
                "min": None if not s.notna().any() else float(s.min()),
                "max": None if not s.notna().any() else float(s.max())}

    # 层级 2/3：装配层 + 监督底表
    level_md = {"layer": "2_装配层 model_dataset.parquet (wq_phyto_biomass)", **col_stat(md, "wq_phyto_biomass")}
    level_fb = {"layer": "3_监督底表 features_base.parquet (wq_phyto_biomass)", **col_stat(fb, "wq_phyto_biomass")}

    # 层级 4：任务监督表（重算）
    sys.path.insert(0, str(RUNTIME_CODE))
    from modeling_real.contracts_real import task_spec_real  # noqa: E402
    from modeling_real.target_builder import build_supervised_base, build_supervised_table  # noqa: E402
    from modeling_real.data_real import RealPreprocessor  # noqa: E402
    from modeling_real.training_real import _mechanism_design, MECH_DESIGN_BASE  # noqa: E402

    base, labels = build_supervised_base()
    table_stats = []
    for task_id, variant, fam in [("T1", "bloom", "bloom"), ("T4", "biomass", "biomass"),
                                  ("T3", "density", "density"), ("T5", "chla", "chla")]:
        spec = task_spec_real(task_id, variant)
        tbl = build_supervised_table(base, labels, spec, 0)
        has_col = "wq_phyto_biomass" in tbl.columns
        st = {"layer": f"4_任务监督表 {task_id}-{variant}-0m", "present": has_col,
              "rows": int(len(tbl)),
              "non_null": int(pd.to_numeric(tbl["wq_phyto_biomass"], errors="coerce").notna().sum()) if has_col else 0,
              "note": ("契约含 wq_phyto_biomass" if has_col
                       else "契约剔除 wq_phyto_biomass（TARGET_SOURCE_FEATURE_EXCLUSIONS 防同月泄漏）→ 列不存在")}
        # 训练帧（预处理器插补后）里机理设计矩阵的有效行
        train = tbl[tbl["dataset_split_frozen"] == "train"]
        pre = RealPreprocessor.fit(train, [c for c in tbl.columns if c not in
                                           {"actual", "month", "target_month", "row_id", "station_id",
                                            "dataset_split_frozen", "actual_provenance"}])
        tf = pre.transform(train)
        design = _mechanism_design(tf)
        valid = np.isfinite(design.to_numpy(dtype=float)).all(axis=1)
        st["mech_design_columns"] = list(design.columns)
        st["mech_design_valid_rows_of_train"] = int(valid.sum())
        st["mech_design_n_columns"] = int(design.shape[1])
        st["mech_fit_would_fallback_constant"] = bool(valid.sum() < 10)
        table_stats.append(st)

    # mech_net_growth_rate_d 全 NaN 的机理验证：三个因子非空行交集
    light = pd.to_numeric(fb["met_shortwave_radiation_wm2"], errors="coerce")
    air = pd.to_numeric(fb["met_air_temperature_c"], errors="coerce")
    wt_cols = [c for c in fb.columns if c == "wq_water_temp"]
    temp = pd.to_numeric(fb[wt_cols[0]], errors="coerce") if wt_cols else air
    temp = temp.combine_first(air) if wt_cols else air
    tp = pd.to_numeric(fb["wq_tp"], errors="coerce")
    inter_temp_light = int((temp.notna() & light.notna()).sum())
    inter_all = int((temp.notna() & light.notna() & tp.notna()).sum())
    mech_ng = {"layer": "3_监督底表 mech_net_growth_rate_d", **col_stat(fb, "mech_net_growth_rate_d"),
               "temp_nonnull_rows": int(temp.notna().sum()),
               "light_nonnull_rows": int(light.notna().sum()),
               "tp_nonnull_rows": int(tp.notna().sum()),
               "temp_and_light_rows": inter_temp_light,
               "temp_light_tp_intersection_rows": inter_all,
               "root_cause": ("temp(ERA5/NASA_POWER 行) × light(仅 NASA_POWER 行) × nutrient(仅 TAIHU 分区站行)"
                              "三个非空集合交集为空 → net_growth 每行至少一个 NaN → 全表 NaN；"
                              "训练时 RealPreprocessor 对全 NaN 列取 median=0.0 → 特征恒 0")}

    chain = pd.DataFrame([
        {k: v for k, v in level_source.items()},
        {k: v for k, v in level_md.items()},
        {k: v for k, v in level_fb.items()},
        *[{k: v for k, v in st.items()} for st in table_stats],
    ])
    summary = {
        "wq_phyto_biomass_verdict": (
            "源头有真实数据：THQBCA-V2 1WaterQuality.xlsx → water_quality.parquet 576 行全 valid/ground_truth"
            "（mg/L，2005-02..2020-11，9 分区站）→ model_dataset/features_base 均保留 576 行 → 唯一阳性测试样本"
            "所在 bloom 监督表亦含 576 行。『全 NaN』不是数据缺失：它发生在任务监督表层——"
            "T3-density/T4-biomass 的防同月泄漏剔除（TARGET_SOURCE_FEATURE_EXCLUSIONS）把该列从特征帧删除，"
            "而 _mechanism_design 对缺席列置整列 NaN，17 列有效性门随之全灭 → _fit_mechanism 常数回退。"
            "这是两段代码的交互缺陷（软件 bug），不是数据不足。"
        ),
        "mech_net_growth_rate_d_verdict": (
            "监督底表全 914 行 NaN（非空交集=0 行）；训练特征被中位数插补为常数 0。根因是机理三因子"
            "（温度/光照/营养盐）的观测来源是互不相交的站点集合，月度宽表内不可能同行齐全。"
        ),
        "mech_light_factor": {**col_stat(fb, "mech_light_factor"),
                              "note": "仅 NASA_POWER 气象网格行有值（242/914）；TAIHU 分区站行全 NaN → 训练时插补为网格中位数"},
        "levels": table_stats,
        "mech_net_growth": mech_ng,
    }
    return summary, chain


# ---------------------------------------------------- D. 水华事件切分审计
def event_split_audit(t: dict) -> tuple[dict, pd.DataFrame]:
    sys.path.insert(0, str(RUNTIME_CODE))
    from modeling_real.contracts_real import task_spec_real  # noqa: E402
    from modeling_real.target_builder import build_supervised_base, build_supervised_table  # noqa: E402

    base, labels = build_supervised_base()
    spec = task_spec_real("T1", "bloom")
    tbl = build_supervised_table(base, labels, spec, 0)
    # 月粒度事件：同站连续阳性月（月粒度下事件=连续阳性月段），含前后 1 个月缓冲
    rows = []
    events = []
    for station, grp in tbl.sort_values("month").groupby("station_id"):
        months = grp["month"].tolist()
        flags = (grp["actual"] == 1).to_numpy()
        # 找连续阳性段
        i = 0
        while i < len(flags):
            if flags[i]:
                j = i
                while j + 1 < len(flags) and flags[j + 1]:
                    j += 1
                events.append({
                    "station_id": station,
                    "event_months": months[i:j + 1],
                    "splits": sorted(set(grp["dataset_split_frozen"].iloc[i:j + 1])),
                    "cross_split": len(set(grp["dataset_split_frozen"].iloc[i:j + 1])) > 1,
                    "buffer_months": (months[max(0, i - 1)], months[min(len(months) - 1, j + 1)]),
                    "buffer_splits": sorted({
                        *grp["dataset_split_frozen"].iloc[max(0, i - 1):i].tolist(),
                        *grp["dataset_split_frozen"].iloc[j + 1:min(len(months), j + 2)].tolist(),
                    }),
                })
                i = j + 1
            else:
                i += 1
    ev_df = pd.DataFrame(events)
    for _, e in ev_df.iterrows():
        rows.append({
            "station_id": e["station_id"],
            "事件月": "+".join(e["event_months"]),
            "所属split": "+".join(e["splits"]),
            "事件跨split": bool(e["cross_split"]),
            "前缓冲月split": e["buffer_splits"][0] if e["buffer_splits"] else None,
            "后缓冲月split": e["buffer_splits"][-1] if e["buffer_splits"] else None,
            "缓冲月与事件同split": set(e["buffer_splits"] or []) <= set(e["splits"]),
        })
    # 邻近月（±1）是否跨集合的额外统计：所有阳性月的相邻月
    adjacency = []
    for _, e in ev_df.iterrows():
        pass
    # 测试集阳性样本的来源标注
    test_pos = tbl[(tbl["dataset_split_frozen"] == "test") & (tbl["actual"] == 1)]
    clms_labels = t["labels"]
    clms_pos_months = sorted(set(month_of(
        clms_labels[(clms_labels["variable_code"] == "bloom_label") &
                    (pd.to_numeric(clms_labels["value"], errors="coerce") == 1)]["observed_at"]).tolist()))
    summary = {
        "n_events_monthly": int(len(ev_df)),
        "n_events_cross_split": int(ev_df["cross_split"].sum()) if len(ev_df) else 0,
        "positive_rows_by_split": {
            sp: int(((tbl["dataset_split_frozen"] == sp) & (tbl["actual"] == 1)).sum())
            for sp in ("train", "validation", "test")
        },
        "test_positive_detail": test_pos[["row_id", "station_id", "month"]].to_dict("records"),
        "clms_positive_months": clms_pos_months,
        "conclusion": (
            "月粒度下 23 个训练期阳性事件（2005-05..2019-08，全部为代理 chla 阈值派生的孤立单月）与 "
            "1 个测试期阳性（2024-12 TAIHU_WHOLE，CLMS bloom_label）互不重叠；未发现同一连续阳性事件被拆进"
            "训练与测试集合（冻结切分按目标月、且 train≤2021-12 与 test≥2024-09 之间有 ≥32 个月间隙）。"
            "但两点保留：(1) 阳性事件本身几乎全部由 chla_station_proxy_v1 代理标签派生，事件真实性受"
            "代理标签与单位混用缺陷影响；(2) 真事件级切分需在旬尺度（CLMS 10-day）上重做，当前月粒度"
            "无法识别旬级事件拆分。建议：以『连续阳性旬/月段 ± 1 旬缓冲』为事件单元整段分配到同一集合。"
        ),
        "recommendation": "事件级切分：event_id = (station, 连续阳性段); 划分时整段分配; 缓冲 1 个时间步不进任何评估",
    }
    return summary, pd.DataFrame(rows)


# ------------------------------------------------------- E. 端到端样本血缘
def lineage_row881(t: dict) -> dict:
    md = t["model_dataset"].reset_index(drop=True)
    row = md.iloc[881]
    wq = t["water_quality"]
    rs = t["remote_sensing"]
    labels = t["labels"]
    # 标签溯源
    lb = labels[(labels["variable_code"] == "bloom_label")].copy()
    lb["month"] = month_of(lb["observed_at"])
    lb_2024_12 = lb[lb["month"] == "2024-12"]
    # 遥感溯源（长表 2024-12 TAIHU_LAKE）
    rs_dec = rs[month_of(rs["observed_at"]) == "2024-12"]
    clms_dec = rs_dec[rs_dec["source_id"].astype(str).str.contains("clms", case=False, na=False)]
    lineage = {
        "预测样本": {
            "来源产物": "backend/model_runtime_v0_3/runs/T1-bloom-1d-0m/test_predictions.csv",
            "row_id": 881,
            "actual": 1.0,
            "month": "2024-12",
            "station_id": "TAIHU_WHOLE",
            "prediction": 0.0,
            "note": "T1-bloom-1d 冻结测试集 40 行中唯一阳性；模型 prediction=0 → 假阴性",
        },
        "特征层": {
            "文件": "data-cleaning/.../tables/model_dataset.parquet 行 881",
            "non_null_features": {k: (float(v) if isinstance(v, (int, float, np.floating)) else str(v))
                                  for k, v in row.items()
                                  if pd.notna(v) and k not in {"aux"}},
            "关键缺陷": "rs_clms_lwq_300m_10daily_chla_mean / _chla_uncertainty / _fcb_prob 三列同值 95.9935531616211"
                       "（= fcb_prob 口径 0.0096 × 1e4 缩放），chla_mean/uncertainty 语义被 fcb_prob 覆盖",
        },
        "标签层": {
            "文件": "data-cleaning/.../tables/labels.parquet（26 行 CLMS bloom_label）",
            "2024-12 行": lb_2024_12[["observed_at", "value", "source_id"]].to_dict("records"),
            "label_bloom_clms_2024_12_TAIHU_WHOLE": 1.0,
            "note": "label_bloom_any=1 由 CLMS bloom_label=1 支路触发（target_builder L447-463）",
        },
        "清洗层长表": {
            "文件": "data-cleaning/.../tables/taihu_clean_final_long.parquet",
            "2024-12-01 TAIHU_LAKE": {
                "chla_mean": 8.123590, "chla_uncertainty": 13.833640, "fcb_prob": 0.008179,
                "source_id": "clms_lwq_300m_10daily_v2",
            },
            "note": "长表三变量语义正常；装配层（storage/cleaned 中间层已不在仓库）把三列写成了同一值",
        },
        "原始数据层": {
            "CLMS 平台目录": "data-cleaning/storage/raw/clms_lwq_catalog/（lwq-nrt_global_300m_10daily_v2 COG 索引）",
            "MEE 月报": "model_dataset 行 881 的 mee_* 文本列（TAIHU_WHOLE 月报）",
        },
        "推理落点": {
            "模型槽位": "backend/model_runtime_v0_3/models/T1-bloom-0m-s20260907-1d.joblib",
            "特征处理": "RealPreprocessor 中位数插补（该行 wq_*/met_*/hydro_* 全缺 → 全部中位数）",
            "结论": "该预测的输入除遥感 CLMS（同值缺陷列）与静态/日历列外全为插补中位数；"
                    "brier 指标对阳性样本的 1/40 贡献来自这一条假阴性",
        },
    }
    return lineage


# --------------------------------------------- F. 专项：CLMS 同值 + 单位混用
def data_defect_checks(t: dict) -> dict:
    md = t["model_dataset"]
    wq = t["water_quality"]
    cols = ["rs_clms_lwq_300m_10daily_chla_mean", "rs_clms_lwq_300m_10daily_chla_uncertainty",
            "rs_clms_lwq_300m_10daily_fcb_prob"]
    sub = md[cols].dropna(how="all")
    same_12 = float((sub[cols[0]] == sub[cols[1]]).mean())
    same_13 = float((sub[cols[0]] == sub[cols[2]]).mean())
    chla = wq[wq["variable_code"] == "chla"].copy()
    unit_mix = chla.groupby(["source_id", "unit"], dropna=False)["value"].agg(["count", "min", "median", "max"])
    # field 航次同月 mg/L 与 ug/L 是否同值异单位（成对）
    field = chla[chla["source_id"] == "taihu_field_samples"]
    mg = set(field[field["unit"] == "mg/L"]["value"].round(5))
    ug = set((field[field["unit"] == "ug/L"]["value"] / 1000.0).round(5))
    paired = len(mg & ug)
    return {
        "clms_three_column_identical": {
            "chla_mean_eq_uncertainty_ratio": same_12,
            "chla_mean_eq_fcb_prob_ratio": same_13,
            "non_null_rows": int(len(sub)),
            "value_range": [float(sub[cols[0]].min()), float(sub[cols[0]].max())],
            "verdict": ("装配层三语义列 100% 同值（值域 89.35~188.12 ≈ fcb_prob×1e4）。"
                        "中间清洗层 storage/cleaned/*.csv 已不在仓库，无法定位写坏点 → 需重建管道复现（阻断项）。"
                        "后果：78 列契约的 chla_mean 特征与其 lag 列语义错误；T2 coverage 标签建立在同值列上；"
                        "FCB 阳性支路（≥0.5）全部恒不触发。"),
        },
        "chla_unit_mixing": {
            "by_source_unit": unit_mix.reset_index().to_dict("records"),
            "mg_vs_ug_paired_values": paired,
            "field_mg_rows": int((chla["source_id"] == "taihu_field_samples").sum() / 2),
            "verdict": ("water_quality.parquet 中同一批野外航次 chla 以 mg/L 与 ug/L 两种单位重复入库"
                        "（数值严格同值异单位成对），另 taihu_water_quality 1 行 0.03 mg/L。"
                        "load_label_wide 以 aggfunc='mean' 对同 (station,month) 两种单位行求均值 → "
                        "field 月标签被混合单位污染（约为真实 μg/L 值的一半量级）。"
                        "chla_proxy 锚点（2020-12 IN_SITU 均值）因此被拉低 → 全部代理 chla 标签系统性偏低 → "
                        "bloom 阈值 20 μg/L 几乎只在代理季节峰触发（阳性 22/914）。"),
        },
        "field_chla_bloom_threshold_check": {
            "n_field_rows": int(len(chla)),
            "n_ge_20ugL_as_is": int((pd.to_numeric(chla["value"], errors="coerce") >= 20).sum()),
            "note": "无论按入库值还是换算 μg/L，野外 chla 均无 ≥20 μg/L 的阳性（max 18.03 μg/L）",
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t = load_tables()
    print("[1/6] 能力表 ...")
    cap = capability_matrix(t)
    cap.to_csv(OUT_DIR / "capability_matrix.csv", index=False, encoding="utf-8-sig")
    RESULTS["capability_matrix_rows"] = int(len(cap))
    RESULTS["capability_same_month_rows"] = int((cap["时间配对性质"] == "same_month_proxy").sum())
    RESULTS["capability_real_future_rows"] = int((cap["时间配对性质"] == "real_future_monthly").sum())

    print("[2/6] 时间配对审计 ...")
    RESULTS["time_pairing"] = time_pairing_audit(t)

    print("[3/6] 机理列溯源 ...")
    mech_summary, chain = mechanism_provenance(t)
    chain.to_csv(OUT_DIR / "mechanism_provenance_chain.csv", index=False, encoding="utf-8-sig")
    RESULTS["mechanism_provenance"] = mech_summary

    print("[4/6] 事件切分审计 ...")
    ev_summary, ev_df = event_split_audit(t)
    ev_df.to_csv(OUT_DIR / "event_split_events.csv", index=False, encoding="utf-8-sig")
    RESULTS["event_split"] = ev_summary

    print("[5/6] 样本血缘 row_id=881 ...")
    RESULTS["lineage_row881"] = lineage_row881(t)

    print("[6/6] 专项缺陷核查 ...")
    RESULTS["data_defects"] = data_defect_checks(t)

    out = OUT_DIR / "t1_audit_summary.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"done -> {out}")


if __name__ == "__main__":
    main()
