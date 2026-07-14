"""Python SDK 入口：让用户可以 `from ucrawl import UcrawlSDK` 直接调用。

设计目标：
- 一次实例化，多次 search
- 支持上下文管理器 (with UcrawlSDK() as sdk:)
- 复用 CLIRunner
- 与 GUI 默认配置完全一致（从 cfg 持久化配置读取默认值）

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

from shared.cli_runner_runtime import CLIRunner
from shared.selection_base import SelectionStrategy, is_selection_strategy

# 保持 CLI/SDK 输出实时刷新，便于长任务反馈
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# 暴露给用户的快捷导入
from shared.runtime_options import (
    DEFAULT_CONFIG,  # noqa: F401 - retained as a public SDK compatibility export
    build_missav_proxy_url,
    compose_runtime_config,
    get_default_save_dir,
    get_platform_defaults,
    get_platform_download_defaults,
    infer_content_type,
    infer_content_type_from_url,
    merge_convenience_params,  # noqa: F401 - retained as a public SDK compatibility export
    validate_config_types,
    validate_direct_download_url,
)
from shared.selection_runtime import (
    AutoSelection,
    SelectionStrategyFactory,
)

def _discover_platform_ids() -> tuple[str, ...]:
    """Keep SDK platform enum aligned with the runtime plugin registry."""
    try:
        from app.core.plugin_registry import registry

        return tuple(plugin.id for plugin in registry.get_all_plugins())
    except Exception:
        return ("douyin", "bilibili", "kuaishou", "missav", "xiaohongshu")

class UcrawlSDK:
    """UCrawl Python SDK。

    Attributes:
        save_dir: 默认保存目录
        verbose: 是否输出 spider 日志
    """

    PLATFORMS = _discover_platform_ids()

    def __init__(
        self,
        save_dir: str | None = None,
        verbose: bool = False,
        config: dict | None = None,
    ):
        """初始化 SDK。

        Args:
            save_dir: 默认保存目录 (None=从 cfg 配置读取，与 GUI 对齐)
            verbose: 是否输出 spider 日志到 stderr (默认 False)
            config: 全局默认配置 (会被 search() 的 config 参数覆盖)
        """
        self.save_dir = save_dir or get_default_save_dir()
        # 与 search()/download_video() 对齐：校验 save_dir 类型
        if save_dir is not None and not isinstance(save_dir, str):
            raise TypeError("save_dir 必须是字符串或 None")
        self.verbose = verbose
        # 与 search() 对齐：校验 config 类型（必须在 dict() 转换之前，避免字符串被当作可迭代对象）
        if config is not None and not isinstance(config, dict):
            raise TypeError("config 必须是字典或 None")
        self.default_config = dict(config or {})

    def __enter__(self) -> "UcrawlSDK":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """清理 SDK 资源。

        当前 SDK/CLI 已完全不依赖 Qt 事件循环，因此 close() 仅保留幂等接口，
        便于兼容既有调用方和上下文管理器用法。
        """
        return None

    def _get_runner_class(self):
        """Return the runner class used by SDK search flows.

        The shared runtime defaults to the shared runner implementation. Host-
        specific public packages can override this hook to preserve patch seams
        without keeping another runner implementation outside ``shared/``.
        """
        return CLIRunner

    def search(
        self,
        source: str,
        keyword: str,
        save_dir: str | None = None,
        selection: SelectionStrategy | str | list[int] | None = None,
        timeout: float | None = None,
        download: bool = True,
        run_timeout: float | None = None,
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
                - dict → 与 REST API 对齐 (如 {"strategy": "all"}, {"strategy": "rule", "select": "0,2,5"})
                - SelectionStrategy 实例 → 完整控制
            timeout: 整体超时秒数 (None=无限)。已弃用，建议使用 run_timeout。
                注意：若需设置 spider HTTP 超时，请通过 config 传入 timeout 关键字，
                如 ``sdk.search(..., run_timeout=60, **{"timeout": 10})``。
            download: 是否触发下载 (True=与 GUI 一致自动下载, False=只收集不下载)
            run_timeout: 整体超时秒数 (None=无限)，与 CLI --run-timeout 对齐。
                优先级高于 timeout 参数。
            **config: 平台特定参数

                douyin:
                    max_items (int): 最大视频数 (默认从 cfg 读取，兜底 20)
                    timeout (int): HTTP 超时秒 (默认 10)

                bilibili:
                    max_pages (int): 翻页数 (默认从 cfg 读取，兜底 1)
                    max_items (int): 最大视频数 (兜底 30)

                kuaishou:
                    max_items (int): 最大视频数 (默认从 cfg 读取，兜底 20)

                missav:
                    individual_only (bool): 只看单体作品 (False=默认)
                    priority (str): "中文字幕优先" / "无码流出优先"
                    proxy (str): 代理 URL (默认从 cfg 读取)

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
        # 与 CLI argparse 和 REST API 对齐：校验 source 和 keyword
        if not isinstance(source, str) or not isinstance(keyword, str):
            raise TypeError("source 和 keyword 必须是字符串")
        # 与 GUI inp_search.text().strip() 对齐：去除前后空白
        keyword = keyword.strip()
        if not source or not keyword:
            raise ValueError("source 和 keyword 不能为空")
        # 与 CLI argparse choices 对齐：校验 source 是否为有效平台 ID
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            raise ValueError(f"无效平台: {source}。支持: {valid_ids}")

        # 与 CLI --run-timeout 对齐：run_timeout 优先，timeout 向后兼容
        effective_run_timeout = run_timeout if run_timeout is not None else timeout
        # 与 REST API 对齐：校验 timeout 类型
        if effective_run_timeout is not None and (
            isinstance(effective_run_timeout, bool)
            or not isinstance(effective_run_timeout, (int, float))
        ):
            raise TypeError("timeout/run_timeout 必须是数字或 None")
        # 与 REST API 对齐：校验 timeout 值
        if effective_run_timeout is not None and effective_run_timeout <= 0:
            raise ValueError("timeout/run_timeout 必须大于 0")
        # 与 REST API 对齐：校验 download 类型
        if not isinstance(download, bool):
            raise TypeError("download 必须是布尔值")
        # 与 REST API 对齐：校验 save_dir 类型
        if save_dir is not None and not isinstance(save_dir, str):
            raise TypeError("save_dir 必须是字符串或 None")
        # 与 CLI argparse type=int/str/bool 对齐：校验已知 config 参数类型
        self._validate_config(config)

        # 把 selection 转换为 Strategy
        strategy = self._resolve_selection(selection)

        # 合并 config (cfg 持久化默认 + 全局默认 + 本次)
        # 与 GUI read_*_run_options 对齐：优先使用 cfg 中的用户设置
        # 与 CLI _build_config 对齐：过滤 None 值，避免覆盖默认值
        # （CLI argparse 只在用户显式提供参数时才设置，不会用 None 覆盖默认）
        explicit_none_keys = {k for k, v in config.items() if v is None}
        merged_config = compose_runtime_config(
            source,
            base_config=self.default_config,
            user_config=config,
            convenience_body={},
            explicit_none_keys=explicit_none_keys,
            defaults_factory=get_platform_defaults,
            proxy_normalizer=build_missav_proxy_url,
        )

        runner = self._get_runner_class()(
            source=source,
            keyword=keyword,
            save_dir=save_dir or self.save_dir,
            selection_strategy=strategy,
            config=merged_config,
            verbose=self.verbose,
            log_to_stderr=self.verbose,
            timeout=effective_run_timeout,
            download=download,
        )
        return runner.run()

    def _validate_config(self, config: dict):
        """校验已知 config 参数类型，与 CLI argparse type 对齐。

        仅校验已知参数，未知参数透传给 spider（保持前向兼容）。
        委托给 shared.runtime_options.validate_config_types 统一实现，
        确保 CLI/SDK/REST API 三层校验逻辑完全一致。
        """
        err = validate_config_types(config)
        if err:
            # 从 "config.xxx 必须是xxx，收到 xxx" 格式中提取字段名和类型信息
            raise TypeError(err.replace("config.", "", 1))

    def _resolve_selection(self, selection) -> SelectionStrategy:
        """把 selection 参数解析为 Strategy 实例。

        与 REST API _build_selection_strategy 对齐：支持 {"strategy": "all"} 格式。
        """
        strategy = SelectionStrategyFactory.from_value(selection, default_strategy="auto")
        if is_selection_strategy(strategy):
            return strategy
        return AutoSelection()

    def download_video(
        self,
        url: str,
        source: str,
        title: str = "",
        save_dir: str | None = None,
        timeout: float = 300,
        verbose: bool = False,
        config: dict | None = None,
        progress_callback: Any = None,
        network_policy: str | None = None,
    ) -> dict[str, Any]:
        """直接下载指定 URL 的视频（与 CLI download 命令对齐）。

        Args:
            url: 视频 URL
            source: 平台 ID (douyin/bilibili/kuaishou/missav)
            title: 视频标题（默认使用 URL）
            save_dir: 保存目录 (None=使用 SDK 默认值)
            timeout: 下载超时秒数 (默认 300)
            verbose: 是否输出下载进度到 stderr (默认 False，与 CLI download 命令对齐)
            config: 平台特定配置 (None=使用平台默认值，与 REST API /api/download 的 config 对齐)
                missav: proxy (str) — 代理 URL
            progress_callback: 下载进度回调函数 (None=不回调，与 GUI DownloadManager 信号对齐)
                签名: callback(progress: int) -> None
                progress 范围 0-100，与 GUI/WebController task_progress 事件对齐
            network_policy: 内部网络策略。Web 公网直链入口传 ``"public"``，
                普通 CLI/SDK 调用保持 ``None`` 以支持本地资源。

        Returns:
            dict: {"status": "ok"/"error", "video_id": ..., "title": ..., "local_path": ..., ...}

        Example:
            >>> sdk = UcrawlSDK(save_dir="downloads")
            >>> result = sdk.download_video("https://...", "douyin", title="测试视频")
            >>> if result["status"] == "ok":
            ...     print(f"下载完成: {result['local_path']}")
            >>>
            >>> # 带进度回调（与 GUI 实时进度对齐）
            >>> def on_progress(pct):
            ...     print(f"进度: {pct}%")
            >>> result = sdk.download_video("https://...", "douyin", progress_callback=on_progress)
        """
        # 与 CLI download 命令对齐：校验参数
        if not isinstance(url, str) or not isinstance(source, str):
            raise TypeError("url 和 source 必须是字符串")
        if not isinstance(title, str):
            raise TypeError("title 必须是字符串")
        if save_dir is not None and not isinstance(save_dir, str):
            raise TypeError("save_dir 必须是字符串或 None")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout 必须是数字")
        if not isinstance(verbose, bool):
            raise TypeError("verbose 必须是布尔值")
        if config is not None and not isinstance(config, dict):
            raise TypeError("config 必须是字典或 None")
        url = url.strip()
        if not url or not source:
            raise ValueError("url 和 source 不能为空")
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if network_policy not in {None, "public"}:
            raise ValueError("network_policy 仅支持 public 或 None")
        if network_policy == "public":
            url_error = validate_direct_download_url(url)
            if url_error:
                raise ValueError(url_error)
        # 与 REST API /api/download 对齐：校验 source 是否为有效平台 ID
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            raise ValueError(f"无效平台: {source}。支持: {valid_ids}")
        # 与 search() 的 _validate_config 对齐：校验已知 config 参数类型
        if config:
            self._validate_config(config)

        from app.models.video_item import VideoItem
        from app.config import cfg
        from app.core.download_manager import DownloadManager
        import time

        # 与 CLI/SDK 对齐：title 为空时使用 URL
        effective_title = title or url

        item = VideoItem(
            url=url,
            title=effective_title,
            source=source,
            status="⏳ 等待中",
            progress=0,
        )

        # 与 search() 对齐：始终合并平台默认配置（GUI read_*_run_options 总是返回平台默认值）
        # 合并顺序：平台默认 → self.default_config → 本次 config（与 search() 完全一致）
        explicit_none_keys = {k for k, v in (config or {}).items() if v is None}
        merged = compose_runtime_config(
            source,
            base_config=self.default_config,
            user_config=config or {},
            convenience_body={},
            explicit_none_keys=explicit_none_keys,
            defaults_factory=get_platform_defaults,
            proxy_normalizer=build_missav_proxy_url,
        )

        # 与 GUI spider build_download_meta 对齐：设置平台默认 ua/referer
        # GUI spider 在 emit_video 时通过 build_download_meta 设置平台特定的 ua、referer，
        # SDK download_video 不经过 spider，需要手动设置这些默认值，
        # 确保下载器能正确构建 HTTP 请求头（如 BilibiliDownloader 需要 Referer 验证）
        platform_defaults = get_platform_download_defaults(source)
        for key, val in platform_defaults.items():
            # 用户 config 优先级高于平台默认值（与 GUI spider 行为一致：
            # spider 的 build_download_meta 也会被用户 config 覆盖）
            if key not in merged:
                merged[key] = val

        # 与 GUI spider 结果对齐：下载前从 URL 推断 content_type
        # GUI spider 在创建 VideoItem 时就设置 content_type（如 "video"/"gallery"/"image"），
        # SDK download_video 不经过 spider，需要从 URL 推断，
        # 以便 DownloadWorker._infer_extension 能正确推断文件扩展名
        if "content_type" not in merged or not merged["content_type"]:
            url_content_type = infer_content_type_from_url(url)
            if url_content_type:
                merged["content_type"] = url_content_type

        # 与 GUI spider build_download_meta 对齐：设置 trace_id
        # GUI spider 在 emit_video 时通过 build_download_meta 始终设置 trace_id，
        # DownloadWorker._trace_id() 依赖此字段做日志关联。
        # SDK download_video 不经过 spider，需要自动生成 trace_id，
        # 格式与 GUI spider 对齐：{source_prefix}-dl-{uuid8}
        import uuid as _uuid
        _source_prefix = {"douyin": "dy", "bilibili": "bili", "kuaishou": "ks", "missav": "miss"}.get(source, source)
        item.meta["trace_id"] = f"{_source_prefix}-dl-{_uuid.uuid4().hex[:8]}"
        if network_policy:
            # Web 直链入口使用该内部标记，下载器据此逐跳校验重定向；
            # 普通 CLI/SDK 调用保持原有的本地资源访问能力。
            item.meta["_network_policy"] = network_policy

        # 所有平台特定配置写入 meta（与 GUI spider meta 对齐）
        # 与 GUI spider 结果对齐：content_type 让 DownloadWorker 可正确推断文件扩展名
        # cookie 让下载器可从 item.meta 读取（kuaishou.py/douyin.py/bilibili.py 读取 cookie/cookies）
        # proxy 让下载器可从 item.meta 读取（missav 代理等场景）
        # download_strategy 让下载器可选择下载策略（与 GUI spider build_download_meta 对齐）
        # audio_url/bvid/cid 让 BilibiliDownloader 可处理 DASH 格式音视频分离下载
        # aweme_id 让 DouyinDownloader 可关联抖音视频 ID
        # file_name/preferred_filename 让 DownloadWorker 可使用指定文件名
        # is_gallery/is_mix 让 DownloadWorker 可正确处理图集/合集路径
        # images_data 让 DouyinDownloader 可下载图集（与 GUI spider DouyinTaskBuilder.build_items 对齐）
        # size_mb 让 BaseDownloader 可选择分块下载策略（与 GUI spider 设置对齐）
        # media_label 让日志可显示媒体类型标签（与 GUI spider build_download_meta 对齐）
        for key in (
            "referer", "ua", "content_type", "cookie", "cookies", "proxy",
            "download_strategy", "folder_name", "use_subdir",
            "audio_url", "aweme_id", "bvid", "cid",
            "file_name", "preferred_filename", "is_gallery", "is_mix",
            "images_data", "size_mb", "media_label",
            # 与 GUI spider DouyinParser 和下载器对齐的额外字段
            "duration",        # 视频时长秒数（ChunkedDownloader/FFmpegDownloader 读取，与 GUI spider DouyinParser 对齐）
            "mix_title",       # 合集标题（与 GUI spider DouyinSpider._process_mix 对齐）
            "create_time",     # 创建时间（与 GUI spider DouyinParser 对齐）
            "author",          # 作者名（与 GUI spider DouyinParser 对齐，用作 folder_name）
            "has_live_photo",  # 是否包含实况照片（与 GUI spider DouyinParser 对齐）
        ):
            if key in merged:
                item.meta[key] = merged[key]

        save_dir = save_dir or self.save_dir
        dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))

        # 与 search() 对齐：记录开始时间，返回 elapsed 字段
        start_time = time.time()

        # 与 CLI download 命令对齐：连接下载信号
        result_holder = {"status": "pending", "error": None}
        stop_summary = None

        def on_started(vid):
            if item.id == vid:
                item.status = "⏳ 下载中..."
                item.progress = 0
                if verbose:
                    sys.stderr.write(f"⏳ 开始下载: {item.title}\n")
                    sys.stderr.flush()
                # 与 GUI DownloadManager task_started 信号对齐：通过回调通知调用方
                if progress_callback:
                    try:
                        progress_callback(0)
                    except Exception:
                        pass

        def on_progress(vid, pct):
            if item.id == vid:
                item.progress = pct
                if verbose:
                    sys.stderr.write(f"\r⏳ 下载进度: {pct}%")
                    sys.stderr.flush()
                    if pct >= 100:
                        sys.stderr.write("\n")
                # 与 GUI DownloadManager task_progress 信号对齐：通过回调通知调用方
                if progress_callback:
                    try:
                        progress_callback(pct)
                    except Exception:
                        pass

        def on_finished(vid):
            if item.id == vid:
                item.status = "✅ 完成"
                item.progress = 100
                result_holder["status"] = "ok"
                if verbose:
                    sys.stderr.write(f"✅ 下载完成: {item.title}\n")
                    sys.stderr.flush()

        def on_error(vid, error):
            if item.id == vid:
                item.status = "❌ 失败"
                # 防御：不覆盖已设置的 timeout 状态（dl_manager.stop_all() 可能触发
                # on_error 回调，此时 result_holder["status"] 可能已被设为 "timeout"）
                if result_holder["status"] != "timeout":
                    item.meta["download_error"] = error
                    result_holder["status"] = "error"
                else:
                    item.meta.setdefault("shutdown_error", error)
                result_holder["error"] = error
                if verbose:
                    sys.stderr.write(f"❌ 下载失败 [{item.title}]: {error}\n")
                    sys.stderr.flush()

        dl_manager.task_started.connect(on_started)
        dl_manager.task_progress.connect(on_progress)
        dl_manager.task_finished.connect(on_finished)
        dl_manager.task_error.connect(on_error)

        dl_manager.add_task(item, save_dir)

        try:
            # 等待下载完成（与 CLI _wait_download 对齐）
            deadline = time.time() + timeout
            timed_out = False
            while time.time() < deadline:
                counter = getattr(dl_manager, "pending_work_counts", None)
                counts = counter() if callable(counter) else None
                if isinstance(counts, (tuple, list)) and len(counts) == 2:
                    active, queued = counts
                else:
                    active = len(getattr(dl_manager, "workers", []))
                    queued = dl_manager.queue.qsize()
                if active == 0 and queued == 0:
                    break
                time.sleep(0.5)
            else:
                timed_out = True

            # 超时检测：与 GUI（无超时）不同，CLI/SDK 有超时机制，需明确标记
            # 与 CLIRunner.run() 对齐：超时返回 "timeout" 而非 "error"，让调用方可区分超时与其他错误
            if timed_out and result_holder["status"] == "pending":
                item.status = "❌ 超时"
                item.meta["download_error"] = f"下载超时 ({timeout}s)"
                result_holder["status"] = "timeout"
                result_holder["error"] = f"下载超时 ({timeout}s)"
        finally:
            # 与 GUI shutdown 对齐：无论成功/失败/异常，都清理 DownloadManager 资源
            stop_summary = dl_manager.stop_all()

        shutdown = {
            "queued_tasks_cleared": 0,
            "workers_requested": 0,
            "unfinished_workers": [],
            "all_workers_stopped": True,
            "dispatcher_stopped": True,
        }
        if isinstance(stop_summary, dict):
            shutdown.update(
                {
                    "queued_tasks_cleared": int(stop_summary.get("queued_tasks_cleared", 0) or 0),
                    "workers_requested": int(stop_summary.get("workers_requested", 0) or 0),
                    "unfinished_workers": [
                        str(worker_id)
                        for worker_id in (stop_summary.get("unfinished_workers") or [])
                    ],
                    "all_workers_stopped": bool(stop_summary.get("all_workers_stopped", True)),
                    "dispatcher_stopped": bool(stop_summary.get("dispatcher_stopped", True)),
                }
            )

        # 与 search() 对齐：计算耗时
        elapsed = round(time.time() - start_time, 2)

        # 与 GUI spider 结果对齐：直接下载不经过 spider，根据文件扩展名推断 content_type
        detected_content_type = item.meta.get("content_type", "") if item.meta else ""
        if not detected_content_type and item.local_path:
            detected_content_type = infer_content_type(item.local_path)
            # 同步到 item.meta，确保 to_dict() 也包含此字段
            if detected_content_type and item.meta is not None:
                item.meta["content_type"] = detected_content_type

        if result_holder["status"] == "ok":
            return {
                "status": "ok",
                "video_id": item.id,
                "url": url,
                "source": source,
                "local_path": item.local_path,
                "title": item.title,
                "save_dir": save_dir,
                # 与 search() 返回的 item.to_dict() 对齐：包含 content_type 和 meta
                "content_type": detected_content_type,
                "meta": dict(item.meta) if item.meta else {},
                "shutdown": shutdown,
                # 与 search() 返回结构对齐：包含 elapsed 字段
                "elapsed": elapsed,
            }
        else:
            error_msg = item.meta.get("download_error", item.status)
            if not shutdown["all_workers_stopped"] or not shutdown["dispatcher_stopped"]:
                error_msg = f"{error_msg}；后台任务仍在停止中"
            # 与 CLIRunner.run() 对齐：超时返回 "timeout"，其他错误返回 "error"
            result_status = result_holder["status"]
            return {
                "status": result_status,
                "video_id": item.id,
                "url": url,
                "source": source,
                "title": item.title,
                "error": error_msg,
                "save_dir": save_dir,
                # 与成功结果对齐：始终包含 local_path（即使为空字符串）
                "local_path": item.local_path or "",
                # 与 search() 返回的 item.to_dict() 对齐：包含 content_type 和 meta
                "content_type": detected_content_type,
                "meta": dict(item.meta) if item.meta else {},
                "shutdown": shutdown,
                # 与 search() 返回结构对齐：包含 elapsed 字段
                "elapsed": elapsed,
            }

    def list_platforms(self) -> list[dict]:
        """列出所有可用平台及其元信息。"""
        from app.core.plugin_registry import registry
        result = []
        for p in registry.get_all_plugins():
            info = {
                "id": p.id,
                "name": p.name,
                "search_placeholder": p.get_search_placeholder(),
            }
            # 可选字段
            if hasattr(p, "description") and p.description:
                info["description"] = p.description
            if hasattr(p, "settings_builder") and p.settings_builder is not None:
                try:
                    info["settings"] = p.settings_builder.field_defs
                except (AttributeError, TypeError):
                    pass
            result.append(info)
        return result

    def scan_directory(self, directory: str, scan_limit: int | None = None) -> dict:
        """扫描本地目录，返回文件清单。

        Args:
            directory: 要扫描的目录
            scan_limit: 最多扫描多少个文件 (None=从配置读取, 与 GUI/Web 一致)

        Returns:
            dict: {"status": "ok", "items": [...], "total_count": N, "message": "...", ...}
        """
        # 与 search()/download_video() 对齐：参数校验抛异常，而非返回 error dict
        if not isinstance(directory, str):
            raise TypeError("directory 必须是字符串")
        if not directory:
            raise ValueError("directory 不能为空")
        if scan_limit is not None and (isinstance(scan_limit, bool) or not isinstance(scan_limit, int)):
            raise TypeError("scan_limit 必须是整数或 None")
        # 与 REST API /api/scan 对齐：scan_limit 必须大于 0
        if scan_limit is not None and scan_limit <= 0:
            raise ValueError("scan_limit 必须大于 0")

        from app.config import cfg
        from app.services.file_service import MediaLibraryService

        # 与 GUI/WebController 对齐：scan_limit 从配置读取
        if scan_limit is None:
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
            try:
                scan_limit = int(scan_limit)
            except (ValueError, TypeError):
                scan_limit = 1000

        # MediaLibraryService 接受 video_extensions 和 image_extensions
        # 与 GUI/WebController 扩展名列表完全一致
        video_exts = (
            ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm",
            ".m3u8", ".ts",
        )
        image_exts = (
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
        )
        service = MediaLibraryService(video_exts, image_exts)

        try:
            result = service.scan_directory(directory, max_scan_count=scan_limit)
            items = []
            for item in result.items:
                # 与 REST API /api/scan 完全一致：先设状态再序列化
                item.status = "✅ 本地"
                item.progress = 100
                items.append(item.to_dict())

            # 与 REST API /api/scan 和 /api/dir/change 对齐：包含 message 字段
            msg = f"已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
            if result.truncated:
                msg = f"文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
            elif result.total_count == 0:
                msg = "该目录下没有找到视频或图片"

            return {
                "status": "ok",
                "directory": directory,
                "items": items,
                "total_count": result.total_count,
                "video_count": result.video_count,
                "image_count": result.image_count,
                "truncated": result.truncated,
                "original_count": result.original_count,
                "message": msg,
            }
        except Exception as e:
            # 与成功响应对齐：错误响应也包含 directory 字段
            return {"status": "error", "error": str(e), "directory": directory}

# ========== 便捷函数 (函数式 API) ==========

def search(
    source: str,
    keyword: str,
    save_dir: str | None = None,
    selection: SelectionStrategy | str | list[int] | None = None,
    timeout: float | None = None,
    download: bool = True,
    run_timeout: float | None = None,
    **config,
) -> dict:
    """函数式 API：直接搜索，等价于 UcrawlSDK().search()。

    Example:
        >>> from ucrawl import search
        >>> result = search("douyin", "测试", max_items=10)
        >>> result = search("bilibili", "BV1xxx", run_timeout=60, download=False)
    """
    # save_dir=None 让 SDK 从 cfg 读取默认值（与 GUI 对齐）
    sdk = UcrawlSDK(save_dir=save_dir)
    try:
        return sdk.search(source, keyword, save_dir=save_dir, selection=selection,
                          timeout=timeout, download=download, run_timeout=run_timeout, **config)
    finally:
        sdk.close()

def list_platforms() -> list[dict]:
    """列出所有可用平台。

    Example:
        >>> from ucrawl import list_platforms
        >>> for p in list_platforms():
        ...     print(p["id"], p["name"])
    """
    sdk = UcrawlSDK()
    try:
        return sdk.list_platforms()
    finally:
        sdk.close()

def scan_directory(directory: str, scan_limit: int | None = None) -> dict:
    """扫描本地目录。

    Example:
        >>> from ucrawl import scan_directory
        >>> result = scan_directory("D:/downloads", scan_limit=500)
    """
    sdk = UcrawlSDK()
    try:
        return sdk.scan_directory(directory, scan_limit)
    finally:
        sdk.close()

def download_video(
    url: str,
    source: str,
    title: str = "",
    save_dir: str | None = None,
    timeout: float = 300,
    verbose: bool = False,
    config: dict | None = None,
    progress_callback: Any = None,
) -> dict:
    """函数式 API：直接下载指定 URL 的视频，等价于 UcrawlSDK().download_video()。

    Example:
        >>> from ucrawl import download_video
        >>> result = download_video("https://...", "douyin", title="测试视频")
        >>> result = download_video("https://...", "missav", title="ABC-123", config={"proxy": "http://127.0.0.1:7890"})
    """
    sdk = UcrawlSDK(save_dir=save_dir)
    try:
        return sdk.download_video(url=url, source=source, title=title, save_dir=save_dir, timeout=timeout, verbose=verbose, config=config, progress_callback=progress_callback)
    finally:
        sdk.close()
