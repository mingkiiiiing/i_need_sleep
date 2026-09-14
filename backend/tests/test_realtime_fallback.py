"""实时轨目录解析：silver 缺失时回退随仓库分发的冻结采集历史。"""
from __future__ import annotations

from pathlib import Path

import backend.app.providers as providers


def _make_catalog(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "stations.json").write_text("{}", encoding="utf-8")
    (base / "status.json").write_text("{}", encoding="utf-8")
    return base


def test_default_prefers_live_silver(tmp_path, monkeypatch):
    live = _make_catalog(tmp_path / "live")
    monkeypatch.setattr(providers, "_DEFAULT_REALTIME_DIR", live)
    monkeypatch.delenv(providers.REALTIME_CATALOG_ENV, raising=False)
    provider = providers.MeeRealtimeObservationProvider()
    assert provider._catalog_dir == live


def test_falls_back_to_shipped_history_when_silver_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "_DEFAULT_REALTIME_DIR", tmp_path / "missing")
    monkeypatch.delenv(providers.REALTIME_CATALOG_ENV, raising=False)
    assert providers._catalog_present(providers._SHIPPED_REALTIME_DIR), (
        "随仓库分发的冻结采集历史必须存在（data/realtime_history/mee_realtime）"
    )
    provider = providers.MeeRealtimeObservationProvider()
    assert provider._catalog_dir == providers._SHIPPED_REALTIME_DIR


def test_env_var_beats_everything(tmp_path, monkeypatch):
    live = _make_catalog(tmp_path / "live")
    monkeypatch.setattr(providers, "_DEFAULT_REALTIME_DIR", live)
    monkeypatch.setenv(providers.REALTIME_CATALOG_ENV, str(tmp_path / "env"))
    provider = providers.MeeRealtimeObservationProvider()
    assert provider._catalog_dir == Path(tmp_path / "env")
