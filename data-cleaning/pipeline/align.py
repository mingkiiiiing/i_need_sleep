from __future__ import annotations

"""Auditable time/space alignment of resampled Taihu series.

The output is a relation table rather than a wide table.  Each row records one
target observation and one candidate driver, including the time gap, spatial
distance (when both records have coordinates), and an explicit match status.
This avoids silently pretending that a temporal-only match is spatially exact.
"""

import csv
import json
import math
import sqlite3
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resample import _float_or_none, _json_or_empty, _parse_time


WATER_QUALITY_VARIABLES = {
    "pH", "cod_mn", "dissolved_oxygen", "total_phosphorus", "phosphate_phosphorus",
    "total_nitrogen", "ammonia_nitrogen", "nitrate_nitrogen", "nitrite_nitrogen",
    "phytoplankton_biomass", "chlorophyll_a", "algae_density", "cyanobacteria_biomass",
}
METEOROLOGY_VARIABLES = {
    "air_temperature", "wind_speed", "wind_direction", "precipitation",
    "shortwave_radiation", "cloud_cover", "pressure", "par", "relative_humidity",
}
HYDROLOGY_VARIABLES = {"water_level", "discharge", "velocity", "water_flow", "water_temperature"}


def _category(row: dict[str, Any]) -> str:
    source_id = str(row.get("source_id") or "")
    variable = str(row.get("variable_code") or "")
    if source_id.startswith("copernicus_") or row.get("scene_id") or variable.startswith("remote_"):
        return "remote_sensing"
    if variable in WATER_QUALITY_VARIABLES:
        return "water_quality"
    if variable in METEOROLOGY_VARIABLES:
        return "meteorology"
    if variable in HYDROLOGY_VARIABLES:
        return "hydrology"
    return "other"


def read_resampled_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for key in ("clean_value", "observed_value", "longitude", "latitude", "aggregation_coverage"):
                row[key] = _float_or_none(row.get(key))
            try:
                row["n_obs"] = int(float(row.get("n_obs") or 0))
            except (TypeError, ValueError):
                row["n_obs"] = 0
            row["quality_flags"] = _json_or_empty(row.get("quality_flags"))
            row["_time"] = _parse_time(row.get("time_bucket") or row.get("observed_at"))
            row["_category"] = _category(row)
            rows.append(row)
    return rows


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


def _series_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("source_id"), row.get("station_id"), row.get("scene_id"), row.get("variable_code"))


def _candidate_spatial(target: dict[str, Any], candidate: dict[str, Any], max_space_m: float) -> tuple[int, float | None, str]:
    target_station = target.get("station_id")
    candidate_station = candidate.get("station_id")
    if target_station and candidate_station and target_station == candidate_station:
        return 0, 0.0, "same_station"
    coords = (target.get("longitude"), target.get("latitude"), candidate.get("longitude"), candidate.get("latitude"))
    if all(value is not None for value in coords):
        distance = _haversine_m(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))
        if distance <= max_space_m:
            return 1, distance, "coordinate_distance"
        return 99, distance, "outside_radius"
    return 2, None, "not_available"


def _nearest_in_series(target: dict[str, Any], series_index: tuple[list[datetime], list[dict[str, Any]]], max_time_diff_hours: float, max_space_m: float) -> tuple[dict[str, Any] | None, float | None, float | None, str]:
    times, valid_rows = series_index
    if not times or target.get("_time") is None:
        return None, None, None, "no_candidate"
    position = bisect_left(times, target["_time"])
    best: tuple[tuple[float, float, float], dict[str, Any], float | None, str] | None = None
    for index in {max(0, position - 1), min(len(valid_rows) - 1, position)}:
        candidate = valid_rows[index]
        time_gap = abs((candidate["_time"] - target["_time"]).total_seconds()) / 3600.0
        if time_gap > max_time_diff_hours:
            continue
        spatial_rank, distance, spatial_status = _candidate_spatial(target, candidate, max_space_m)
        if spatial_rank >= 99:
            continue
        distance_score = distance if distance is not None else 0.0
        score = (float(spatial_rank), time_gap, distance_score)
        if best is None or score < best[0]:
            best = (score, candidate, distance, spatial_status)
    if best is None:
        return None, None, None, "no_match_within_threshold"
    return best[1], best[0][1], best[2], best[3]


def align_records(
    rows: list[dict[str, Any]],
    *,
    max_time_diff_hours: float = 72.0,
    max_space_m: float = 50_000.0,
) -> dict[str, Any]:
    targets = [row for row in rows if row.get("_category") in {"water_quality", "remote_sensing"} and row.get("clean_value") is not None]
    series_by_variable: dict[str, list[tuple[list[datetime], list[dict[str, Any]]]]] = defaultdict(list)
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("_category") in {"meteorology", "hydrology", "remote_sensing", "water_quality"} and row.get("clean_value") is not None:
            grouped[_series_key(row)].append(row)
    for series in grouped.values():
        ordered = sorted(series, key=lambda item: item.get("_time") or datetime.max.replace(tzinfo=timezone.utc))
        valid = [row for row in ordered if row.get("_time") is not None and row.get("clean_value") is not None]
        series_by_variable[str(series[0].get("variable_code") or "")].append(([row["_time"] for row in valid], valid))

    alignments: list[dict[str, Any]] = []
    match_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    for target in targets:
        target_category = str(target.get("_category"))
        target_counts[target_category] += 1
        for variable, series_list in sorted(series_by_variable.items()):
            if variable == target.get("variable_code") and target_category == _category(target):
                continue
            # Only drivers that can be used by the first-release model are
            # emitted; unrelated archive variables stay in the resampled table.
            feature_category = _category(series_list[0][1][0]) if series_list[0][1] else "other"
            if feature_category not in {"meteorology", "hydrology", "remote_sensing", "water_quality"}:
                continue
            best: tuple[tuple[float, int, float], dict[str, Any], float | None, float | None, str] | None = None
            for series_index in series_list:
                candidate, time_gap, space_gap, spatial_status = _nearest_in_series(target, series_index, max_time_diff_hours, max_space_m)
                if candidate is None or time_gap is None:
                    continue
                rank = 0 if spatial_status == "same_station" else 1 if spatial_status == "coordinate_distance" else 2
                distance_score = space_gap if space_gap is not None else 0.0
                score = (time_gap, rank, distance_score)
                if best is None or score < best[0]:
                    best = (score, candidate, time_gap, space_gap, spatial_status)
            if best is None:
                alignments.append(
                    {
                        "target_source_id": target.get("source_id"), "target_station_id": target.get("station_id"),
                        "target_scene_id": target.get("scene_id"),
                        "target_variable_code": target.get("variable_code"), "target_time_bucket": target.get("time_bucket"),
                        "target_clean_value": target.get("clean_value"), "feature_source_id": None,
                        "feature_station_id": None, "feature_scene_id": None, "feature_variable_code": variable,
                        "feature_time_bucket": None, "feature_clean_value": None,
                        "time_gap_hours": None, "space_gap_m": None,
                        "target_category": target_category, "feature_category": feature_category,
                        "spatial_status": "not_available", "match_status": "unmatched",
                        "quality_flags": ["Q23"],
                    }
                )
                match_counts["unmatched"] += 1
                continue
            candidate = best[1]
            status = "matched_temporal_spatial" if best[4] in {"same_station", "coordinate_distance"} else "matched_temporal_only"
            flags = []
            if status == "matched_temporal_only":
                flags.append("Q23")
            alignments.append(
                {
                    "target_source_id": target.get("source_id"), "target_station_id": target.get("station_id"),
                    "target_scene_id": target.get("scene_id"),
                    "target_variable_code": target.get("variable_code"), "target_time_bucket": target.get("time_bucket"),
                    "target_clean_value": target.get("clean_value"), "feature_source_id": candidate.get("source_id"),
                    "feature_station_id": candidate.get("station_id"), "feature_scene_id": candidate.get("scene_id"), "feature_variable_code": variable,
                    "feature_time_bucket": candidate.get("time_bucket"), "feature_clean_value": candidate.get("clean_value"),
                    "time_gap_hours": round(float(best[2]), 6), "space_gap_m": None if best[3] is None else round(float(best[3]), 3),
                    "target_category": target_category, "feature_category": feature_category,
                    "spatial_status": best[4], "match_status": status, "quality_flags": flags,
                }
            )
            match_counts[status] += 1
    return {
        "records": alignments,
        "target_counts": dict(target_counts),
        "match_counts": dict(match_counts),
        "series_count": sum(len(items) for items in series_by_variable.values()),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    return len(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS temporal_alignments")
        connection.execute(
            """CREATE TABLE temporal_alignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_source_id TEXT, target_station_id TEXT, target_scene_id TEXT, target_variable_code TEXT,
                target_time_bucket TEXT, target_clean_value REAL,
                feature_source_id TEXT, feature_station_id TEXT, feature_scene_id TEXT, feature_variable_code TEXT,
                feature_time_bucket TEXT, feature_clean_value REAL,
                time_gap_hours REAL, space_gap_m REAL,
                target_category TEXT, feature_category TEXT,
                spatial_status TEXT, match_status TEXT, quality_flags TEXT
            )"""
        )
        columns = [
            "target_source_id", "target_station_id", "target_scene_id", "target_variable_code", "target_time_bucket", "target_clean_value",
            "feature_source_id", "feature_station_id", "feature_scene_id", "feature_variable_code", "feature_time_bucket", "feature_clean_value",
            "time_gap_hours", "space_gap_m", "target_category", "feature_category", "spatial_status", "match_status", "quality_flags",
        ]
        sql = f"INSERT INTO temporal_alignments ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
        connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in columns) for row in rows])
        connection.commit()
    finally:
        connection.close()


def run_alignment(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, max_time_diff_hours: float = 72.0, max_space_m: float = 50_000.0, manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    rows = read_resampled_csv(input_path)
    result = align_records(rows, max_time_diff_hours=max_time_diff_hours, max_space_m=max_space_m)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or Path(__file__).resolve().parents[1] / "storage" / "exports" / f"align_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "temporal_alignments.csv"
    _write_csv(output, result["records"])
    database = database or Path(__file__).resolve().parents[1] / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["records"])
    manifest = {
        "run_id": run_id or f"align_{stamp}",
        "status": "completed_with_temporal_only_or_unmatched" if any(row.get("match_status") != "matched_temporal_spatial" for row in result["records"]) else "completed",
        "input": str(input_path), "output": str(output), "database": str(database),
        "input_rows": len(rows), "alignment_rows": len(result["records"]),
        "target_counts": result["target_counts"], "match_counts": result["match_counts"], "series_count": result["series_count"],
        "thresholds": {"max_time_diff_hours": max_time_diff_hours, "max_space_m": max_space_m},
        "spatial_policy": "same station or both coordinates within radius; otherwise temporal-only with Q23; never fabricate distance",
    }
    manifest_path = manifest_path or Path(__file__).resolve().parents[1] / "storage" / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
