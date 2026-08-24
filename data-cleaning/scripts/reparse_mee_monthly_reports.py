from __future__ import annotations

import csv
import json
from pathlib import Path

from pipeline.sources.mee_monthly_reports import DEFAULT_MANIFEST, DEFAULT_SILVER, parse_taihu_section


def main() -> None:
    csv_path = DEFAULT_SILVER / "mee_taihu_monthly_2022_2026.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    parsed_fields = set()
    for row in rows:
        text_path = Path(row["taihu_text_path"])
        parsed = parse_taihu_section(text_path.read_text(encoding="utf-8")) if text_path.exists() else {}
        row.update({key: "" if value is None else value for key, value in parsed.items()})
        parsed_fields.update(parsed)
    fieldnames = list(rows[0])
    fieldnames.extend(sorted(parsed_fields - set(fieldnames)))
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    if DEFAULT_MANIFEST.exists():
        manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        by_period = {row["period"]: row for row in rows}
        manifest["rows"] = [by_period.get(row["period"], row) for row in manifest.get("rows", [])]
        manifest["parser_revision"] = "lake-only fields stop before 1.2 环湖河流"
        DEFAULT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(csv_path, len(rows))


if __name__ == "__main__":
    main()
