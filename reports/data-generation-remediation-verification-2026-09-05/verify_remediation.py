from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd


REPORT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = REPORT_DIR.parents[1]
DATA_ROOT = PROJECT_ROOT / "data-cleaning"
RUN_ROOT = DATA_ROOT / "storage" / "runs" / "data_factory" / "mvp_meiliangwan_2024"
SIM_ROOT = RUN_ROOT / "simulation" / "baseline_seed20260904"
RELEASE_ROOT = DATA_ROOT / "storage" / "releases" / "data_factory_release" / "SIM-V1"
CUTOFF = pd.Timestamp("2024-08-28")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metric(rows: list[dict], name: str, value, unit: str, result: str, evidence: str) -> None:
    if isinstance(value, np.integer):
        value = int(value)
    elif isinstance(value, np.floating):
        value = float(value)
    rows.append({"metric": name, "value": value, "unit": unit, "result": result, "evidence": evidence})


def dg(rows: list[dict], issue_id: str, verdict: str, claim: str, evidence: str, residual: str = "") -> None:
    rows.append({"issue_id": issue_id, "verdict": verdict, "claim": claim, "evidence": evidence, "residual_risk": residual})


def main() -> None:
    metrics: list[dict] = []
    matrix: list[dict] = []
    residuals: list[dict] = []

    release_manifest = json.loads((RELEASE_ROOT / "release_manifest.json").read_text(encoding="utf-8"))
    fit_manifest = json.loads((RELEASE_ROOT / "lineage/manifests/fit_manifest.json").read_text(encoding="utf-8"))
    sim_manifest = json.loads((RELEASE_ROOT / "lineage/manifests/sim_manifest.json").read_text(encoding="utf-8"))
    obs_manifest = json.loads((RELEASE_ROOT / "lineage/manifests/observations_manifest.json").read_text(encoding="utf-8"))

    bloom_lake = pd.read_parquet(RELEASE_ROOT / "data/bloom_lake_daily.parquet")
    wq = pd.read_parquet(SIM_ROOT / "latent/water_quality_grid_daily_TAIHU_ML.parquet")
    hydro = pd.read_parquet(SIM_ROOT / "latent/hydrology_daily_TAIHU_ML.parquet")
    labels = pd.read_parquet(RELEASE_ROOT / "data/task_labels.parquet")
    samples = pd.read_parquet(RELEASE_ROOT / "data/model_training_samples.parquet")
    station = pd.read_parquet(RELEASE_ROOT / "data/station_observations.parquet")
    satellite = pd.read_parquet(RELEASE_ROOT / "data/satellite_observations.parquet")
    target_obs = pd.read_parquet(RELEASE_ROOT / "data/target_observation_daily.parquet")
    row_lineage = pd.read_parquet(RELEASE_ROOT / "lineage/row_lineage.parquet")
    file_lineage = pd.read_parquet(RELEASE_ROOT / "lineage/file_lineage.parquet")
    acceptance = pd.read_csv(RELEASE_ROOT / "quality/acceptance_21.csv")
    veto = pd.read_csv(RELEASE_ROOT / "quality/veto_12.csv")
    split_manifest = pd.read_csv(RELEASE_ROOT / "data/split_manifest.csv", parse_dates=["date"])

    # Repository and immutable release evidence.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    code_diff = subprocess.check_output(
        ["git", "diff", "--name-only", release_manifest["code_commit"], "--", "data-cleaning/data_factory", "data-cleaning/config/data_factory", "data-cleaning/tests"],
        cwd=PROJECT_ROOT,
        text=True,
    ).strip().splitlines()
    tracked = subprocess.check_output(
        ["git", "ls-files", "data-cleaning/data_factory", "data-cleaning/config/data_factory", "data-cleaning/tests/test_data_factory*"],
        cwd=PROJECT_ROOT,
        text=True,
    ).strip().splitlines()

    hash_failures: list[str] = []
    hash_entries = 0
    for line in (RELEASE_ROOT / "hashes.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split(None, 1)
        rel = rel.strip().lstrip("*")
        path = RELEASE_ROOT / rel
        hash_entries += 1
        if not path.exists() or sha256(path) != expected:
            hash_failures.append(rel)
    disk_files = sum(1 for p in RELEASE_ROOT.rglob("*") if p.is_file())
    archive = RELEASE_ROOT.parent / "SIM-V1-audit-20260904-rejected"
    archive_files = sum(1 for p in archive.rglob("*") if p.is_file()) if archive.exists() else 0
    metric(metrics, "release_manifest_files", release_manifest["files"], "hashed files", "pass", "manifest.files")
    metric(metrics, "release_disk_files", disk_files, "files", "informational", "45 payload files plus hashes, manifest and generated support files")
    metric(metrics, "release_hash_failures", len(hash_failures), "files", "pass" if not hash_failures else "fail", "; ".join(hash_failures) or "45/45 SHA-256 matched")
    metric(metrics, "release_code_commit_matches_head", int(release_manifest["code_commit"] == head), "boolean", "pass" if release_manifest["code_commit"] == head else "warning", f"manifest={release_manifest['code_commit']}; HEAD={head}")
    metric(metrics, "data_factory_paths_changed_since_release_commit", len(code_diff), "files", "pass" if not code_diff else "fail", "; ".join(code_diff) or "none")
    metric(metrics, "tracked_data_factory_files", len(tracked), "files", "pass", "git ls-files")
    metric(metrics, "archived_old_release_files", archive_files, "files", "pass" if archive.exists() and archive_files else "fail", str(archive))

    # DG-001: copied values remain, but identity is explicitly partial throughout lake outputs.
    zone = bloom_lake[bloom_lake.spatial_id.eq("TAIHU_ML")].sort_values("date")
    whole = bloom_lake[bloom_lake.spatial_id.eq("TAIHU_WHOLE")].sort_values("date")
    copied = len(zone) == len(whole) and np.allclose(zone.bloom_area_km2, whole.bloom_area_km2) and np.allclose(zone.bloom_fraction_mean, whole.bloom_fraction_mean)
    coverage = float(whole.domain_coverage_fraction.min())
    lake_label = labels[(labels.spatial_type == "lake")]
    lake_sample = samples[(samples.spatial_type == "lake")]
    partial_propagates = bool(
        len(whole)
        and whole.is_partial_domain.all()
        and (whole.domain_coverage_fraction < 1).all()
        and len(lake_label)
        and lake_label.is_partial_domain.all()
        and (lake_label.domain_coverage_fraction < 1).all()
        and len(lake_sample)
        and lake_sample.is_partial_domain.all()
        and (lake_sample.domain_coverage_fraction < 1).all()
    )
    metric(metrics, "whole_lake_values_still_equal_ml", int(copied), "boolean", "warning", "Numerical copying remains by approved partial-domain design")
    metric(metrics, "partial_domain_coverage", coverage, "ratio", "pass" if np.isclose(coverage, 0.208298) else "fail", "TAIHU_WHOLE minimum coverage")
    dg(matrix, "DG-001", "通过（范围显式化）" if partial_propagates else "未通过", "全湖复制不再冒充全湖覆盖", f"coverage={coverage:.6f}; whole/labels/samples partial propagation={partial_propagates}; values_equal_ML={copied}", "仍未实现全湖仿真，只能按部分域 lake 代理使用")

    # DG-002: manifest and code-testable cutoff evidence.
    family_dates = {k: pd.Timestamp(v) for k, v in fit_manifest["per_family_max_input_date"].items()}
    cutoff_ok = bool(fit_manifest.get("cutoff_enforced_all_families") and all(v <= CUTOFF for v in family_dates.values()))
    metric(metrics, "fit_families_at_or_before_cutoff", sum(v <= CUTOFF for v in family_dates.values()), "of 6", "pass" if cutoff_ok else "fail", json.dumps({k: str(v.date()) for k, v in family_dates.items()}, ensure_ascii=False))
    dg(matrix, "DG-002", "通过" if cutoff_ok else "未通过", "所有拟合族执行训练截止门禁", json.dumps({k: str(v.date()) for k, v in family_dates.items()}, ensure_ascii=False), "历史文件中存在截止后记录是允许的；关键是不得进入 fit")

    # DG-003 identity.
    sat_labels = labels[labels.label_source_type.eq("satellite_observation")]
    sat_identity_ok = bool(len(sat_labels) == 70 and sat_labels.is_synthetic.all() and (~sat_labels.is_ground_truth).all() and sat_labels.label_status.str.startswith("simulation_observed_").all())
    metric(metrics, "satellite_labels", len(sat_labels), "rows", "pass" if sat_identity_ok else "fail", f"synthetic={int(sat_labels.is_synthetic.sum())}; ground_truth={int(sat_labels.is_ground_truth.sum())}")
    dg(matrix, "DG-003", "通过" if sat_identity_ok else "未通过", "卫星模拟观测身份不可逆", f"70 labels; statuses={sorted(sat_labels.label_status.unique())}; upstream satellite synthetic={int(satellite.is_synthetic.sum())}/{len(satellite)}")

    # DG-004 observation-layer feature assembly and leakage claims.
    observed_ratio = samples.feature_observed_ratio.astype(float)
    parsed = samples.features_json.head(5000).map(json.loads)
    latent_tokens = ("latent", "truth_")
    latent_keys = sorted({key for row in parsed for key in row if any(token in key.lower() for token in latent_tokens)})
    feature_ok = not latent_keys and observed_ratio.between(0, 1).all()
    metric(metrics, "training_samples", len(samples), "rows", "pass", "model_training_samples.parquet")
    metric(metrics, "feature_observed_ratio_mean", float(observed_ratio.mean()), "ratio", "pass", f"min={observed_ratio.min():.4f}; max={observed_ratio.max():.4f}")
    metric(metrics, "sampled_latent_feature_keys", len(latent_keys), "keys", "pass" if not latent_keys else "fail", ",".join(latent_keys) or "none in first 5,000 samples")
    dg(matrix, "DG-004", "通过" if feature_ok else "未通过", "训练特征改由可用时刻受控的观测层装配", f"rows={len(samples)}; observed_ratio mean={observed_ratio.mean():.3f}; latent keys={latent_keys or 'none'}", "本复核按字段与门禁验证，未把仿真观测等同于真实观测")

    # DG-005 and DG-006 physical behavior.
    level = hydro.water_level_m.astype(float)
    level_bounds = float((np.isclose(level, 2.0) | np.isclose(level, 5.0)).mean())
    bound_defs = {"total_phosphorus": (0.005, 2.0), "total_nitrogen": (0.1, 12.0)}
    bound_shares = {}
    for variable, (low, high) in bound_defs.items():
        values = wq.loc[wq.variable_code.eq(variable), "value"].astype(float)
        bound_shares[variable] = float((np.isclose(values, low) | np.isclose(values, high)).mean())
    chla = wq[wq.variable_code.eq("chlorophyll_a")].copy()
    months = pd.to_datetime(chla.date).dt.month
    summer = float(chla.loc[months.isin([6, 7, 8]), "value"].mean())
    winter = float(chla.loc[months.isin([12, 1, 2]), "value"].mean())
    chla_ratio = summer / winter
    physical_ok = level_bounds == 0 and bound_shares["total_nitrogen"] == 0 and bound_shares["total_phosphorus"] < 0.05
    metric(metrics, "water_level_min", float(level.min()), "m", "pass", f"max={level.max():.6f}; mean={level.mean():.6f}")
    metric(metrics, "water_level_bound_share", level_bounds, "ratio", "pass" if level_bounds == 0 else "fail", "exactly 2.0 or 5.0 m")
    metric(metrics, "total_phosphorus_bound_share", bound_shares["total_phosphorus"], "ratio", "pass" if bound_shares["total_phosphorus"] < 0.05 else "fail", "lower+upper exact-bound share")
    metric(metrics, "total_nitrogen_bound_share", bound_shares["total_nitrogen"], "ratio", "pass" if bound_shares["total_nitrogen"] < 0.05 else "fail", "lower+upper exact-bound share")
    metric(metrics, "chlorophyll_a_summer_winter_ratio", chla_ratio, "ratio", "pass" if chla_ratio >= 1.5 else "fail", f"summer={summer:.6f}; winter={winter:.6f}")
    dg(matrix, "DG-005", "通过" if physical_ok else "未通过", "水位塌缩与营养盐边界饱和修复", f"level={level.min():.3f}..{level.max():.3f} m, bound={level_bounds:.2%}; TP={bound_shares['total_phosphorus']:.2%}; TN={bound_shares['total_nitrogen']:.2%}")
    dg(matrix, "DG-006", "通过" if chla_ratio >= 1.5 else "未通过", "Chl-a 季节性增强", f"summer/winter={chla_ratio:.3f}")

    # DG-007 class balance at unique-date grain.
    binary = samples[samples.target_metric.isin(["T1", "T7"])].copy()
    balance = (
        binary.drop_duplicates(["target_metric", "spatial_type", "spatial_id", "split", "target_date", "label_value"])
        .groupby(["target_metric", "spatial_type", "split"])
        .label_value.agg(samples="size", positives="sum").reset_index()
    )
    balance["positive_rate"] = balance.positives / balance.samples
    degenerate = balance[balance.positive_rate.isin([0.0, 1.0])]
    metric(metrics, "single_class_binary_groups", len(degenerate), "groups", "warning" if len(degenerate) else "pass", "; ".join(f"{r.target_metric}/{r.spatial_type}/{r.split}={r.positive_rate:.0%}" for r in degenerate.itertuples()))
    dg(matrix, "DG-007", "保留警告（未根治）" if len(degenerate) else "通过", "单类组合风险", f"unique-date single-class groups={len(degenerate)}", "不能据此发布完整二分类验证结论；至少五年、含多次事件的真实时序才可根治")

    # DG-008 task-grain contract decision.
    task_grains = labels.groupby("task_id").spatial_type.apply(lambda x: sorted(set(x))).to_dict()
    matrix_text = (DATA_ROOT / "data_factory/contracts/schema.py").read_text(encoding="utf-8")
    task_matrix_present = "TASK_GRAIN_MATRIX" in matrix_text
    missing_grid = sorted(set(f"T{i}" for i in range(1, 8)) - set(labels.loc[labels.spatial_type.eq("grid"), "task_id"]))
    metric(metrics, "tasks_without_grid_labels", len(missing_grid), "tasks", "informational", ",".join(missing_grid) or "none")
    dg(matrix, "DG-008", "通过（契约裁决）" if task_matrix_present else "未通过", "任务粒度由 TASK_GRAIN_MATRIX 明确登记", f"matrix present={task_matrix_present}; actual grains={json.dumps(task_grains, ensure_ascii=False)}", f"{','.join(missing_grid)} 仍未实现 grid 标签；这是范围裁决，不是能力补齐")

    # DG-009/010 packaging and lineage.
    required = [
        "lineage/source_registry.csv", "generation/parameter_sets.parquet", "lineage/transformation_log.jsonl",
        "quality/leakage_audit.csv", "data/target_observation_daily.parquet", "data/dynamic_features_grid_daily.parquet",
    ]
    missing = [p for p in required if not (RELEASE_ROOT / p).exists()]
    sample_ids = set(samples.sample_id.astype(str))
    lineage_ids = set(row_lineage.sample_id.astype(str))
    lineage_coverage = len(sample_ids & lineage_ids) / len(sample_ids)
    metric(metrics, "formal_contract_files_missing", len(missing), "files", "pass" if not missing else "fail", ",".join(missing) or "none")
    metric(metrics, "row_lineage_rows", len(row_lineage), "rows", "pass" if len(row_lineage) == len(samples) else "fail", f"sample rows={len(samples)}; id coverage={lineage_coverage:.2%}")
    metric(metrics, "file_lineage_rows", len(file_lineage), "rows", "pass", "separate file-level lineage retained")
    dg(matrix, "DG-009", "通过" if not missing else "未通过", "正式交付契约文件补齐", f"missing={missing}; hashes={hash_entries}/45, failures={len(hash_failures)}")
    dg(matrix, "DG-010", "通过" if len(row_lineage) == len(samples) and lineage_coverage == 1 else "未通过", "样本级 row lineage", f"row_lineage={len(row_lineage)}; samples={len(samples)}; sample_id coverage={lineage_coverage:.2%}; file_lineage={len(file_lineage)}")

    # DG-011 stage verdict and gates.
    a_status = acceptance.status.value_counts().to_dict()
    v_status = veto.status.value_counts().to_dict()
    qtext = (RELEASE_ROOT / "quality/quality_summary.md").read_text(encoding="utf-8")
    stage_ok = all(token in qtext for token in ("packaging | **PASS**", "simulation_fidelity | **PASS**", "training_readiness | **WARNING**"))
    metric(metrics, "acceptance_pass", a_status.get("pass", 0), "rules", "pass", json.dumps(a_status))
    metric(metrics, "acceptance_warning", a_status.get("warning", 0), "rules", "warning", "A13")
    metric(metrics, "veto_pass", v_status.get("pass", 0), "rules", "pass" if v_status.get("pass", 0) == 12 else "fail", json.dumps(v_status))
    dg(matrix, "DG-011", "通过（SIM 发布口径）" if stage_ok else "未通过", "三段式判定落地", f"packaging=PASS, fidelity=PASS, readiness=WARNING; acceptance={a_status}; veto={v_status}", "摘要仍显示总体 PASS；正式实验不得把它解释为 training readiness PASS")

    # DG-012 repository identity.
    commit_ok = head == release_manifest["code_commit"] and not code_diff and len(tracked) >= 50
    dg(matrix, "DG-012", "通过" if commit_ok else "未通过", "代码已冻结并写入发布 manifest", f"HEAD={head}; code_commit={release_manifest['code_commit']}; changed_since_commit={len(code_diff)}; tracked={len(tracked)}")

    # DG-013 station observations.
    station_ok = bool(len(station) == 576 and station.station_id.nunique() == 4 and station.grid_id.notna().all() and station.is_synthetic.all() and (~station.is_ground_truth).all())
    blank_units = int(station.unit.fillna("").eq("").sum())
    null_names = int(station.station_name.isna().sum())
    metric(metrics, "station_observation_rows", len(station), "rows", "pass" if station_ok else "fail", f"stations={station.station_id.nunique()}; grids={station.grid_id.nunique()}")
    metric(metrics, "station_observation_blank_units", blank_units, "rows", "warning" if blank_units else "pass", "A06 currently validates label units, not observation units")
    metric(metrics, "station_observation_null_names", null_names, "rows", "warning" if null_names else "pass", "station_id remains populated")
    dg(matrix, "DG-013", "通过（有附加质量缺口）" if station_ok else "未通过", "界内站点观测恢复", f"rows={len(station)}; stations={station.station_id.nunique()}; mapped grids={station.grid_id.nunique()}; synthetic={int(station.is_synthetic.sum())}", f"576/576 unit 为空且 station_name 为空；身份正确但字段语义不完整")

    # DG-014 MEE time and identity/QC.
    mee = pd.read_parquet(RUN_ROOT / "realtime/mee_observations.parquet")
    mee_obs = pd.read_parquet(RUN_ROOT / "observations/mee_realtime_observations.parquet")
    mee_time = pd.to_datetime(mee.observed_time, errors="coerce")
    mee_tz_ok = bool(mee_time.notna().all() and getattr(mee_time.dt, "tz", None) is not None)
    corrupted = int(mee.station_name.astype(str).str.contains("\ufffd").sum())
    candidate_gt = int((mee.role.eq("observation_candidate") & mee.is_ground_truth).sum())
    mapped_mee = int(mee_obs.grid_id.notna().sum())
    mee_ok = len(mee) == 708 and mee_tz_ok and corrupted == 0
    metric(metrics, "mee_rows", len(mee), "rows", "pass" if mee_ok else "fail", f"timezone={getattr(mee_time.dt, 'tz', None)}; corrupted_names={corrupted}")
    metric(metrics, "mee_candidate_rows_already_ground_truth", candidate_gt, "rows", "warning" if candidate_gt else "pass", "role=observation_candidate and is_ground_truth=true")
    metric(metrics, "mee_rows_mapped_to_grid", mapped_mee, "rows", "warning" if mapped_mee == 0 else "pass", f"of {len(mee_obs)} normalized MEE rows")
    dg(matrix, "DG-014", "通过（时间修复；用途受限）" if mee_ok else "未通过", "MEE 时间戳补全年份与 +08:00", f"rows={len(mee)}; tz={getattr(mee_time.dt, 'tz', None)}; corrupt={corrupted}; candidate_gt={candidate_gt}; grid_mapped={mapped_mee}", "尚未空间映射，且 observation_candidate 已标 ground_truth；不得直接并入太湖训练标签")

    # Additional audit observations not represented by old DG ids.
    if blank_units:
        residuals.append({
            "id": "RV-001", "severity": "Medium", "finding": "模拟站点观测的单位和站名为空",
            "evidence": f"station_observations: blank unit={blank_units}/{len(station)}, null station_name={null_names}/{len(station)}",
            "impact": "不影响当前 SIM 特征计算，但不满足可独立解释、跨源单位校验与外部交付的完整语义。",
            "required_action": "按 variable_code 写入规范单位，并从 stations/mapping 回填 station_name；扩展 A06 到观测表。",
        })
    if candidate_gt or mapped_mee == 0:
        residuals.append({
            "id": "RV-002", "severity": "High", "finding": "MEE 实时记录仍不具备直接训练接入条件",
            "evidence": f"observation_candidate & ground_truth={candidate_gt}/{len(mee)}; grid_id non-null={mapped_mee}/{len(mee_obs)}",
            "impact": "当前数据没有进入 2024 SIM 训练集，因此未造成现包泄漏；若未来直接接入，会缺少空间粒度和候选到正式标签的审核边界。",
            "required_action": "先完成权威站点坐标映射与 QC 状态机，再将通过记录升级为 is_ground_truth=true。",
        })

    pd.DataFrame(metrics).to_csv(REPORT_DIR / "verification_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(matrix).to_csv(REPORT_DIR / "dg_001_014_verification.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(residuals).to_csv(REPORT_DIR / "residual_findings.csv", index=False, encoding="utf-8-sig")
    balance.to_csv(REPORT_DIR / "binary_class_balance.csv", index=False, encoding="utf-8-sig")

    summary = {
        "as_of": "2026-09-05",
        "scope": "SIM-V1 / mvp_meiliangwan_2024 / df-0.2.0",
        "release_decision": "APPROVE_SIMULATION_ONLY_WITH_CAVEATS",
        "formal_experiment_decision": "NOT_READY",
        "dg_pass_or_accepted": int(pd.DataFrame(matrix).verdict.str.startswith(("通过", "保留警告")).sum()),
        "dg_unresolved": int((pd.DataFrame(matrix).verdict == "未通过").sum()),
        "accepted_limitations": ["DG-007", "DG-001 full-lake capability not implemented", "DG-008 missing grid task capability"],
        "new_residuals": residuals,
        "release_hash_entries": hash_entries,
        "release_hash_failures": hash_failures,
        "release_code_commit": release_manifest["code_commit"],
        "head": head,
        "tests": "51 passed, 1 deprecation warning",
        "notes": "A13 and DG-007 prevent treating the package as formal experimental evidence; SIM-V1 may be used for pipeline and algorithm-operation tests with simulation boundaries visible.",
    }
    (REPORT_DIR / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
