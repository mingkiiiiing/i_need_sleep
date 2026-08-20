"""Safely validate a NASA Earthdata bearer token without persisting it."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).parents[1]
DEFAULT_OUTPUT = ROOT / "storage" / "manifests" / "earthdata_auth_probe.json"
TOKEN_ENV = "TAIHU_EARTHDATA_TOKEN"
TOKEN_ENDPOINT = "https://urs.earthdata.nasa.gov/api/users/tokens"


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def probe(
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] | None = None,
    output_path: Path | None = None,
    timeout: int = 20,
) -> dict:
    """Validate a token and write only redacted response metadata."""

    env = os.environ if env is None else env
    output_path = DEFAULT_OUTPUT if output_path is None else Path(output_path)
    token = str(env.get(TOKEN_ENV, "")).strip()
    manifest = {
        "schema_version": "1.0",
        "source_ids": ["gpm_imerg", "nasa_lance_modis_viirs", "nasa_oceancolor"],
        "generated_at_utc": _now_utc(),
        "endpoint": TOKEN_ENDPOINT,
        "required_env": [TOKEN_ENV],
        "present_env": {TOKEN_ENV: bool(token)},
        "token_request_attempted": False,
        "token_validated": False,
        "http_status": None,
        "status": "PROBE_ERROR",
        "error_class": None,
        "redaction": "Token value and response body are never persisted or printed.",
    }
    if not token:
        manifest.update(status="BLOCKED_AUTH", error_class="MissingEarthdataToken")
    else:
        request = Request(
            TOKEN_ENDPOINT,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        opener = urlopen if opener is None else opener
        manifest["token_request_attempted"] = True
        try:
            with opener(request, timeout=timeout) as response:
                manifest["http_status"] = int(response.status)
                response.read()
            if manifest["http_status"] == 200:
                manifest.update(status="AUTHENTICATED", token_validated=True)
            else:
                manifest.update(status="AUTH_FAILED", error_class="UnexpectedHTTPStatus")
        except HTTPError as exc:
            manifest.update(status="AUTH_FAILED", http_status=int(exc.code), error_class="HTTPError")
        except (URLError, TimeoutError):
            manifest.update(status="PROBE_ERROR", error_class="NetworkError")
        except Exception as exc:  # pragma: no cover - defensive redaction boundary
            manifest.update(status="PROBE_ERROR", error_class=type(exc).__name__)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    result = probe(output_path=args.output, timeout=args.timeout)
    print(
        json.dumps(
            {
                "status": result["status"],
                "token_request_attempted": result["token_request_attempted"],
                "token_validated": result["token_validated"],
                "http_status": result["http_status"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
