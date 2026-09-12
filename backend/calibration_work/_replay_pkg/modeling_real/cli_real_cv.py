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
    GATE_MIN_TEST_ROWS,
    HORIZON_MAP_V3,
    SERVING_FEATURE_COLUMNS_V2,
    SERVING_LAGGED_TARGET_FEATURES,
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
# 时间分块比例（2026-09-11 修）：此前留出段 100% 划给 validation、test 为空，
# 于是 test_metrics_by_family.json 全空 → 门禁表只能记 NA、经验覆盖率无法核算。
# 现按 60/20/20 切成 拟合 / 族选择+校准 / 留出测试 三段，全部按月份时序、无前视。
CV_BLOCK_TRAIN_FRACTION = 0.6
CV_BLOCK_VALIDATION_FRACTION = 0.2
# 2026-09-11 扩到 T1/T5/T6：叶绿素代理标签（公示口径）补齐后，这五个任务的
# 真实标签/代理标签全部落在冻结 train 期，统一以训练期内时间分块协议做族选择。
CV_TASKS = (
    ("T1", "bloom"), ("T3", "density"), ("T4", "biomass"), ("T5", "chla"),
    ("T6", "probability"),
    # 风险等级是页面默认焦点指标，其冻结划分 test 仅 1 行、融合族又因序数标签整族缺席，
    # 门禁长期只能记 NA。纳入补训后才有可评估的融合 vs 单模型比较。
    ("T6", "risk_level"),
)
CV_HORIZONS = (1, 3, 7, 15)
# 中长期趋势（month_offset 1/2/3）：标签方向修正后按目标月划分，冻结 validation
# 同样无足够标签，沿用训练期内时间分块协议（分块键=目标月，防前视）。
CV_TREND_HORIZONS = (30, 60, 90)

PROTOCOL_DISCLOSURE = (
    "五个任务（T1/T3/T4/T5/T6）的真实标签或公示代理标签全部落在冻结 train 期（2005-02..2020-11，含 2020-12 航次），冻结 validation 基本为 0 行或无水质行；"
    "本 run 在不动冻结划分的前提下，于补训副本内把可用月份按时间顺序切成三段"
    f"（前 {int(CV_BLOCK_TRAIN_FRACTION * 100)}% 拟合、中 {int(CV_BLOCK_VALIDATION_FRACTION * 100)}% 族选择与 conformal 校准、"
    f"后 {100 - int(CV_BLOCK_TRAIN_FRACTION * 100) - int(CV_BLOCK_VALIDATION_FRACTION * 100)}% 留出测试）。"
    "测试段完全在时间上晚于拟合段，无前视；测试指标与经验覆盖率在该段上真实核算。"
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
        "block_fractions": {
            "train": CV_BLOCK_TRAIN_FRACTION,
            "validation": CV_BLOCK_VALIDATION_FRACTION,
            "test": round(1 - CV_BLOCK_TRAIN_FRACTION - CV_BLOCK_VALIDATION_FRACTION, 6),
        },
        "disclosure": PROTOCOL_DISCLOSURE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _climatology_history(history_table, target_month_cutoff: str, columns: tuple) -> pd.DataFrame | None:
    """月气候态基线的拟合样本：任务历史标签序列中目标月严格早于留出测试段的那些行。

    history_table 是同一任务 month_offset=0 的监督表——它的 actual 就是逐站逐月的真实
    标签，calendar_month_sin/cos 即标签所在月。用它估月气候态，得到的是真实季节循环；
    用几十行的中长期拟合段去估，只会得到一张几乎全 0 的查表。
    截断到留出测试段之前，保证评估时没有前视。
    """
    if history_table is None or not len(history_table):
        return None
    frame = history_table.loc[history_table["target_month"] < target_month_cutoff]
    keep = [c for c in ("actual", *columns) if c in frame.columns]
    if "actual" not in keep or not len(frame):
        return None
    return frame.loc[:, keep].reset_index(drop=True)


def _train_cv_run(
    spec, horizon: int, offset: int, table, feature_columns: tuple,
    runs_dir: Path, models_dir: Path, split_key: str,
    climatology_history: pd.DataFrame | None = None,
) -> dict | None:
    """单个 CV run：按 split_key 列（输入月或目标月）时间三块切分后训练并补写协议披露。

    三块（时序，无前视）：拟合 / 族选择+conformal 校准 / 留出测试。
    留出测试段是评估证据的唯一来源：门禁比较与经验覆盖率都在它上面核算。
    """
    months = sorted(table[split_key].unique())
    if len(months) < 5:
        print(f"[train-cv] {spec.task_id}-{spec.variant}-{horizon}d: {split_key} months<{len(months)} 跳过")
        return None
    train_end = months[max(int(len(months) * CV_BLOCK_TRAIN_FRACTION) - 1, 0)]
    validation_end = months[
        max(int(len(months) * (CV_BLOCK_TRAIN_FRACTION + CV_BLOCK_VALIDATION_FRACTION)) - 1, 0)
    ]

    def _split_of(month: str) -> str:
        if month <= train_end:
            return "train"
        if month <= validation_end:
            return "validation"
        return "test"

    # StationMonthSource 只认 train/validation/test；三块按时间顺序切，测试段晚于拟合段
    table = table.copy()
    table["dataset_split_frozen"] = [_split_of(month) for month in table[split_key]]
    counts = table["dataset_split_frozen"].value_counts().to_dict()
    source = StationMonthSource(table, feature_columns)
    run_dir = runs_dir / f"{spec.task_id}-{spec.variant}-{horizon}d-{offset}m-cv"
    if (run_dir / "evaluation_manifest.json").is_file():
        print(f"[train-cv] {spec.task_id}-{spec.variant}-{horizon}d: 已完成，跳过")
        return {"run_id": f"{spec.task_id}-{spec.variant}-{offset}m-s{SEED}-cv", "status": "skipped_completed"}
    result = train_run_real(
        spec, horizon, source, run_dir, seed=SEED,
        data_manifest={"data_version": DATA_VERSION_V3},
        protocol_tag="cv",
        climatology_history=climatology_history,
    )
    # run_config 补写协议披露
    config_path = run_dir / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["split_protocol"] = _protocol_fragment()
    config["split_key"] = split_key
    config["split_counts_internal"] = {
        "train": int(counts.get("train", 0)),
        "cv_validation": int(counts.get("validation", 0)),
        "cv_test": int(counts.get("test", 0)),
    }
    config["split_block_bounds"] = {
        "train_max_month": train_end,
        "validation_max_month": validation_end,
        "test_min_month": months[months.index(validation_end) + 1] if validation_end in months else None,
    }
    _write_json(config, config_path)
    # bundle 元数据补写协议标记（运行层据此区分 value_origin / training_protocol）。
    # 模型写固定槽位文件名，与冻结划分共用同一槽位、一槽一份。
    model_path = data_real.bundle_slot_filename(spec.task_id, spec.variant, offset, horizon, SEED)
    bundle = data_real.load_bundle(models_dir / model_path)
    bundle.uncertainty_meta["split_protocol"] = PROTOCOL_ID
    bundle.uncertainty_meta["protocol_disclosure"] = PROTOCOL_DISCLOSURE
    data_real.save_bundle(bundle, models_dir, filename=model_path)
    print(
        f"[train-cv] {result['run_id']}: {result['status']} "
        f"selected={result.get('selected_family')} cv_val={result.get('validation_value')} "
        f"test_rows={result.get('test_rows')} test={result.get('test_value')} "
        f"coverage={result.get('empirical_coverage_test')}"
    )
    return result


def _frozen_slot_is_evidenced(task_id: str, variant: str, horizon: int, offset: int) -> bool:
    """冻结划分 run 是否已有足够留出测试证据（n_test ≥ 门禁最小行数）。

    有则不再补训该槽位：冻结模型训练样本更多、评估证据更直接，补训只在冻结划分
    取不到证据时才有存在理由。两个协议共用同一模型槽位，必须只有一个写进去——
    否则门禁表里同一 (任务, 时效) 会出现两条互相矛盾的记录，服务哪个模型取决于
    写入顺序，那正是本轮要消除的"评估记录与当前模型对不上"。
    """
    manifest_path = package_root() / "runs" / f"{task_id}-{variant}-{horizon}d-{offset}m" / "evaluation_manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        return int(json.loads(manifest_path.read_text(encoding="utf-8")).get("test_rows") or 0) >= GATE_MIN_TEST_ROWS
    except Exception:  # noqa: BLE001 — 读不出证据即视为没有证据，走补训
        return False


def cmd_train_cv() -> list[dict]:
    import os

    # serving 契约与 cli_real.cmd_train_all 同一开关：补训模型同样只吃推理时
    # 逐站可得的特征子集，保证 T3/T4 服务输出对站点输入有响应。
    serving = os.environ.get("TAIHU_FEATURE_CONTRACT", "").strip().lower() == "serving"
    feature_universe = SERVING_FEATURE_COLUMNS_V2 if serving else FEATURE_COLUMNS_V2
    print(f"[train-cv] feature contract: {'serving-8col' if serving else 'frozen-78col'}")
    base, labels = build_supervised_base()
    _entries, tables = build_availability_matrix(base, labels)
    out_dir = package_root()
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    models_dir = out_dir / "models"
    results = []
    for task_id, variant in CV_TASKS:
        spec = next(
            s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant
        )
        for horizon in (*CV_HORIZONS, *CV_TREND_HORIZONS):
            offset = HORIZON_MAP_V3.month_offset(horizon)
            if _frozen_slot_is_evidenced(task_id, variant, horizon, offset):
                print(f"[train-cv] {task_id}-{variant}-{horizon}d: 冻结划分已有测试证据，不补训")
                continue
            table = tables[f"{task_id}-{variant}-{offset}m"]
            if not len(table):
                print(f"[train-cv] {task_id}-{variant}-{horizon}d: 监督表为空 跳过")
                continue
            feature_columns = tuple(c for c in feature_universe if c in table.columns)
            # month_offset≥1：当月实测（wq_chla）相对目标月为历史量，按时效追加（同 cli_real）
            if serving and offset >= 1:
                extra = SERVING_LAGGED_TARGET_FEATURES.get(spec.label_family, ())
                feature_columns = tuple(dict.fromkeys((
                    *feature_columns, *(c for c in extra if c in table.columns),
                )))
            # offset≥1 的监督表按目标月划分；时间分块同样用目标月，保证块间无前视
            split_key = "target_month" if offset >= 1 else "month"
            # 中长期（offset≥1）：月气候态基线改由该任务的历史标签序列拟合，
            # 截断在留出测试段之前。否则基线只见过几十行同季样本，退化成常量查表。
            history = None
            if offset >= 1:
                months = sorted(table[split_key].unique())
                if len(months) >= 5:
                    test_start = months[
                        max(int(len(months) * (CV_BLOCK_TRAIN_FRACTION + CV_BLOCK_VALIDATION_FRACTION)), 0)
                    ]
                    history = _climatology_history(tables[f"{task_id}-{variant}-0m"], test_start, feature_columns)
            result = _train_cv_run(
                spec, horizon, offset, table, feature_columns, runs_dir, models_dir, split_key,
                climatology_history=history,
            )
            if result is not None:
                results.append(result)
    return results


def cmd_patch_availability() -> None:
    """availability_matrix：CV 补训覆盖的条目改为 trainable（协议标记），供 manifest 引用。"""
    path = package_root() / "evaluation" / "availability_matrix.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    patched = 0
    covered_offsets = {HORIZON_MAP_V3.month_offset(h) for h in (*CV_HORIZONS, *CV_TREND_HORIZONS)}
    for entry in payload.get("entries", []):
        if (
            (entry.get("task_id"), entry.get("variant")) in CV_TASKS
            and entry.get("month_offset") in covered_offsets
            and not entry.get("trainable")
        ):
            entry["trainable"] = True
            entry["reason"] = None
            entry["supplemental_protocol"] = PROTOCOL_ID
            entry["protocol_note"] = (
                "冻结 validation 不足；以训练期内时间分块协议补训（分块键="
                f"{'目标月' if entry.get('month_offset', 0) >= 1 else '输入月'}），非冻结划分口径。"
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
            "T1/T3/T4/T5/T6 的 4 短时效 run 与 30/60/90 天中长期趋势 run 以训练期内"
            "时间分块协议补训（offset≥1 分块键=目标月）；其余模型仍为冻结划分协议。"
            "运行层 results[*].training_protocol 区分两种口径。"
        ),
    }
    _write_json(manifest, path)
    print(f"[manifest] supplemental_training models={len(cv_models)} → {path}")


def cmd_climatology() -> dict:
    """生成季节气候态基线产物（补训覆盖不到的 30/60 天时效由运行层回退消费）。"""
    from modeling_real.seasonal_climatology import write_seasonal_climatology

    return write_seasonal_climatology()


# ---------------------------------------------------------------- 产物刷新（2026-09-11）
# 为什么需要这个命令：模型权重未变，但三件事必须重新推导，否则交付包继续输出错误口径——
#   ① 标签来源：声明 ground_truth 与逐行 actual_provenance 不符（T5 的 567 行全是代理）；
#   ② 模型身份：run_id 不含时效，接口按 run_id 拼文件名会得到不存在的文件；
#   ③ 中长期路由与区间验收：T+30/60 的 5 样本模型、欠覆盖区间必须被如实降级。
# 本命令只重写"可由监督表确定性推导"的产物，绝不触碰 models/*.joblib 与 supervised/*.parquet。


def _rebuild_availability(entries: list[dict]) -> Path:
    path = package_root() / "evaluation" / "availability_matrix.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_train_rows": 10,
        "min_validation_rows": 5,
        "label_provenance_source": "supervised_table_actual_provenance_rowwise",
        "entries": entries,
    }
    _write_json(payload, path)
    return path


def cmd_patch_run_configs(tables: dict) -> int:
    """按监督表逐行 actual_provenance 回填每个 run_config 的来源与产物身份。"""
    from modeling_real.contracts_real import artifact_id_real
    from modeling_real.target_builder import provenance_summary

    runs_dir = package_root() / "runs"
    patched = 0
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        config_path = run_dir / "run_config.json"
        if not config_path.is_file():
            continue
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 读不出的配置保持原样，不猜测
            continue
        task_id = config.get("task_id")
        variant = config.get("variant")
        offset = config.get("month_offset")
        horizon = config.get("horizon_days")
        table = tables.get(f"{task_id}-{variant}-{offset}m")
        spec = next(
            (s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant), None
        )
        if table is not None and spec is not None:
            provenance = provenance_summary(table, spec.label_provenance)
            config["label_provenance"] = provenance["observed"]
            config["label_provenance_declared"] = provenance["declared"]
            config["label_provenance_breakdown"] = provenance["breakdown"]
            config["label_provenance_rows"] = provenance["rows"]
            config["label_provenance_unresolved_rows"] = provenance["unresolved_rows"]
        protocol = (
            (config.get("split_protocol") or {}).get("protocol_id")
            or ("train_internal_time_block_cv_v1" if str(config.get("run_id", "")).endswith("-cv") else "frozen_split")
        )
        config["protocol"] = protocol
        if task_id is not None and variant is not None and offset is not None and horizon is not None:
            config["artifact_id"] = artifact_id_real(
                task_id, variant, int(offset), int(horizon), int(config.get("seed") or SEED), protocol
            )
        _write_json(config, config_path)
        patched += 1
    print(f"[refresh] run_config patched={patched} → {runs_dir}")
    return patched


def cmd_refresh_derived() -> dict:
    """一次性刷新全部可推导产物（不动模型权重与监督底表 parquet）。"""
    from modeling_real.seasonal_climatology import write_seasonal_climatology

    base, labels = build_supervised_base()
    entries, tables = build_availability_matrix(base, labels)
    path = _rebuild_availability(entries)
    print(f"[refresh] availability rebuilt entries={len(entries)} → {path}")
    patched = cmd_patch_run_configs(tables)
    cmd_patch_availability()
    climatology = write_seasonal_climatology(base=base, labels=labels)
    cmd_gate()
    cmd_manifest()
    cmd_patch_manifest()
    return {"availability_entries": len(entries), "run_config_patched": patched,
            "climatology_tasks": len(climatology.get("tasks", []))}


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "all"
    if command == "train-cv":
        cmd_train_cv()
        return 0
    if command == "climatology":
        cmd_climatology()
        return 0
    if command == "refresh-derived":
        cmd_refresh_derived()
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
        cmd_climatology()
        cmd_gate()
        cmd_manifest()
        cmd_patch_manifest()
        return 0
    print(f"unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
