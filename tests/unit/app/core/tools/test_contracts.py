from __future__ import annotations

from pathlib import Path

import pytest

from app.core.tools.contracts import (
    CancellationToken,
    ToolCancelledError,
    ToolContext,
    ToolManifest,
    ToolRunResult,
    ToolRunStatus,
)


def test_manifest_serializes_stable_frontend_contract() -> None:
    manifest = ToolManifest(
        id="media.health",
        title="媒体体检",
        summary="检查媒体流",
        category="media",
        input_schema={"path": {"type": "file", "required": True}},
        permissions=("read_file",),
        supports_cancel=True,
        icon="metadata",
        sort_order=20,
    )

    payload = manifest.to_dict()

    assert payload["id"] == "media.health"
    assert payload["input_schema"]["path"]["type"] == "file"
    assert payload["permissions"] == ["read_file"]
    assert payload["supports_cancel"] is True
    assert payload["sort_order"] == 20


def test_context_authorizes_only_paths_inside_approved_roots(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "video.mp4"
    source.write_bytes(b"media")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"media")
    context = ToolContext(parameters={}, approved_roots=(str(approved),))

    assert context.authorize_path(source) == source.resolve()
    with pytest.raises(PermissionError):
        context.authorize_path(outside)


def test_cancel_token_interrupts_context() -> None:
    token = CancellationToken()
    context = ToolContext(parameters={}, cancellation=token)

    token.cancel()

    assert context.is_cancelled()
    with pytest.raises(ToolCancelledError):
        context.raise_if_cancelled()


def test_run_result_is_json_compatible() -> None:
    result = ToolRunResult.success(
        "完成",
        data={"streams": 2},
        output_paths=("D:/output.mp4",),
        warnings=("warning",),
    )

    payload = result.to_dict()

    assert payload == {
        "status": ToolRunStatus.SUCCEEDED.value,
        "message": "完成",
        "data": {"streams": 2},
        "output_paths": ["D:/output.mp4"],
        "warnings": ["warning"],
    }
