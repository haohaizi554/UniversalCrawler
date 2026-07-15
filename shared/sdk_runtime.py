"""可通过 ``from ucrawl import UcrawlSDK`` 使用的 Python SDK 运行时。

搜索调用复用 ``CLIRunner``，并通过 ``shared.runtime_options`` 读取持久化配置
及代码兜底值；这些来源与优先级是共享契约，不代表 SDK 与任一前端拥有完全
相同的交互行为。直接下载不经过 spider，因此其下载元数据在本模块内组装。

示例：
    >>> from ucrawl import UcrawlSDK
    >>> sdk = UcrawlSDK(save_dir="downloads")
    >>> result = sdk.search("douyin", "测试关键词", max_items=20)
    >>> [item["title"] for item in result["items"]]
"""

from __future__ import annotations

import os
import sys
from typing import Any

from shared.cli_runner_runtime import CLIRunner
from shared.selection_base import SelectionStrategy, is_selection_strategy

# 保持 CLI/SDK 输出实时刷新，便于长任务反馈
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# 下列导入属于既有 SDK 的公开兼容表面。
from shared.runtime_options import (
    DEFAULT_CONFIG,  # noqa: F401 - 作为公开 SDK 兼容导出保留。
    build_missav_proxy_url,
    compose_runtime_config,
    get_default_save_dir,
    get_platform_defaults,
    get_platform_download_defaults,
    infer_content_type,
    infer_content_type_from_url,
    merge_convenience_params,  # noqa: F401 - 作为公开 SDK 兼容导出保留。
    validate_config_types,
    validate_direct_download_url,
)
from shared.selection_runtime import (
    AutoSelection,
    SelectionStrategyFactory,
)

def _discover_platform_ids() -> tuple[str, ...]:
    """从插件注册表生成平台枚举；注册表不可用时返回内置兜底集合。"""
    try:
        from app.core.plugin_registry import registry

        return tuple(plugin.id for plugin in registry.get_all_plugins())
    except Exception:
        return ("douyin", "bilibili", "kuaishou", "missav", "xiaohongshu")

class UcrawlSDK:
    """UCrawl Python SDK。

    属性：
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

        参数：
            save_dir: 默认保存目录；None 时从共享运行时配置读取
            verbose: 是否输出 spider 日志到 stderr (默认 False)
            config: 全局默认配置 (会被 search() 的 config 参数覆盖)
        """
        self.save_dir = save_dir or get_default_save_dir()
        # 在回退到默认目录后仍校验调用方显式传入的原始类型。
        if save_dir is not None and not isinstance(save_dir, str):
            raise TypeError("save_dir 必须是字符串或 None")
        self.verbose = verbose
        # 必须先校验再 dict()，避免把字符串等可迭代对象误当配置映射。
        if config is not None and not isinstance(config, dict):
            raise TypeError("config 必须是字典或 None")
        self.default_config = dict(config or {})

    def __enter__(self) -> "UcrawlSDK":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """保留幂等清理接口；当前实例不持有跨调用的运行资源。"""
        return None

    def _get_runner_class(self):
        """返回 SDK 搜索流程使用的执行器类。

        共享运行时默认使用 shared 中的执行器实现。宿主专用的公开包可覆盖此
        钩子以保留补丁接缝，无需在 ``shared/`` 之外再维护一份执行器实现。
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

        参数：
            source: 平台 ID (douyin/bilibili/kuaishou/missav)
            keyword: 搜索关键词 / 链接 / 用户 ID
            save_dir: 本次调用的保存目录 (None=使用 SDK 默认值)
            selection: 二次选择策略
                - None → AutoSelection (有 TTY 交互，无 TTY 管道，否则全选)
                - "all" → 全选
                - "first" → 只选第一个
                - "last" → 只选最后一个
                - list[int] → 指定索引 (如 [0, 2, 5])
                - dict → 策略描述 (如 {"strategy": "all"} 或 rule 配置)
                - SelectionStrategy 实例 → 完整控制
            timeout: 已弃用的整体运行超时；仅在 run_timeout 为 None 时生效
            download: True 时下载发现项，False 时只收集
            run_timeout: 整体运行超时，优先于兼容参数 timeout
                spider 的 HTTP 请求超时是 ``config["timeout"]``，与这两个整体
                运行超时参数相互独立
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

        返回：
            dict: 详细结果 (见 CLIRunner.run() 的返回结构)

        示例：
            >>> sdk = UcrawlSDK(save_dir="downloads")
            >>> result = sdk.search("douyin", "测试", max_items=10)
            >>> print(f"找到 {len(result['items'])} 个项目")
            >>>
            >>> # 合集场景用预加载
            >>> from ucrawl import PipeSelection
            >>> sel = PipeSelection(preloaded_choices=[[0], [1, 2]])
            >>> result = sdk.search("bilibili", "BVxxxx", selection=sel)
        """
        # SDK 在创建运行器前完成公共参数校验，错误直接抛给调用方。
        if not isinstance(source, str) or not isinstance(keyword, str):
            raise TypeError("source 和 keyword 必须是字符串")
        keyword = keyword.strip()
        if not source or not keyword:
            raise ValueError("source 和 keyword 不能为空")
        # 有效平台以当前插件注册表为准，而不是静态 PLATFORMS 快照。
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            raise ValueError(f"无效平台: {source}。支持: {valid_ids}")

        # ``run_timeout`` 是新名称；只有未提供时才读取旧 ``timeout`` 参数。
        effective_run_timeout = run_timeout if run_timeout is not None else timeout
        if effective_run_timeout is not None and (
            isinstance(effective_run_timeout, bool)
            or not isinstance(effective_run_timeout, (int, float))
        ):
            raise TypeError("timeout/run_timeout 必须是数字或 None")
        if effective_run_timeout is not None and effective_run_timeout <= 0:
            raise ValueError("timeout/run_timeout 必须大于 0")
        if not isinstance(download, bool):
            raise TypeError("download 必须是布尔值")
        if save_dir is not None and not isinstance(save_dir, str):
            raise TypeError("save_dir 必须是字符串或 None")
        # 仅已知配置键受类型约束，插件私有键继续透传。
        self._validate_config(config)

        # 所有受支持的选择描述在进入运行器前转换为策略对象。
        strategy = self._resolve_selection(selection)

        # 配置优先级为持久化/兜底平台默认、SDK 实例默认、本次调用配置。
        # 本次显式传入 None 的键最终删除，不能意外恢复较低优先级的值。
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
        """用共享 schema 校验已知配置键，并保留未知插件键。"""
        err = validate_config_types(config)
        if err:
            # SDK 异常不重复 shared 校验器已添加的 ``config.`` 前缀。
            raise TypeError(err.replace("config.", "", 1))

    def _resolve_selection(self, selection) -> SelectionStrategy:
        """把字符串、索引列表、策略字典或对象解析为 SelectionStrategy。"""
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
        """直接下载指定 URL，并返回下载与清理状态。

        参数：
            url: 视频 URL
            source: 平台 ID (douyin/bilibili/kuaishou/missav)
            title: 视频标题（默认使用 URL）
            save_dir: 保存目录 (None=使用 SDK 默认值)
            timeout: 下载超时秒数 (默认 300)
            verbose: 是否输出下载进度到 stderr
            config: 平台特定配置；None 时使用共享平台默认值
                missav: proxy (str) — 代理 URL
            progress_callback: 下载进度回调函数；None 时不回调
                签名: callback(progress: int) -> None
                progress 范围为 0-100
            network_policy: 内部信任边界。Web 公网直链入口使用 ``"public"``，
                先拒绝本地/私有目标，再把策略写入元数据供下载器逐跳校验重定向；
                普通 CLI/SDK 调用保持 ``None``，以明确保留本地资源访问能力

        返回：
            dict: {"status": "ok"/"error", "video_id": ..., "title": ..., "local_path": ..., ...}

        示例：
            >>> sdk = UcrawlSDK(save_dir="downloads")
            >>> result = sdk.download_video("https://...", "douyin", title="测试视频")
            >>> if result["status"] == "ok":
            ...     print(f"下载完成: {result['local_path']}")
            >>>
            >>> # 带进度回调
            >>> def on_progress(pct):
            ...     print(f"进度: {pct}%")
            >>> result = sdk.download_video("https://...", "douyin", progress_callback=on_progress)
        """
        # 直接下载在创建 VideoItem 前拒绝无效的公共参数。
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
            # 公网入口必须在任何网络 IO 前执行首跳 SSRF 校验。
            url_error = validate_direct_download_url(url)
            if url_error:
                raise ValueError(url_error)
        # 下载器来源必须来自当前插件注册表。
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            raise ValueError(f"无效平台: {source}。支持: {valid_ids}")
        # 配置仍允许插件私有键，仅共享键执行类型校验。
        if config:
            self._validate_config(config)

        from app.models.video_item import VideoItem
        from app.config import cfg
        from app.core.download_manager import DownloadManager
        import time

        # URL 是空标题时唯一稳定且可追踪的展示值。
        effective_title = title or url

        item = VideoItem(
            url=url,
            title=effective_title,
            source=source,
            status="⏳ 等待中",
            progress=0,
        )

        # 元数据配置来源按平台持久化/兜底默认、SDK 实例默认、本次 config 合并；
        # 高优先级的显式 None 会删除同名低优先级值。
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

        # 直接下载绕过 spider 的任务元数据构造器，因此补入平台请求头和本地认证
        # 默认值。已有 merged 键优先，确保调用配置不会被推导值覆盖。
        platform_defaults = get_platform_download_defaults(source)
        for key, val in platform_defaults.items():
            if key not in merged:
                merged[key] = val

        # 未提供 content_type 时从 URL 提供下载前提示；仍无法判断则在落盘后
        # 根据本地路径再次推断。
        if "content_type" not in merged or not merged["content_type"]:
            url_content_type = infer_content_type_from_url(url)
            if url_content_type:
                merged["content_type"] = url_content_type

        # 直接下载没有 spider 生成的 trace_id，需在入队前创建以关联下载日志。
        import uuid as _uuid
        _source_prefix = {"douyin": "dy", "bilibili": "bili", "kuaishou": "ks", "missav": "miss"}.get(source, source)
        item.meta["trace_id"] = f"{_source_prefix}-dl-{_uuid.uuid4().hex[:8]}"
        if network_policy:
            # 首跳校验后仍需把策略传给下载器，覆盖后续每次重定向。
            item.meta["_network_policy"] = network_policy

        # 只把下载器与路径策略消费的白名单字段复制到 item.meta。其值来自上面的
        # 合并配置、平台下载默认值及 content_type 推断，避免把任意配置泄漏给
        # 下载任务。
        for key in (
            "referer", "ua", "content_type", "cookie", "cookies", "proxy",
            "download_strategy", "folder_name", "use_subdir",
            "audio_url", "aweme_id", "bvid", "cid",
            "file_name", "preferred_filename", "is_gallery", "is_mix",
            "images_data", "size_mb", "media_label",
            # 解析器可直接提供、且下载器或路径策略会消费的补充字段。
            "duration",        # 分块/FFmpeg 下载器使用的视频时长
            "mix_title",       # 合集路径标题
            "create_time",     # 媒体创建时间
            "author",          # 可作为 folder_name 来源的作者名
            "has_live_photo",  # 实况照片标记
        ):
            if key in merged:
                item.meta[key] = merged[key]

        save_dir = save_dir or self.save_dir
        dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))

        # elapsed 覆盖入队、等待和停止下载管理器的完整调用时段。
        start_time = time.time()

        # 信号回调维护同步返回所需的状态，并可转发进度。
        result_holder = {"status": "pending", "error": None}
        stop_summary = None

        def on_started(vid):
            if item.id == vid:
                item.status = "⏳ 下载中..."
                item.progress = 0
                if verbose:
                    sys.stderr.write(f"⏳ 开始下载: {item.title}\n")
                    sys.stderr.flush()
                # 首次回调 0，使调用方能建立自己的进度状态。
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
                # 用户回调异常不能中断下载管理器的工作线程。
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
            # timeout 从任务入队后开始限制队列与活动 worker 的完成时间。
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

            # 超时是独立终态，调用方可与下载器错误区分。
            if timed_out and result_holder["status"] == "pending":
                item.status = "❌ 超时"
                item.meta["download_error"] = f"下载超时 ({timeout}s)"
                result_holder["status"] = "timeout"
                result_holder["error"] = f"下载超时 ({timeout}s)"
        finally:
            # 所有退出路径都停止 DownloadManager；摘要会暴露未停止的 worker。
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

        # 清理完成后再冻结耗时，确保返回值覆盖资源释放阶段。
        elapsed = round(time.time() - start_time, 2)

        # URL 未提供类型线索时，使用最终本地路径补全 content_type。
        detected_content_type = item.meta.get("content_type", "") if item.meta else ""
        if not detected_content_type and item.local_path:
            detected_content_type = infer_content_type(item.local_path)
            # 同步到元数据，令结果中的顶层字段与 meta 来源一致。
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
                # content_type 与 meta 是直接下载的公开结果字段。
                "content_type": detected_content_type,
                "meta": dict(item.meta) if item.meta else {},
                "shutdown": shutdown,
                "elapsed": elapsed,
            }
        else:
            error_msg = item.meta.get("download_error", item.status)
            if not shutdown["all_workers_stopped"] or not shutdown["dispatcher_stopped"]:
                error_msg = f"{error_msg}；后台任务仍在停止中"
            # 保留 timeout/error 区分，不把停止阶段的附加信息改写成新终态。
            result_status = result_holder["status"]
            return {
                "status": result_status,
                "video_id": item.id,
                "url": url,
                "source": source,
                "title": item.title,
                "error": error_msg,
                "save_dir": save_dir,
                # 失败结果也固定提供 local_path，未落盘时为空字符串。
                "local_path": item.local_path or "",
                "content_type": detected_content_type,
                "meta": dict(item.meta) if item.meta else {},
                "shutdown": shutdown,
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

        参数：
            directory: 要扫描的目录
            scan_limit: 最多扫描多少个文件；None 时读取共享下载配置

        返回：
            dict: {"status": "ok", "items": [...], "total_count": N, "message": "...", ...}
        """
        # 调用参数错误直接抛异常；扫描过程错误才进入结构化结果。
        if not isinstance(directory, str):
            raise TypeError("directory 必须是字符串")
        if not directory:
            raise ValueError("directory 不能为空")
        if scan_limit is not None and (isinstance(scan_limit, bool) or not isinstance(scan_limit, int)):
            raise TypeError("scan_limit 必须是整数或 None")
        if scan_limit is not None and scan_limit <= 0:
            raise ValueError("scan_limit 必须大于 0")

        from app.config import cfg
        from app.services.file_service import MediaLibraryService

        # 未显式指定时采用持久化本地媒体扫描上限，并对损坏配置兜底。
        if scan_limit is None:
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
            try:
                scan_limit = int(scan_limit)
            except (ValueError, TypeError):
                scan_limit = 1000

        # 扩展名集合定义 SDK 扫描对 MediaLibraryService 的输入边界。
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
                # 本地扫描项在序列化前标记为已完成，避免呈现为待下载任务。
                item.status = "✅ 本地"
                item.progress = 100
                items.append(item.to_dict())

            # message 是给直接调用者展示的扫描摘要。
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
            # 失败结果保留 directory，便于调用方关联原始请求。
            return {"status": "error", "error": str(e), "directory": directory}

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

    示例：
        >>> from ucrawl import search
        >>> result = search("douyin", "测试", max_items=10)
        >>> result = search("bilibili", "BV1xxx", run_timeout=60, download=False)
    """
    # save_dir=None 由 SDK 通过共享运行时配置解析默认目录。
    sdk = UcrawlSDK(save_dir=save_dir)
    try:
        return sdk.search(source, keyword, save_dir=save_dir, selection=selection,
                          timeout=timeout, download=download, run_timeout=run_timeout, **config)
    finally:
        sdk.close()

def list_platforms() -> list[dict]:
    """列出所有可用平台。

    示例：
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

    示例：
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

    示例：
        >>> from ucrawl import download_video
        >>> result = download_video("https://...", "douyin", title="测试视频")
        >>> result = download_video("https://...", "missav", title="ABC-123", config={"proxy": "http://127.0.0.1:7890"})
    """
    sdk = UcrawlSDK(save_dir=save_dir)
    try:
        return sdk.download_video(url=url, source=source, title=title, save_dir=save_dir, timeout=timeout, verbose=verbose, config=config, progress_callback=progress_callback)
    finally:
        sdk.close()
