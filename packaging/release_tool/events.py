"""Structured, redacted events for the release-builder protocol."""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TextIO, TypeAlias

from .models import ReleaseStage


EVENT_PREFIX = "@@UCRAWL_RELEASE_EVENT@@"
REDACTED = "[REDACTED]"

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | Mapping[str, "JSONValue"] | Sequence["JSONValue"]

_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----.*?"
    r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----",
    re.DOTALL | re.IGNORECASE,
)
_SENSITIVE_HEADER = re.compile(
    r"(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_URL_USERINFO = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+@")
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&;][^=&\s]*(?:token|key|password|passwd|secret|authorization|cookie|credential)[^=&\s]*\s*=)[^&#\s]*"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b[^\s=,;]*(?:token|key|password|passwd|secret|authorization|cookie|credential)[^\s=,;]*\s*=\s*[^\s,;#&]+"
)
_SENSITIVE_DATA_KEY = re.compile(
    r"(?i)(?:token|key|password|passwd|secret|authorization|cookie|credential)"
)


def redact_release_text(text: str) -> str:
    """Return text with credential-like content removed before it can be emitted."""

    redacted = str(text)
    redacted = _PRIVATE_KEY_BLOCK.sub(REDACTED, redacted)
    redacted = _SENSITIVE_HEADER.sub(lambda match: f"{match.group(0).split(':', 1)[0]}: {REDACTED}", redacted)
    redacted = _BEARER_TOKEN.sub(f"Bearer {REDACTED}", redacted)
    redacted = _URL_USERINFO.sub(lambda match: f"{match.group(1)}{REDACTED}@", redacted)
    redacted = _SENSITIVE_QUERY_VALUE.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
    return _SENSITIVE_ASSIGNMENT.sub(REDACTED, redacted)


def _redact_event_data(value: object, *, key: str = "") -> JSONValue:
    if key and _SENSITIVE_DATA_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_release_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("release event data must contain only finite floats")
        return value
    if isinstance(value, Mapping):
        return {
            redact_release_text(str(item_key)): _redact_event_data(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_redact_event_data(item) for item in value]
    return REDACTED


def _freeze_json_value(value: JSONValue) -> JSONValue:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json_value(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, str):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def _mutable_json_value(value: JSONValue) -> JSONValue:
    if isinstance(value, Mapping):
        return {str(key): _mutable_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_mutable_json_value(item) for item in value]
    return value


def _reject_non_standard_json_constant(value: str) -> None:
    raise ValueError(f"release event payload contains non-standard JSON constant {value!r}")


def _timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validated_progress(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("release event progress must be an integer between 0 and 100")
    return value


@dataclass(frozen=True)
class ReleaseEvent:
    kind: str
    sequence: int
    timestamp: str
    stage: ReleaseStage
    progress: int
    message: str = ""
    data: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, Mapping):
            raise ValueError("release event data must be a mapping")
        data = _redact_event_data(self.data)
        if not isinstance(data, Mapping):  # Defensive guard for the declared event contract.
            raise ValueError("release event data must be a mapping")
        object.__setattr__(self, "message", redact_release_text(self.message))
        object.__setattr__(self, "data", _freeze_json_value(data))

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "stage": self.stage.value,
            "progress": self.progress,
            "message": self.message,
            "data": _mutable_json_value(self.data),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ReleaseEvent":
        try:
            kind = payload["kind"]
            sequence = payload["sequence"]
            timestamp = payload["timestamp"]
            stage = payload["stage"]
            progress = payload["progress"]
        except KeyError as error:
            raise ValueError(f"release event is missing {error.args[0]!r}") from error

        if not isinstance(kind, str) or not kind:
            raise ValueError("release event kind must be a non-empty string")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("release event sequence must be a positive integer")
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError("release event timestamp must be a non-empty string")
        if not isinstance(stage, str):
            raise ValueError("release event stage must be a string")
        if not isinstance(payload.get("message", ""), str):
            raise ValueError("release event message must be a string")
        data = payload.get("data", {})
        if not isinstance(data, Mapping):
            raise ValueError("release event data must be a mapping")

        return cls(
            kind=kind,
            sequence=sequence,
            timestamp=timestamp,
            stage=ReleaseStage(stage),
            progress=_validated_progress(progress),
            message=redact_release_text(payload.get("message", "")),
            data=_redact_event_data(data),
        )


class ReleaseEventEmitter:
    """Serialize release events while preserving sequence and progress invariants."""

    def __init__(self, *, stream: TextIO, clock: Callable[[], datetime] = datetime.now) -> None:
        self._stream = stream
        self._clock = clock
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_progress = 0

    def emit(
        self,
        kind: str,
        *,
        stage: ReleaseStage,
        progress: int,
        message: str = "",
        data: Mapping[str, JSONValue] | None = None,
    ) -> ReleaseEvent:
        progress = _validated_progress(progress)
        if not isinstance(kind, str) or not kind:
            raise ValueError("release event kind must be a non-empty string")
        if not isinstance(stage, ReleaseStage):
            stage = ReleaseStage(stage)

        with self._lock:
            if progress < self._last_progress:
                raise ValueError("release event progress must not decrease")
            event = ReleaseEvent(
                kind=kind,
                sequence=self._sequence + 1,
                timestamp=_timestamp_text(self._clock()),
                stage=stage,
                progress=progress,
                message=redact_release_text(message),
                data={} if data is None else data,
            )
            self._sequence = event.sequence
            self._last_progress = event.progress
            payload = json.dumps(
                event.to_payload(),
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
            )
            line = f"{EVENT_PREFIX}{payload}\n"
            try:
                self._stream.write(line)
                self._stream.flush()
            except Exception:
                raise RuntimeError("failed to emit release event") from None
            return event


def parse_event_line(line: str) -> ReleaseEvent | None:
    text = str(line).rstrip("\r\n")
    if not text.startswith(EVENT_PREFIX):
        return None
    payload = json.loads(
        text[len(EVENT_PREFIX) :],
        parse_constant=_reject_non_standard_json_constant,
    )
    if not isinstance(payload, Mapping):
        raise ValueError("release event payload must be a JSON object")
    return ReleaseEvent.from_payload(payload)


class ReleaseLogError(RuntimeError):
    """Raised when a release log cannot be persisted."""


class ReleaseLogWriter:
    """Persist one redacted UTF-8 release-log line at a time."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def write_line(self, text: str) -> None:
        safe_text = redact_release_text(text).rstrip("\r\n")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"{safe_text}\n")
                stream.flush()
        except (OSError, UnicodeError):
            raise ReleaseLogError("failed to write release log") from None


__all__ = [
    "EVENT_PREFIX",
    "JSONValue",
    "ReleaseEvent",
    "ReleaseEventEmitter",
    "ReleaseLogError",
    "ReleaseLogWriter",
    "parse_event_line",
    "redact_release_text",
]
