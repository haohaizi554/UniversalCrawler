from __future__ import annotations

import io
import json
import math
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
GITHUB_TOKEN_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_")
GITHUB_TOKEN_CASES = tuple(
    f"{prefix}abcdefghijklmnopqrstuvwxyz123456" for prefix in GITHUB_TOKEN_PREFIXES
)


@pytest.mark.parametrize(
    ("text", "secrets", "expected"),
    [
        (
            "Authorization: Bearer ghp_header_token",
            ("ghp_header_token",),
            "Authorization: [REDACTED]",
        ),
        (
            'password="correct horse \\"battery\\" staple", keep=visible',
            ('correct horse \\"battery\\" staple',),
            "password=[REDACTED], keep=visible",
        ),
        ("token='a b c'; keep=visible", ("a b c",), "token=[REDACTED]; keep=visible"),
        (
            "proxy=https://alice:password@127.0.0.1:7890",
            ("alice", "password"),
            "proxy=https://[REDACTED]@127.0.0.1:7890",
        ),
        (
            "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate\n-----END OPENSSH PRIVATE KEY-----",
            ("private",),
            "[REDACTED]",
        ),
        *[
            (f"release token {token} complete", (token,), "release token [REDACTED] complete")
            for token in GITHUB_TOKEN_CASES
        ],
        ("monkey keyframe tokenize build complete", (), "monkey keyframe tokenize build complete"),
    ],
)
def test_credential_text_corpus_redacts_secrets_and_preserves_benign_text(text, secrets, expected):
    redacted = redact_release_text(text)

    assert redacted == expected
    assert all(secret not in redacted for secret in secrets)


@pytest.mark.parametrize(
    ("key", "redacted"),
    [
        ("APIKey", True),
        ("ApiKey", True),
        ("apiKey", True),
        ("api_key", True),
        ("proxyAPIKey", True),
        ("accessToken", True),
        ("privateKey", True),
        ("monkey", False),
        ("keyframe", False),
        ("tokenize", False),
    ],
)
def test_credential_mapping_key_corpus_uses_acronym_aware_semantic_segments(key, redacted):
    event = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC).emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={"nested": {key: "nested-secret"}},
    )

    expected = "[REDACTED]" if redacted else "nested-secret"
    assert event.data["nested"][key] == expected


def test_credential_corpus_redacts_github_tokens_from_message_log_and_non_sensitive_data(tmp_path: Path):
    token = GITHUB_TOKEN_CASES[0]
    stream = io.StringIO()
    event = ReleaseEventEmitter(stream=stream, clock=lambda: FIXED_UTC).emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        message=f"message {token}",
        data={"nested": {"note": f"data {token}"}},
    )
    log_path = tmp_path / "release.log"
    ReleaseLogWriter(log_path).write_line(f"log {token}")

    assert token not in stream.getvalue()
    assert token not in json.dumps(event.to_payload())
    assert token not in log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "key",
    (
        "apikey",
        "APIKey",
        "api_key",
        "accessToken",
        "ACCESS_TOKEN",
        "refreshtoken",
        "refresh-token",
        "clientSecret",
        "CLIENT_PASSWORD",
        "privatekey",
        "signingKey",
        "proxyusername",
        "proxy-password",
        "proxyToken",
        "proxyAPIKey",
        "authorization",
        "cookie",
        "password",
        "passwd",
        "secret",
        "token",
        "key",
        "credentials",
    ),
)
def test_canonical_credential_keys_redact_mapping_assignment_and_query_values(key):
    secret = "correct horse battery staple"
    event = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC).emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={"nested": {key: secret}},
    )
    text = f'{key}="{secret}"; ?{key}={secret}'

    assert event.data["nested"][key] == "[REDACTED]"
    assert redact_release_text(text) == f"{key}=[REDACTED]; ?{key}=[REDACTED]"


@pytest.mark.parametrize("key", ("monkey", "keyframe", "tokenize"))
def test_benign_keys_survive_mapping_assignment_and_query_values(key):
    value = "plain words"
    event = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC).emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={"nested": {key: value}},
    )
    text = f'{key}="{value}"; ?{key}=words'

    assert event.data["nested"][key] == value
    assert redact_release_text(text) == text


@pytest.mark.parametrize(
    "key",
    ("X-API-Key", "X-Auth-Token", "X-Access-Token", "X-Client-Secret"),
)
def test_transport_prefixed_credential_keys_redact_mapping_assignment_query_and_headers(key):
    secret = "transport-secret"
    event = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC).emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={"nested": {key: secret}},
    )

    assert event.data["nested"][key] == "[REDACTED]"
    assert redact_release_text(f'{key}="{secret}"') == f"{key}=[REDACTED]"
    assert redact_release_text(f"?{key}={secret}") == f"?{key}=[REDACTED]"
    assert redact_release_text(f"{key}: {secret}") == f"{key}: [REDACTED]"


@pytest.mark.parametrize("key", ("Monkey", "Keyframe", "X-Monkey"))
def test_benign_header_and_transport_lookalike_keys_survive_every_surface(key):
    value = "banana"
    event = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC).emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={"nested": {key: value}},
    )

    assert event.data["nested"][key] == value
    assert redact_release_text(f'{key}="{value}"') == f'{key}="{value}"'
    assert redact_release_text(f"?{key}={value}") == f"?{key}={value}"
    assert redact_release_text(f"{key}: {value}") == f"{key}: {value}"


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('before Bearer "ghp_quoted_token" after', "before Bearer [REDACTED] after"),
        ("before Bearer 'ghp_quoted_token' after", "before Bearer [REDACTED] after"),
    ],
)
def test_release_logs_redact_quoted_bearer_values_without_losing_context(text, expected):
    assert redact_release_text(text) == expected


@pytest.mark.parametrize(
    "marker",
    (
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    ),
)
def test_release_logs_redact_truncated_private_key_material_through_end_of_text(marker):
    text = f"before\n{marker}\nprivate material\nstill truncated"

    assert redact_release_text(text) == "before\n[REDACTED]"


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


def test_emitter_redacts_nested_plain_sensitive_mapping_keys():
    secret = "never-emit-this"
    emitter = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC)

    event = emitter.emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={
            "key": secret,
            "private_key": secret,
            "publication": {
                "credentials": secret,
                "api_key": secret,
                "token": secret,
                "password": secret,
                "secret": secret,
                "cookie": secret,
                "authorization": secret,
            },
        },
    )

    assert secret not in json.dumps(event.to_payload())
    assert event.data["key"] == "[REDACTED]"
    assert event.data["private_key"] == "[REDACTED]"
    assert all(value == "[REDACTED]" for value in event.data["publication"].values())


def test_emitter_redacts_semantic_credential_key_segments_without_overmatching_benign_keys():
    secret = "never-emit-this"
    emitter = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC)
    sensitive_keys = (
        "key",
        "api_key",
        "private-key",
        "token",
        "access_token",
        "password",
        "secret",
        "cookie",
        "authorization",
        "proxy_username",
        "proxy-password",
        "proxyCredentials",
    )
    benign_data = {"monkey": "banana", "keyframe": "frame", "tokenize": "words"}

    event = emitter.emit(
        "warning",
        stage=ReleaseStage.PREFLIGHT,
        progress=10,
        data={**{key: secret for key in sensitive_keys}, **benign_data},
    )

    assert all(event.data[key] == "[REDACTED]" for key in sensitive_keys)
    assert {key: event.data[key] for key in benign_data} == benign_data


@pytest.mark.parametrize(
    "private_key_block",
    [
        "-----BEGIN RSA PRIVATE KEY-----\nprivate\n-----END RSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate\n-----END OPENSSH PRIVATE KEY-----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\nprivate\n-----END PGP PRIVATE KEY BLOCK-----",
    ],
)
def test_release_logs_redact_common_private_key_armors(private_key_block):
    redacted = redact_release_text(private_key_block)

    assert private_key_block not in redacted
    assert redacted == "[REDACTED]"


@pytest.mark.parametrize("non_finite", (math.nan, math.inf, -math.inf))
def test_emitter_rejects_nested_non_finite_float_data(non_finite):
    emitter = ReleaseEventEmitter(stream=io.StringIO(), clock=lambda: FIXED_UTC)

    with pytest.raises(ValueError, match="finite"):
        emitter.emit(
            "progress",
            stage=ReleaseStage.PREFLIGHT,
            progress=10,
            data={"nested": [{"value": non_finite}]},
        )


def test_parser_rejects_non_standard_json_constants():
    line = (
        f'{EVENT_PREFIX}'
        '{"kind":"progress","sequence":1,"timestamp":"2026-07-19T04:05:06Z",'
        '"stage":"preflight","progress":10,"data":{"value":NaN}}'
    )

    with pytest.raises(ValueError, match="standard JSON"):
        parse_event_line(line)


class _FailingWriteStream:
    def __init__(self, secret: str) -> None:
        self.lines: list[str] = []
        self._secret = secret
        self._failed = False

    def write(self, text: str) -> int:
        self.lines.append(text)
        if not self._failed:
            self._failed = True
            raise OSError(self._secret)
        return len(text)

    def flush(self) -> None:
        return None


class _FailingFlushStream:
    def __init__(self, secret: str) -> None:
        self.lines: list[str] = []
        self._secret = secret
        self._failed = False

    def write(self, text: str) -> int:
        self.lines.append(text)
        return len(text)

    def flush(self) -> None:
        if not self._failed:
            self._failed = True
            raise OSError(self._secret)


@pytest.mark.parametrize("stream_type", (_FailingWriteStream, _FailingFlushStream))
def test_emitter_reserves_sequence_after_stream_failure_without_leaking_error(stream_type):
    secret = "Authorization: Bearer do-not-leak"
    stream = stream_type(secret)
    emitter = ReleaseEventEmitter(stream=stream, clock=lambda: FIXED_UTC)

    with pytest.raises(RuntimeError, match="release event") as failure:
        emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=10)

    retry = emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=10)
    assert secret not in str(failure.value)
    assert failure.value.__cause__ is None
    assert parse_event_line(stream.lines[0]).sequence == 1
    assert retry.sequence == 2
    assert parse_event_line(stream.lines[-1]).sequence == 2


def test_emitted_and_parsed_event_data_are_deeply_immutable():
    source = {"nested": {"items": [{"safe": "value"}]}}
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream, clock=lambda: FIXED_UTC)

    emitted = emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=10, data=source)
    parsed = parse_event_line(stream.getvalue())
    source["nested"]["items"][0]["safe"] = "mutated-source"

    for event in (emitted, parsed):
        assert event.data["nested"]["items"][0]["safe"] == "value"
        with pytest.raises(TypeError):
            event.data["nested"]["items"][0]["safe"] = "mutated-event"
        with pytest.raises(AttributeError):
            event.data["nested"]["items"].append("mutated-event")

        payload = event.to_payload()
        assert isinstance(payload["data"], dict)
        assert isinstance(payload["data"]["nested"]["items"], list)
        payload["data"]["nested"]["items"][0]["safe"] = "mutated-payload"
        assert event.data["nested"]["items"][0]["safe"] == "value"
        json.dumps(payload, allow_nan=False)


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
