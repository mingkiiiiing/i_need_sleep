from __future__ import annotations

import csv
from pathlib import Path

from scripts.audit_source_field_aliases import load_alias_lookup, load_p0_p1_rows, split_fields


ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
AUDIT_PATH = STORAGE / "exports" / "source_field_mapping_audit.csv"
UNMAPPED_PATH = STORAGE / "exports" / "unmapped_fields.csv"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_p0_p1_fields_are_all_audited_as_mapped_or_unmapped() -> None:
    assert load_alias_lookup()
    expected = {(row["source_id"], field) for row in load_p0_p1_rows() for field in split_fields(row["key_variables"])}
    audit = _rows(AUDIT_PATH)
    unmapped = _rows(UNMAPPED_PATH)
    observed = {(row["source_id"], row["raw_field"]) for row in audit}

    assert expected == observed
    assert audit
    assert all(row["mapping_status"] in {"mapped", "unmapped"} for row in audit)
    assert all((row["mapping_status"] == "mapped") == bool(row["mapped_variable"]) for row in audit)
    assert {(row["source_id"], row["raw_field"]) for row in unmapped} == {
        (row["source_id"], row["raw_field"]) for row in audit if row["mapping_status"] == "unmapped"
    }
    assert all(row["reason"] for row in unmapped)


def test_priority_source_aliases_cover_protocol_remote_sensing_and_forecast_fields() -> None:
    audit = {(row["source_id"], row["raw_field"]): row["mapped_variable"] for row in _rows(AUDIT_PATH)}
    assert audit[("hj1404_station_protocol", "value")] == "observed_value"
    assert audit[("hj1404_station_protocol", "status")] == "quality_flags"
    assert audit[("cdse_sentinel2_l2a", "B02")] == "band_b02_reflectance"
    assert audit[("clms_lwq_nrt_300m_v2", "CHLAMEAN")] == "remote_chlorophyll_a"
    assert audit[("clms_lwq_nrt_300m_v2", "CHLAUNC")] == "remote_uncertainty"
    assert audit[("ecmwf_open_ifs_aifs", "2m_temperature")] == "air_temperature"
    assert audit[("nasa_power_hourly", "WS10M")] == "wind_speed"
    assert audit[("open_meteo_forecast", "wind_speed_10m")] == "wind_speed"
    assert audit[("nesdc_taihu_2007_2015", "SiO3")] == ""
    assert audit[("hj1404_station_protocol", "parameter_code")] == ""

