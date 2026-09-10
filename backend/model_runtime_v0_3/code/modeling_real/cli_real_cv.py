"""V0.3 补充训练 CLI：T3-density / T4-biomass 训练期内时间分块协议（train-cv / gate / manifest / all）。

背景：冻结划分（train≤2021 / val 2022-2023 / test≥2024）下，T3/T4 的 576 行真实标签
（2005-02..2020-11）全部落在 train 期，validation/test 均为 0 行，按原门禁口径不可训练
（insufficient_validation_rows_min5）。本脚本不改动冻结划分本身，只在补训副本内把
train 期按月份时间分块（早 70% 月拟合 / 晚 30% 月做族选择与 conformal 残差校准），
复用 train_run_real 的全部候选族与产物落盘逻辑补训 1/3/7/15 天（month_offset=0）模型。

诚实边界（写入 run_config / uncertainty_meta / manifest）：
- 协议 ID = train_internal_time_block_cv_v1，validation 指标来自训练期晚段分块，
  不是冻结 2022-2023 验证集；
- 冻结测试期（≥2024-01）无 T3/T4 标签，测试指标与经验覆盖率保持空，不得伪造；
- 门禁表中这些 run 因测试指标缺失记为 N.A.（missing_fusion_or_single_family_test_metrics）。

用法：
  C:/Anaconda/python.exe backend/model_runtime_v0_3/code/modeling_real/cli_real_cv.py all
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from modeling_real import data_real  # noqa: E402
from modeling_real.cli_real import cmd_gate, cmd_manifest  # noqa: E402
from modeling_real.contracts_real import (  # noqa: E402
    DATA_VERSION_V3,
    DEFAULT_SEED_V3,
    FEATURE_COLUMNS_V2,
    HORIZON_MAP_V3,
    SERVING_FEATURE_COLUMNS_V2,
    TASK_SPECS_REAL,
    package_root,
)
from modeling_real.data_real import StationMonthSource  # noqa: E402
from modeling_real.target_builder import (  # noqa: E402
    build_availability_matrix,
    build_supervised_base,
)
from modeling_real.training_real import train_run_real  # noqa: E402

SEED = DEFAULT_SEED_V3
PROTOCOL_ID = "train_internal_time_block_cv_v1"
CV_BLOCK_FRACTION = 0.7
# 2026-09-11 扩到 T1/T5/T6：叶绿素代理标签（公示口径）补齐后，这五个任务的
# 真实标签/代理标签全部落在冻结 train 期，统一以训练期内时间分块协议做族选择。
CV_TASKS = (("T1", "bloom"), ("T3", "density"), ("T4", "biomass"), ("T5", "chla"), ("T6", "probability"))
CV_HORIZONS = (1, 3, 7, 15)

PROTOCOL_DISCLOSURE = (
    "五个任务（T1/T3/T4/T5/T6）的真实标签或公示代理标签全部落在冻结 train 期（2005-02..2020-11，含 2020-12 航次），冻结 validation 基本为 0 行或无水质行；"
    "本 run 在不动冻结划分的前提下，于补训副本内把 train 期按月份时间分块"
    f"（早 {int(CV_BLOCK_FRACTION * 100)}% 月拟合、晚 {100 - int(CV_BLOCK_FRACTION * 100)}% 月做族选择）。"
    "conformal 残差池 = 两部分：早段拟合模型对晚段的折外预测残差，以及全量 train 拟合的最终模型对晚段的"
    "残差（后者含在样本内成分，区间偏窄）；冻结测试期无该任务标签，测试指标与经验覆盖率保持空。"
    "该协议模型不得与冻结划分模型的口径混同。"
)


def _write_json(payload: dict, path: Path) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _protocol_fragment() -> dict:
    return {
        "protocol_id": PROTOCOL_ID,
        "block_fraction": CV_BLOCK_FRACTION,
        "disclosure": PROTOCOL_DISCLOSURE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def cmd_train_cv() -> list[dict]:
    import os

    # serving 契约与 cli_real.cmd_train_all 同一开关：补训模型同样只吃推理时
    # 逐站可得的特征子集，保证 T3/T4 服务输出对站点输入有响应。
    serving = os.environ.get("TAIHU_FEATURE_CONTRACT", "").strip().lower() == "serving"
    feature_universe = SERVING_FEATURE_COLUMNS_V2 if serving else FEATURE_COLUMNS_V2
    print(f"[train-cv] feature contract: {'serving-7col' if serving else 'frozen-78col'}")
    base, labels = build_supervised_base()
    _entries, tables = build_availability_matrix(base, labels)
    out_dir = package_root()
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for task_id, variant in CV_TASKS:
        spec = next(
            s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant
        )
        for horizon in CV_HORIZONS:
            offset = HORIZON_MAP_V3.month_offset(horizon)
            table = tables[f"{task_id}-{variant}-{offset}m"].copy()
            months = sorted(table["month"].unique())
            if len(months) < 6:
                print(f"[train-cv] {task_id}-{variant}-{horizon}d: months<{len(months)} 跳过")
                continue
            cut = months[int(len(months) * CV_BLOCK_FRACTION)]
            # StationMonthSource 只认 train/validation/test；晚段分块以 validation 供给族选择与校准
            table["dataset_split_frozen"] = [
                "train" if month <= cut else "validation" for month in table["month"]
            ]
            feature_columns = tuple(c for c in feature_universe if c in table.columns)
            source = StationMonthSource(table, feature_columns)
            run_dir = runs_dir / f"{task_id}-{variant}-{horizon}d-{offset}m-cv"
            result = train_run_real(
                spec, horizon, source, run_dir, seed=SEED,
                data_manifest={"data_version": DATA_VERSION_V3},
            )
            # run_config 补写协议披露
            config_path = run_dir / "run_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["split_protocol"] = _protocol_fragment()
            config["split_counts_internal"] = {
                "train": int(sum(1 for month in table["month"] if month <= cut)),
                "cv_validation": int(sum(1 for month in table["month"] if month > cut)),
            }
            _write_json(config, config_path)
            # bundle 元数据补写协议标记（运行层据此区分 value_origin / training_protocol）
            models_dir = out_dir / "models"
            model_path = models_dir / f"{result['run_id']}-{horizon}d.joblib"
            bundle = data_real.load_bundle(model_path)
            bundle.uncertainty_meta["split_protocol"] = PROTOCOL_ID
            bundle.uncertainty_meta["protocol_disclosure"] = PROTOCOL_DISCLOSURE
            data_real.save_bundle(bundle, models_dir)
            print(
                f"[train-cv] {result['run_id']}: {result['status']} "
                f"selected={result.get('selected_family')} cv_val={result.get('validation_value')}"
            )
            results.append(result)
    return results


def cmd_patch_availability() -> None:
    """availability_matrix：T3/T4 0m 条目改为 trainable（协议标记），供 manifest 引用。"""
    path = package_root() / "evaluation" / "availability_matrix.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    patched = 0
    for entry in payload.get("entries", []):
        if (
            (entry.get("task_id"), entry.get("variant")) in CV_TASKS
            and entry.get("month_offset") == 0
            and not entry.get("trainable")
        ):
            entry["trainable"] = True
            entry["reason"] = None
            entry["supplemental_protocol"] = PROTOCOL_ID
            entry["protocol_note"] = (
                "冻结 validation 为 0 行；以训练期内时间分块协议补训，非冻结划分口径。"
            )
            patched += 1
    payload["supplemental_training"] = _protocol_fragment()
    _write_json(payload, path)
    print(f"[availability] patched={patched} → {path}")


def cmd_patch_manifest() -> None:
    """manifest 补写补充训练说明段（模型条目由 cmd_manifest 从 bundle 自动带出协议键）。"""
    path = package_root() / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    cv_models = [
        model for model in manifest.get("models", [])
        if (model.get("uncertainty") or {}).get("split_protocol") == PROTOCOL_ID
    ]
    manifest["supplemental_training"] = {
        **_protocol_fragment(),
        "model_count": len(cv_models),
        "runs": sorted({model["run_id"] for model in cv_models}),
        "note": (
            "T3-density / T4-biomass 4 短时效 run 以训练期内时间分块协议补训；"
            "其余模型仍为冻结划分协议。运行层 results[*].training_protocol 区分两种口径。"
        ),
    }
    _write_json(manifest, path)
    print(f"[manifest] supplemental_training models={len(cv_models)} → {path}")


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "all"
    if command == "train-cv":
        cmd_train_cv()
        return 0
    if command == "gate":
        cmd_gate()
        return 0
    if command == "manifest":
        cmd_patch_availability()
        cmd_manifest()
        cmd_patch_manifest()
        return 0
    if command == "all":
        cmd_train_cv()
        cmd_patch_availability()
        cmd_gate()
        cmd_manifest()
        cmd_patch_manifest()
        return 0
    print(f"unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
