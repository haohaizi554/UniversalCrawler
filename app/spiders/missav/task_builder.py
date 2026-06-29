"""Task builder for MissAV download items."""

from __future__ import annotations

from app.spiders.base_task_builder import BaseTaskBuilder


class MissAVTaskBuilder(BaseTaskBuilder):
    """Build normalized metadata for MissAV HLS tasks."""

    def build_download_meta(
        self,
        trace_id: str,
        referer: str,
        user_agent: str,
        proxy: str | None,
        *,
        headers: dict | None = None,
        cookie: str | None = None,
        include_cookies: bool = False,
        use_browser_headers: bool = False,
        browser_storage_state: dict | None = None,
        playlist_cache: dict | None = None,
    ) -> dict:
        return super().build_download_meta(
            trace_id=trace_id,
            referer=referer,
            user_agent=user_agent,
            proxy=proxy,
            download_strategy="m3u8",
            content_type="video",
            media_label="video",
            m3u8_thread_count=16,
            headers=headers,
            cookie=cookie,
            missav_include_cookies=include_cookies,
            missav_use_browser_headers=use_browser_headers,
            browser_storage_state=browser_storage_state,
            playlist_cache=playlist_cache,
        )

    def build_video_meta(
        self,
        trace_id: str,
        referer: str,
        user_agent: str,
        proxy: str | None,
        *,
        headers: dict | None = None,
        cookie: str | None = None,
        include_cookies: bool = False,
        use_browser_headers: bool = False,
        browser_storage_state: dict | None = None,
        playlist_cache: dict | None = None,
    ) -> dict:
        return self.build_download_meta(
            trace_id,
            referer,
            user_agent,
            proxy,
            headers=headers,
            cookie=cookie,
            include_cookies=include_cookies,
            use_browser_headers=use_browser_headers,
            browser_storage_state=browser_storage_state,
            playlist_cache=playlist_cache,
        )
