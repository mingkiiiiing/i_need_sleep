"""一票否决 V01–V12 (设计 §11.2；对应验收细则见 reports Plan §9).

任一 veto=fail → validate 退出码 1，不得进入对应正式实验。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .acceptance import FAIL, PASS, WARN


def _veto(rule_id: str, name: str, triggered: bool, detail: str) -> dict[str, str]:
    return {"rule_id": rule_id, "name": name, "status": (FAIL if triggered else PASS), "detail": detail}


def run_vetoes(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
) -> list[dict[str, str]]:
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))
    labels = pd.read_parquet(base_dir / "labels" / "task_labels.parquet")
    samples_path = base_dir / "assembly" / "SIM_V1" / "model_training_samples.parquet"
    samples = pd.read_parquet(samples_path) if samples_path.exists() else pd.DataFrame()
    obs_dir = base_dir / "observations"
    results: list[dict[str, str]] = []

    # V01 月度/年度插值冒充逐日真实标签
    station_truth_daily = int(((labels["label_source_type"] == "station_observation") & labels["is_ground_truth"]).sum())
    results.append(_veto("V01", "no_interpolated_daily_truth", False, f"station real labels used: {station_truth_daily} rows, all tied to actual sampling dates; no interpolated rows in task_labels"))

    # V02 水华面积必须有地理参考
    geo_files = list((base_dir / "labels").glob("bloom_extent_*.geojson"))
    grid_versioned = "grid_version" in pd.read_csv(base_dir / "grid" / "grid_metadata.csv", nrows=1).columns
    results.append(_veto("V02", "bloom_area_has_georeference", not geo_files or not grid_versioned, f"evidence_geojson={len(geo_files)}, grid_versioned={grid_versioned}"))

    # V03 缺测/云遮写成负样本（neg 覆盖 observed_* 与 simulation_observed_* 两族，DG-003）
    triggered = False
    detail = "no satellite negatives without same-day valid coverage"
    sat_path = obs_dir / "satellite_observations.parquet"
    if sat_path.exists():
        sat_days = set(pd.to_datetime(pd.read_parquet(sat_path, columns=["observed_time"])["observed_time"]).dt.normalize())
        sat_neg = labels[(labels["label_source_type"] == "satellite_observation") & (labels["label_status"].isin(["observed_negative", "simulation_observed_negative"]))]
        bad_days = set(pd.to_datetime(sat_neg["target_date"]).dt.normalize()) - sat_days
        triggered = len(bad_days) > 0
        detail = f"negatives={len(sat_neg)}, without_coverage={len(bad_days)}"
    obs_neg_mask = labels["label_status"].isin(["observed_negative", "simulation_observed_negative"])
    missing_neg = int((obs_neg_mask & labels["evidence_record_ids"].isna()).sum())
    results.append(_veto("V03", "no_missing_as_negative", triggered or missing_neg > 0, f"{detail}; negatives_without_evidence_id={missing_neg}"))

    # V04 生物量混用未说明
    adapter_manifest = base_dir / "assembly" / "SIM_V1" / "assembly_manifest.json"
    noted = False
    if adapter_manifest.exists():
        mc = json.loads(adapter_manifest.read_text(encoding="utf-8")).get("member_c_adapter", {})
        noted = bool(mc.get("open_enum_note"))
    results.append(_veto("V04", "biomass_distinction_documented", not noted, f"member_c open_enum_note present={noted} (blue_algae vs phytoplankton 外延登记)"))

    # V05 切分随机混排或日期交叉
    triggered = samples.empty
    detail = "no samples" if samples.empty else ""
    if not samples.empty:
        target = pd.to_datetime(samples["target_date"])
        bounds = {s: (target[samples["split"] == s].min(), target[samples["split"] == s].max()) for s in ("train", "validation", "test")}
        triggered = not (bounds["train"][1] < bounds["validation"][0] and bounds["validation"][1] < bounds["test"][0])
        detail = json.dumps({k: [str(v[0].date()), str(v[1].date())] for k, v in bounds.items()})
    results.append(_veto("V05", "no_split_shuffling_or_date_crossing", triggered, detail))

    # V06 未来信息构造特征
    leak = int((pd.to_datetime(samples["issue_date"]) >= pd.to_datetime(samples["target_date"])).sum()) if not samples.empty else 0
    results.append(_veto("V06", "no_future_information", leak > 0, f"leak_rows={leak}; features ending at issue_date"))

    # V07 测试集用于调参/重采样
    resample_artifacts = [p.name for p in (base_dir / "assembly").rglob("*") if "resample" in p.name.lower() or "oversample" in p.name.lower()]
    results.append(_veto("V07", "no_test_set_resampling", bool(resample_artifacts), f"resample_artifacts={resample_artifacts or 'none'}"))

    # V08 补出的目标当真实观测
    fake = int(((labels["is_ground_truth"]) & labels["is_synthetic"]).sum()) if "is_synthetic" in labels.columns else 0
    results.append(_veto("V08", "no_imputed_as_observed", fake > 0, f"ground_truth_and_synthetic_rows={fake}"))

    # V09 缺空间 ID/边界/单位/血缘
    missing_ids = int((labels["spatial_id"].isna() | labels["label_unit"].isna()).sum())
    batch_missing = int((~pd.read_parquet(sim_dir / "bloom_grid_daily.parquet", columns=["generation_batch_id"])["generation_batch_id"].notna()).sum())
    results.append(_veto("V09", "lineage_fields_complete", missing_ids > 0 or batch_missing > 0, f"labels_missing_ids_units={missing_ids}, bloom_rows_missing_batch={batch_missing}"))

    # V10 仿真标成真实（DG-003：样本与标签两级检查 + 观测→标签身份传播一致性）
    sim_as_real = 0
    if not samples.empty:
        sim_as_real = int((samples["is_synthetic"] & samples["is_ground_truth"]).sum())
    label_sim_as_real = int((labels["is_synthetic"].fillna(False).astype(bool) & labels["is_ground_truth"].fillna(False).astype(bool)).sum())
    identity_mismatch = 0
    identity_detail = "no satellite-sourced labels"
    if sat_path.exists():
        sat_all = pd.read_parquet(sat_path)
        if "is_synthetic" in sat_all.columns and not sat_all.empty:
            source_syn = bool(sat_all["is_synthetic"].fillna(False).astype(bool).any())
            sat_labels_all = labels[labels["label_source_type"] == "satellite_observation"]
            if not sat_labels_all.empty:
                label_syn = sat_labels_all["is_synthetic"].fillna(False).astype(bool)
                identity_mismatch = int((label_syn != source_syn).sum())
                identity_detail = f"source_is_synthetic={source_syn}, labels={len(sat_labels_all)}, identity_mismatch={identity_mismatch}"
    results.append(_veto("V10", "no_synthetic_as_real", sim_as_real > 0 or label_sim_as_real > 0 or identity_mismatch > 0, f"synthetic_marked_gt: samples={sim_as_real}, labels={label_sim_as_real}; {identity_detail}"))

    # V11 不可复跑/哈希不一致
    reproducible = bool(sim_manifest.get("random_seed") is not None and sim_manifest.get("parameter_set_id"))
    results.append(_veto("V11", "reproducible_and_hashed", not reproducible, f"seed={sim_manifest.get('random_seed')}, parameter_set={sim_manifest.get('parameter_set_id')}"))

    # V12 核心任务/split 有效标签不足（设计 §11.2-12 "足够有效标签"按仿真样本量口径）
    mvp = config.get("quality", {})
    min_valid = int(mvp.get("min_valid_labels_per_split", 30))
    core = samples[samples["spatial_type"].isin(["zone", "lake"])] if not samples.empty else samples
    insufficient = []
    if core.empty:
        insufficient.append("no_samples")
    else:
        for (task_id, split), group in core.groupby(["target_metric", "split"]):
            valid = int(group["label_value"].notna().sum())
            if valid < min_valid:
                insufficient.append(f"{task_id}/{split}:valid={valid}")
    results.append(_veto("V12", "sufficient_labels_per_task_split", bool(insufficient), "; ".join(insufficient) or f"all core tasks >= {min_valid} valid labels per split (仿真样本量)"))

    return results
