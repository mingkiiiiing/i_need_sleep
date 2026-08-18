from __future__ import annotations

from urllib.parse import urlencode

from .common import IngestResult, request_json, utc_now, write_raw_json


POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def ingest_nasa_power(
    start: str,
    end: str,
    longitude: float = 120.30,
    latitude: float = 31.20,
) -> IngestResult:
    params = {
        "parameters": "T2M,WS10M,WD10M,PRECTOTCORR,ALLSKY_SFC_SW_DWN",
        "community": "RE",
        "longitude": f"{longitude:.6f}",
        "latitude": f"{latitude:.6f}",
        "start": start.replace("-", ""),
        "end": end.replace("-", ""),
        "format": "JSON",
    }
    url = POWER_URL + "?" + urlencode(params)
    retrieved_at = utc_now()
    try:
        status, content_type, payload = request_json(url)
        parameters = payload.get("properties", {}).get("parameter", {})
        record_count = len(parameters.get("T2M", {}))
        raw_path = write_raw_json("nasa_power_hourly", url, status, content_type, payload)
        return IngestResult(
            source_id="nasa_power_hourly",
            status="ingested" if status == 200 else "failed",
            request_url=url,
            raw_path=str(raw_path),
            records=record_count,
            retrieved_at=retrieved_at,
            metadata={
                "longitude": longitude,
                "latitude": latitude,
                "parameters": sorted(parameters.keys()),
                "units": payload.get("parameters", {}),
                "time_standard": payload.get("header", {}).get("time_standard"),
            },
        )
    except Exception as exc:
        return IngestResult("nasa_power_hourly", "failed", url, None, 0, retrieved_at, str(exc))
