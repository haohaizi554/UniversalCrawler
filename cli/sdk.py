"""Python SDK 入口：让用户可以 `from ucrawl import UcrawlSDK` 直接调用。

设计目标：
- 一次实例化，多次 search
- 支持上下文管理器 (with UcrawlSDK() as sdk:)
- 自动管理 QApplication 单例
- 复用 CLIRunner
- 与 GUI 默认配置完全一致

使用示例：
    >>> from ucrawl import UcrawlSDK
    >>>
    >>> # 1. 简单搜索
    >>> sdk = UcrawlSDK(save_dir="downloads")
    >>> result = sdk.search("douyin", "测试关键词", max_items=20)
    >>> for item in result["items"]:
    ...     print(item["title"], item["url"])
    >>>
    >>> # 2. 用规则选择器
    >>> from ucrawl import RuleSelection
    >>> sel = RuleSelection(select="0,2,5")  # 只选 0/2/5
    >>> result = sdk.search("missav", "ABC-123", selection=sel)
    >>>
    >>> # 3. 批量 (合集场景) 用 PipeSelection 预加载多次选择
    >>> from ucrawl import PipeSelection
    >>> sel = PipeSelection(preloaded_choices=[[0, 1], [2, 3]])  # 第一次选 0,1; 第二次选 2,3
    >>> result = sdk.search("bilibili", "合集BVxxx", selection=sel)
"""

from __future__ import annotations

import os
import sys
from typing import Any

# 必须在导入 Qt 之前设置
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# 暴露给用户的快捷导入
from cli.runner import CLIRunner, run_search as _run_search
from cli.selection import (
    SelectionStrategy,
    RuleSelection,
    InteractiveTTYSelection,
    PipeSelection,
    AutoSelection,
)

# 与 GUI 对齐的默认值
DEFAULT_CONFIG = {
    "douyin": {"max_items": 20, "timeout": 10},
    "bilibili": {"max_pages": 1},
    "kuaishou": {"max_items": 20},
    "missav": {
        "individual_only": False,
        "priority": "中文字幕优先",
        "proxy": "http://127.0.0.1:7890"
    }
}


def build_missav_proxy_url(proxy_str: str) -> str:
    """与 GUI `build_missav_proxy_url` 完全一致的转换逻辑。"""
    normalized = proxy_str.strip()
    if normalized == "Clash (7890)":
        return "http://127.0.0.1:7890"
    if normalized == "v2rayN (10809)":
        return "http://127.0.0.1:10809"
    if ":" in normalized:
        return normalized if normalized.startswith("http") else f"http://{normalized}"
    return "http://127.0.0.1:7890"


class UcrawlSDK:
    """UCrawl Python SDK。

    Attributes:
        save_dir: 默认保存目录
        verbose: 是否输出 spider 日志
    """

    PLATFORMS = ("douyin", "bilibili", "kuaishou", "missav")

    def __init__(
        self,
        save_dir: str = "downloads",
        verbose: bool = False,
        config: dict | None = None,
    ):
        """初始化 SDK。

        Args:
            save_dir: 默认保存目录
            verbose: 是否输出 spider 日志到 stderr (默认 False)
            config: 全局默认配置 (会被 search() 的 config 参数覆盖)
        """
        self.save_dir = save_dir
        self.verbose = verbose
        self.default_config = dict(config or {})
        self._qt_app = None

    def __enter__(self) -> "UcrawlSDK":
        self._ensure_qt()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _ensure_qt(self):
        """确保 QApplication 已创建。"""
        if self._qt_app is None:
            from PyQt6.QtWidgets import QApplication
            self._qt_app = QApplication.instance()
            if self._qt_app is None:
                self._qt_app = QApplication(sys.argv)
                self._qt_app.setQuitOnLastWindowClosed(False)

    def close(self):
        """清理资源。"""
        if self._qt_app is not None:
            try:
                self._qt_app.quit()
            except Exception:
                pass
            self._qt_app = None

    def search(
        self,
        source: str,
        keyword: str,
        save_dir: str | None = None,
        selection: SelectionStrategy | str | list[int] | None = None,
        timeout: float | None = None,
        download: bool = True,
        **config,
    ) -> dict[str, Any]:
        """执行一次搜索并返回结果。

        Args:
            source: 平台 ID (douyin/bilibili/kuaishou/missav)
            keyword: 搜索关键词 / 链接 / 用户 ID
            save_dir: 本次调用的保存目录 (None=使用 SDK 默认值)
            selection: 二次选择策略
                - None → AutoSelection (有 TTY 交互，无 TTY 管道，否则全选)
                - "all" → 全选
                - "first" → 只选第一个
                - "last" → 只选最后一个
                - list[int] → 指定索引 (如 [0, 2, 5])
                - SelectionStrategy 实例 → 完整控制
            timeout: 超时秒数 (None=无限)
            download: 是否触发下载 (True=与 GUI 一致自动下载, False=只收集不下载)
            **config: 平台特定参数

                douyin:
                    max_items (int): 最大视频数 (默认 20)
                    timeout (int): HTTP 超时秒 (默认 10)

                bilibili:
                    max_pages (int): 翻页数 (默认 1)
                    max_items (int): 最大视频数 (默认 30)

                kuaishou:
                    max_items (int): 最大视频数 (默认 20)

                missav:
                    individual_only (bool): 只看单体作品 (False=默认)
                    priority (str): "中文字幕优先" / "无码流出优先"
                    proxy (str): 代理 URL (默认 "http://127.0.0.1:7890")

        Returns:
            dict: 详细结果 (见 CLIRunner.run() 的返回结构)

        Example:
            >>> sdk = UcrawlSDK(save_dir="downloads")
            >>> result = sdk.search("douyin", "测试", max_items=10)
            >>> print(f"找到 {len(result['items'])} 个项目")
            >>>
            >>> # 合集场景用预加载
            >>> from ucrawl import PipeSelection
            >>> sel = PipeSelection(preloaded_choices=[[0], [1, 2]])
            >>> result = sdk.search("bilibili", "BVxxxx", selection=sel)
        """
        self._ensure_qt()

        # 把 selection 转换为 Strategy
        strategy = self._resolve_selection(selection)

        # 合并 config (平台默认 + 全局默认 + 本次)
        merged_config = dict(DEFAULT_CONFIG.get(source, {}))
        merged_config.update(self.default_config)
        merged_config.update(config)
        if save_dir is not None:
            merged_config["save_dir"] = save_dir
        # MissAV 代理转换（与 GUI 一致）
        if source == "missav" and "proxy" in merged_config and merged_config["proxy"] is not None:
            merged_config["proxy"] = build_missav_proxy_url(merged_config["proxy"])

        runner = CLIRunner(
            source=source,
            keyword=keyword,
            save_dir=save_dir or self.save_dir,
            selection_strategy=strategy,
            config=merged_config,
            verbose=self.verbose,
            log_to_stderr=self.verbose,
            timeout=timeout,
            download=download,
        )
        return runner.run()

    def _resolve_selection(self, selection) -> SelectionStrategy:
        """把 selection 参数解析为 Strategy 实例。"""
        if selection is None:
            return AutoSelection()
        if isinstance(selection, SelectionStrategy):
            return selection
        if isinstance(selection, str):
            if selection == "all":
                return RuleSelection(all_items=True)
            if selection == "first":
                return RuleSelection(first=True)
            if selection == "last":
                return RuleSelection(last=True)
            if selection == "interactive":
                return InteractiveTTYSelection()
            if selection == "pipe":
                return PipeSelection()
            # 兼容 "0,2,5" 字符串
            return RuleSelection(select=selection)
        if isinstance(selection, (list, tuple)):
            return PipeSelection(preloaded_choices=[list(selection)])
        if isinstance(selection, dict):
            return RuleSelection(**selection)
        raise TypeError(f"无法解析 selection 参数: {type(selection).__name__}")

    def list_platforms(self) -> list[dict]:
        """列出所有可用平台及其元信息。"""
        from app.core.plugin_registry import registry
        result = []
        for p in registry.get_all_plugins():
            info = {
                "id": p.id,
                "name": p.name,
            }
            # 可选字段
            if hasattr(p, "description"):
                info["description"] = p.description
            if hasattr(p, "settings_builder") and p.settings_builder is not None:
                try:
                    info["settings"] = p.settings_builder.field_defs
                except (AttributeError, TypeError):
                    pass
            result.append(info)
        return result

    def scan_directory(self, directory: str, scan_limit: int = 1000) -> dict:
        """扫描本地目录，返回文件清单。

        Args:
            directory: 要扫描的目录
            scan_limit: 最多扫描多少个文件

        Returns:
            dict: {"status": "ok", "items": [...], "total_count": N, ...}
        """
        from app.config import cfg
        from app.services.file_service import MediaLibraryService, ScanResult

        # MediaLibraryService 接受 video_extensions 和 image_extensions
        video_exts = (
            ".mp4", ".mov", ".mkv", ".flv", ".avi", ".webm", ".m3u8", ".ts",
        )
        image_exts = (
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
        )
        service = MediaLibraryService(video_exts, image_exts)

        try:
            result = service.scan_directory(directory, max_scan_count=scan_limit)
            items = []
            for item in result.items:
                d = item.to_dict()
                d["url"] = ""
                d["source"] = ""
                d["progress"] = 100
                d["status"] = "✅ 本地"
                items.append(d)
            return {
                "status": "ok",
                "directory": directory,
                "items": items,
                "total_count": result.total_count,
                "video_count": result.video_count,
                "image_count": result.image_count,
                "truncated": result.truncated,
                "original_count": result.original_count,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ========== 便捷函数 (函数式 API) ==========

def search(
    source: str,
    keyword: str,
    save_dir: str = "downloads",
    selection: SelectionStrategy | str | list[int] | None = None,
    **config,
) -> dict:
    """函数式 API：直接搜索，等价于 UcrawlSDK().search()。

    Example:
        >>> from ucrawl import search
        >>> result = search("douyin", "测试", max_items=10, save_dir="downloads")
    """
    sdk = UcrawlSDK(save_dir=save_dir)
    return sdk.search(source, keyword, save_dir=save_dir, selection=selection, **config)


def list_platforms() -> list[dict]:
    """列出所有可用平台。

    Example:
        >>> from ucrawl import list_platforms
        >>> for p in list_platforms():
        ...     print(p["id"], p["name"])
    """
    sdk = UcrawlSDK()
    return sdk.list_platforms()


def scan_directory(directory: str, scan_limit: int = 1000) -> dict:
    """扫描本地目录。

    Example:
        >>> from ucrawl import scan_directory
        >>> result = scan_directory("D:/downloads", scan_limit=500)
    """
    sdk = UcrawlSDK()
    return sdk.scan_directory(directory, scan_limit)
