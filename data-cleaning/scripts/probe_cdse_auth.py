"""Safely probe Copernicus Data Space OAuth credentials.

The probe deliberately records only presence/absence and response metadata. It
never writes client secrets or access tokens to the manifest or stdout.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
DEFAULT_OUTPUT = STORAGE / "manifests" / "cdse_auth_probe.json"
TOKEN_ENDPOINT = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
REQUIRED_ENV = ("TAIHU_CDSE_CLIENT_ID", "TAIHU_CDSE_CLIENT_SECRET")


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _base_manifest(env: Mapping[str, str]) -> dict:
    present = {name: bool(str(env.get(name, "")).strip()) for name in REQUIRED_ENV}
    return {
        "schema_version": "1.0",
        "source_id": "copernicus_sentinel2_stac",
        "generated_at_utc": _now_utc(),
        "endpoint": TOKEN_ENDPOINT,
        "required_env": list(REQUIRED_ENV),
        "present_env": present,
        "token_request_attempted": False,
        "token_received": False,
        "http_status": None,
        "status": "PROBE_ERROR",
        "error_class": None,
        "redaction": "Credential values and token payloads are never persisted or printed.",
    }


def _write_manifest(manifest: dict, output_path: Path) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def probe(
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] | None = None,
    output_path: Path | None = None,
    timeout: int = 20,
) -> dict:
    """Probe CDSE credentials and write a redacted manifest.

    ``opener`` is injectable so tests can exercise authenticated and failed
    responses without making a real network request.
    """

    env = os.environ if env is None else env
    output_path = DEFAULT_OUTPUT if output_path is None else Path(output_path)
    manifest = _base_manifest(env)
    missing = [name for name, present in manifest["present_env"].items() if not present]
    if missing:
        manifest.update(
            status="BLOCKED_AUTH",
            missing_env=missing,
            error_class="MissingCredentialEnvironment",
        )
        return _write_manifest(manifest, output_path)

    request_data = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": str(env["TAIHU_CDSE_CLIENT_ID"]),
            "client_secret": str(env["TAIHU_CDSE_CLIENT_SECRET"]),
        }
    ).encode("utf-8")
    request = Request(
        TOKEN_ENDPOINT,
        data=request_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener = urlopen if opener is None else opener
    manifest["token_request_attempted"] = True
    try:
        with opener(request, timeout=timeout) as response:
            manifest["http_status"] = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
        if manifest["http_status"] == 200 and bool(payload.get("access_token")):
            manifest.update(status="AUTHENTICATED", token_received=True)
        else:
            manifest.update(status="AUTH_FAILED", error_class="MissingAccessToken")
    except HTTPError as exc:
        manifest.update(status="AUTH_FAILED", http_status=int(exc.code), error_class="HTTPError")
    except (URLError, TimeoutError):
        manifest.update(status="PROBE_ERROR", error_class="NetworkError")
    except (ValueError, TypeError, KeyError):
        manifest.update(status="PROBE_ERROR", error_class="InvalidTokenResponse")
    except Exception as exc:  # pragma: no cover - defensive redaction boundary
        manifest.update(status="PROBE_ERROR", error_class=type(exc).__name__)
    return _write_manifest(manifest, output_path)


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
                "token_received": result["token_received"],
                "http_status": result["http_status"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
