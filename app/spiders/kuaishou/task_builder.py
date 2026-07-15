"""快手下载任务装配，按流地址选择 HTTP 或 HLS 下载策略。"""

from __future__ import annotations

from app.spiders.base_task_builder import BaseTaskBuilder

class KuaishouTaskBuilder(BaseTaskBuilder):
    """保持快手 meta 与其他短视频平台一致，便于前端状态和日志复用。"""

    def build_download_meta(self, trace_id: str, referer: str, stream_url: str, user_agent: str | None = None) -> dict:
        """根据 URL 后缀选择下载策略；m3u8 交给 HLS 路径，其余走普通 HTTP。"""
        return super().build_download_meta(
            trace_id=trace_id,
            referer=referer,
            user_agent=user_agent,
            download_strategy="m3u8" if ".m3u8" in stream_url else "http",
            content_type="video",  # 统一视频类型，避免下载器按平台名称猜测资源类别。
            media_label="视频",  # 前端状态与日志统一使用中文媒体标签。
        )
