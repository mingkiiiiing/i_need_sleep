from pipeline.sources.open_meteo_seasonal import parse_ensemble


def test_ensemble_parser_emits_mean_and_interval():
    payload = {"latitude": 31.2, "longitude": 120.3, "timezone": "Asia/Shanghai", "daily": {"time": ["2026-08-19"], "temperature_2m_mean": [20], "temperature_2m_mean_member01": [22]}}
    row = parse_ensemble(payload).iloc[0]
    assert row["temperature_2m_mean_ensemble_mean"] == 21
    assert row["temperature_2m_mean_member_count"] == 2
    assert row["temperature_2m_mean_p10"] < row["temperature_2m_mean_p90"]
