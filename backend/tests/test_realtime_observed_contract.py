"""实时观测轨（observed）API 契约测试（大任务 1 验收）。

原则：断言"API 与站点目录一致"，不断言具体站点数（79→81 自动变化）；
observed 与 simulated 双轨隔离；缺测显式；is_ground_truth 恒 False。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

REALTIME_META = {"data_mode": "observed", "claim_boundary": "official_observation_not_cross_validated"}
LOCATION_STATUSES = {"verified", "metadata_only", "suspicious", "missing"}
VARIABLES_PER_STATION = 11


def _observed_meta(body: dict) -> dict:
    meta = body["meta"]
    for key, value in REALTIME_META.items():
        assert meta[key] == value, f"meta.{key}={meta[key]!r}, expected {value!r}"
    assert meta["dataset_version"] == "MEE-RT-V1"
    assert meta["as_of"], "observed meta.as_of 必须来自实时数据"
    return meta


def test_realtime_status_reports_honest_state():
    body = client.get("/api/v1/realtime/status").json()
    assert body["code"] == 200
    _observed_meta(body)
    data = body["data"]
    assert data["source"] == "mee_surface_water_realtime"
    assert data["available"] is True
    assert data["latest_station_count"] >= 1
    assert data["freshness_status"] in {"normal", "delayed", "severely_overdue", "unavailable"}
    assert data["observed_lag_h"] is not None


def test_station_list_matches_snapshot_exactly():
    status = client.get("/api/v1/realtime/status").json()["data"]
    response = client.get("/api/v1/spatial-entities", params={"mode": "observed", "active": "latest"})
    body = response.json()
    assert response.status_code == 200
    _observed_meta(body)
    stations = body["data"]
    # 验收门槛：活跃站点数与最新快照唯一站点数完全一致（79→81 自动变化）
    assert len(stations) == status["active_station_count"] == status["latest_station_count"]
    assert len({item["id"] for item in stations}) == len(stations), "entity_id 必须唯一"
    for item in stations:
        assert item["entity_type"] == "monitoring_station"
        assert item["id"].startswith("mee-")
        assert item["source_station_name"], "站名必须保留"
        assert item["location"]["location_status"] in LOCATION_STATUSES
        assert item["available_variable_count"] + item["missing_variable_count"] + item["qc_rejected_variable_count"] == VARIABLES_PER_STATION
        assert item["data_mode"] == "observed"


def test_station_list_filters():
    all_stations = client.get("/api/v1/spatial-entities", params={"mode": "observed"}).json()["data"]
    jiangsu = client.get("/api/v1/spatial-entities", params={"mode": "observed", "province": "江苏省"}).json()["data"]
    assert 0 < len(jiangsu) < len(all_stations)
    assert all(item["province"] == "江苏省" for item in jiangsu)
    missing_loc = client.get(
        "/api/v1/spatial-entities", params={"mode": "observed", "location_status": "missing"}
    ).json()["data"]
    assert missing_loc, "当前注册表必有坐标缺失站"
    assert all(item["location"]["location_status"] == "missing" for item in missing_loc)
    assert all(item["location"]["lon"] is None and item["location"]["lat"] is None for item in missing_loc)


def test_station_detail_and_latest_observations_complete():
    stations = client.get("/api/v1/spatial-entities", params={"mode": "observed"}).json()["data"]
    target = next(item for item in stations if item["available_variable_count"] > 0)
    detail = client.get(f"/api/v1/spatial-entities/{target['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == target["id"]

    obs_body = client.get(f"/api/v1/spatial-entities/{target['id']}/observations", params={"window": "latest"}).json()
    _observed_meta(obs_body)
    rows = obs_body["data"]
    assert len(rows) == VARIABLES_PER_STATION, "每站每快照固定 11 个指标状态，缺测不省略"
    codes = {row["variable_code"] for row in rows}
    assert {"chlorophyll_a", "cyanobacteria_density", "total_phosphorus", "total_nitrogen"} <= codes
    for row in rows:
        assert row["station_entity_id"] == target["id"]
        assert row["observation_status"] in {"ok", "missing", "qc_rejected", "parse_failed"}
        assert row["evidence_level"] == "official_station_observation"
        assert row["verification_state"] == "not_cross_validated"
        assert row["is_ground_truth"] is False, "未经跨源验证不得标真值"
        if row["observation_status"] == "missing":
            assert row["value"] is None and row["missing_reason"] == "upstream_missing"
            assert row["qc_status"] == "not_applicable"
        if row["observation_status"] == "ok":
            assert row["value"] is not None and row["qc_status"] == "pass"
    assert counts_match(rows, target)


def counts_match(rows: list[dict], target: dict) -> bool:
    ok = sum(1 for r in rows if r["observation_status"] == "ok")
    missing = sum(1 for r in rows if r["observation_status"] in ("missing", "parse_failed"))
    rejected = sum(1 for r in rows if r["observation_status"] == "qc_rejected")
    return (
        ok == target["available_variable_count"]
        and missing == target["missing_variable_count"]
        and rejected == target["qc_rejected_variable_count"]
    )


def test_observations_range_window_and_validation():
    stations = client.get("/api/v1/spatial-entities", params={"mode": "observed"}).json()["data"]
    target = stations[0]["id"]
    ranged = client.get(
        f"/api/v1/spatial-entities/{target}/observations",
        params={"window": "range", "start": "2026-09-04", "end": "2026-09-06"},
    )
    assert ranged.status_code == 200
    latest_count = len(
        client.get(f"/api/v1/spatial-entities/{target}/observations", params={"window": "latest"}).json()["data"]
    )
    assert len(ranged.json()["data"]) >= latest_count

    missing_end = client.get(
        f"/api/v1/spatial-entities/{target}/observations",
        params={"window": "range", "start": "2026-09-04"},
    )
    assert missing_end.status_code == 422
    assert missing_end.json()["errors"][0]["code"] == "INVALID_DATE_RANGE"

    reversed_range = client.get(
        f"/api/v1/spatial-entities/{target}/observations",
        params={"window": "range", "start": "2026-09-06", "end": "2026-09-04"},
    )
    assert reversed_range.status_code == 422

    variable_filtered = client.get(
        f"/api/v1/spatial-entities/{target}/observations",
        params={"window": "latest", "variables": "total_phosphorus,total_nitrogen"},
    ).json()["data"]
    assert {row["variable_code"] for row in variable_filtered} == {"total_phosphorus", "total_nitrogen"}


def test_station_quality_is_honest():
    stations = client.get("/api/v1/spatial-entities", params={"mode": "observed"}).json()["data"]
    target = next(item for item in stations if item["location"]["location_status"] == "missing")
    body = client.get(f"/api/v1/spatial-entities/{target['id']}/quality").json()
    assert body["code"] == 200
    _observed_meta(body)
    quality = body["data"]
    assert quality["is_ground_truth"] is False
    assert quality["verification_state"] == "not_cross_validated"
    assert quality["suitability"]["model_use"] is False, "未经跨源验证不得进入模型真值"
    assert quality["variable_coverage"]["total"] == VARIABLES_PER_STATION
    assert any("不得生成地图点位" in item for item in quality["limitations"])
    assert quality["status"] in {"normal", "delayed", "severely_overdue", "unavailable"}


def test_unknown_realtime_entity_returns_404():
    response = client.get("/api/v1/spatial-entities/mee-00000000/observations")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "ENTITY_NOT_FOUND"


def test_simulated_track_untouched():
    """双轨隔离：默认 simulated 行为与信封不变。"""
    body = client.get("/api/v1/spatial-entities").json()
    assert body["meta"]["data_mode"] == "simulated"
    assert body["meta"]["claim_boundary"] == "simulation_only"
    assert all(item["entity_type"] == "demo_zone" for item in body["data"])
    demo_id = body["data"][0]["id"]
    demo_obs = client.get(f"/api/v1/spatial-entities/{demo_id}/observations").json()
    assert demo_obs["meta"]["data_mode"] == "simulated"
    assert all(row["value_origin"] == "simulated" for row in demo_obs["data"])


def test_capabilities_disclose_realtime_track():
    caps = client.get("/api/v1/system/capabilities").json()["data"]["capabilities"]
    assert caps["realtime_observation"] in {"observed_track_available", "observed_track_no_data", "not_configured"}


def test_realtime_summary_lake_aggregates():
    """全湖汇总：类别分布/达标率/预警/健康分/地图点位全部由 observed 数据计算。"""
    body = client.get("/api/v1/realtime/summary").json()
    assert body["code"] == 200
    _observed_meta(body)
    data = body["data"]
    status = client.get("/api/v1/realtime/status").json()["data"]
    assert data["station_total"] == status["active_station_count"]
    # 类别分布与达标率口径一致（达标 = 上游类别 ≤ III）
    assert sum(data["class_counts"].values()) == data["class_total"]
    assert data["class_compliance"]["num"] <= data["class_compliance"]["den"]
    assert abs(data["class_iii_rate"] - data["class_compliance"]["num"] / data["class_compliance"]["den"]) < 1e-3
    # 预警条目落在筛查阈值语义内，且与点位同源
    for w in data["warnings"]:
        assert w["chla"] >= data["warning_thresholds"]["light"]
        assert w["band"] in ("light", "moderate")
    # 健康分透明加权且在 [0,100]
    assert 0 <= data["health"]["score"] <= 100
    assert data["health"]["definition"]
    subs = data["health"]["subscores"]
    assert set(subs) == {"class_compliance", "algae_normal", "completeness"}
    # 地图点位仅含 verified/metadata_only（与 /spatial-entities 地图规则一致）
    assert all(m["location_status"] in ("verified", "metadata_only") for m in data["markers"])
    assert all(m["lon"] is not None and m["lat"] is not None for m in data["markers"])


def test_realtime_timeline_and_historical_replay():
    """快照时间轴 + 历史快照回放：回放口径与最新隔离（freshness=historical）。"""
    timeline = client.get("/api/v1/realtime/timeline").json()["data"]
    assert timeline["latest_snapshot_id"]
    assert len(timeline["snapshots"]) >= 2
    first = timeline["snapshots"][0]
    assert first["class_compliance"]["den"] >= 1
    assert 0 <= first["warning_count"]

    replay = client.get(f"/api/v1/realtime/summary?snapshot={first['snapshot_id']}").json()
    assert replay["code"] == 200
    data = replay["data"]
    assert data["selected_snapshot_id"] == first["snapshot_id"]
    assert data["is_latest"] is False
    assert data["freshness_status"] == "historical"
    # 回放快照的达标口径与 timeline 一致
    assert data["class_compliance"] == first["class_compliance"]
    assert data["latest_snapshot_id"] == timeline["latest_snapshot_id"]

    missing = client.get("/api/v1/realtime/summary?snapshot=mee_surface_water_realtime_19990101T000000Z")
    assert missing.status_code == 404
    assert missing.json()["errors"][0]["code"] == "ENTITY_NOT_FOUND"
