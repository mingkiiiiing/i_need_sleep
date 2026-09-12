# -*- coding: utf-8 -*-
"""interval_audit 共用工具：只读加载 manifest / runs / models，不做任何写回。

铁律：本目录只新建文件；对既有文件一律只读（joblib.load 只读打开）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]  # model_runtime_v0_3/（interval_audit -> code -> v0_3）
BACKEND = PKG_ROOT.parent
VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe"
CODE_DIR = PKG_ROOT / "code"
OUT_DIR = Path(__file__).resolve().parent

ACCEPT_LINE = 0.88  # 验收线 = coverage_target 0.90 - 容差 0.02


def _ensure_modeling_importable() -> None:
    """把 code/ 目录挂到 sys.path，使 joblib 反序列化能找到 modeling_real 包。

    只改进程内 sys.path，不改任何文件。
    """
    s = str(CODE_DIR)
    if s not in sys.path:
        sys.path.insert(0, s)


def load_manifest() -> dict:
    return json.loads((PKG_ROOT / "manifest.json").read_text(encoding="utf-8"))


def load_gate_table() -> dict:
    return json.loads((PKG_ROOT / "evaluation" / "gate_table.json").read_text(encoding="utf-8"))


def list_run_dirs() -> list[str]:
    runs = PKG_ROOT / "runs"
    return sorted(p.name for p in runs.iterdir() if p.is_dir())


def read_run_json(run: str, name: str):
    p = PKG_ROOT / "runs" / run / name
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def read_run_predictions(run: str):
    """读 test_predictions.csv（只读）。返回 (columns, rows[list[dict]])；缺失返回 (None, [])。"""
    import csv

    p = PKG_ROOT / "runs" / run / "test_predictions.csv"
    if not p.is_file():
        return None, []
    with p.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames or [], list(r)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_bundle(rel_file: str):
    """只读加载 models/*.joblib；返回 bundle 或 (None, 错误说明)。"""
    path = PKG_ROOT / rel_file
    if not path.is_file():
        return None, f"file_missing:{rel_file}"
    try:
        _ensure_modeling_importable()
        import joblib

        return joblib.load(path), None
    except Exception as exc:  # noqa: BLE001
        return None, f"load_error:{type(exc).__name__}:{exc}"


def bundle_interval_facts(bundle) -> dict:
    """从 bundle 抽取 intervals 残差分位等价字段（结构自查，兼容 None）。"""
    if bundle is None:
        return {"available": False, "reason": "bundle_not_loaded"}
    iv = getattr(bundle, "intervals", None)
    if iv is None:
        return {"available": False, "reason": "intervals_is_none(ordinal_or_uncalibrated)"}
    d = getattr(iv, "__dict__", None) or {}
    p05 = d.get("residual_p05")
    p95 = d.get("residual_p95")
    width = None
    if p05 is not None and p95 is not None:
        width = float(p95) - float(p05)
    return {
        "available": True,
        "residual_p05": None if p05 is None else float(p05),
        "residual_p95": None if p95 is None else float(p95),
        "width_p95_minus_p05": width,
        "method": d.get("method"),
        "coverage_target": d.get("coverage_target"),
        "calibration_n": d.get("calibration_n"),
        "calibration_source": d.get("calibration_source"),
    }


def run_dir_name_rule(artifact: dict) -> str:
    """由 artifact 字段推导 run 目录命名（跨检规则，非权威）：

    {task_id}-{variant}-{horizon_days}d-{month_offset}m
      + ("-cv" 当 protocol == train_internal_time_block_cv_v1，frozen_split 无后缀)
    """
    suffix = "-cv" if artifact.get("protocol") == "train_internal_time_block_cv_v1" else ""
    return f"{artifact['task_id']}-{artifact['variant']}-{artifact['horizon_days']}d-{artifact['month_offset']}m{suffix}"


def fmt(x, nd=6):
    if x is None:
        return "NA"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)
