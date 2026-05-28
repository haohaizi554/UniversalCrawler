"""包初始化模块，为 `app/core/lib/douyin/link` 提供统一导出或包级说明。"""

# app/core/lib/douyin/link/__init__.py
from .extractor import Extractor, ExtractorTikTok
from .requester import Requester

__all__ = [
    "Extractor",
    "ExtractorTikTok",
    "Requester",
]