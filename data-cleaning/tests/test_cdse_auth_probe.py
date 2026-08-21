import json
from pathlib import Path

from scripts.probe_cdse_auth import REQUIRED_ENV, probe


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({"access_token": "DO_NOT_PERSIST_THIS_TOKEN"}).encode()


def test_missing_cdse_credentials_are_blocked_without_network(tmp_path):
    calls = []
    manifest = probe(env={}, opener=lambda *args, **kwargs: calls.append(args), output_path=tmp_path / "probe.json")
    assert manifest["status"] == "BLOCKED_AUTH"
    assert manifest["token_request_attempted"] is False
    assert set(manifest["missing_env"]) == set(REQUIRED_ENV)
    assert calls == []
    assert "DO_NOT_PERSIST" not in (tmp_path / "probe.json").read_text(encoding="utf-8")


def test_successful_probe_is_redacted(tmp_path):
    captured = {}

    def fake_open(request, timeout):
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return _Response()

    env = {
        "TAIHU_CDSE_CLIENT_ID": "student-client",
        "TAIHU_CDSE_CLIENT_SECRET": "student-secret",
    }
    output = tmp_path / "probe.json"
    manifest = probe(env=env, opener=fake_open, output_path=output)
    text = output.read_text(encoding="utf-8")
    assert manifest["status"] == "AUTHENTICATED"
    assert manifest["token_received"] is True
    assert captured["timeout"] == 20
    assert "student-secret" not in text
    assert "DO_NOT_PERSIST_THIS_TOKEN" not in text
    assert "student-secret" in captured["body"]
