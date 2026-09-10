"""算法交付包 V0.2 接入契约。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.algorithm_models import AlgorithmModelService, CLAIM_BOUNDARY, DATA_VERSION
from backend.main import app

client = TestClient(app)


class FakeRealtime:
    def summary(self):
        return {
            "latest_snapshot_id": "mee-test-snapshot",
            "latest_observed_at": "2026-09-09T15:00:00+08:00",
            "means": {
                "water_temperature": {"value": 28.2},
                "total_phosphorus": {"value": 0.096},
                "total_nitrogen": {"value": 1.717},
                "dissolved_oxygen": {"value": 6.105},
            },
            "markers": [
                {"id": "mee-a", "name": "A", "lat": 31.1, "lon": 120.1, "observed_at": "2026-09-09T15:00:00+08:00", "metrics": {"pH": 7.8, "water_temperature": 28.0, "total_phosphorus": 0.09, "total_nitrogen": 1.6, "dissolved_oxygen": 6.2}},
                {"id": "mee-b", "name": "B", "lat": 31.3, "lon": 120.3, "observed_at": "2026-09-09T15:00:00+08:00", "metrics": {"pH": 8.2, "water_temperature": 28.4, "total_phosphorus": 0.10, "total_nitrogen": 1.8, "dissolved_oxygen": 6.0}},
            ],
        }


def test_complete_model_runtime_and_prediction_provenance():
    service = AlgorithmModelService(FakeRealtime())
    status = service.status()
    assert status["status"] == "ready"
    assert status["model_count"] == 63
    assert status["data_version"] == DATA_VERSION
    assert status["claim_boundary"] == CLAIM_BOUNDARY

    result = service.predict_suite(3)
    assert set(result["results"]) == {
        "bloom", "area", "coverage", "density", "biomass", "chla",
        "risk_level", "probability", "spatial",
    }
    assert result["prediction_run_id"].startswith("ALG-V0.2-mee-test-snapshot-lake-3d")
    assert result["input_provenance"]["observed_feature_count"] == 5
    assert result["input_provenance"]["imputed_feature_count"] > 0
    assert result["quality_gate"]["decision"] == "scenario_assessment_only"
    assert result["model"]["claim_boundary"] == CLAIM_BOUNDARY
    assert result["acceptance"]["status"] == "FAIL"
    explanation = result["results"]["probability"]["explainability"]
    assert explanation["method"] == "local_one_at_a_time_sensitivity"
    assert explanation["is_shap"] is False
    assert explanation["unavailable_factors"][0]["feature"] == "ammonia_nitrogen_mg_L"
    uncertainty = result["results"]["probability"]["uncertainty"]
    assert uncertainty["sample_count"] == 64
    assert uncertainty["is_calibrated_confidence_interval"] is False


def test_spatial_field_and_pair_calibration_are_traceable():
    service = AlgorithmModelService(FakeRealtime())
    field = service.spatial_field(7, "chla")
    assert field["point_count"] == 2
    assert field["interpolation_status"] == "not_continuous_raster"
    assert all(0 <= point["normalized"] <= 1 for point in field["points"])

    calibrated = service.calibrate_retrieval({
        "parameter": "chlorophyll_a",
        "pairs": [
            {"retrieved": 1, "reference": 3},
            {"retrieved": 2, "reference": 5},
            {"retrieved": 3, "reference": 7},
        ],
        "values": [4],
    })
    assert calibrated["value_origin"] == "derived_calibrated_retrieval"
    assert calibrated["metrics"]["pair_count"] == 3
    assert calibrated["calibrated_values"][0] == pytest.approx(9.0)


def test_model_status_endpoint_discloses_hybrid_track():
    response = client.get("/api/v1/model/status")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["model_count"] == 63
    assert body["meta"]["data_mode"] == "hybrid"
    assert body["meta"]["dataset_version"] == DATA_VERSION
    assert body["meta"]["claim_boundary"] == CLAIM_BOUNDARY
