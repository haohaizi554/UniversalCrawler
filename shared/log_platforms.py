"""Pure platform metadata used by log projections in every frontend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from shared.icon_contract import PLATFORM_ICON_FILES, platform_icon_file

BUILTIN_PLATFORM_ORDER = ("douyin", "bilibili", "kuaishou", "missav", "xiaohongshu")


@dataclass(frozen=True)
class PlatformUiMeta:
    id: str
    label: str
    icon_path: str | None = None
    emoji: str | None = None
    aliases: tuple[str, ...] = ()


def builtin_platform_metas(
    icon_path_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, PlatformUiMeta]:
    resolve = icon_path_resolver or (lambda _platform_id: None)
    return {
        "all": PlatformUiMeta("all", "全部", emoji="🌐"),
        "system": PlatformUiMeta(
            "system",
            "系统",
            emoji="⚙️",
            aliases=("系统", "system", "gui", "applicationcontroller"),
        ),
        "douyin": PlatformUiMeta(
            "douyin",
            "抖音",
            icon_path=resolve("douyin"),
            emoji="🎵",
            aliases=("抖音", "douyin", "dy_", "aweme", "douyinspider", "douyindownloader"),
        ),
        "bilibili": PlatformUiMeta(
            "bilibili",
            "Bilibili",
            icon_path=resolve("bilibili"),
            emoji="📺",
            aliases=(
                "Bilibili",
                "bilibili",
                "bili",
                "biliapi",
                "bilibilispider",
                "bilibilidownloader",
                "bv",
                "bvid",
            ),
        ),
        "kuaishou": PlatformUiMeta(
            "kuaishou",
            "快手",
            icon_path=resolve("kuaishou"),
            emoji="⚡",
            aliases=("快手", "kuaishou", "ks_", "kuaishouspider", "kuaishoudownloader"),
        ),
        "missav": PlatformUiMeta(
            "missav",
            "MissAV",
            icon_path=resolve("missav"),
            emoji="🎀",
            aliases=("MissAV", "missav", "missavspider", "missavdownloader", "surrit"),
        ),
        "xiaohongshu": PlatformUiMeta(
            "xiaohongshu",
            "小红书",
            icon_path=resolve("xiaohongshu"),
            emoji="📃",
            aliases=("小红书", "xiaohongshu", "xhs", "redbook", "xiaohongshuspider", "xiaohongshudownloader"),
        ),
    }


def platform_icon_file_for_id(platform_id: str, meta: PlatformUiMeta | None = None) -> str:
    del meta
    normalized = str(platform_id or "").lower()
    if normalized in {"", "system", "all"}:
        return ""
    if normalized not in PLATFORM_ICON_FILES:
        return ""
    return platform_icon_file(normalized)
