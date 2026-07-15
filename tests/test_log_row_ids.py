from pathlib import Path
from unittest.mock import MagicMock

from app.services.app_state import AppState
from app.services.frontend_log_adapter import parse_debug_log_file


def test_runtime_log_ids_remain_unique_and_stable_after_ring_eviction():
    state = AppState(cache_service=MagicMock())
    state.configure_log_buffer(100)

    for index in range(101):
        state.record_log(f"same message {index}", topic="test.logs")

    before = state.get_log_buffer()
    survivor_id = before[50]["id"]
    state.record_log("newest message", topic="test.logs")
    after = state.get_log_buffer()

    assert len({row["id"] for row in after}) == len(after)
    assert survivor_id in {row["id"] for row in after}


def test_file_log_ids_survive_append_and_distinguish_identical_rows(tmp_path):
    log_file = Path(tmp_path) / "debug.log"
    duplicate = "[2026-07-15 12:00:00] [INFO] Test / identical event"
    log_file.write_text(f"{duplicate}\n{duplicate}", encoding="utf-8")

    before = parse_debug_log_file(log_file, limit=10)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{duplicate}")
    after = parse_debug_log_file(log_file, limit=10)

    assert [row["id"] for row in after[:2]] == [row["id"] for row in before]
    assert len({row["id"] for row in after}) == 3
