"""Index THQBCA annual remote-sensing raster members without extracting rasters."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


REMOTE_PRODUCT_SPECS = {
    "vege": {"product_family": "aquatic_vegetation", "variable_code": "aquatic_vegetation_class", "unit": "category"},
    "FAC": {"product_family": "floating_algae_cover", "variable_code": "fai", "unit": "dimensionless"},
    "SDD": {"product_family": "secchi_depth", "variable_code": "secchi_depth", "unit": "m"},
    "Chla": {"product_family": "chlorophyll_a", "variable_code": "remote_chlorophyll_a", "unit": "ug/L"},
    "TSI": {"product_family": "trophic_state_index", "variable_code": "trophic_state_index", "unit": "index"},
}
MEMBER_RE = re.compile(r"^THQBCA-V2/2\.Bio-optics/2\.[1-5](?:[^/]*)/TH_(?P<family>[^_]+)_(?P<period>\d{4}(?:-\d{2}-\d{2})?)\.tif$", re.IGNORECASE)


def build_remote_product_index(listing_manifest: Path, output_csv: Path, index_manifest: Path) -> dict[str, Any]:
    """Create a provenance-only index; pixel values remain unextracted."""

    listing = json.loads(Path(listing_manifest).read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for member in listing.get("members", []):
        normalized = str(member).replace("\\", "/")
        match = MEMBER_RE.match(normalized)
        if not match:
            if "/2.Bio-optics/" in normalized and normalized.lower().endswith(".tif"):
                unmatched.append(normalized)
            continue
        family_key = match.group("family")
        spec = REMOTE_PRODUCT_SPECS.get(family_key) or REMOTE_PRODUCT_SPECS.get(family_key.capitalize())
        if spec is None:
            unmatched.append(normalized)
            continue
        period = match.group("period")
        records.append({
            "source_id": "taihu_thqbca_history",
            "source_member": normalized,
            "product_family": spec["product_family"],
            "variable_code": spec["variable_code"],
            "source_parameter": family_key,
            "product_period": period,
            "product_year": int(period[:4]),
            "unit": spec["unit"],
            "asset_type": "GeoTIFF",
            "asset_status": "archive_member_only",
            "value_status": "not_extracted",
            "value_origin": "remote_product_index",
            "conversion_rule": "Index only; extract and spatially summarize the raster in a later remote-sensing task",
            "license_tag": "THQBCA-Zenodo-record-license-review",
        })
    records.sort(key=lambda row: (row["product_family"], row["product_period"], row["source_member"]))
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0]) if records else [
        "source_id", "source_member", "product_family", "variable_code", "source_parameter",
        "product_period", "product_year", "unit", "asset_type", "asset_status", "value_status",
        "value_origin", "conversion_rule", "license_tag",
    ]
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    by_family: dict[str, int] = {}
    for row in records:
        by_family[row["product_family"]] = by_family.get(row["product_family"], 0) + 1
    result = {
        "source_id": "taihu_thqbca_history",
        "listing_manifest": str(listing_manifest),
        "output_csv": str(output_csv),
        "records": len(records),
        "by_family": by_family,
        "unmatched_raster_members": unmatched,
        "value_status": "not_extracted",
        "asset_status": "archive_member_only",
        "data_truth": "real_external_metadata",
    }
    index_manifest = Path(index_manifest)
    index_manifest.parent.mkdir(parents=True, exist_ok=True)
    index_manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
