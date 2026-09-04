"""发布清单与哈希 `release` (设计 §12 交付目录).

组装 data_factory_release/SIM-V1/（data/geometry/contract/quality/lineage/docs）
并生成 hashes.sha256；release 重建整个发布目录。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from data_factory import CONTRACT_VERSION, GENERATOR_VERSION
from data_factory.contracts.constants import CONFIG_DIR, RELEASE_ROOT, SOURCE_REGISTRY_CSV, run_dir

# DG-009：必需交付清单（缺任一 → release fail，退出码 1）
REQUIRED_RELEASE_FILES = (
    "data/grid_metadata.csv",
    "data/station_grid_mapping.csv",
    "data/stations.csv",
    "data/split_manifest.csv",
    "data/bloom_grid_daily.parquet",
    "data/bloom_lake_daily.parquet",
    "data/satellite_observations.parquet",
    "data/station_observations.parquet",
    "data/task_labels.parquet",
    "data/model_training_samples.parquet",
    "data/member_c_training_samples.csv",
    "data/dynamic_features_grid_daily.parquet",
    "data/target_observation_daily.parquet",
    "generation/parameter_sets.parquet",
    "lineage/source_registry.csv",
    "lineage/file_lineage.parquet",
    "lineage/row_lineage.parquet",
    "lineage/transformation_log.jsonl",
    "quality/leakage_audit.csv",
    "hashes.sha256",
    "release_manifest.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_sim_dir(base_dir: Path) -> Path | None:
    sim_root = base_dir / "simulation"
    if not sim_root.exists():
        return None
    dirs = [d for d in sim_root.iterdir() if d.is_dir() and (d / "sim_manifest.json").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: (d / "sim_manifest.json").stat().st_mtime)


def build_release(config: dict[str, Any], *, dataset: str | None = None, release_root: Path | None = None) -> dict[str, Any]:
    dataset = dataset or config.get("dataset_id", "mvp_meiliangwan_2024")
    base_dir = run_dir(dataset)
    sim_dir = _latest_sim_dir(base_dir)
    if sim_dir is None:
        raise SystemExit("no simulation run found; run `python -m data_factory simulate` first")
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))

    # DG-011：validate 未通过（acceptance/veto 任一 fail）→ 拒绝发布，不动现有发布目录
    blocked: list[str] = []
    for name, table in (("acceptance_21.csv", "acceptance"), ("veto_12.csv", "veto")):
        path = base_dir / "quality" / name
        if path.exists():
            frame = pd.read_csv(path)
            blocked += [f"{table}:{rule}" for rule in frame.loc[frame["status"] == "fail", "rule_id"]]
    if blocked:
        return {
            "status": "blocked",
            "command": "release",
            "reason": "quality gate failed；先修复并重跑 validate，再 release",
            "failing_rules": blocked,
            "dataset_version": dataset,
        }

    release_root = Path(release_root or RELEASE_ROOT) / "SIM-V1"
    if release_root.exists():
        shutil.rmtree(release_root)
    release_root.mkdir(parents=True)

    copied: list[dict[str, str]] = []
    missing: list[str] = []

    def _copy(src: Path, dest_rel: str) -> None:
        if not src.exists():
            missing.append(str(src))
            return
        dest = release_root / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append({"src": str(src), "dest": str(dest), "sha256": _sha256(dest)})

    # data/
    _copy(base_dir / "grid" / "grid_metadata.csv", "data/grid_metadata.csv")
    _copy(base_dir / "grid" / "station_grid_mapping.csv", "data/station_grid_mapping.csv")
    _copy(base_dir / "grid" / "stations.csv", "data/stations.csv")
    _copy(base_dir / "splits" / "split_manifest.csv", "data/split_manifest.csv")
    _copy(sim_dir / "bloom_grid_daily.parquet", "data/bloom_grid_daily.parquet")
    _copy(sim_dir / "bloom_lake_daily.parquet", "data/bloom_lake_daily.parquet")
    _copy(base_dir / "observations" / "satellite_observations.parquet", "data/satellite_observations.parquet")
    _copy(base_dir / "observations" / "station_observations.parquet", "data/station_observations.parquet")
    _copy(base_dir / "labels" / "task_labels.parquet", "data/task_labels.parquet")
    _copy(base_dir / "assembly" / "SIM_V1" / "model_training_samples.parquet", "data/model_training_samples.parquet")
    _copy(base_dir / "assembly" / "SIM_V1" / "member_c_training_samples.csv", "data/member_c_training_samples.csv")
    # DG-004 发布表：观测层特征与标签用观测真值行
    _copy(base_dir / "data" / "dynamic_features_grid_daily.parquet", "data/dynamic_features_grid_daily.parquet")
    _copy(base_dir / "data" / "target_observation_daily.parquet", "data/target_observation_daily.parquet")

    # generation/：校准参数集（DG-009）
    _copy(base_dir / "fit" / "parameter_sets.parquet", "generation/parameter_sets.parquet")

    # geometry/
    for name in ("lake_boundary.geojson", "region_boundaries.geojson", "grid_boundaries.geojson"):
        _copy(base_dir / "grid" / name, f"geometry/{name}")
    for geo in sorted((base_dir / "labels").glob("bloom_extent_*.geojson")):
        _copy(geo, f"geometry/{geo.name}")

    # contract/（冻结输入原样入包）
    for name in ("label_thresholds.yaml", "mechanism_parameters.yaml", "generation_config.yaml", "scenario_catalog.yaml", "realtime_sources.yml"):
        _copy(CONFIG_DIR / name, f"contract/{name}")
    from data_factory.contracts.field_dictionary import build_field_dictionary, build_label_dictionary

    build_field_dictionary().to_csv(release_root / "contract" / "field_dictionary.csv", index=False, encoding="utf-8")
    build_label_dictionary().to_csv(release_root / "contract" / "label_dictionary.csv", index=False, encoding="utf-8")

    # quality/
    for name in (
        "acceptance_21.csv",
        "veto_12.csv",
        "label_coverage_by_task_split.csv",
        "positive_negative_balance.csv",
        "feature_completeness.csv",
        "physical_bounds_summary.csv",
        "distribution_checks.csv",
        "reproducibility_manifest.md",
        "quality_summary.md",
    ):
        _copy(base_dir / "quality" / name, f"quality/{name}")

    # lineage/ + manifests/
    _copy(base_dir / "lineage" / "row_lineage.parquet", "lineage/row_lineage.parquet")
    _copy(base_dir / "lineage" / "file_lineage.parquet", "lineage/file_lineage.parquet")
    _copy(SOURCE_REGISTRY_CSV, "lineage/source_registry.csv")
    _copy(sim_dir / "sim_manifest.json", "lineage/manifests/sim_manifest.json")
    for name in ("fit_manifest.json", "labels_manifest.json", "assembly_manifest.json", "observations_manifest.json", "grid_manifest.json", "split_lock.json"):
        subdir = {"fit_manifest.json": "fit", "labels_manifest.json": "labels", "assembly_manifest.json": "assembly/SIM_V1", "observations_manifest.json": "observations", "grid_manifest.json": "grid", "split_lock.json": "splits"}[name]
        _copy(base_dir / subdir / name, f"lineage/manifests/{name}")

    # DG-009 生成件：transformation_log.jsonl + leakage_audit.csv
    transform_path = release_root / "lineage" / "transformation_log.jsonl"
    n_stages = _write_transformation_log(base_dir, sim_dir, transform_path, sim_manifest.get("parameter_set_id"))
    copied.append({"src": "generated", "dest": str(transform_path), "sha256": _sha256(transform_path)})
    leak_path = release_root / "quality" / "leakage_audit.csv"
    _write_leakage_audit(base_dir, leak_path)
    copied.append({"src": "generated", "dest": str(leak_path), "sha256": _sha256(leak_path)})

    # docs/
    docs = release_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "README.md").write_text(_readme_text(config, sim_manifest, missing), encoding="utf-8")
    (docs / "limitations.md").write_text(_limitations_text(sim_manifest), encoding="utf-8")

    hash_lines = [f"{entry['sha256']}  {Path(entry['dest']).relative_to(release_root).as_posix()}" for entry in copied]
    # newline="\n"：sha256sum 要求 LF，Windows 默认会转成 CRLF 导致复核失败
    (release_root / "hashes.sha256").write_text("\n".join(hash_lines) + "\n", encoding="utf-8", newline="\n")

    # release_manifest.json 由本命令自身产出，不参与“预先存在”校验
    absent_required = [
        rel for rel in REQUIRED_RELEASE_FILES
        if rel != "release_manifest.json" and not (release_root / rel).exists()
    ]
    status = "completed" if not missing and not absent_required else "failed"

    release_manifest = {
        "status": status,
        "command": "release",
        "track": "SIM-V1",
        "dataset_version": dataset,
        "contract_version": CONTRACT_VERSION,
        "generator_version": GENERATOR_VERSION,
        "scenario_id": sim_manifest.get("scenario_id"),
        "random_seed": sim_manifest.get("random_seed"),
        "parameter_set_id": sim_manifest.get("parameter_set_id"),
        "generation_batch_id": sim_manifest.get("generation_batch_id"),
        "code_commit": _git_commit(),
        "release_root": str(release_root),
        "files": len(copied),
        "transformation_log_stages": n_stages,
        "missing": missing,
        "absent_required": absent_required,
        "hashes_file": str(release_root / "hashes.sha256"),
        "rows_written": len(copied),
        "next_action": "sha256sum -c hashes.sha256 复核后交付" if status == "completed" else "补齐缺失文件后重跑 release（缺必需交付 → 退出码 1）",
    }
    (release_root / "release_manifest.json").write_text(json.dumps(release_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return release_manifest


def _git_commit() -> str | None:
    import subprocess

    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001 — git 不可用时如实留空
        return None


def _write_transformation_log(base_dir: Path, sim_dir: Path, out_path: Path, parameter_set_id: str | None) -> int:
    """DG-009：每阶段 输入→输出表名/行数/规则/参数集引用 的转换日志。"""

    chain: list[tuple[str, Path]] = [
        ("freeze-grid", base_dir / "grid" / "grid_manifest.json"),
        ("ingest-history", base_dir / "history" / "history_manifest.json"),
        ("lock-splits", base_dir / "splits" / "split_lock.json"),
        ("fit", base_dir / "fit" / "fit_manifest.json"),
        ("simulate", sim_dir / "sim_manifest.json"),
        ("build-observations", base_dir / "observations" / "observations_manifest.json"),
        ("build-labels", base_dir / "labels" / "labels_manifest.json"),
        ("assemble", base_dir / "assembly" / "SIM_V1" / "assembly_manifest.json"),
        ("validate", base_dir / "quality" / "quality_summary.md"),
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    lines: list[str] = []
    for stage, path in chain:
        if not path.exists():
            continue
        if path.suffix == ".json":
            manifest = json.loads(path.read_text(encoding="utf-8"))
            outputs = manifest.get("outputs") or manifest.get("output") or {}
            record = {
                "stage": stage,
                "generator_version": manifest.get("generator_version", GENERATOR_VERSION),
                "parameter_set_id": manifest.get("parameter_set_id", parameter_set_id),
                "generation_batch_id": manifest.get("generation_batch_id"),
                "inputs_sha256": manifest.get("inputs_sha256") or manifest.get("input_filtering") or {},
                "outputs": outputs,
                "rows_written": manifest.get("rows_written"),
                "rules": manifest.get("rule") or manifest.get("unknown_rule") or manifest.get("gating") or "",
            }
        else:  # 质量报告等非 JSON 产物：只登记文件本身
            record = {
                "stage": stage,
                "generator_version": GENERATOR_VERSION,
                "parameter_set_id": parameter_set_id,
                "generation_batch_id": None,
                "inputs_sha256": {},
                "outputs": {path.name: str(path)},
                "rows_written": None,
                "rules": "A01–A23 acceptance + V01–V12 veto",
            }
        lines.append(json.dumps(record, ensure_ascii=False, default=str))
        n += 1
    # newline="\n"：jsonl 统一 LF
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
    return n


def _write_leakage_audit(base_dir: Path, out_path: Path) -> None:
    """DG-009：泄漏审计汇总（A05/A06/A15/A22 + V05/V06 + fit 逐 family cutoff）。"""

    rows: list[dict[str, str]] = []
    for name, table in (("acceptance_21.csv", "acceptance"), ("veto_12.csv", "veto")):
        path = base_dir / "quality" / name
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        for rule_id in ("A05", "A06", "A15", "A22", "V05", "V06"):
            hit = frame[frame["rule_id"] == rule_id]
            if hit.empty:
                continue
            row = hit.iloc[0]
            rows.append({"check": f"{table}:{rule_id}", "name": row["name"], "status": row["status"], "detail": str(row["detail"])[:300]})
    fit_manifest_path = base_dir / "fit" / "fit_manifest.json"
    if fit_manifest_path.exists():
        fit_manifest = json.loads(fit_manifest_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "check": "fit:per_family_max_input_date",
                "name": "calibration cutoff audit (DG-002)",
                "status": "pass" if fit_manifest.get("cutoff_enforced_all_families") else "unknown",
                "detail": f"train_cutoff={fit_manifest.get('train_cutoff_date')}; per_family={json.dumps(fit_manifest.get('per_family_max_input_date') or {}, ensure_ascii=False)}",
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8")


def _readme_text(config: dict[str, Any], sim_manifest: dict[str, Any], missing: list[str]) -> str:
    return f"""# SIM-V1 发布包（梅梁湾 × 2024 MVP）

- dataset_version: {config.get("dataset_id")}
- track: SIM-V1（全仿真；全部标签为 simulation_*，**不得作为真实观测使用**）
- scenario/seed: {sim_manifest.get("scenario_id")} / {sim_manifest.get("random_seed")}
- parameter_set_id: {sim_manifest.get("parameter_set_id")}
- generator_version: {GENERATOR_VERSION}

## 目录
- data/ 网格、水华逐日、观测层、训练样本、观测层特征表（dynamic_features_grid_daily/target_observation_daily，DG-004）与成员 C 适配 CSV
- generation/ 校准参数集 parameter_sets.parquet（DG-009）
- geometry/ 湖界/分区/网格与水华范围 GeoJSON 证据
- contract/ 冻结阈值、机理参数、生成配置、字段字典、任务×粒度契约矩阵（DG-008，见 field_dictionary.csv 备注）
- quality/ 23 项验收 + 12 项否决 + 九件套 + leakage_audit.csv（DG-011 三段式判定见 quality_summary.md）
- lineage/ row_lineage.parquet（sample_id 键控，DG-010）+ file_lineage.parquet（阶段链）+ source_registry.csv + transformation_log.jsonl（DG-009）+ 各阶段 manifest
- hashes.sha256 全部文件哈希（复核：`sha256sum -c hashes.sha256`）

## 复现
```bash
python -m data_factory freeze-grid
python -m data_factory ingest-history --source release-tables
python -m data_factory lock-splits
python -m data_factory fit --split train
python -m data_factory simulate --scenario {sim_manifest.get("scenario_id")} --seed {sim_manifest.get("random_seed")}
python -m data_factory build-observations
python -m data_factory build-labels
python -m data_factory assemble --track SIM-V1
python -m data_factory validate
python -m data_factory release
```

缺失项：{missing or "无"}
"""


def _limitations_text(sim_manifest: dict[str, Any]) -> str:
    lines = ["# 明确简化与限制", ""]
    for item in sim_manifest.get("limitations", []):
        lines.append(f"- {item}")
    lines += [
        "",
        "## 口径",
        "- SIM-V1 全部标签为 simulation_*（is_synthetic=true），仅用于仿真世界内的算法比较与预训练。",
        "- 观测层由真实采样日历/过境日驱动，但观测值本身是模拟的。",
        "- MVP 为单湖区（梅梁湾）单年（2024）；全湖配置就绪未实跑。",
        "",
        "## 部分域与任务粒度 (DG-001/DG-008)",
        "- 本包仿真域仅为梅梁湾：lake 粒度（TAIHU_WHOLE）行的 domain_coverage_fraction ≈ 0.208（仿真有效面积/冻结全湖面积），is_partial_domain=true；grid/zone/station 行 coverage=1.0。",
        "- 任务×粒度契约矩阵：T1/T2/T5=grid+zone+lake；T3/T4/T6/T7=zone+lake；T3/T4/T5 另有 station 粒度观测标签。超出现登记粒度的使用（如全湖 T3）未获支持。",
        "",
        "## 观测层特征与已知不足 (DG-004/DG-007)",
        "- 特征仅来自观测层：真实逐日气象（d+1 出账）、站点采样水温（月度，稀疏）、卫星 chla/bloom_fraction（~35 个过境日）；水位/营养盐/生物量等 latent 变量不作为特征。WQ 特征缺测如实为空，缺失率见 assembly manifest 的 feature_observed_ratio 与成员 C 适配摘要。",
        "- 冬季藻类生物学过程（越冬/休眠/补种）未建模，冬季 chla 动态可信度有限；夏季/冬季均值比已通过 A21 门禁（>=1.5），但 DG-007 根治需多年观测数据。",
    ]
    return "\n".join(lines) + "\n"
