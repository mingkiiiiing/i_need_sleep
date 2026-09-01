from __future__ import annotations

"""Sentinel-2 pixel indexing, scene summaries and ground calibration.

The module accepts a local pixel table exported from Sentinel-2 L2A assets. It
does not download or invent unavailable bands. Reflectance scaling is always an
explicit command-line parameter; if a band, cloud layer or water mask is
missing, the output keeps a quality flag and leaves the derived value null.
"""

import csv
import json
import math
import re
import sqlite3
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
Q_REMOTE_INVALID = "Q30"
Q_REMOTE_BAND_MISSING = "Q31"
Q_REMOTE_QUALITY_MISSING = "Q32"
Q_REMOTE_UNCALIBRATED = "Q33"
Q_REMOTE_COVERAGE = "Q34"
Q_REMOTE_COORD = "Q35"

REMOTE_ALIASES = {
    "scene_id": {"scene_id", "scene", "product_id", "granule_id", "影像编号", "场景编号"},
    "acquisition_at": {"acquisition_at", "acquisition_time", "sensing_time", "datetime", "time", "过境时间", "影像时间"},
    "pixel_id": {"pixel_id", "row_col", "pixel", "像元编号", "像元索引"},
    "longitude": {"longitude", "lon", "lng", "x", "经度", "东经"},
    "latitude": {"latitude", "lat", "y", "纬度", "北纬"},
    "pixel_area_km2": {"pixel_area_km2", "pixel_area", "area_km2", "像元面积"},
    "band_b02_reflectance": {"band_b02_reflectance", "b02", "b2", "blue", "blue_reflectance"},
    "band_b03_reflectance": {"band_b03_reflectance", "b03", "b3", "green", "green_reflectance"},
    "band_b04_reflectance": {"band_b04_reflectance", "b04", "b4", "red", "red_reflectance"},
    "band_b05_reflectance": {"band_b05_reflectance", "b05", "b5", "red_edge_1", "b05_reflectance"},
    "band_b08_reflectance": {"band_b08_reflectance", "b08", "b8", "nir", "near_infrared", "b08_reflectance"},
    "band_b11_reflectance": {"band_b11_reflectance", "b11", "swir1", "b11_reflectance"},
    "scene_classification": {"scene_classification", "scl", "场景分类"},
    "cloud_probability": {"cloud_probability", "cloud_prob", "cld", "云概率", "云量"},
    "water_mask": {"water_mask", "water", "lake_mask", "水体掩膜"},
}


def _norm_header(value: Any) -> str:
    return re.sub(r"[\s\-./]+", "_", str(value or "").strip().casefold())


def _parse_time(value: Any) -> datetime | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(str(value), fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    if value in (None, "", "null", "None", "NoData", "nodata"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool | None:
    if value in (None, "", "null", "None"):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "water", "是"}:
        return True
    if text in {"0", "false", "no", "n", "land", "否"}:
        return False
    try:
        return bool(float(text))
    except ValueError:
        return None


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


def _canonical_columns(headers: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    lookup: dict[str, str] = {}
    for canonical, aliases in REMOTE_ALIASES.items():
        for alias in aliases:
            lookup[_norm_header(alias)] = canonical
    mapping: dict[str, str] = {}
    conflicts: list[str] = []
    for header in headers:
        canonical = lookup.get(_norm_header(header))
        if canonical:
            if canonical in mapping.values():
                conflicts.append(canonical)
            else:
                mapping[header] = canonical
        else:
            mapping[header] = str(header)
    return mapping, sorted(set(conflicts))


def _read_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if path.suffix.casefold() in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "features" in payload:
            raw_rows = []
            for feature in payload.get("features", []):
                row = dict(feature.get("properties") or {})
                row.update({"scene_id": feature.get("id"), "geometry": feature.get("geometry")})
                raw_rows.append(row)
        elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            raw_rows = payload["rows"]
        elif isinstance(payload, list):
            raw_rows = payload
        else:
            raw_rows = [payload]
        headers = sorted({key for row in raw_rows if isinstance(row, dict) for key in row})
        mapping, conflicts = _canonical_columns(headers)
        return [{mapping.get(key, key): value for key, value in row.items()} for row in raw_rows if isinstance(row, dict)], conflicts
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        mapping, conflicts = _canonical_columns(reader.fieldnames or [])
        rows = [{mapping.get(key, key): value for key, value in row.items()} for row in reader]
    return rows, conflicts


def _band(row: dict[str, Any], code: str, scale: float) -> float | None:
    value = _number(row.get(code))
    if value is None:
        return None
    return value * scale


def _water_valid(row: dict[str, Any], ndwi: float | None, scl: float | None, ndwi_threshold: float) -> tuple[bool | None, str]:
    explicit = _bool(row.get("water_mask"))
    if explicit is not None:
        return explicit, "source_water_mask"
    if scl is not None:
        return int(scl) == 6, "SCL_6_water"
    if ndwi is not None:
        return ndwi >= ndwi_threshold, "NDWI_threshold"
    return None, "not_available"


def _cloud_valid(row: dict[str, Any], scl: float | None, cloud_threshold: float) -> tuple[bool, str, bool]:
    flags = False
    cloud = _number(row.get("cloud_probability"))
    if cloud is None:
        flags = True
        cloud_ok = True
        method = "cloud_probability_missing"
    else:
        cloud_ok = cloud <= cloud_threshold
        method = "cloud_probability"
    if scl is not None and int(scl) in {3, 8, 9, 10, 11}:
        cloud_ok = False
        method = "SCL_cloud_or_snow"
    return cloud_ok, method, flags


def _index_values(b03: float | None, b04: float | None, b05: float | None, b08: float | None, b11: float | None) -> tuple[float | None, float | None, float | None, list[str]]:
    flags: list[str] = []
    ndwi = (b03 - b08) / (b03 + b08) if b03 is not None and b08 is not None and abs(b03 + b08) > 1e-12 else None
    if ndwi is None:
        flags.append(Q_REMOTE_BAND_MISSING)
    fai = None
    if b04 is not None and b08 is not None and b11 is not None:
        fai = b08 - (b04 + (b11 - b04) * (842.0 - 665.0) / (1610.0 - 665.0))
    else:
        flags.append(Q_REMOTE_BAND_MISSING)
    mci = None
    if b04 is not None and b05 is not None and b08 is not None:
        mci = b05 - (b04 + (b08 - b04) * (705.0 - 665.0) / (842.0 - 665.0))
    else:
        flags.append(Q_REMOTE_BAND_MISSING)
    return ndwi, fai, mci, sorted(set(flags))


def index_pixels(rows: list[dict[str, Any]], *, reflectance_scale: float = 1.0, cloud_threshold: float = 40.0, ndwi_water_threshold: float = 0.0, fai_threshold: float = 0.0, pixel_area_km2: float | None = None) -> dict[str, Any]:
    pixels: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        scene_id = str(row.get("scene_id") or "")
        timestamp = _parse_time(row.get("acquisition_at"))
        lon, lat = _number(row.get("longitude")), _number(row.get("latitude"))
        flags: list[str] = []
        if not scene_id or timestamp is None:
            flags.append(Q_REMOTE_INVALID)
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            flags.append(Q_REMOTE_COORD)
        bands = {code: _band(row, code, reflectance_scale) for code in ("band_b02_reflectance", "band_b03_reflectance", "band_b04_reflectance", "band_b05_reflectance", "band_b08_reflectance", "band_b11_reflectance")}
        for code, value in bands.items():
            if value is not None and not -0.1 <= value <= 3.0:
                flags.append(Q_REMOTE_INVALID)
        ndwi, fai, mci, index_flags = _index_values(bands["band_b03_reflectance"], bands["band_b04_reflectance"], bands["band_b05_reflectance"], bands["band_b08_reflectance"], bands["band_b11_reflectance"])
        flags.extend(index_flags)
        scl = _number(row.get("scene_classification"))
        water_valid, water_method = _water_valid(row, ndwi, scl, ndwi_water_threshold)
        if water_valid is None:
            flags.append(Q_REMOTE_QUALITY_MISSING)
        cloud_valid, cloud_method, cloud_missing = _cloud_valid(row, scl, cloud_threshold)
        if cloud_missing:
            flags.append(Q_REMOTE_QUALITY_MISSING)
        valid_pixel = bool(water_valid is True and cloud_valid and not any(flag in flags for flag in (Q_REMOTE_INVALID, Q_REMOTE_COORD, Q_REMOTE_BAND_MISSING)))
        area = _number(row.get("pixel_area_km2")) or pixel_area_km2
        bloom = bool(valid_pixel and fai is not None and fai > fai_threshold)
        output = {
            "source_id": "sentinel2_local_pixel",
            "source_file": str(row.get("source_file") or ""),
            "source_row": str(row.get("source_row") or index),
            "scene_id": scene_id,
            "acquisition_at": timestamp.isoformat() if timestamp else None,
            "pixel_id": row.get("pixel_id") or str(index),
            "longitude": lon,
            "latitude": lat,
            "pixel_area_km2": area,
            **bands,
            "scene_classification": scl,
            "cloud_probability": _number(row.get("cloud_probability")),
            "water_mask": water_valid,
            "water_mask_method": water_method,
            "cloud_valid": cloud_valid,
            "cloud_mask_method": cloud_method,
            "valid_pixel": valid_pixel,
            "ndwi": ndwi,
            "fai": fai,
            "mci": mci,
            "fai_threshold": fai_threshold,
            "remote_bloom_class": "suspected_bloom" if bloom else "clear_water" if valid_pixel else "invalid",
            "bloom_pixel_area_km2": area if bloom and area is not None else 0.0 if bloom else None,
            "remote_chlorophyll_a": None,
            "remote_chlorophyll_status": "not_calibrated",
            "value_origin": "derived",
            "quality_flags": sorted(set(flags + ([Q_REMOTE_UNCALIBRATED] if valid_pixel else []))),
        }
        pixels.append(output)
        grouped[scene_id].append(output)

    summaries: list[dict[str, Any]] = []
    for scene_id, scene_rows in sorted(grouped.items()):
        total = len(scene_rows)
        valid = [row for row in scene_rows if row.get("valid_pixel")]
        blooms = [row for row in valid if row.get("remote_bloom_class") == "suspected_bloom"]
        area_values = [float(row["bloom_pixel_area_km2"]) for row in blooms if row.get("bloom_pixel_area_km2") is not None]
        valid_fais = [float(row["fai"]) for row in valid if row.get("fai") is not None]
        valid_mcis = [float(row["mci"]) for row in valid if row.get("mci") is not None]
        valid_ndwis = [float(row["ndwi"]) for row in valid if row.get("ndwi") is not None]
        first = scene_rows[0]
        summary_flags: list[str] = []
        coverage = len(valid) / total if total else 0.0
        if coverage < 0.5:
            summary_flags.append(Q_REMOTE_COVERAGE)
        summaries.append(
            {
                "source_id": "sentinel2_local_scene",
                "scene_id": scene_id,
                "acquisition_at": first.get("acquisition_at"),
                "longitude": first.get("longitude"),
                "latitude": first.get("latitude"),
                "total_pixels": total,
                "valid_water_pixels": len(valid),
                "valid_pixel_fraction": coverage,
                "bloom_pixels": len(blooms),
                "remote_bloom_area_km2": sum(area_values) if area_values else 0.0,
                "mean_fai": sum(valid_fais) / len(valid_fais) if valid_fais else None,
                "mean_mci": sum(valid_mcis) / len(valid_mcis) if valid_mcis else None,
                "mean_ndwi": sum(valid_ndwis) / len(valid_ndwis) if valid_ndwis else None,
                "remote_bloom_class": "suspected_bloom" if blooms else "clear_water" if valid else "invalid",
                "remote_chlorophyll_a": None,
                "remote_chlorophyll_status": "not_calibrated",
                "quality_flags": sorted(set(summary_flags + [Q_REMOTE_UNCALIBRATED])),
            }
        )
    return {"pixels": pixels, "summaries": summaries}


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


def _write_sqlite_index(path: Path, pixels: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS remote_pixel_indices")
        connection.execute("DROP TABLE IF EXISTS remote_scene_summary")
        for table, rows in (("remote_pixel_indices", pixels), ("remote_scene_summary", summaries)):
            if not rows:
                connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                continue
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            text_columns = {"source_id", "source_file", "source_row", "scene_id", "acquisition_at", "pixel_id", "water_mask_method", "cloud_mask_method", "remote_bloom_class", "remote_chlorophyll_status", "value_origin", "quality_flags"}
            definitions = [f'"{column}" TEXT' if column in text_columns else f'"{column}" REAL' for column in columns]
            connection.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            sql = f'INSERT INTO {table} ({",".join(chr(34)+c+chr(34) for c in columns)}) VALUES ({",".join("?" for _ in columns)})'
            connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if isinstance(row.get(column), (list, dict)) else row.get(column) for column in columns) for row in rows])
        connection.commit()
    finally:
        connection.close()


def run_remote_index(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, reflectance_scale: float = 1.0, cloud_threshold: float = 40.0, ndwi_water_threshold: float = 0.0, fai_threshold: float = 0.0, pixel_area_km2: float | None = None) -> dict[str, Any]:
    raw_rows, conflicts = _read_records(input_path)
    result = index_pixels(raw_rows, reflectance_scale=reflectance_scale, cloud_threshold=cloud_threshold, ndwi_water_threshold=ndwi_water_threshold, fai_threshold=fai_threshold, pixel_area_km2=pixel_area_km2)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or STORAGE / "exports" / f"remote_index_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    pixel_path, summary_path = output_root / "remote_pixel_indices.csv", output_root / "remote_scene_summary.csv"
    _write_csv(pixel_path, result["pixels"])
    _write_csv(summary_path, result["summaries"])
    database = database or STORAGE / "data_cleaning.db"
    _write_sqlite_index(database, result["pixels"], result["summaries"])
    manifest: dict[str, Any] = {
        "run_id": f"remote_index_{stamp}",
        "status": "completed_with_schema_conflicts" if conflicts else "completed",
        "input": str(input_path), "input_rows": len(raw_rows), "scene_rows": len(result["summaries"]),
        "schema_conflicts": conflicts,
        "parameters": {"reflectance_scale": reflectance_scale, "cloud_threshold_percent": cloud_threshold, "ndwi_water_threshold": ndwi_water_threshold, "fai_threshold": fai_threshold, "pixel_area_km2_default": pixel_area_km2},
        "rules": {"fai": "B08 - linear baseline(B04,B11) at 842nm", "mci": "B05 - linear baseline(B04,B08) at 705nm", "ndwi": "(B03-B08)/(B03+B08)", "bloom_label": "suspected_bloom only; requires ground calibration for confirmed label", "chlorophyll": "null until calibration model is applied"},
        "files": {"pixel_indices": str(pixel_path), "scene_summary": str(summary_path), "database": str(database)},
        "row_quality_counts": dict(Counter(flag for row in result["pixels"] for flag in row.get("quality_flags", []))),
    }
    manifest_path = STORAGE / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pair_remote_ground(remote_path: Path, ground_path: Path, *, max_time_diff_hours: float = 12.0, max_space_m: float = 5_000.0) -> dict[str, Any]:
    remote_rows = _read_csv_rows(remote_path)
    ground_rows = _read_csv_rows(ground_path)
    for row in remote_rows:
        row["_time"] = _parse_time(row.get("acquisition_at"))
        for key in ("longitude", "latitude", "mean_fai", "mean_mci", "mean_ndwi", "remote_bloom_area_km2"):
            row[key] = _number(row.get(key))
    for row in ground_rows:
        row["_time"] = _parse_time(row.get("observed_at") or row.get("acquisition_at"))
        row["ground_chlorophyll_a"] = _number(row.get("ground_chlorophyll_a") or row.get("chlorophyll_a") or row.get("叶绿素a"))
        row["longitude"] = _number(row.get("longitude") or row.get("lon"))
        row["latitude"] = _number(row.get("latitude") or row.get("lat"))
    candidates = [row for row in ground_rows if row.get("_time") is not None and row.get("ground_chlorophyll_a") is not None]
    pairs: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for scene in remote_rows:
        best: tuple[tuple[float, float], dict[str, Any], float | None, str] | None = None
        for ground in candidates:
            if scene.get("_time") is None:
                continue
            gap = abs((ground["_time"] - scene["_time"]).total_seconds()) / 3600.0
            if gap > max_time_diff_hours:
                continue
            if all(value is not None for value in (scene.get("longitude"), scene.get("latitude"), ground.get("longitude"), ground.get("latitude"))):
                distance = _haversine_m(float(scene["longitude"]), float(scene["latitude"]), float(ground["longitude"]), float(ground["latitude"]))
                if distance > max_space_m:
                    continue
                status = "matched_temporal_spatial"
                score = (gap, distance)
            else:
                distance = None
                status = "matched_temporal_only"
                score = (gap, 0.0)
            if best is None or score < best[0]:
                best = (score, ground, distance, status)
        if best is None:
            pairs.append({"scene_id": scene.get("scene_id"), "acquisition_at": scene.get("acquisition_at"), "match_status": "unmatched", "time_gap_hours": None, "space_gap_m": None, "ground_chlorophyll_a": None, "quality_flags": ["Q23"]})
            counts["unmatched"] += 1
            continue
        ground, distance, status = best[1], best[2], best[3]
        pair = {key: value for key, value in scene.items() if not key.startswith("_")}
        pair.update({"ground_station_id": ground.get("station_id"), "ground_observed_at": ground.get("observed_at") or ground.get("acquisition_at"), "ground_chlorophyll_a": ground.get("ground_chlorophyll_a"), "ground_longitude": ground.get("longitude"), "ground_latitude": ground.get("latitude"), "time_gap_hours": best[0][0], "space_gap_m": distance, "match_status": status, "quality_flags": ["Q23"] if status == "matched_temporal_only" else []})
        pairs.append(pair)
        counts[status] += 1
    return {"pairs": pairs, "counts": dict(counts), "remote_rows": len(remote_rows), "ground_candidates": len(candidates)}


def run_remote_pair(remote_path: Path, ground_path: Path, output_root: Path | None = None, database: Path | None = None, *, max_time_diff_hours: float = 12.0, max_space_m: float = 5_000.0) -> dict[str, Any]:
    result = pair_remote_ground(remote_path, ground_path, max_time_diff_hours=max_time_diff_hours, max_space_m=max_space_m)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or STORAGE / "exports" / f"remote_pair_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    pair_path = output_root / "remote_ground_pairs.csv"
    _write_csv(pair_path, result["pairs"])
    database = database or STORAGE / "data_cleaning.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE IF EXISTS remote_ground_pairs")
        rows = result["pairs"]
        if rows:
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            text_columns = {"scene_id", "acquisition_at", "ground_station_id", "ground_observed_at", "match_status", "quality_flags", "source_id", "remote_bloom_class", "remote_chlorophyll_status"}
            definitions = [f'"{column}" TEXT' if column in text_columns else f'"{column}" REAL' for column in columns]
            connection.execute(f'CREATE TABLE remote_ground_pairs (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            sql = f'INSERT INTO remote_ground_pairs ({",".join(chr(34)+c+chr(34) for c in columns)}) VALUES ({",".join("?" for _ in columns)})'
            connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if isinstance(row.get(column), (list, dict)) else row.get(column) for column in columns) for row in rows])
        else:
            connection.execute("CREATE TABLE remote_ground_pairs (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        connection.commit()
    finally:
        connection.close()
    manifest = {"run_id": f"remote_pair_{stamp}", "status": "completed", "remote_input": str(remote_path), "ground_input": str(ground_path), "remote_rows": result["remote_rows"], "ground_candidates": result["ground_candidates"], "pair_rows": len(result["pairs"]), "match_counts": result["counts"], "thresholds": {"max_time_diff_hours": max_time_diff_hours, "max_space_m": max_space_m}, "files": {"pairs": str(pair_path), "database": str(database)}}
    manifest_path = STORAGE / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def _solve_linear(matrix: list[list[float]], vector: list[float], ridge: float = 1e-8) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for index in range(size):
        augmented[index][index] += ridge
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular calibration design matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[column])]
    return [augmented[index][-1] for index in range(size)]


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float | None]:
    if not actual:
        return {"n": 0, "r2": None, "rmse": None, "mae": None}
    errors = [predicted[index] - actual[index] for index in range(len(actual))]
    mse = sum(error * error for error in errors) / len(errors)
    mae = sum(abs(error) for error in errors) / len(errors)
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    r2 = 1.0 - sum(error * error for error in errors) / total if total > 1e-12 else None
    return {"n": len(actual), "r2": r2, "rmse": math.sqrt(mse), "mae": mae}


def _calibration_rows(path: Path, features: list[str]) -> list[dict[str, Any]]:
    rows = _read_csv_rows(path)
    output: list[dict[str, Any]] = []
    for row in rows:
        target = _number(row.get("ground_chlorophyll_a") or row.get("chlorophyll_a") or row.get("叶绿素a"))
        values = [_number(row.get(feature)) for feature in features]
        timestamp = _parse_time(row.get("acquisition_at"))
        if target is None or target < 0 or any(value is None or not math.isfinite(value) for value in values) or timestamp is None:
            continue
        output.append({"time": timestamp, "target": target, "features": [float(value) for value in values], "source": row})
    return sorted(output, key=lambda item: item["time"])


def calibrate_chlorophyll(pair_path: Path, features: list[str] | None = None, min_pairs: int = 10) -> dict[str, Any]:
    features = features or ["mean_fai", "mean_mci", "mean_ndwi"]
    rows = _calibration_rows(pair_path, features)
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    model_path = STORAGE / "exports" / f"remote_calibration_{stamp}" / "chlorophyll_model.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"run_id": f"remote_calibration_{stamp}", "features": features, "input": str(pair_path), "usable_pairs": len(rows), "min_pairs": min_pairs}
    if len(rows) < min_pairs:
        result.update({"status": "blocked_insufficient_ground_truth", "reason": "ground_chlorophyll_a pairs are fewer than min_pairs", "model": None})
        model_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["model_path"] = str(model_path)
        return result
    split = max(2, int(round(len(rows) * 0.2)))
    split = min(split, len(rows) - 2)
    train, validation = rows[:-split], rows[-split:]
    design = [[1.0] + [math.log1p(value) for value in item["features"]] for item in train]
    matrix = [[sum(row[i] * row[j] for row in design) for j in range(len(design[0]))] for i in range(len(design[0]))]
    vector = [sum(design[row][i] * math.log1p(train[row]["target"]) for row in range(len(train))) for i in range(len(design[0]))]
    coefficients = _solve_linear(matrix, vector)

    def predict(item: dict[str, Any]) -> float:
        value = coefficients[0] + sum(coefficients[index + 1] * math.log1p(item["features"][index]) for index in range(len(features)))
        return max(0.0, math.expm1(value))

    train_actual, train_pred = [item["target"] for item in train], [predict(item) for item in train]
    val_actual, val_pred = [item["target"] for item in validation], [predict(item) for item in validation]
    model = {"model_type": "log1p_ols_ridge", "features": features, "coefficients": coefficients, "target": "chlorophyll_a", "unit": "ug/L", "training_time_range": [train[0]["time"].isoformat(), train[-1]["time"].isoformat()], "validation_time_range": [validation[0]["time"].isoformat(), validation[-1]["time"].isoformat()], "train_metrics": _metrics(train_actual, train_pred), "validation_metrics": _metrics(val_actual, val_pred), "uncertainty_rmse_ug_L": _metrics(val_actual, val_pred)["rmse"], "calibration_status": "validated_temporal_holdout"}
    result.update({"status": "completed", "model": model, "model_path": str(model_path)})
    model_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_remote_calibration(pair_path: Path, output_root: Path | None = None, database: Path | None = None, *, features: list[str] | None = None, min_pairs: int = 10) -> dict[str, Any]:
    result = calibrate_chlorophyll(pair_path, features=features, min_pairs=min_pairs)
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or Path(result["model_path"]).parent
    output_root.mkdir(parents=True, exist_ok=True)
    model_path = output_root / "chlorophyll_model.json"
    model_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or STORAGE / "data_cleaning.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE IF EXISTS remote_calibration_models")
        connection.execute("CREATE TABLE remote_calibration_models (run_id TEXT PRIMARY KEY, status TEXT, model_json TEXT, model_path TEXT, usable_pairs INTEGER, validation_r2 REAL, validation_rmse REAL, validation_mae REAL)")
        model = result.get("model") or {}
        metrics = model.get("validation_metrics") or {}
        connection.execute("INSERT INTO remote_calibration_models VALUES (?,?,?,?,?,?,?,?)", (result["run_id"], result["status"], json.dumps(model, ensure_ascii=False), str(model_path), result.get("usable_pairs"), metrics.get("r2"), metrics.get("rmse"), metrics.get("mae")))
        connection.commit()
    finally:
        connection.close()
    result["model_path"] = str(model_path)
    result["database"] = str(database)
    manifest_path = STORAGE / "manifests" / f"{result['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest"] = str(manifest_path)
    return result
