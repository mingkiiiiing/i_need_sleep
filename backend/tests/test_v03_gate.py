"""V0.3 10% 门禁：实时生成、无硬编码比较数、N.A. 如实披露。"""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.algorithm_models import V3_PACKAGE_DIR
from backend.model_runtime_v0_3.code.modeling_real.gate import build_gate_table

GATE_MIN_TEST_ROWS = 15


def _stored_gate() -> dict:
    path = V3_PACKAGE_DIR / "evaluation" / "gate_table.json"
    assert path.is_file(), "gate_table.json 缺失：请先运行 cli_real.py gate"
    return json.loads(path.read_text(encoding="utf-8"))


def test_gate_table_is_regenerable_without_hardcoded_numbers():
    stored = _stored_gate()
    rebuilt = build_gate_table(V3_PACKAGE_DIR / "runs")
    # 汇总必须可由 runs/ 目录实时重建（无硬编码比较数）
    assert rebuilt["summary"] == stored["summary"]
    assert rebuilt["rows"] == stored["rows"]


def test_gate_rows_disclose_na_for_small_test_sets():
    gate = _stored_gate()
    rows = gate["rows"]
    assert rows, "门禁表不应为空"
    for row in rows:
        if row["n_test"] < GATE_MIN_TEST_ROWS:
            assert row["status"] == "NA", f"{row['task_id']}/{row['variant']} 应为 NA"
            assert row["na_reason"]
            assert row["uplift"] is None
    summary = gate["summary"]
    assert summary["comparison_rows"] == len(rows)
    assert summary["evaluable_comparisons"] == (
        summary["pass"] + summary["fail"]
    )
    assert summary["not_applicable"] == len(rows) - summary["evaluable_comparisons"]
    assert summary["status"] in {"PASS", "FAIL", "NOT_APPLICABLE"}


def test_gate_honesty_note_present():
    gate = _stored_gate()
    assert gate.get("honesty_note")
    assert gate["min_test_rows"] == GATE_MIN_TEST_ROWS
