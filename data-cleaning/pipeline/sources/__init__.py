"""Source adapters. Adapters only fetch and preserve raw responses."""

from .copernicus_stac import ingest_sentinel2_stac
from .nasa_power import ingest_nasa_power
from .open_meteo import ingest_open_meteo_forecast
from .lake_geodata import probe_lake_geodata_sources, summarize_lake_geodata_html
from .water_station import ingest_water_station_endpoint, normalize_water_station_file, normalize_water_station_rows, probe_water_station_auth, run_water_station_parse
from .zenodo import download_thqbca_archive, extract_thqbca_workbooks, ingest_thqbca_metadata, list_thqbca_archive
from .cma_files import parse_cma_bytes, parse_cma_file
from .research_center_files import parse_research_center_bytes, parse_research_center_file
from .noaa_gfs import build_gfs_filter_url, parse_gfs_grib, run_gfs
from .c3s_seasonal import apply_bias_correction, build_c3s_plan, build_c3s_request, parse_c3s_dataset, run_c3s_seasonal
from .gpm_imerg import aggregate_imerg_windows, build_imerg_access_urls, build_imerg_filename, parse_imerg_hdf5, run_gpm_imerg
from .copernicus_assets import build_download_plan, load_stac_scenes, run_sentinel2_asset_download, select_sentinel2_assets, s3_href_to_https
from .clms_lwq import parse_lwq_catalog, run_clms_lwq_catalog, select_latest_lwq_product
from .clms_lwq_byoc import build_clms_process_request, run_clms_lwq_byoc
from .sentinel3_olci import build_sentinel3_process_request, run_sentinel3_olci
from .tba_hydrology import parse_tba_html, run_tba_hydrology
from .mwr_hfc import inspect_mwr_hfc_html, run_mwr_hfc_probe
from .glofas import aggregate_glofas_ensemble, build_glofas_request, parse_glofas_dataset, parse_glofas_tabular, run_glofas
from .hydro_boundaries import build_hydrolakes_hydrobasins, run_hydrolakes_hydrobasins
from .static_features import build_static_features, download_static_assets, run_static_features
from .hydrology_consistency import run_hydrology_consistency

__all__ = ["ingest_sentinel2_stac", "ingest_nasa_power", "ingest_open_meteo_forecast", "probe_lake_geodata_sources", "summarize_lake_geodata_html", "ingest_water_station_endpoint", "normalize_water_station_file", "normalize_water_station_rows", "probe_water_station_auth", "run_water_station_parse", "ingest_thqbca_metadata", "download_thqbca_archive", "list_thqbca_archive", "extract_thqbca_workbooks", "parse_cma_bytes", "parse_cma_file", "parse_research_center_bytes", "parse_research_center_file", "build_gfs_filter_url", "parse_gfs_grib", "run_gfs", "apply_bias_correction", "build_c3s_plan", "build_c3s_request", "parse_c3s_dataset", "run_c3s_seasonal", "aggregate_imerg_windows", "build_imerg_access_urls", "build_imerg_filename", "parse_imerg_hdf5", "run_gpm_imerg", "build_download_plan", "load_stac_scenes", "run_sentinel2_asset_download", "select_sentinel2_assets", "s3_href_to_https", "parse_lwq_catalog", "run_clms_lwq_catalog", "select_latest_lwq_product", "build_clms_process_request", "run_clms_lwq_byoc", "build_sentinel3_process_request", "run_sentinel3_olci", "parse_tba_html", "run_tba_hydrology", "inspect_mwr_hfc_html", "run_mwr_hfc_probe", "aggregate_glofas_ensemble", "build_glofas_request", "parse_glofas_dataset", "parse_glofas_tabular", "run_glofas", "build_hydrolakes_hydrobasins", "run_hydrolakes_hydrobasins", "build_static_features", "download_static_assets", "run_static_features", "run_hydrology_consistency"]
