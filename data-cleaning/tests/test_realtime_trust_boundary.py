"""实时数据可信边界回归（审计 2026-09-06 整改）。

覆盖：MEE ground truth 降级（值域 QC ≠ 独立验证）、采集状态留痕（成功/失败）、
新鲜度门禁、桥接层站名保留 + 站点-网格映射。
CLMS 测试隔离与真值分类见 tests/test_clms_lwq.py。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from data_factory.ingestion.mee_realtime import TZ_CN, normalize, run_collect_mee
from data_factory.simulation.observation import bridge_realtime_mee, filter_mee_fresh

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=TZ_CN)

RECORDS = [
    {"station_id": "兰山嘴", "station_name": "兰山嘴", "observed_time": "09-06 19:00", "do": 8.0},
    {"station_id": "拖山", "station_name": "拖山", "observed_time": "09-06 19:00", "do": 7.5},
    {"station_id": "明星路桥", "station_name": "明星路桥", "observed_time": "09-06 19:00", "do": 6.1},
]


class TestMeeGroundTruthBoundary:
    def test_normalize_never_marks_ground_truth(self):
        frame = normalize(RECORDS, retrieved_at=NOW, snapshot_file="snap.json")
        assert len(frame) == 3
        # 可信边界：物理值域/时间 QC 通过也只是官方接口观测，is_ground_truth 恒 False
        assert not frame["is_ground_truth"].any()
        assert (frame["value_type"] == "observed").all()
        assert (frame["quality_flag"] == "pass").all()
        assert (frame["provenance_type"] == "observed").all()

    def test_normalize_preserves_readable_station_name(self):
        frame = normalize(RECORDS, retrieved_at=NOW, snapshot_file="snap.json")
        assert set(frame["station_name"]) == {"兰山嘴", "拖山", "明星路桥"}


class TestMeeBridgeMapping:
    def _meta(self):
        return {"dataset_version": "mvp", "generator_version": "v-test", "generation_batch_id": "b-test"}

    def test_bridge_preserves_station_name_and_maps_grid(self):
        frame = normalize(RECORDS, retrieved_at=NOW, snapshot_file="snap.json")
        mapping = pd.DataFrame(
            [
                {"station_id": "兰山嘴", "station_name": "兰山嘴", "grid_id": "G02323474", "mapping_status": "mapped"},
                {"station_id": "拖山", "station_name": "拖山", "grid_id": "G02353470", "mapping_status": "mapped"},
            ]
        )
        out = bridge_realtime_mee(frame, self._meta(), station_mapping=mapping)
        assert out["station_name"].notna().all()
        by_station = out.drop_duplicates("station_name").set_index("station_name")
        assert by_station.loc["兰山嘴", "grid_id"] == "G02323474"
        assert by_station.loc["拖山", "grid_id"] == "G02353470"
        # 未映射站点保留站名、grid_id 置空并在 qc_note 留痕，不得猜测网格
        unmapped = out[out["station_name"] == "明星路桥"]
        assert pd.isna(unmapped["grid_id"].iloc[0])
        assert "station_not_mapped_to_grid" in unmapped["qc_note"].iloc[0]

    def test_bridge_empty_input_keeps_schema(self):
        out = bridge_realtime_mee(pd.DataFrame(), self._meta())
        assert out.empty
        assert {"station_id", "station_name", "grid_id", "observed_time", "value_type", "is_ground_truth"}.issubset(out.columns)


class TestMeeFreshnessGate:
    def test_gate_drops_stale_keeps_fresh(self):
        frame = pd.DataFrame(
            {
                "station_id": ["a", "a"],
                "observed_time": [
                    pd.Timestamp("2026-09-06 18:00").tz_localize(TZ_CN),
                    pd.Timestamp("2026-09-04 20:00").tz_localize(TZ_CN),
                ],
            }
        )
        now = pd.Timestamp("2026-09-06 19:30").tz_localize(TZ_CN)
        kept, dropped = filter_mee_fresh(frame, 24.0, now=now)
        assert dropped == 1
        assert len(kept) == 1
        assert kept["observed_time"].iloc[0] == pd.Timestamp("2026-09-06 18:00").tz_localize(TZ_CN)

    def test_gate_disabled_when_max_lag_zero(self):
        frame = pd.DataFrame({"station_id": ["a"], "observed_time": [pd.Timestamp("2000-01-01").tz_localize(TZ_CN)]})
        kept, dropped = filter_mee_fresh(frame, 0, now=pd.Timestamp("2026-09-06").tz_localize(TZ_CN))
        assert dropped == 0 and len(kept) == 1


def _mee_body() -> dict:
    """动态构造两站一小时的 tbody（新鲜时间随测试时刻推进，避免用例老化）。"""
    fresh = (datetime.now(TZ_CN) - timedelta(hours=1)).strftime("%m-%d %H:%M")
    return {
        "result": 1,
        "tbody": [
            ["江苏省", "太湖流域", "兰山嘴", fresh, "3", "原始值：28.5", "原始值：7.3", "原始值：5.1",
             "原始值：410", "原始值：22", "原始值：4.3", "原始值：0.10", "原始值：0.15", "原始值：1.9", "原始值：0.002", "--"],
            ["江苏省", "太湖流域", "拖山", fresh, "2", "原始值：27.9", "原始值：7.6", "原始值：6.4",
             "原始值：388", "原始值：18", "原始值：3.9", "原始值：0.08", "原始值：1.7", "原始值：1.6", "--", "--"],
        ],
    }


def _cfg() -> dict:
    return {"realtime_sources": {"mee": {"enabled": True, "tls_verify": False, "freshness_max_lag_h": 24}}}


def _run_collect(tmp_path, monkeypatch, fetch=None):
    """统一入口：采集 + 目录构建全部落在 tmp_path，禁止写正式 silver/raw。"""
    import data_factory.ingestion.mee_realtime as mee

    if fetch is None:
        payload = json.dumps(_mee_body(), ensure_ascii=False).encode("utf-8")
        fetch = lambda cfg, verify: (payload, 200, {"Content-Type": "application/json"}, 0)  # noqa: E731
    monkeypatch.setattr(mee, "fetch_snapshot", fetch)
    return mee.run_collect_mee(
        _cfg(),
        out_dir=tmp_path,
        raw_root=tmp_path / "raw",
        catalog_dir=tmp_path / "catalog",
        catalog_registry_path=tmp_path / "no_registry.json",
    )


class TestRunCollectMeeStatusFile:
    def test_success_writes_status_and_downgrades_truth(self, tmp_path, monkeypatch):
        result = _run_collect(tmp_path, monkeypatch)
        assert result["status"] == "completed"
        assert result["rows_written"] == 19  # 兰山嘴 10 项 + 拖山 9 项（缺测不生成记录）
        assert result["freshness_status"] == "fresh"
        status = json.loads((tmp_path / "mee_collection_status.json").read_text(encoding="utf-8"))
        assert status["status"] == "completed"
        assert status["freshness_status"] == "fresh"
        assert status["latest_observed_time"] is not None
        frame = pd.read_parquet(tmp_path / "mee_observations.parquet")
        assert not frame["is_ground_truth"].any()
        assert set(frame["station_name"]) == {"兰山嘴", "拖山"}
        # 三层结构：目录与完整缺测观测同步重建
        catalog = json.loads((tmp_path / "catalog" / "stations.json").read_text(encoding="utf-8"))
        assert catalog["station_count"] == 2
        obs = pd.read_parquet(tmp_path / "catalog" / "observations.parquet")
        assert len(obs) == 22  # 2 站 × 11 指标，缺测显式落行
        assert (obs["observation_status"] == "missing").sum() == 22 - 19
        assert not obs["is_ground_truth"].any()

    def test_failure_writes_status_and_raises(self, tmp_path, monkeypatch):
        import data_factory.ingestion.mee_realtime as mee

        def boom(cfg, verify):
            raise RuntimeError("SSL UNEXPECTED_EOF_WHILE_READING")

        with pytest.raises(RuntimeError):
            _run_collect(tmp_path, monkeypatch, fetch=boom)
        status = json.loads((tmp_path / "mee_collection_status.json").read_text(encoding="utf-8"))
        assert status["status"] == "failed"
        assert "SSL UNEXPECTED_EOF_WHILE_READING" in status["last_error"]
        published = json.loads((tmp_path / "catalog" / "status.json").read_text(encoding="utf-8"))
        assert published["collection_status"] == "failed"
        assert published["last_error_code"] == "UPSTREAM_TLS_FAILURE"

    def test_failure_keeps_last_success(self, tmp_path, monkeypatch):
        _run_collect(tmp_path, monkeypatch)
        first = json.loads((tmp_path / "mee_collection_status.json").read_text(encoding="utf-8"))

        def boom(cfg, verify):
            raise RuntimeError("network down")

        with pytest.raises(RuntimeError):
            _run_collect(tmp_path, monkeypatch, fetch=boom)
        second = json.loads((tmp_path / "mee_collection_status.json").read_text(encoding="utf-8"))
        assert second["status"] == "failed"
        assert second["last_success_utc"] == first["last_success_utc"]
        published = json.loads((tmp_path / "catalog" / "status.json").read_text(encoding="utf-8"))
        assert published["collection_status"] == "failed"
        assert published["last_success_at"] == first["last_success_utc"]
        assert published["snapshot_count"] == 1
