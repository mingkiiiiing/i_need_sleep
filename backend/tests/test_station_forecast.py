"""站点级机理+AI 融合预测（station_forecast）单元与 API 契约测试。

单元部分用合成 catalog（确定性正弦场景：叶绿素a = 30 + 10·sin(2π·t/24h) + 低幅噪声，
小时步长）——该场景下持续性基线天然弱势（逐时相位漂移），岭回归可学到日内周期，
用于验证引擎结构、诚实门槛（样本量/基线）与降级路径，不依赖真实数据分布。

API 部分沿用既有实时轨契约测试约定：断言与 catalog 一致的结构事实，不断言具体数值。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import station_forecast as sf
from backend.app.providers import MeeRealtimeObservationProvider

VARIABLES_OK = (
    "chlorophyll_a", "cyanobacteria_density", "water_temperature", "total_phosphorus",
    "total_nitrogen", "ammonia_nitrogen", "dissolved_oxygen", "pH", "turbidity",
    "conductivity", "cod_mn",
)


def _write_catalog(catalog_dir, observations: pd.DataFrame, station_ids: list[str], snapshot_id: str) -> None:
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "stations.json").write_text(json.dumps({
        "source_id": "mee_surface_water_realtime",
        "generated_at_utc": "2026-09-06T00:00:00Z",
        "station_count": len(station_ids),
        "stations": [
            {"entity_id": sid, "source_id": "mee_surface_water_realtime", "source_station_name": sid,
             "normalized_station_name": sid, "province": "江苏省", "basin": "太湖流域",
             "first_seen_at": "2026-09-01T00:00:00Z", "last_seen_at": "2026-09-06T00:00:00Z",
             "latest_observed_at": "2026-09-06T08:00:00+08:00", "latest_snapshot_id": snapshot_id,
             "latest_water_quality_level": 3, "active_in_latest_snapshot": True, "aliases": [],
             "location": {"lon": 120.2, "lat": 31.3, "location_status": "verified",
                          "registry_source": "test", "coord_source": "test"}}
            for sid in station_ids
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (catalog_dir / "snapshots.json").write_text(json.dumps({
        "source_id": "mee_surface_water_realtime", "snapshot_count": 1,
        "snapshots": [{"snapshot_id": snapshot_id, "retrieved_at_utc": "2026-09-06T00:00:00Z",
                       "declared_record_count": len(observations), "station_stats": []}],
    }, ensure_ascii=False), encoding="utf-8")
    (catalog_dir / "status.json").write_text(json.dumps({
        "source": "mee_surface_water_realtime", "as_of": "2026-09-06T00:00:00Z",
        "collection_status": "completed", "snapshot_count": 1,
        "latest_snapshot_id": snapshot_id, "latest_station_count": len(station_ids),
        "active_station_count": len(station_ids), "latest_observed_at": "2026-09-06T08:00:00+08:00",
    }, ensure_ascii=False), encoding="utf-8")
    observations.to_parquet(catalog_dir / "observations.parquet", index=False)


def _synthetic_observations(station_ids: list[str], *, with_chla: bool = True) -> pd.DataFrame:
    """6 天小时步长：chla = 30 + 10·sin(日周期) + N(0,1)；其余变量取平滑常值。"""
    rng = np.random.default_rng(42)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    hours = [start + timedelta(hours=h) for h in range(24 * 6)]
    rows = []
    for sid in station_ids:
        for t in hours:
            ts_iso = t.isoformat().replace("+00:00", "+00:00")
            chla = 30.0 + 10.0 * np.sin(2 * np.pi * t.hour / 24) + float(rng.normal(0, 1))
            for code in VARIABLES_OK:
                if code == "chlorophyll_a":
                    if not with_chla:
                        rows.append(_row(sid, snapshot_id_of(t), ts_iso, code, None, "missing", "upstream_missing"))
                        continue
                    value, status, reason = round(chla, 3), "ok", None
                elif code == "water_temperature":
                    value, status, reason = 26.0 + 3.0 * np.sin(2 * np.pi * t.hour / 24), "ok", None
                elif code == "cyanobacteria_density":
                    value, status, reason = 180.0, "ok", None
                else:
                    value, status, reason = {"total_phosphorus": 0.12, "total_nitrogen": 1.1,
                                             "ammonia_nitrogen": 0.18, "dissolved_oxygen": 7.2,
                                             "pH": 8.3, "turbidity": 28.0, "conductivity": 410.0,
                                             "cod_mn": 4.2}[code], "ok", None
                rows.append(_row(sid, snapshot_id_of(t), ts_iso, code, value, status, reason))
    return pd.DataFrame(rows)


def snapshot_id_of(_) -> str:
    return "mee_surface_water_realtime_test_20260906T000000Z"


def _row(sid, snapshot_id, ts_iso, code, value, status, reason):
    return {"station_entity_id": sid, "snapshot_id": snapshot_id, "observed_at": ts_iso,
            "retrieved_at": "2026-09-06T00:00:00Z", "variable_code": code, "value": value,
            "unit": "test", "observation_status": status, "missing_reason": reason,
            "source_quality_note": None, "qc_status": "pass" if status == "ok" else "not_applicable",
            "evidence_level": "official_station_observation", "verification_state": "not_cross_validated",
            "is_ground_truth": False}


@pytest.fixture()
def synthetic_provider(tmp_path, monkeypatch):
    catalog = tmp_path / "mee_realtime"
    stations = ["mee-test-a", "mee-test-b"]
    frame = _synthetic_observations(stations)
    # mee-test-b 无叶绿素a 序列：用于"站点级预测不覆盖"的降级路径
    frame = frame[~((frame["station_entity_id"] == "mee-test-b") & (frame["variable_code"] == "chlorophyll_a"))]
    _write_catalog(catalog, frame, stations, snapshot_id_of(None))
    return MeeRealtimeObservationProvider(catalog)


def test_engine_serves_forecast_with_honest_disclosure(synthetic_provider):
    engine = sf.StationForecastEngine(synthetic_provider)
    card = engine.forecast("mee-test-a")["model_card"]
    data = engine.forecast("mee-test-a")

    assert data["station_id"] == "mee-test-a"
    assert data["forecasts"], "正弦场景下 T+1 应通过门槛"
    first = data["forecasts"][0]
    assert first["horizon_days"] == 1
    chla = first["chlorophyll_a"]
    assert chla["lower_bound"] <= chla["value"] <= chla["upper_bound"]
    assert first["band"] in {"none", "light", "moderate"}
    assert first["band_label"] == sf.BAND_LABELS[first["band"]]
    assert 0 <= first["risk_score"] <= 100
    assert first["mechanism"]["excluded_inputs"], "机理模块必须披露无观测输入的剔除项"
    assert first["drivers"], "必须返回线性归因驱动因子"
    assert all(d["method"] == "linear_model_attribution" for d in first["drivers"])

    # 诚实披露：模型卡携带评估指标与边界声明；归因不得声称是 SHAP（免责说明除外）
    assert card["claim_boundary"] == sf.CLAIM_BOUNDARY
    assert card["training"]["stations"] == 1
    assert card["served_horizons_days"]
    evaluation = first["evaluation"]
    assert evaluation["mae_ugl"] <= evaluation["mae_persistence_ugl"], "服务的提前期必须不劣于持续性基线"
    claimed_methods = {d["method"] for d in first["drivers"]} | {card["fusion"].lower()}
    assert not any("shap" in method for method in claimed_methods)
    assert "非 SHAP" in " ".join(card["notes"])


def test_engine_blocks_station_without_chla(synthetic_provider):
    engine = sf.StationForecastEngine(synthetic_provider)
    with pytest.raises(sf.StationForecastNotAvailable):
        engine.forecast("mee-test-b")


def test_engine_blocks_all_horizons_when_sample_gate_raised(synthetic_provider, monkeypatch):
    monkeypatch.setattr(sf, "MIN_SAMPLES_PER_HORIZON", 10_000)
    engine = sf.StationForecastEngine(synthetic_provider)
    with pytest.raises(sf.StationForecastNotAvailable) as excinfo:
        engine.forecast("mee-test-a")
    assert "门槛" in str(excinfo.value)


def test_engine_blocks_when_model_has_no_skill(synthetic_provider, monkeypatch):
    """把持续性基线替换为逐样本精确值 → 模型必然"劣于基线" → 门槛拦截。"""
    engine = sf.StationForecastEngine(synthetic_provider)
    original_cv = sf.StationForecastEngine._blocked_cv

    def perfect_baseline(self, X, y_log, valid):
        summary, residuals = original_cv(self, X, y_log, valid)
        summary["mae_persistence_ugl"] = 0.0
        return summary, residuals

    monkeypatch.setattr(sf.StationForecastEngine, "_blocked_cv", perfect_baseline)
    with pytest.raises(sf.StationForecastNotAvailable):
        engine.forecast("mee-test-a")


def test_engine_rebuilds_on_catalog_signature_change(synthetic_provider, tmp_path):
    engine = sf.StationForecastEngine(synthetic_provider)
    engine.forecast("mee-test-a")
    assert engine._built

    # 订正观测值并发布新快照（status.json 变化 → 签名变化 → 重建）
    catalog_dir = synthetic_provider._catalog_dir
    frame = pd.read_parquet(catalog_dir / "observations.parquet")
    frame.loc[frame["variable_code"] == "chlorophyll_a", "value"] = 55.0
    frame["snapshot_id"] = "mee_surface_water_realtime_test_20260907T000000Z"
    _write_catalog(catalog_dir, frame, ["mee-test-a", "mee-test-b"], "mee_surface_water_realtime_test_20260907T000000Z")

    data = engine.forecast("mee-test-a")
    assert data["forecasts"][0]["chlorophyll_a"]["value"] > 40.0, "签名变化后必须按新数据重建"


def test_engine_unavailable_without_chla_anywhere(tmp_path):
    catalog = tmp_path / "mee_realtime"
    stations = ["mee-test-b"]
    _write_catalog(catalog, _synthetic_observations(stations, with_chla=False), stations, snapshot_id_of(None))
    engine = sf.StationForecastEngine(MeeRealtimeObservationProvider(catalog))
    with pytest.raises(sf.StationForecastNotAvailable):
        engine.forecast("mee-test-b")
    status = engine.status()
    assert status["status"] == "unavailable"
    assert status["reason"]


# ---------- API 契约（真实 catalog；约定同 test_realtime_observed_contract） ----------


def _covered_station_ids() -> set[str]:
    from backend.app.services import service, station_forecast_engine

    engine = station_forecast_engine(service.realtime)
    engine._ensure_built()
    return set(engine._table["sid"])


def test_station_forecast_api_contract():
    from backend.main import app

    client = TestClient(app)
    covered = _covered_station_ids()
    station_id = sorted(covered)[0]
    body = client.get(f"/api/v1/realtime/stations/{station_id}/forecast").json()
    assert body["code"] == 200
    meta = body["meta"]
    assert meta["data_mode"] == "observed"
    assert meta["claim_boundary"] == "official_observation_not_cross_validated"
    data = body["data"]
    assert data["station_id"] == station_id
    assert data["model_card"]["model_version"] == "MHW-STATION-FC-V0.1"
    assert data["forecasts"]
    for forecast in data["forecasts"]:
        assert forecast["horizon_days"] in data["model_card"]["served_horizons_days"]
        assert "chlorophyll_a" in forecast and "drivers" in forecast


def test_station_forecast_api_uncovered_station_409():
    from backend.main import app

    client = TestClient(app)
    covered = _covered_station_ids()
    stations = client.get(
        "/api/v1/spatial-entities", params={"mode": "observed", "active": "latest"}
    ).json()["data"]
    uncovered = next(s["id"] for s in stations if s["id"] not in covered)
    response = client.get(f"/api/v1/realtime/stations/{uncovered}/forecast")
    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["code"] == "FORECAST_NOT_AVAILABLE"
    assert body["meta"]["data_mode"] == "observed"


def test_station_forecast_api_unknown_station_404():
    from backend.main import app

    client = TestClient(app)
    response = client.get("/api/v1/realtime/stations/mee-does-not-exist/forecast")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "ENTITY_NOT_FOUND"


def test_station_forecast_status_endpoint():
    from backend.main import app

    client = TestClient(app)
    body = client.get("/api/v1/realtime/forecast/status").json()
    assert body["code"] == 200
    data = body["data"]
    assert data["status"] in {"pilot_v0.1", "unavailable", "not_configured"}
    if data["status"] == "pilot_v0.1":
        assert data["served_horizons_days"]
        assert data["covered_stations"] >= 1
