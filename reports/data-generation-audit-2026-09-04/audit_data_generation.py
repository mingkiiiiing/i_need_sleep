"""Independent read-only audit of the Data Factory MVP outputs.

The script reads existing project artifacts and writes only audit evidence into
this report directory. It does not rerun or modify the generator.
"""

from __future__ import annotations

import hashlib
import json
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_naive(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)


def add_metric(rows: list[dict], metric: str, value, unit: str, interpretation: str) -> None:
    if isinstance(value, (np.integer,)):
        value = int(value)
    elif isinstance(value, (np.floating,)):
        value = float(value)
    rows.append({"metric": metric, "value": value, "unit": unit, "interpretation": interpretation})


def add_issue(rows: list[dict], issue_id: str, severity: str, finding: str, evidence: str, impact: str, remediation: str) -> None:
    rows.append(
        {
            "issue_id": issue_id,
            "severity": severity,
            "finding": finding,
            "evidence": evidence,
            "impact": impact,
            "remediation": remediation,
        }
    )


def run_audit() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    grid = pd.read_csv(RUN_ROOT / "grid" / "grid_metadata.csv")
    bloom_grid = pd.read_parquet(SIM_ROOT / "bloom_grid_daily.parquet")
    bloom_lake = pd.read_parquet(SIM_ROOT / "bloom_lake_daily.parquet")
    hydro = pd.read_parquet(SIM_ROOT / "latent" / "hydrology_daily_TAIHU_ML.parquet")
    wq = pd.read_parquet(SIM_ROOT / "latent" / "water_quality_grid_daily_TAIHU_ML.parquet")
    labels = pd.read_parquet(RUN_ROOT / "labels" / "task_labels.parquet")
    samples = pd.read_parquet(RUN_ROOT / "assembly" / "SIM_V1" / "model_training_samples.parquet")
    satellite = pd.read_parquet(RUN_ROOT / "observations" / "satellite_observations.parquet")
    station = pd.read_parquet(RUN_ROOT / "observations" / "station_observations.parquet")
    history_wq = pd.read_parquet(RUN_ROOT / "history" / "water_quality.parquet")
    history_met = pd.read_parquet(RUN_ROOT / "history" / "meteorology_hydrology.parquet")
    params = pd.read_parquet(RUN_ROOT / "fit" / "parameter_sets.parquet")
    split_manifest = pd.read_csv(RUN_ROOT / "splits" / "split_manifest.csv", parse_dates=["date"])
    sim_manifest = json.loads((SIM_ROOT / "sim_manifest.json").read_text(encoding="utf-8"))
    labels_manifest = json.loads((RUN_ROOT / "labels" / "labels_manifest.json").read_text(encoding="utf-8"))
    release_manifest = json.loads((RELEASE_ROOT / "release_manifest.json").read_text(encoding="utf-8"))

    metrics: list[dict] = []
    issues: list[dict] = []

    sim_cells = bloom_grid["grid_id"].nunique()
    all_cells = grid["grid_id"].nunique()
    sim_area = float(grid.loc[grid["grid_id"].isin(bloom_grid["grid_id"].unique()), "effective_water_area_m2"].sum() / 1e6)
    full_area = float(grid["effective_water_area_m2"].sum() / 1e6)
    add_metric(metrics, "simulation_days", pd.to_datetime(bloom_grid["date"]).nunique(), "days", "MVP only")
    add_metric(metrics, "simulation_grid_cells", sim_cells, "cells", "Meiliang Bay cells")
    add_metric(metrics, "frozen_grid_cells", all_cells, "cells", "Full frozen Taihu grid")
    add_metric(metrics, "simulation_area_share", sim_area / full_area, "ratio", "MVP area divided by frozen full-lake area")
    add_metric(metrics, "training_samples", len(samples), "rows", "All SIM-V1 synthetic samples")
    add_metric(metrics, "task_label_rows", len(labels), "rows", "Includes simulation truth and satellite-derived rows")

    # Whole-lake alias check.
    zone = bloom_lake[bloom_lake["spatial_id"] == "TAIHU_ML"].sort_values("date").reset_index(drop=True)
    whole = bloom_lake[bloom_lake["spatial_id"] == "TAIHU_WHOLE"].sort_values("date").reset_index(drop=True)
    comparable_cols = [c for c in ("bloom_area_km2", "bloom_fraction_mean") if c in bloom_lake.columns]
    alias_equal = bool(len(zone) == len(whole) and all(np.allclose(zone[c], whole[c], equal_nan=True) for c in comparable_cols))
    add_metric(metrics, "whole_lake_equals_meiliang_bay", int(alias_equal), "boolean", "1 means whole-lake rows duplicate the only simulated zone")
    if alias_equal:
        add_issue(
            issues,
            "DG-001",
            "Critical",
            "TAIHU_WHOLE is not a full-lake simulation in the MVP output.",
            f"All {len(zone)} daily whole-lake rows equal TAIHU_ML; simulated area is {sim_area:.3f} km2 versus frozen full-lake {full_area:.3f} km2 ({sim_area/full_area:.1%}).",
            "Lake-level labels and metrics can be mistaken for full Taihu results.",
            "Do not emit TAIHU_WHOLE when full_lake=false; use an explicit partial_domain id, or simulate every frozen zone before whole-lake aggregation.",
        )

    # Fit cutoff leakage: code only filters weather; quantify records visible to unfiltered fit branches.
    history_wq_dates = local_naive(history_wq["observed_at"])
    wq_gt = history_wq["is_ground_truth"].fillna(False).astype(bool)
    wq_after = int((wq_gt & (history_wq_dates > CUTOFF)).sum())
    met_dates = local_naive(history_met["observed_at"])
    water_temp_mask = history_met["variable_code"].eq("lake_surface_temperature")
    hydro_mask = history_met["variable_code"].eq("water_level")
    temp_after = int((water_temp_mask & (met_dates > CUTOFF)).sum())
    hydro_after = int((hydro_mask & (met_dates > CUTOFF)).sum())
    add_metric(metrics, "ground_truth_wq_rows_after_fit_cutoff", wq_after, "rows", "Rows accessible to unfiltered nutrient/algae fit")
    add_metric(metrics, "lake_temperature_rows_after_fit_cutoff", temp_after, "rows", "Rows accessible to unfiltered water-temperature fit")
    add_metric(metrics, "water_level_rows_after_fit_cutoff", hydro_after, "rows", "Rows accessible to unfiltered hydrology fit")
    if wq_after + temp_after + hydro_after > 0:
        add_issue(
            issues,
            "DG-002",
            "Critical",
            "The calibration cutoff is not enforced in several fit branches.",
            f"After {CUTOFF.date()}, history contains {wq_after} ground-truth water-quality rows, {temp_after} lake-temperature rows and {hydro_after} water-level rows. fitter.py filters weather only; nutrient/algae, water-temperature, hydrology and observation fits receive unfiltered tables.",
            "Validation/test/future observations can influence generator parameters while manifests claim train-only fitting.",
            "Filter every fit input by observed/available time before calling each fitter; save per-family max input date and test it against the split lock.",
        )

    # Synthetic remote-sensing provenance laundering.
    sat_is_synthetic = int(satellite["is_synthetic"].fillna(False).sum())
    sat_labels = labels[labels["label_source_type"] == "satellite_observation"]
    sat_labels_non_syn = int((~sat_labels["is_synthetic"].fillna(False)).sum())
    sat_labels_observed = int(sat_labels["label_status"].astype(str).str.startswith("observed_").sum())
    add_metric(metrics, "synthetic_satellite_observation_rows", sat_is_synthetic, "rows", "Generated from latent simulation state")
    add_metric(metrics, "satellite_labels_marked_non_synthetic", sat_labels_non_syn, "rows", "Contradicts their upstream observation origin")
    add_metric(metrics, "satellite_labels_with_observed_status", sat_labels_observed, "rows", "Observed label vocabulary applied to simulated retrieval")
    if sat_is_synthetic and sat_labels_non_syn:
        add_issue(
            issues,
            "DG-003",
            "Critical",
            "Synthetic satellite retrievals are relabeled as non-synthetic observed labels.",
            f"The observation table has {sat_is_synthetic:,} is_synthetic=true rows. Label construction creates {len(sat_labels)} satellite labels; {sat_labels_non_syn} are is_synthetic=false and {sat_labels_observed} use observed_* status. The manifest calls them satellite_real_labels={labels_manifest.get('satellite_real_labels')}.",
            "This breaks the irreversible identity boundary and makes the current A18/V10 PASS a false assurance.",
            "Propagate is_synthetic/value_type/source lineage from every contributing observation. Use simulation_observed_* or proxy_* status; never hard-code is_syn=false.",
        )

    # Latent-state features rather than observation-visible features.
    parsed = samples["features_json"].head(5000).map(json.loads)
    observed_required = ["air_temperature", "water_temperature", "chlorophyll_a", "bloom_fraction"]
    all_complete = float(np.mean([all(key in row for key in observed_required) for row in parsed]))
    add_metric(metrics, "sampled_rows_with_complete_latent_core", all_complete, "ratio", "Computed from 5,000 samples")
    add_metric(metrics, "station_observation_rows", len(station), "rows", "Actual station observation layer used for MVP")
    if len(station) == 0 and all_complete == 1.0:
        add_issue(
            issues,
            "DG-004",
            "High",
            "Training features come from the omniscient latent layer, not the observation layer.",
            f"Station observation output has {len(station)} rows, but sampled training rows have 100% complete water temperature, Chl-a and bloom-fraction keys because horizons.py reads latent simulation tables directly.",
            "Model performance will assume perfect daily variables that are unavailable in real operation; feature completeness is overstated.",
            "Assemble operational features from timestamped observation/forecast tables, apply missingness and availability masks, and reserve latent truth only for targets and simulator diagnostics.",
        )

    # Physical clipping and collapse.
    bound_map = {
        "total_phosphorus": (0.005, 2.0),
        "total_nitrogen": (0.1, 12.0),
        "ammonia_nitrogen": (0.005, 5.0),
        "dissolved_oxygen": (0.0, 20.0),
        "water_temperature": (0.0, 40.0),
    }
    clip_rows = []
    for variable, (low, high) in bound_map.items():
        values = wq.loc[wq["variable_code"] == variable, "value"].astype(float)
        at_low = int(np.isclose(values, low).sum())
        at_high = int(np.isclose(values, high).sum())
        clip_rows.append({"variable": variable, "rows": len(values), "at_lower_bound": at_low, "at_upper_bound": at_high, "bound_share": (at_low + at_high) / max(len(values), 1)})
    clipping = pd.DataFrame(clip_rows)
    level_values = hydro["water_level_m"].astype(float)
    level_bound_share = float((np.isclose(level_values, 2.0) | np.isclose(level_values, 5.0)).mean())
    add_metric(metrics, "water_level_at_bounds", level_bound_share, "ratio", "Hydrology values exactly at 2 m or 5 m")
    max_clip = clipping.sort_values("bound_share", ascending=False).iloc[0]
    if level_bound_share > 0.1 or float(max_clip["bound_share"]) > 0.05:
        add_issue(
            issues,
            "DG-005",
            "Critical",
            "Physical clipping hides model instability instead of validating realism.",
            f"Water level is at a hard bound for {level_bound_share:.1%} of days. Highest water-quality bound share is {max_clip['variable']} at {float(max_clip['bound_share']):.1%}. The current A07 checks only post-clip out-of-range values.",
            "A generator can pass physical bounds while producing collapsed or saturated state trajectories.",
            "Fail or warn on pre-clip and bound-hit rates; repair fitted units/parameters, especially water level, before accepting distribution realism.",
        )

    chla = wq.loc[wq["variable_code"] == "chlorophyll_a", ["date", "value"]].copy()
    chla["date"] = pd.to_datetime(chla["date"])
    chla_month = chla.assign(month=chla["date"].dt.month).groupby("month")["value"].mean()
    chla_mean = float(chla["value"].mean())
    chla_cv = float(chla["value"].std(ddof=0) / chla_mean)
    winter = float(chla_month.loc[[1, 2, 12]].mean())
    summer = float(chla_month.loc[[6, 7, 8]].mean())
    seasonal_lift = summer / winter - 1.0
    add_metric(metrics, "chlorophyll_a_mean", chla_mean, "ug/L", "Latent simulated grid-days")
    add_metric(metrics, "chlorophyll_a_cv", chla_cv, "ratio", "Overall coefficient of variation")
    add_metric(metrics, "chlorophyll_a_summer_vs_winter", seasonal_lift, "ratio", "Jun-Aug mean divided by Dec-Feb mean minus one")
    if abs(seasonal_lift) < 0.1:
        add_issue(
            issues,
            "DG-006",
            "High",
            "Chlorophyll-a seasonality is too weak for the claimed bloom dynamics.",
            f"Mean Chl-a is {chla_mean:.3f} ug/L, CV={chla_cv:.3f}, and Jun-Aug is only {seasonal_lift:.1%} above Dec-Feb.",
            "The simulator produces many positive bloom labels without a correspondingly informative Chl-a seasonal signal, reducing ecological credibility.",
            "Recalibrate pigment/non-cyanobacteria terms and validate against held-out monthly distributions, event duration and joint Chl-a/biomass/bloom relationships.",
        )

    # Class balance at unique target-date level, not repeated horizon rows.
    binary = samples[samples["target_metric"].isin(["T1", "T7"])].copy()
    date_balance = (
        binary.drop_duplicates(["target_metric", "spatial_type", "spatial_id", "split", "target_date", "label_value"])
        .groupby(["target_metric", "spatial_type", "split"])["label_value"]
        .agg(samples="size", positives="sum")
        .reset_index()
    )
    date_balance["positive_rate"] = date_balance["positives"] / date_balance["samples"]
    degenerate = date_balance[(date_balance["positive_rate"] == 0) | (date_balance["positive_rate"] == 1)]
    add_metric(metrics, "degenerate_binary_task_split_groups", len(degenerate), "groups", "Unique-date groups with only one class")
    if len(degenerate):
        examples = "; ".join(f"{r.target_metric}/{r.spatial_type}/{r.split}={r.positive_rate:.0%}" for r in degenerate.head(8).itertuples())
        add_issue(
            issues,
            "DG-007",
            "High",
            "Chronological splits contain single-class binary evaluation groups.",
            f"{len(degenerate)} task/spatial/split groups are 0% or 100% positive at unique-date grain; examples: {examples}.",
            "Classification metrics can be undefined or misleading; a one-year seasonal split confounds season with split.",
            "Use at least five years, keep chronological gaps, and ensure each validation/test period contains multiple bloom and non-bloom episodes without synthetic resampling.",
        )

    # Task/spatial coverage.
    task_levels = labels.groupby(["task_id", "spatial_type"]).size().reset_index(name="rows")
    required_grid_tasks = {"T1", "T2", "T3", "T4", "T5", "T6", "T7"}
    grid_tasks = set(task_levels.loc[task_levels["spatial_type"] == "grid", "task_id"])
    missing_grid_tasks = sorted(required_grid_tasks - grid_tasks)
    if missing_grid_tasks:
        add_issue(
            issues,
            "DG-008",
            "High",
            "The MVP does not cover all seven tasks at 1 km grid grain.",
            f"Grid labels exist for {sorted(grid_tasks)}; missing {missing_grid_tasks}. T3/T4/T6/T7 are only emitted at zone/lake grain.",
            "The release does not yet satisfy the full formal dataset contract or spatial algorithm coverage.",
            "Either generate all required grid targets or explicitly revise the contract and algorithm task matrix with approved grain per task.",
        )

    # Release reproducibility/package completeness.
    required_release = [
        "lineage/source_registry.csv",
        "generation/parameter_sets.parquet",
        "lineage/transformation_log.jsonl",
        "quality/leakage_audit.csv",
        "data/target_observation_daily.parquet",
        "data/dynamic_features_grid_daily.parquet",
    ]
    missing_release = [rel for rel in required_release if not (RELEASE_ROOT / rel).exists()]
    add_metric(metrics, "release_files", release_manifest.get("files", 0), "files", "Files declared by release manifest")
    add_metric(metrics, "formal_contract_files_missing", len(missing_release), "files", ", ".join(missing_release))
    if missing_release:
        add_issue(
            issues,
            "DG-009",
            "High",
            "The release manifest's missing=[] does not test the full formal contract.",
            "Missing audited contract artifacts: " + ", ".join(missing_release) + ".",
            "The published SIM-V1 package cannot independently reconstruct fitted parameters or prove row-level transformations and leakage checks.",
            "Expand the release contract and fail release when any required data, calibration, lineage or quality artifact is absent.",
        )

    lineage = pd.read_parquet(RELEASE_ROOT / "lineage" / "row_lineage.parquet")
    add_metric(metrics, "row_lineage_rows", len(lineage), "rows", "Current lineage table granularity")
    if len(lineage) < 100 and len(samples) > 100_000:
        add_issue(
            issues,
            "DG-010",
            "Medium",
            "row_lineage.parquet is file-level rather than row-level lineage.",
            f"Lineage has {len(lineage)} rows for {len(samples):,} training samples.",
            "Individual samples cannot be traced to their exact features, labels and parent observations from the release alone.",
            "Rename it file_lineage or add sample_id/label_id keyed lineage with bounded parent references and transformation versions.",
        )

    # Existing internal checks and tests are useful but incomplete.
    acceptance = pd.read_csv(RELEASE_ROOT / "quality" / "acceptance_21.csv")
    warning_count = int((acceptance["status"] == "warning").sum())
    add_metric(metrics, "internal_acceptance_warnings", warning_count, "rules", "Warnings despite overall PASS")
    add_issue(
        issues,
        "DG-011",
        "High",
        "The overall quality verdict is PASS even with a known class-balance failure and untested claims.",
        f"A13 is warning while quality_summary says PASS. A15 checks issue_date < target_date but does not prove each feature's available_time. A07 checks only values after clipping.",
        "Users can interpret a packaging pass as scientific and operational readiness.",
        "Separate schema/package PASS from simulation-fidelity PASS and training-readiness PASS; make critical warnings block release.",
    )

    # Hash verification.
    hash_failures = []
    hash_file = RELEASE_ROOT / "hashes.sha256"
    for raw in hash_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        expected, rel = raw.split(None, 1)
        rel = rel.strip().lstrip("*")
        path = RELEASE_ROOT / rel
        actual = sha256_file(path) if path.exists() else None
        if actual != expected:
            hash_failures.append(rel)
    add_metric(metrics, "release_hash_failures", len(hash_failures), "files", "Independent SHA-256 verification")

    # Code version state.
    add_issue(
        issues,
        "DG-012",
        "High",
        "The generator implementation and tests are currently untracked by Git.",
        "git status reports data-cleaning/data_factory, its config and its tests as untracked; manifests carry generator=df-0.1.0 but no code_commit.",
        "The release cannot identify the exact source revision that generated the files.",
        "Commit or otherwise freeze the generator source and record code_commit plus source-tree hash in every manifest before formal release.",
    )

    # Station mapping weakness.
    grid_manifest = json.loads((RUN_ROOT / "grid" / "grid_manifest.json").read_text(encoding="utf-8"))
    outside = int(grid_manifest.get("outside_boundary_stations", 0))
    total_stations = int(grid_manifest.get("n_stations", 0))
    add_metric(metrics, "stations_outside_boundary", outside, "stations", f"of {total_stations} station records")
    if total_stations and outside / total_stations > 0.5:
        add_issue(
            issues,
            "DG-013",
            "Medium",
            "Most imported station coordinates fail the Taihu boundary check.",
            f"{outside}/{total_stations} stations ({outside/total_stations:.1%}) are outside the frozen boundary; only four mapped stations are reported for the MVP and station_observations has zero rows.",
            "Station-driven calibration and observation realism are not demonstrated.",
            "Resolve station identities/coordinates against an authoritative registry and require mapped sampling coverage before claiming station observation support.",
        )

    # Realtime MEE quality: this source is outside SIM labels but part of the data factory.
    mee_path = RUN_ROOT / "realtime" / "mee_observations.parquet"
    if mee_path.exists():
        mee = pd.read_parquet(mee_path)
        malformed_time = int((~mee["observed_time"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}")).sum())
        corrupted_names = int(mee["station_name"].astype(str).str.contains("�|����", regex=True).sum())
        auto_pass_gt = int((mee["is_ground_truth"].fillna(False) & mee["quality_flag"].eq("pass")).sum())
        add_metric(metrics, "mee_rows_with_no_year_in_timestamp", malformed_time, "rows", "Timestamp does not begin with YYYY-MM-DD")
        add_metric(metrics, "mee_rows_with_corrupted_station_name", corrupted_names, "rows", "Replacement characters in station names")
        if malformed_time or corrupted_names:
            add_issue(
                issues,
                "DG-014",
                "High",
                "Realtime MEE rows are promoted to ground truth before timestamp and encoding validation.",
                f"{malformed_time}/{len(mee)} rows have timestamps without a year; {corrupted_names}/{len(mee)} rows have corrupted station names; {auto_pass_gt}/{len(mee)} rows are already quality_flag=pass and is_ground_truth=true.",
                "Records cannot be safely mapped, deduplicated across years, or used as formal observations despite appearing trusted.",
                "Decode with the verified response charset, construct a full timezone-aware timestamp using retrieval context, validate station ids/coordinates and ranges, and keep observation_candidate/is_ground_truth=false until QC passes.",
            )

    # Parameter support summary.
    parameter_support = (
        params.groupby(["family", "method"])
        .agg(parameters=("parameter_key", "size"), median_n=("n_samples", "median"), min_n=("n_samples", "min"), max_n=("n_samples", "max"))
        .reset_index()
    )

    summary = {
        "status": "NOT_READY_FOR_FORMAL_EXPERIMENT",
        "mvp_status": "STRUCTURALLY_RUNNABLE_WITH_CRITICAL_DATA_QUALITY_DEFECTS",
        "critical": int(sum(row["severity"] == "Critical" for row in issues)),
        "high": int(sum(row["severity"] == "High" for row in issues)),
        "medium": int(sum(row["severity"] == "Medium" for row in issues)),
        "tests_observed": "35 targeted tests passed; independent audit identifies gaps not covered by those tests",
        "scope": "mvp_meiliangwan_2024 / baseline / seed 20260904 / SIM-V1",
        "hash_failures": hash_failures,
        "missing_release_contract_files": missing_release,
    }
    return pd.DataFrame(metrics), pd.DataFrame(issues), pd.concat([clipping.assign(table="clipping"), date_balance.assign(table="date_balance"), task_levels.assign(table="task_levels")], ignore_index=True, sort=False), {"summary": summary, "parameter_support": parameter_support.to_dict(orient="records")}


def main() -> None:
    metrics, issues, details, extra = run_audit()
    metrics.to_csv(REPORT_DIR / "audit_metrics.csv", index=False, encoding="utf-8-sig")
    issues.to_csv(REPORT_DIR / "audit_findings.csv", index=False, encoding="utf-8-sig")
    details.to_csv(REPORT_DIR / "audit_details.csv", index=False, encoding="utf-8-sig")
    (REPORT_DIR / "audit_summary.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(extra["summary"], ensure_ascii=False, indent=2))
    print("\nFindings by severity")
    print(issues.groupby("severity").size().to_string())
    print("\nKey metrics")
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
