from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

_TEST_ARTIFACT_ROOT: Path | None = None


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    global _TEST_ARTIFACT_ROOT
    _TEST_ARTIFACT_ROOT = Path(tempfile.mkdtemp(prefix="a23-data-cleaning-tests-"))
    os.environ["A23_MANIFEST_ROOT"] = str(_TEST_ARTIFACT_ROOT / "manifests")
    os.environ["A23_STAGING_ROOT"] = str(_TEST_ARTIFACT_ROOT / "staging")


def pytest_unconfigure(config) -> None:  # type: ignore[no-untyped-def]
    os.environ.pop("A23_MANIFEST_ROOT", None)
    os.environ.pop("A23_STAGING_ROOT", None)
    if _TEST_ARTIFACT_ROOT is not None:
        shutil.rmtree(_TEST_ARTIFACT_ROOT, ignore_errors=True)
