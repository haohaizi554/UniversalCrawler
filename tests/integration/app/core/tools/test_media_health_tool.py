from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.tools.contracts import ToolContext, ToolManifest, ToolRunResult

from app.core.tools.builtin import media_health
from app.core.tools.builtin.media_health import MediaHealthTool


class _ImmediateProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.terminated = False

    def poll(self) -> int:
        return self.returncode

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return self._stdout, self._stderr

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.terminated = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class _CancellingProcess(_ImmediateProcess):
    def __init__(self, cancel_event: threading.Event) -> None:
        super().__init__()
        self._cancel_event = cancel_event
        self.returncode = None

    def poll(self) -> int | None:
        if not self._cancel_event.is_set():
            self._cancel_event.set()
            return None
        return self.returncode


def _context(path: Path | str, *, cancel_event: threading.Event | None = None) -> SimpleNamespace:
    path_value = Path(path) if path else Path.cwd()
    return SimpleNamespace(
        workspace_root=path_value.parent,
        parameters={"path": str(path)},
        allowed_paths=(path_value.parent,),
        cancel_event=cancel_event or threading.Event(),
    )


def _status(result: ToolRunResult) -> str:
    status = getattr(result, "status", None)
    if status:
        value = str(getattr(status, "value", status))
        return {"succeeded": "success", "failed": "error"}.get(value, value)
    if bool(getattr(result, "cancelled", False)):
        return "cancelled"
    return "success" if bool(getattr(result, "success", False)) else "error"


def _data(result: ToolRunResult) -> dict[str, Any]:
    for name in ("data", "output", "details", "result"):
        value = getattr(result, name, None)
        if isinstance(value, dict):
            return value
    return {}


def _error_code(result: ToolRunResult) -> str:
    for name in ("error_code", "code"):
        value = getattr(result, name, "")
        if value:
            return str(value)
    data = _data(result)
    return str(data.get("error_code") or data.get("code") or "")


def _healthy_payload() -> str:
    return json.dumps(
        {
            "format": {
                "duration": "83.2",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "size": "1024",
                "bit_rate": "3200000",
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
    )


def test_module_exposes_read_only_cancellable_tool_contract() -> None:
    tool = MediaHealthTool(ffprobe_resolver=lambda: "ffprobe")

    assert isinstance(tool.manifest, ToolManifest)
    assert media_health.manifest is MediaHealthTool.manifest
    assert callable(media_health.validate)
    assert callable(media_health.run)
    assert getattr(tool.manifest, "id", getattr(tool.manifest, "tool_id", "")) == "media_health"
    assert tuple(getattr(tool.manifest, "permissions", ())) == ("read_file",)
    assert bool(getattr(tool.manifest, "supports_cancel", True))
    assert "path" in getattr(tool.manifest, "input_schema", {})


def test_validate_rejects_missing_path_without_filesystem_io() -> None:
    tool = MediaHealthTool(ffprobe_resolver=lambda: "ffprobe")

    errors = tool.validate(_context(""))

    assert errors
    assert "媒体文件" in " ".join(str(error) for error in errors)


def test_validate_rejects_remote_media_url() -> None:
    context = SimpleNamespace(
        workspace_root=Path.cwd(),
        parameters={"path": "https://example.invalid/video.mp4"},
        cancel_event=threading.Event(),
    )

    errors = MediaHealthTool(ffprobe_resolver=lambda: "ffprobe").validate(context)

    assert errors
    assert "本地文件" in " ".join(str(error) for error in errors)


def test_run_resolves_relative_path_from_context_workspace(tmp_path: Path) -> None:
    media_path = tmp_path / "relative.mp4"
    media_path.write_bytes(b"media")
    context = SimpleNamespace(
        workspace_root=tmp_path,
        parameters={"path": media_path.name},
        cancel_event=threading.Event(),
    )
    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=lambda *_args, **_kwargs: _ImmediateProcess(stdout=_healthy_payload()),
        poll_interval=0,
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert Path(_data(result)["path"]) == media_path


def test_run_reports_healthy_metadata_and_uses_worker_thread(tmp_path: Path) -> None:
    media_path = tmp_path / "healthy.mp4"
    media_path.write_bytes(b"media")
    io_threads: list[threading.Thread] = []

    def resolve_ffprobe() -> str:
        io_threads.append(threading.current_thread())
        return "ffprobe"

    def start_process(*_args, **_kwargs) -> _ImmediateProcess:
        io_threads.append(threading.current_thread())
        return _ImmediateProcess(stdout=_healthy_payload())

    tool = MediaHealthTool(
        ffprobe_resolver=resolve_ffprobe,
        process_factory=start_process,
        poll_interval=0,
    )

    result = tool.run(_context(media_path))

    assert _status(result) == "success"
    assert _data(result)["status"] == "healthy"
    assert _data(result)["metadata"] == {
        "duration": "00:01:23",
        "resolution": "1920 x 1080",
        "format": "MP4",
        "content_type": "video",
        "size_bytes": 1024,
        "bit_rate": 3200000,
        "stream_count": 2,
        "video_codec": "h264",
        "audio_codec": "aac",
    }
    assert _data(result)["issues"] == []
    assert _data(result)["repair_suggestions"] == []
    assert io_threads
    assert all(thread is not threading.main_thread() for thread in io_threads)


def test_run_drains_large_ffprobe_output_without_false_timeout(tmp_path: Path) -> None:
    media_path = tmp_path / "large-metadata.mp4"
    media_path.write_bytes(b"media")
    script = (
        "import json; "
        "print(json.dumps({"
        "'format': {'duration': '1', 'format_name': 'mp4', 'tags': {'comment': 'x' * 524288}}, "
        "'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 16, 'height': 16}]"
        "}))"
    )

    def start_process(_command, **kwargs):
        return subprocess.Popen([sys.executable, "-c", script], **kwargs)

    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=start_process,
        timeout_seconds=1,
        poll_interval=0.01,
    )

    result = tool.run(_context(media_path))

    assert _status(result) == "success"
    assert _data(result)["status"] == "healthy"


def test_run_classifies_audio_only_media(tmp_path: Path) -> None:
    media_path = tmp_path / "audio.mp3"
    media_path.write_bytes(b"media")
    payload = json.dumps(
        {
            "format": {"duration": "12.0", "format_name": "mp3"},
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
        }
    )
    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=lambda *_args, **_kwargs: _ImmediateProcess(stdout=payload),
        poll_interval=0,
    )

    result = tool.run(_context(media_path))

    assert _data(result)["status"] == "healthy"
    assert _data(result)["metadata"]["content_type"] == "audio"
    assert _data(result)["metadata"]["audio_codec"] == "mp3"


def test_run_does_not_require_duration_for_still_images(tmp_path: Path) -> None:
    media_path = tmp_path / "cover.jpg"
    media_path.write_bytes(b"media")
    payload = json.dumps(
        {
            "format": {"format_name": "image2"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "width": 640,
                    "height": 360,
                }
            ],
        }
    )
    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=lambda *_args, **_kwargs: _ImmediateProcess(stdout=payload),
        poll_interval=0,
    )

    result = tool.run(_context(media_path))

    assert _data(result)["status"] == "healthy"
    assert _data(result)["issues"] == []
    assert _data(result)["metadata"]["content_type"] == "image"


def test_run_returns_structured_failure_when_ffprobe_is_missing(tmp_path: Path) -> None:
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"media")
    tool = MediaHealthTool(ffprobe_resolver=lambda: None, poll_interval=0)

    result = tool.run(_context(media_path))

    assert _status(result) == "error"
    assert _error_code(result) == "ffprobe_not_found"
    assert _data(result)["status"] == "unavailable"
    assert _data(result)["repair_suggestions"][0]["code"] == "install_ffmpeg"


def test_run_returns_structured_failure_for_malformed_ffprobe_payload(tmp_path: Path) -> None:
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"media")
    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=lambda *_args, **_kwargs: _ImmediateProcess(
            stdout='{"format": [], "streams": "not-a-stream-list"}',
        ),
        poll_interval=0,
    )

    result = tool.run(_context(media_path))

    assert _status(result) == "error"
    assert _error_code(result) == "invalid_probe_output"
    assert _data(result)["status"] == "unavailable"


def test_run_rejects_media_outside_approved_roots_before_ffprobe(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    media_path = tmp_path / "outside.mp4"
    media_path.write_bytes(b"media")
    context = ToolContext(
        parameters={"path": str(media_path)},
        approved_roots=(str(approved),),
    )

    def unexpected_resolver() -> str:
        raise AssertionError("unauthorized paths must not start ffprobe")

    result = MediaHealthTool(ffprobe_resolver=unexpected_resolver).run(context)

    assert _status(result) == "error"
    assert _error_code(result) == "path_not_authorized"


def test_run_turns_probe_errors_into_diagnosis_and_repair_suggestion(tmp_path: Path) -> None:
    media_path = tmp_path / "broken.mp4"
    media_path.write_bytes(b"media")
    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=lambda *_args, **_kwargs: _ImmediateProcess(
            returncode=1,
            stderr="moov atom not found",
        ),
        poll_interval=0,
    )

    result = tool.run(_context(media_path))

    assert _status(result) == "success"
    assert _data(result)["status"] == "unhealthy"
    assert _data(result)["issues"][0]["code"] == "probe_failed"
    assert "moov atom not found" in _data(result)["issues"][0]["message"]
    assert _data(result)["repair_suggestions"][0]["code"] == "remux"


def test_run_honors_cancellation_before_starting_io(tmp_path: Path) -> None:
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"media")
    cancel_event = threading.Event()
    cancel_event.set()

    def unexpected_resolver() -> str:
        raise AssertionError("cancelled runs must not resolve ffprobe")

    result = MediaHealthTool(ffprobe_resolver=unexpected_resolver).run(
        _context(media_path, cancel_event=cancel_event)
    )

    assert _status(result) == "cancelled"
    assert "取消" in result.message


def test_run_terminates_ffprobe_when_cancelled_during_probe(tmp_path: Path) -> None:
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"media")
    cancel_event = threading.Event()
    process = _CancellingProcess(cancel_event)
    tool = MediaHealthTool(
        ffprobe_resolver=lambda: "ffprobe",
        process_factory=lambda *_args, **_kwargs: process,
        poll_interval=0,
    )

    result = tool.run(_context(media_path, cancel_event=cancel_event))

    assert _status(result) == "cancelled"
    assert "取消" in result.message
    assert process.terminated
