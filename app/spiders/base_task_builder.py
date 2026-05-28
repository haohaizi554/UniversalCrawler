"""爬虫实现模块，负责 `app/spiders/base_task_builder.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations

from typing import Any


class BaseTaskBuilder:
    """平台任务装配公共基类。

    各平台仍可保留自己的高层装配方法，但底层下载 meta 统一走这里，
    这样 trace_id / referer / ua / proxy / strategy 等字段的结构会更一致。
    """

    def build_download_meta(
        self,
        *,
        trace_id: str,
        referer: str | None = None,
        user_agent: str | None = None,
        proxy: str | None = None,
        download_strategy: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """构建 `download_meta` 对应的结果、参数或对象，供 `BaseTaskBuilder` 使用。"""
        payload = {
            "trace_id": trace_id,
            "referer": referer,
            "ua": user_agent,
            "proxy": proxy,
            "download_strategy": download_strategy,
            **extra,
        }
        return {
            key: value
            for key, value in payload.items()
            if value not in (None, "", [], {})
        }
