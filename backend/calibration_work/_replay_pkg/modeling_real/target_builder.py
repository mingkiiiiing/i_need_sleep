"""站点-月度监督表构造：真实标签透视、月份平移、水华代理与可用性矩阵。

标签来源（主理人裁定 2/3 + 第三轮裁定）：
- water_quality.parquet 长表（6777 行 ground_truth）透视出 wq 标签（chla 单位 μg/L）；
- labels.parquet 的 26 条 CLMS bloom_label 代理标签（is_ground_truth=False）；
- T1/T6 水华代理 = 站点月 chla ≥ 20 μg/L 或 CLMS bloom_label=1 或 CLMS FCB 月均概率 ≥0.5
  或 MODIS-Aqua chla_retrieval 当月湖面均值 ≥20 μg/L（仅 TAIHU_WHOLE 行），
  provenance=proxy_derived，任何代理标签一律不标 ground_truth。
MODIS quality 规则（第三轮）：valid 优先；该月无 valid 行时方可用 review 行并降权披露
（review = 有效像元占比 <5% 或聚合天数 <3，值非无效，仅覆盖度降级）。
划分（主理人裁定 3，冻结）：按发布月 train≤2021 / validation 2022-2023 / test≥2024。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .chla_proxy import PROVENANCE as PROVENANCE_CHLA
from .contracts_real import (
    BLOOM_THRESHOLD_UG_L,
    DEFAULT_SEED_V3,
    FEATURE_COLUMNS_V2,
    FCB_BLOOM_PROB_THRESHOLD,
    FCB_PROB_SCALE_FACTOR,
    HORIZONS_V3,
    HORIZON_MAP_V3,
    PROVENANCE_GROUND_TRUTH,
    PROVENANCE_PROXY_DERIVED,
    RISK_CLASSES_V3,
    SERVING_FEATURE_COLUMNS_V2,
    SERVING_LAGGED_TARGET_FEATURES,
    SPLIT_BOUNDS,
    TASK_SPECS_REAL,
    TaskSpecReal,
    clean_tables_dir,
    feature_columns_for_task,
    feature_contract_sha256,
    split_of_month,
)

# serving 契约相对冻结 78 列契约的扩展列（推理时逐站可得，需显式并入监督表，
# 否则 feature_columns_for_task 返回的冻结列会把它们过滤掉）。
SERVING_EXTENSION_COLUMNS: tuple[str, ...] = tuple(
    name for name in SERVING_FEATURE_COLUMNS_V2 if name not in FEATURE_COLUMNS_V2
)

# label_family → 目标列（第二轮扩展：biomass / density / coverage）
LABEL_FAMILY_COLUMNS = {
    "bloom": "label_bloom_any",
    "chla": "label_chla_ug_l",
    "biomass": "label_phyto_biomass_mg_l",
    "density": "label_density_rank_proxy",
    "coverage": "label_coverage_fcb_prob",
}

LAKE_STATIONS = (
    "TAIHU_CT", "TAIHU_ET", "TAIHU_GH", "TAIHU_ML",
    "TAIHU_ST", "TAIHU_WHOLE", "TAIHU_WT", "TAIHU_XK", "TAIHU_ZS",
)
FIELD_STATIONS = ("IN_SITU_GROUP", "S1")
WQ_LABEL_CODES = {
    "chla": "label_chla_ug_l",
    "tp": "label_tp_mg_l",
    "tn": "label_tn_mg_l",
    "do": "label_do_mg_l",
    "nh4_n": "label_nh4_n_mg_l",
    "phyto_biomass": "label_phyto_biomass_mg_l",
}
LABEL_COLUMNS = tuple(WQ_LABEL_CODES.values()) + ("label_bloom_clms",)


def _aux_station(aux_value) -> str | None:
    if isinstance(aux_value, str):
        try:
            return json.loads(aux_value).get("station_id")
        except ValueError:
            return None
    return None


def load_label_wide(tables_dir: Path | None = None) -> pd.DataFrame:
    """把 water_quality 长表 + labels.parquet 透视为 (station_id, month) 月度标签宽表。"""
    tables = Path(tables_dir) if tables_dir else clean_tables_dir()
    wq = pd.read_parquet(tables / "water_quality.parquet")
    wq = wq[wq["is_ground_truth"] == True]  # noqa: E712
    wq["station_id"] = wq["aux"].map(_aux_station)
    wq = wq[wq["station_id"].isin(LAKE_STATIONS + FIELD_STATIONS)]
    wq["month"] = pd.to_datetime(wq["observed_at"]).dt.strftime("%Y-%m")
    wq = wq[wq["variable_code"].isin(WQ_LABEL_CODES)]
    wide = (
        wq.pivot_table(
            index=["station_id", "month"],
            columns="variable_code",
            values="value",
            aggfunc="mean",
        )
        .reset_index()
        .rename(columns=WQ_LABEL_CODES)
    )
    labels = pd.read_parquet(tables / "labels.parquet")
    bloom = labels[labels["variable_code"] == "bloom_label"].copy()
    bloom["month"] = pd.to_datetime(bloom["observed_at"]).dt.strftime("%Y-%m")
    bloom = bloom.assign(station_id="TAIHU_WHOLE")
    bloom_monthly = (
        bloom.groupby(["station_id", "month"])["value"].max().rename("label_bloom_clms").reset_index()
    )
    wide = wide.merge(bloom_monthly, on=["station_id", "month"], how="outer")
    for col in LABEL_COLUMNS:
        if col not in wide.columns:
            wide[col] = np.nan
        wide[col] = pd.to_numeric(wide[col], errors="coerce").astype(float)
    return wide


def augment_provenance(series: pd.Series) -> str:
    """同一 (站点, 目标月) 内多行标签的来源汇总口径（月聚合任务用）。

    全空 → 未标注来源的实测标签，按 ground_truth 记；
    单一来源 → 该来源；
    多来源 → "mixed(来源A|来源B…)"，逐字保留各自名字，绝不塌缩成 ground_truth。
    """
    values = sorted({str(v) for v in series.dropna().unique()})
    if not values:
        return PROVENANCE_GROUND_TRUTH
    return values[0] if len(values) == 1 else "mixed(" + "|".join(values) + ")"


def provenance_summary(table: pd.DataFrame, declared: str) -> dict:
    """监督表逐行 actual_provenance 的权威汇总（2026-09-11 新增）。

    声明口径（spec.label_provenance）只说明"允许哪些来源"；这里给出"实际是什么"。
    落盘的 label_provenance 必须是本函数的 observed 值，禁止用声明值顶替——
    T5 的 567 行 T+90 标签全部来自 chla_station_proxy_v1，声明 ground_truth 是错的。
    """
    rows = int(len(table))
    if "actual_provenance" not in table.columns or not rows:
        return {
            "declared": declared,
            "observed": declared,
            "breakdown": {},
            "dominant": declared,
            "rows": rows,
            "unresolved_rows": 0,
            "observed_available": False,
        }
    raw = table["actual_provenance"]
    unresolved = int(raw.isna().sum())
    counts = {
        str(k): int(v) for k, v in raw.dropna().value_counts().items()
    }
    if not counts:
        observed = declared
        dominant = declared
    else:
        dominant = max(counts, key=lambda k: counts[k])
        observed = dominant if len(counts) == 1 else "mixed(" + "|".join(sorted(counts)) + ")"
    return {
        "declared": declared,
        "observed": observed,
        "breakdown": dict(sorted(counts.items())),
        "dominant": dominant,
        "rows": rows,
        "unresolved_rows": unresolved,
        "observed_available": True,
    }


def bloom_proxy_from_chla(chla_ug_l: pd.Series) -> pd.Series:
    """chla ≥ 20 μg/L 的水华代理标签（provenance=proxy_derived，非 ground_truth）。"""
    return (pd.to_numeric(chla_ug_l, errors="coerce") >= BLOOM_THRESHOLD_UG_L).astype(float)


def risk_band(chla_ug_l: pd.Series) -> pd.Series:
    bands = pd.Series(pd.NA, index=chla_ug_l.index, dtype="object")
    values = pd.to_numeric(chla_ug_l, errors="coerce")
    for rank, name in enumerate(RISK_CLASSES_V3):
        low, high = {
            "none": (0.0, 10.0), "low": (10.0, 20.0), "medium": (20.0, 30.0),
            "high": (30.0, 50.0), "severe": (50.0, np.inf),
        }[name]
        bands[values.ge(low) & values.lt(high)] = name
    return bands


def _calendar_columns(frame: pd.DataFrame, month_col: str = "month") -> pd.DataFrame:
    month_num = frame[month_col].str[5:7].astype(int)
    angle = 2.0 * np.pi * (month_num - 1) / 12.0
    out = frame.copy()
    out["calendar_month_sin"] = np.sin(angle)
    out["calendar_month_cos"] = np.cos(angle)
    return out


def load_water_temperature_monthly(tables_dir: Path | None = None) -> pd.DataFrame:
    """站点-月度水温（℃）：ERA5 湖表温度网格月均为主，野外实测水温覆盖对应站-月。

    来源与口径（如实披露）：
    - era5_lake_temp（meteorology_hydrology.parquet，provenance=derived，单位 degC）：
      单网格（31.1N, 120.25E）湖表温度，2020-01..2026-08；同一网格适用于全部站点，
      不代表站间差异；
    - water_quality.parquet 的 water_temperature（ground_truth，仅 IN_SITU_GROUP
      2020-12/2023-10 航次，41 行）：对应站-月用实测月均值覆盖网格值。
    返回 (station_id, month, wq_water_temp, wq_water_temp_provenance)。
    """
    tables = Path(tables_dir) if tables_dir else clean_tables_dir()
    mh = pd.read_parquet(tables / "meteorology_hydrology.parquet")
    lst = mh[mh["variable_code"] == "lake_surface_temperature"].copy()
    lst["month"] = pd.to_datetime(lst["observed_at"]).dt.strftime("%Y-%m")
    lst["value"] = pd.to_numeric(lst["value"], errors="coerce")
    grid_monthly = lst.groupby("month", as_index=False)["value"].mean().rename(
        columns={"value": "wq_water_temp"}
    )
    grid_monthly["wq_water_temp_provenance"] = "era5_lake_surface_temp_grid_31.1N_120.25E"

    wq = pd.read_parquet(tables / "water_quality.parquet")
    wt = wq[(wq["is_ground_truth"] == True) & (wq["variable_code"] == "water_temperature")].copy()  # noqa: E712
    wt["station_id"] = wt["aux"].map(_aux_station)
    wt = wt[wt["station_id"].isin(FIELD_STATIONS)]
    wt["month"] = pd.to_datetime(wt["observed_at"]).dt.strftime("%Y-%m")
    measured = wt.groupby(["station_id", "month"], as_index=False)["value"].mean().rename(
        columns={"value": "wq_water_temp"}
    )
    measured["wq_water_temp_provenance"] = "mee_insitu_measured"

    return measured, grid_monthly


def _attach_water_temperature(features: pd.DataFrame, tables_dir: Path | None = None) -> pd.DataFrame:
    """给监督底表挂载 wq_water_temp：全站按月取 ERA5 网格月均，野外站实测月覆盖。"""
    measured, grid_monthly = load_water_temperature_monthly(tables_dir)
    out = features.merge(grid_monthly, on="month", how="left", sort=False)
    for row in measured.itertuples():
        mask = (out["station_id"] == row.station_id) & (out["month"] == row.month)
        out.loc[mask, "wq_water_temp"] = row.wq_water_temp
        out.loc[mask, "wq_water_temp_provenance"] = "mee_insitu_measured"
    return out


def _mechanism_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """由真实水温(优先)/气温(回退)/光照/营养盐确定性重算的机理因子（非拟合、无泄漏）。

    温度口径（2026-09-11 对齐）：优先 wq_water_temp（ERA5 湖表温度/野外实测），
    缺测回退 met_air_temperature_c（气温，披露为回退口径）；与运行时机理展示同序。
    """
    out = frame.copy()
    water_temp = pd.to_numeric(out.get("wq_water_temp"), errors="coerce") if "wq_water_temp" in out.columns else None
    air_temp = pd.to_numeric(out["met_air_temperature_c"], errors="coerce")
    temp = water_temp.combine_first(air_temp) if water_temp is not None else air_temp
    light = pd.to_numeric(out["met_shortwave_radiation_wm2"], errors="coerce")
    tp = pd.to_numeric(out["wq_tp"], errors="coerce")
    tn = pd.to_numeric(out["wq_tn"], errors="coerce")
    temp_factor = np.clip((temp - 10.0) / (28.0 - 10.0), 0.0, 1.0)
    temp_factor[(temp <= 4.0) | (temp >= 38.0)] = 0.0
    light_factor = np.clip(light / 18.0, 0.0, 1.0)
    phos_factor = tp / (tp + 0.02)
    nitro_factor = tn / (tn + 0.6)
    nutrient_factor = np.minimum(phos_factor, nitro_factor)
    net_growth = 0.9 * temp_factor * light_factor * nutrient_factor - 0.16
    out["mech_temperature_factor"] = temp_factor.round(6)
    out["mech_light_factor"] = light_factor.round(6)
    out["mech_phosphorus_factor"] = phos_factor.round(6)
    out["mech_nitrogen_factor"] = nitro_factor.round(6)
    out["mech_nutrient_factor"] = nutrient_factor.round(6)
    out["mech_net_growth_rate_d"] = net_growth.round(6)
    return out


def _lag_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """按站点月序的滞后/滚动特征；重复站点-月（野外样本行）取月均值后回填。"""
    bases = [
        "wq_chla", "wq_tp", "wq_tn", "wq_do", "wq_nh4_n",
        "met_air_temperature_c", "met_shortwave_radiation_wm2",
        "hydro_water_level_m", "rs_clms_lwq_300m_10daily_chla_mean",
    ]
    agg = frame.groupby(["station_id", "month"], as_index=False)[bases].mean()
    agg = agg.sort_values(["station_id", "month"], kind="mergesort").reset_index(drop=True)
    for base in bases:
        lag1 = agg.groupby("station_id")[base].shift(1)
        lag2 = agg.groupby("station_id")[base].shift(2)
        roll3 = (
            agg.groupby("station_id")[base]
            .transform(lambda s: s.rolling(3, min_periods=1).mean())
        )
        agg[f"{base}_lag1m"] = lag1
        agg[f"{base}_lag2m"] = lag2
        agg[f"{base}_roll3m_mean"] = roll3
    lag_cols = [c for c in agg.columns if c.endswith(("_lag1m", "_lag2m", "_roll3m_mean"))]
    out = frame.merge(
        agg[["station_id", "month", *lag_cols]],
        on=["station_id", "month"], how="left", sort=False,
    )
    return out


def load_field_chla_samples(tables_dir: Path | None = None) -> pd.DataFrame:
    """野外航次/S1 的逐样本 chla（μg/L，ground_truth），用于逐样本标签回填。"""
    tables = Path(tables_dir) if tables_dir else clean_tables_dir()
    wq = pd.read_parquet(tables / "water_quality.parquet")
    wq = wq[(wq["is_ground_truth"] == True) & (wq["variable_code"] == "chla")]  # noqa: E712
    wq = wq[wq["aux"].map(_aux_station).isin(FIELD_STATIONS)]
    out = pd.DataFrame({
        "station_id": wq["aux"].map(_aux_station),
        "month": pd.to_datetime(wq["observed_at"]).dt.strftime("%Y-%m"),
        "label_chla_ug_l": pd.to_numeric(wq["value"], errors="coerce"),
    })
    return out.dropna(subset=["label_chla_ug_l"])


def load_modis_bloom_months(tables_dir: Path | None = None) -> dict[str, object]:
    """MODIS-Aqua chla_retrieval 当月湖面均值 ≥20 μg/L 的阳性月集合（第三轮裁定）。

    聚合规则（清洗包 quality 语义 + 主理人授权）：
    - 仅取 source_id=modis_aqua_chla*（TAIHU_BBOX 湖面提取，不含 CLMS 行）；
    - 同月多行（逐日场景 + 月度聚合）按行均值聚合为湖面月均值；
    - valid 优先：该月存在 valid 行时仅用 valid 行均值；否则回退 review 行均值
      并计入 degraded_months（降权披露；review = 有效像元 <5% 或聚合天数 <3）。
    返回 {"positive_months": set[str], "covered_months": int, "degraded_months": int}。
    """
    tables = Path(tables_dir) if tables_dir else clean_tables_dir()
    rs = pd.read_parquet(tables / "remote_sensing.parquet")
    modis = rs[
        rs["variable_code"].astype(str).str.contains("chla_retrieval", na=False)
        & rs["source_id"].astype(str).str.contains("modis", na=False)
    ].copy()
    modis["month"] = pd.to_datetime(modis["observed_at"]).dt.strftime("%Y-%m")
    modis["value"] = pd.to_numeric(modis["value"], errors="coerce")
    positive: set[str] = set()
    covered = 0
    degraded = 0
    for month, group in modis.groupby("month"):
        valid = group.loc[group["quality_status"] == "valid", "value"].dropna()
        if len(valid):
            mean = float(valid.mean())
        else:
            review = group.loc[group["quality_status"] == "review", "value"].dropna()
            if not len(review):
                continue
            mean = float(review.mean())
            degraded += 1
        covered += 1
        if mean >= BLOOM_THRESHOLD_UG_L:
            positive.add(month)
    return {
        "positive_months": positive,
        "covered_months": covered,
        "degraded_months": degraded,
    }


def build_supervised_base(tables_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (特征+标签监督底表, 月度标签宽表)。底表每行 = model_dataset 一条样本记录。"""
    tables = Path(tables_dir) if tables_dir else clean_tables_dir()
    features = pd.read_parquet(tables / "model_dataset.parquet").reset_index(drop=True)
    features["row_id"] = features.index
    labels = load_label_wide(tables)
    field_samples = load_field_chla_samples(tables)
    features["label_chla_ug_l"] = np.nan
    # 逐行来源列从底表就存在：代理回填与实测标签各自标注，禁止让下游靠 NaN 猜。
    features["label_chla_provenance"] = None
    features["label_bloom_clms"] = np.nan
    # 逐样本回填（IN_SITU/S1）：月内按值排序一一对应，防 (station,month) 笛卡尔积
    field_rows = features["station_id"].isin(FIELD_STATIONS) & features["wq_chla"].notna()
    for (station, month), idx in features[field_rows].groupby(["station_id", "month"]).groups.items():
        targets = field_samples[
            (field_samples["station_id"] == station) & (field_samples["month"] == month)
        ].sort_values("label_chla_ug_l")
        rows = features.loc[idx].sort_values("wq_chla")
        if len(targets) == len(rows):
            features.loc[rows.index, "label_chla_ug_l"] = targets["label_chla_ug_l"].to_numpy()
        else:
            # 样本数不一致时回退月度均值（如实披露于审计）
            monthly = targets["label_chla_ug_l"].mean()
            if pd.notna(monthly):
                features.loc[idx, "label_chla_ug_l"] = float(monthly)
    # 常规站：月度宽表直连
    routine = features["station_id"].isin(LAKE_STATIONS)
    if routine.any():
        label_cols = [
            "label_bloom_clms", "label_tp_mg_l", "label_tn_mg_l",
            "label_do_mg_l", "label_nh4_n_mg_l", "label_phyto_biomass_mg_l", "label_chla_ug_l",
        ]
        orig_index = features.loc[routine].index
        merged = features.loc[routine, ["station_id", "month"]].merge(
            labels[["station_id", "month", *label_cols]], on=["station_id", "month"],
            how="left", sort=False,
        )
        for col in label_cols:
            features.loc[orig_index, col] = merged[col].to_numpy()
        # ---- 站点水质特征回填（2026-09-11 面板重建口径）----
        # wq_chla 在 model_dataset 全空（观测未入特征底表），导致训练时该列常数、
        # 推理时 MEE 唯一逐站可变的叶绿素输入被树模型完全忽略（80 实体输入指纹
        # 不同、输出同值的根因）。与 label_chla_ug_l 同源回填（μg/L 口径）：
        # 对 month_offset>0 任务它是历史月特征；对 month_offset=0 任务为同月同源
        # 现值口径（月度标签粒度与代理语义已在合同中披露）。
        fill = routine & features["wq_chla"].isna() & features["label_chla_ug_l"].notna()
        features.loc[fill, "wq_chla"] = pd.to_numeric(
            features.loc[fill, "label_chla_ug_l"], errors="coerce"
        )
        # ---- 站点 chla 代理标签（公示口径，2026-09-11 主理人授权补档）----
        # 「chla 实测 × 站点水质实测」共存行数为零导致 T5/T1/T6 无法训练出站点响应；
        # 用公开公式结构 + 2020-12 航次实测锚点 + 固定种子残差为有实测 TP/TN 的常规站
        # 行生成代理标签（只填缺失，实测标签绝不覆盖）。公式/锚点/种子随 params
        # 公示进 manifest；消费方必须按 proxy_derived 口径披露。
        from modeling_real.chla_proxy import fill_station_chla_proxy

        features, chla_proxy_params = fill_station_chla_proxy(features, labels)
        # 代理回填后仍无来源的行，就是实测标签（航次/S1/常规站 wq chla）：显式记为 ground_truth。
        # 这一步把"来源未知"从隐式默认变成显式事实——否则任何漏标都会静默变成实测。
        measured_mask = features["label_chla_ug_l"].notna() & features["label_chla_provenance"].isna()
        features.loc[measured_mask, "label_chla_provenance"] = PROVENANCE_GROUND_TRUTH
        chla_proxy_params["measured_label_rows"] = int(measured_mask.sum())
    # 水华代理（月度口径）：chla 月度均值 ≥20 或 CLMS bloom_label=1；有标签即 0/1，无标签为 NaN
    monthly_chla_mean = features.groupby(["station_id", "month"])["label_chla_ug_l"].mean()
    proxy = bloom_proxy_from_chla(monthly_chla_mean).rename("label_bloom_proxy").reset_index()
    features = features.merge(proxy, on=["station_id", "month"], how="left", sort=False)

    # ---- 第二轮扩展目标（主理人裁定 1/2/3/4）----
    # T2-coverage：CLMS FCB 概率月度均值（frame 列为 0-1 概率的 1e4 缩放，先归一）。
    # 来源 CLMS LWQ 300m 10-day 产品，覆盖 2024-09..2026-08；provenance=proxy_derived。
    fcb_raw = pd.to_numeric(features["rs_clms_lwq_300m_10daily_fcb_prob"], errors="coerce")
    features["label_fcb_prob_01"] = fcb_raw / FCB_PROB_SCALE_FACTOR
    # T3-density：phyto_biomass 月均的全局分位秩代理（0-1，无量纲；未做细胞体积换算，如实披露）。
    station_month = features.groupby(["station_id", "month"], as_index=False).agg(
        biomass_mean=("label_phyto_biomass_mg_l", "mean"),
        fcb_prob_01_mean=("label_fcb_prob_01", "mean"),
    )
    station_month["label_density_rank_proxy"] = station_month["biomass_mean"].rank(
        pct=True, na_option="keep"
    )
    station_month["label_coverage_fcb_prob"] = station_month["fcb_prob_01_mean"]
    features = features.merge(
        station_month[["station_id", "month", "label_density_rank_proxy", "label_coverage_fcb_prob"]],
        on=["station_id", "month"], how="left", sort=False,
    )
    # 扩展水华代理定义（裁定 4 + 第三轮）：CLMS FCB 月均概率 ≥0.5 或 MODIS 湖面月均 chla ≥20
    # 计阳性；MODIS 湖面均值是全湖口径，仅映射到 TAIHU_WHOLE 行（最保守）。
    modis_bloom = load_modis_bloom_months(tables)
    modis_positive_months = modis_bloom["positive_months"]
    is_whole = features["station_id"] == "TAIHU_WHOLE"
    in_modis_positive = features["month"].isin(modis_positive_months)
    features["label_bloom_modis"] = np.where(
        is_whole & in_modis_positive, 1.0, np.nan
    )
    has_label = (
        features["label_chla_ug_l"].notna()
        | features["label_bloom_clms"].notna()
        | features["label_coverage_fcb_prob"].notna()
        | features["label_bloom_modis"].notna()
    )
    positive = (
        (features["label_bloom_proxy"] == 1.0)
        | (features["label_bloom_clms"] == 1.0)
        | (features["label_coverage_fcb_prob"] >= FCB_BLOOM_PROB_THRESHOLD)
        | (features["label_bloom_modis"] == 1.0)
    )
    features["label_bloom_any"] = np.where(
        has_label,
        np.where(positive, 1.0, 0.0),
        np.nan,
    )
    features["dataset_split_frozen"] = features["month"].map(split_of_month)
    features = _attach_water_temperature(features, tables)
    features = _calendar_columns(features)
    features = _mechanism_columns(features)
    features = _lag_columns(features)
    # merge 会重建 DataFrame 丢掉 attrs：代理参数在返回前最后挂载
    try:
        features.attrs["chla_proxy_params"] = chla_proxy_params
    except NameError:
        pass
    return features, labels


def build_supervised_table(
    base: pd.DataFrame,
    labels: pd.DataFrame,
    spec: TaskSpecReal,
    month_offset: int,
) -> pd.DataFrame:
    """输出一个 (task, horizon) 监督表：契约特征列 + actual + 审计列。

    方向合同（2026-09-11 修正，此前未来标签配反、在学过去值）：
        输入行月份 M  →  目标 = 该站 M + month_offset 月的标签。
    - month_offset=0：actual 取**同一行**的标签（保留逐样本身份，野外航次 10 样本/月
      不再被 drop_duplicates 压成同一值）；
    - month_offset>0：actual = 目标月该站标签的月均值（野外多样本月聚合口径，如实披露）；
      dataset_split_frozen 按**目标月**划分（保证训练期看不到目标月数据）；
      calendar_month_sin/cos 重算为**目标月**季节（与推理侧 target-month 日历一致）。
    目标同源特征（如 biomass 任务剔除 wq_phyto_biomass 当月值）按契约函数剔除，防同月泄漏。

    serving 扩展列（2026-09-11 修）：推理侧逐站可得的实测列（水温）与目标滞后列
    （wq_chla，仅 month_offset>0 时并入）必须显式并进特征集，否则会被冻结 78 列的
    交集静默丢掉——训练与展示就用了不同的输入，正是"服务站差异无响应"的根因。
    """
    if spec.problem_type == "none" or spec.label_family == "none":
        raise ValueError(f"task {spec.task_id}/{spec.variant} has no real label family")
    column = LABEL_FAMILY_COLUMNS[spec.label_family]
    feature_columns = tuple(dict.fromkeys((
        *feature_columns_for_task(spec.label_family),
        *SERVING_EXTENSION_COLUMNS,
        # 目标同源的滞后列：month_offset>0 时输入月 M 相对目标月 M+offset 是历史量，
        # 无同月泄漏；month_offset=0 时并入即等于把标签喂给模型，必须排除。
        *(SERVING_LAGGED_TARGET_FEATURES.get(spec.label_family, ()) if month_offset > 0 else ()),
    )))
    prov_col = "label_chla_provenance" if spec.label_family == "chla" else None
    labeled = base.dropna(subset=[column])
    if month_offset == 0:
        out = labeled.copy()
        out["actual"] = pd.to_numeric(out[column], errors="coerce")
        out["target_month"] = out["month"]
        # 逐行继承来源。残余 NaN（来源列缺失时）显式记为 ground_truth 并在
        # provenance_summary.unresolved_rows 里计数，不做静默兜底。
        out["actual_provenance"] = (
            out[prov_col].fillna(PROVENANCE_GROUND_TRUTH) if prov_col else spec.label_provenance
        )
    else:
        agg_spec: dict[str, tuple[str, str]] = {"actual": (column, "mean")}
        lookup = labeled.groupby(["station_id", "month"], as_index=False).agg(
            actual=(column, "mean"),
        )
        if prov_col:
            prov = (
                labeled.groupby(["station_id", "month"])[[prov_col]]
                .agg(augment_provenance)
                .reset_index()
            )
            lookup = lookup.merge(prov, on=["station_id", "month"], how="left", sort=False)
            lookup = lookup.rename(columns={prov_col: "actual_provenance"})
        else:
            lookup["actual_provenance"] = spec.label_provenance
        lookup["input_month"] = (
            pd.to_datetime(lookup["month"] + "-01") - pd.DateOffset(months=month_offset)
        ).dt.strftime("%Y-%m")
        lookup = lookup.rename(columns={"month": "target_month"})
        out = base.merge(
            lookup[["station_id", "input_month", "target_month", "actual", "actual_provenance"]],
            left_on=["station_id", "month"],
            right_on=["station_id", "input_month"],
            how="inner", sort=False,
        )
        # 目标月划分：训练/验证/测试按被预测月份切，训练期绝不含目标月之后的信息
        out["dataset_split_frozen"] = out["target_month"].map(split_of_month)
        # 目标月日历：模型学「被预测月份的季节」，与推理侧 target-month 日历一致
        month_num = out["target_month"].str[5:7].astype(int)
        angle = 2.0 * np.pi * (month_num - 1) / 12.0
        out["calendar_month_sin"] = np.sin(angle)
        out["calendar_month_cos"] = np.cos(angle)
        out["actual"] = pd.to_numeric(out["actual"], errors="coerce")
    keep = [
        "row_id", "station_id", "month", "target_month", "dataset_split_frozen",
        "actual", "actual_provenance", *feature_columns,
    ]
    out = out.loc[:, [c for c in keep if c in out.columns]].reset_index(drop=True)
    if spec.problem_type == "ordinal":
        out["actual"] = risk_band(out["actual"]).astype("object")
    return out


def availability_entry(
    table: pd.DataFrame, spec: TaskSpecReal, horizon_days: int, month_offset: int
) -> dict:
    counts = table["dataset_split_frozen"].value_counts().to_dict() if len(table) else {}
    train_n = int(counts.get("train", 0))
    val_n = int(counts.get("validation", 0))
    test_n = int(counts.get("test", 0))
    provenance = provenance_summary(table, spec.label_provenance)
    entry = {
        "task_id": spec.task_id,
        "variant": spec.variant,
        "horizon_days": int(horizon_days),
        "month_offset": int(month_offset),
        "train_rows": train_n,
        "validation_rows": val_n,
        "test_rows": test_n,
        # label_provenance = 逐行 actual_provenance 的权威汇总（不是任务配置的声明值）；
        # 声明值另存 label_provenance_declared，供审计"声明与事实是否一致"。
        "label_provenance": provenance["observed"],
        "label_provenance_declared": provenance["declared"],
        "label_provenance_breakdown": provenance["breakdown"],
        "label_provenance_rows": provenance["rows"],
    }
    if spec.problem_type == "none":
        entry.update(trainable=False, reason="no_real_label_in_release")
        return entry
    if train_n < 10:
        entry.update(trainable=False, reason="insufficient_train_rows_min10")
        return entry
    if val_n < 5:
        entry.update(trainable=False, reason="insufficient_validation_rows_min5")
        return entry
    if spec.problem_type in {"binary", "ordinal"}:
        train_labels = table.loc[table["dataset_split_frozen"] == "train", "actual"].dropna()
        if train_labels.nunique() < 2:
            entry.update(trainable=False, reason="single_class_train_labels")
            return entry
    entry.update(trainable=True, reason=None)
    return entry


def build_availability_matrix(
    base: pd.DataFrame, labels: pd.DataFrame
) -> tuple[list[dict], dict[str, pd.DataFrame]]:
    entries: list[dict] = []
    tables: dict[str, pd.DataFrame] = {}
    for spec in TASK_SPECS_REAL:
        for horizon in HORIZONS_V3:
            offset = HORIZON_MAP_V3.month_offset(horizon)
            if spec.problem_type == "none":
                table = pd.DataFrame(columns=["row_id", "station_id", "month", "dataset_split_frozen", "actual"])
            else:
                table = build_supervised_table(base, labels, spec, offset)
            key = f"{spec.task_id}-{spec.variant}-{offset}m"
            tables[key] = table
            entries.append(availability_entry(table, spec, horizon, offset))
    return entries, tables


def contract_manifest_fragment() -> dict:
    return {
        "version": "v2.0",
        "n_features": len(FEATURE_COLUMNS_V2),
        "sha256": feature_contract_sha256(),
        "groups": {
            "water_quality": 10, "meteorology": 5, "hydrology": 2, "remote_sensing": 20,
            "static": 6, "calendar": 2, "mechanism": 6, "lag_state": 27,
        },
    }


def split_manifest_fragment(base: pd.DataFrame) -> dict:
    counts = base["dataset_split_frozen"].value_counts().to_dict()
    return {
        "rule": "frozen_by_issue_month: train<=2021-12, validation=2022-01..2023-12, test>=2024-01",
        "frozen_by": "target_builder.split_of_month (V0.3 rebuild, supersedes model_dataset.dataset_split 882/23/9)",
        "rows": {k: int(counts.get(k, 0)) for k in ("train", "validation", "test")},
        "bounds": SPLIT_BOUNDS,
        "row_granularity": "station_month; field-campaign samples retained at sample level (IN_SITU_GROUP/S1)",
        "note": (
            "wq 常规站样本仅 2005-02..2020-11（季度，含 phyto_biomass 576 行全在 train 期）；"
            "chla 地面样本为 2020-12/2022-12/2023-10 野外航次 + 2026-08 S1；"
            "CLMS（bloom_label / fcb_prob）覆盖 2020-12/2022-12/2023-10 + 2024-09..2026-08，全在 validation/test 期；"
            "MODIS-Aqua chla_retrieval（TAIHU_BBOX 湖面提取）valid 优先聚合，"
            "无 valid 月回退 review（降权披露：有效像元 <5% 或聚合天数 <3），"
            "湖面月均 ≥20μg/L 计阳性，仅映射 TAIHU_WHOLE 行"
        ),
    }
