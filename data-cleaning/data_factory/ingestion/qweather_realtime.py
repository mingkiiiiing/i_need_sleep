"""和风天气实时/预报采集 — 可选，key 门控 (taihugurad qweather_fetcher.py 重写式适配)。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from data_factory.contracts.constants import RAW_ROOT
from .raw_store import write_raw_snapshot

SOURCE_ID = "qweather_realtime"


def run_qweather(config: dict[str, Any], *, raw_root: Path | None = None, out_dir: Path | None = None) -> dict[str, Any]:
    cfg = (config.get("realtime_sources") or {}).get("qweather") or {}
    if not cfg.get("enabled", False):
        return {"status": "disabled", "command": "collect-realtime", "source_id": SOURCE_ID, "rows_written": 0}
    api_key = os.environ.get(cfg.get("env_key", "QWEATHER_API_KEY"), "")
    if not api_key:
        return {
            "status": "BLOCKED_AUTH",
            "command": "collect-realtime",
            "source_id": SOURCE_ID,
            "message": f"环境变量 {cfg.get('env_key', 'QWEATHER_API_KEY')} 未设置；设置后重跑。",
        }

    import requests

    host = os.environ.get(cfg.get("env_host", "QWEATHER_HOST"), cfg.get("default_host", ""))
    throttle = float(cfg.get("throttle_s", 1.0))
    raw_root = raw_root or RAW_ROOT
    collected: list[dict[str, Any]] = []
    for station in cfg.get("stations", []):
        location = f"{station['lon']},{station['lat']}"
        for endpoint in cfg.get("endpoints", ["now", "24h", "7d"]):
            url = f"https://{host}/v7/weather/{endpoint}"
            resp = requests.get(url, params={"location": location, "key": api_key}, timeout=30)
            if resp.status_code == 429:
                time.sleep(60)
                resp = requests.get(url, params={"location": location, "key": api_key}, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            if str(body.get("code")) != "200":
                raise RuntimeError(f"qweather {endpoint} code={body.get('code')}")
            write_raw_snapshot(
                SOURCE_ID,
                resp.content,
                raw_root=raw_root,
                request_url=url,
                http_status=resp.status_code,
                extra={"station": station["name"], "endpoint": endpoint},
            )
            collected.append({"station": station["name"], "endpoint": endpoint, "code": body.get("code")})
            time.sleep(throttle)
    return {
        "status": "completed",
        "command": "collect-realtime",
        "source_id": SOURCE_ID,
        "rows_written": len(collected),
        "requests": collected,
    }
