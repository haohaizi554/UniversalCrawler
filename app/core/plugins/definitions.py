"""内置平台的具体插件定义。

每个类都由 ``BasePlugin.__init_subclass__`` 自动注册，无需维护额外清单。
新增平台时只需实现一个 ``*Plugin`` 类，可放在本文件或同包独立模块中。
"""

from __future__ import annotations

from typing import Any

from .base import BasePlugin
from .metadata import (
    InteractiveChoice,
    InteractiveField,
    PlatformAuthSpec,
    PlatformInteractiveSpec,
)


ITEM_CHOICES = tuple(
    InteractiveChoice(label, value)
    for label, value in (
        ("1", 1),
        ("2", 2),
        ("5", 5),
        ("10", 10),
        ("20", 20),
        ("max (9999)", 9999),
    )
)
PAGE_CHOICES = tuple(
    InteractiveChoice(label, value)
    for label, value in (
        ("1", 1),
        ("2", 2),
        ("5", 5),
        ("10", 10),
        ("20", 20),
        ("max (500)", 500),
    )
)

class KuaishouPlugin(BasePlugin):
    id = "kuaishou"
    name = "快手"
    aliases = ("ks",)
    sort_order = 20
    interactive_spec = PlatformInteractiveSpec(
        input_label="快手主页链接、分享链接、快手号或关键词",
        examples=(
            "主页链接: https://www.kuaishou.com/profile/xxx",
            "分享链接: https://v.kuaishou.com/xxxxx/",
            "快手号: 直接输入纯数字快手号",
            "关键词: 先进入站内搜索，再从结果跳到主页继续扫描",
        ),
        empty_tip="优先使用主页或分享链接；关键词会先站内搜索再进入主页。",
        result_tip="快手允许在浏览器中手动登录，分享链接可解析单条作品。",
        fields=(
            InteractiveField(
                key="max_items",
                prompt="视频数量",
                summary_label="视频数",
                choices=ITEM_CHOICES,
            ),
        ),
        auth=PlatformAuthSpec(
            mode="cookie",
            config_key="kuaishou_cookie_file",
            default_file="ks_auth.json",
            cookie_names=("userId", "kuaishou.server.web_st"),
            login_url="https://www.kuaishou.com/",
            login_description="快手将打开浏览器，请手动登录。",
            summary="浏览器手动登录",
        ),
    )

    def get_search_placeholder(self) -> str:
        return "输入：快手主页链接、分享链接、快手号或关键词..."

    def get_spider_class(self):
        from app.spiders.kuaishou.spider import KuaishouSpider
        return KuaishouSpider

    def get_downloader_class(self):
        from app.core.downloaders.kuaishou import KuaishouDownloader
        return KuaishouDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {"max_items": 20, "timeout": 10}

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.kuaishou.com/",
        }

class MissAVPlugin(BasePlugin):
    id = "missav"
    name = "MissAV"
    aliases = ("miss",)
    sort_order = 30
    interactive_spec = PlatformInteractiveSpec(
        input_label="番号、演员名或 MissAV 链接",
        examples=(
            "番号: SSIS-001",
            "演员名: 三上悠亚",
            "列表/详情链接: https://missav.ai/...",
        ),
        empty_tip="先确认代理可用，再尝试番号或作品链接。",
        result_tip="MissAV 会扫描列表、筛选版本并嗅探 m3u8。",
        fields=(
            InteractiveField(
                key="individual_only",
                prompt="仅单体作品",
                summary_label="仅单体",
                choices=(
                    InteractiveChoice("否", False),
                    InteractiveChoice("是", True),
                ),
            ),
            InteractiveField(
                key="priority",
                prompt="排序偏好",
                summary_label="偏好",
                choices=(
                    InteractiveChoice(
                        "中文字幕优先",
                        "中文字幕优先",
                    ),
                    InteractiveChoice(
                        "无码流出优先",
                        "无码流出优先",
                    ),
                ),
            ),
            InteractiveField(
                key="proxy",
                prompt="代理",
                summary_label="代理",
                choices=(
                    InteractiveChoice(
                        "Clash (7890)",
                        "Clash (7890)",
                    ),
                    InteractiveChoice(
                        "v2rayN (10809)",
                        "v2rayN (10809)",
                    ),
                    InteractiveChoice(
                        "自定义",
                        None,
                        custom=True,
                    ),
                ),
                custom_prompt="代理地址",
            ),
        ),
        auth=PlatformAuthSpec(mode="none"),
    )

    def get_search_placeholder(self) -> str:
        return "输入：番号或老师名..."

    def get_spider_class(self):
        from app.spiders.missav.spider import MissAVSpider
        return MissAVSpider

    def get_downloader_class(self):
        from app.core.downloaders.missav import MissAVDownloader
        return MissAVDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {
            "individual_only": False,
            "priority": "中文字幕优先",
            "proxy": "http://127.0.0.1:7890",
        }

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://missav.ai/",
        }

class BilibiliPlugin(BasePlugin):
    id = "bilibili"
    name = "Bilibili"
    aliases = ("bili", "bl")
    sort_order = 40
    interactive_spec = PlatformInteractiveSpec(
        input_label="BV 号、UP 主页、合集链接或关键词",
        examples=(
            "BV 号: BV1xx411c7mD",
            "UP 主页: https://space.bilibili.com/123456",
            "视频链接: https://www.bilibili.com/video/BVxxxx",
        ),
        empty_tip="可直接输入 BV 号、UP 主页或视频链接，通常比模糊关键词稳定。",
        result_tip="B 站会先选择主项目，再按需展开分 P 或合集。",
        fields=(
            InteractiveField(
                key="max_pages",
                prompt="搜索页数",
                summary_label="页数",
                choices=PAGE_CHOICES,
            ),
        ),
        auth=PlatformAuthSpec(
            mode="cookie",
            config_key="bilibili_cookie_file",
            default_file="bili_auth.json",
            cookie_names=("SESSDATA",),
            login_url="https://www.bilibili.com/",
            login_description="B 站将打开浏览器，请扫码登录。",
            summary="浏览器扫码",
        ),
    )

    def get_search_placeholder(self) -> str:
        return "输入：BV号、UP主ID、合集链接、主页链接、视频链接、分享链接或关键词..."

    def get_spider_class(self):
        from app.spiders.bilibili.spider import BilibiliSpider
        return BilibiliSpider

    def get_downloader_class(self):
        from app.core.downloaders.bilibili import BilibiliDownloader
        return BilibiliDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {"max_pages": 1, "max_items": 9999, "timeout": 10, "api_workers": 8}

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.bilibili.com",
        }

class DouyinPlugin(BasePlugin):
    id = "douyin"
    name = "抖音"
    aliases = ("dy",)
    sort_order = 10
    interactive_spec = PlatformInteractiveSpec(
        input_label="主页链接、分享链接或合集链接",
        examples=(
            "主页链接: https://www.douyin.com/user/xxx",
            "分享链接: https://v.douyin.com/xxxxx/",
            "合集链接: 带 collection / mix / modal_id 的链接",
        ),
        empty_tip="优先尝试主页链接或分享链接；纯数字 UID 当前仍不支持。",
        result_tip="抖音会按统一采集流程扫码、采集、选择并入队下载。",
        fields=(
            InteractiveField(
                key="max_items",
                prompt="视频数量",
                summary_label="视频数",
                choices=ITEM_CHOICES,
            ),
        ),
        auth=PlatformAuthSpec(
            mode="cookie",
            config_key="douyin_cookie_file",
            default_file="dy_auth.json",
            cookie_names=("sessionid_ss",),
            login_url="https://www.douyin.com/",
            login_description="抖音将打开浏览器，请扫码登录。",
            summary="浏览器扫码",
        ),
    )

    def get_search_placeholder(self) -> str:
        return "输入：主页链接、分享链接或合集链接..."

    def get_spider_class(self):
        from app.spiders.douyin.spider import DouyinSpider
        return DouyinSpider

    def get_downloader_class(self):
        from app.core.downloaders.douyin import DouyinDownloader
        return DouyinDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {"max_items": 20, "timeout": 10}

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.douyin.com/",
        }

class XiaohongshuPlugin(BasePlugin):
    id = "xiaohongshu"
    name = "小红书"
    aliases = ("xhs",)
    sort_order = 15
    interactive_spec = PlatformInteractiveSpec(
        input_label="小红书关键词、笔记链接或作者主页链接",
        examples=(
            "关键词: 穿搭 / 探店 / 摄影",
            "笔记链接: https://www.xiaohongshu.com/explore/...",
            "作者主页: https://www.xiaohongshu.com/user/profile/...",
        ),
        empty_tip="优先使用完整笔记链接或作者主页链接；关键词模式会先搜索再选择。",
        result_tip="小红书会准备浏览器 Cookie，必要时请在页面中登录。",
        fields=(
            InteractiveField(
                key="max_items",
                prompt="笔记数量",
                summary_label="笔记数",
                choices=ITEM_CHOICES,
            ),
        ),
        auth=PlatformAuthSpec(
            mode="cookie",
            config_key="xiaohongshu_cookie_file",
            default_file="xhs_auth.json",
            cookie_names=("web_session", "a1"),
            login_url="https://www.xiaohongshu.com/",
            login_description="小红书将打开浏览器获取 Cookie，必要时请手动登录。",
            summary="浏览器 Cookie / 手动登录",
        ),
    )

    def get_search_placeholder(self) -> str:
        return "输入：关键词、分享链接、视频/笔记链接、主页链接，或小红书号..."

    def get_spider_class(self):
        from app.spiders.xiaohongshu.spider import XiaohongshuSpider
        return XiaohongshuSpider

    def get_downloader_class(self):
        from app.core.downloaders.xiaohongshu import XiaohongshuDownloader
        return XiaohongshuDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {
            "max_items": 20,
            "search_max_pages": 5,
            "timeout": 30,
            "request_interval": 1.5,
            "detail_request_interval": 0.5,
            "sort": "general",
            "note_type": 0,
        }

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.xiaohongshu.com/",
        }

def get_default_plugins() -> list[BasePlugin]:
    """返回按 ``sort_order`` 排序的内置插件实例。"""
    from .discovery import discover_builtin_plugins
    return discover_builtin_plugins()
