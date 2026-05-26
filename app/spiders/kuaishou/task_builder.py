from __future__ import annotations

from app.spiders.base_task_builder import BaseTaskBuilder


class KuaishouTaskBuilder(BaseTaskBuilder):
    def build_download_meta(self, trace_id: str, referer: str, stream_url: str) -> dict:
        return super().build_download_meta(
            trace_id=trace_id,
            referer=referer,
            download_strategy="m3u8" if ".m3u8" in stream_url else "http",
        )
