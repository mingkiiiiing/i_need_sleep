from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from pipeline.sources.noaa_gfs import DEFAULT_BBOX, build_gfs_filter_url, run_gfs


def test_gfs_filter_url_is_noaa_bounded_and_not_ecmwf() -> None:
    url = build_gfs_filter_url("2026-08-19", 0, 6, bbox=DEFAULT_BBOX, variables=["TMP", "APCP", "UGRD"])
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "nomads.ncep.noaa.gov"
    assert query["file"] == ["gfs.t00z.pgrb2.0p25.f006"]
    assert query["dir"] == ["/gfs.20260819/00/atmos"]
    assert query["subregion"] == ["on"]
    assert query["leftlon"] == ["119.9"]
    assert query["rightlon"] == ["120.75"]
    assert query["var_TMP"] == ["on"]
    assert query["var_APCP"] == ["on"]
    assert "all_lev" not in query
    assert "ecmwf" not in url.casefold()


def test_gfs_filter_url_rejects_unknown_variable_or_cycle() -> None:
    with pytest.raises(ValueError):
        build_gfs_filter_url("2026-08-19", 3, 0)
    with pytest.raises(ValueError):
        build_gfs_filter_url("2026-08-19", 0, 0, variables=["UNKNOWN"])


def test_empty_gfs_run_is_explicitly_blocked_and_model_identity_is_noaa(tmp_path: Path) -> None:
    result = run_gfs("2026-08-19", 0, steps=[], raw_root=tmp_path / "raw", silver_root=tmp_path / "silver", manifest_path=tmp_path / "manifest.json")
    assert result["real_batch"] is False
    assert result["status"] == "BLOCKED_REMOTE"
    assert result["variables"]
    assert all("ECMWF" not in str(item) for item in result["variables"])
