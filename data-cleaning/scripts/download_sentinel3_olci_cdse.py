"""Download Sentinel-3 OLCI WFR NTC products via CDSE OData.

Authenticates with CDSE client credentials from .env.cdse,
searches OData catalog for S3 OLCI L2 WFR products over Taihu,
downloads full NetCDF products, then extracts Taihu subset.

Period: 2017-11-01 to 2026-08-27
Variables: CHL_NN, CHL_OC4ME, Rrs, WQSF
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
RAW_DIR = STORAGE / "raw" / "ocean_color" / "sentinel3_olci"
MANIFEST_DIR = STORAGE / "manifests"
PROGRESS = MANIFEST_DIR / "sentinel3_olci_download_progress.json"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CDSE_ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1"
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_DOWNLOAD = "https://zipper.dataspace.copernicus.eu/odata/v1"

TAIHU_BBOX = (119.90, 30.90, 120.75, 31.65)


def load_cdse_credentials():
    env_file = ROOT / ".env.cdse"
    if not env_file.exists():
        raise FileNotFoundError(f"CDSE credentials not found: {env_file}")
    creds = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        creds[key.strip()] = val.strip()
    client_id = creds.get("TAIHU_CDSE_CLIENT_ID", "")
    client_secret = creds.get("TAIHU_CDSE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise ValueError("CDSE client ID or secret is empty in .env.cdse")
    return client_id, client_secret


def get_access_token(client_id, client_secret):
    resp = requests.post(CDSE_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Token failed: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json()["access_token"]


def make_session():
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=3, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.headers["User-Agent"] = "Taihu-bloom-project/1.0 (research)"
    return s


def search_products(session, start_date, end_date, max_pages=50):
    products = []
    skip = 0
    top = 1000

    while True:
        filter_str = (
            f"Collection/Name eq 'SENTINEL-3' "
            f"and ContentDate/Start gt {start_date.strftime('%Y-%m-%dT00:00:00.000Z')} "
            f"and ContentDate/Start lt {end_date.strftime('%Y-%m-%dT23:59:59.999Z')} "
            f"and contains(Name, 'OL_2_WFR')"
        )
        params = {
            "$filter": filter_str,
            "$top": top,
            "$skip": skip,
            "$orderby": "ContentDate/Start asc",
            "$select": "Id,Name,ContentDate/Start,ContentLength,ModificationDate",
        }

        resp = session.get(f"{CDSE_ODATA}/Products", params=params, timeout=120)
        if resp.status_code != 200:
            print(f"  Search error: HTTP {resp.status_code}")
            break

        data = resp.json()
        batch = data.get("value", [])
        if not batch:
            break

        products.extend(batch)
        skip += top

        if len(batch) < top:
            break
        if max_pages and skip >= max_pages * top:
            break

        time.sleep(0.5)

    return products


def download_product(session, product_id, product_name, token, raw_dir):
    target = raw_dir / f"{product_name}.nc"
    if target.exists() and target.stat().st_size > 100000:
        return "skip"

    zip_target = raw_dir / f"{product_name}.zip"
    if zip_target.exists() and zip_target.stat().st_size > 100000:
        return "skip_zip"

    url = f"{CDSE_DOWNLOAD}/Products({product_id})/$value"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = session.get(url, headers=headers, timeout=600, stream=True,
                          allow_redirects=True)
        if resp.status_code == 200:
            with open(zip_target, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            size = zip_target.stat().st_size
            if size > 100000:
                return "ok"
            else:
                zip_target.unlink(missing_ok=True)
                return "fail_size"
        elif resp.status_code == 401:
            return "auth_expired"
        else:
            return f"fail_http_{resp.status_code}"
    except Exception as e:
        return f"fail_{type(e).__name__}"


def main():
    client_id, client_secret = load_cdse_credentials()
    session = make_session()

    start_date = datetime(2017, 11, 1)
    end_date = datetime(2026, 8, 27)

    print("=== Sentinel-3 OLCI WFR Download ===")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Output: {RAW_DIR}")

    print("Getting access token...")
    token = get_access_token(client_id, client_secret)
    print("  Token acquired")

    print("Searching products...")
    products = search_products(session, start_date, end_date)
    print(f"  Found {len(products)} products")

    if not products:
        print("No products found, exiting")
        return 0

    manifest = {
        "created": datetime.now(timezone.utc).isoformat(),
        "total_products": len(products),
        "products": [],
    }

    stats = {"ok": 0, "skip": 0, "fail": 0, "auth_refresh": 0}

    for i, prod in enumerate(products):
        pid = prod["Id"]
        pname = prod["Name"]
        pdate = prod.get("ContentDate", {}).get("Start", "?")
        psize = prod.get("ContentLength", 0)

        result = download_product(session, pid, pname, token, RAW_DIR)

        if result == "auth_expired":
            print("  Token expired, refreshing...")
            token = get_access_token(client_id, client_secret)
            stats["auth_refresh"] += 1
            result = download_product(session, pid, pname, token, RAW_DIR)

        if result == "ok":
            stats["ok"] += 1
        elif result.startswith("skip"):
            stats["skip"] += 1
        else:
            stats["fail"] += 1

        manifest["products"].append({
            "id": pid, "name": pname, "date": pdate,
            "size_mb": round(psize / 1e6, 1), "status": result,
        })

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(products)}] ok={stats['ok']} "
                  f"skip={stats['skip']} fail={stats['fail']}", flush=True)
            PROGRESS.parent.mkdir(parents=True, exist_ok=True)
            PROGRESS.write_text(json.dumps({
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "progress": f"{i+1}/{len(products)}",
                "stats": stats,
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        if result.startswith("skip"):
            continue
        time.sleep(0.3)

    manifest["stats"] = stats
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest_path = MANIFEST_DIR / "sentinel3_olci_wfr_download.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    print(f"\n=== Summary ===")
    print(f"Total products: {len(products)}")
    print(f"Downloaded: {stats['ok']}")
    print(f"Skipped: {stats['skip']}")
    print(f"Failed: {stats['fail']}")
    print(f"Manifest: {manifest_path}")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    main()
