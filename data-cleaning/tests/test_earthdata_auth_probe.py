import json

from scripts.probe_earthdata_auth import TOKEN_ENV, probe


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return b'{"username":"student"}'


def test_missing_earthdata_token_is_blocked_without_network(tmp_path):
    calls = []
    manifest = probe(env={}, opener=lambda *args, **kwargs: calls.append(args), output_path=tmp_path / "probe.json")
    assert manifest["status"] == "BLOCKED_AUTH"
    assert manifest["token_request_attempted"] is False
    assert calls == []
    assert "MissingEarthdataToken" in (tmp_path / "probe.json").read_text(encoding="utf-8")


def test_validated_token_is_never_persisted(tmp_path):
    captured = {}

    def fake_open(request, timeout):
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _Response()

    token = "earthdata-super-secret-token"
    output = tmp_path / "probe.json"
    manifest = probe(env={TOKEN_ENV: token}, opener=fake_open, output_path=output)
    text = output.read_text(encoding="utf-8")
    persisted = json.loads(text)
    assert manifest["status"] == "AUTHENTICATED"
    assert manifest["token_validated"] is True
    assert captured["authorization"] == f"Bearer {token}"
    assert captured["timeout"] == 20
    assert token not in text
    assert token not in json.dumps(persisted)
