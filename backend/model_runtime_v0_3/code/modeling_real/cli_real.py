"""V0.3 离线管线 CLI：build-tables / train-all（断点续跑）/ gate / manifest / all。

用法（工程根目录）：
  C:/Anaconda/python.exe backend/model_runtime_v0_3/code/modeling_real/cli_real.py all
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from modeling_real import gate as gate_mod  # noqa: E402
from modeling_real.contracts_real import (  # noqa: E402
    BLOOM_THRESHOLD_UG_L,
    CLAIM_BOUNDARY_V3,
    DATA_VERSION_V3,
    FEATURE_COLUMNS_V2,
    HORIZONS_V3,
    HORIZON_GRANULARITY_TIER_V3,
    HORIZON_MONTH_MAP_V3,
    PACKAGE_GENERATION,
    RISK_BANDS_UG_L,
    SCENARIO_HORIZONS_V3,
    SERVING_FEATURE_COLUMNS_V2,
    TASK_SPECS_REAL,
    feature_contract_sha256,
    package_root,
)
from modeling_real.data_real import StationMonthSource, frame_digest  # noqa: E402
from modeling_real.target_builder import (  # noqa: E402
    build_availability_matrix,
    build_supervised_base,
    contract_manifest_fragment,
    split_manifest_fragment,
)
from modeling_real.training_real import train_run_real  # noqa: E402

SEED = 20260907
LEGACY_PACKAGE = "model_runtime_v0_2"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cmd_build_tables() -> dict:
    base, labels = build_supervised_base()
    entries, tables = build_availability_matrix(base, labels)
    out_dir = package_root()
    evaluation = out_dir / "evaluation"
    evaluation.mkdir(parents=True, exist_ok=True)
    base_out = out_dir / "supervised"
    base_out.mkdir(parents=True, exist_ok=True)
    base.drop(columns=[c for c in base.columns if str(c).startswith("label_")]).to_parquet(
        base_out / "features_base.parquet", index=False
    )
    # 叶绿素代理标签公示参数（公式/锚点/σ/seed）随构建落盘，manifest 引用
    proxy_params = base.attrs.get("chla_proxy_params")
    if proxy_params:
        (evaluation / "chla_proxy_params.json").write_text(
            json.dumps(proxy_params, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    labels.to_parquet(base_out / "labels_wide.parquet", index=False)
    availability = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_train_rows": 10,
        "min_validation_rows": 5,
        "entries": entries,
    }
    (evaluation / "availability_matrix.json").write_text(
        json.dumps(availability, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    trainable = [e for e in entries if e["trainable"]]
    print(f"[build-tables] supervised rows={len(base)} trainable runs={len(trainable)}")
    for entry in trainable:
        print(
            f"  - {entry['task_id']}-{entry['variant']}-{entry['month_offset']}m "
            f"train={entry['train_rows']} val={entry['validation_rows']} test={entry['test_rows']}"
        )
    return {"availability": availability, "base": base, "labels": labels}


def cmd_train_all(base: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    import os

    # serving 契约：只用「训练面板真实变化 ∩ 推理时逐站可得」的特征子集训练，
    # 保证选出的模型在服务时对站点输入有响应（冻结契约仍为默认，可对照重训）。
    serving = os.environ.get("TAIHU_FEATURE_CONTRACT", "").strip().lower() == "serving"
    feature_universe = SERVING_FEATURE_COLUMNS_V2 if serving else FEATURE_COLUMNS_V2
    print(f"[train-all] feature contract: {'serving-7col' if serving else 'frozen-78col'}")
    out_dir = package_root()
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    entries, tables = build_availability_matrix(base, labels)
    data_manifest = {"data_version": DATA_VERSION_V3, "data_sha256": _sha256_data()}
    results = []
    for entry in entries:
        if not entry["trainable"]:
            continue
        key = f"{entry['task_id']}-{entry['variant']}-{entry['month_offset']}m"
        horizon = entry["horizon_days"]
        spec = next(
            s for s in TASK_SPECS_REAL
            if s.task_id == entry["task_id"] and s.variant == entry["variant"]
        )
        table = tables[key]
        # 任务级特征列：监督表已剔除目标同源特征（防同月泄漏），按交集对齐
        task_feature_columns = tuple(c for c in feature_universe if c in table.columns)
        source = StationMonthSource(table, task_feature_columns)
        result = train_run_real(
            spec, horizon, source, runs_dir / f"{spec.task_id}-{spec.variant}-{horizon}d-{entry['month_offset']}m",
            seed=SEED, data_manifest=data_manifest,
        )
        print(f"[train] {result['run_id']}: {result['status']} selected={result.get('selected_family')}")
        results.append(result)
    return results


def _sha256_data() -> str:
    tables = Path(__file__).resolve().parents[4] / (
        "data-cleaning/storage/final_cleaned/TAIHU_CLEAN_FINAL_V1_20260831/tables/model_dataset.parquet"
    )
    return _sha256_file(tables) if tables.is_file() else "missing"


def cmd_gate() -> dict:
    runs_dir = package_root() / "runs"
    table = gate_mod.build_gate_table(runs_dir)
    out = package_root() / "evaluation" / "gate_table.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = table["summary"]
    print(
        f"[gate] rows={summary['comparison_rows']} evaluable={summary['evaluable_comparisons']} "
        f"pass={summary['pass']} fail={summary['fail']} na={summary['not_applicable']} → {summary['status']}"
    )
    return table


def cmd_manifest() -> dict:
    import os

    from modeling_real import data_real

    serving = os.environ.get("TAIHU_FEATURE_CONTRACT", "").strip().lower() == "serving"
    out_dir = package_root()
    models_dir = out_dir / "models"
    model_entries = []
    for path in sorted(models_dir.glob("*.joblib")):
        bundle = data_real.load_bundle(path)
        model_entries.append({
            "run_id": bundle.run_id,
            "file": str(path.relative_to(out_dir)).replace("\\", "/"),
            "sha256": _sha256_file(path),
            "selected_family": bundle.selected_family,
            "horizon_days": bundle.horizon_days,
            "month_offset": bundle.month_offset,
            "granularity_tier": bundle.granularity_tier,
            "test_metrics": bundle.test_metrics,
            "uncertainty": bundle.uncertainty_meta,
        })
    # CV 协议 run 冻结测试段无标签（test_metrics 为空）：补挂训练期内时间分块
    # 验证段指标（selection_manifest.validation_metrics_by_family[selected_family]），
    # 字段来源如实标注 validation_metric_source，供验收矩阵展示。
    for entry in model_entries:
        if entry.get("test_metrics"):
            continue
        run_id = entry.get("run_id") or ""
        parts = run_id.rsplit("-s", 1)[0].split("-")
        if len(parts) < 3:
            continue
        task_id, variant, offset = parts[0], parts[1], parts[2]
        sel_path = out_dir / "runs" / f"{task_id}-{variant}-{entry.get('horizon_days')}d-{offset}-cv" / "selection_manifest.json"
        if not sel_path.is_file():
            continue
        try:
            sel = json.loads(sel_path.read_text(encoding="utf-8"))
            family = sel.get("selected_family")
            vm = (sel.get("validation_metrics_by_family") or {}).get(family)
            if vm:
                entry["validation_metrics"] = vm
                entry["validation_metric_source"] = "train_internal_time_block_cv_v1"
        except Exception:  # noqa: BLE001 — 证据缺失时保持为空，不伪造
            continue

    availability_path = out_dir / "evaluation" / "availability_matrix.json"
    availability = (
        json.loads(availability_path.read_text(encoding="utf-8")) if availability_path.is_file() else {"entries": []}
    )
    features = pd.read_parquet(out_dir / "supervised" / "features_base.parquet")
    from modeling_real.target_builder import load_modis_bloom_months

    modis_audit = load_modis_bloom_months()
    modis_audit["positive_months"] = sorted(modis_audit["positive_months"])
    manifest = {
        "version": "0.3.1" if serving else "0.3",
        "feature_contract_mode": "serving" if serving else "frozen",
        "package_generation": PACKAGE_GENERATION,
        "claim_boundary": CLAIM_BOUNDARY_V3,
        "data_version": DATA_VERSION_V3,
        "data_sha256": _sha256_data(),
        "feature_contract": contract_manifest_fragment(),
        "horizon_month_map": {str(k): v for k, v in HORIZON_MONTH_MAP_V3.items()},
        "horizon_granularity_tier": {str(k): v for k, v in HORIZON_GRANULARITY_TIER_V3.items()},
        "horizons": list(HORIZONS_V3),
        "scenario_horizons": list(SCENARIO_HORIZONS_V3),
        "granularity_disclosure": (
            "月度标签粒度：1/3/7/15 天映射为当月标签（7/15 为半月近似披露），30/60/90 天映射为 t+1/2/3 月"
        ),
        "serving_contract_note": (
            "serving 契约（v2.1-7col）：特征=wq_tp/tn/do/nh4_n/ph + 日历正余弦，"
            "全部为推理时逐站可得的 MEE 实测口径（wq_chla 不在冻结 78 列契约中，"
            "仅其滞后列在内，防同月同源泄漏）。滞后/遥感/气象/水文/机理/静态列在"
            "推理时为全湖常量或中位数插补，故不入选。"
        ) if serving else None,
        "split": split_manifest_fragment(features),
        "models": model_entries,
        "availability_matrix": availability["entries"],
        "bloom_threshold_ug_l": BLOOM_THRESHOLD_UG_L,
        "risk_bands_ug_l": {
            name: (">=50" if name == "severe" else f"{low}-{high}")
            for name, (low, high) in RISK_BANDS_UG_L.items()
        },
        "label_provenance_rule": "代理标签（chla≥20 或 CLMS bloom_label 或 CLMS FCB 月均概率≥0.5 或 MODIS 湖面月均 chla≥20μg/L）一律 provenance=proxy_derived，不得标 ground_truth；仅 T4-biomass（wq_phyto_biomass）与 T5-chla（地面 chla）为 ground_truth",
        "proxy_label_rules": {
            "modis_audit": {
                "positive_months": modis_audit["positive_months"],
                "covered_months": modis_audit["covered_months"],
                "degraded_months": modis_audit["degraded_months"],
            },
            "T1-T6_bloom": "月度水华代理：chla 月均≥20μg/L 或 CLMS bloom_label=1 或 CLMS FCB 湖面月均概率≥0.5 或 MODIS 湖面月均 chla≥20μg/L（仅 TAIHU_WHOLE 行）；有任一来源即定义为 0/1（fcb 阈值口径：CLMS LWQ 300m 10-day FCB 概率按月聚合均值，frame 列为 0-1 概率的 1e4 缩放已归一）",
            "T1-T6_bloom_modis": "MODIS-Aqua chla_retrieval（TAIHU_BBOX 湖面提取，不含 CLMS 行）按月行均值聚合为湖面月均值；valid 行优先，无 valid 月回退 review 行均值并降权披露（review=有效像元 <5% 或聚合天数 <3，值非无效仅覆盖度降级）；≥20μg/L 计阳性",
            "T2-coverage": "湖面蓝藻覆盖概率代理 = CLMS FCB 概率月度均值（0-1）；来源 CLMS LWQ 300m 10-day 产品，仅覆盖 2024-09..2026-08（test 期）；provenance=proxy_derived",
            "T3-density": "蓝藻密度秩代理 = phyto_biomass 月度均值在全量站点-月的分位秩（0-1，无量纲）；未做细胞体积换算，如实披露；provenance=proxy_derived",
            "T4-biomass": "浮游植物生物量（mg/L）直接作目标；wq_phyto_biomass 576 行 ground_truth，2005-02..2020-11（全在 train 期）；训练剔除当月 wq_phyto_biomass 特征防同月泄漏",
            "chla_station_proxy": "见 evaluation/chla_proxy_params.json（公示公式+2020-12 航次实测锚点+固定种子残差自助）；代理标签仅回填缺失行，实测标签绝不覆盖；消费方按 proxy_derived 披露",
            "target_source_feature_exclusions": "biomass/density 剔除 wq_phyto_biomass，coverage 剔除 rs_clms_lwq_300m_10daily_fcb_prob（当月值，滞后/滚动列保留）",
        },
        "legacy": {
            "v0_2_package": LEGACY_PACKAGE,
            "legacy": True,
            "note": "保留作对照与回退（env TAIHU_MODEL_PACKAGE_DIR=model_runtime_v0_2）",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[manifest] models={len(model_entries)} → {out_dir / 'manifest.json'}")
    return manifest


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "all"
    if command == "build-tables":
        cmd_build_tables()
        return 0
    if command == "train-all":
        built = cmd_build_tables()
        cmd_train_all(built["base"], built["labels"])
        return 0
    if command == "gate":
        cmd_gate()
        return 0
    if command == "manifest":
        cmd_manifest()
        return 0
    if command == "all":
        built = cmd_build_tables()
        cmd_train_all(built["base"], built["labels"])
        cmd_gate()
        cmd_manifest()
        return 0
    print(f"unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
