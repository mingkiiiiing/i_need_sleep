from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

API = "https://seasonal-api.open-meteo.com/v1/seasonal"
VARIABLES = ("temperature_2m_mean", "precipitation_sum", "shortwave_radiation_sum", "wind_speed_10m_mean")


def parse_ensemble(payload: dict[str, Any]) -> pd.DataFrame:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    rows = []
    for position, date in enumerate(dates):
        row = {"forecast_date": date, "latitude": payload.get("latitude"), "longitude": payload.get("longitude"), "timezone": payload.get("timezone"), "model": "ecmwf_seas5"}
        for variable in VARIABLES:
            columns = [key for key in daily if key == variable or key.startswith(f"{variable}_member")]
            values = [daily[key][position] for key in columns if position < len(daily[key]) and daily[key][position] is not None]
            numeric = np.asarray(values, dtype=float)
            row[f"{variable}_ensemble_mean"] = float(np.mean(numeric)) if len(numeric) else None
            row[f"{variable}_p10"] = float(np.quantile(numeric, 0.1)) if len(numeric) else None
            row[f"{variable}_p90"] = float(np.quantile(numeric, 0.9)) if len(numeric) else None
            row[f"{variable}_member_count"] = int(len(numeric))
        rows.append(row)
    return pd.DataFrame(rows)


def run_open_meteo_seasonal(output_root: Path, *, forecast_days: int = 90, latitude: float = 31.2, longitude: float = 120.3) -> dict[str, Any]:
    params = {"latitude": latitude, "longitude": longitude, "daily": ",".join(VARIABLES), "forecast_days": forecast_days, "models": "ecmwf_seas5", "timezone": "Asia/Shanghai"}
    response = requests.get(API, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    frame = parse_ensemble(payload)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path, csv_path, parquet_path, manifest_path = output_root / f"raw_{stamp}.json", output_root / "seasonal_ensemble_daily.csv", output_root / "seasonal_ensemble_daily.parquet", output_root / "manifest.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    frame.to_parquet(parquet_path, index=False)
    manifest = {"source_id": "open_meteo_ecmwf_seas5", "status": "completed" if len(frame) == forecast_days else "completed_with_warnings", "authorization": "none", "api": API, "forecast_days": len(frame), "start": frame["forecast_date"].min() if len(frame) else None, "end": frame["forecast_date"].max() if len(frame) else None, "member_count_min": int(frame.filter(like="_member_count").min().min()) if len(frame) else 0, "outputs": {"raw": str(raw_path), "csv": str(csv_path), "parquet": str(parquet_path)}, "manifest": str(manifest_path)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
