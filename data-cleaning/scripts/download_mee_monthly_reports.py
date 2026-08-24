from pipeline.sources.mee_monthly_reports import run_mee_taihu_monthly


if __name__ == "__main__":
    result = run_mee_taihu_monthly()
    print(result["status"], result["completed_months"], result["expected_months"])
