"""时间切分锁 (设计 §10：先切分、再拟合、再生成).

70/15/15 自然时间 + 两个 ≥30 天隔离窗；同日同 split；split_lock 哈希冻结。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from data_factory.lineage.hashing import content_hash


def build_split_manifest(dates: pd.DatetimeIndex, *, train_fraction: float, validation_fraction: float, isolation_days: int) -> pd.DataFrame:
    unique = pd.DatetimeIndex(sorted(set(dates)))
    n = len(unique)
    if n < 10:
        raise ValueError(f"too few dates for splits: {n}")
    train_end = int(n * train_fraction)
    val_end = int(n * (train_fraction + validation_fraction))
    labels = []
    for i, date in enumerate(unique):
        if i < train_end:
            split = "train"
        elif i < val_end:
            split = "validation"
        else:
            split = "test"
        labels.append(split)
    # 隔离窗：train 末尾与 validation 开头各 isolation_days//2，validation/test 之间同
    half = isolation_days // 2
    for i in range(max(train_end - half, 0), min(train_end + half, n)):
        labels[i] = "isolation"
    for i in range(max(val_end - half, 0), min(val_end + half, n)):
        labels[i] = "isolation"
    manifest = pd.DataFrame({"date": unique, "split": labels})
    manifest["isolation_window"] = manifest["split"] == "isolation"
    return manifest


def run_lock_splits(config: dict[str, Any], *, out_dir: Path) -> dict[str, Any]:
    sim = config["simulation"]
    start = pd.Timestamp(sim["start_date"])
    end = pd.Timestamp(sim["end_date"])
    dates = pd.date_range(start, end, freq="D")
    splits_cfg = config["splits"]
    manifest = build_split_manifest(
        dates,
        train_fraction=float(splits_cfg["train_fraction"]),
        validation_fraction=float(splits_cfg["validation_fraction"]),
        isolation_days=int(splits_cfg["isolation_days"]),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "split_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    lock = {
        "date_start": str(start.date()),
        "date_end": str(end.date()),
        "train_fraction": splits_cfg["train_fraction"],
        "validation_fraction": splits_cfg["validation_fraction"],
        "isolation_days": splits_cfg["isolation_days"],
        "counts": manifest["split"].value_counts().to_dict(),
        "manifest_sha256": content_hash(manifest.to_csv(index=False)),
        "rule": "同日同 split；train/validation 与 validation/test 之间各 ≥30 天隔离窗；标准化/拟合/阈值/生成器只见 train",
    }
    lock_path = out_dir / "split_lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "completed",
        "command": "lock-splits",
        "rows_written": int(len(manifest)),
        "counts": lock["counts"],
        "manifest_sha256": lock["manifest_sha256"],
        "output": str(manifest_path),
        "manifest": str(lock_path),
    }


def load_split_lock(out_dir: Path) -> dict[str, Any]:
    return json.loads((Path(out_dir) / "split_lock.json").read_text(encoding="utf-8"))
