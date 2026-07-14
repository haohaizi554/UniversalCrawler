from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.downloaders.chunked import ChunkedDownloader
from app.exceptions import StreamDownloadError
from app.models import VideoItem


class ChunkedDownloaderIntegrityTests(unittest.TestCase):
    @staticmethod
    def _head_response(*, etag: str = '"v1"') -> Mock:
        response = Mock()
        response.headers = {
            "content-length": "10",
            "accept-ranges": "bytes",
            "etag": etag,
        }
        response.raise_for_status.return_value = None
        return response

    @staticmethod
    def _stream_response(chunks: list[bytes], *, failure: Exception | None = None) -> Mock:
        response = Mock()
        response.status_code = 206
        response.headers = {
            "content-length": "10",
            "content-range": "bytes 0-9/10",
        }
        response.raise_for_status.return_value = None
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        def iter_content(*, chunk_size: int = 0):
            del chunk_size
            yield from chunks
            if failure is not None:
                raise failure

        response.iter_content.side_effect = iter_content
        return response

    @staticmethod
    def _cfg_get(section: str, key: str, default=None):
        if (section, key) == ("download", "max_retries"):
            return 0
        if (section, key) == ("download", "resume_enabled"):
            return True
        if (section, key) == ("download", "max_concurrent"):
            return 8
        return default

    @patch("app.core.downloaders.chunked.time.sleep", return_value=None)
    @patch("app.core.downloaders.chunked.requests.get")
    @patch("app.core.downloaders.chunked.requests.head")
    @patch("app.core.downloaders.chunked.cfg.get")
    def test_unexpected_worker_exception_cannot_publish_partial_target(
        self,
        mocked_cfg_get,
        mocked_head,
        mocked_get,
        _mocked_sleep,
    ) -> None:
        mocked_cfg_get.side_effect = self._cfg_get
        mocked_head.return_value = self._head_response()
        mocked_get.return_value = self._stream_response([b"1234"], failure=TypeError("worker protocol bug"))
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "demo.mp4")
            with self.assertRaises(StreamDownloadError):
                ChunkedDownloader().download(item, str(target), lambda *_args, **_kwargs: None, lambda: False)

            self.assertFalse(target.exists())
            self.assertFalse(Path(f"{target}.merging").exists())

    @patch("app.core.downloaders.chunked.time.sleep", return_value=None)
    @patch("app.core.downloaders.chunked.requests.get")
    @patch("app.core.downloaders.chunked.requests.head")
    @patch("app.core.downloaders.chunked.cfg.get")
    def test_completed_part_without_matching_source_manifest_is_not_reused(
        self,
        mocked_cfg_get,
        mocked_head,
        mocked_get,
        _mocked_sleep,
    ) -> None:
        mocked_cfg_get.side_effect = self._cfg_get
        mocked_head.return_value = self._head_response(etag='"v2"')
        mocked_get.return_value = self._stream_response([b"fresh-data"])
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "demo.mp4")
            Path(temp_dir, ".demo.mp4.part0").write_bytes(b"stale-data")

            ChunkedDownloader().download(item, str(target), lambda *_args, **_kwargs: None, lambda: False)

            self.assertEqual(target.read_bytes(), b"fresh-data")
            self.assertFalse(Path(temp_dir, ".demo.mp4.parts.json").exists())

        mocked_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
