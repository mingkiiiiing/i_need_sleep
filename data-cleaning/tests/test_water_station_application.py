from pathlib import Path


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
RECEIPT = STORAGE / "authorization" / "water_station" / "application_receipt.md"


def test_water_station_application_has_required_scope_and_fields():
    text = RECEIPT.read_text(encoding="utf-8")
    for marker in (
        "DRAFT_READY",
        "PENDING_MANUAL_SUBMISSION",
        "2019-01-01",
        "连续 7 天",
        "15—30 分钟",
        "station_id",
        "longitude",
        "latitude",
        "observed_at",
        "water_temperature",
        "chlorophyll_a",
        "algae_density",
        "cyanobacteria_phycocyanin",
        "dissolved_oxygen",
        "total_phosphorus",
        "total_nitrogen",
        "ammonia_nitrogen",
        "quality_code",
    ):
        assert marker in text


def test_water_station_application_has_receipt_and_security_controls():
    text = RECEIPT.read_text(encoding="utf-8")
    for marker in (
        "external_request_id",
        "external_receipt_url",
        "授权期限、署名和再分发限制",
        "不保存身份证号、证件完整照片、密码或登录 Token",
        "[提交后填写，不要编造]",
        "storage/raw/authorized_waterstation/inbox/<delivery_id>/",
    ):
        assert marker in text
