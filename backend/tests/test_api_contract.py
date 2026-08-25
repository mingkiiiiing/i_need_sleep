from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_capabilities_expose_real_blockers_and_demo_provenance():
    response = client.get("/api/v1/system/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["capabilities"]["long_term_forecast_30_90d"] == "blocked_auth"
    assert body["meta"]["data_mode"] == "simulated"
    assert body["meta"]["claim_boundary"] == "simulation_only"


def test_demo_zones_are_not_claimed_as_real_stations():
    response = client.get("/api/v1/spatial-entities?entity_type=demo_zone")

    assert response.status_code == 200
    assert len(response.json()["data"]) == 6
    assert {item["entity_type"] for item in response.json()["data"]} == {"demo_zone"}


def test_long_term_forecast_is_blocked_instead_of_fabricated():
    response = client.get("/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=30")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CAPABILITY_UNAVAILABLE"


def test_cockpit_compatibility_view_has_simulated_metadata():
    response = client.get("/api/v1/cockpit/points")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["pointData"]["northwest_hotspot"]["dataMode"] == "simulated"
    assert body["meta"]["dataset_version"] == "DEMO-PRED-V1"


def test_cockpit_warning_action_is_explicitly_simulated():
    response = client.post("/api/v1/cockpit/handle-warning", json={"event_id": "demo-event-0"})

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "simulated_dispatched"
    assert response.json()["data"]["channels"] == ["platform_simulation"]
