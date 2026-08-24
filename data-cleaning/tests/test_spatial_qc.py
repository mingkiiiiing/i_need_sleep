from __future__ import annotations

from pipeline.qc import quality_control


def _row(time: str, row_no: int, *, station: str, longitude: float, latitude: float, variable: str = "water_temperature", crs: int = 4326) -> dict[str, object]:
    return {
        "source_id": "spatial_fixture",
        "source_file": "spatial.csv",
        "source_row": str(row_no),
        "station_id": station,
        "scene_id": None,
        "observed_at": time,
        "variable_code": variable,
        "observed_value": 20.0,
        "raw_value": 20.0,
        "clean_value": 20.0,
        "unit": "degC",
        "raw_unit": "degC",
        "longitude": longitude,
        "latitude": latitude,
        "crs_epsg": crs,
        "quality_flags": [],
    }


def test_spatial_rules_identify_swap_zero_boundary_drift_and_crs() -> None:
    rows = [
        _row("2026-08-18T00:00:00Z", 1, station="SWAP", longitude=31.2, latitude=120.3, variable="air_temperature"),
        _row("2026-08-18T00:00:00Z", 2, station="ZERO", longitude=0.0, latitude=0.0, variable="cloud_cover"),
        _row("2026-08-18T00:00:00Z", 3, station="OUTSIDE", longitude=121.5, latitude=32.0, variable="wind_speed"),
        _row("2026-08-18T00:00:00Z", 4, station="CRS", longitude=120.3, latitude=31.2, variable="precipitation", crs=3857),
        _row("2026-08-18T00:00:00Z", 5, station="DRIFT", longitude=120.3, latitude=31.2, variable="water_level"),
        _row("2026-08-18T01:00:00Z", 6, station="DRIFT", longitude=120.3, latitude=31.2, variable="water_level"),
        _row("2026-08-18T02:00:00Z", 7, station="DRIFT", longitude=120.32, latitude=31.2, variable="water_level"),
    ]

    result = quality_control(rows, max_rate_per_hour={})

    assert result["spatial_issue_counts"] == {"Q36": 1, "Q37": 1, "Q38": 1, "Q40": 1, "Q39": 1}
    assert result["spatial_boundary_status"] == "loaded"
    issue_codes = {(issue["source_row"], issue["issue_code"]) for issue in result["issues"]}
    assert ("1", "Q36") in issue_codes
    assert ("2", "Q37") in issue_codes
    assert ("3", "Q38") in issue_codes
    assert ("4", "Q40") in issue_codes
    assert ("7", "Q39") in issue_codes
    # The swapped record also violates the canonical global latitude range,
    # so the existing Q07 hard gate rejects it; Q36 remains auditable in the
    # issue log and the other spatial findings stay review-only.
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["source_row"] == "1"
    assert len(result["suspect"]) == 4


def test_scene_centroid_outside_lake_is_not_treated_as_station_failure() -> None:
    row = _row(
        "2026-08-18T00:00:00Z",
        1,
        station="",
        longitude=119.6753,
        latitude=31.1114,
        variable="cloud_cover",
    )
    row["scene_id"] = "S2_OUTSIDE_CENTROID"

    result = quality_control([row], max_rate_per_hour={})

    assert result["spatial_issue_counts"] == {}
    assert result["cleaned"][0]["source_row"] == "1"
