from __future__ import annotations

import json

import numpy as np
import xarray as xr

from pipeline.sources.c3s_seasonal import (
    apply_bias_correction,
    build_c3s_plan,
    build_c3s_request,
    parse_c3s_dataset,
    run_c3s_seasonal,
)


def test_c3s_requests_keep_hindcast_and_forecast_axes_consistent():
    request = build_c3s_request(
        kind="hindcast", years=[1993, 1994], init_month=5,
        variables=["2m_temperature", "total_precipitation"], lead_months=[1, 3],
    )
    assert request["format"] == "grib"
    assert request["originating_centre"] == "ecmwf"
    assert request["product_type"] == "monthly_mean"
    assert request["year"] == ["1993", "1994"]
    assert request["month"] == "05"
    assert request["leadtime_month"] == ["1", "3"]
    assert request["area"] == [31.65, 119.9, 30.9, 120.75]


def test_c3s_plan_contains_both_kinds_with_shared_schema():
    plan = build_c3s_plan(forecast_year=2026, init_month=8, hindcast_years=[1993, 1994], lead_months=[1, 2])
    assert set(plan["requests"]) == {"hindcast", "forecast"}
    assert plan["requests"]["forecast"]["year"] == "2026"
    assert plan["requests"]["hindcast"]["year"] == ["1993", "1994"]
    assert plan["schema_contract"]["lead_month"] == "1-based forecast month"


def test_c3s_netcdf_parser_preserves_member_and_lead_month(tmp_path):
    path = tmp_path / "c3s_fixture.nc"
    dataset = xr.Dataset(
        {
            "t2m": (
                ("forecast_reference_time", "leadtime_month", "number", "latitude", "longitude"),
                np.array([[[[[273.15, 274.15], [275.15, 276.15]], [[277.15, 278.15], [279.15, 280.15]]],
                           [[[283.15, 284.15], [285.15, 286.15]], [[287.15, 288.15], [289.15, 290.15]]]]]),
            )
        },
        coords={
            "forecast_reference_time": np.array(["2026-05-01"], dtype="datetime64[ns]"),
            "leadtime_month": [1, 2], "number": [0, 1],
            "latitude": [31.0, 31.5], "longitude": [120.0, 120.5],
        },
    )
    dataset.to_netcdf(path, engine="scipy")
    result = parse_c3s_dataset(path, kind="forecast", bbox=(119.9, 30.9, 120.75, 31.65))
    assert result["record_count"] == 4
    assert result["lead_months"] == [1, 2]
    assert {row["ensemble_member"] for row in result["rows"]} == {0, 1}
    assert {row["value"] for row in result["rows"]} == {1.5, 5.5, 11.5, 15.5}
    assert all(row["dataset_kind"] == "forecast" for row in result["rows"])


def test_c3s_bias_correction_only_changes_forecast_rows():
    rows = [
        {"dataset_kind": "hindcast", "variable_code": "air_temperature", "lead_month": 1, "value": 10.0},
        {"dataset_kind": "forecast", "variable_code": "air_temperature", "lead_month": 1, "value": 12.0},
    ]
    corrected = apply_bias_correction(rows, {("air_temperature", 1): 10.0}, {("air_temperature", 1): 11.5})
    assert corrected[0]["value"] == 10.0
    assert corrected[1]["value"] == 13.5
    assert corrected[1]["bias_correction_status"] == "hindcast_additive_delta"


def test_c3s_run_without_cds_credentials_returns_truthful_block(tmp_path, monkeypatch):
    monkeypatch.delenv("TAIHU_CDS_API_KEY", raising=False)
    manifest = tmp_path / "c3s.json"
    result = run_c3s_seasonal(
        2026, 8, hindcast_years=[1993, 1994], lead_months=[1, 2],
        raw_root=tmp_path / "raw", silver_root=tmp_path / "silver", manifest_path=manifest,
    )
    assert result["status"] == "BLOCKED_AUTH"
    assert result["data_truth"] == "official_request_plan_only"
    assert manifest.exists()
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["requests"]["forecast"]["year"] == "2026"
    assert saved["requests"]["hindcast"]["year"] == ["1993", "1994"]
