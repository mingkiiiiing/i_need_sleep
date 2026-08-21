"""Revalidate the downloaded THQBCA archive and its parsed long table."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .sources.zenodo import list_thqbca_archive


REQUIRED_MEMBERS = {
    "THQBCA-V2/1.WaterQuality/1WaterQuality.xlsx",
    "THQBCA-V2/3.Climate/3.Climate.xlsx",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_summary(path: Path) -> dict[str, Any]:
    records = 0
    by_variable: dict[str, int] = {}
    observed_times: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            records += 1
            variable = str(row.get("variable_code") or "")
            by_variable[variable] = by_variable.get(variable, 0) + 1
            observed_at = str(row.get("observed_at") or "")
            if observed_at:
                observed_times.append(observed_at)
    observed_times.sort()
    return {
        "records": records,
        "by_variable": by_variable,
        "observed_at_min": observed_times[0] if observed_times else None,
        "observed_at_max": observed_times[-1] if observed_times else None,
    }


def revalidate_thqbca(
    archive: Path,
    download_manifest: Path,
    listing_manifest: Path,
    parse_manifest: Path,
    parsed_csv: Path,
    output_manifest: Path,
    *,
    refreshed_listing_manifest: Path | None = None,
) -> dict[str, Any]:
    """Run reproducible integrity checks without downloading the archive again."""

    archive = Path(archive)
    download_manifest = Path(download_manifest)
    listing_manifest = Path(listing_manifest)
    parse_manifest = Path(parse_manifest)
    parsed_csv = Path(parsed_csv)
    output_manifest = Path(output_manifest)
    refreshed_listing_manifest = refreshed_listing_manifest or output_manifest.with_name(
        "thqbca_archive_listing_revalidated.json"
    )

    expected_download = _read_json(download_manifest)
    previous_listing = _read_json(listing_manifest)
    previous_parse = _read_json(parse_manifest)
    actual_md5 = _md5(archive)
    actual_size = archive.stat().st_size
    refreshed_listing = list_thqbca_archive(archive, refreshed_listing_manifest)
    refreshed_payload = _read_json(refreshed_listing_manifest)
    csv_summary = _csv_summary(parsed_csv)

    expected_members = sorted(str(item).replace("\\", "/") for item in previous_listing.get("members", []))
    actual_members = sorted(str(item).replace("\\", "/") for item in refreshed_payload.get("members", []))
    members_match = expected_members == actual_members
    required_members_present = REQUIRED_MEMBERS.issubset(set(actual_members))
    row_count_match = int(previous_parse.get("records", -1)) == csv_summary["records"]
    variable_counts_match = previous_parse.get("by_variable", {}) == csv_summary["by_variable"]
    time_range_match = (
        previous_parse.get("observed_at_min") == csv_summary["observed_at_min"]
        and previous_parse.get("observed_at_max") == csv_summary["observed_at_max"]
    )
    checks = {
        "archive_exists": archive.is_file(),
        "archive_size_match": actual_size == int(expected_download.get("size", -1)),
        "archive_md5_match": actual_md5.lower() == str(expected_download.get("md5", "")).lower(),
        "archive_manifest_verified": bool(expected_download.get("verified")),
        "member_count_match": int(previous_listing.get("member_count", -1)) == int(refreshed_payload.get("member_count", -2)),
        "members_match": members_match,
        "required_workbooks_present": required_members_present,
        "parsed_row_count_match": row_count_match,
        "parsed_variable_counts_match": variable_counts_match,
        "parsed_time_range_match": time_range_match,
    }
    status = "verified" if all(checks.values()) else "failed"
    result = {
        "task_id": "P04-01",
        "status": status,
        "data_truth": "real_external",
        "archive": str(archive),
        "download_manifest": str(download_manifest),
        "listing_manifest": str(listing_manifest),
        "refreshed_listing_manifest": str(refreshed_listing_manifest),
        "parse_manifest": str(parse_manifest),
        "parsed_csv": str(parsed_csv),
        "archive_observed": {"size": actual_size, "md5": actual_md5},
        "parsed_observed": csv_summary,
        "checks": checks,
        "expected": {
            "size": expected_download.get("size"),
            "md5": expected_download.get("md5"),
            "member_count": previous_listing.get("member_count"),
            "records": previous_parse.get("records"),
            "observed_at_min": previous_parse.get("observed_at_min"),
            "observed_at_max": previous_parse.get("observed_at_max"),
        },
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
