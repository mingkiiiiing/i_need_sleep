"""血缘台账 (设计 §9 lineage；DG-010 重构).

- file_lineage.parquet：阶段链台账（每阶段一行，manifest 内容寻址 id 串联）
- row_lineage.parquet：sample_id 键控逐行血缘，由 assemble 阶段产出（行数=样本数）
逐行血缘字段同时内嵌于各数据表（generation_batch_id/parameter_set_id/parent_record_ids）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from data_factory import GENERATOR_VERSION
from data_factory.contracts.constants import utc_now_iso
from data_factory.lineage.hashing import content_hash


def _stage_rows(manifests: list[tuple[str, Path]], parent_id: str | None, batch_id: str | None, seed: int | None, parameter_set_id: str | None, scenario_id: str | None) -> list[dict[str, Any]]:
    rows = []
    created = utc_now_iso()
    for stage, path in manifests:
        if not path.exists():
            continue
        payload = path.read_text(encoding="utf-8")
        record_id = f"ln-{stage}-{content_hash(payload)[:16]}"
        rows.append(
            {
                "record_id": record_id,
                "stage": stage,
                "parent_record_ids": parent_id or "",
                "transformation": f"{stage} manifest sha-derived record id",
                "generator_version": GENERATOR_VERSION,
                "scenario_id": scenario_id,
                "random_seed": seed,
                "parameter_set_id": parameter_set_id,
                "generation_batch_id": batch_id,
                "created_at_utc": created,
            }
        )
        parent_id = record_id
    return rows


def build_stage_lineage(base_dir: Path, sim_dir: Path) -> pd.DataFrame:
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))
    batch_id = sim_manifest.get("generation_batch_id")
    seed = sim_manifest.get("random_seed")
    psid = sim_manifest.get("parameter_set_id")

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
    rows = _stage_rows(chain, None, batch_id, seed, psid, sim_manifest.get("scenario_id"))
    return pd.DataFrame(rows)


def write_row_lineage(base_dir: Path, sim_dir: Path) -> dict[str, Any]:
    frame = build_stage_lineage(base_dir, sim_dir)
    out_dir = base_dir / "lineage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "file_lineage.parquet"
    frame.to_parquet(out_path, index=False)
    sample_path = out_dir / "row_lineage.parquet"
    sample_rows = int(len(pd.read_parquet(sample_path, columns=["sample_id"]))) if sample_path.exists() else 0
    return {
        "status": "completed",
        "command": "lineage",
        "stages": frame["stage"].tolist() if not frame.empty else [],
        "rows_written": int(len(frame)),
        "row_lineage_rows": sample_rows,
        "note": "DG-010：阶段链台账更名为 file_lineage.parquet；sample_id 键控的 row_lineage.parquet 由 assemble 产出（行数=样本数）",
        "output": str(out_path),
    }
