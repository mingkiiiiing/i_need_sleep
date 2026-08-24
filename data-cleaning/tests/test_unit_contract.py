from __future__ import annotations

import pytest

from pipeline.units import standardize_units


def _row(variable_code: str, unit: str, value: float) -> dict[str, object]:
    return {
        "source_id": "unit_contract_fixture",
        "source_file": "unit_contract.csv",
        "source_row": "1",
        "variable_code": variable_code,
        "unit": unit,
        "clean_value": value,
        "observed_value": value,
        "quality_flags": [],
    }


@pytest.mark.parametrize(
    ("variable_code", "source_unit", "value", "expected_unit", "expected_value", "rule"),
    [
        ("chlorophyll_a", "mg/m³", 2.5, "ug/L", 2.5, "mg/m3->ug/L"),
        ("algae_density", "cells/mL", 12.0, "cells/L", 12000.0, "cells/mL->cells/L"),
        ("algae_density", "cells/m3", 12000.0, "cells/L", 12.0, "cells/m3->cells/L"),
        ("water_level", "cm", 150.0, "m", 1.5, "cm->m"),
        ("precipitation", "mm/day", 24.0, "mm", 24.0, "mm/day->mm"),
        ("shortwave_radiation", "Wh/m²", 360.0, "W/m2", 360.0, "Wh/m2->W/m2"),
    ],
)
def test_required_unit_conversions_are_explicit(
    variable_code: str,
    source_unit: str,
    value: float,
    expected_unit: str,
    expected_value: float,
    rule: str,
) -> None:
    row = _row(variable_code, source_unit, value)
    standardize_units([row])
    assert row["source_unit"] == source_unit
    assert row["unit"] == expected_unit
    assert row["clean_value"] == pytest.approx(expected_value)
    assert rule in str(row["conversion_rule"])
    assert row["unit_valid"] is True
    assert "Q21" in row["quality_flags"]


def test_unknown_unit_is_not_guessed() -> None:
    row = _row("water_level", "fathom", 1.0)
    standardize_units([row])
    assert row["unit_valid"] is False
    assert row["unit_issue"] == "Q11"
    assert row["unit"] == "fathom"

