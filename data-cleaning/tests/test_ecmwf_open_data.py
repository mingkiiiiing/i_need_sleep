from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.sources.ecmwf_open_data import DEFAULT_BBOX, DEFAULT_PARAMS, build_ecmwf_request, download_ecmwf_open_data, run_ecmwf_open_data


def test_ecmwf_request_is_bounded_and_keeps_requested_variables() -> None:
    request = build_ecmwf_request("2026-08-19", 0, [0, 24, 48, 72], bbox=DEFAULT_BBOX, parameters=DEFAULT_PARAMS)
    assert request["type"] == "fc"
    assert request["step"] == [0, 24, 48, 72]
    assert request["param"] == list(DEFAULT_PARAMS)
    assert request["area"] == [DEFAULT_BBOX[3], DEFAULT_BBOX[0], DEFAULT_BBOX[1], DEFAULT_BBOX[2]]
    assert request["grid"] == [0.25, 0.25]
    assert request["format"] == "grib2"


def test_ecmwf_request_rejects_unbounded_or_unknown_request() -> None:
    with pytest.raises(ValueError):
        build_ecmwf_request("2026-08-19", 3, [0])
    with pytest.raises(ValueError):
        build_ecmwf_request("2026-08-19", 0, [0], parameters=["unknown"])
    with pytest.raises(ValueError):
        build_ecmwf_request("2026-08-19", 0, [361])


def test_ecmwf_missing_optional_client_is_explicitly_blocked(tmp_path: Path) -> None:
    result = download_ecmwf_open_data("2026-08-19", 0, steps=[0, 72], raw_root=tmp_path)
    assert result["request"]["area"] == [DEFAULT_BBOX[3], DEFAULT_BBOX[0], DEFAULT_BBOX[1], DEFAULT_BBOX[2]]
    if result["status"] == "BLOCKED_DEPENDENCY":
        assert "ecmwf-opendata" in result["error"]
    else:
        assert result["status"] in {"completed", "BLOCKED_REMOTE"}


def test_run_ecmwf_writes_auditable_manifest_when_real_batch_unavailable(tmp_path: Path) -> None:
    manifest = tmp_path / "ecmwf.json"
    result = run_ecmwf_open_data("2026-08-19", 0, steps=[0, 72], raw_root=tmp_path / "raw", silver_root=tmp_path / "silver", manifest_path=manifest)
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["request"]["step"] == [0, 72]
    assert result["manifest_path"] == str(manifest)
    # The public ECMWF endpoint may be reachable in a network-enabled test
    # environment. Validate the auditable branch that actually ran instead of
    # treating a newly available real batch as a test failure.
    assert saved["real_batch"] is result["real_batch"]
    if result["real_batch"]:
        assert result["parsed"]["status"] == "completed"
        assert result["parsed"]["records"] > 0
    else:
        assert result["status"] in {"BLOCKED_REMOTE", "BLOCKED_DEPENDENCY"}
