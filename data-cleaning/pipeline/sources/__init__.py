"""Source adapters. Adapters only fetch and preserve raw responses."""

from .copernicus_stac import ingest_sentinel2_stac
from .nasa_power import ingest_nasa_power
from .open_meteo import ingest_open_meteo_forecast
from .lake_geodata import probe_lake_geodata_sources, summarize_lake_geodata_html
from .water_station import ingest_water_station_endpoint, normalize_water_station_file, normalize_water_station_rows, run_water_station_parse
from .zenodo import download_thqbca_archive, extract_thqbca_workbooks, ingest_thqbca_metadata, list_thqbca_archive

__all__ = ["ingest_sentinel2_stac", "ingest_nasa_power", "ingest_open_meteo_forecast", "probe_lake_geodata_sources", "summarize_lake_geodata_html", "ingest_water_station_endpoint", "normalize_water_station_file", "normalize_water_station_rows", "run_water_station_parse", "ingest_thqbca_metadata", "download_thqbca_archive", "list_thqbca_archive", "extract_thqbca_workbooks"]
