from pipeline.sources.sentinel2_process_monthly import build_request


def test_process_request_is_bounded_and_uses_exact_day():
    body = build_request("2025-06-18", (200000, 3400000, 260000, 3470000), 2000, 2334)
    assert body["input"]["data"][0]["type"] == "sentinel-2-l2a"
    assert body["input"]["data"][0]["dataFilter"]["timeRange"]["from"] == "2025-06-18T00:00:00Z"
    assert body["output"]["width"] == 2000
    assert body["output"]["height"] == 2334


def test_process_request_can_use_monthly_window():
    body = build_request("2025-06-01", (200000, 3400000, 260000, 3470000), 2000, 2334, end_date="2025-06-30", pixel_composite=True)
    assert body["input"]["data"][0]["dataFilter"]["timeRange"]["to"] == "2025-06-30T23:59:59Z"
    assert 'mosaicking: "ORBIT"' in body["evalscript"]
