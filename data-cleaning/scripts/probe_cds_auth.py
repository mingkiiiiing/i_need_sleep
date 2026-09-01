"""Inspect CDS/EWDS API configuration without exposing an API key."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
DEFAULT_OUTPUT = STORAGE / "manifests" / "cds_auth_probe.json"
REQUIRED_ENV = ("TAIHU_CDS_API_KEY",)
ENDPOINTS = {
    "cds": "https://cds.climate.copernicus.eu/api",
    "ewds": "https://ewds.climate.copernicus.eu/api",
}
KEY_LINE = re.compile(r"^\s*(?:key|api_key|apikey)\s*:\s*(\S+)\s*$", re.IGNORECASE)
URL_LINE = re.compile(r"^\s*url\s*:\s*(\S+)\s*$", re.IGNORECASE)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_config_paths() -> list[Path]:
    home = Path.home()
    return [home / ".cdsapirc", home / ".ewdsapirc", home / ".config" / "cdsapi" / "config"]


def _file_metadata(path: Path) -> dict:
    result = {"path": str(path), "exists": path.exists(), "readable": False, "key_present": False, "url_present": False}
    if not result["exists"]:
        return result
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return result
    result["readable"] = True
    for line in text.splitlines():
        key_match = KEY_LINE.match(line)
        if key_match and key_match.group(1).strip():
            result["key_present"] = True
        if URL_LINE.match(line):
            result["url_present"] = True
    return result


def probe(
    env: Mapping[str, str] | None = None,
    config_paths: Sequence[Path] | None = None,
    output_path: Path | None = None,
) -> dict:
    """Inspect environment/config presence and write a redacted manifest.

    This task intentionally verifies configuration readability only. Actual
    dataset requests are performed by the later ERA5/C3S/GloFAS adapters.
    """

    env = os.environ if env is None else env
    output_path = DEFAULT_OUTPUT if output_path is None else Path(output_path)
    paths = list(default_config_paths() if config_paths is None else config_paths)
    env_present = bool(str(env.get("TAIHU_CDS_API_KEY", "")).strip())
    files = [_file_metadata(Path(path)) for path in paths]
    file_key_present = any(item["readable"] and item["key_present"] for item in files)
    configured = env_present or file_key_present
    manifest = {
        "schema_version": "1.0",
        "source_ids": ["era5_land", "c3s_seasonal", "glofas_forecast"],
        "generated_at_utc": _now_utc(),
        "endpoints": ENDPOINTS,
        "required_env": list(REQUIRED_ENV),
        "present_env": {"TAIHU_CDS_API_KEY": env_present},
        "config_files": files,
        "config_source": "environment" if env_present else ("config_file" if file_key_present else None),
        "status": "CONFIGURED_PENDING_TERMS" if configured else "BLOCKED_AUTH",
        "terms_status": "pending_manual_confirmation",
        "network_probe_attempted": False,
        "redaction": "API key and file contents are never persisted or printed.",
    }
    if not configured:
        manifest["error_class"] = "MissingCDSConfiguration"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = probe(output_path=args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "config_source": result["config_source"],
                "network_probe_attempted": result["network_probe_attempted"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
