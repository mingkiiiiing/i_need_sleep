from __future__ import annotations

"""Download and structure the public MEE surface-water monthly reports."""

import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
INDEX_URL = "https://www.mee.gov.cn/hjzl/shj/dbsszyb/"
DEFAULT_RAW = STORAGE / "raw" / "mee_surface_water_monthly"
DEFAULT_SILVER = STORAGE / "silver" / "mee_taihu_monthly"
DEFAULT_MANIFEST = STORAGE / "manifests" / "mee_taihu_monthly_2022_2026.json"
REPORT_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*全国地表水水质月报")
_OCR_ENGINE: Any | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _get(url: str, *, timeout: int = 60) -> requests.Response:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "TaihuCompetitionDataAudit/1.0"})
    response.raise_for_status()
    return response


def discover_reports(index_pages: int = 4) -> list[dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for page in range(index_pages):
        url = INDEX_URL if page == 0 else urljoin(INDEX_URL, f"index_{page}.shtml")
        response = _get(url)
        soup = BeautifulSoup(response.content.decode("utf-8", "replace"), "html.parser")
        for anchor in soup.select("a[href]"):
            title = " ".join(anchor.get_text(" ", strip=True).split())
            match = REPORT_RE.search(title)
            if not match:
                continue
            year, month = int(match.group(1)), int(match.group(2))
            period = f"{year:04d}-{month:02d}"
            discovered[period] = {
                "period": period,
                "year": year,
                "month": month,
                "title": title,
                "landing_url": urljoin(url, anchor["href"]),
                "index_url": url,
            }
    return [discovered[key] for key in sorted(discovered)]


def _resolve_pdf(landing_url: str) -> str:
    if landing_url.lower().endswith(".pdf"):
        return landing_url
    response = _get(landing_url)
    soup = BeautifulSoup(response.content.decode("utf-8", "replace"), "html.parser")
    candidates = [urljoin(landing_url, anchor["href"]) for anchor in soup.select("a[href]") if ".pdf" in anchor["href"].lower()]
    if not candidates:
        candidates = [urljoin(landing_url, match) for match in re.findall(r"[.\w/-]+\.pdf", response.text, flags=re.I)]
    if not candidates:
        raise ValueError("No public PDF link found on landing page")
    return candidates[0]


def _extract_pdf_text(path: Path) -> tuple[str, int]:
    # MuPDF is substantially faster than pypdf on the image-heavy 50--70 MB
    # public monthly reports.  We still retain the source PDF and checksum.
    import fitz

    with fitz.open(path) as document:
        pages = [page.get_text("text") or "" for page in document]
        embedded = "\n".join(pages)
        if "太湖湖体" in embedded:
            return embedded, len(document)

        # The public reports are commonly image-only PDFs.  Taihu is the first
        # lake in the lake/reservoir chapter, normally within the final 15
        # pages, so OCR that bounded tail rather than all 40--60 pages.
        import numpy as np
        from rapidocr import RapidOCR

        global _OCR_ENGINE
        if _OCR_ENGINE is None:
            _OCR_ENGINE = RapidOCR()
        engine = _OCR_ENGINE
        ocr_pages: list[str] = []
        for page_index in range(max(0, len(document) - 15), len(document)):
            page = document[page_index]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
            result = engine(image)
            text = "\n".join(result.txts or ())
            ocr_pages.append(text)
            if "太湖湖体" in text or ("湖泊和水库" in text and "太湖" in text):
                return text, len(document)
        return "\n".join(ocr_pages), len(document)


def extract_taihu_section(text: str) -> str:
    normalized = text.replace("\u3000", " ").replace("\xa0", " ")
    starts = [match.start() for pattern in (r"(?:^|\n)\s*1\s+太湖", r"三、湖泊和水库\s*1\s*太湖") for match in re.finditer(pattern, normalized)]
    if not starts:
        location = normalized.find("太湖湖体")
        starts = [location] if location >= 0 else []
    if not starts:
        return ""
    start = min(starts)
    tail = normalized[start:]
    endings = [match.start() for pattern in (r"(?:^|\n)\s*2\s+(?:巢湖|滇池)", r"\n\s*2\.1\s*湖体") for match in re.finditer(pattern, tail)]
    end = min((value for value in endings if value > 20), default=len(tail))
    return re.sub(r"[ \t]+", " ", tail[:end]).strip()


def parse_taihu_section(section: str) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", section)
    lake_only = re.split(r"1\.2环湖河流", compact, maxsplit=1)[0]
    quality_only = re.split(r"营养状态评价", lake_only, maxsplit=1)[0]

    def capture(pattern: str, source: str = lake_only) -> str | None:
        match = re.search(pattern, source)
        return match.group(1) if match else None

    whole_lake_status = capture(r"(?:太湖)?全湖整体水质(?:为)?([^，。；]+)", quality_only) or capture(r"全湖整体为([^，。；]+)", quality_only)

    return {
        "monitoring_point_count": int(capture(r"太湖湖体共监测(\d+)个点位") or 0) or None,
        "whole_lake_status": whole_lake_status,
        "main_exceedance_indicators": capture(r"主要(?:污染|超标)指标为([^。；]+)", quality_only),
        "tn_assessment": capture(r"总氮单独评价时[：:]?(.*?)(?:营养状态评价|1\.2|环湖河流|$)"),
        "trophic_assessment": capture(r"营养状态评价表明[：:]?(.*?)(?:1\.2|环湖河流|主要环湖河流|$)"),
        "tp_concentration_mentions": "|".join(re.findall(r"总磷(?:平均)?浓度(?:为)?([0-9.]+\s*毫克/升|[0-9.]+\s*mg/L)", lake_only, flags=re.I)) or None,
        "tn_concentration_mentions": "|".join(re.findall(r"总氮(?:平均)?浓度(?:为)?([0-9.]+\s*毫克/升|[0-9.]+\s*mg/L)", lake_only, flags=re.I)) or None,
    }


def run_mee_taihu_monthly(
    start_period: str = "2022-01",
    end_period: str = "2026-06",
    *,
    raw_root: Path = DEFAULT_RAW,
    silver_root: Path = DEFAULT_SILVER,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    raw_root, silver_root, manifest_path = Path(raw_root), Path(silver_root), Path(manifest_path)
    raw_root.mkdir(parents=True, exist_ok=True)
    silver_root.mkdir(parents=True, exist_ok=True)
    reports = [item for item in discover_reports() if start_period <= item["period"] <= end_period]
    rows: list[dict[str, Any]] = []
    for index, report in enumerate(reports, start=1):
        period = report["period"]
        print(f"[{index}/{len(reports)}] MEE {period}", flush=True)
        row = dict(report)
        try:
            pdf_url = _resolve_pdf(report["landing_url"])
            pdf_path = raw_root / f"mee_surface_water_{period}.pdf"
            if not pdf_path.exists() or pdf_path.stat().st_size == 0:
                response = _get(pdf_url, timeout=120)
                pdf_path.write_bytes(response.content)
                time.sleep(0.15)
            text, page_count = _extract_pdf_text(pdf_path)
            section = extract_taihu_section(text)
            text_path = silver_root / f"taihu_{period}.txt"
            text_path.write_text(section, encoding="utf-8")
            row.update(
                status="completed" if section else "completed_no_taihu_section",
                pdf_url=pdf_url,
                pdf_path=str(pdf_path),
                pdf_bytes=pdf_path.stat().st_size,
                pdf_sha256=_sha256(pdf_path),
                pdf_pages=page_count,
                taihu_text_path=str(text_path),
                **parse_taihu_section(section),
            )
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
    csv_path = silver_root / "mee_taihu_monthly_2022_2026.csv"
    fieldnames = sorted({key for row in rows for key in row})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    expected = []
    year, month = map(int, start_period.split("-"))
    end_year, end_month = map(int, end_period.split("-"))
    while (year, month) <= (end_year, end_month):
        expected.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    found = {row["period"] for row in rows if row.get("status", "").startswith("completed")}
    manifest = {
        "run_id": f"mee_taihu_monthly_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "completed" if found == set(expected) else "completed_with_gaps",
        "source_id": "mee_surface_water_monthly_reports",
        "index_url": INDEX_URL,
        "period": [start_period, end_period],
        "expected_months": len(expected),
        "completed_months": len(found),
        "missing_months": sorted(set(expected) - found),
        "failed": [row for row in rows if row.get("status") == "failed"],
        "structured_csv": str(csv_path),
        "raw_root": str(raw_root),
        "rows": rows,
        "data_truth": "public report text and classifications; class labels are not converted to numeric concentrations",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


__all__ = ["discover_reports", "extract_taihu_section", "parse_taihu_section", "run_mee_taihu_monthly"]
