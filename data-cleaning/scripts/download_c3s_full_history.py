"""Download the Taihu C3S monthly seasonal archive without duplicate hindcasts."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.sources.c3s_seasonal import run_c3s_seasonal


MANIFEST = STORAGE / "manifests" / "c3s_seasonal_full_2016_2026.json"


def _compact(result: dict) -> dict:
    return {
        "status": result.get("status"),
        "records": result.get("records", 0),
        "output": result.get("output"),
        "assets": result.get("assets", []),
    }


def _completed_manifest(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if payload.get("status") == "completed" else None


def _write_progress(outcomes: list[dict]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_period": "2016-01 through 2026-12 initialisations",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_units": sum(item["status"] == "completed" for item in outcomes),
        "total_units": 132,
        "failed_units": sum(item["status"] != "completed" for item in outcomes),
        "outcomes": outcomes,
    }
    temporary = MANIFEST.with_suffix(".json.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(MANIFEST)


def main() -> int:
    outcomes: list[dict] = []
    for month in range(1, 13):
        path = STORAGE / "manifests" / f"c3s_hindcast_{month:02d}.json"
        result = _completed_manifest(path) or run_c3s_seasonal(
            2016, month, include_hindcast=True, include_forecast=False, manifest_path=path,
        )
        outcomes.append({"kind": "hindcast", "month": month, **_compact(result)})
        _write_progress(outcomes)

    for year in range(2017, 2027):
        for month in range(1, 13):
            path = STORAGE / "manifests" / f"c3s_forecast_{year}_{month:02d}.json"
            result = _completed_manifest(path) or run_c3s_seasonal(
                year, month, include_hindcast=False, include_forecast=True, manifest_path=path,
            )
            outcomes.append({"kind": "forecast", "year": year, "month": month, **_compact(result)})
            _write_progress(outcomes)
    return 0 if all(item["status"] == "completed" for item in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
