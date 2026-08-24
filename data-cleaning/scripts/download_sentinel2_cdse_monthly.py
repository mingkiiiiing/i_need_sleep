import argparse
from datetime import date
from pathlib import Path

from pipeline.sources.sentinel2_process_monthly import run_cdse_monthly


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-08-23")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    kwargs = {"manifest_path": Path(args.manifest)} if args.manifest else {}
    result = run_cdse_monthly(date.fromisoformat(args.start), date.fromisoformat(args.end), **kwargs)
    print(result["status"], result["completed_months"], result["month_count"])
