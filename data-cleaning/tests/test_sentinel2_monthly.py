from datetime import date

from pipeline.sources.sentinel2_monthly import _month_ranges, select_best_day


def _scene(day: str, tile: str, cloud: float):
    assets = {name: {"href": f"https://example/{name}.tif"} for name in ("green", "red", "rededge1", "nir", "swir16", "scl")}
    return {"id": f"S2A_T{tile}_{day.replace('-', '')}_L2A", "properties": {"datetime": f"{day}T02:00:00Z", "eo:cloud_cover": cloud, "grid:code": f"MGRS-{tile}"}, "assets": assets}


def test_month_ranges_are_bounded():
    assert list(_month_ranges(date(2022, 1, 15), date(2022, 3, 3))) == [
        ("2022-01", date(2022, 1, 15), date(2022, 1, 31)),
        ("2022-02", date(2022, 2, 1), date(2022, 2, 28)),
        ("2022-03", date(2022, 3, 1), date(2022, 3, 3)),
    ]


def test_best_day_prefers_tile_coverage_before_cloud():
    selected = select_best_day([
        _scene("2023-05-01", "50RQV", 0.1),
        _scene("2023-05-08", "50RQV", 10.0),
        _scene("2023-05-08", "51RTQ", 10.0),
    ])
    assert {item["properties"]["datetime"][:10] for item in selected} == {"2023-05-08"}
    assert len(selected) == 2
