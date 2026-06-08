"""爬虫实现模块，负责 `app/spiders/missav/task_builder.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations

from app.spiders.base_task_builder import BaseTaskBuilder


class MissAVTaskBuilder(BaseTaskBuilder):
    """负责将解析结果转换为 `MissAVTaskBuilder` 对应的任务或数据对象。"""
    def build_download_meta(self, trace_id: str, referer: str, user_agent: str, proxy: str | None) -> dict:
        """构建 `download_meta` 对应的结果、参数或对象，供 `MissAVTaskBuilder` 使用。"""
        return super().build_download_meta(
            trace_id=trace_id,
            referer=referer,
            user_agent=user_agent,
            proxy=proxy,
            download_strategy="m3u8",  # 与 KuaishouTaskBuilder 对齐：MissAV 视频始终使用 m3u8 下载策略
            content_type="video",  # 与 DouyinParser/BilibiliSpider/KuaishouTaskBuilder 对齐：MissAV 视频始终为 video
            media_label="视频",  # 与 DouyinParser 对齐：GUI 日志使用
        )

    def build_video_meta(self, trace_id: str, referer: str, user_agent: str, proxy: str | None) -> dict:
        """兼容旧调用点，逐步收敛到统一的 build_download_meta。"""
        return self.build_download_meta(trace_id, referer, user_agent, proxy)
