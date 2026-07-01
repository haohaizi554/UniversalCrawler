from app.services import frontend_status_adapter as status_adapter


def test_format_transfer_speed_uses_human_units():
    assert status_adapter.format_transfer_speed(0) == "0 B/s"
    assert status_adapter.format_transfer_speed(2048) == "2.0 KB/s"
    assert status_adapter.format_transfer_speed(2 * 1024 * 1024) == "2.0 MB/s"


def test_parse_speed_string_accepts_binary_units_and_invalid_values():
    assert status_adapter.parse_speed_string("2 MB/s") == 2 * 1024 * 1024
    assert status_adapter.parse_speed_string("1.5MiB/s") == int(1.5 * 1024**2)
    assert status_adapter.parse_speed_string("not moving") == 0


def test_aggregate_speed_prefers_numeric_bps_with_text_fallback():
    active = [
        {"speed_bps": 1024},
        {"speed": "2 KB/s"},
        {"speed": "bad"},
    ]

    assert status_adapter.aggregate_speed_bps(active) == 3 * 1024
    assert status_adapter.aggregate_speed(active) == "3.0 KB/s"


def test_build_app_status_derives_running_error_and_idle_payloads():
    running = status_adapter.build_app_status(
        running=True,
        running_state="空闲中",
        queue_count=1,
        active_count=2,
        completed_count=3,
        failed_count=0,
        active_downloads=[{"speed_bps": 2048}],
        version="1.2.3",
    )

    assert running["running_state"] == "运行中"
    assert running["status_indicator"] == "running"
    assert running["download_speed"] == "2.0 KB/s"
    assert running["download_speed_bps"] == 2048
    assert running["version"] == "v1.2.3"

    failed = status_adapter.build_app_status(
        running=False,
        running_state="空闲中",
        queue_count=0,
        active_count=0,
        completed_count=0,
        failed_count=1,
        active_downloads=[],
        version="1.0.0",
    )
    assert failed["status_indicator"] == "error"
    assert failed["running_state"] == "空闲中"

    idle = status_adapter.build_app_status(
        running=False,
        running_state="空闲中",
        queue_count=0,
        active_count=0,
        completed_count=0,
        failed_count=0,
        active_downloads=[],
        version="1.0.0",
    )
    assert idle["status_indicator"] == "idle"
