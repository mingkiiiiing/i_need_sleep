from __future__ import annotations

from urllib.parse import urlencode

from .common import IngestResult, request_json, utc_now, write_raw_json


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def ingest_open_meteo_forecast(
    longitude: float = 120.30,
    latitude: float = 31.20,
    forecast_days: int = 7,
) -> IngestResult:
    """Fetch hourly weather fields for a Taihu point.

    This is a no-key meteorological fallback. It is not a water-quality or
    water-temperature sensor; values are preserved as ``forecast_proxy`` and
    should be replaced by an authorized official feed when available.
    """

    params = {
        "latitude": f"{latitude:.6f}",
        "longitude": f"{longitude:.6f}",
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation,shortwave_radiation",
        "forecast_days": str(max(1, min(int(forecast_days), 16))),
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "timezone": "UTC",
    }
    url = OPEN_METEO_URL + "?" + urlencode(params)
    retrieved_at = utc_now()
    try:
        status, content_type, payload = request_json(url)
        hourly = payload.get("hourly", {})
        records = len(hourly.get("time", []))
        raw_path = write_raw_json("open_meteo_forecast", url, status, content_type, payload)
        return IngestResult(
            source_id="open_meteo_forecast",
            status="ingested" if status == 200 and records else "failed",
            request_url=url,
            raw_path=str(raw_path),
            records=records,
            retrieved_at=retrieved_at,
            metadata={
                "longitude": longitude,
                "latitude": latitude,
                "forecast_days": forecast_days,
                "hourly_units": payload.get("hourly_units", {}),
                "model": payload.get("model") or payload.get("generationtime_ms"),
                "records_per_variable": records,
                "forecast_proxy": True,
            },
        )
    except Exception as exc:
        return IngestResult("open_meteo_forecast", "failed", url, None, 0, retrieved_at, str(exc))

