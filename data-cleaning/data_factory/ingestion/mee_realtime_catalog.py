"""MEE 实时站点三层结构：Snapshot → Station 目录 + 完整缺测观测 (审计整改 2026-09-06).

以不可变原始快照为唯一事实来源重建（storage/silver/mee_realtime/）：
- station 目录：entity_id = mee-<sha256_8>(source_id|province|basin|normalized_name)，
  别名表处理括号/空格/上游改名；站点从最新快照消失只标 active=false，不删历史。
- 观测层：每站每快照固定 11 个指标状态行，缺测显式落行（不省略），
  is_ground_truth 恒 False（未经跨源验证的官方观测）。
- location_status：verified/metadata_only/suspicious/missing；无验证坐标不生成地图点位，
  共用同一坐标的站（旧注册表 fallback 占位）判 suspicious。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .mee_realtime import CANONICAL_CODES, QC_RANGES, TZ_CN, _resolve_observed_time, parse_tbody

SOURCE_ID = "mee_surface_water_realtime"
STATION_ENTITY_PREFIX = "mee-"
VARIABLE_CODES: tuple[str, ...] = tuple(code for code, _ in CANONICAL_CODES.values())
LOCATION_STATUSES = ("verified", "metadata_only", "suspicious", "missing")
OBSERVATION_STATUSES = ("ok", "missing", "qc_rejected", "parse_failed")
EVIDENCE_LEVEL = "official_station_observation"
VERIFICATION_STATE = "not_cross_validated"
# 展示新鲜度分带（小时）：≤6 正常，≤12 延迟，>12 严重过期；无成功快照 → unavailable
FRESHNESS_NORMAL_H = 6.0
FRESHNESS_DELAYED_H = 12.0

_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]\s*$")
_WS_RE = re.compile(r"[\s\u3000]+")


def normalize_station_name(raw: Any) -> str:
    """站点名归一：去空白、全角括号转半角、去尾部括号注记（如“卫八路桥（嘉兴金桥）”）。"""
    text = "" if raw is None else str(raw).strip()
    text = text.replace("（", "(").replace("）", ")")
    text = _WS_RE.sub("", text)
    return _PAREN_RE.sub("", text).strip()


def station_entity_id(province: Any, basin: Any, normalized_name: str, *, source_id: str = SOURCE_ID) -> str:
    key = "|".join((source_id, str(province or ""), str(basin or ""), normalized_name))
    return STATION_ENTITY_PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def freshness_band(lag_h: float | None) -> str:
    if lag_h is None:
        return "unavailable"
    if lag_h <= FRESHNESS_NORMAL_H:
        return "normal"
    if lag_h <= FRESHNESS_DELAYED_H:
        return "delayed"
    return "severely_overdue"


def _snapshot_stem(path: Path) -> str:
    return path.stem


def _snapshot_retrieved_at(path: Path) -> str | None:
    sidecar = path.with_suffix(".manifest.json")
    if sidecar.exists():
        try:
            stamp = json.loads(sidecar.read_text(encoding="utf-8")).get("retrieved_at_utc")
            if stamp:
                return stamp
        except (OSError, ValueError):
            pass
    match = re.search(r"(\d{8}T\d{6}Z)", path.stem)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    return None


def iter_snapshots(raw_root: Path) -> list[dict[str, Any]]:
    base = Path(raw_root) / SOURCE_ID
    if not base.exists():
        return []
    snaps = []
    for path in sorted(base.glob("**/*.json")):
        if path.name.endswith(".manifest.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        snaps.append(
            {
                "snapshot_id": _snapshot_stem(path),
                "snapshot_file": str(path),
                "retrieved_at_utc": _snapshot_retrieved_at(path),
                "declared_record_count": payload.get("records"),
                "payload": payload,
            }
        )
    snaps.sort(key=lambda item: (item["retrieved_at_utc"] or "", item["snapshot_id"]))
    return snaps


def load_station_locations(registry_path: Path | None) -> dict[str, dict[str, Any]]:
    """合并站点注册表 → 归一名 → 位置信息与 location_status。

    规则：显式 verified 优先；无坐标 missing；多站共用同一坐标（fallback 占位）suspicious；
    其余有坐标 metadata_only（注册表坐标均未经官方核验）。
    """
    if registry_path is None or not Path(registry_path).exists():
        return {}
    payload = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    entries = payload if isinstance(payload, list) else payload.get("stations", [])
    by_name: dict[str, dict[str, Any]] = {}
    coord_owner: dict[tuple[float, float], str] = {}
    for entry in entries:
        name = normalize_station_name(entry.get("name") or entry.get("id"))
        if not name:
            continue
        lon, lat = entry.get("lon"), entry.get("lat")
        status = "missing"
        if entry.get("location_status") == "verified" and lon is not None and lat is not None:
            status = "verified"
        elif lon is not None and lat is not None:
            status = "metadata_only"
        info = {
            "lon": float(lon) if lon is not None else None,
            "lat": float(lat) if lat is not None else None,
            "location_status": status,
            "registry_source": entry.get("registry_source", ""),
            "coord_source": entry.get("coord_source", ""),
        }
        by_name[name] = info
        if info["lon"] is not None:
            # 共用同一坐标（旧注册表 fallback 占位）：所有涉事站标 suspicious，
            # 但显式 verified 的站保持 verified 不降级
            key = (round(info["lon"], 6), round(info["lat"], 6))
            first_owner = coord_owner.setdefault(key, name)
            if first_owner != name:
                if by_name[name]["location_status"] != "verified":
                    by_name[name]["location_status"] = "suspicious"
                if by_name[first_owner]["location_status"] != "verified":
                    by_name[first_owner]["location_status"] = "suspicious"
    return by_name


def _resolve_location(name_variants: set[str], locations: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in sorted(name_variants, key=len, reverse=True):
        normalized = normalize_station_name(candidate)
        if normalized in locations:
            return locations[normalized]
    return None


def _variable_rows(record: dict[str, Any], *, snapshot_id: str, retrieved_at: str | None) -> tuple[str, list[dict[str, Any]]]:
    """单站单快照 → (station_key, 11 行指标状态)。缺测/解析失败显式落行。"""
    if retrieved_at:
        retrieved_ts = pd.Timestamp(retrieved_at)
        now_cn = retrieved_ts.tz_localize(TZ_CN) if retrieved_ts.tzinfo is None else retrieved_ts.tz_convert(TZ_CN)
    else:
        now_cn = pd.Timestamp.now(tz=TZ_CN)
    observed_ts = _resolve_observed_time(record.get("observed_time"), now_cn.to_pydatetime())
    observed_iso = None if pd.isna(observed_ts) else observed_ts.isoformat()
    time_failed = observed_iso is None
    rows: list[dict[str, Any]] = []
    for key, (code, unit) in CANONICAL_CODES.items():
        value = record.get(key)
        if time_failed:
            status, missing_reason, qc_status = "parse_failed", "unparseable_observed_time", "not_applicable"
        elif value is None:
            status, missing_reason, qc_status = "missing", "upstream_missing", "not_applicable"
        else:
            low, high = QC_RANGES.get(code, (float("-inf"), float("inf")))
            if low <= float(value) <= high:
                status, missing_reason, qc_status = "ok", None, "pass"
            else:
                status, missing_reason, qc_status = "qc_rejected", None, "pending_review"
        rows.append(
            {
                "station_entity_id": "",  # 由调用方按实体回填
                "snapshot_id": snapshot_id,
                "observed_at": observed_iso,
                "retrieved_at": retrieved_at,
                "variable_code": code,
                "value": float(value) if status in ("ok", "qc_rejected") else None,
                "unit": unit,
                "observation_status": status,
                "missing_reason": missing_reason,
                "source_quality_note": None,
                "qc_status": qc_status,
                "evidence_level": EVIDENCE_LEVEL,
                "verification_state": VERIFICATION_STATE,
                "is_ground_truth": False,
            }
        )
    return str(record.get("station_name") or ""), rows


def build_catalog(
    *,
    raw_root: Path,
    out_dir: Path,
    registry_path: Path | None = None,
    collection_status_path: Path | None = None,
) -> dict[str, Any]:
    """从全部不可变快照重建站点目录 + 观测层（幂等全量重建）。"""

    snapshots = iter_snapshots(raw_root)
    locations = load_station_locations(registry_path)

    entities: dict[str, dict[str, Any]] = {}
    obs_rows: list[dict[str, Any]] = []
    seen_variants: dict[str, set[str]] = {}
    snapshot_summaries: list[dict[str, Any]] = []

    for snap in snapshots:
        records = parse_tbody(snap["payload"])
        station_keys: set[str] = set()
        latest_observed: str | None = None
        snapshot_station_stats: list[dict[str, Any]] = []
        for record in records:
            province = record.get("province")
            basin = record.get("basin")
            raw_name = str(record.get("station_name") or "").strip()
            normalized = normalize_station_name(raw_name)
            if not normalized:
                continue
            entity_id = station_entity_id(province, basin, normalized)
            station_keys.add(entity_id)
            variants = seen_variants.setdefault(entity_id, set())
            variants.add(raw_name)
            key, rows = _variable_rows(record, snapshot_id=snap["snapshot_id"], retrieved_at=snap["retrieved_at_utc"])
            for row in rows:
                row["station_entity_id"] = entity_id
            obs_rows.extend(rows)
            observed_at = next((r["observed_at"] for r in rows if r["observed_at"]), None)
            if observed_at and (latest_observed is None or observed_at > latest_observed):
                latest_observed = observed_at
            # 回放用站点级快照数据（水质类别 + chla），体积小、随目录一次落盘
            chla_value = next(
                (r["value"] for r in rows if r["variable_code"] == "chlorophyll_a" and r["observation_status"] == "ok"),
                None,
            )
            snapshot_station_stats.append(
                {
                    "entity_id": entity_id,
                    "level": record.get("water_quality_level"),
                    "chla": round(float(chla_value), 3) if chla_value is not None else None,
                }
            )
            entity = entities.get(entity_id)
            if entity is None:
                entity = {
                    "entity_id": entity_id,
                    "source_id": SOURCE_ID,
                    "source_station_name": raw_name or normalized,
                    "normalized_station_name": normalized,
                    "province": province,
                    "basin": basin,
                    "first_seen_at": snap["retrieved_at_utc"],
                    "last_seen_at": snap["retrieved_at_utc"],
                    "latest_observed_at": latest_observed,
                    "latest_snapshot_id": snap["snapshot_id"],
                    "latest_water_quality_level": record.get("water_quality_level"),
                    "active_in_latest_snapshot": False,
                    "aliases": [],
                    "location": None,
                }
                entities[entity_id] = entity
            else:
                entity["last_seen_at"] = snap["retrieved_at_utc"]
                if snap["retrieved_at_utc"] and (entity["latest_snapshot_id"] == "" or snap["retrieved_at_utc"] >= (entity.get("_latest_retrieved") or "")):
                    entity["_latest_retrieved"] = snap["retrieved_at_utc"]
                    entity["latest_snapshot_id"] = snap["snapshot_id"]
                    entity["latest_observed_at"] = latest_observed
                    entity["latest_water_quality_level"] = record.get("water_quality_level")
                    entity["source_station_name"] = raw_name or normalized
                    entity["province"] = province
                    entity["basin"] = basin
        snapshot_summaries.append(
            {
                "snapshot_id": snap["snapshot_id"],
                "snapshot_file": snap["snapshot_file"],
                "retrieved_at_utc": snap["retrieved_at_utc"],
                "declared_record_count": snap["declared_record_count"],
                "parsed_station_count": len(station_keys),
                "latest_observed_at": max(
                    (r["observed_at"] for r in obs_rows if r["snapshot_id"] == snap["snapshot_id"] and r["observed_at"]),
                    default=None,
                ),
                # 每快照站点级水质类别与 chla（回放时间轴数据源）
                "station_stats": snapshot_station_stats,
            }
        )

    if snapshots:
        latest_snapshot_id = snapshots[-1]["snapshot_id"]
        for entity in entities.values():
            entity["active_in_latest_snapshot"] = entity["latest_snapshot_id"] == latest_snapshot_id
            entity["aliases"] = sorted(seen_variants.get(entity["entity_id"], set()))
            location = _resolve_location(set(entity["aliases"]), locations)
            entity["location"] = location
            entity.pop("_latest_retrieved", None)

    observations = pd.DataFrame(obs_rows)
    if not observations.empty:
        observations = observations.sort_values(
            ["station_entity_id", "snapshot_id", "variable_code"], kind="stable"
        ).reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    stations_list = sorted(entities.values(), key=lambda item: item["entity_id"])
    _atomic_write_text(
        out_dir / "stations.json",
        json.dumps({"source_id": SOURCE_ID, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "station_count": len(stations_list), "stations": stations_list}, ensure_ascii=False, indent=2),
    )
    _atomic_write_text(
        out_dir / "snapshots.json",
        json.dumps({"source_id": SOURCE_ID, "snapshot_count": len(snapshot_summaries), "snapshots": snapshot_summaries}, ensure_ascii=False, indent=2),
    )
    _atomic_write_parquet(observations, out_dir / "observations.parquet")

    status = _build_status(snapshots, snapshot_summaries, entities, observations, collection_status_path)
    # status.json is the publication marker and must be replaced last.  Readers
    # reload only after this file changes, so they never observe a half-written bundle.
    _atomic_write_text(out_dir / "status.json", json.dumps(status, ensure_ascii=False, indent=2))

    return {
        "status": "completed",
        "command": "build-mee-catalog",
        "snapshot_count": len(snapshot_summaries),
        "station_count": len(stations_list),
        "observation_rows": int(len(observations)),
        "active_station_count": sum(1 for e in stations_list if e["active_in_latest_snapshot"]),
        "location_status_counts": _location_status_counts(stations_list),
        "output": str(out_dir),
        **{k: status[k] for k in ("freshness_status", "as_of", "latest_observed_at")},
    }


def _atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(path)


def _location_status_counts(stations: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in LOCATION_STATUSES}
    for entity in stations:
        location = entity.get("location") or {}
        counts[location.get("location_status", "missing")] += 1
    return counts


def _error_code(last_error: str | None) -> str | None:
    if not last_error:
        return None
    text = last_error.lower()
    if "ssl" in text or "tls" in text or "certificate" in text:
        return "UPSTREAM_TLS_FAILURE"
    if "timeout" in text or "timed out" in text:
        return "UPSTREAM_TIMEOUT"
    if "http status" in text:
        return "UPSTREAM_HTTP_ERROR"
    return "UPSTREAM_FETCH_FAILED"


def _build_status(
    snapshots: list[dict[str, Any]],
    snapshot_summaries: list[dict[str, Any]],
    entities: dict[str, Any],
    observations: pd.DataFrame,
    collection_status_path: Path | None,
) -> dict[str, Any]:
    collection: dict[str, Any] = {}
    if collection_status_path and Path(collection_status_path).exists():
        try:
            collection = json.loads(Path(collection_status_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            collection = {}
    latest = snapshot_summaries[-1] if snapshot_summaries else None
    as_of = latest["retrieved_at_utc"] if latest else collection.get("last_success_utc")
    latest_observed = collection.get("latest_observed_time") or (latest or {}).get("latest_observed_at")
    lag_h: float | None = None
    if latest_observed:
        observed_ts = pd.Timestamp(latest_observed)
        now_cn = pd.Timestamp.now(tz=TZ_CN)
        if observed_ts.tzinfo is None:
            observed_ts = observed_ts.tz_localize(TZ_CN)
        else:
            observed_ts = observed_ts.tz_convert(TZ_CN)
        lag_h = (now_cn - observed_ts).total_seconds() / 3600.0
    latest_station_count = None
    if latest:
        latest_station_count = latest["parsed_station_count"]
    active_count = sum(1 for e in entities.values() if e["active_in_latest_snapshot"])
    return {
        "source": SOURCE_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "last_attempt_at": collection.get("last_attempt_utc"),
        "last_success_at": collection.get("last_success_utc"),
        "collection_status": collection.get("status", "unavailable"),
        "last_error": collection.get("last_error"),
        "last_error_code": _error_code(collection.get("last_error")),
        "snapshot_count": len(snapshot_summaries),
        "latest_snapshot_id": (latest or {}).get("snapshot_id"),
        "latest_station_count": latest_station_count,
        "active_station_count": active_count,
        "declared_record_count": (latest or {}).get("declared_record_count"),
        "parsed_station_count": (latest or {}).get("parsed_station_count"),
        "latest_observed_at": latest_observed,
        "observed_lag_h": round(lag_h, 2) if lag_h is not None else None,
        "freshness_status": freshness_band(lag_h) if latest_observed else "unavailable",
        "observation_rows": int(len(observations)),
    }


def latest_station_views(entities: list[dict[str, Any]], observations: pd.DataFrame, latest_snapshot_id: str | None) -> list[dict[str, Any]]:
    """站点摘要视图：最新快照内各站可用/缺失指标计数（供 API 列表直接返回）。"""
    views = []
    for entity in entities:
        counts = {"ok": 0, "missing": 0, "qc_rejected": 0, "parse_failed": 0}
        if latest_snapshot_id:
            sub = observations[
                (observations["station_entity_id"] == entity["entity_id"])
                & (observations["snapshot_id"] == latest_snapshot_id)
            ]
            if not sub.empty:
                for status_key, count in sub["observation_status"].value_counts().items():
                    counts[status_key] = int(count)
        views.append(
            {
                **entity,
                "available_variable_count": counts["ok"],
                "qc_rejected_variable_count": counts["qc_rejected"],
                "missing_variable_count": counts["missing"] + counts["parse_failed"],
            }
        )
    return views
