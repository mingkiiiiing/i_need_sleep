from pipeline.response_contract import contract_response


def test_contract_preserves_payload_and_adds_all_required_fields():
    result = contract_response({"status": "completed", "input_rows": 3, "output_rows": 2, "custom": 1}, command="demo")
    required = {"status", "run_id", "rows_read", "rows_written", "rows_rejected", "outputs", "manifest", "warnings", "next_action"}
    assert required.issubset(result)
    assert result["rows_read"] == 3
    assert result["rows_written"] == 2
    assert result["custom"] == 1
