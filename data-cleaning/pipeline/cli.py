from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .clean import run_cleaning
from .fault_injection import run_fault_injection
from .resample import run_resampling
from .align import run_alignment, run_spatial_alignment
from .imputation_validation import DEFAULT_INPUT as IMPUTATION_VALIDATION_DEFAULT_INPUT, DEFAULT_OUTPUT as IMPUTATION_VALIDATION_DEFAULT_OUTPUT, DEFAULT_SUMMARY as IMPUTATION_VALIDATION_DEFAULT_SUMMARY, DEFAULT_DATABASE as IMPUTATION_VALIDATION_DEFAULT_DATABASE, run_imputation_validation
from .features import run_daily_direct_features, run_feature_engineering, run_lag_rolling_features, run_mechanistic_features, run_reliability_features
from .remote import run_remote_calibration, run_remote_index, run_remote_pair
from .experiment import run_split
from .modeling import train_experiment
from .forecast_labels import run_horizon_labels
from .horizon_datasets import HORIZON_SPECS, run_horizon_dataset_gate
from .coverage import run_coverage
from .station_validate import run_station_validation
from .waterstation_batch import run_water_station_batch
from .waterstation_batch_dir import run_water_station_batch_directory
from .waterstation_preflight import run_water_station_preflight
from .waterstation_issue_report import DEFAULT_REPORT as WATERSTATION_ISSUE_REPORT, DEFAULT_SUMMARY as WATERSTATION_ISSUE_SUMMARY, run_water_station_issue_report
from .quality_report import run_quality_report
from .batch import run_data_cleaning_batch
from .sources import download_thqbca_archive, extract_thqbca_workbooks, ingest_nasa_power, ingest_open_meteo_forecast, ingest_sentinel2_stac, ingest_thqbca_metadata, ingest_water_station_endpoint, list_thqbca_archive, probe_lake_geodata_sources, run_water_station_parse
from .sources.water_station import probe_water_station_auth
from .sources.thqbca_data import parse_thqbca_workbooks
from .sources.nasa_power_history import ingest_nasa_power_history
from .sources.era5_land import DEFAULT_VARIABLES, run_era5_land
from .sources.cma_files import parse_cma_file
from .sources.research_center_files import parse_research_center_file
from .sources.ecmwf_open_data import DEFAULT_BBOX as ECMWF_DEFAULT_BBOX, DEFAULT_PARAMS as ECMWF_DEFAULT_PARAMS, run_ecmwf_open_data
from .forecast_assembly import assemble_forecast_values
from .sources.noaa_gfs import DEFAULT_BBOX as GFS_DEFAULT_BBOX, DEFAULT_VARIABLES as GFS_DEFAULT_VARIABLES, run_gfs
from .sources.c3s_seasonal import DEFAULT_BBOX as C3S_DEFAULT_BBOX, DEFAULT_HINDCAST_YEARS as C3S_DEFAULT_HINDCAST_YEARS, DEFAULT_LEAD_MONTHS as C3S_DEFAULT_LEAD_MONTHS, DEFAULT_VARIABLES as C3S_DEFAULT_VARIABLES, run_c3s_seasonal
from .sources.gpm_imerg import DEFAULT_BBOX as IMERG_DEFAULT_BBOX, run_gpm_imerg
from .sources.copernicus_assets import TARGET_ASSETS as SENTINEL2_TARGET_ASSETS, run_sentinel2_asset_download
from .sources.clms_lwq import run_clms_lwq_catalog
from .sources.clms_lwq_byoc import run_clms_lwq_byoc
from .sources.sentinel3_olci import DEFAULT_BBOX as OLCI_DEFAULT_BBOX, run_sentinel3_olci
from .sources.tba_hydrology import run_tba_hydrology
from .sources.mwr_hfc import run_mwr_hfc_probe
from .sources.glofas import DEFAULT_AREA as GLOFAS_DEFAULT_AREA, DEFAULT_LEAD_HOURS as GLOFAS_DEFAULT_LEAD_HOURS, run_glofas
from .sources.hydro_boundaries import DEFAULT_HYDROBASINS_ARCHIVE, DEFAULT_LAKE_BOUNDARY, DEFAULT_OUTPUT_GPKG, DEFAULT_TOPOLOGY_CSV, run_hydrolakes_hydrobasins
from .sources.static_features import DEFAULT_BOUNDARY_PACKAGE, DEFAULT_MANIFEST as STATIC_FEATURES_DEFAULT_MANIFEST, DEFAULT_OUTPUT_DEM, DEFAULT_OUTPUT_PARQUET, DEFAULT_OUTPUT_SLOPE, DEFAULT_OUTPUT_WORLDCOVER, DEFAULT_RAW_ROOT as STATIC_FEATURES_DEFAULT_RAW_ROOT, run_static_features
from .sources.hydrology_consistency import DEFAULT_GLOFAS_MANIFEST, DEFAULT_INPUT as HYDROLOGY_DEFAULT_INPUT, DEFAULT_MANIFEST as HYDROLOGY_DEFAULT_MANIFEST, DEFAULT_MWR_MANIFEST, DEFAULT_OUTPUT_CSV as HYDROLOGY_DEFAULT_OUTPUT, DEFAULT_REPORT as HYDROLOGY_DEFAULT_REPORT, DEFAULT_TBA_MANIFEST, run_hydrology_consistency
from .waterstation_delivery import DEFAULT_INBOX as WATERSTATION_DEFAULT_INBOX, DEFAULT_INVENTORY as WATERSTATION_DEFAULT_INVENTORY, DEFAULT_MANIFEST as WATERSTATION_DEFAULT_MANIFEST, run_waterstation_delivery
from .file_quarantine import DEFAULT_INPUT_ROOT as FILE_QUARANTINE_DEFAULT_INPUT_ROOT, DEFAULT_MANIFEST as FILE_QUARANTINE_DEFAULT_MANIFEST, DEFAULT_REPORT as FILE_QUARANTINE_DEFAULT_REPORT, run_file_quarantine
from .forecast_failover import run_forecast_failover
from .thqbca_revalidation import revalidate_thqbca
from .response_contract import contract_response


def main() -> int:
    parser = argparse.ArgumentParser(description="A23 Taihu raw-source ingestion")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="fetch and preserve raw source responses")
    ingest.add_argument("--source", choices=["sentinel2", "nasa_power", "open_meteo", "thqbca", "all"], default="all")
    ingest.add_argument("--start", default="2025-06-01")
    ingest.add_argument("--end", default="2025-06-30")
    ingest.add_argument("--longitude", type=float, default=120.30)
    ingest.add_argument("--latitude", type=float, default=31.20)
    ingest.add_argument("--forecast-days", type=int, default=7, help="Open-Meteo forecast horizon (1-16 days)")
    s2_assets = sub.add_parser("sentinel2-assets", help="plan/download bounded Sentinel-2 bands for one STAC scene")
    s2_assets.add_argument("--stac-input", required=True, help="raw STAC response envelope or FeatureCollection JSON")
    s2_assets.add_argument("--scene-id", default=None)
    s2_assets.add_argument("--output-root", default=None)
    s2_assets.add_argument("--manifest", default=None)
    s2_assets.add_argument("--bands", nargs="+", default=list(SENTINEL2_TARGET_ASSETS))
    s2_assets.add_argument("--no-prefer-cog", action="store_true")
    clms = sub.add_parser("clms-lwq", help="fetch and select the latest CLMS Lake Water Quality catalogue product")
    clms.add_argument("--product", default="lwq-nrt_global_300m_10daily_v2")
    clms.add_argument("--variant", choices=["cog", "nc"], default="cog")
    clms.add_argument("--as-of", default=None, help="UTC ISO-8601 reference time for historical replay")
    clms.add_argument("--output-root", default=None)
    clms.add_argument("--manifest", default=None)
    clms_crop = sub.add_parser("clms-lwq-byoc", help="request a bounded Taihu CLMS LWQ BYOC raster")
    clms_crop.add_argument("--selected-product", default=None, help="selected CLMS catalogue JSON")
    clms_crop.add_argument("--start", default=None)
    clms_crop.add_argument("--end", default=None)
    clms_crop.add_argument("--bbox", nargs=4, type=float, default=[119.90, 30.90, 120.75, 31.65], metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    clms_crop.add_argument("--width", type=int, default=320)
    clms_crop.add_argument("--height", type=int, default=320)
    clms_crop.add_argument("--output", default=None)
    clms_crop.add_argument("--manifest", default=None)
    olci = sub.add_parser("sentinel3-olci", help="request a bounded Taihu Sentinel-3 OLCI L2 raster")
    olci.add_argument("--start", required=True, help="UTC ISO-8601 start time")
    olci.add_argument("--end", required=True, help="UTC ISO-8601 end time")
    olci.add_argument("--bbox", nargs=4, type=float, default=list(OLCI_DEFAULT_BBOX), metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    olci.add_argument("--max-cloud-coverage", type=float, default=80.0)
    olci.add_argument("--mosaicking-order", choices=["mostRecent", "leastRecent", "leastCC"], default="mostRecent")
    olci.add_argument("--upsampling", choices=["NEAREST", "BILINEAR", "BICUBIC"], default="BILINEAR")
    olci.add_argument("--width", type=int, default=320)
    olci.add_argument("--height", type=int, default=320)
    olci.add_argument("--output", default=None)
    olci.add_argument("--manifest", default=None)
    tba = sub.add_parser("tba-hydrology", help="parse a legally saved Taihu Basin Authority water-level HTML page")
    tba.add_argument("--input", default=None, help="legally saved TBA HTML; omitted means policy-blocked and does not fetch")
    tba.add_argument("--output", default=None, help="normalized water-level CSV")
    tba.add_argument("--manifest", default=None)
    tba.add_argument("--expected-dom-fingerprint", default=None)
    tba.add_argument("--source-timezone", default="Asia/Shanghai")
    tba.add_argument("--source-url", default="https://www.tba.gov.cn/")
    tba.add_argument("--allow-public-snapshot", action="store_true", help="only with explicit authorization evidence")
    tba.add_argument("--authorization-evidence", default=None)
    mwr = sub.add_parser("mwr-hfc-probe", help="verify MWR HFC entry boundary or parse a legally exported file")
    mwr.add_argument("--input", default=None, help="authorized CSV/JSON/XLSX export; omitted means policy-blocked and does not fetch")
    mwr.add_argument("--output", default=None, help="normalized water/rain observation CSV")
    mwr.add_argument("--manifest", default=None)
    mwr.add_argument("--source-timezone", default="Asia/Shanghai")
    mwr.add_argument("--source-url", default="https://hfc.mwr.cn/")
    mwr.add_argument("--allow-public-snapshot", action="store_true", help="only with explicit authorization evidence")
    mwr.add_argument("--authorization-evidence", default=None)
    glofas = sub.add_parser("glofas", help="build the official GloFAS request plan or parse an authorized proxy export")
    glofas.add_argument("--run-date", required=True, help="UTC forecast reference date/time")
    glofas.add_argument("--input", default=None, help="authorized NetCDF/GRIB/CSV/JSON export; omitted means auth-blocked plan only")
    glofas.add_argument("--area", nargs=4, type=float, default=list(GLOFAS_DEFAULT_AREA), metavar=("NORTH", "WEST", "SOUTH", "EAST"))
    glofas.add_argument("--lead-hours", nargs="+", type=int, default=list(GLOFAS_DEFAULT_LEAD_HOURS))
    glofas.add_argument("--output-root", default=None)
    glofas.add_argument("--manifest", default=None)
    glofas.add_argument("--authorization-evidence", default=None)
    hydro = sub.add_parser("hydro-boundaries", help="build the Taihu HydroLAKES/HydroBASINS GeoPackage and topology index")
    hydro.add_argument("--lake-boundary", default=str(DEFAULT_LAKE_BOUNDARY))
    hydro.add_argument("--hydrobasins", default=None, help="official HydroBASINS Asia archive or extracted shapefile")
    hydro.add_argument("--output-gpkg", default=str(DEFAULT_OUTPUT_GPKG))
    hydro.add_argument("--topology-csv", default=str(DEFAULT_TOPOLOGY_CSV))
    hydro.add_argument("--manifest", default=None)
    hydro.add_argument("--buffer-deg", type=float, default=0.5)
    static = sub.add_parser("static-features", help="download public DEM/WorldCover tiles and derive Taihu static features")
    static.add_argument("--boundary-package", default=str(DEFAULT_BOUNDARY_PACKAGE))
    static.add_argument("--raw-root", default=str(STATIC_FEATURES_DEFAULT_RAW_ROOT))
    static.add_argument("--output-parquet", default=str(DEFAULT_OUTPUT_PARQUET))
    static.add_argument("--output-dem", default=str(DEFAULT_OUTPUT_DEM))
    static.add_argument("--output-slope", default=str(DEFAULT_OUTPUT_SLOPE))
    static.add_argument("--output-worldcover", default=str(DEFAULT_OUTPUT_WORLDCOVER))
    static.add_argument("--manifest", default=str(STATIC_FEATURES_DEFAULT_MANIFEST))
    static.add_argument("--buffer-deg", type=float, default=0.5)
    static.add_argument("--no-download", action="store_true", help="only use already downloaded public tiles")
    hydro_check = sub.add_parser("hydrology-consistency", help="check hydrology jumps, units, flow signs, datum status and rainfall lags")
    hydro_check.add_argument("--input", nargs="+", default=[str(HYDROLOGY_DEFAULT_INPUT)])
    hydro_check.add_argument("--output-csv", default=str(HYDROLOGY_DEFAULT_OUTPUT))
    hydro_check.add_argument("--report", default=str(HYDROLOGY_DEFAULT_REPORT))
    hydro_check.add_argument("--manifest", default=str(HYDROLOGY_DEFAULT_MANIFEST))
    hydro_check.add_argument("--tba-manifest", default=str(DEFAULT_TBA_MANIFEST))
    hydro_check.add_argument("--mwr-manifest", default=str(DEFAULT_MWR_MANIFEST))
    hydro_check.add_argument("--glofas-manifest", default=str(DEFAULT_GLOFAS_MANIFEST))
    hydro_check.add_argument("--jump-threshold-m-per-day", type=float, default=0.3)
    hydro_check.add_argument("--max-lag-days", type=int, default=30)
    delivery = sub.add_parser("waterstation-delivery", help="isolate an authorized water-station/buoy delivery and record checksums")
    delivery.add_argument("--inbox-root", default=str(WATERSTATION_DEFAULT_INBOX))
    delivery.add_argument("--inventory", default=str(WATERSTATION_DEFAULT_INVENTORY))
    delivery.add_argument("--manifest", default=str(WATERSTATION_DEFAULT_MANIFEST))
    delivery.add_argument("--delivery-id", default=None)
    clean = sub.add_parser("clean", help="normalize raw JSON, run QC, export CSV and SQLite")
    clean.add_argument("--raw-root", default=None)
    batch = sub.add_parser("run-batch", help="run an isolated batch through the selected data-cleaning stage")
    batch.add_argument("--raw-root", default=None)
    batch.add_argument("--runs-root", default=None)
    batch.add_argument("--run-id", default=None)
    batch.add_argument("--as-of", default=None)
    batch.add_argument("--through", choices=["quality", "resample", "align", "features", "coverage", "labels", "split", "gate", "remediation"], default="quality")
    batch.add_argument("--target-variable", default="phytoplankton_biomass")
    batch.add_argument("--split-strategy", choices=["time", "group"], default="time")
    batch.add_argument("--train-fraction", type=float, default=0.7)
    batch.add_argument("--validation-fraction", type=float, default=0.15)
    sub.add_parser("fault-test", help="run labelled missing/outlier/duplicate/timestamp QC fixture")
    download = sub.add_parser("download-thqbca", help="resume THQBCA archive download and verify MD5")
    download.add_argument("--output", default="storage/raw/taihu_thqbca_zenodo/THQBCA-V2.rar")
    download.add_argument("--md5", default="9fb11bd2ecb80470abfd33d54bdc9fa3")
    listing = sub.add_parser("list-thqbca", help="list THQBCA archive members without extraction")
    listing.add_argument("--archive", default="storage/raw/taihu_thqbca_zenodo/THQBCA-V2.rar")
    listing.add_argument("--manifest", default="storage/manifests/thqbca_archive_listing.json")
    extract = sub.add_parser("extract-thqbca", help="extract only the water-quality and climate workbooks")
    extract.add_argument("--archive", default="storage/raw/taihu_thqbca_zenodo/THQBCA-V2.rar")
    extract.add_argument("--output-root", default="storage/raw/taihu_thqbca_zenodo/extracted")
    parse = sub.add_parser("parse-thqbca", help="parse extracted THQBCA water-quality and climate workbooks")
    parse.add_argument("--water-quality", default="storage/raw/taihu_thqbca_zenodo/extracted/THQBCA-V2/1.WaterQuality/1WaterQuality.xlsx")
    parse.add_argument("--climate", default="storage/raw/taihu_thqbca_zenodo/extracted/THQBCA-V2/3.Climate/3.Climate.xlsx")
    parse.add_argument("--output", default="storage/raw/taihu_thqbca_parsed/thqbca_observations.csv")
    parse.add_argument("--manifest", default="storage/manifests/thqbca_parse.json")
    parse.add_argument("--remote-listing", default="storage/manifests/thqbca_archive_listing.json")
    parse.add_argument("--remote-index-output", default="storage/raw/taihu_thqbca_parsed/thqbca_remote_product_index.csv")
    parse.add_argument("--remote-index-manifest", default="storage/manifests/thqbca_remote_product_index.json")
    nasa_history = sub.add_parser("nasa-power-history", help="download NASA POWER history in year chunks")
    nasa_history.add_argument("--start-year", type=int, default=2005)
    nasa_history.add_argument("--end-year", type=int, default=2020)
    nasa_history.add_argument("--longitude", type=float, default=120.30)
    nasa_history.add_argument("--latitude", type=float, default=31.20)
    nasa_history.add_argument("--raw-root", default=None)
    nasa_history.add_argument("--output-root", default=None)
    nasa_history.add_argument("--manifest", default=None)
    era5 = sub.add_parser("era5-land", help="download and parse ERA5-Land year chunks")
    era5.add_argument("--start-year", type=int, default=2005)
    era5.add_argument("--end-year", type=int, default=2020)
    era5.add_argument("--bbox", nargs=4, type=float, default=[119.90, 30.90, 120.75, 31.65], metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    era5.add_argument("--variables", nargs="+", default=list(DEFAULT_VARIABLES))
    era5.add_argument("--raw-root", default=None)
    era5.add_argument("--silver-root", default=None)
    era5.add_argument("--manifest", default=None)
    cma = sub.add_parser("cma-file", help="parse a legally downloaded CMA CSV/TXT/ZIP file")
    cma.add_argument("--input", required=True)
    cma.add_argument("--output", required=True)
    cma.add_argument("--source-id", default="cma_history_file")
    cma.add_argument("--source-timezone", default="Asia/Shanghai")
    cma.add_argument("--manifest", default=None)
    research = sub.add_parser("research-center-file", help="parse a legally downloaded national data-centre file")
    research.add_argument("--input", required=True)
    research.add_argument("--output", required=True)
    research.add_argument("--metadata", default=None, help="JSON metadata/authorization record")
    research.add_argument("--manifest", required=True)
    research.add_argument("--source-id", default="research_center_file")
    ecmwf = sub.add_parser("ecmwf-open-data", help="download and parse a bounded ECMWF Open Data forecast run")
    ecmwf.add_argument("--run-date", required=True, help="UTC run date YYYY-MM-DD")
    ecmwf.add_argument("--cycle", type=int, choices=[0, 6, 12, 18], required=True)
    ecmwf.add_argument("--steps", nargs="+", type=int, default=list(range(0, 73, 3)))
    ecmwf.add_argument("--bbox", nargs=4, type=float, default=list(ECMWF_DEFAULT_BBOX), metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    ecmwf.add_argument("--parameters", nargs="+", default=list(ECMWF_DEFAULT_PARAMS))
    ecmwf.add_argument("--raw-root", default=None)
    ecmwf.add_argument("--silver-root", default=None)
    ecmwf.add_argument("--manifest", default=None)
    forecast_assemble = sub.add_parser("forecast-assemble", help="assemble ECMWF forecast_values and local-day summaries")
    forecast_assemble.add_argument("--input", required=True, help="ECMWF area-mean forecast CSV")
    forecast_assemble.add_argument("--output-root", default=None)
    forecast_assemble.add_argument("--database", default=None)
    gfs = sub.add_parser("noaa-gfs", help="download and parse a bounded NOAA GFS NOMADS run")
    gfs.add_argument("--run-date", required=True, help="UTC run date YYYY-MM-DD")
    gfs.add_argument("--cycle", type=int, choices=[0, 6, 12, 18], required=True)
    gfs.add_argument("--steps", nargs="+", type=int, default=list(range(0, 73, 6)))
    gfs.add_argument("--bbox", nargs=4, type=float, default=list(GFS_DEFAULT_BBOX), metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    gfs.add_argument("--variables", nargs="+", default=list(GFS_DEFAULT_VARIABLES))
    gfs.add_argument("--raw-root", default=None)
    gfs.add_argument("--silver-root", default=None)
    gfs.add_argument("--manifest", default=None)
    c3s = sub.add_parser("c3s-seasonal", help="download and parse paired C3S seasonal hindcast/forecast data")
    c3s.add_argument("--forecast-year", type=int, required=True)
    c3s.add_argument("--init-month", type=int, required=True, choices=range(1, 13))
    c3s.add_argument("--hindcast-years", nargs="+", type=int, default=list(C3S_DEFAULT_HINDCAST_YEARS))
    c3s.add_argument("--lead-months", nargs="+", type=int, default=list(C3S_DEFAULT_LEAD_MONTHS))
    c3s.add_argument("--bbox", nargs=4, type=float, default=list(C3S_DEFAULT_BBOX), metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    c3s.add_argument("--variables", nargs="+", default=list(C3S_DEFAULT_VARIABLES))
    c3s.add_argument("--originating-centre", default="ecmwf")
    c3s.add_argument("--system", default="51")
    c3s.add_argument("--raw-root", default=None)
    c3s.add_argument("--silver-root", default=None)
    c3s.add_argument("--manifest", default=None)
    imerg = sub.add_parser("gpm-imerg", help="download and parse bounded NASA GPM IMERG half-hourly granules")
    imerg.add_argument("--start-time", required=True, help="UTC ISO-8601 time aligned to :00 or :30")
    imerg.add_argument("--end-time", required=True, help="UTC ISO-8601 time aligned to :00 or :30")
    imerg.add_argument("--run", choices=["early", "late", "final"], default="early")
    imerg.add_argument("--version", default="07")
    imerg.add_argument("--bbox", nargs=4, type=float, default=list(IMERG_DEFAULT_BBOX), metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    imerg.add_argument("--raw-root", default=None)
    imerg.add_argument("--silver-root", default=None)
    imerg.add_argument("--manifest", default=None)
    failover = sub.add_parser("forecast-failover", help="select ECMWF/GFS/Open-Meteo forecast source with health logging")
    failover.add_argument("--ecmwf", default=None, help="ECMWF forecast_values CSV")
    failover.add_argument("--gfs", default=None, help="NOAA GFS area-mean CSV")
    failover.add_argument("--open-meteo", default=None, help="Open-Meteo normalized forecast CSV (development only)")
    failover.add_argument("--priority-config", default=None)
    failover.add_argument("--environment", choices=["production", "development"], default="production")
    failover.add_argument("--required-horizon-hours", type=float, default=72.0)
    failover.add_argument("--output", default=None)
    failover.add_argument("--health-database", default=None)
    failover.add_argument("--manifest", default=None)
    failover.add_argument("--run-id", default="forecast-failover")
    failover.add_argument("--checked-at-utc", default=None)
    revalidate = sub.add_parser("revalidate-thqbca", help="revalidate THQBCA archive, members and parsed rows")
    revalidate.add_argument("--archive", default="storage/raw/taihu_thqbca_zenodo/THQBCA-V2.rar")
    revalidate.add_argument("--download-manifest", default="storage/manifests/thqbca_download_20260818T100147Z.json")
    revalidate.add_argument("--listing-manifest", default="storage/manifests/thqbca_archive_listing.json")
    revalidate.add_argument("--parse-manifest", default="storage/manifests/thqbca_parse.json")
    revalidate.add_argument("--parsed-csv", default="storage/raw/taihu_thqbca_parsed/thqbca_observations.csv")
    revalidate.add_argument("--output", default="storage/manifests/thqbca_revalidation.json")
    resample = sub.add_parser("resample", help="resample hourly/daily records without upsampling low-frequency sources")
    resample.add_argument("--input", required=True, help="cleaned_observations.csv or another standard observation CSV")
    resample.add_argument("--output-root", default=None)
    resample.add_argument("--database", default=None)
    resample.add_argument("--frequency", choices=["auto", "hourly", "daily", "decadal", "monthly"], default="auto", help="target frequency; never upsamples a coarser native source")
    align = sub.add_parser("align", help="align target and driver series with auditable time/space gaps")
    align.add_argument("--input", required=True, help="resampled_observations.csv")
    align.add_argument("--output-root", default=None)
    align.add_argument("--database", default=None)
    align.add_argument("--max-time-diff-hours", type=float, default=24.0)
    align.add_argument("--ideal-ground-remote-hours", type=float, default=3.0)
    align.add_argument("--matching-strategy", choices=["nearest"], default="nearest")
    align.add_argument("--max-space-m", type=float, default=50000.0)
    spatial_align = sub.add_parser("spatial-align", help="station buffers, 300 m grid aggregation and lake-area statistics")
    spatial_align.add_argument("--input", required=True, help="resampled_observations.csv")
    spatial_align.add_argument("--output-root", default=None)
    spatial_align.add_argument("--database", default=None)
    spatial_align.add_argument("--boundary", default="storage/silver/geo/taihu_boundary.gpkg")
    spatial_align.add_argument("--grid-size-m", type=float, default=300.0)
    spatial_align.add_argument("--station-buffer-pixels", nargs="+", type=int, default=[1, 2, 3])
    spatial_align.add_argument("--grid-origin", nargs=2, type=float, default=[119.90, 30.90], metavar=("LONGITUDE", "LATITUDE"))
    spatial_align.add_argument("--manifest", default=None)
    imputation_validation = sub.add_parser("imputation-validation", help="masked 5/10/20 percent validation of imputation methods")
    imputation_validation.add_argument("--input", default=str(IMPUTATION_VALIDATION_DEFAULT_INPUT))
    imputation_validation.add_argument("--output", default=str(IMPUTATION_VALIDATION_DEFAULT_OUTPUT))
    imputation_validation.add_argument("--summary", default=str(IMPUTATION_VALIDATION_DEFAULT_SUMMARY))
    imputation_validation.add_argument("--database", default=str(IMPUTATION_VALIDATION_DEFAULT_DATABASE))
    imputation_validation.add_argument("--mask-rates", nargs="+", type=float, default=[0.05, 0.10, 0.20])
    imputation_validation.add_argument("--seed", type=int, default=20260819)
    imputation_validation.add_argument("--min-series-length", type=int, default=10)
    features = sub.add_parser("features", help="build causal lag, rolling, nutrient and weather features")
    features.add_argument("--alignment", required=True, help="temporal_alignments.csv")
    features.add_argument("--observations", required=True, help="resampled_observations.csv")
    features.add_argument("--output-root", default=None)
    features.add_argument("--database", default=None)
    daily_features = sub.add_parser("daily-features", help="build lake-day direct features with category lineage")
    daily_features.add_argument("--observations", required=True, help="daily resampled observations CSV")
    daily_features.add_argument("--output-root", required=True)
    daily_features.add_argument("--database", required=True)
    daily_features.add_argument("--static-features", default="storage/silver/geo/static_features.parquet")
    daily_features.add_argument("--manifest", default=None)
    lag_features = sub.add_parser("lag-rolling-features", help="build causal 1/3/7/14/30/90-day lag and rolling features")
    lag_features.add_argument("--input", required=True)
    lag_features.add_argument("--output-root", required=True)
    lag_features.add_argument("--database", required=True)
    lag_features.add_argument("--manifest", default=None)
    mechanism_features = sub.add_parser("mechanistic-features", help="build transparent temperature/nutrient/light/wind/hydrology/phenology features")
    mechanism_features.add_argument("--input", required=True)
    mechanism_features.add_argument("--output-root", required=True)
    mechanism_features.add_argument("--database", required=True)
    mechanism_features.add_argument("--manifest", default=None)
    reliability_features = sub.add_parser("reliability-features", help="build data-age/source/proxy/coverage/uncertainty metadata")
    reliability_features.add_argument("--input", required=True)
    reliability_features.add_argument("--output-root", required=True)
    reliability_features.add_argument("--database", required=True)
    reliability_features.add_argument("--manifest", default=None)
    horizon_gate = sub.add_parser("horizon-dataset-gate", help="emit a trainability audit and feature-only candidate without fabricating targets")
    horizon_gate.add_argument("--input", required=True)
    horizon_gate.add_argument("--output-root", required=True)
    horizon_gate.add_argument("--horizon", choices=sorted(HORIZON_SPECS), required=True)
    horizon_gate.add_argument("--seasonal-ready", action="store_true")
    remote_index = sub.add_parser("remote-index", help="calculate Sentinel-2 indices and scene summaries from local pixels")
    remote_index.add_argument("--input", required=True, help="local Sentinel-2 pixel CSV/JSON")
    remote_index.add_argument("--output-root", default=None)
    remote_index.add_argument("--database", default=None)
    remote_index.add_argument("--reflectance-scale", type=float, default=1.0, help="explicit multiplier; e.g. 0.0001 for uint16/10000 products")
    remote_index.add_argument("--cloud-threshold", type=float, default=40.0)
    remote_index.add_argument("--ndwi-water-threshold", type=float, default=0.0)
    remote_index.add_argument("--fai-threshold", type=float, default=0.0)
    remote_index.add_argument("--pixel-area-km2", type=float, default=None)
    remote_pair = sub.add_parser("remote-pair", help="pair remote scene summaries with ground chlorophyll observations")
    remote_pair.add_argument("--remote", required=True, help="remote_scene_summary.csv")
    remote_pair.add_argument("--ground", required=True, help="ground CSV with observed_at, coordinates and chlorophyll_a")
    remote_pair.add_argument("--output-root", default=None)
    remote_pair.add_argument("--database", default=None)
    remote_pair.add_argument("--max-time-diff-hours", type=float, default=12.0)
    remote_pair.add_argument("--max-space-m", type=float, default=5000.0)
    remote_cal = sub.add_parser("remote-calibrate", help="fit temporal-holdout chlorophyll calibration from paired samples")
    remote_cal.add_argument("--pairs", required=True, help="remote_ground_pairs.csv")
    remote_cal.add_argument("--features", default="mean_fai,mean_mci,mean_ndwi")
    remote_cal.add_argument("--min-pairs", type=int, default=10)
    remote_cal.add_argument("--output-root", default=None)
    remote_cal.add_argument("--database", default=None)
    split = sub.add_parser("split", help="split feature data into leakage-audited train/validation/test sets")
    split.add_argument("--input", required=True, help="feature_dataset.csv")
    split.add_argument("--strategy", choices=["time", "group"], default="time")
    split.add_argument("--train-fraction", type=float, default=0.7)
    split.add_argument("--validation-fraction", type=float, default=0.15)
    split.add_argument("--time-granularity", choices=["day", "month", "year"], default="day")
    split.add_argument("--group-field", default="target_station_id")
    split.add_argument("--validation-groups", default="")
    split.add_argument("--test-groups", default="")
    split.add_argument("--output-root", default=None)
    split.add_argument("--database", default=None)
    train = sub.add_parser("train", help="train leakage-audited AI and mechanism-fusion experiments")
    train.add_argument("--input-dir", required=True, help="experiment split directory containing train/validation/test CSVs")
    train.add_argument("--target-variable", default="phytoplankton_biomass")
    train.add_argument("--algorithm", choices=["random_forest", "hist_gradient_boosting"], default="random_forest")
    train.add_argument("--fusion", choices=["none", "mechanistic_cascade", "mechanistic_residual"], default="mechanistic_cascade")
    train.add_argument("--random-state", type=int, default=42)
    train.add_argument("--output-root", default=None)
    train.add_argument("--database", default=None)
    labels = sub.add_parser("horizon-labels", help="construct leakage-audited 1-3d/7-15d/30-90d future labels")
    labels.add_argument("--input", required=True, help="experiment_dataset.csv or another target feature CSV")
    labels.add_argument("--target-variable", default="phytoplankton_biomass")
    labels.add_argument("--output-root", default=None)
    labels.add_argument("--database", default=None)
    coverage = sub.add_parser("coverage", help="audit high-frequency source coverage and short-term forecast gaps")
    coverage.add_argument("--input", required=True, help="standard/resampled observation CSV")
    coverage.add_argument("--as-of", default=None, help="optional ISO-8601 reference time for staleness calculation")
    coverage.add_argument("--output-root", default=None)
    coverage.add_argument("--database", default=None)
    station_fetch = sub.add_parser("waterstation-fetch", help="fetch a user-supplied water-station JSON endpoint and preserve raw response")
    station_fetch.add_argument("--url", required=True)
    station_fetch.add_argument("--source-id", default="water_station_endpoint")
    station_auth_probe = sub.add_parser("waterstation-auth-probe", help="check HJ1404 endpoint/token readiness without making a request")
    station_auth_probe.add_argument("--url", default=None, help="formal authorized HJ1404 endpoint; omitted for token-only probe")
    station_auth_probe.add_argument("--manifest", default="storage/manifests/hj1404_auth_probe.json")
    station_parse = sub.add_parser("waterstation-parse", help="normalize an MEE-compatible water-station JSON/CSV/XLSX file")
    station_parse.add_argument("--input", required=True)
    station_parse.add_argument("--output", required=True)
    station_parse.add_argument("--source-id", default=None)
    station_validate = sub.add_parser("waterstation-validate", help="quality-gate standardized water-station observations before modelling")
    station_validate.add_argument("--input", required=True, help="cleaned or standardized water-station CSV")
    station_validate.add_argument("--max-median-interval-hours", type=float, default=6.0)
    station_validate.add_argument("--max-gap-hours", type=float, default=24.0)
    station_validate.add_argument("--output-root", default=None)
    station_validate.add_argument("--database", default=None)
    station_batch = sub.add_parser("waterstation-batch", help="parse, clean and P0-validate one authorized station export")
    station_batch.add_argument("--input", required=True, help="user-supplied JSON/CSV/TSV/XLSX station export or fetched raw envelope")
    station_batch.add_argument("--source-id", default="taihu_water_station_batch")
    station_batch.add_argument("--max-median-interval-hours", type=float, default=6.0)
    station_batch.add_argument("--max-gap-hours", type=float, default=24.0)
    station_batch.add_argument("--output-root", default=None)
    station_batch.add_argument("--database", default=None)
    station_batch_dir = sub.add_parser("waterstation-batch-dir", help="process many authorized station exports with hash deduplication")
    station_batch_dir.add_argument("--input-root", required=True, help="directory recursively containing JSON/CSV/TSV/XLSX station exports")
    station_batch_dir.add_argument("--source-id", default="taihu_water_station_batch")
    station_batch_dir.add_argument("--max-median-interval-hours", type=float, default=6.0)
    station_batch_dir.add_argument("--max-gap-hours", type=float, default=24.0)
    station_batch_dir.add_argument("--output-root", default=None)
    station_batch_dir.add_argument("--database", default=None)
    preflight = sub.add_parser("waterstation-preflight", help="read-only inventory and P0 validation for authorized station files")
    preflight.add_argument("--input-root", required=True, help="directory containing authorized JSON/CSV/TSV/XLSX station files")
    preflight.add_argument("--source-id", default="taihu_water_station_preflight")
    preflight.add_argument("--max-median-interval-hours", type=float, default=6.0)
    preflight.add_argument("--max-gap-hours", type=float, default=24.0)
    preflight.add_argument("--output-root", default=None)
    preflight.add_argument("--database", default=None)
    preflight_issues = sub.add_parser("waterstation-preflight-issues", help="return file/field-located issues from a water-station preflight")
    preflight_issues.add_argument("--preflight-root", required=True, help="directory containing preflight_inventory.csv, preflight_issues.csv and preflight_summary.json")
    preflight_issues.add_argument("--input-root", default=None, help="original authorized input root; used for raw schema/coordinate checks")
    preflight_issues.add_argument("--output", default=str(WATERSTATION_ISSUE_REPORT))
    preflight_issues.add_argument("--summary", default=str(WATERSTATION_ISSUE_SUMMARY))
    preflight_issues.add_argument("--manifest", default=None)
    quality = sub.add_parser("quality-report", help="summarize cleaned rows, missingness, duplicates, proxies and freshness")
    quality.add_argument("--cleaned", required=True, help="cleaned_observations.csv")
    quality.add_argument("--rejected", default=None)
    quality.add_argument("--pending", default=None)
    quality.add_argument("--issues", default=None)
    quality.add_argument("--normalized", default=None)
    quality.add_argument("--suspect", default=None)
    quality.add_argument("--pending-conflicts", default=None)
    quality.add_argument("--duplicate-audit", default=None)
    quality.add_argument("--as-of", default=None)
    quality.add_argument("--max-staleness-days", type=float, default=30.0)
    quality.add_argument("--low-frequency-hours", type=float, default=24.0)
    quality.add_argument("--output-root", default=None)
    quality.add_argument("--database", default=None)
    quarantine = sub.add_parser("file-quarantine", help="read-only file-level quarantine checks for raw assets")
    quarantine.add_argument("--input-root", default=str(FILE_QUARANTINE_DEFAULT_INPUT_ROOT))
    quarantine.add_argument("--output", default=str(FILE_QUARANTINE_DEFAULT_REPORT))
    quarantine.add_argument("--manifest", default=str(FILE_QUARANTINE_DEFAULT_MANIFEST))
    lake_probe = sub.add_parser("lake-geodata-probe", help="probe public NIGLAS/NESDC Taihu metadata pages and record access boundary")
    lake_probe.add_argument("--output-root", default=None)
    lake_probe.add_argument("--database", default=None)
    args = parser.parse_args()

    if args.command == "clean":
        result = run_cleaning(Path(args.raw_root) if args.raw_root else None)
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"completed", "completed_with_warnings"} else 1
    if args.command == "run-batch":
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
        if as_of is not None and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        result = run_data_cleaning_batch(
            Path(args.raw_root) if args.raw_root else None,
            runs_root=Path(args.runs_root) if args.runs_root else None,
            run_id=args.run_id,
            as_of=as_of,
            through=args.through,
            target_variable=args.target_variable,
            split_strategy=args.split_strategy,
            train_fraction=args.train_fraction,
            validation_fraction=args.validation_fraction,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] != "failed" else 1
    if args.command == "fault-test":
        result = run_fault_injection()
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["recall"] == 1.0 else 1
    if args.command == "sentinel2-assets":
        result = run_sentinel2_asset_download(
            Path(args.stac_input),
            scene_id=args.scene_id,
            output_root=Path(args.output_root) if args.output_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            bands=args.bands,
            prefer_cog=not args.no_prefer_cog,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_AUTH", "BLOCKED_DATA"} else 1
    if args.command == "clms-lwq":
        result = run_clms_lwq_catalog(
            product=args.product,
            variant=args.variant,
            as_of=args.as_of,
            output_root=Path(args.output_root) if args.output_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 1
    if args.command == "clms-lwq-byoc":
        result = run_clms_lwq_byoc(
            selected_product=Path(args.selected_product) if args.selected_product else None,
            start=args.start,
            end=args.end,
            bbox=tuple(args.bbox),
            output_path=Path(args.output) if args.output else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            width=args.width,
            height=args.height,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] == "BLOCKED_AUTH" else 1
    if args.command == "sentinel3-olci":
        result = run_sentinel3_olci(
            start=args.start,
            end=args.end,
            bbox=tuple(args.bbox),
            output_path=Path(args.output) if args.output else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            width=args.width,
            height=args.height,
            max_cloud_coverage=args.max_cloud_coverage,
            mosaicking_order=args.mosaicking_order,
            upsampling=args.upsampling,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] == "BLOCKED_AUTH" else 1
    if args.command == "tba-hydrology":
        result = run_tba_hydrology(
            input_path=Path(args.input) if args.input else None,
            output_csv=Path(args.output) if args.output else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            expected_dom_fingerprint=args.expected_dom_fingerprint,
            source_url=args.source_url,
            source_timezone=args.source_timezone,
            allow_public_snapshot=args.allow_public_snapshot,
            authorization_evidence_path=Path(args.authorization_evidence) if args.authorization_evidence else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_POLICY", "BLOCKED_DATA", "BLOCKED_SCHEMA_DRIFT"} else 1
    if args.command == "mwr-hfc-probe":
        result = run_mwr_hfc_probe(
            input_path=Path(args.input) if args.input else None,
            output_csv=Path(args.output) if args.output else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            source_url=args.source_url,
            source_timezone=args.source_timezone,
            allow_public_snapshot=args.allow_public_snapshot,
            authorization_evidence_path=Path(args.authorization_evidence) if args.authorization_evidence else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_POLICY", "BLOCKED_DATA"} else 1
    if args.command == "glofas":
        result = run_glofas(
            run_date=args.run_date,
            input_path=Path(args.input) if args.input else None,
            area=tuple(args.area),
            lead_hours=args.lead_hours,
            output_root=Path(args.output_root) if args.output_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            authorization_evidence_path=Path(args.authorization_evidence) if args.authorization_evidence else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_AUTH", "BLOCKED_DATA"} else 1
    if args.command == "hydro-boundaries":
        result = run_hydrolakes_hydrobasins(
            lake_boundary_path=Path(args.lake_boundary),
            hydrobasins_path=Path(args.hydrobasins) if args.hydrobasins else None,
            output_gpkg=Path(args.output_gpkg),
            topology_csv=Path(args.topology_csv),
            manifest_path=Path(args.manifest) if args.manifest else None,
            buffer_deg=args.buffer_deg,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_DATA", "BLOCKED_AUTH"} else 1
    if args.command == "static-features":
        result = run_static_features(
            boundary_package=Path(args.boundary_package),
            raw_root=Path(args.raw_root),
            output_parquet=Path(args.output_parquet),
            output_dem=Path(args.output_dem),
            output_slope=Path(args.output_slope),
            output_worldcover=Path(args.output_worldcover),
            manifest_path=Path(args.manifest),
            buffer_deg=args.buffer_deg,
            download=not args.no_download,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_DATA", "BLOCKED_AUTH"} else 1
    if args.command == "hydrology-consistency":
        result = run_hydrology_consistency(
            input_paths=[Path(item) for item in args.input],
            output_csv=Path(args.output_csv),
            report_path=Path(args.report),
            manifest_path=Path(args.manifest),
            tba_manifest=Path(args.tba_manifest),
            mwr_manifest=Path(args.mwr_manifest),
            glofas_manifest=Path(args.glofas_manifest),
            jump_threshold_m_per_day=args.jump_threshold_m_per_day,
            max_lag_days=args.max_lag_days,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] in {"BLOCKED_DATA", "BLOCKED_AUTH"} else 1
    if args.command == "waterstation-delivery":
        result = run_waterstation_delivery(
            inbox_root=Path(args.inbox_root),
            inventory_path=Path(args.inventory),
            manifest_path=Path(args.manifest),
            delivery_id=args.delivery_id,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "isolated" else 2 if result["status"] == "BLOCKED_AUTH" else 1
    if args.command == "download-thqbca":
        result = download_thqbca_archive(Path(args.output), args.md5)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest_path = Path("storage/manifests") / f"thqbca_download_{stamp}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        result["retrieved_at"] = stamp
        result["manifest"] = str(manifest_path)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["verified"] else 1
    if args.command == "list-thqbca":
        result = list_thqbca_archive(Path(args.archive), Path(args.manifest))
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "extract-thqbca":
        result = extract_thqbca_workbooks(Path(args.archive), Path(args.output_root))
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "parse-thqbca":
        result = parse_thqbca_workbooks(
            Path(args.water_quality), Path(args.climate), Path(args.output), Path(args.manifest),
            Path(args.remote_listing), Path(args.remote_index_output), Path(args.remote_index_manifest),
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "nasa-power-history":
        result = ingest_nasa_power_history(
            args.start_year, args.end_year, args.longitude, args.latitude,
            raw_root=Path(args.raw_root) if args.raw_root else None,
            output_root=Path(args.output_root) if args.output_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 1
    if args.command == "era5-land":
        result = run_era5_land(
            args.start_year, args.end_year, tuple(args.bbox), args.variables,
            raw_root=Path(args.raw_root) if args.raw_root else None,
            silver_root=Path(args.silver_root) if args.silver_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2 if result["status"] == "BLOCKED_AUTH" else 1
    if args.command == "cma-file":
        result = parse_cma_file(
            Path(args.input), Path(args.output), source_id=args.source_id, source_timezone=args.source_timezone,
        )
        if args.manifest:
            manifest = Path(args.manifest)
        else:
            manifest = Path("storage/manifests") / "cma_history_file.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["manifest"] = str(manifest)
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "research-center-file":
        result = parse_research_center_file(
            Path(args.input), Path(args.output), metadata=Path(args.metadata) if args.metadata else None,
            manifest_path=Path(args.manifest), source_id=args.source_id,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    if args.command == "ecmwf-open-data":
        result = run_ecmwf_open_data(
            args.run_date, args.cycle, steps=args.steps, bbox=tuple(args.bbox), parameters=args.parameters,
            raw_root=Path(args.raw_root) if args.raw_root else None,
            silver_root=Path(args.silver_root) if args.silver_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("real_batch") else 2
    if args.command == "forecast-assemble":
        result = assemble_forecast_values(
            Path(args.input), Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 1
    if args.command == "noaa-gfs":
        result = run_gfs(
            args.run_date, args.cycle, steps=args.steps, bbox=tuple(args.bbox), variables=args.variables,
            raw_root=Path(args.raw_root) if args.raw_root else None,
            silver_root=Path(args.silver_root) if args.silver_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("real_batch") else 2
    if args.command == "c3s-seasonal":
        result = run_c3s_seasonal(
            args.forecast_year, args.init_month, hindcast_years=args.hindcast_years,
            variables=args.variables, lead_months=args.lead_months, bbox=tuple(args.bbox),
            originating_centre=args.originating_centre, system=args.system,
            raw_root=Path(args.raw_root) if args.raw_root else None,
            silver_root=Path(args.silver_root) if args.silver_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] == "BLOCKED_AUTH" else 1
    if args.command == "gpm-imerg":
        result = run_gpm_imerg(
            args.start_time, args.end_time, run=args.run, version=args.version, bbox=tuple(args.bbox),
            raw_root=Path(args.raw_root) if args.raw_root else None,
            silver_root=Path(args.silver_root) if args.silver_root else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2 if result["status"] == "BLOCKED_AUTH" else 1
    if args.command == "forecast-failover":
        candidates = {
            "ecmwf_open_ifs_aifs": args.ecmwf,
            "noaa_gfs": args.gfs,
            "open_meteo_forecast": args.open_meteo,
        }
        result = run_forecast_failover(
            candidates, priority_config=Path(args.priority_config) if args.priority_config else None,
            environment=args.environment, required_horizon_hours=args.required_horizon_hours,
            output=Path(args.output) if args.output else None,
            health_database=Path(args.health_database) if args.health_database else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            run_id=args.run_id, checked_at_utc=args.checked_at_utc,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] == "completed" else 2
    if args.command == "revalidate-thqbca":
        result = revalidate_thqbca(
            Path(args.archive),
            Path(args.download_manifest),
            Path(args.listing_manifest),
            Path(args.parse_manifest),
            Path(args.parsed_csv),
            Path(args.output),
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "verified" else 1
    if args.command == "resample":
        result = run_resampling(Path(args.input), Path(args.output_root) if args.output_root else None, Path(args.database) if args.database else None, frequency=args.frequency)
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "align":
        result = run_alignment(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            max_time_diff_hours=args.max_time_diff_hours,
            ideal_ground_remote_hours=args.ideal_ground_remote_hours,
            matching_strategy=args.matching_strategy,
            max_space_m=args.max_space_m,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "spatial-align":
        result = run_spatial_alignment(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            boundary_path=Path(args.boundary) if args.boundary else None,
            grid_size_m=args.grid_size_m,
            station_buffer_pixels=tuple(args.station_buffer_pixels),
            grid_origin=tuple(args.grid_origin),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "imputation-validation":
        result = run_imputation_validation(
            Path(args.input), Path(args.output),
            summary_path=Path(args.summary),
            database=Path(args.database) if args.database else None,
            mask_rates=args.mask_rates,
            seed=args.seed,
            min_series_length=args.min_series_length,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "features":
        result = run_feature_engineering(
            Path(args.alignment),
            Path(args.observations),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 1
    if args.command == "daily-features":
        result = run_daily_direct_features(
            Path(args.observations), Path(args.output_root), Path(args.database),
            static_features_path=Path(args.static_features) if args.static_features else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    if args.command == "lag-rolling-features":
        result = run_lag_rolling_features(
            Path(args.input), Path(args.output_root), Path(args.database),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    if args.command == "mechanistic-features":
        result = run_mechanistic_features(
            Path(args.input), Path(args.output_root), Path(args.database),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    if args.command == "reliability-features":
        result = run_reliability_features(
            Path(args.input), Path(args.output_root), Path(args.database),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    if args.command == "horizon-dataset-gate":
        result = run_horizon_dataset_gate(Path(args.input), Path(args.output_root), horizon=args.horizon, seasonal_ready=args.seasonal_ready)
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "READY" else 2
    if args.command == "remote-index":
        result = run_remote_index(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            reflectance_scale=args.reflectance_scale,
            cloud_threshold=args.cloud_threshold,
            ndwi_water_threshold=args.ndwi_water_threshold,
            fai_threshold=args.fai_threshold,
            pixel_area_km2=args.pixel_area_km2,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"completed", "completed_with_schema_conflicts"} else 1
    if args.command == "remote-pair":
        result = run_remote_pair(
            Path(args.remote), Path(args.ground),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            max_time_diff_hours=args.max_time_diff_hours,
            max_space_m=args.max_space_m,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "remote-calibrate":
        result = run_remote_calibration(
            Path(args.pairs),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            features=[item.strip() for item in args.features.split(",") if item.strip()],
            min_pairs=args.min_pairs,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 1
    if args.command == "split":
        result = run_split(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            strategy=args.strategy,
            train_fraction=args.train_fraction,
            validation_fraction=args.validation_fraction,
            group_field=args.group_field,
            validation_groups={item.strip() for item in args.validation_groups.split(",") if item.strip()},
            test_groups={item.strip() for item in args.test_groups.split(",") if item.strip()},
            time_granularity=args.time_granularity,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "train":
        result = train_experiment(
            Path(args.input_dir),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            target_variable=args.target_variable,
            algorithm=args.algorithm,
            fusion=args.fusion,
            random_state=args.random_state,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "horizon-labels":
        result = run_horizon_labels(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            target_variable=args.target_variable,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "coverage":
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
        if as_of is not None and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        result = run_coverage(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            as_of=as_of,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "waterstation-fetch":
        result = ingest_water_station_endpoint(args.url, source_id=args.source_id)
        print(json.dumps(contract_response(result.to_dict(), command=args.command), ensure_ascii=True, indent=2))
        return 0 if result.status == "ingested" else 2 if result.status == "BLOCKED_AUTH" else 1
    if args.command == "waterstation-auth-probe":
        result = probe_water_station_auth(args.url)
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({**result, "manifest": str(manifest_path)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["manifest"] = str(manifest_path)
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready_to_request" else 2
    if args.command == "waterstation-parse":
        result = run_water_station_parse(Path(args.input), Path(args.output), source_id=args.source_id)
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "waterstation-validate":
        result = run_station_validation(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            max_median_interval_hours=args.max_median_interval_hours,
            max_gap_hours=args.max_gap_hours,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["validation_status"] == "ready" else 2
    if args.command == "waterstation-batch":
        result = run_water_station_batch(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            source_id=args.source_id,
            max_median_interval_hours=args.max_median_interval_hours,
            max_gap_hours=args.max_gap_hours,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready" else 2
    if args.command == "waterstation-batch-dir":
        result = run_water_station_batch_directory(
            Path(args.input_root),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            source_id=args.source_id,
            max_median_interval_hours=args.max_median_interval_hours,
            max_gap_hours=args.max_gap_hours,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready" else 2
    if args.command == "waterstation-preflight":
        result = run_water_station_preflight(
            Path(args.input_root),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            source_id=args.source_id,
            max_median_interval_hours=args.max_median_interval_hours,
            max_gap_hours=args.max_gap_hours,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready" else 2
    if args.command == "waterstation-preflight-issues":
        result = run_water_station_issue_report(
            Path(args.preflight_root),
            input_root=Path(args.input_root) if args.input_root else None,
            output_path=Path(args.output),
            summary_path=Path(args.summary),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        print(json.dumps(contract_response({key: value for key, value in result.items() if key != "issue_rows"}, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready" else 2
    if args.command == "quality-report":
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
        if as_of is not None and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        result = run_quality_report(
            Path(args.cleaned),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
              rejected_path=Path(args.rejected) if args.rejected else None,
              pending_path=Path(args.pending) if args.pending else None,
              issues_path=Path(args.issues) if args.issues else None,
              normalized_path=Path(args.normalized) if args.normalized else None,
              suspect_path=Path(args.suspect) if args.suspect else None,
              pending_conflicts_path=Path(args.pending_conflicts) if args.pending_conflicts else None,
              duplicate_audit_path=Path(args.duplicate_audit) if args.duplicate_audit else None,
            as_of=as_of,
            max_staleness_days=args.max_staleness_days,
            low_frequency_hours=args.low_frequency_hours,
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0
    if args.command == "file-quarantine":
        result = run_file_quarantine(
            input_root=Path(args.input_root),
            report_path=Path(args.output),
            manifest_path=Path(args.manifest),
        )
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"completed", "completed_with_issues"} else 2
    if args.command == "lake-geodata-probe":
        result = probe_lake_geodata_sources(
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
        )
        # Windows console encodings may not render page titles/Chinese source
        # names; the JSON manifest on disk remains UTF-8 and lossless.
        print(json.dumps(contract_response(result, command=args.command), ensure_ascii=True, indent=2))
        return 0 if result["status"] == "completed" else 1

    results = []
    if args.source in {"sentinel2", "all"}:
        results.append(ingest_sentinel2_stac(args.start, args.end))
    if args.source in {"nasa_power", "all"}:
        results.append(ingest_nasa_power(args.start, args.end, args.longitude, args.latitude))
    if args.source == "open_meteo":
        results.append(ingest_open_meteo_forecast(args.longitude, args.latitude, args.forecast_days))
    if args.source in {"thqbca", "all"}:
        results.append(ingest_thqbca_metadata())

    manifest_dir = Path(__file__).resolve().parents[1] / "storage" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"ingest_{stamp}.json"
    manifest_path.write_text(
        json.dumps(
            {"run_id": f"ingest_{stamp}", "results": [result.to_dict() for result in results]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for result in results:
        # Console encoding on Windows may be GBK; keep the machine-readable
        # response lossless while avoiding UnicodeEncodeError for units such
        # as °C and W/m².
        print(json.dumps(contract_response(result.to_dict(), command=args.command), ensure_ascii=True))
    print(json.dumps(contract_response({"manifest": str(manifest_path), "status": "completed"}, command=args.command), ensure_ascii=True))
    return 0 if all(result.status in {"ingested", "metadata_ingested"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

