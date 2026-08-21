from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
LOCAL_ZONE_NAME = "Asia/Shanghai"
LOCAL_ZONE = ZoneInfo(LOCAL_ZONE_NAME)


def _timezone(value: str | None):
    if not value:
        return None
    text = str(value).strip()
    if text.upper() in {"Z", "UTC", "GMT", "+00:00"}:
        return UTC
    try:
        return ZoneInfo(text)
    except ZoneInfoNotFoundError:
        match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text)
        if match:
            minutes = int(match.group(2)) * 60 + int(match.group(3))
            if match.group(1) == "-":
                minutes = -minutes
            return timezone(timedelta(minutes=minutes))
    return None


def parse_time(value: Any, *, source_timezone: str | None = None) -> dict[str, str | None]:
    """Parse a timestamp without silently assigning a timezone.

    Naive values are accepted only when the caller supplies an explicit
    ``source_timezone``. The result always contains UTC and Asia/Shanghai
    representations so downstream code can use one canonical storage field
    while retaining the local display time.
    """

    result: dict[str, str | None] = {
        "status": "missing" if value in (None, "") else "invalid",
        "utc": None,
        "local": None,
        "source_timezone": source_timezone,
    }
    if value in (None, ""):
        return result
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value).strip()
        if not text:
            result["status"] = "missing"
            return result
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y%m%d%H", "%Y%m%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return result
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        tz = _timezone(source_timezone)
        if tz is None:
            result["status"] = "pending_timezone"
            return result
        parsed = parsed.replace(tzinfo=tz)
    utc_value = parsed.astimezone(UTC)
    local_value = parsed.astimezone(LOCAL_ZONE)
    result.update(
        {
            "status": "accepted",
            "utc": utc_value.isoformat(),
            "local": local_value.isoformat(),
            "source_timezone": source_timezone or str(parsed.tzinfo),
        }
    )
    return result

