import json

from scripts.probe_cds_auth import probe


def test_missing_cds_key_is_blocked_and_redacted(tmp_path):
    manifest = probe(env={}, config_paths=[], output_path=tmp_path / "probe.json")
    assert manifest["status"] == "BLOCKED_AUTH"
    assert manifest["network_probe_attempted"] is False
    assert manifest["config_source"] is None
    assert "MissingCDSConfiguration" == manifest["error_class"]
    assert "API key" in (tmp_path / "probe.json").read_text(encoding="utf-8")


def test_readable_cds_config_reports_presence_without_key_value(tmp_path):
    config = tmp_path / ".cdsapirc"
    config.write_text(
        "url: https://cds.climate.copernicus.eu/api\nkey: student:super-secret-key\n",
        encoding="utf-8",
    )
    output = tmp_path / "probe.json"
    manifest = probe(env={}, config_paths=[config], output_path=output)
    text = output.read_text(encoding="utf-8")
    assert manifest["status"] == "CONFIGURED_PENDING_TERMS"
    assert manifest["config_source"] == "config_file"
    assert manifest["config_files"][0]["readable"] is True
    assert manifest["config_files"][0]["key_present"] is True
    assert "super-secret-key" not in text
    assert "student:super-secret-key" not in text


def test_environment_key_is_presence_only(tmp_path):
    manifest = probe(
        env={"TAIHU_CDS_API_KEY": "student:super-secret-key"},
        config_paths=[],
        output_path=tmp_path / "probe.json",
    )
    persisted = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "CONFIGURED_PENDING_TERMS"
    assert persisted["present_env"]["TAIHU_CDS_API_KEY"] is True
    assert "super-secret-key" not in json.dumps(persisted)
