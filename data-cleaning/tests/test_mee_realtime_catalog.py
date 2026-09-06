"""MEE 实时站点三层结构（Snapshot→Station 目录→完整缺测观测）回归测试。

大任务 1 验收：站点集合由最新成功快照动态决定；别名归一；缺测显式落行；
location_status 分级；测试全部使用 tmp_path，禁止写正式 storage。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from data_factory.ingestion.mee_realtime_catalog import (
    SOURCE_ID,
    build_catalog,
    freshness_band,
    load_station_locations,
    normalize_station_name,
    station_entity_id,
)

NOW_UTC = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _snapshot_body(rows: list[list[str | int]], *, records: int = 82) -> dict:
    return {"result": 1, "total": 1, "records": records, "thead": [], "tbody": rows}


def _station_row(province: str, name: str, time_text: str, *, chla: str = "--", algae: str = "--", tn: str = "原始值：1.9") -> list[str | int]:
    return [province, "太湖流域", name, time_text, "3", "原始值：28.5", "原始值：7.3", "原始值：5.1",
            "原始值：410", "原始值：22", "原始值：4.3", "原始值：0.10", "原始值：0.15", tn, chla, algae]


def _write_snapshot(raw_root, stamp: str, body: dict) -> None:
    path = raw_root / "mee_surface_water_realtime" / "2026" / "09" / "06" / f"{SOURCE_ID}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


class TestNormalizeAndEntityId:
    def test_normalize_strips_annotation_and_fullwidth(self):
        assert normalize_station_name("卫八路桥（嘉兴金桥）") == "卫八路桥"
        assert normalize_station_name("新港口(新塘港) ") == "新港口"
        assert normalize_station_name("五里湖心") == "五里湖心"

    def test_entity_id_stable_and_scoped(self):
        first = station_entity_id("江苏省", "太湖流域", "五里湖心")
        assert first.startswith("mee-") and len(first) == len("mee-") + 8
        assert first == station_entity_id("江苏省", "太湖流域", "五里湖心")
        assert first != station_entity_id("上海市", "太湖流域", "五里湖心")
        assert first != station_entity_id("江苏省", "太湖流域", "拖山")


class TestLocationStatus:
    def _registry(self, tmp_path, stations: list[dict]):
        path = tmp_path / "stations.json"
        path.write_text(json.dumps({"stations": stations}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_shared_coordinates_marked_suspicious(self, tmp_path):
        registry = self._registry(tmp_path, [
            {"name": "甲", "lon": 120.1, "lat": 31.2},
            {"name": "乙", "lon": 120.1, "lat": 31.2},
            {"name": "丙", "lon": 120.3, "lat": 31.3},
            {"name": "丁"},
        ])
        locations = load_station_locations(registry)
        assert locations["甲"]["location_status"] == "suspicious"
        assert locations["乙"]["location_status"] == "suspicious"
        assert locations["丙"]["location_status"] == "metadata_only"
        assert locations["丁"]["location_status"] == "missing"

    def test_explicit_verified_wins(self, tmp_path):
        registry = self._registry(tmp_path, [
            {"name": "甲", "lon": 120.1, "lat": 31.2, "location_status": "verified"},
            {"name": "乙", "lon": 120.1, "lat": 31.2},
        ])
        locations = load_station_locations(registry)
        assert locations["甲"]["location_status"] == "verified"
        assert locations["乙"]["location_status"] == "suspicious"


class TestBuildCatalog:
    def _build(self, tmp_path, extra_registry: dict | None = None):
        raw_root = tmp_path / "raw"
        early = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
        late = datetime(2026, 9, 6, 11, 0, tzinfo=timezone.utc)
        # 早期快照：两站；拖山带括号别名；chla 有值
        _write_snapshot(raw_root, "20260904T140000Z", _snapshot_body([
            _station_row("江苏省", "拖山（无锡）", "09-04 20:00", chla="原始值：0.002"),
            _station_row("江苏省", "五里湖心", "09-04 20:00", tn="原始值：999.0"),
        ], records=90))
        # 最新快照：五里湖心消失（active=false），新站入列，拖山 chla 缺测
        _write_snapshot(raw_root, "20260906T110000Z", _snapshot_body([
            _station_row("江苏省", "拖山", "09-06 19:00"),
            _station_row("上海市", "淀峰", "09-06 19:00"),
        ], records=82))
        registry_path = None
        if extra_registry is not None:
            registry_path = tmp_path / "registry.json"
            registry_path.write_text(json.dumps({"stations": extra_registry}, ensure_ascii=False), encoding="utf-8")
        return build_catalog(
            raw_root=raw_root,
            out_dir=tmp_path / "catalog",
            registry_path=registry_path,
        )

    def test_station_set_follows_latest_snapshot(self, tmp_path):
        manifest = self._build(tmp_path)
        assert manifest["snapshot_count"] == 2
        catalog = json.loads((tmp_path / "catalog" / "stations.json").read_text(encoding="utf-8"))
        stations = {s["source_station_name"]: s for s in catalog["stations"]}
        assert catalog["station_count"] == 3
        assert stations["拖山"]["active_in_latest_snapshot"] is True
        assert stations["淀峰"]["active_in_latest_snapshot"] is True
        assert stations["五里湖心"]["active_in_latest_snapshot"] is False, "消失站点只标记不删除"

    def test_alias_variants_merge_into_one_entity(self, tmp_path):
        self._build(tmp_path)
        catalog = json.loads((tmp_path / "catalog" / "stations.json").read_text(encoding="utf-8"))
        tuoshan = [s for s in catalog["stations"] if normalize_station_name(s["source_station_name"]) == "拖山"]
        assert len(tuoshan) == 1, "括号别名必须合并为同一实体"
        assert set(tuoshan[0]["aliases"]) == {"拖山（无锡）", "拖山"}

    def test_missing_rows_are_explicit_and_truth_free(self, tmp_path):
        self._build(tmp_path)
        obs = pd.read_parquet(tmp_path / "catalog" / "observations.parquet")
        assert not obs["is_ground_truth"].any()
        assert set(obs["evidence_level"]) == {"official_station_observation"}
        assert set(obs["verification_state"]) == {"not_cross_validated"}
        # 每站每快照固定 11 行
        counts = obs.groupby(["station_entity_id", "snapshot_id"]).size()
        assert (counts == 11).all()
        # 最新快照拖山 chla/藻密度缺测 → missing + upstream_missing，不省略
        catalog = json.loads((tmp_path / "catalog" / "stations.json").read_text(encoding="utf-8"))
        tuoshan_id = next(s["entity_id"] for s in catalog["stations"] if s["source_station_name"] == "拖山")
        latest = obs[obs["snapshot_id"].str.endswith("20260906T110000Z")]
        tuoshan_missing = latest[
            (latest["station_entity_id"] == tuoshan_id)
            & (latest["variable_code"] == "chlorophyll_a")
            & (latest["observation_status"] == "missing")
        ]
        assert len(tuoshan_missing) == 1
        assert tuoshan_missing.iloc[0]["missing_reason"] == "upstream_missing"
        assert tuoshan_missing.iloc[0]["qc_status"] == "not_applicable"
        assert tuoshan_missing.iloc[0]["value"] is None or pd.isna(tuoshan_missing.iloc[0]["value"])
        # 越界值（TN=999）→ qc_rejected，不冒充 ok
        rejected = obs[obs["observation_status"] == "qc_rejected"]
        assert len(rejected) == 1 and rejected.iloc[0]["variable_code"] == "total_nitrogen"
        # 早期快照 chla 有值 → ok
        early_ok = obs[(obs["snapshot_id"].str.endswith("20260904T140000Z")) & (obs["variable_code"] == "chlorophyll_a")]
        assert (early_ok["observation_status"] == "ok").sum() == 1

    def test_location_status_from_registry(self, tmp_path):
        manifest = self._build(tmp_path, extra_registry=[
            {"name": "拖山", "lon": 120.2156, "lat": 31.3422, "registry_source": "taihugurad_stations_json"},
            {"name": "淀峰", "lon": 121.0, "lat": 31.0, "registry_source": "taihugurad_stations_json"},
        ])
        assert manifest["location_status_counts"]["metadata_only"] == 2
        assert manifest["location_status_counts"]["missing"] == 1  # 五里湖心未登记
        catalog = json.loads((tmp_path / "catalog" / "stations.json").read_text(encoding="utf-8"))
        tuoshan = next(s for s in catalog["stations"] if s["source_station_name"] == "拖山")
        assert tuoshan["location"]["lon"] == 120.2156

    def test_status_reports_freshness_and_error(self, tmp_path):
        self._build(tmp_path)
        status = json.loads((tmp_path / "catalog" / "status.json").read_text(encoding="utf-8"))
        assert status["source"] == SOURCE_ID
        assert status["latest_station_count"] == 2
        assert status["declared_record_count"] == 82
        assert status["collection_status"] == "unavailable"  # 无采集状态文件
        assert status["last_error_code"] is None

    def test_freshness_bands(self):
        assert freshness_band(0.4) == "normal"
        assert freshness_band(6.0) == "normal"
        assert freshness_band(6.1) == "delayed"
        assert freshness_band(12.0) == "delayed"
        assert freshness_band(12.1) == "severely_overdue"
        assert freshness_band(None) == "unavailable"
