from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

from .common import IngestResult, request_json, utc_now, write_raw_json


ZENODO_URL = "https://zenodo.org/api/records/13917285"


def ingest_thqbca_metadata() -> IngestResult:
    retrieved_at = utc_now()
    try:
        status, content_type, payload = request_json(ZENODO_URL)
        files = payload.get("files", [])
        raw_path = write_raw_json("taihu_thqbca_zenodo", ZENODO_URL, status, content_type, payload)
        return IngestResult(
            source_id="taihu_thqbca_zenodo",
            status="metadata_ingested" if status == 200 else "failed",
            request_url=ZENODO_URL,
            raw_path=str(raw_path),
            records=len(files),
            retrieved_at=retrieved_at,
            metadata={
                "title": payload.get("metadata", {}).get("title"),
                "doi": payload.get("metadata", {}).get("doi"),
                "files": [
                    {
                        "key": item.get("key"),
                        "size": item.get("size"),
                        "checksum": item.get("checksum"),
                        "download": item.get("links", {}).get("self"),
                    }
                    for item in files
                ],
                "archive_downloaded": False,
            },
        )
    except Exception as exc:
        return IngestResult("taihu_thqbca_zenodo", "failed", ZENODO_URL, None, 0, retrieved_at, str(exc))


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_thqbca_archive(output: Path, expected_md5: str | None = None) -> dict[str, str | int | bool]:
    """Download the large archive with Range resume and final MD5 verification."""
    download_url = "https://zenodo.org/api/records/13917285/files/THQBCA-V2.rar/content"
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    if output.exists() and expected_md5:
        actual = _md5_file(output)
        if actual.lower() == expected_md5.lower():
            return {"path": str(output), "size": output.stat().st_size, "md5": actual, "verified": True, "resumed": False}
        output.unlink()

    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "A23-Taihu-data-pipeline/0.2"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(download_url, headers=headers)
    response = urlopen(request, timeout=120)
    resumed = offset > 0 and response.getcode() == 206
    if not resumed:
        offset = 0
        partial.unlink(missing_ok=True)
    digest = hashlib.md5()
    if resumed:
        with partial.open("rb") as existing:
            for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                digest.update(chunk)
    size = offset
    try:
        with response, partial.open("ab" if resumed else "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    finally:
        response.close()
    actual_md5 = digest.hexdigest()
    if expected_md5 and actual_md5.lower() != expected_md5.lower():
        raise ValueError(f"MD5 mismatch: expected={expected_md5}, actual={actual_md5}; partial retained at {partial}")
    partial.replace(output)
    return {"path": str(output), "size": size, "md5": actual_md5, "verified": bool(expected_md5), "resumed": resumed}


def list_thqbca_archive(archive: Path, manifest_path: Path) -> dict[str, str | int | bool]:
    """List archive members without extracting the 925 MB source file."""
    tool = shutil.which("bsdtar") or shutil.which("tar") or r"C:\Anaconda\Library\bin\bsdtar.exe"
    if not Path(tool).exists() and shutil.which(tool) is None:
        raise FileNotFoundError("no tar/bsdtar executable available for RAR listing")
    completed = subprocess.run([tool, "-tf", str(archive)], capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(f"archive listing failed: {completed.stderr[-1000:]}")
    members = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "archive": str(archive),
        "member_count": len(members),
        "members": members,
        "top_level": sorted({member.replace("\\", "/").split("/")[0] for member in members}),
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": str(manifest_path), "member_count": len(members), "listed": True}


def extract_thqbca_workbooks(archive: Path, output_root: Path) -> dict[str, str | bool]:
    """Extract only the two tabular workbooks needed for first-pass modeling."""
    tool = shutil.which("bsdtar") or shutil.which("tar") or r"C:\Anaconda\Library\bin\bsdtar.exe"
    if not Path(tool).exists() and shutil.which(tool) is None:
        raise FileNotFoundError("no tar/bsdtar executable available for RAR extraction")
    members = [
        "THQBCA-V2/1.WaterQuality/1WaterQuality.xlsx",
        "THQBCA-V2/3.Climate/3.Climate.xlsx",
    ]
    output_root.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run([tool, "-xf", str(archive), "-C", str(output_root), *members], capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError(f"workbook extraction failed: {completed.stderr[-1000:]}")
    paths = {"water_quality": str(output_root / members[0]), "climate": str(output_root / members[1])}
    missing = [path for path in paths.values() if not Path(path).exists()]
    if missing:
        raise FileNotFoundError(f"extraction completed but expected files are missing: {missing}")
    return {**paths, "extracted": True}
