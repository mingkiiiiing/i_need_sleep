"""发布轨道编排 `assemble --track` (设计 §9 三轨道).

SIM-V1：全仿真装配（本期实装）；HYBRID-V1/REAL-V1：占位 STAGED，
待真实标签配比与混合门控评审后启用（验证/测试仅收 ground_truth）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_factory.contracts.constants import utc_now_iso
from data_factory.contracts.enums import Track
from . import horizons
from .member_c_adapter import write_member_c_csv


def run_assemble(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
    labels_dir: Path,
    track: str = Track.SIM_V1.value,
    dataset: str | None = None,
) -> dict[str, Any]:
    dataset = dataset or config.get("dataset_id", "mvp_meiliangwan_2024")
    if track == Track.SIM_V1.value:
        manifest = horizons.run_assembly(config, base_dir=base_dir, sim_dir=sim_dir, labels_dir=labels_dir, dataset=dataset, track=track)
        samples_path = Path(manifest["outputs"]["model_training_samples"])
        import pandas as pd

        samples = pd.read_parquet(samples_path)
        member_c = write_member_c_csv(samples, samples_path.parent / "member_c_training_samples.csv", track=track)
        manifest["member_c_adapter"] = member_c
        manifest["outputs"]["member_c_training_samples"] = member_c["output"]
        samples_path.parent.joinpath("assembly_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    out_dir = base_dir / "assembly" / track.replace("-", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "status": "STAGED",
        "command": "assemble",
        "track": track,
        "dataset_version": dataset,
        "reason": "HYBRID-V1/REAL-V1 需要 真实标签配比评审 与 混合门控规则 冻结后实装 (设计 §9/首期明确不做)",
        "gating_preview": {
            "validation_test": "仅 source_type=ground_truth 且 label_status=observed_* 的样本",
            "train": "ground_truth 优先；SIM 样本仅可用于预训练/增强且 is_synthetic=true",
        },
        "checked_at_utc": utc_now_iso(),
    }
    (out_dir / "assembly_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
