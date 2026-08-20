from pathlib import Path

import yaml


POLICY = Path(__file__).parents[1] / "config" / "web_collection_policy.yml"


def _policy():
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def test_web_policy_covers_required_authorities_and_defaults_to_blocked():
    policy = _policy()
    assert policy["policy_mode"] == "deny_by_default"
    assert policy["global_rules"]["manual_confirmation_required"] is True
    assert policy["global_rules"]["reverse_engineering_private_ajax"] is False
    assert policy["global_rules"]["default_decision_before_review"] == "BLOCKED_POLICY"
    source_ids = {item["source_id"] for item in policy["sources"]}
    assert {"mee_surface_water_realtime", "tba_current_level", "mwr_hfc"}.issubset(source_ids)
    for item in policy["sources"]:
        assert item["terms_status"] == "manual_review_required"
        assert item["robots_status"] == "not_verified"
        assert item["current_decision"] == "BLOCKED_POLICY"


def test_web_policy_has_frequency_contact_and_prohibited_actions():
    policy = _policy()
    for item in policy["sources"]:
        assert item["robots_url"].endswith("/robots.txt")
        assert item["minimum_interval_seconds_after_approval"] >= 3600
        assert item["max_requests_per_run_after_approval"] == 1
        assert item["contact_url"].startswith("https://")
        assert item["contact_method"]
        assert item["prohibited_actions"]
        assert item["allowed_actions_before_review"]
