"""入湖河流负荷静态档案（江苏省控断面）契约测试。

数据档案：backend/app/data/inflow_rivers_monthly.json
（392 行 = 7 断面 × 56 个月，2022-01 ~ 2026-08，参数零缺失——
 这些完整性事实本身即验收门槛，防止档案被静默截断或改写口径。）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "inflow_rivers_monthly.json"
)
# 三口径（数据文件字段 / 成功信封 / 错误信封）统一的档案版本；静态档案
# 不得借用观察轨 DEMO-OBS-V1 标注。文件内版本若变更，此处必须同步更新。
DATASET_VERSION = "JIANGSU_INFLOW_RIVERS_V1_20260913"
EXPECTED_SECTIONS = [
    "大溪港",
    "陈东桥",
    "官渎桥",
    "洪巷桥",
    "社渎港桥",
    "湖山桥",
    "分水（黄埝桥）",
]
EXPECTED_CLASS_COUNTS = {"Ⅱ": 128, "Ⅲ": 223, "Ⅳ": 37, "Ⅴ": 4}
PARAM_FIELDS = ("temp_c", "ph", "do", "codmn", "cod", "bod5", "nh3n", "tp")


# ---- 静态档案文件本身的完整性 ----


def test_dataset_file_completeness() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    records = payload["records"]
    assert len(records) == 392
    # 文件侧版本口径与代码常量逐字一致（防止档案版本静默漂移）
    assert payload["dataset_version"] == DATASET_VERSION
    assert payload["start_month"] == "2022-01"
    assert payload["end_month"] == "2026-08"
    assert payload["month_count"] == 56
    # 每月 7 断面齐全
    per_month: dict[str, int] = {}
    for r in records:
        per_month[r["ym"]] = per_month.get(r["ym"], 0) + 1
    assert set(per_month.values()) == {7}
    # 参数零缺失
    for r in records:
        for field in PARAM_FIELDS:
            assert r[field] is not None, f"{r['section']} {r['ym']} {field} 缺失"
    # 水质类别取值域
    assert {r["wq_class"] for r in records} <= set(EXPECTED_CLASS_COUNTS)


# ---- GET /inflow/rivers/summary ----


def test_inflow_summary_envelope_and_counts() -> None:
    resp = client.get("/api/v1/inflow/rivers/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["meta"]["dataset_version"] == DATASET_VERSION
    data = body["data"]
    assert data["as_of"] == "2026-08"
    # 信封版本与档案数据体内部版本必须同口径（诚实披露红线）
    assert data["dataset_version"] == DATASET_VERSION
    assert data["record_count"] == 392
    assert [s["section"] for s in data["sections"]] == EXPECTED_SECTIONS
    assert data["overall_class_counts"] == EXPECTED_CLASS_COUNTS
    assert data["iv_plus_count"] == 41


def test_inflow_summary_latest_and_mean_values() -> None:
    data = client.get("/api/v1/inflow/rivers/summary").json()["data"]
    by_name = {s["section"]: s for s in data["sections"]}
    # 抽查两个端点断面（与原始 xlsx 逐值核对）
    daxigang = by_name["大溪港"]
    assert daxigang["latest"] == {"ym": "2026-08", "wq_class": "Ⅱ", "tp": 0.044, "nh3n": 0.07}
    assert daxigang["record_count"] == 56
    fenshui = by_name["分水（黄埝桥）"]
    assert fenshui["latest"]["tp"] == 0.172
    assert fenshui["latest"]["wq_class"] == "Ⅲ"
    # 统计为直接聚合：大溪港全期无 Ⅳ 类及以上
    assert daxigang["iv_plus_count"] == 0
    assert sum(s["record_count"] for s in data["sections"]) == 392


# ---- GET /inflow/rivers/monthly ----


def test_inflow_monthly_full_and_filtered() -> None:
    resp = client.get("/api/v1/inflow/rivers/monthly")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["dataset_version"] == DATASET_VERSION
    data = body["data"]
    assert data["count"] == 392
    assert data["meta"]["month_count"] == 56
    # 信封版本与 monthly 数据体内部 meta 版本同口径
    assert data["meta"]["dataset_version"] == DATASET_VERSION

    resp = client.get("/api/v1/inflow/rivers/monthly", params={"section": "陈东桥"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 56
    assert {r["section"] for r in data["records"]} == {"陈东桥"}


def test_inflow_monthly_empty_section_treated_as_absent() -> None:
    """空字符串 section 与未提供等价：返回全量，而非 404 或空集。"""
    resp = client.get("/api/v1/inflow/rivers/monthly", params={"section": ""})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 392
    assert data["meta"]["month_count"] == 56


def test_inflow_monthly_unknown_section_returns_404() -> None:
    resp = client.get("/api/v1/inflow/rivers/monthly", params={"section": "不存在"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 404
    assert "断面" in body["message"]
    # 错误信封同样使用档案版本口径（不得退回观察轨版本）
    assert body["meta"]["dataset_version"] == DATASET_VERSION


# ---- 模块层：未知断面在函数层也必须显式抛错（禁止静默空集） ----


def test_inflow_module_monthly_rejects_unknown_section() -> None:
    from backend.app import inflow

    with pytest.raises(KeyError):
        inflow.monthly("不存在")


# ---- mean_last12 空集契约：最近12个月值全缺失时输出 null，禁止伪装 0.0 ----


def _fake_dataset_with_gaps() -> dict:
    """构造带缺失窗口的档案：tp 在最近12个月全 None，nh3n 部分缺失。

    真实官方档案零缺失，此用例锁定「若未来档案出现缺测窗口」时的序列化契约
    （JSON null），防止 max(1, count) 一类写法把空集均值静默算成 0.0。
    """
    records = []
    # 第 1 个月在 last12 窗口之外且 tp 有值，确保窗口切片本身正确
    records.append(
        {"section": "缺测断面", "ym": "2025-12", "wq_class": "Ⅲ", "tp": 0.5, "nh3n": 0.5}
    )
    for i in range(1, 13):  # 2026-01 ~ 2026-12：进入 last12 窗口
        records.append(
            {
                "section": "缺测断面",
                "ym": f"2026-{i:02d}",
                "wq_class": "Ⅳ" if i <= 6 else "Ⅲ",
                "tp": None,  # 窗口内 tp 全缺测
                "nh3n": 0.2 if i % 2 == 0 else None,  # 部分缺测
            }
        )
    return {
        "dataset_version": "TEST-GAP",
        "description": "缺测窗口测试档案",
        "source": "测试构造",
        "cadence": "monthly",
        "start_month": "2025-12",
        "end_month": "2026-12",
        "month_count": 13,
        "sections": [{"section": "缺测断面", "water": "缺测断面", "city": "测试市"}],
        "parameters": {"tp": "总磷(mg/L)", "nh3n": "氨氮(mg/L)"},
        "records": records,
    }


def test_inflow_summary_mean_last12_null_when_window_all_missing(monkeypatch) -> None:
    from backend.app import inflow

    monkeypatch.setattr(inflow, "_dataset", _fake_dataset_with_gaps)
    resp = client.get("/api/v1/inflow/rivers/summary")
    assert resp.status_code == 200
    section = resp.json()["data"]["sections"][0]
    # tp 窗口内全缺失 → JSON null（is None），绝不允许是 0.0
    assert section["mean_last12"]["tp"] is None
    assert section["mean_last12"]["tp"] != 0.0
    # nh3n 部分缺失 → 对既有记录直接聚合
    assert section["mean_last12"]["nh3n"] == pytest.approx(0.2)
    # 缺失不影响类别统计与最新月序列化
    assert section["latest"]["ym"] == "2026-12"
    assert section["class_counts"] == {"Ⅲ": 7, "Ⅳ": 6}
    assert section["iv_plus_count"] == 6
