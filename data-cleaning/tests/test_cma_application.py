from pathlib import Path


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
RECEIPT = STORAGE / "authorization" / "cma" / "application_receipt.md"


def test_cma_application_record_has_scope_and_pending_receipt():
    text = RECEIPT.read_text(encoding="utf-8")
    for marker in (
        "DRAFT_READY",
        "PENDING_MANUAL_SUBMISSION",
        "2019-01-01",
        "CLDAS",
        "3 小时",
        "气温",
        "降水",
        "风速",
        "相对湿度",
        "短波辐射",
        "external_request_id",
        "receipt_status",
    ):
        assert marker in text


def test_cma_application_record_contains_no_real_identity_or_secret():
    text = RECEIPT.read_text(encoding="utf-8")
    assert "身份证号、家庭住址等无关信息打码" in text
    assert "密码或登录 Token" in text
    assert "[填写]" in text
    assert "[提交后填写，不要编造]" in text
