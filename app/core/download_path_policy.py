"""分发器与下载线程共用的纯路径策略。"""

from __future__ import annotations

import os

from app.models import VideoItem
from app.utils import sanitize_filename


def resolve_task_save_directory(video: VideoItem, save_directory: str) -> str:
    """只计算任务目标目录，不在此阶段创建或修改文件系统。"""
    meta = video.meta if isinstance(getattr(video, "meta", None), dict) else {}
    content_type = str(meta.get("content_type") or "")
    raw_folder_name = str(meta.get("folder_name") or "").strip()
    folder_name = sanitize_filename(raw_folder_name) if raw_folder_name else ""
    uses_subdirectory = bool(
        meta.get("is_gallery")
        or content_type == "gallery"
        or meta.get("is_mix")
        or meta.get("use_subdir")
    )
    if folder_name and uses_subdirectory:
        return os.path.join(str(save_directory), folder_name)
    return str(save_directory)
