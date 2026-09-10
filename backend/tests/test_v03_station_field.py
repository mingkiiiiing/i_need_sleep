"""快照站点场 / 全湖聚合层 / 驱动因素分布的合同测试（2026-09-11 口径统一）。

三条硬口径：
1. 地图站点场与结果面板同一 prediction_snapshot_id；覆盖分母 = 快照站点层总数，
   缺坐标/缺结果的站不悄悄消失，逐站给出排除原因。
2. 全湖汇总 = 站间分布聚合（中位数/四分位/风险站占比），不是"均值虚拟站点"。
3. 全湖驱动因素 = 站间机理分解分布（环境状态口径），不是单站条形卡。
"""
from types import SimpleNamespace

from app.prediction_snapshot import (
    CHLA_BLOOM_THRESHOLD_UG_L,
    PredictionSnapshotService,
)


class _CapableRealtime:
    """具备快照 ID 上报能力与站点目录（含坐标核验状态）的实时源。"""

    def status(self):
        return {"latest_snapshot_id": "mee_surface_water_realtime_test", "means": {}}

    def summary(self):
        return self.status()

    def station(self, entity_id):
        catalog = {
            "mee-a": {"source_station_name": "甲站", "location": {"lon": 120.1, "lat": 31.1, "location_status": "verified"}},
            "mee-b": {"source_station_name": "乙站", "location": {"lon": 120.2, "lat": 31.2, "location_status": "metadata_only"}},
            # 丙站坐标未通过核验：可画预测值但不可上图
            "mee-c": {"source_station_name": "丙站", "location": {"lon": None, "lat": None, "location_status": "missing"}},
        }
        return catalog.get(entity_id)

    def stations(self, active="latest"):
        return [{"id": eid} for eid in ("mee-a", "mee-b", "mee-c")]


def _result(value, origin="v0_3_real_bundle", unit=None):
    return {"value": value, "value_origin": origin, "unit": unit}


def _horizon_record(results):
    return {"results": results, "prediction_run_id": "RUN-1"}


def _published(service, live_id):
    lake = {
        "1": _horizon_record({
            "probability": _result(0.5),
            "chla": _result(3.0, unit="μg/L"),
            "biomass": _result(4.0),
        }),
        "30": _horizon_record({
            "probability": _result(0.2, origin="legacy_v0_2_synthetic_fallback"),
            "chla": _result(9.0, origin="legacy_v0_2_synthetic_fallback", unit="μg/L"),
        }),
    }
    stations = {
        "mee-a": {
            "1": {"results": {
                "probability": _result(0.4), "chla": _result(10.0, unit="μg/L"),
                "biomass": _result(2.0), "risk_level": {"value": "low"},
            }},
            "30": {"results": {"probability": _result(0.3, origin="legacy_v0_2_synthetic_fallback")}},
        },
        "mee-b": {
            "1": {"results": {
                "probability": _result(0.6), "chla": _result(25.0, unit="μg/L"),
                "biomass": _result(6.0), "risk_level": {"value": "medium"},
            }},
            "30": {"results": {"probability": _result(0.7, origin="legacy_v0_2_synthetic_fallback")}},
        },
        # 丙站缺 T+1 结果：覆盖口径里计入 total，不计入 with_prediction
        "mee-c": {
            "30": {"results": {"probability": _result(0.1, origin="legacy_v0_2_synthetic_fallback")}},
        },
    }
    service._published = {
        "id": live_id,
        "key": {"source_snapshot_id": "mee_surface_water_realtime_test"},
        "manifest": {"responsiveness": {}},
        "common": {},
        "lake": lake,
        "stations": stations,
    }
    service._state = "ready"
    service._stations_total = 3
    service._stations_done = 2
    service._stations_ready = False


def _service():
    algorithm = SimpleNamespace(realtime=_CapableRealtime())
    return PredictionSnapshotService(algorithm, _CapableRealtime(), cache_dir="__nonexistent__")


def test_station_field_serves_snapshot_points_with_exclusion_reasons():
    service = _service()
    _published(service, service._current_live_prediction_id())
    field = service.station_field(1, "risk")
    assert field is not None
    assert field["metric"] == "risk" and field["result_key"] == "probability"
    assert field["value_origin"] == "v0_3_real_bundle"
    # 3 站在快照、2 站有结果、1 站缺可信坐标不可上图
    assert field["coverage"] == {"total": 3, "with_prediction": 2, "plottable": 2}
    assert len(field["points"]) == 2
    point = field["points"][0]
    assert {"entity_id", "name", "lon", "lat", "value"} <= set(point)
    # 缺结果与缺坐标的站都必须留下原因，不允许悄悄消失
    reasons = {row["entity_id"]: row["reason"] for row in field["excluded"]}
    assert reasons == {"mee-c": "prediction_missing"}


def test_station_field_excludes_unplottable_but_counts_prediction():
    service = _service()
    _published(service, service._current_live_prediction_id())
    # 给丙站补上结果：应计入 with_prediction，但因缺坐标进入 excluded
    service._published["stations"]["mee-c"]["1"] = {"results": {"probability": _result(0.2)}}
    field = service.station_field(1, "risk")
    assert field["coverage"] == {"total": 3, "with_prediction": 3, "plottable": 2}
    excluded = {row["entity_id"]: row for row in field["excluded"]}
    assert excluded["mee-c"]["reason"] == "missing_verified_coords"
    assert "丙站" in excluded["mee-c"]["name"]


def test_station_field_marks_scenario_horizons():
    service = _service()
    _published(service, service._current_live_prediction_id())
    field = service.station_field(30, "risk")
    assert field["compliance"] == {"label": "情景推演", "locked": True}
    short = service.station_field(1, "risk")
    assert short["compliance"]["locked"] is False


def test_lake_aggregate_is_station_distribution_not_virtual_station():
    service = _service()
    _published(service, service._current_live_prediction_id())
    agg = service._compute_lake_aggregate(service._published["id"])
    h1 = agg["1"]
    assert h1["coverage"] == {"total": 3, "reported": 2}
    # 口径闭环合同：聚合层自证身份与同源性
    assert h1["scope"] == "lake_aggregate"
    assert h1["station_total"] == 3 and h1["station_reported"] == 2
    assert h1["prediction_snapshot_id"] == service._published["id"]
    assert h1["source_snapshot_id"] == "mee_surface_water_realtime_test"
    assert "probability" in h1["aggregation_method"] and "excluded" in h1["aggregation_method"]
    chla = h1["metrics"]["chla"]
    # 站间分布：甲 10、乙 25（站点层聚合，不含全湖行）→ 中位数 17.5，不是均值虚拟站
    assert chla["median"] == 17.5
    assert chla["p25"] < chla["median"] < chla["p75"]
    # 风险概率带 P90 与高风险站占比（≥0.5 与 T1 判据同阈值）：甲 0.4、乙 0.6 → 1/2
    prob = h1["metrics"]["probability"]
    assert prob["p90"] >= prob["p75"]
    assert h1["probability_high_share"]["num"] == 1 and h1["probability_high_share"]["den"] == 2
    # 风险站占比：叶绿素 a ≥20μg/L 的站 1/2
    assert h1["chla_bloom_share"]["threshold_ug_l"] == CHLA_BLOOM_THRESHOLD_UG_L
    assert h1["chla_bloom_share"]["num"] == 1 and h1["chla_bloom_share"]["den"] == 2
    assert h1["risk_level_distribution"] == {"low": 1, "medium": 1}
    # 算法包不可读时全湖判级如实缺省，绝不编造等级
    assert h1["risk_level_lake"]["value"] is None
    assert h1["risk_level_lake"]["reason"] == "risk_bands_unavailable"
    # 面积/覆盖率不从站点预测推导：聚合层没有这两个指标
    assert "area" not in h1["metrics"] and "coverage" not in h1["metrics"]


def test_lake_risk_level_rederived_from_frozen_bands():
    """全湖风险等级 = 冻结风险带作用于 chla 中位数重新判级，不是站点等级平均。"""
    bands = {
        "none": (0.0, 10.0),
        "low": (10.0, 20.0),
        "medium": (20.0, 30.0),
        "high": (30.0, 50.0),
        "severe": (50.0, float("inf")),
    }

    class _WithBands(_CapableRealtime):
        pass

    algorithm = SimpleNamespace(realtime=_CapableRealtime(), _runtime_imports=lambda: [None] * 6 + [bands])
    service = PredictionSnapshotService(algorithm, _CapableRealtime(), cache_dir="__nonexistent__")
    _published(service, service._current_live_prediction_id())
    agg = service._compute_lake_aggregate(service._published["id"])
    h1 = agg["1"]
    # chla 中位数 17.5 → 冻结带 low；站点等级分布是 low/medium 各 1，全湖判级不取平均
    assert h1["risk_level_lake"]["value"] == "low"
    assert h1["risk_level_lake"]["chla_median_ug_l"] == 17.5


def test_driver_distribution_aggregates_station_mechanism_factors():
    service = _service()
    _published(service, service._current_live_prediction_id())
    for entity_id, limiting, tp in (("mee-a", "nitrogen", 0.05), ("mee-b", "phosphorus", 0.30)):
        service._published["stations"][entity_id]["1"]["mechanism_drivers"] = {
            "factors": [
                {"key": "temperature", "label": "温度适合度", "source_value": 27.0, "unit": "℃", "proxy": True},
                {"key": "phosphorus", "label": "磷条件", "source_value": tp, "unit": "mg/L", "proxy": False},
            ],
            "limiting_factor": limiting,
            "net_growth_rate_d": 0.4 if entity_id == "mee-a" else 0.2,
        }
    dist = service.driver_distribution(1)
    assert dist["n_stations"] == 2
    by_key = {f["key"]: f for f in dist["factors"]}
    assert by_key["phosphorus"]["median"] == 0.175
    assert by_key["temperature"]["proxy_count"] == 2
    assert dist["limiting_factor_distribution"] == {"nitrogen": 1, "phosphorus": 1}
    assert dist["net_growth_rate_d"]["median"] == 0.3
    assert "环境状态口径" in dist["note"]


def test_ensure_lake_aggregate_backfills_legacy_cache():
    """旧缓存（聚合层上线前）在站点齐全的就地补齐路径里必须能补出聚合层。"""
    service = _service()
    _published(service, service._current_live_prediction_id())
    service._stations_ready = True
    service._ensure_lake_aggregate(service._published["id"])
    lake_record = service._published["lake"]["1"]
    assert service._published["manifest"]["lake_aggregate"] is True
    assert "station_aggregate" in lake_record
    assert lake_record["station_aggregate"]["metrics"]["chla"]["median"] == 17.5


def test_station_field_refuses_when_snapshot_not_serving():
    service = _service()
    _published(service, "stale-id-not-matching-live")
    assert service.station_field(1, "risk") is None
    assert service.driver_distribution(1) is None
