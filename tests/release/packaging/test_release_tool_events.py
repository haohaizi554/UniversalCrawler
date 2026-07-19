from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.events import (
    EVENT_PREFIX,
    ReleaseEventEmitter,
    ReleaseLogError,
    ReleaseLogWriter,
    parse_event_line,
    redact_release_text,
)
from release_tool.models import ReleaseStage


FIXED_UTC = datetime(2026, 7, 19, 4, 5, 6, tzinfo=UTC)


def test_event_round_trip_uses_fixed_prefix_and_monotonic_sequence(capsys):
    emitter = ReleaseEventEmitter(stream=sys.stdout, clock=lambda: FIXED_UTC)

    first = emitter.emit("stage", stage=ReleaseStage.PREFLIGHT, progress=10)
    second = emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=15)

    lines = capsys.readouterr().out.splitlines()
    parsed = [parse_event_line(line) for line in lines]
    assert all(line.startswith(EVENT_PREFIX) for line in lines)
    assert parsed == [first, second]
    assert [event.sequence for event in parsed] == [1, 2]
    assert second.progress >= first.progress
    assert first.timestamp == "2026-07-19T04:05:06Z"


def test_emitter_rejects_progress_regressions_and_invalid_bounds():
    emitter = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC)
    emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=20)

    with pytest.raises(ValueError, match="must not decrease"):
        emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=19)
    with pytest.raises(ValueError, match="between 0 and 100"):
        emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=101)


def test_parse_event_line_ignores_non_event_output():
    assert parse_event_line("regular release output\n") is None


def test_emitter_allocates_unique_sequences_when_called_concurrently():
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream, clock=lambda: FIXED_UTC)

    with ThreadPoolExecutor(max_workers=8) as executor:
        events = list(
            executor.map(
                lambda _: emitter.emit(
                    "progress",
                    stage=ReleaseStage.BUILDING_PORTABLE,
                    progress=40,
                ),
                range(40),
            )
        )

    assert sorted(event.sequence for event in events) == list(range(1, 41))
    assert [parse_event_line(line).sequence for line in stream.getvalue().splitlines()] == list(
        range(1, 41)
    )


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz",
        "Bearer ghp_abcdefghijklmnopqrstuvwxyz",
        "Cookie: session=top-secret",
        "https://alice:password@127.0.0.1:7890",
        "-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----",
        "https://example.invalid/build?token=top-secret&keep=visible",
        "api_key=top-secret",
    ],
)
def test_release_logs_redact_sensitive_material(secret):
    redacted = redact_release_text(secret)

    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_emitter_recursively_redacts_hostile_message_and_data(capsys):
    token = "ghp_abcdefghijklmnopqrstuvwxyz"
    password = "do-not-log-this"
    emitter = ReleaseEventEmitter(stream=sys.stdout, clock=lambda: FIXED_UTC)

    emitted = emitter.emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        message=f"Authorization: Bearer {token}",
        data={
            "token": token,
            "nested": {
                "proxy": f"https://alice:{password}@127.0.0.1:7890",
                "query": f"https://example.invalid/?password={password}",
            },
        },
    )

    line = capsys.readouterr().out
    assert token not in line
    assert password not in line
    assert "[REDACTED]" in line
    assert emitted.data["token"] == "[REDACTED]"
    assert emitted.data["nested"]["proxy"] == "https://[REDACTED]@127.0.0.1:7890"


def test_log_writer_appends_redacted_utf8_lines(tmp_path: Path):
    path = tmp_path / "release.log"
    writer = ReleaseLogWriter(path)

    writer.write_line("first")
    writer.write_line("Cookie: session=top-secret")

    assert path.read_text(encoding="utf-8") == "first\nCookie: [REDACTED]\n"


def test_log_writer_raises_named_error_when_persistence_fails(tmp_path: Path, monkeypatch):
    def fail_open(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(ReleaseLogError, match="release log"):
        ReleaseLogWriter(tmp_path / "release.log").write_line("progress")
