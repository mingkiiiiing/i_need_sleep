from pipeline.sources.taihu_insitu_parse import _time


def test_taihu_local_time_is_converted_to_utc():
    assert _time("2020_12_22  9:52:00") == "2020-12-22T01:52:00+00:00"
