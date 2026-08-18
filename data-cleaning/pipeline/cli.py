from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .clean import run_cleaning
from .fault_injection import run_fault_injection
from .resample import run_resampling
from .align import run_alignment
from .features import run_feature_engineering
from .remote import run_remote_calibration, run_remote_index, run_remote_pair
from .experiment import run_split
from .modeling import train_experiment
from .forecast_labels import run_horizon_labels
from .coverage import run_coverage
from .station_validate import run_station_validation
from .waterstation_batch import run_water_station_batch
from .waterstation_batch_dir import run_water_station_batch_directory
from .waterstation_preflight import run_water_station_preflight
from .quality_report import run_quality_report
from .batch import run_data_cleaning_batch
from .sources import download_thqbca_archive, extract_thqbca_workbooks, ingest_nasa_power, ingest_open_meteo_forecast, ingest_sentinel2_stac, ingest_thqbca_metadata, ingest_water_station_endpoint, list_thqbca_archive, probe_lake_geodata_sources, run_water_station_parse
from .sources.thqbca_data import parse_thqbca_workbooks


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
    resample = sub.add_parser("resample", help="resample hourly/daily records without upsampling low-frequency sources")
    resample.add_argument("--input", required=True, help="cleaned_observations.csv or another standard observation CSV")
    resample.add_argument("--output-root", default=None)
    resample.add_argument("--database", default=None)
    align = sub.add_parser("align", help="align target and driver series with auditable time/space gaps")
    align.add_argument("--input", required=True, help="resampled_observations.csv")
    align.add_argument("--output-root", default=None)
    align.add_argument("--database", default=None)
    align.add_argument("--max-time-diff-hours", type=float, default=72.0)
    align.add_argument("--max-space-m", type=float, default=50000.0)
    features = sub.add_parser("features", help="build causal lag, rolling, nutrient and weather features")
    features.add_argument("--alignment", required=True, help="temporal_alignments.csv")
    features.add_argument("--observations", required=True, help="resampled_observations.csv")
    features.add_argument("--output-root", default=None)
    features.add_argument("--database", default=None)
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
    quality = sub.add_parser("quality-report", help="summarize cleaned rows, missingness, duplicates, proxies and freshness")
    quality.add_argument("--cleaned", required=True, help="cleaned_observations.csv")
    quality.add_argument("--rejected", default=None)
    quality.add_argument("--pending", default=None)
    quality.add_argument("--issues", default=None)
    quality.add_argument("--as-of", default=None)
    quality.add_argument("--max-staleness-days", type=float, default=30.0)
    quality.add_argument("--low-frequency-hours", type=float, default=24.0)
    quality.add_argument("--output-root", default=None)
    quality.add_argument("--database", default=None)
    lake_probe = sub.add_parser("lake-geodata-probe", help="probe public NIGLAS/NESDC Taihu metadata pages and record access boundary")
    lake_probe.add_argument("--output-root", default=None)
    lake_probe.add_argument("--database", default=None)
    args = parser.parse_args()

    if args.command == "clean":
        result = run_cleaning(Path(args.raw_root) if args.raw_root else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] != "failed" else 1
    if args.command == "fault-test":
        result = run_fault_injection()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["recall"] == 1.0 else 1
    if args.command == "download-thqbca":
        result = download_thqbca_archive(Path(args.output), args.md5)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest_path = Path("storage/manifests") / f"thqbca_download_{stamp}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        result["retrieved_at"] = stamp
        result["manifest"] = str(manifest_path)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["verified"] else 1
    if args.command == "list-thqbca":
        result = list_thqbca_archive(Path(args.archive), Path(args.manifest))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "extract-thqbca":
        result = extract_thqbca_workbooks(Path(args.archive), Path(args.output_root))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "parse-thqbca":
        result = parse_thqbca_workbooks(Path(args.water_quality), Path(args.climate), Path(args.output), Path(args.manifest))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "resample":
        result = run_resampling(Path(args.input), Path(args.output_root) if args.output_root else None, Path(args.database) if args.database else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "align":
        result = run_alignment(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            max_time_diff_hours=args.max_time_diff_hours,
            max_space_m=args.max_space_m,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "features":
        result = run_feature_engineering(
            Path(args.alignment),
            Path(args.observations),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 1
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"completed", "completed_with_schema_conflicts"} else 1
    if args.command == "remote-pair":
        result = run_remote_pair(
            Path(args.remote), Path(args.ground),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            max_time_diff_hours=args.max_time_diff_hours,
            max_space_m=args.max_space_m,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "remote-calibrate":
        result = run_remote_calibration(
            Path(args.pairs),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            features=[item.strip() for item in args.features.split(",") if item.strip()],
            min_pairs=args.min_pairs,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "horizon-labels":
        result = run_horizon_labels(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            target_variable=args.target_variable,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "waterstation-fetch":
        result = ingest_water_station_endpoint(args.url, source_id=args.source_id)
        print(json.dumps(result.to_dict(), ensure_ascii=True, indent=2))
        return 0 if result.status == "ingested" else 1
    if args.command == "waterstation-parse":
        result = run_water_station_parse(Path(args.input), Path(args.output), source_id=args.source_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "waterstation-validate":
        result = run_station_validation(
            Path(args.input),
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
            max_median_interval_hours=args.max_median_interval_hours,
            max_gap_hours=args.max_gap_hours,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
            as_of=as_of,
            max_staleness_days=args.max_staleness_days,
            low_frequency_hours=args.low_frequency_hours,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "lake-geodata-probe":
        result = probe_lake_geodata_sources(
            Path(args.output_root) if args.output_root else None,
            Path(args.database) if args.database else None,
        )
        # Windows console encodings may not render page titles/Chinese source
        # names; the JSON manifest on disk remains UTF-8 and lossless.
        print(json.dumps(result, ensure_ascii=True, indent=2))
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
        print(json.dumps(result.to_dict(), ensure_ascii=True))
    print(json.dumps({"manifest": str(manifest_path)}, ensure_ascii=True))
    return 0 if all(result.status in {"ingested", "metadata_ingested"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
