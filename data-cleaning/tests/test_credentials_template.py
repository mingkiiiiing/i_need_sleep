from pathlib import Path


ROOT = Path(__file__).parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
GITIGNORE = ROOT / ".gitignore"


EXPECTED_VARIABLES = {
    "TAIHU_CDSE_CLIENT_ID",
    "TAIHU_CDSE_CLIENT_SECRET",
    "TAIHU_CDS_API_KEY",
    "TAIHU_EARTHDATA_TOKEN",
    "TAIHU_CMA_ACCOUNT_REF",
    "TAIHU_WATER_STATION_TOKEN",
}


def test_env_example_contains_names_only_and_no_real_values():
    lines = [line.strip() for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()]
    assert set(lines) == {f"{name}=" for name in EXPECTED_VARIABLES}
    for line in lines:
        name, value = line.split("=", 1)
        assert name in EXPECTED_VARIABLES
        assert value == ""
        assert not any(secret in value.lower() for secret in ("token", "secret", "key"))


def test_gitignore_covers_credentials_and_oauth_artifacts():
    text = GITIGNORE.read_text(encoding="utf-8")
    assert ".env\n" in text
    assert ".env.*\n" in text
    assert "!.env.example\n" in text
    for entry in ("storage/auth/", "storage/tokens/", "storage/oauth/"):
        assert entry in text
    assert "storage/**/oauth*.json" in text
    assert "storage/**/*token*.json" in text
