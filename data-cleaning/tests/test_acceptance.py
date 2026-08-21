from pathlib import Path

from pipeline.acceptance import _sha256


def test_sha256_is_stable(tmp_path: Path):
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert _sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
