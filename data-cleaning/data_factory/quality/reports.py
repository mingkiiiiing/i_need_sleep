"""质量报告九件套 `validate` (设计 §11/§12 quality/).

acceptance_21.csv / veto_12.csv / label_coverage_by_task_split.csv /
positive_negative_balance.csv / feature_completeness.csv /
physical_bounds_summary.csv / distribution_checks.csv /
reproducibility_manifest.md / quality_summary.md + hashes.sha256
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .acceptance import PASS, run_acceptance
from .veto import run_vetoes

NINE_FILES = [
    "acceptance_21.csv",
    "veto_12.csv",
    "label_coverage_by_task_split.csv",
    "positive_negative_balance.csv",
    "feature_completeness.csv",
    "physical_bounds_summary.csv",
    "distribution_checks.csv",
    "reproducibility_manifest.md",
    "quality_summary.md",
]

# DG-011 三段式判定：A01–A25 全部分段覆盖（5+5+15）
SEGMENT_RULES: dict[str, tuple[str, ...]] = {
    "packaging": ("A01", "A02", "A03", "A04", "A09"),
    "simulation_fidelity": ("A07", "A08", "A20", "A21", "A23"),
    "training_readiness": ("A05", "A06", "A10", "A11", "A12", "A13", "A14", "A15", "A16", "A17", "A18", "A19", "A22", "A24", "A25"),
}


def segment_verdicts(acceptance_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    verdicts: dict[str, dict[str, Any]] = {}
    for segment, rule_ids in SEGMENT_RULES.items():
        seg = acceptance_df[acceptance_df["rule_id"].isin(rule_ids)]
        fails = seg.loc[seg["status"] == "fail", "rule_id"].tolist()
        warns = seg.loc[seg["status"] == "warning", "rule_id"].tolist()
        verdicts[segment] = {
            "verdict": "fail" if fails else ("warning" if warns else "pass"),
            "fail_rules": fails,
            "warning_rules": warns,
        }
    return verdicts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_quality(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
    mechanism: dict[str, Any],
) -> dict[str, Any]:
    acceptance = run_acceptance(config, base_dir=base_dir, sim_dir=sim_dir, mechanism=mechanism)
    vetoes = run_vetoes(config, base_dir=base_dir, sim_dir=sim_dir)

    acceptance_df = pd.DataFrame(acceptance)
    veto_df = pd.DataFrame(vetoes)
    samples_path = base_dir / "assembly" / "SIM_V1" / "model_training_samples.parquet"
    samples = pd.read_parquet(samples_path) if samples_path.exists() else pd.DataFrame()
    labels = pd.read_parquet(base_dir / "labels" / "task_labels.parquet")

    out_dir = base_dir / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    acceptance_df.to_csv(out_dir / "acceptance_21.csv", index=False, encoding="utf-8")
    veto_df.to_csv(out_dir / "veto_12.csv", index=False, encoding="utf-8")

    # 覆盖与平衡（仿真样本量口径，来源：训练样本 split；标签真值表本身无 split）
    if samples.empty:
        coverage = pd.DataFrame(columns=["target_metric", "spatial_type", "split", "samples", "positive", "negative", "unknown", "unit"])
        balance = coverage.copy()
        feature_rows = pd.DataFrame(columns=["feature", "present_ratio"])
    else:
        grouped = samples.groupby(["target_metric", "spatial_type", "split"])
        coverage = grouped.agg(
            samples=("sample_id", "size"),
            positive=("label_value", lambda s: int((s == 1).sum())),
            negative=("label_value", lambda s: int((s == 0).sum())),
        ).reset_index()
        coverage["unknown"] = 0
        coverage["unit"] = "simulation_samples"
        balance = coverage[coverage["target_metric"].isin(["T1", "T7"])].copy()
        import numpy as np

        feature_parsed = samples["features_json"].head(5000).map(json.loads)
        all_keys = sorted({k for d in feature_parsed for k in d})
        feature_rows = pd.DataFrame(
            [{"feature": key, "present_ratio": round(float(np.mean([key in d for d in feature_parsed])), 4)} for key in all_keys]
        )
    coverage.to_csv(out_dir / "label_coverage_by_task_split.csv", index=False, encoding="utf-8")
    balance.to_csv(out_dir / "positive_negative_balance.csv", index=False, encoding="utf-8")
    feature_rows.to_csv(out_dir / "feature_completeness.csv", index=False, encoding="utf-8")

    # 物理界限与分布核对（对潜在层逐变量汇总）
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))
    wq = pd.read_parquet(sim_dir / "latent" / f"water_quality_grid_daily_{sim_manifest['zones'][0]}.parquet")
    wq["date"] = pd.to_datetime(wq["date"])
    bounds = mechanism.get("physical_bounds", {})
    bounds_rows = []
    for variable, rng in bounds.items():
        values = wq.loc[wq["variable_code"] == variable, "value"] if variable in set(wq["variable_code"]) else None
        if values is None or values.empty:
            continue
        out_of = int(((values < rng[0]) | (values > rng[1])).sum())
        bounds_rows.append(
            {
                "variable": variable,
                "min_allowed": rng[0],
                "max_allowed": rng[1],
                "sim_min": round(float(values.min()), 4),
                "sim_max": round(float(values.max()), 4),
                "out_of_bounds": out_of,
            }
        )
    bounds_df = pd.DataFrame(bounds_rows)
    bounds_df.to_csv(out_dir / "physical_bounds_summary.csv", index=False, encoding="utf-8")

    monthly = (
        wq[wq["variable_code"] == "chlorophyll_a"]
        .assign(month=lambda d: d["date"].dt.month)
        .groupby("month")["value"]
        .agg(["mean", "std", "size"])
        .round(4)
        .reset_index()
        .rename(columns={"mean": "chla_monthly_mean", "std": "chla_monthly_std", "size": "n_grid_days"})
    )
    monthly.to_csv(out_dir / "distribution_checks.csv", index=False, encoding="utf-8")

    fit_manifest = json.loads((base_dir / "fit" / "fit_manifest.json").read_text(encoding="utf-8"))
    repro_lines = [
        "# 复现要素 (仿真样本量口径)",
        "",
        f"- dataset_id: {sim_manifest.get('dataset_id')}",
        f"- scenario_id: {sim_manifest.get('scenario_id')}",
        f"- random_seed: {sim_manifest.get('random_seed')}",
        f"- parameter_set_id: {sim_manifest.get('parameter_set_id')} (fit cutoff {fit_manifest.get('train_cutoff_date')})",
        f"- grid_version: {sim_manifest.get('grid_version')}",
        f"- generation_batch_id: {sim_manifest.get('generation_batch_id')}",
        f"- generator_version: {sim_manifest.get('generator_version')}",
        f"- rng: {sim_manifest.get('rng', {}).get('root')}; streams: {', '.join(sim_manifest.get('rng', {}).get('streams', []))}",
        "",
        "复跑命令：见 release/README.md Quick Start；同 seed 重跑 bloom_grid_daily 行哈希逐行一致。",
    ]
    (out_dir / "reproducibility_manifest.md").write_text("\n".join(repro_lines) + "\n", encoding="utf-8")

    n_fail_a = int((acceptance_df["status"] == "fail").sum())
    n_veto_fail = int((veto_df["status"] == "fail").sum())
    verdicts = segment_verdicts(acceptance_df)
    overall = "PASS" if n_fail_a == 0 and n_veto_fail == 0 else "FAIL"
    verdict_lines = [
        "## 三段式判定 (DG-011)",
        "",
        "| 段 | 判定 | fail 规则 | warning 规则 |",
        "|---|---|---|---|",
    ]
    for segment, info in verdicts.items():
        verdict_lines.append(
            f"| {segment} | **{info['verdict'].upper()}** | {', '.join(info['fail_rules']) or '—'} | {', '.join(info['warning_rules']) or '—'} |"
        )
    verdict_lines += [
        "",
        "- packaging：schema/文件/哈希；simulation_fidelity：物理钳位率(A07)/季节性(A21)/分布(A20)/部分域标注(A23)。",
        "- training_readiness：可观测性(A14)/泄漏审计(A15/A22)/平衡明细(A13，单类组合列为 warning 并在 acceptance 表给出明细)。",
        "- 任一段 fail → release 拒绝 (build_release 会复检 acceptance_21/veto_12)。",
    ]
    summary_lines = [
        "# SIM-V1 质量门禁摘要",
        "",
        f"- 总体结论: **{overall}** (acceptance fail={n_fail_a}, veto fail={n_veto_fail})",
        f"- 数据集: {sim_manifest.get('dataset_id')} / 情景 {sim_manifest.get('scenario_id')} / seed {sim_manifest.get('random_seed')}",
        f"- 标签行: {len(labels)} (仿真样本量口径)",
        f"- 训练样本: {len(samples)} (仿真样本量口径)",
        "",
        "## 验收 A01–A25",
        "",
        acceptance_df.to_markdown(index=False),
        "",
        "## 一票否决 V01–V12",
        "",
        veto_df.to_markdown(index=False),
        "",
        *verdict_lines,
        "",
        "数量阈值为 MVP profile 缩放值；SIM-V1 的统计名称为『仿真样本量』，不代表真实样本量 (设计 §11)。",
    ]
    (out_dir / "quality_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    hash_lines = [f"{_sha256(out_dir / name)}  {name}" for name in NINE_FILES if (out_dir / name).exists()]
    (out_dir / "hashes.sha256").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

    return {
        "status": "completed" if overall == "PASS" else "failed",
        "command": "validate",
        "overall": overall,
        "verdicts": verdicts,
        "release_blocked": n_fail_a > 0 or n_veto_fail > 0,
        "acceptance_fail": n_fail_a,
        "veto_fail": n_veto_fail,
        "acceptance_warnings": int((acceptance_df["status"] == "warning").sum()),
        "rows_written": int(len(acceptance) + len(vetoes)),
        "quality_dir": str(out_dir),
        "nine_files": [name for name in NINE_FILES if (out_dir / name).exists()],
        "outputs": {"quality_summary": str(out_dir / "quality_summary.md"), "hashes": str(out_dir / "hashes.sha256")},
        "next_action": "python -m data_factory release" if overall == "PASS" else "修复 fail 项后重跑 validate",
    }
