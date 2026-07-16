from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import Mock, patch


def test_build_web_url_uses_the_actual_non_loopback_bind_host():
    from entry.web_launch_runtime import build_web_url

    assert build_web_url("192.168.1.25", 8443, "https") == "https://192.168.1.25:8443"
    assert build_web_url("::1", 8000, "http") == "http://[::1]:8000"
    assert build_web_url("0.0.0.0", 8000, "http") == "http://localhost:8000"


def test_remote_access_token_is_persisted_and_appended_to_bootstrap_url(tmp_path):
    from entry.web_launch_runtime import build_access_url, resolve_web_access_token

    token_file = Path(tmp_path, "web-access-token")
    generated = "generated-access-token-with-enough-entropy"

    assert resolve_web_access_token(
        "127.0.0.1",
        token_file=token_file,
        token_factory=lambda: generated,
    ) is None
    assert not token_file.exists()

    token = resolve_web_access_token(
        "0.0.0.0",
        token_file=token_file,
        token_factory=lambda: generated,
    )
    assert token == generated
    assert token_file.read_text(encoding="utf-8").strip() == generated
    assert resolve_web_access_token(
        "0.0.0.0",
        token_file=token_file,
        token_factory=lambda: "must-not-replace-existing-token",
    ) == generated
    assert build_access_url("https://localhost:8000", token) == (
        "https://localhost:8000/?access_token=generated-access-token-with-enough-entropy"
    )


def test_access_token_reader_waits_for_concurrent_creator_to_finish(tmp_path):
    from entry.web_launch_runtime import resolve_web_access_token

    token_file = Path(tmp_path, "web-access-token")
    token_file.touch()
    generated = "concurrent-access-token-with-enough-entropy"

    with patch.object(Path, "read_text", side_effect=["", "partial", generated]), patch(
        "entry.web_launch_runtime.time.sleep"
    ) as sleep:
        token = resolve_web_access_token("0.0.0.0", token_file=token_file)

    assert token == generated
    sleep.assert_called()


def test_resolve_existing_web_url_only_accepts_matching_ucrawl_instance():
    from entry.web_launch_runtime import resolve_existing_web_url

    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            return json.dumps(self._payload).encode("utf-8")

    def accepted(*_args, **_kwargs):
        return _Response({"status": "ok", "version": "3.6.17"})

    def rejected(*_args, **_kwargs):
        return _Response({"status": "ok", "version": "3.6.16"})

    assert resolve_existing_web_url(
        "127.0.0.1",
        8000,
        "http",
        expected_version="3.6.17",
        urlopen_func=accepted,
    ) == "http://localhost:8000"
    assert resolve_existing_web_url(
        "127.0.0.1",
        8000,
        "http",
        expected_version="3.6.17",
        urlopen_func=rejected,
    ) is None


def test_resolve_existing_https_url_verifies_the_configured_certificate():
    from entry.web_launch_runtime import resolve_existing_web_url

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            return b'{"status":"ok","version":"3.6.17"}'

    seen_kwargs = {}

    def opener(_request, **kwargs):
        seen_kwargs.update(kwargs)
        return _Response()

    verified_context = object()
    with patch("entry.web_launch_runtime.ssl.create_default_context", return_value=verified_context) as create_context:
        result = resolve_existing_web_url(
            "127.0.0.1",
            8443,
            "https",
            ssl_certfile="server-cert.pem",
            expected_version="3.6.17",
            urlopen_func=opener,
        )

    assert result == "https://localhost:8443"
    create_context.assert_called_once_with(cafile="server-cert.pem")
    assert seen_kwargs["context"] is verified_context


def test_web_entry_reuses_matching_instance_before_creating_qt_or_uvicorn():
    from entry import web_entry

    stderr = io.StringIO()
    browser_open = Mock()
    with patch.object(web_entry, "_is_port_in_use", return_value=True), patch(
        "entry.web_launch_runtime.resolve_existing_web_url",
        return_value="http://localhost:8000",
    ), patch.object(web_entry.webbrowser, "open", browser_open), patch.object(web_entry.sys, "stderr", stderr):
        result = web_entry.main(["--no-qt", "--port", "8000"])

    assert result == 0
    browser_open.assert_called_once_with("http://localhost:8000")
    assert "直接复用现有实例" in stderr.getvalue()


def test_web_entry_does_not_probe_remote_occupied_port_with_access_secret():
    from fastapi import FastAPI
    from entry import web_entry

    class _Server:
        def __init__(self, config):
            self.app = config.app

        async def serve(self):
            async with self.app.router.lifespan_context(self.app):
                pass

    fake_uvicorn = Mock()
    fake_uvicorn.Config.side_effect = lambda app, **_kwargs: Mock(app=app)
    fake_uvicorn.Server.side_effect = _Server
    stderr = io.StringIO()
    access_token = "remote-access-token-with-enough-entropy"

    with (
        patch.object(web_entry, "_validate_transport_security", return_value="https"),
        patch.object(web_entry, "_is_port_in_use", return_value=True),
        patch.object(web_entry, "_find_available_port", return_value=8001),
        patch("entry.web_launch_runtime.resolve_web_access_token", return_value=access_token),
        patch("entry.web_launch_runtime.resolve_existing_web_url") as probe,
        patch("app.web.server.create_app", side_effect=lambda *, lifespan, access_token=None: FastAPI(lifespan=lifespan)),
        patch.dict("sys.modules", {"uvicorn": fake_uvicorn}),
        patch.object(web_entry.signal, "signal"),
        patch.object(web_entry.sys, "stderr", stderr),
    ):
        result = web_entry.main(
            ["--no-qt", "--no-browser", "--host", "0.0.0.0", "--port", "8000"]
        )

    assert result == 0
    probe.assert_not_called()
    assert access_token not in stderr.getvalue()
    assert "https://localhost:8001" in stderr.getvalue()
