from __future__ import annotations

import json

import pytest

from shared.release_identity import (
    ReleaseIdentity,
    format_release_tag,
    load_runtime_release_identity,
    parse_release_tag,
)


def test_release_identity_orders_revision_after_semver() -> None:
    assert ReleaseIdentity("3.6.21", 2) > ReleaseIdentity("3.6.21", 1)
    assert ReleaseIdentity("3.7.0", 0) > ReleaseIdentity("3.6.21", 99)


@pytest.mark.parametrize("value", (-1, True, 1.5, "1"))
def test_release_identity_rejects_non_integer_revision(value: object) -> None:
    with pytest.raises(ValueError, match="revision"):
        ReleaseIdentity("3.6.21", value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tag", "expected"),
    (
        ("v3.6.21", ReleaseIdentity("3.6.21", 0)),
        ("v3.6.21-r1", ReleaseIdentity("3.6.21", 1)),
        ("v3.7.0-rc.1", ReleaseIdentity("3.7.0-rc.1", 0)),
    ),
)
def test_release_tag_round_trip(tag: str, expected: ReleaseIdentity) -> None:
    identity = parse_release_tag(tag)

    assert identity == expected
    assert format_release_tag(identity.version, identity.revision) == tag


@pytest.mark.parametrize("tag", ("3.6.21", "v3.6.21-r0", "v3.6.21-r-1", "v3.6.21-rx"))
def test_release_tag_rejects_noncanonical_values(tag: str) -> None:
    with pytest.raises(ValueError, match="release tag"):
        parse_release_tag(tag)


def test_runtime_identity_missing_file_defaults_to_initial_release(tmp_path) -> None:
    assert load_runtime_release_identity(tmp_path, fallback_version="3.6.21") == ReleaseIdentity(
        "3.6.21",
        0,
    )


def test_runtime_identity_reads_packaged_marker(tmp_path) -> None:
    (tmp_path / "release_identity.json").write_text(
        json.dumps(
            {
                "version": "3.6.21",
                "revision": 3,
                "tag": "v3.6.21-r3",
                "sourceCommit": "a" * 40,
            }
        ),
        encoding="utf-8",
    )

    identity = load_runtime_release_identity(tmp_path, fallback_version="0.0.0")

    assert identity == ReleaseIdentity("3.6.21", 3)


@pytest.mark.parametrize(
    "payload",
    (
        {"version": "3.6.21", "revision": -1, "tag": "v3.6.21"},
        {"version": "3.6.21", "revision": 2, "tag": "v3.6.21-r1"},
        {"version": "3.6.21", "revision": True, "tag": "v3.6.21-r1"},
    ),
)
def test_runtime_identity_rejects_invalid_marker_without_trusting_partial_data(
    tmp_path,
    payload,
) -> None:
    (tmp_path / "release_identity.json").write_text(json.dumps(payload), encoding="utf-8")

    assert load_runtime_release_identity(tmp_path, fallback_version="3.6.20") == ReleaseIdentity(
        "3.6.20",
        0,
    )
