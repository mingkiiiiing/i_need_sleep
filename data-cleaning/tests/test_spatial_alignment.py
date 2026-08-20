from __future__ import annotations

import csv
import json
import sqlite3

from pipeline.align import run_spatial_alignment, spatial_align_records


def _row(
    *,
    source_id: str,
    time: str = "2026-08-18T00:00:00+00:00",
    variable: str = "chlorophyll_a",
    value: float | None = 1.0,
    station: str | None = None,
    scene: str | None = None,
    lon: float | None = 120.0,
    lat: float | None = 31.0,
    pixel_size_m: float | None = None,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_file": "fixture.csv",
        "source_row": "1",
        "station_id": station,
        "scene_id": scene,
        "observed_at": time,
        "time_bucket": time,
        "variable_code": variable,
        "clean_value": value,
        "observed_value": value,
        "longitude": lon,
        "latitude": lat,
        "pixel_size_m": pixel_size_m,
        "quality_flags": [],
        "_category": "remote_sensing" if scene else "water_quality",
    }


def test_station_buffer_returns_smallest_matching_pixel_radius() -> None:
    rows = [
        _row(source_id="station_source", station="S1", lon=120.3, lat=31.2, variable="water_temperature"),
        _row(source_id="remote_source", scene="SCENE_1", lon=120.301, lat=31.2),
        _row(source_id="remote_source", scene="SCENE_2", lon=120.3045, lat=31.2),
        _row(source_id="remote_source", scene="SCENE_3", lon=120.309, lat=31.2),
        _row(source_id="remote_source", scene="SCENE_OUT", lon=120.32, lat=31.2),
    ]
    result = spatial_align_records(rows, grid_size_m=300.0, grid_origin=(120.0, 31.0))
    matches = [item for item in result["station_buffer_matches"] if item["spatial_match_status"] == "matched"]
    assert [item["buffer_pixels"] for item in matches] == [1, 2, 3]
    assert all(item["within_3px"] for item in matches)
    assert result["counts"]["matched_station_buffer_rows"] == 3


def test_remote_pixels_are_aggregated_to_300m_grid_with_resolution_lineage() -> None:
    rows = [
        _row(source_id="remote_source", scene="A", lon=120.0001, lat=31.0001, value=1.0, pixel_size_m=10),
        _row(source_id="remote_source", scene="B", lon=120.0008, lat=31.0002, value=2.0, pixel_size_m=20),
        _row(source_id="remote_source", scene="C", lon=120.0015, lat=31.0003, value=3.0, pixel_size_m=30),
    ]
    result = spatial_align_records(rows, grid_size_m=300.0, grid_origin=(120.0, 31.0))
    assert len(result["grid_300m_observations"]) == 1
    grid = result["grid_300m_observations"][0]
    assert grid["grid_size_m"] == 300.0
    assert grid["n_pixels"] == 3
    assert grid["valid_pixel_count"] == 3
    assert grid["value_mean"] == 2.0
    assert grid["source_pixel_resolutions_m"] == [10.0, 20.0, 30.0]


def test_lake_statistics_use_boundary_and_run_writes_sqlite(tmp_path) -> None:
    boundary = tmp_path / "boundary.geojson"
    boundary.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[119.99, 30.99], [120.02, 30.99], [120.02, 31.02], [119.99, 31.02], [119.99, 30.99]]]}
        }]
    }), encoding="utf-8")
    input_csv = tmp_path / "resampled.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_id", "station_id", "scene_id", "observed_at", "time_bucket", "variable_code", "clean_value", "observed_value", "longitude", "latitude", "pixel_size_m", "quality_flags"])
        writer.writeheader()
        writer.writerow({"source_id": "remote_source", "station_id": "", "scene_id": "SCENE", "observed_at": "2026-08-18T00:00:00+00:00", "time_bucket": "2026-08-18T00:00:00+00:00", "variable_code": "chlorophyll_a", "clean_value": 2.0, "observed_value": 2.0, "longitude": 120.0, "latitude": 31.0, "pixel_size_m": 10, "quality_flags": "[]"})
    output_root = tmp_path / "out"
    database = tmp_path / "spatial.sqlite"
    manifest = run_spatial_alignment(input_csv, output_root, database, boundary_path=boundary, grid_origin=(120.0, 31.0))
    assert manifest["status"] == "completed"
    assert manifest["boundary"]["status"] == "loaded"
    assert manifest["counts"]["grid_rows"] == 1
    assert (output_root / "grid_300m_observations.csv").exists()
    connection = sqlite3.connect(database)
    try:
        names = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        assert {"station_buffer_matches", "grid_300m_observations", "lake_area_stats"}.issubset(names)
    finally:
        connection.close()
