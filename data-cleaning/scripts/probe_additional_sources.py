"""Probe availability of additional data sources:
1. GOCI/GOCI-II (NOSC/KOSC)
2. CASEarth 2022 Taihu data
3. 2019 Taihu random forest bloom data
4. Taihu auto station historical data (MEE)
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
RESULTS = STORAGE / "manifests" / "probe_additional_sources.json"


def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = "Taihu-bloom-project/1.0 (research)"
    return s


def probe_goci(session):
    """Check GOCI/GOCI-II data availability from KOSC/NOSC"""
    print("\n=== 1. GOCI/GOCI-II Probe ===")
    results = {"source": "GOCI/GOCI-II", "status": "unknown", "details": {}}

    urls_to_check = [
        ("KOSC", "https://kosc.kiost.ac.kr/"),
        ("NOSC", "https://nosc.nfra.go.kr/"),
        ("GOCI Portal", "http://goci.nfrda.go.kr/"),
        ("KOSC Data", "https://kosc.kiost.ac.kr/data"),
    ]

    for name, url in urls_to_check:
        try:
            resp = session.get(url, timeout=20, allow_redirects=True)
            results["details"][name] = {
                "url": url,
                "status_code": resp.status_code,
                "accessible": resp.status_code < 400,
                "final_url": resp.url,
            }
            print(f"  {name}: HTTP {resp.status_code} ({'OK' if resp.status_code < 400 else 'FAIL'})")
        except Exception as e:
            results["details"][name] = {"url": url, "error": str(e)[:100]}
            print(f"  {name}: ERROR {str(e)[:60]}")

    try:
        search_url = "https://kosc.kiost.ac.kr/data/search"
        resp = session.get(search_url, timeout=20, params={
            "sensor": "GOCI",
            "level": "L1B",
        })
        results["details"]["search_test"] = {
            "status_code": resp.status_code,
            "content_length": len(resp.text),
        }
    except Exception as e:
        results["details"]["search_test"] = {"error": str(e)[:100]}

    results["recommendation"] = (
        "Register at KOSC (kosc.kiost.ac.kr) for GOCI/GOCI-II access. "
        "GOCI: 2011-05 to 2019, GOCI-II: 2020-present. "
        "Need to check if Taihu (119.9-120.75E, 30.9-31.65N) is in their coverage."
    )
    return results


def probe_casearth(session):
    """Check CASEarth 2022 Taihu data availability"""
    print("\n=== 2. CASEarth 2022 Taihu Data Probe ===")
    results = {"source": "CASEarth_2022_Taihu", "status": "unknown", "details": {}}

    urls = [
        ("CASEarth Main", "https://casearth.cn/"),
        ("CASEarth Data", "https://data.casearth.cn/"),
        ("CASEarth Search", "https://data.casearth.cn/sdo/search"),
    ]

    for name, url in urls:
        try:
            resp = session.get(url, timeout=20, allow_redirects=True)
            results["details"][name] = {
                "url": url,
                "status_code": resp.status_code,
                "accessible": resp.status_code < 400,
            }
            print(f"  {name}: HTTP {resp.status_code}")
        except Exception as e:
            results["details"][name] = {"error": str(e)[:100]}
            print(f"  {name}: ERROR {str(e)[:60]}")

    try:
        search_url = "https://data.casearth.cn/sdo/search"
        resp = session.get(search_url, timeout=20, params={"keyword": "太湖"})
        results["details"]["taihu_search"] = {
            "status_code": resp.status_code,
            "content_length": len(resp.text),
            "has_results": "太湖" in resp.text or "Taihu" in resp.text,
        }
        print(f"  Taihu search: HTTP {resp.status_code}, has_results={results['details']['taihu_search']['has_results']}")
    except Exception as e:
        results["details"]["taihu_search"] = {"error": str(e)[:100]}
        print(f"  Taihu search: ERROR {str(e)[:60]}")

    results["recommendation"] = (
        "Register at data.casearth.cn, search for '太湖' or 'Taihu'. "
        "Look for 2022 annual dataset with 36 GeoTIFFs, 10m resolution, ~1.07GB."
    )
    return results


def probe_2019_bloom(session):
    """Check 2019 Taihu random forest bloom data availability"""
    print("\n=== 3. 2019 Taihu Bloom Data Probe ===")
    results = {"source": "2019_Taihu_Bloom_RF", "status": "unknown", "details": {}}

    zenodo_urls = [
        ("Zenodo search", "https://zenodo.org/api/records?q=taihu+cyanobacteria&size=5"),
        ("Zenodo search 2", "https://zenodo.org/api/records?q=taihu+bloom+random+forest&size=5"),
    ]

    for name, url in zenodo_urls:
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])
                results["details"][name] = {
                    "status_code": 200,
                    "total_hits": data.get("hits", {}).get("total", 0),
                    "records": [
                        {"id": h["id"], "title": h.get("metadata", {}).get("title", "?")[:80],
                         "doi": h.get("doi", "")}
                        for h in hits[:3]
                    ],
                }
                print(f"  {name}: {len(hits)} hits")
                for h in hits[:3]:
                    print(f"    [{h['id']}] {h.get('metadata',{}).get('title','?')[:60]}")
            else:
                results["details"][name] = {"status_code": resp.status_code}
                print(f"  {name}: HTTP {resp.status_code}")
        except Exception as e:
            results["details"][name] = {"error": str(e)[:100]}
            print(f"  {name}: ERROR {str(e)[:60]}")

    geodata_urls = [
        ("geodata.cn search", "https://www.geodata.cn/main/face_science_detail?guid=30292244868129"),
    ]
    for name, url in geodata_urls:
        try:
            resp = session.get(url, timeout=20)
            results["details"][name] = {
                "status_code": resp.status_code,
                "content_length": len(resp.text),
            }
            print(f"  {name}: HTTP {resp.status_code}")
        except Exception as e:
            results["details"][name] = {"error": str(e)[:100]}
            print(f"  {name}: ERROR {str(e)[:60]}")

    results["recommendation"] = (
        "Search Zenodo for 'Taihu cyanobacteria' or 'Taihu_Cyanobacteria.rar'. "
        "Also check geodata.cn and lake.geodata.cn for the 2019 random forest dataset. "
        "Actual dates: 2018-10-28, 2019-04-06, 2019-06-03."
    )
    return results


def probe_taihu_auto_station(session):
    """Check Taihu auto station historical data availability"""
    print("\n=== 4. Taihu Auto Station Historical Data Probe ===")
    results = {"source": "Taihu_Auto_Station", "status": "unknown", "details": {}}

    urls = [
        ("MEE Realtime", "https://szzdjc.cnemc.cn:8070/GJZ/Business/Publish/Main.html"),
        ("MEE Data Portal", "https://data.cnemc.cn/"),
        ("CMA Data", "https://data.cma.cn/"),
        ("CMA Mekb", "https://k.data.cma.cn/mekb/"),
    ]

    for name, url in urls:
        try:
            resp = session.get(url, timeout=20, allow_redirects=True)
            results["details"][name] = {
                "url": url,
                "status_code": resp.status_code,
                "accessible": resp.status_code < 400,
                "final_url": resp.url,
            }
            print(f"  {name}: HTTP {resp.status_code} ({'OK' if resp.status_code < 400 else 'FAIL'})")
        except Exception as e:
            results["details"][name] = {"error": str(e)[:100]}
            print(f"  {name}: ERROR {str(e)[:60]}")

    try:
        api_url = "https://szzdjc.cnemc.cn:8070/GJZ/Business/Publish/AirDataNew.aspx"
        resp = session.get(api_url, timeout=20, params={
            "stationcode": "",
            "starttime": "2024-01-01",
            "endtime": "2024-01-31",
        })
        results["details"]["mee_api_test"] = {
            "status_code": resp.status_code,
            "content_length": len(resp.text),
        }
        print(f"  MEE API test: HTTP {resp.status_code}")
    except Exception as e:
        results["details"]["mee_api_test"] = {"error": str(e)[:100]}
        print(f"  MEE API test: ERROR {str(e)[:60]}")

    results["recommendation"] = (
        "Taihu auto station historical data requires:\n"
        "  1. Check MEE portal (szzdjc.cnemc.cn) for historical archive or API\n"
        "  2. Contact CNEMC for data access agreement\n"
        "  3. Verify sample contains: station name/coords, 4h frequency, "
        "water_temp/chl_a/algae_density, quality flags\n"
        "  4. Must cover 2+ complete bloom seasons\n"
        "  5. License must allow algorithm training\n"
        "  Without chl_a/algae_density or continuous stations, DO NOT purchase."
    )
    return results


def main():
    session = make_session()
    all_results = {}

    all_results["goci"] = probe_goci(session)
    time.sleep(1)
    all_results["casearth"] = probe_casearth(session)
    time.sleep(1)
    all_results["2019_bloom"] = probe_2019_bloom(session)
    time.sleep(1)
    all_results["taihu_auto_station"] = probe_taihu_auto_station(session)

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "results": all_results,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"\n=== Probe Results saved to: {RESULTS} ===")
    return 0


if __name__ == "__main__":
    main()
