"""生态环境部国控地表水实时水质接口采集 (taihugurad water_quality_scraper.py 重写式适配).

上游参考实现: https://github.com/…/taihugurad (README 声称 MIT，仓库无 LICENSE 文件，
来源与该事实登记于 source_registry)。差异：verify=False 配置化、无 loguru、
快照入 storage/raw/mee_realtime/（不可变）、解析记录带规范 variable_code。
"""

from __future__ import annotations

import json
import re
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_factory.contracts.constants import RAW_ROOT
from .raw_store import write_raw_snapshot

MEE_API_URL = "https://szzdjc.cnemc.cn:8070/GJZ/Ajax/Publish.ashx"
MEE_RIVER_ID = "1200000000"
SOURCE_ID = "mee_surface_water_realtime"
TZ_CN = timezone(timedelta(hours=8))

# QC 物理范围（对齐 config/qc_rules.yml 物理界限；单位为 CANONICAL_CODES 规范化后单位）
QC_RANGES: dict[str, tuple[float, float]] = {
    "water_temperature": (0.0, 40.0),
    "pH": (6.0, 9.5),
    "dissolved_oxygen": (0.0, 20.0),
    "conductivity": (0.0, 1500.0),
    "turbidity": (0.0, 500.0),
    "cod_mn": (0.0, 50.0),
    "ammonia_nitrogen": (0.0, 10.0),
    "total_phosphorus": (0.0, 2.0),
    "total_nitrogen": (0.0, 15.0),
    "chlorophyll_a": (0.0, 2000.0),
    "cyanobacteria_density": (0.0, 100000.0),
}

# tbody 列序: [省份, 流域, 断面名, 监测时间, 水质类别, 水温, pH, DO, 电导率, 浊度, CODMn, NH3N, TP, TN, Chla, 藻密度]
PARAM_KEYS = ["water_temp", "ph", "do", "conductivity", "turbidity", "codmn", "nh3n", "tp", "tn", "chla", "algae_density"]

CANONICAL_CODES = {
    "water_temp": ("water_temperature", "degC"),
    "ph": ("pH", ""),
    "do": ("dissolved_oxygen", "mg/L"),
    "conductivity": ("conductivity", "uS/cm"),
    "turbidity": ("turbidity", "NTU"),
    "codmn": ("cod_mn", "mg/L"),
    "nh3n": ("ammonia_nitrogen", "mg/L"),
    "tp": ("total_phosphorus", "mg/L"),
    "tn": ("total_nitrogen", "mg/L"),
    "chla": ("chlorophyll_a", "ug/L"),
    "algae_density": ("cyanobacteria_density", "10^4 cells/L"),
}

_VALUE_RE = re.compile(r"原始值：([\d.]+)")


def _extract_value(html_str: Any) -> float | None:
    if html_str is None:
        return None
    text = str(html_str)
    if text in ("--", "&nbsp;", ""):
        return None
    match = _VALUE_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def fetch_snapshot(cfg: dict[str, Any], *, verify: bool) -> tuple[bytes, int, dict[str, str], int]:
    """POST getRealDatas，返回 (payload, http_status, headers, retries_used)。"""

    import requests

    params = {
        "action": "getRealDatas",
        "AreaID": "",
        "RiverID": cfg.get("river_id", MEE_RIVER_ID),
        "MNName": "",
        "PageIndex": int(cfg.get("page_index", 1)),
        "PageSize": int(cfg.get("page_size", 500)),
    }
    max_retries = int(cfg.get("max_retries", 3))
    delay = float(cfg.get("retry_delay_s", 5))
    timeout = float(cfg.get("timeout_s", 30))
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(cfg.get("api_url", MEE_API_URL), data=params, timeout=timeout, verify=verify)
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") and data["result"] != 0:
                return resp.content, resp.status_code, dict(resp.headers), attempt - 1
            last_error = RuntimeError(f"api returned no data (result={data.get('result')})")
        except Exception as exc:  # noqa: BLE001 — 网络异常统一重试
            last_error = exc
        if attempt < max_retries:
            time.sleep(delay)
    raise RuntimeError(f"MEE realtime fetch failed after {max_retries} attempts: {last_error}")


def parse_tbody(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in payload.get("tbody", []):
        if len(row) < 6 or not row[2]:
            continue
        record: dict[str, Any] = {
            "province": row[0],
            "basin": row[1],
            "station_name": row[2],
            "station_id": row[2],
            "observed_time": row[3],
            "water_quality_level": int(row[4]) if row[4] and str(row[4]).isdigit() else None,
        }
        for i, key in enumerate(PARAM_KEYS):
            idx = 5 + i
            value = _extract_value(row[idx]) if idx < len(row) else None
            if value is not None:
                if key == "chla":        # mg/L → ug/L
                    value *= 1000.0
                elif key == "algae_density":  # cells/L → 万cells/L
                    value /= 10000.0
            record[key] = value
        records.append(record)
    return records


_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _resolve_observed_time(raw: Any, now_cn: datetime) -> pd.Timestamp:
    """DG-014：上游时间只有 'MM-DD HH:mm' 无年份，按 retrieved_at 北京时间补全年份；
    补全后若落在未来（容差 1 天，实时页面不会出现未来时刻）视为上一年的跨年数据；
    不可解析返回 NaT（QC 判罚）。"""
    text = "" if raw is None else str(raw).strip()
    parsed: datetime | None = None
    has_year = False
    for fmt in _TIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            has_year = fmt.startswith("%Y")
            break
        except ValueError:
            continue
    if parsed is None:
        return pd.NaT
    if not has_year:
        now_naive = now_cn.astimezone(TZ_CN).replace(tzinfo=None)
        guess = parsed.replace(year=now_naive.year)
        if guess > now_naive + timedelta(days=1):
            guess = guess.replace(year=now_naive.year - 1)
        parsed = guess
    return pd.Timestamp(parsed).tz_localize(TZ_CN)


def _station_id_ok(station_id: Any) -> bool:
    text = "" if station_id is None else str(station_id).strip()
    return bool(text) and len(text) <= 64 and _CTRL_RE.search(text) is None


def normalize(records: list[dict[str, Any]], *, retrieved_at: datetime, snapshot_file: str) -> pd.DataFrame:
    """补全年份+北京时间时区，并执行 QC 门：时间/站点名/物理范围全部通过才
    value_type=observed + is_ground_truth=true，否则 pending_review + observation_candidate。"""
    now_cn = retrieved_at.astimezone(TZ_CN)
    retrieved_str = retrieved_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict[str, Any]] = []
    for record in records:
        observed_time = _resolve_observed_time(record.get("observed_time"), now_cn)
        station_id = str(record.get("station_id") or "").strip()
        time_ok = not pd.isna(observed_time)
        station_ok = _station_id_ok(station_id)
        for key, value in record.items():
            if key not in CANONICAL_CODES or value is None:
                continue
            code, unit = CANONICAL_CODES[key]
            reasons: list[str] = []
            if not time_ok:
                reasons.append("unparseable_observed_time")
            if not station_ok:
                reasons.append("invalid_station_id")
            low, high = QC_RANGES.get(code, (float("-inf"), float("inf")))
            if not low <= float(value) <= high:
                reasons.append(f"out_of_range[{low},{high}]")
            passed = not reasons
            rows.append(
                {
                    "station_id": station_id,
                    "station_name": record.get("station_name"),
                    "observed_time": observed_time,
                    "variable_code": code,
                    "value": float(value),
                    "unit": unit,
                    "retrieved_at_utc": retrieved_str,
                    "snapshot_file": snapshot_file,
                    "value_type": "observed" if passed else "observation_candidate",
                    "provenance_type": "observed",
                    "is_ground_truth": passed,
                    "role": "observation_candidate",
                    "quality_flag": "pass" if passed else "pending_review",
                    "qc_note": "" if passed else ";".join(reasons),
                }
            )
    return pd.DataFrame(rows)


def run_collect_mee(config: dict[str, Any], *, out_dir: Path, raw_root: Path | None = None) -> dict[str, Any]:
    cfg = (config.get("realtime_sources") or {}).get("mee") or config.get("mee") or {}
    if not cfg.get("enabled", True):
        return {"status": "disabled", "command": "collect-realtime", "rows_written": 0}
    verify = bool(cfg.get("tls_verify", False))
    warnings_list: list[str] = []
    if not verify:
        message = "tls_verify=false: 上游证书校验关闭（上游自签证书），已在 manifest 留痕"
        warnings.warn(message, UserWarning)
        warnings_list.append(message)

    now_utc = datetime.now(timezone.utc)
    payload, http_status, headers, retries = fetch_snapshot(cfg, verify=verify)
    snapshot = write_raw_snapshot(
        SOURCE_ID,
        payload,
        raw_root=raw_root or RAW_ROOT,
        now_utc=now_utc,
        request_url=cfg.get("api_url", MEE_API_URL),
        http_status=http_status,
        response_headers=headers,
        retries=retries,
        extra={"tls_verify": verify, "river_id": cfg.get("river_id", MEE_RIVER_ID)},
    )

    body = json.loads(payload.decode("utf-8"))
    records = parse_tbody(body)
    observations = normalize(records, retrieved_at=now_utc, snapshot_file=str(snapshot))
    qc_pass = int((observations["quality_flag"] == "pass").sum()) if not observations.empty else 0

    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "mee_observations.parquet"
    if parquet_path.exists():
        existing = pd.read_parquet(parquet_path)
        observations = pd.concat([existing, observations], ignore_index=True).drop_duplicates(
            subset=["station_id", "observed_time", "variable_code"], keep="last"
        )
    observations.to_parquet(parquet_path, index=False)

    return {
        "status": "completed",
        "command": "collect-realtime",
        "source_id": SOURCE_ID,
        "station_count": len(records),
        "rows_read": len(records),
        "rows_written": int(len(observations)),
        "qc_pass_rows": qc_pass,
        "qc_pending_rows": int(len(observations) - qc_pass),
        "snapshot": str(snapshot),
        "output": str(parquet_path),
        "tls_verify": verify,
        "retries": retries,
        "warnings": warnings_list,
        "next_action": "数据为观测候选；接口失败只允许 missing_reason=api_unavailable，不得用模拟值补位",
    }
