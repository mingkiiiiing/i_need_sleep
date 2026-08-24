import csv
from pathlib import Path


REGISTRY = Path(__file__).parents[1] / "config" / "data_source_registry.csv"
CHECKLIST = Path(__file__).parents[1] / "config" / "luna_execution_checklist.csv"


def _rows():
    with REGISTRY.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_license_fields_are_complete_and_conservative():
    rows = _rows()
    required = {
        "license_tag",
        "redistribution_allowed",
        "commercial_use",
        "attribution_text",
        "authorization_evidence_path",
    }
    assert rows
    assert len({row["source_id"] for row in rows}) == len(rows)
    assert required.issubset(rows[0])

    allowed = {"yes", "conditional", "pending_review", "no"}
    for row in rows:
        for field in required:
            assert row[field].strip(), (row["source_id"], field)
        assert row["redistribution_allowed"] in allowed
        assert row["commercial_use"] in allowed
        assert row["authorization_evidence_path"].startswith(
            "storage/manifests/authorizations/"
        )
        assert row["authorization_evidence_path"].endswith(".json")


def test_known_open_licenses_and_restricted_defaults():
    rows = {row["source_id"]: row for row in _rows()}
    for source_id in ("hydrolakes", "hydrobasins", "esa_worldcover"):
        assert rows[source_id]["license_tag"] == "CC-BY-4.0"
        assert rows[source_id]["redistribution_allowed"] == "yes"
        assert rows[source_id]["commercial_use"] == "yes"
    assert rows["bst_oli_code"]["license_tag"] == "MIT"
    assert rows["bst_oli_code"]["redistribution_allowed"] == "yes"
    assert rows["cdse_sentinel2_l2a"]["redistribution_allowed"] != "yes"
    assert rows["mee_surface_water_realtime"]["redistribution_allowed"] != "yes"


def test_completed_dependencies_and_no_future_task_started():
    with CHECKLIST.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    status = {row["task_id"]: row["status"] for row in rows}
    assert status["P01-06"] == "DONE"
    assert status["P01-07"] == "DONE"
    assert status["P02-01"] == "DONE"
    assert status["P02-02"] in {"IN_PROGRESS", "DONE"}
    assert status["P02-03"] in {"IN_PROGRESS", "DONE"}
    assert status["P02-04"] in {"IN_PROGRESS", "DONE"}
    assert status["P02-05"] in {"IN_PROGRESS", "DONE"}
    assert status["P02-06"] in {"IN_PROGRESS", "DONE"}
    assert status["P02-07"] in {"IN_PROGRESS", "DONE"}
    assert status["P03-01"] in {"IN_PROGRESS", "DONE"}
    assert status["P03-02"] in {"IN_PROGRESS", "DONE"}
    assert status["P03-03"] in {"IN_PROGRESS", "DONE"}
    assert status["P03-04"] in {"IN_PROGRESS", "DONE"}
    assert status["P03-05"] in {"IN_PROGRESS", "DONE"}
    assert status["P03-06"] in {"IN_PROGRESS", "DONE"}
    assert status["P04-01"] in {"IN_PROGRESS", "DONE"}
    assert status["P04-02"] in {"IN_PROGRESS", "DONE"}
    assert status["P04-03"] in {"IN_PROGRESS", "DONE"}
    assert status["P04-04"] in {"IN_PROGRESS", "DONE", "BLOCKED_AUTH"}
    assert status["P04-05"] in {"IN_PROGRESS", "DONE", "BLOCKED_DATA"}
    assert status["P04-06"] in {"IN_PROGRESS", "DONE", "BLOCKED_METADATA", "BLOCKED_DATA"}
    assert status["P05-01"] in {"IN_PROGRESS", "DONE", "BLOCKED_DEPENDENCY", "BLOCKED_REMOTE"}
    assert status["P05-02"] in {"IN_PROGRESS", "DONE", "BLOCKED_DATA"}
    assert status["P05-03"] in {"IN_PROGRESS", "DONE", "BLOCKED_REMOTE", "BLOCKED_DEPENDENCY"}
    assert status["P05-04"] in {"IN_PROGRESS", "DONE", "BLOCKED_AUTH", "BLOCKED_DEPENDENCY"}
