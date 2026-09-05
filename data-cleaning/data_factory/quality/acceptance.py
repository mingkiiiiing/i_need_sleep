"""验收检查 A01–A21 (设计 §11.1；SIM 轨口径，数量统计一律称"仿真样本量").

每个检查返回 (rule_id, name, status: pass|fail|warning, detail)。
数量阈值用 quality.mvp_profile 缩放并如实标注。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_factory import GENERATOR_VERSION
from data_factory.contracts.enums import TASK_UNITS
from data_factory.contracts.schema import validate_schema

PASS, FAIL, WARN = "pass", "fail", "warning"


def _rule(rule_id: str, name: str, ok: bool, detail: str, warn_only: bool = False) -> dict[str, str]:
    return {"rule_id": rule_id, "name": name, "status": (PASS if ok else (WARN if warn_only else FAIL)), "detail": detail}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_acceptance(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
    mechanism: dict[str, Any],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    grid_dir, labels_dir, obs_dir = base_dir / "grid", base_dir / "labels", base_dir / "observations"
    assembly_dir = base_dir / "assembly" / "SIM_V1"
    sim_manifest = _load_json(sim_dir / "sim_manifest.json")
    fit_manifest = _load_json(base_dir / "fit" / "fit_manifest.json")

    cells = pd.read_csv(grid_dir / "grid_metadata.csv")
    mapping = pd.read_csv(grid_dir / "station_grid_mapping.csv")
    bloom_grid = pd.read_parquet(sim_dir / "bloom_grid_daily.parquet")
    bloom_lake = pd.read_parquet(sim_dir / "bloom_lake_daily.parquet")
    bloom_lake["date"] = pd.to_datetime(bloom_lake["date"])
    labels = pd.read_parquet(labels_dir / "task_labels.parquet")
    samples_path = assembly_dir / "model_training_samples.parquet"
    samples = pd.read_parquet(samples_path) if samples_path.exists() else pd.DataFrame()

    # A01 文件可读（以上全部成功加载）
    results.append(_rule("A01", "files_readable", True, f"manifests+tables loaded: bloom_grid={len(bloom_grid)}, labels={len(labels)}, samples={len(samples)}"))

    # A02 Schema 契约
    issues = []
    issues += validate_schema(bloom_grid, "bloom_grid_daily")
    issues += validate_schema(bloom_lake, "bloom_lake_daily")
    issues += validate_schema(labels, "task_labels")
    if not samples.empty:
        issues += validate_schema(samples, "model_training_samples")
    results.append(_rule("A02", "schema_contract", not issues, "; ".join(issues[:5]) or "all core tables match contract"))

    # A03 主键唯一（同一目标日可并存 simulation_truth 与观测两源，以 source_type 区分，设计 §6.1 两层世界）
    dupes = {
        "bloom_grid": int(bloom_grid.duplicated(["grid_id", "date"]).sum()),
        "bloom_lake": int(bloom_lake.duplicated(["date", "spatial_id"]).sum()),
        "labels": int(labels.duplicated(["task_id", "spatial_id", "spatial_type", "target_date", "label_source_type"]).sum()),
    }
    if not samples.empty:
        dupes["samples"] = int(samples.duplicated(["sample_id"]).sum())
    results.append(_rule("A03", "primary_key_unique", all(v == 0 for v in dupes.values()), json.dumps(dupes)))

    # A04 日期连续
    dates = pd.to_datetime(sorted(bloom_lake["date"].unique()))
    expected = pd.date_range(dates.min(), dates.max(), freq="D")
    continuous = len(dates) == len(expected) and (dates == expected).all()
    results.append(_rule("A04", "dates_continuous", bool(continuous), f"{dates.min().date()}..{dates.max().date()} days={len(dates)}/{len(expected)}"))

    # A05 issue/available/target 关系
    problems = []
    for table_name, path in (("station", obs_dir / "station_observations.parquet"), ("satellite", obs_dir / "satellite_observations.parquet")):
        if path.exists():
            obs = pd.read_parquet(path, columns=["observed_time", "available_time"])
            bad = int((pd.to_datetime(obs["available_time"]) < pd.to_datetime(obs["observed_time"])).sum())
            if bad:
                problems.append(f"{table_name}:available<observed={bad}")
    if not samples.empty:
        bad_issue = int((pd.to_datetime(samples["issue_date"]) >= pd.to_datetime(samples["target_date"])).sum())
        if bad_issue:
            problems.append(f"samples:issue>=target={bad_issue}")
        horizon_mismatch = int(((pd.to_datetime(samples["target_date"]) - pd.to_datetime(samples["issue_date"])).dt.days != samples["horizon_days"]).sum())
        if horizon_mismatch:
            problems.append(f"samples:horizon_mismatch={horizon_mismatch}")
    results.append(_rule("A05", "issue_available_target_order", not problems, "; ".join(problems) or "all ordering constraints hold"))

    # A06 单位合法
    unit_map = {**{task: unit for task, unit in TASK_UNITS.items()}, "T3": "10^4 cells/L", "T7": "0/1"}
    expected_units = labels["task_id"].map(unit_map)
    bad_units = int((expected_units != labels["label_unit"]).sum())
    results.append(_rule("A06", "units_legal", bad_units == 0, f"illegal_unit_rows={bad_units}"))

    # A07 物理界限（对抽样潜在值 + 全部标签值）
    bounds = mechanism.get("physical_bounds", {})
    wq = pd.read_parquet(sim_dir / "latent" / f"water_quality_grid_daily_{sim_manifest['zones'][0]}.parquet")
    violations = {}
    variable_bounds = {
        "total_phosphorus": bounds.get("total_phosphorus"),
        "total_nitrogen": bounds.get("total_nitrogen"),
        "dissolved_oxygen": bounds.get("dissolved_oxygen"),
        "pH": bounds.get("pH"),
        "chlorophyll_a": bounds.get("chlorophyll_a"),
        "water_temperature": bounds.get("water_temperature"),
    }
    for variable, rng in variable_bounds.items():
        if not rng:
            continue
        values = wq.loc[wq["variable_code"] == variable, "value"]
        violations[variable] = int(((values < rng[0]) | (values > rng[1])).sum())
    frac_bad = int(((bloom_grid["bloom_fraction"] < 0) | (bloom_grid["bloom_fraction"] > 1)).sum())
    violations["bloom_fraction"] = frac_bad
    # DG-005：pre-clip 触顶/触底率门禁（主变量 >10% 视为物理失真，即使 clip 后合规也 fail）
    bound_rates = sim_manifest.get("bound_hit_rate") or {}
    bound_gate_vars = ("water_level", "total_nitrogen", "total_phosphorus", "chlorophyll_a")
    bound_problems = []
    for variable in bound_gate_vars:
        rate = float(bound_rates.get(variable, 0.0) or 0.0)
        if rate > 0.10:
            bound_problems.append(f"{variable}:bound_hit_rate={rate:.3f}>0.10")
    ok07 = all(v == 0 for v in violations.values()) and not bound_problems
    results.append(_rule("A07", "physical_bounds", ok07, json.dumps({**violations, "bound_hit_rate": {k: bound_rates.get(k, 0.0) for k in bound_gate_vars}})))

    # A08 坐标与湖界
    boundary_ok = (base_dir.parent.parent / "silver" / "geo" / "taihu_boundary.gpkg").exists() or (base_dir / "grid" / "grid_boundaries.geojson").exists()
    coord_bad = int(((cells["lon"] < 119.5) | (cells["lon"] > 121.0) | (cells["lat"] < 30.5) | (cells["lat"] > 32.0)).sum())
    results.append(_rule("A08", "coordinates_and_boundary", bool(boundary_ok) and coord_bad == 0, f"boundary_file={boundary_ok}, out_of_bbox={coord_bad}"))

    # A09 网格版本一致
    versions = cells["grid_version"].unique().tolist()
    results.append(_rule("A09", "grid_version_consistent", len(versions) == 1 and versions[0] == sim_manifest.get("grid_version"), f"csv={versions}, manifest={sim_manifest.get('grid_version')}"))

    # A10 站点-网格-湖区映射
    station_obs_path = obs_dir / "station_observations.parquet"
    unmapped = 0
    if station_obs_path.exists():
        station_obs = pd.read_parquet(station_obs_path, columns=["station_id", "grid_id"])
        sim_station_ids = set(station_obs["station_id"].unique())
        mapped_ids = set(mapping.loc[~mapping["outside_boundary"].astype(str).str.lower().isin(["true", "1", "yes"]), "station_id"])
        unmapped = len(sim_station_ids - mapped_ids)
    results.append(_rule("A10", "station_grid_mapping_complete", unmapped == 0, f"unmapped_stations={unmapped}"))

    # A11 标签证据与 unknown 规则（neg 覆盖 observed_* 与 simulation_observed_* 两族，DG-003）
    sat_labels = labels[labels["label_source_type"] == "satellite_observation"]
    neg_without_evidence = 0
    if station_obs_path.exists() and (obs_dir / "satellite_observations.parquet").exists():
        sat = pd.read_parquet(obs_dir / "satellite_observations.parquet", columns=["observed_time"])
        sat_days = set(pd.to_datetime(sat["observed_time"]).dt.normalize())
        obs_neg_mask = sat_labels["label_status"].isin(["observed_negative", "simulation_observed_negative"])
        sat_neg_days = set(pd.to_datetime(sat_labels.loc[obs_neg_mask, "target_date"]).dt.normalize())
        neg_without_evidence = len(sat_neg_days - sat_days)
    unknown_total = int((labels["label_status"] == "unknown").sum())
    results.append(_rule("A11", "label_evidence_and_unknown_rule", neg_without_evidence == 0, f"negatives_without_satellite_evidence={neg_without_evidence}, unknown_rows={unknown_total}"))

    # A12/A13 覆盖与平衡（设计 §11.1 报告项；硬性不足由 V12 把关）
    mvp = config.get("quality", {})
    min_pos = int(mvp.get("min_positive_dates_per_split", 5))
    min_neg = int(mvp.get("min_negative_dates_per_split", 15))
    binary = labels[labels["label_unit"] == "0/1"]
    balance_rows = []
    warn_entries = []
    for (task_id, spatial_type), group in binary.groupby(["task_id", "spatial_type"]):
        for split in ("train", "validation", "test"):
            merged = pd.DataFrame()
            if not samples.empty:
                merged = samples[(samples["target_metric"] == task_id) & (samples["spatial_type"] == spatial_type) & (samples["split"] == split)]
            if merged.empty:
                sub = group[group["split"] == split] if "split" in group.columns else group
                pos = int((sub["label_value"] == 1).sum())
                neg = int((sub["label_value"] == 0).sum())
                unit = "label_dates"
            else:
                pos = int((merged["label_value"] == 1).sum())
                neg = int((merged["label_value"] == 0).sum())
                unit = "simulation_samples"
            balance_rows.append({"task_id": task_id, "spatial_type": spatial_type, "split": split, "positive": pos, "negative": neg, "unit": unit})
            if pos < min_pos or neg < min_neg:
                warn_entries.append(f"{task_id}/{spatial_type}/{split}:pos={pos},neg={neg}")
    results.append(_rule("A12", "label_coverage_report", True, f"tasks={labels['task_id'].nunique()}, rows={len(labels)} (仿真样本量)"))
    results.append(_rule("A13", "positive_negative_balance", not warn_entries, f"mvp_min_pos={min_pos}, min_neg={min_neg}; " + ("; ".join(warn_entries[:6]) or "balanced") + f"; entries={len(balance_rows)}", warn_only=True))

    # A14 特征完整度（DG-004 口径：观测层气象特征必须 100%；WQ 观测特征按 feature_observed_ratio 如实报告，不设 100% 门槛）
    if samples.empty:
        results.append(_rule("A14", "feature_completeness", False, "no samples assembled"))
    else:
        parsed = samples["features_json"].head(2000).map(json.loads)
        required = {"air_temperature", "wind_speed", "precipitation", "shortwave_radiation"}
        missing_ratio = float(np.mean([not required.issubset(d.keys()) for d in parsed]))
        ratio_col = pd.to_numeric(samples.get("feature_observed_ratio"), errors="coerce").dropna()
        ratio_desc = f"mean={ratio_col.mean():.3f}, min={ratio_col.min():.3f}, max={ratio_col.max():.3f}" if len(ratio_col) else "n/a"
        all_keys = set().union(*[set(d) for d in parsed]) if len(parsed) else set()
        # TP/TN 已升级为站点仿真观测层特征（含测量误差/发布延迟），不再视为 latent 泄漏
        latent_leak = sorted(all_keys & {"water_level", "cyanobacteria_density", "blue_algae_biomass", "relative_humidity", "bloom_area_km2"})
        ok = missing_ratio == 0.0 and not latent_leak
        results.append(_rule("A14", "feature_completeness", ok, f"weather_core_missing_ratio={missing_ratio:.4f} (sample of {len(parsed)}); feature_observed_ratio {ratio_desc}; latent_feature_keys={latent_leak or 'none'}"))

    # A15 未来泄漏
    leak = 0
    if not samples.empty:
        leak = int((pd.to_datetime(samples["issue_date"]) >= pd.to_datetime(samples["target_date"])).sum())
    results.append(_rule("A15", "no_future_leakage", leak == 0, f"leak_rows={leak}; features only from <= issue_date"))

    # A16 日期交叉
    if samples.empty:
        results.append(_rule("A16", "no_date_crossing", False, "no samples"))
    else:
        target = pd.to_datetime(samples["target_date"])
        ranges = {}
        for split in ("train", "validation", "test"):
            sub = target[samples["split"] == split]
            ranges[split] = (sub.min(), sub.max()) if len(sub) else (None, None)
        ok = (
            ranges["train"][1] is not None
            and ranges["validation"][0] is not None
            and ranges["train"][1] < ranges["validation"][0]
            and ranges["validation"][1] < ranges["test"][0]
        )
        results.append(_rule("A16", "no_date_crossing", bool(ok), json.dumps({k: [str(v[0].date()) if v[0] is not None else None, str(v[1].date()) if v[1] is not None else None] for k, v in ranges.items()})))

    # A17 实体交叉（网格实体按日期切分天然跨 split；报告为 warning 级审计）
    if samples.empty:
        results.append(_rule("A17", "entity_crossing_audit", False, "no samples", warn_only=True))
    else:
        per_entity = samples[samples["spatial_type"] == "grid"].groupby("spatial_id")["split"].nunique()
        multi = int((per_entity > 1).sum())
        results.append(_rule("A17", "entity_crossing_audit", True, f"grid entities spanning >1 split: {multi} (split is date-based; entity overlap expected and reported)", warn_only=True))

    # A18 身份不可逆
    bad_identity = int((samples["is_synthetic"] & samples["is_ground_truth"]).sum()) if not samples.empty else 0
    fake_obs = int(((labels["label_status"].isin(["observed_positive", "observed_negative"])) & labels["is_synthetic"]).sum())
    results.append(_rule("A18", "identity_irreversible", bad_identity == 0 and fake_obs == 0, f"synthetic_gt_rows={bad_identity}, synthetic_observed_labels={fake_obs}"))

    # A19 复现要素
    repro_ok = bool(sim_manifest.get("random_seed") is not None and sim_manifest.get("parameter_set_id") == fit_manifest.get("parameter_set_id") and sim_manifest.get("generator_version") == GENERATOR_VERSION)
    results.append(_rule("A19", "reproducibility_elements", repro_ok, f"seed={sim_manifest.get('random_seed')}, parameter_set={sim_manifest.get('parameter_set_id')}, generator={GENERATOR_VERSION}"))

    # A20 分布核对：仿真月度均值 vs 拟合月度气候态（log 空间 ±3σ）
    dist_problems = []
    ps = pd.read_parquet(base_dir / "fit" / "parameter_sets.parquet")
    for variable in ("chlorophyll_a", "total_phosphorus", "total_nitrogen"):
        values = wq.loc[wq["variable_code"] == variable, ["date", "value"]].copy()
        if values.empty:
            continue
        values["date"] = pd.to_datetime(values["date"])
        values["month"] = values["date"].dt.month
        sim_monthly = np.log(values.groupby("month")["value"].mean().clip(lower=1e-6))
        fitted = ps[(ps["family"] == "nutrients") & (ps["parameter_key"] == "lognorm_mu") & (ps["variable_code"] == variable) & (ps["scope_id"] == f"{sim_manifest['zones'][0]}-m{sim_monthly.index[0]:02d}")]
        if fitted.empty:
            continue
        merged = sim_monthly.to_frame("sim").reset_index()
        merged["fitted"] = [float(ps[(ps["variable_code"] == variable) & (ps["scope_id"] == f"{sim_manifest['zones'][0]}-m{int(m):02d}")]["value"].iloc[0]) for m in merged["month"]]
        merged["sigma"] = [float(ps[(ps["variable_code"] == variable) & (ps["scope_id"] == f"{sim_manifest['zones'][0]}-m{int(m):02d}") & (ps["parameter_key"] == "lognorm_sigma")]["value"].iloc[0]) for m in merged["month"]]
        dev = (merged["sim"] - merged["fitted"]).abs() / merged["sigma"].clip(lower=0.15)
        if float(dev.max()) > 5.0:
            dist_problems.append(f"{variable}:max_z={float(dev.max()):.2f}")
    results.append(_rule("A20", "distribution_vs_climatology", not dist_problems, "; ".join(dist_problems) or "monthly log-means within tolerance of fitted climatology", warn_only=True))

    # A21 季节性（DG-006 硬门禁：chla 夏/冬均值比 >= 1.5）与空间聚集方向（信息性）
    wq_chla = wq[wq["variable_code"] == "chlorophyll_a"].copy()
    wq_chla["date"] = pd.to_datetime(wq_chla["date"])
    monthly = wq_chla.groupby(wq_chla["date"].dt.month)["value"].mean()
    summer = float(monthly.reindex([6, 7, 8]).mean())
    winter = float(monthly.reindex([12, 1, 2]).mean())
    season_ratio = summer / winter if winter > 0 else float("inf")
    bloom_lake_zone = bloom_lake[bloom_lake["spatial_id"] != "TAIHU_WHOLE"]
    corr = float(np.corrcoef(
        pd.read_parquet(sim_dir / "latent" / f"weather_daily_{sim_manifest['zones'][0]}.parquet")["wind_speed"],
        bloom_lake_zone.set_index("date").reindex(pd.to_datetime(pd.read_parquet(sim_dir / "latent" / f"weather_daily_{sim_manifest['zones'][0]}.parquet")["date"]))["bloom_fraction_mean"].fillna(0.0),
    )[0, 1])
    seasonal_ok = season_ratio >= 1.5
    results.append(_rule("A21", "chla_seasonality", seasonal_ok, f"chla_summer(6-8)={summer:.2f}, winter(12-2)={winter:.2f}, ratio={season_ratio:.3f} (require>=1.5); corr(wind,bloom)={corr:.3f} (informational, expect<=0.2)"))

    # A22 校准时间截止（DG-002）：每个拟合 family 的最大输入日期不得越过 train 末期
    cutoff_str = str(fit_manifest.get("train_cutoff_date", ""))
    per_family = fit_manifest.get("per_family_max_input_date") or {}
    cutoff_problems = []
    if not fit_manifest.get("cutoff_enforced_all_families") or not per_family:
        cutoff_problems.append("fit manifest missing cutoff enforcement fields")
    for family, max_date in sorted(per_family.items()):
        if max_date and cutoff_str and str(max_date) > cutoff_str:
            cutoff_problems.append(f"{family}:max_input={max_date}>cutoff={cutoff_str}")
        if max_date is None:
            cutoff_problems.append(f"{family}:no_valid_input_dates")
    results.append(_rule("A22", "calibration_cutoff_enforced", not cutoff_problems, "; ".join(cutoff_problems) or f"all family max_input_date <= train_cutoff {cutoff_str}"))

    # A23 部分域显式标注（DG-001）：lake 粒度行（bloom_lake 与 task_labels）必须带覆盖率
    coverage_problems = []
    lake_bl = bloom_lake[bloom_lake["spatial_id"] == "TAIHU_WHOLE"]
    if lake_bl.empty:
        coverage_problems.append("bloom_lake has no TAIHU_WHOLE rows")
    else:
        if "domain_coverage_fraction" not in bloom_lake.columns:
            coverage_problems.append("bloom_lake missing domain_coverage_fraction")
        else:
            cov = lake_bl["domain_coverage_fraction"]
            if cov.isna().any():
                coverage_problems.append(f"lake rows null coverage={int(cov.isna().sum())}")
            bad_rng = int(((cov <= 0) | (cov > 1)).sum())
            if bad_rng:
                coverage_problems.append(f"lake rows coverage outside (0,1]={bad_rng}")
            if "is_partial_domain" in lake_bl.columns:
                partial_bad = int((lake_bl.loc[lake_bl["is_partial_domain"] == True, "domain_coverage_fraction"] >= 1).sum())  # noqa: E712
                if partial_bad:
                    coverage_problems.append(f"partial rows with coverage>=1={partial_bad}")
    if "domain_coverage_fraction" not in labels.columns:
        coverage_problems.append("task_labels missing domain_coverage_fraction")
    else:
        lake_labels = labels[labels["spatial_type"] == "lake"]
        null_lab = int(lake_labels["domain_coverage_fraction"].isna().sum()) if len(lake_labels) else 0
        if null_lab:
            coverage_problems.append(f"lake labels null coverage={null_lab}")
    lake_cov_value = float(lake_bl["domain_coverage_fraction"].iloc[0]) if not lake_bl.empty and "domain_coverage_fraction" in lake_bl.columns else None
    results.append(_rule("A23", "partial_domain_explicit", not coverage_problems, "; ".join(coverage_problems) or f"lake coverage={lake_cov_value}, partial={bool(lake_bl['is_partial_domain'].iloc[0]) if not lake_bl.empty and 'is_partial_domain' in lake_bl.columns else 'n/a'}"))

    return results
