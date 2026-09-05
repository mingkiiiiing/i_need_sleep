import csv
import json
from pathlib import Path

from blue_algae_m7.predictor import build_demo_rows, predict


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "01_成果" / "member_c_modeling_framework"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = build_demo_rows()
    with (OUT_DIR / "sample_training_rows_V0.1.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = predict(
        "TH_CENTER",
        "short_term",
        ["chlorophyll_a", "bloom_area", "blue_algae_density", "spatial_extent", "risk_level"],
    )
    with (OUT_DIR / "prediction_contract_sample_V0.1.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    handoff = {
        "status": "PASS",
        "scope": "member_c_framework_only",
        "sample_rows": len(rows),
        "claim_boundary": result["claim_boundary"],
        "effect_claim_allowed": result["effect_claim_allowed"],
        "real_data_entry": (
            "blue_algae_m7.training_data.train_and_predict("
            "member_c_training_samples.csv, station_id, forecast_scale, target_metrics)"
        ),
        "next_real_data_requirements": [
            "aligned daily label table with positive and credible negative samples",
            "same-period dynamic weather, water quality, hydrology, or remote sensing features",
            "train/test split rule by time",
            "target metric definitions and risk thresholds",
        ],
    }
    with (OUT_DIR / "member_c_handoff_V0.1.json").open("w", encoding="utf-8") as handle:
        json.dump(handoff, handle, ensure_ascii=False, indent=2)

    print(json.dumps(handoff, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

