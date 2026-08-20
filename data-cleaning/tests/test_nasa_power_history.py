import json
from datetime import datetime, timedelta, timezone

from pipeline.sources.nasa_power_history import ingest_nasa_power_history


def _payload(year: int):
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    hours = (366 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 365) * 24
    keys = [(start + timedelta(hours=index)).strftime("%Y%m%d%H") for index in range(hours)]
    params = {
        "T2M": {key: 10.0 for key in keys},
        "WS10M": {key: 2.0 for key in keys},
        "WD10M": {key: 180.0 for key in keys},
        "PRECTOTCORR": {key: 24.0 for key in keys},
        "ALLSKY_SFC_SW_DWN": {key: 100.0 for key in keys},
    }
    return {
        "geometry": {"coordinates": [120.3, 31.2, 29.15]},
        "header": {"time_standard": "UTC"},
        "parameters": {
            "T2M": {"units": "C"}, "WS10M": {"units": "m/s"}, "WD10M": {"units": "Degrees"},
            "PRECTOTCORR": {"units": "mm/day"}, "ALLSKY_SFC_SW_DWN": {"units": "Wh/m^2"},
        },
        "properties": {"parameter": params},
    }


def test_nasa_history_year_chunking_and_idempotent_reuse(tmp_path):
    calls = []

    def requester(url):
        calls.append(url)
        year = int(url.split("start=")[1][:4])
        return 200, "application/json", _payload(year)

    result = ingest_nasa_power_history(
        2020, 2020,
        raw_root=tmp_path / "raw",
        output_root=tmp_path / "silver",
        manifest_path=tmp_path / "manifest.json",
        requester=requester,
    )
    assert result["status"] == "completed"
    assert result["checks"]["all_time_standard_utc"]
    assert result["silver"]["rows"] == 8784 * 5
    assert len(calls) == 1
    second = ingest_nasa_power_history(
        2020, 2020,
        raw_root=tmp_path / "raw",
        output_root=tmp_path / "silver2",
        manifest_path=tmp_path / "manifest2.json",
        requester=requester,
    )
    assert second["status"] == "completed"
    assert len(calls) == 1
