from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
REGISTRY_PATH = ROOT / "config" / "data_source_registry.csv"
ALIASES_PATH = ROOT / "config" / "aliases.yml"
AUDIT_PATH = STORAGE / "exports" / "source_field_mapping_audit.csv"
UNMAPPED_PATH = STORAGE / "exports" / "unmapped_fields.csv"

SEMANTIC_GROUPS = {
    "water_quality",
    "biology",
    "meteorology",
    "sediment",
    "remote_sensing",
    "candidate_station_water_quality",
    "hydrology",
    "climate",
    "water_quality_summary",
    "dispatch",
    "quality_index",
}

METADATA_FIELDS = {
    "parameter_code",
    "product_metadata",
    "s3_path",
    "size",
    "station",
}


def normalize(value: str) -> str:
    # Keep Unicode letters (including Chinese aliases) while removing spaces,
    # underscores and punctuation. This avoids collapsing "叶绿素a" and
    # "遥感叶绿素a" into the same one-letter key.
    return re.sub(r"[^\w]+", "", value.casefold(), flags=re.UNICODE)


def load_alias_lookup() -> dict[str, str]:
    config = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8"))
    aliases = config.get("aliases", {})
    lookup: dict[str, str] = {}
    collisions: dict[str, set[str]] = {}
    for canonical, values in aliases.items():
        for alias in [canonical, *values]:
            key = normalize(str(alias))
            if not key:
                continue
            if key in lookup and lookup[key] != canonical:
                collisions.setdefault(key, {lookup[key]}).add(canonical)
            else:
                lookup[key] = canonical
    if collisions:
        details = ", ".join(f"{key}: {sorted(values)}" for key, values in sorted(collisions.items()))
        raise ValueError(f"ambiguous aliases: {details}")
    return lookup


def classify_field(raw_field: str, lookup: dict[str, str]) -> tuple[str, str, str]:
    stripped = raw_field.strip()
    normalized = normalize(stripped)
    if stripped.casefold() in SEMANTIC_GROUPS:
        return "", "unmapped", "semantic_group_requires_dataset_schema"
    if stripped.casefold() in METADATA_FIELDS:
        return "", "unmapped", "metadata_or_protocol_field_requires_adapter_schema"
    mapped = lookup.get(normalized)
    if mapped:
        return mapped, "mapped", "unique_alias"
    return "", "unmapped", "no_safe_standard_variable_alias"


def load_p0_p1_rows() -> list[dict[str, str]]:
    with REGISTRY_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row["priority"] in {"P0", "P1"}]


def split_fields(value: str) -> list[str]:
    fields: list[str] = []
    for part in re.split(r"[,;]", value):
        part = part.strip()
        if not part:
            continue
        # A legacy registry row contains the note
        # "lake stations may include chlorophyll_a and algae_density" inside
        # the key-variable cell. Extract the two actual fields rather than
        # treating the prose as one variable name.
        if "may include" in part.casefold():
            tail = part.split("may include", 1)[1]
            fields.extend(item.strip() for item in tail.replace(" and ", ",").split(",") if item.strip())
        else:
            fields.append(part)
    return fields


def main() -> None:
    lookup = load_alias_lookup()
    audit_rows: list[dict[str, str]] = []
    for source in load_p0_p1_rows():
        raw_fields = split_fields(source["key_variables"])
        for raw_field in raw_fields:
            mapped, status, reason = classify_field(raw_field, lookup)
            audit_rows.append(
                {
                    "source_id": source["source_id"],
                    "priority": source["priority"],
                    "raw_field": raw_field,
                    "mapped_variable": mapped,
                    "mapping_status": status,
                    "reason": reason,
                }
            )
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_id", "priority", "raw_field", "mapped_variable", "mapping_status", "reason"]
    for path, rows in ((AUDIT_PATH, audit_rows), (UNMAPPED_PATH, [row for row in audit_rows if row["mapping_status"] == "unmapped"])):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    mapped_count = sum(row["mapping_status"] == "mapped" for row in audit_rows)
    unmapped_count = len(audit_rows) - mapped_count
    print({"p0_p1_field_count": len(audit_rows), "mapped_count": mapped_count, "unmapped_count": unmapped_count, "audit": str(AUDIT_PATH), "unmapped": str(UNMAPPED_PATH)})


if __name__ == "__main__":
    main()
