from __future__ import annotations

import json
import shutil

from backend.app.providers import MeeRealtimeObservationProvider, _DEFAULT_REALTIME_DIR


def test_provider_hot_reloads_when_status_publication_marker_changes(tmp_path):
    catalog = tmp_path / "mee_realtime"
    shutil.copytree(_DEFAULT_REALTIME_DIR, catalog)
    provider = MeeRealtimeObservationProvider(catalog)

    first = provider.status()
    stations_path = catalog / "stations.json"
    stations_doc = json.loads(stations_path.read_text(encoding="utf-8"))
    target_id = stations_doc["stations"][0]["entity_id"]
    stations_doc["stations"][0]["source_station_name"] = "热重载测试站"
    stations_path.write_text(json.dumps(stations_doc, ensure_ascii=False), encoding="utf-8")

    status_path = catalog / "status.json"
    status_doc = json.loads(status_path.read_text(encoding="utf-8"))
    status_doc["as_of"] = "2099-01-01T00:00:00Z"
    status_path.write_text(json.dumps(status_doc, ensure_ascii=False), encoding="utf-8")

    assert first["as_of"] != "2099-01-01T00:00:00Z"
    assert provider.status()["as_of"] == "2099-01-01T00:00:00Z"
    assert provider.station(target_id)["source_station_name"] == "热重载测试站"
