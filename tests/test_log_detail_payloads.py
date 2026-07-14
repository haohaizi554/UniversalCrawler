from shared.log_detail_payloads import (
    build_log_detail_payload,
    extract_trace_id,
    normalize_detail_payload,
)


def test_normalize_detail_payload_enriches_message_path_and_status_code():
    item = {
        "message": r"Scan complete: D:\Downloads\video.mp4",
        "detail": '{"traceId": "trace-from-detail", "extra": "ok"}',
        "status_code": "SCAN_DONE",
        "platform": "system",
        "source": "GUI",
    }

    payload = normalize_detail_payload(item, status_code="SCAN_DONE")

    assert payload["description"] == "Scan complete"
    assert payload["path"] == r"D:\Downloads\video.mp4"
    assert payload["status_code"] == "SCAN_DONE"
    assert payload["traceId"] == "trace-from-detail"


def test_extract_trace_id_prefers_top_level_then_detail_payload():
    assert extract_trace_id({"trace_id": "top", "detail": {"trace_id": "detail"}}) == "top"
    assert extract_trace_id({"detail": {"traceId": "detail"}}) == "detail"
    assert extract_trace_id({"detail": '{"trace": "json-trace"}'}) == "json-trace"


def test_build_log_detail_payload_uses_normalized_detail_payload():
    item = {
        "time": "2026-07-01 12:00:00",
        "level": "INFO",
        "source": "GUI",
        "message_summary": "Application init",
        "detail": '{"trace_id": "trace-1"}',
    }

    payload = build_log_detail_payload(item, platform_label="system", status_code="APP_INIT")

    assert payload["platform"] == "system"
    assert payload["trace_id"] == "trace-1"
    assert payload["message"] == "Application init"
    assert payload["detail"]["status_code"] == "APP_INIT"
