"""爬虫实现模块，负责 `app/spiders/kuaishou/task_builder.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations

from app.spiders.base_task_builder import BaseTaskBuilder


class KuaishouTaskBuilder(BaseTaskBuilder):
    """负责将解析结果转换为 `KuaishouTaskBuilder` 对应的任务或数据对象。"""
    def build_download_meta(self, trace_id: str, referer: str, stream_url: str) -> dict:
        """构建 `download_meta` 对应的结果、参数或对象，供 `KuaishouTaskBuilder` 使用。"""
        return super().build_download_meta(
            trace_id=trace_id,
            referer=referer,
            download_strategy="m3u8" if ".m3u8" in stream_url else "http",
        )
