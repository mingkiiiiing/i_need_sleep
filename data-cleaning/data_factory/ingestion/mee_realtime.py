"""生态环境部国控地表水实时水质接口采集 (taihugurad water_quality_scraper.py 重写式适配).

上游参考实现: https://github.com/…/taihugurad (README 声称 MIT，仓库无 LICENSE 文件，
来源与该事实登记于 source_registry)。差异：verify=False 配置化、无 loguru、
快照入 storage/raw/mee_realtime/（不可变）、解析记录带规范 variable_code。
"""

from __future__ import annotations

import http.client
import json
import re
import ssl
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import pandas as pd

from data_factory.contracts.constants import RAW_ROOT
from .raw_store import write_raw_snapshot

MEE_API_URL = "https://szzdjc.cnemc.cn:8070/GJZ/Ajax/Publish.ashx"
MEE_RIVER_ID = "1200000000"
SOURCE_ID = "mee_surface_water_realtime"
TZ_CN = timezone(timedelta(hours=8))
FRESHNESS_DEFAULT_MAX_LAG_H = 24.0

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


def _ssl_context(verify: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not verify:
        # 上游站点自签证书：关闭校验但仍走 TLS；留痕见 manifest tls_verify 字段
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _post_form(url: str, params: dict[str, Any], *, timeout: float, verify: bool) -> tuple[int, dict[str, str], bytes]:
    """标准库 http.client POST 表单。

    实测（2026-09-06）：urllib3 2.5.0（requests）对上游的 TLS ClientHello 会被
    WAF 直接断连（SSL UNEXPECTED_EOF_WHILE_READING），标准库 ssl ClientHello
    可正常完成 TLS 1.3 握手并取得数据，因此固定使用 http.client。
    """
    parsed = urlsplit(url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/GJZ/",
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
        "Connection": "close",
    }
    if parsed.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            parsed.hostname, parsed.port or 443, context=_ssl_context(verify), timeout=timeout
        )
    elif parsed.scheme == "http":
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
    else:
        raise ValueError(f"unsupported scheme in MEE api_url: {url}")
    try:
        conn.request("POST", target, body=urlencode(params), headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        return resp.status, {key: value for key, value in resp.getheaders()}, payload
    finally:
        conn.close()


def fetch_snapshot(cfg: dict[str, Any], *, verify: bool) -> tuple[bytes, int, dict[str, str], int]:
    """POST getRealDatas，返回 (payload, http_status, headers, retries_used)。"""

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
            status, headers, payload = _post_form(cfg.get("api_url", MEE_API_URL), params, timeout=timeout, verify=verify)
            if status != 200:
                raise RuntimeError(f"http status {status}")
            data = json.loads(payload.decode("utf-8"))
            if data.get("result") and data["result"] != 0:
                return payload, status, headers, attempt - 1
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
    """补全年份+北京时间时区，并执行 QC 门：时间/站点名/物理范围任一不通过则
    pending_review + observation_candidate；全部通过仅标 value_type=observed。
    is_ground_truth 恒为 False——值域/时间 QC 不构成独立验证（无设备质控、无
    交叉来源核验），升级真值须经 station_validate 等独立校验后另行标记
    （审计 2026-09-06 实时数据可信边界整改）。"""
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
                    "is_ground_truth": False,
                    "role": "observation_candidate",
                    "quality_flag": "pass" if passed else "pending_review",
                    "qc_note": "" if passed else ";".join(reasons),
                }
            )
    return pd.DataFrame(rows)


def _status_path(out_dir: Path) -> Path:
    return out_dir / "mee_collection_status.json"


def _write_status(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _status_path(out_dir)
    previous: dict[str, Any] = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    payload["last_success_utc"] = previous.get("last_success_utc") if payload.get("status") != "completed" else payload.get("last_success_utc")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _evaluate_freshness(observations: pd.DataFrame, now_cn: datetime, max_lag_h: float) -> dict[str, Any]:
    if observations.empty or "observed_time" not in observations.columns:
        return {"latest_observed_time": None, "freshness_lag_h": None, "freshness_status": "unknown"}
    latest = observations["observed_time"].max()
    if pd.isna(latest):
        return {"latest_observed_time": None, "freshness_lag_h": None, "freshness_status": "unknown"}
    lag_h = (now_cn - latest).total_seconds() / 3600.0
    return {
        "latest_observed_time": pd.Timestamp(latest).isoformat(),
        "freshness_lag_h": round(float(lag_h), 2),
        "freshness_status": "fresh" if float(lag_h) <= max_lag_h else "stale",
    }


def run_collect_mee(
    config: dict[str, Any],
    *,
    out_dir: Path,
    raw_root: Path | None = None,
    catalog_dir: Path | None = None,
    catalog_registry_path: Path | None = None,
) -> dict[str, Any]:
    cfg = (config.get("realtime_sources") or {}).get("mee") or config.get("mee") or {}
    if not cfg.get("enabled", True):
        return {"status": "disabled", "command": "collect-realtime", "rows_written": 0}
    verify = bool(cfg.get("tls_verify", False))
    max_lag_h = float(cfg.get("freshness_max_lag_h", FRESHNESS_DEFAULT_MAX_LAG_H))
    warnings_list: list[str] = []
    if not verify:
        message = "tls_verify=false: 上游证书校验关闭（上游自签证书），已在 manifest 留痕"
        warnings.warn(message, UserWarning)
        warnings_list.append(message)

    now_utc = datetime.now(timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload, http_status, headers, retries = fetch_snapshot(cfg, verify=verify)
    except Exception as exc:
        _write_status(
            out_dir,
            {
                "source_id": SOURCE_ID,
                "status": "failed",
                "last_attempt_utc": now_utc.astimezone(timezone.utc).isoformat(),
                "last_error": f"{type(exc).__name__}: {exc}",
                "freshness_max_lag_h": max_lag_h,
                "freshness_status": "unknown",
            },
        )
        raise

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

    parquet_path = out_dir / "mee_observations.parquet"
    if parquet_path.exists():
        existing = pd.read_parquet(parquet_path)
        observations = pd.concat([existing, observations], ignore_index=True).drop_duplicates(
            subset=["station_id", "observed_time", "variable_code"], keep="last"
        )
    # 可信边界统一重标：历史行若由旧版本写入 ground_truth=true，一并降级
    observations["is_ground_truth"] = False
    observations.to_parquet(parquet_path, index=False)

    qc_pass = int((observations["quality_flag"] == "pass").sum()) if not observations.empty else 0

    now_cn = now_utc.astimezone(TZ_CN)
    freshness = _evaluate_freshness(observations, now_cn, max_lag_h)
    status_payload = {
        "source_id": SOURCE_ID,
        "status": "completed",
        "last_attempt_utc": now_utc.isoformat(),
        "last_success_utc": now_utc.isoformat(),
        "http_status": http_status,
        "retries": retries,
        "station_count": len(records),
        "rows_total": int(len(observations)),
        "freshness_max_lag_h": max_lag_h,
        **freshness,
        "snapshot": str(snapshot),
        "output": str(parquet_path),
    }
    _write_status(out_dir, status_payload)

    # 三层结构重建（Snapshot→Station 目录→完整缺测观测）：以原始快照为唯一事实来源，
    # 失败不回滚本次采集（raw/parquet 已落盘），错误在 manifest 留痕。
    # catalog_dir/catalog_registry_path 可覆盖（测试必须指向临时目录，禁止写正式 silver）
    catalog_summary: dict[str, Any] | None = None
    catalog_error = None
    try:
        from data_factory.contracts.constants import MEE_REALTIME_CATALOG_DIR, STATION_REGISTRY_MERGED

        from .mee_realtime_catalog import build_catalog

        if catalog_registry_path is None:
            catalog_registry_path = STATION_REGISTRY_MERGED if STATION_REGISTRY_MERGED.exists() else None
        catalog_summary = build_catalog(
            raw_root=raw_root or RAW_ROOT,
            out_dir=catalog_dir or MEE_REALTIME_CATALOG_DIR,
            registry_path=catalog_registry_path,
            collection_status_path=_status_path(out_dir),
        )
    except Exception as exc:  # noqa: BLE001 — 目录构建失败不阻断采集，但必须留痕
        catalog_error = f"{type(exc).__name__}: {exc}"

    result = {
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
        "freshness_max_lag_h": max_lag_h,
        **freshness,
        "next_action": "数据为官方接口观测（is_ground_truth=false，待独立验证）；freshness_status=stale 表示上游停更，"
        "观测层桥接会按 freshness_max_lag_h 门禁剔除；接口失败只允许 missing_reason=api_unavailable，不得用模拟值补位",
    }
    if freshness["freshness_status"] == "stale":
        result["warnings"] = warnings_list + [
            f"freshness stale: 最新观测落后 {freshness['freshness_lag_h']}h（门禁 {max_lag_h}h），已留痕 mee_collection_status.json"
        ]
    if catalog_error:
        result["warnings"] = result.get("warnings", []) + [f"mee_realtime_catalog build failed: {catalog_error}"]
        result["catalog_error"] = catalog_error
    elif catalog_summary:
        result["catalog"] = {
            k: catalog_summary[k]
            for k in ("station_count", "active_station_count", "snapshot_count", "observation_rows", "freshness_status", "output")
            if k in catalog_summary
        }
    return result
