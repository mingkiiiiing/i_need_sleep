from __future__ import annotations

import os
from pathlib import Path


def manifest_root(package_root: Path) -> Path:
    """Return the manifest directory, allowing test runs to stay isolated."""

    override = os.environ.get("A23_MANIFEST_ROOT")
    return Path(override) if override else Path(package_root) / "storage" / "manifests"


def staging_root(package_root: Path) -> Path:
    """Return the staging directory, allowing test runs to stay isolated."""

    override = os.environ.get("A23_STAGING_ROOT")
    return Path(override) if override else Path(package_root) / "storage" / "staging"
