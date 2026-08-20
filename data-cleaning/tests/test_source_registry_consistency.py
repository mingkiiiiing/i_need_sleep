from __future__ import annotations

import csv
from pathlib import Path

import yaml


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"
SOURCES_PATH = CONFIG_ROOT / "sources.yml"
REGISTRY_PATH = CONFIG_ROOT / "data_source_registry.csv"


def _load_sources() -> list[dict[str, object]]:
    config = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    return list(config.get("sources", []))


def _load_registry() -> list[dict[str, str]]:
    with REGISTRY_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_runtime_sources_have_registry_rows_and_registry_statuses() -> None:
    runtime_sources = _load_sources()
    registry = _load_registry()
    runtime_ids = [str(source["source_id"]) for source in runtime_sources]
    registry_ids = [row["source_id"] for row in registry]

    assert len(runtime_ids) == len(set(runtime_ids))
    assert len(registry_ids) == len(set(registry_ids))
    assert set(runtime_ids).issubset(set(registry_ids))
    assert "automation_status" in registry[0]
    assert all(row["automation_status"] for row in registry)
    assert all(row["endpoint_or_url"] for row in registry)


def test_registry_marks_runtime_and_pending_sources_without_claiming_unimplemented_ones() -> None:
    registry = _load_registry()
    by_id = {row["source_id"]: row for row in registry}

    assert by_id["copernicus_sentinel2_stac"]["automation_status"] == "runtime_configured"
    assert by_id["nasa_power_hourly"]["automation_status"] == "runtime_configured"
    assert by_id["taihu_thqbca_zenodo"]["automation_status"] == "runtime_configured"
    assert by_id["open_meteo_forecast"]["automation_status"] == "runtime_configured"
    assert by_id["mee_water_station_protocol"]["automation_status"] == "config_only_pending_adapter"
    assert by_id["cma_cldas"]["automation_status"] == "config_only_pending_adapter"
    assert by_id["tba_taihu_portal"]["automation_status"] == "config_only_pending_adapter"
    assert by_id["niglas_lake_geodata"]["automation_status"] == "config_only_pending_adapter"
    assert by_id["gpm_imerg"]["automation_status"] == "adapter_ready_auth_blocked"
    assert by_id["earth_search_sentinel2_l2a"]["automation_status"] == "runtime_verified"
    assert by_id["zenodo_taihu_insitu_10434391"]["automation_status"] == "runtime_verified"
    assert by_id["open_meteo_ecmwf_seas5"]["automation_status"] == "runtime_verified"
    assert all(
        row["automation_status"] == "registry_only_not_implemented"
        for row in registry
        if row["source_id"] not in {
            "copernicus_sentinel2_stac",
            "nasa_power_hourly",
            "taihu_thqbca_zenodo",
            "open_meteo_forecast",
            "mee_water_station_protocol",
            "cma_cldas",
            "tba_taihu_portal",
            "niglas_lake_geodata",
            "gpm_imerg",
            "earth_search_sentinel2_l2a",
            "zenodo_taihu_insitu_10434391",
            "open_meteo_ecmwf_seas5",
        }
    )
