from __future__ import annotations

from app.spiders.base_task_builder import BaseTaskBuilder


class MissAVTaskBuilder(BaseTaskBuilder):
    def build_download_meta(self, trace_id: str, referer: str, user_agent: str, proxy: str | None) -> dict:
        return super().build_download_meta(
            trace_id=trace_id,
            referer=referer,
            user_agent=user_agent,
            proxy=proxy,
        )

    def build_video_meta(self, trace_id: str, referer: str, user_agent: str, proxy: str | None) -> dict:
        """兼容旧调用点，逐步收敛到统一的 build_download_meta。"""
        return self.build_download_meta(trace_id, referer, user_agent, proxy)
