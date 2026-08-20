import hashlib
import json
from pathlib import Path

import pytest

from pipeline.sources.common import download_asset


class _InterruptingResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __init__(self):
        self.calls = 0

    def read(self, _size):
        self.calls += 1
        if self.calls == 1:
            return b"abcd"
        raise OSError("simulated connection interruption")


class _ResumeResponse:
    status = 206

    def __init__(self):
        self.done = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _size):
        if self.done:
            return b""
        self.done = True
        return b"efgh"


def test_interrupted_download_resumes_partial_and_atomically_renames(tmp_path):
    output = tmp_path / "asset.bin"
    expected = hashlib.sha256(b"abcdefgh").hexdigest()
    first_calls = []

    def first_open(request, timeout):
        first_calls.append((request.headers.get("Range"), timeout))
        return _InterruptingResponse()

    with pytest.raises(OSError):
        download_asset(
            "source_a",
            "asset_001",
            "https://example.test/asset.bin",
            output,
            expected_sha256=expected,
            opener=first_open,
        )
    partial = output.with_suffix(".bin.partial")
    assert partial.read_bytes() == b"abcd"
    assert not output.exists()
    assert first_calls[0][0] is None

    second_calls = []

    def second_open(request, timeout):
        second_calls.append((request.headers.get("Range"), timeout))
        return _ResumeResponse()

    result = download_asset(
        "source_a",
        "asset_001",
        "https://example.test/asset.bin?token=secret",
        output,
        expected_sha256=expected,
        opener=second_open,
    )
    assert result["status"] == "completed"
    assert result["resumed"] is True
    assert output.read_bytes() == b"abcdefgh"
    assert not partial.exists()
    assert second_calls[0][0] == "bytes=4-"


def test_same_source_asset_checksum_is_not_downloaded_twice(tmp_path):
    output = tmp_path / "asset.bin"
    output.write_bytes(b"stable")
    expected = hashlib.sha256(b"stable").hexdigest()
    calls = []

    def should_not_open(*args, **kwargs):
        calls.append(True)
        raise AssertionError("idempotent asset should not be requested")

    first = download_asset(
        "source_b",
        "asset_002",
        "https://example.test/asset.bin",
        output,
        expected_sha256=expected,
        opener=should_not_open,
    )
    second = download_asset(
        "source_b",
        "asset_002",
        "https://example.test/asset.bin",
        output,
        expected_sha256=expected,
        opener=should_not_open,
    )
    assert first["status"] == "skipped_existing"
    assert second["status"] == "skipped_existing"
    assert calls == []
    manifest = json.loads(Path(first["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_id"] == "source_b"
    assert manifest["asset_id"] == "asset_002"
    assert manifest["checksum_sha256"] == expected
