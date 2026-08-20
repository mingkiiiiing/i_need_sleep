from __future__ import annotations

import h5py
import numpy as np
import pytest

from pipeline.sources.gpm_imerg import (
    aggregate_imerg_windows,
    build_imerg_access_urls,
    build_imerg_filename,
    parse_imerg_hdf5,
    run_gpm_imerg,
)


def test_imerg_filename_and_urls_use_official_half_hour_path():
    filename = build_imerg_filename("2026-08-19T00:30:00Z", run="early", version="07")
    assert filename == "3B-HHR-E.MS.MRG.3IMERG.20260819-S003000-E005959.0030.V07.HDF5"
    urls = build_imerg_access_urls("2026-08-19T00:30:00Z", run="early")
    assert "/GPM_3IMERGHH.07/2026/231/" in urls["file"]
    assert filename in urls["file"]
    assert "/opendap/" in urls["opendap"]


def test_imerg_hdf5_parser_keeps_quality_and_converts_rate_to_30min(tmp_path):
    path = tmp_path / "granule.HDF5"
    with h5py.File(path, "w") as handle:
        grid = handle.create_group("Grid")
        grid.create_dataset("lat", data=np.array([31.0, 31.5]))
        grid.create_dataset("lon", data=np.array([120.0, 120.5]))
        precipitation = grid.create_dataset("precipitationCal", data=np.array([[2.0, 4.0], [6.0, 8.0]]))
        precipitation.attrs["units"] = "mm/hr"
        precipitation.attrs["_FillValue"] = -9999.9
        quality = grid.create_dataset("precipitationQualityIndex", data=np.array([[0.8, 0.9], [1.0, 0.7]]))
        quality.attrs["units"] = "1"
    result = parse_imerg_hdf5(path, observed_at="2026-08-19T00:30:00Z")
    row = result["row"]
    assert result["record_count"] == 1
    assert row["value"] == 2.5
    assert row["unit"] == "mm"
    assert row["quality_index"] == pytest.approx(0.85)
    assert row["valid_pixel_count"] == 4
    assert row["is_imputed"] is False


def test_imerg_aggregation_never_turns_missing_input_into_zero():
    rows = [
        {
            "observed_at": f"2026-08-19T{hour:02d}:{minute:02d}:00Z",
            "value": 1.0,
            "quality_index": 0.8,
            "station_id": "TAIHU_AREA_MEAN",
            "run": "early",
        }
        for hour in range(6)
        for minute in (0, 30)
    ]
    outputs = aggregate_imerg_windows(rows, windows_hours=(6, 24))
    six_hour = [row for row in outputs if row["window_hours"] == 6][-1]
    twenty_four_hour = [row for row in outputs if row["window_hours"] == 24][-1]
    assert six_hour["value"] == 12.0
    assert six_hour["aggregation_status"] == "complete"
    assert twenty_four_hour["value"] is None
    assert twenty_four_hour["aggregation_status"] == "missing_input"


def test_imerg_run_without_earthdata_token_returns_request_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("TAIHU_EARTHDATA_TOKEN", raising=False)
    result = run_gpm_imerg(
        "2026-08-19T00:00:00Z", "2026-08-19T01:00:00Z",
        raw_root=tmp_path / "raw", silver_root=tmp_path / "silver", manifest_path=tmp_path / "manifest.json",
    )
    assert result["status"] == "BLOCKED_AUTH"
    assert result["data_truth"] == "official_request_plan_only"
    assert result["granule_count"] == 3
    assert not (tmp_path / "silver").exists()
