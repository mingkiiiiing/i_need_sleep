from datetime import datetime

import numpy as np
import xarray as xr

from pipeline.sources import era5_land
from pipeline.sources.era5_land import build_cds_request, parse_era5_land_netcdf, run_era5_land


def test_cds_request_uses_bbox_area_and_hourly_utc_contract():
    request = build_cds_request(2020, (119.9, 30.9, 120.75, 31.65), ["2m_temperature", "total_precipitation"])
    assert request["year"] == "2020"
    assert request["area"] == [31.65, 119.9, 30.9, 120.75]
    assert request["time"] == [f"{hour:02d}:00" for hour in range(24)]
    assert request["format"] == "netcdf"


def test_parse_era5_land_official_schema_fixture_converts_units_and_bbox(tmp_path):
    path = tmp_path / "era5_land_official_schema_fixture.nc"
    xr.Dataset(
        {
            "t2m": (("time", "latitude", "longitude"), np.array([[[300.15, 301.15], [299.15, 300.15]]])),
            "tp": (("time", "latitude", "longitude"), np.array([[[0.001, 0.002], [0.003, 0.004]]])),
        },
        coords={"time": [datetime(2020, 1, 1, 0)], "latitude": [31.2, 31.1], "longitude": [120.0, 120.5]},
        attrs={"source": "official ERA5-Land NetCDF schema fixture; values are test-only"},
    ).to_netcdf(path, engine="scipy")
    result = parse_era5_land_netcdf(path, (119.9, 31.0, 120.6, 31.3))
    assert result["record_count"] == 2
    temperature = next(row for row in result["rows"] if row["variable_code"] == "air_temperature")
    precipitation = next(row for row in result["rows"] if row["variable_code"] == "precipitation")
    assert temperature["clean_value"] == 27.0
    assert precipitation["clean_value"] == 2.5
    assert temperature["source_timezone"] == "UTC"


def test_credentials_present_detects_env_key_and_config_file(tmp_path, monkeypatch):
    """凭据检测：环境变量与配置文件两条路径都要覆盖，且不得依赖本机真实配置。"""
    monkeypatch.delenv("TAIHU_CDS_API_KEY", raising=False)
    monkeypatch.setattr(era5_land.Path, "home", classmethod(lambda cls: tmp_path))
    assert era5_land._credentials_present() is False
    (tmp_path / ".cdsapirc").write_text("url: https://cds.climate.copernicus.eu/api\nkey: dummy\n", encoding="utf-8")
    assert era5_land._credentials_present() is True
    monkeypatch.setenv("TAIHU_CDS_API_KEY", "dummy-key")
    assert era5_land._credentials_present() is True


def test_no_cds_credentials_returns_blocked_auth_without_network(tmp_path, monkeypatch):
    """无凭据时必须返回 BLOCKED_AUTH，且不得访问网络。

    本机可能真实存在 ~/.cdsapirc，因此这里显式隔离凭据检测，
    保证该用例只验证"缺凭据"分支本身，不受开发环境影响。
    """
    monkeypatch.delenv("TAIHU_CDS_API_KEY", raising=False)
    monkeypatch.setattr(era5_land, "_credentials_present", lambda: False)
    result = run_era5_land(2020, 2020, (119.9, 30.9, 120.75, 31.65), manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["error_class"] == "MissingCDSConfiguration"
    assert result["data_truth"] == "official_request_plan_only"
    assert result["requests"][0]["request"]["format"] == "netcdf"
