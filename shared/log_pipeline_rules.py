"""把日志事实映射到流水线边界、范围、原因与事件阶段。

输入是可能含新旧字段的日志字典，字段读取统一委托 ``classification_facts``。
这些函数包含有意排序的首命中规则：排除项和强语义必须位于来源/文本等宽泛
启发式之前，不能在整理词表时随意换序。布尔谓词默认 False；未知 scope、
reason 和 stage 分别回退为 ``system``、``fallback_system`` 和 ``step``。
"""

from __future__ import annotations

from typing import Any

from shared.log_classification import (
    classification_facts,
    derive_result_type,
    is_performance_log,
    is_system_config_log,
)


def is_download_component_source(source: str) -> bool:
    """判断归一化来源名是否属于已知下载执行组件。"""
    source = str(source or "").strip().lower()
    if not source:
        return False

    tokens = (
        "downloadmanager",
        "download_manager",
        "downloadworker",
        "download_worker",
        "downloadrunner",
        "download_runner",
        "downloadservice",
        "download_service",
        "downloader",
        "bilibilidownloader",
        "douyindownloader",
        "kuaishoudownloader",
        "xiaohongshudownloader",
        "missavdownloader",
        "n_m3u8dl",
        "n_m3u8dl_re",
        "ffmpeg",
    )
    return any(token in source for token in tokens)

def is_download_boundary_log(item: dict[str, Any]) -> bool:
    """仅在日志已越过爬取到下载执行的边界后返回 True。

    输入先归一化为 source/action/status/event/message/detail。爬取交接状态和动作
    必须最先排除；随后依次接受下载状态前缀、动作、受来源约束的生成消息、强
    下载组件及 downloader 边界词。把宽泛来源判断移到排除项之前会把
    ``TASK_EMIT``/``ITEM_FOUND`` 误归为下载日志。未命中时返回 False。
    """
    facts = classification_facts(item)
    source = facts["source_lower"]
    action = facts["action_lower"]
    status = facts["status_upper"]
    event_code = facts["event_code_upper"]
    message = facts["message_lower"]
    detail = facts["detail_lower"]
    combined = facts["combined_upper"]

    crawl_handoff_statuses = (
        "BILI_TASK_EMIT",
        "BILI_QUEUE_READY",
        "APP_ITEM_FOUND",
        "APP_CRAWL_START",
        "APP_CRAWL_FINISH",
        "XHS_TASK_EMIT",
        "DY_TASK_EMIT",
        "KS_TASK_EMIT",
        "MISSAV_TASK_EMIT",
    )
    if status in crawl_handoff_statuses or event_code in crawl_handoff_statuses:
        return False

    crawl_handoff_actions = {
        "emit_download_task",
        "download_queue_ready",
        "item_found",
        "start_crawl",
        "crawl_finished",
        "run_start",
        "run_finish",
    }
    if action in crawl_handoff_actions:
        return False

    download_status_prefixes = (
        "DL_",
        "APP_DL_",
        "BILI_DL_",
        "BILI_MERGE",
        "XHS_DL_",
        "DY_DL_",
        "KS_DL_",
        "MISSAV_DL_",
    )
    if any(status.startswith(prefix) for prefix in download_status_prefixes):
        return True
    if any(event_code.startswith(prefix) for prefix in download_status_prefixes):
        return True

    download_actions = {
        "queue_task",
        "dispatch_task",
        "start_download",
        "prepare_download",
        "download_finished",
        "normalize_extension",
        "release_slot",
        "merge_finished",
        "ffmpeg",
        "api::stream_audio",
        "api::stream_video",
        "stream_audio",
        "stream_video",
        "download_stream",
        "download_file",
        "download_hls",
        "download_m3u8",
    }
    if action in download_actions:
        return True

    chinese_download_tokens = (
        "下载完成",
        "下载任务完成",
        "下载任务已进入队列",
        "进入队列",
        "已进入队列",
        "任务已从队列分发",
        "从队列分发",
        "分发到下载线程",
        "下载任务开始执行",
        "开始执行",
        "开始下载",
        "准备下载",
        "下载并发槽位已释放",
        "槽位已释放",
        "音视频合并完成",
        "合并完成",
        "流请求建立成功",
    )

    generated_download_prefixes = (
        "DOWNLOADER_",
        "DOWNLOADMANAGER_",
        "DOWNLOADWORKER_",
        "DOWNLOADRUNNER_",
        "DOWNLOADSERVICE_",
        "BILIBILIDOWNLOADER_",
        "DOUYINDOWNLOADER_",
        "KUAISHOUDOWNLOADER_",
        "XIAOHONGSHUDOWNLOADER_",
        "MISSAVDOWNLOADER_",
    )

    generated_text = " ".join([event_code, status, message, detail]).lower()

    if any(event_code.startswith(prefix) for prefix in generated_download_prefixes):
        if any(token in generated_text for token in chinese_download_tokens):
            return True

    if is_download_component_source(source):
        if any(token in message for token in chinese_download_tokens):
            return True
        if any(token in detail for token in chinese_download_tokens):
            return True

    strong_download_sources = (
        "downloadmanager",
        "download_manager",
        "downloadworker",
        "download_worker",
        "downloadrunner",
        "download_runner",
        "downloadservice",
        "download_service",
        "n_m3u8dl",
        "n_m3u8dl_re",
        "ffmpeg",
    )
    if any(token in source for token in strong_download_sources):
        return True

    if "FFMPEG" in combined:
        return True

    if "MERGE" in combined:
        return True

    if "合并" in message:
        return True

    if "downloader" in source:
        downloader_boundary_tokens = (
            "PREPARE",
            "STREAM_AUDIO",
            "STREAM_VIDEO",
            "START_DOWNLOAD",
            "DOWNLOAD START",
            "DOWNLOAD STARTED",
            "DOWNLOAD OK",
            "DOWNLOAD COMPLETE",
            "DL_START",
            "DL_QUEUE",
            "DL_DISPATCH",
            "DL_FINISH",
            "BILI_DL_PREPARE",
            "BILI_MERGE_OK",
            "SAVE_PATH",
            "TARGET_PATH",
            "LOCAL_PATH",
            "CONTENT_LENGTH",
            "_VIDEO.M4S",
            "_AUDIO.M4S",
            "M3U8",
        )
        boundary_text = " ".join(
            [
                action.upper(),
                status,
                event_code,
                message.upper(),
                detail.upper(),
            ]
        )
        if any(token in boundary_text for token in downloader_boundary_tokens):
            return True

    return False

def is_platform_root_crawl_log(item: dict[str, Any]) -> bool:
    """识别平台根来源的爬取日志；下载边界排除始终拥有更高优先级。"""
    if is_download_boundary_log(item):
        return False

    facts = classification_facts(item)
    source = facts["source_lower"]
    message = facts["message_lower"]
    status = facts["status_upper"]
    event_code = facts["event_code_upper"]
    combined = facts["combined_upper"]

    platform_root_sources = {
        "bilibili",
        "bili",
        "douyin",
        "dy",
        "kuaishou",
        "ks",
        "xiaohongshu",
        "xhs",
        "redbook",
        "missav",
    }

    if source in platform_root_sources:
        return True

    platform_prefixes = (
        "BILIBILI_",
        "BILI_",
        "DOUYIN_",
        "DY_",
        "KUAISHOU_",
        "KS_",
        "XIAOHONGSHU_",
        "XHS_",
        "MISSAV_",
    )

    if any(status.startswith(prefix) for prefix in platform_prefixes):
        return True

    if any(event_code.startswith(prefix) for prefix in platform_prefixes):
        return True

    crawl_message_tokens = (
        "已聚合",
        "聚合",
        "扫描结束",
        "扫描完成",
        "正在展开",
        "展开",
        "最终确认",
        "有效资源",
        "候选资源",
        "发现",
        "第 ",
        "页",
        "route",
        "搜索",
        "解析",
        "获取播放",
        "播放地址",
        "装配完成",
        "提交到下载队列",
    )

    if any(token in message for token in crawl_message_tokens):
        return True

    crawl_combined_tokens = (
        "AGGREGATE",
        "AGGREGATED",
        "COLLECT",
        "COLLECTED",
        "EXPAND",
        "EXPANDED",
        "SCAN",
        "FOUND",
        "DISCOVER",
        "DISCOVERED",
        "CONFIRM",
        "CONFIRMED",
        "ROUTE",
        "PARSE",
        "EXTRACT",
        "FETCH",
        "PLAY_URL",
        "GET_VIDEO_INFO",
        "GET_PLAY_URL",
        "TASK_EMIT",
        "QUEUE_READY",
    )

    if any(token in combined for token in crawl_combined_tokens):
        return True

    return False

def is_crawl_pipeline_log(item: dict[str, Any]) -> bool:
    """识别搜索、解析、提取和发现阶段；已越过下载边界时固定返回 False。"""
    if is_download_boundary_log(item):
        return False

    if is_platform_root_crawl_log(item):
        return True

    facts = classification_facts(item)
    source = facts["source_lower"]
    action = facts["action_lower"]
    status = facts["status_upper"]
    event_code = facts["event_code_upper"]
    message = facts["message_lower"]
    combined = facts["combined_upper"]

    crawl_status_prefixes = (
        "APP_CRAWL",
        "APP_ITEM_FOUND",
        "WEB_CRAWL",
        "WEB_ITEM_FOUND",
        "WEB_SPIDER_FINISH",
        "BILI_SPIDER",
        "BILI_ROUTE",
        "BILI_PARSE",
        "BILI_API",
        "BILI_QUEUE_READY",
        "BILI_TASK_EMIT",
        "XHS_",
        "DY_",
        "KS_",
        "MISSAV_",
    )

    crawl_actions = {
        "run_start",
        "run_finish",
        "start_crawl",
        "stop_crawl",
        "crawl_finished",
        "_on_spider_finished_enter",
        "item_found",
        "download_queue_ready",
        "emit_download_task",
        "api::check_login",
        "api::get_video_info",
        "api::get_play_url",
        "check_login",
        "get_video_info",
        "get_play_url",
        "search",
        "parse",
        "fetch",
        "extract",
        "extract_detail",
        "extract_items",
        "resolve_url",
        "resolve_play_url",
        "parse_detail",
        "parse_page",
        "parse_video",
        "parse_note",
        "parse_aweme",
        "parse_feed",
        "parse_profile",
    }

    crawl_source_tokens = (
        "spider",
        "api",
        "parser",
        "extractor",
        "crawler",
        "scraper",
        "resolver",
        "route",
        "browser",
        "playwright",
    )

    crawl_message_tokens = (
        "解析",
        "获取播放流地址",
        "获取播放地址",
        "检查登录",
        "搜索",
        "发现可下载资源",
        "提交到下载队列",
        "下载任务已装配完成",
        "已聚合",
        "聚合",
        "扫描结束",
        "扫描完成",
        "正在展开",
        "最终确认",
        "有效资源",
        "候选资源",
        "第 ",
        "页",
        "fetch video detail",
        "get video info",
        "get play url",
    )

    if any(status.startswith(prefix) for prefix in crawl_status_prefixes):
        return True

    if any(event_code.startswith(prefix) for prefix in crawl_status_prefixes):
        return True

    if action in crawl_actions:
        return True

    if action.startswith("api::") and not any(
        token in action
        for token in ("stream_audio", "stream_video", "download", "merge")
    ):
        return True

    if any(token in source for token in crawl_source_tokens):
        return True

    if any(token in message for token in crawl_message_tokens):
        return True

    if any(token in combined for token in ("GET_VIDEO_INFO", "GET_PLAY_URL", "CHECK_LOGIN", "ITEM_FOUND", "TASK_EMIT")):
        return True

    return False

def derive_scope_reason(item: dict[str, Any]) -> str:
    """返回 scope 判定原因，按性能、下载、配置、平台爬取、一般爬取取首项。

    未命中语义规则时保留 ``legacy_<category>`` 供诊断；连旧分类也没有则回退
    ``fallback_system``。该顺序与 ``derive_log_scope`` 的边界优先级配套。
    """
    if is_performance_log(item):
        return "performance_token"

    if is_download_boundary_log(item):
        return "download_boundary"

    if is_system_config_log(item):
        return "system_config"

    if is_platform_root_crawl_log(item):
        return "platform_root_crawl"

    if is_crawl_pipeline_log(item):
        return "crawl_pipeline"

    facts = classification_facts(item)
    if facts["legacy_category"]:
        return f"legacy_{facts['legacy_category']}"

    return "fallback_system"

def derive_log_scope(item: dict[str, Any]) -> str:
    """返回 error、performance、crawl、download 或 system。

    显式/强错误优先于其他范围，其次是性能；ApplicationController 事件先按其
    结构化状态细分。其余日志依次判定下载边界、系统配置和爬取语义，再处理旧
    category。旧 category 只是低优先级提示，不能覆盖新的边界规则；最终回退
    system。上述首命中顺序不可随意调整。
    """
    facts = classification_facts(item)

    raw_level = facts["raw_level"]
    source = facts["source_lower"]
    action = facts["action_lower"]
    status = facts["status_upper"]
    event_code = facts["event_code_upper"]
    combined = facts["combined_upper"]
    legacy_category = facts["legacy_category"]

    if raw_level in {"ERROR", "FATAL", "CRITICAL"}:
        return "error"

    hard_error_tokens = (
        "LOCAL_HLS_PROXY_ERROR",
        "PROXY_ERROR",
        "CONNECTION_RESET",
        "FATAL",
        "EXCEPTION",
        "TRACEBACK",
    )
    if any(token in combined for token in hard_error_tokens):
        return "error"

    if is_performance_log(item):
        return "performance"

    if source == "applicationcontroller":
        if status.startswith(("APP_CRAWL", "APP_ITEM_FOUND")) or event_code.startswith(
            ("APP_CRAWL", "APP_ITEM_FOUND")
        ):
            return "crawl"

        if status.startswith("APP_DL_") or event_code.startswith("APP_DL_"):
            return "download"

        if action in {"start_crawl", "item_found", "crawl_finished"}:
            return "crawl"

        if action in {"download_finished"}:
            return "download"

        if is_system_config_log(item):
            return "system"

        if status.startswith(("APP_INIT", "APP_READY", "APP_SCAN", "APP_DIR")) or event_code.startswith(
            ("APP_INIT", "APP_READY", "APP_SCAN", "APP_DIR")
        ):
            return "system"

        return "system"

    if is_download_boundary_log(item):
        return "download"

    if is_system_config_log(item):
        return "system"

    if is_platform_root_crawl_log(item):
        return "crawl"

    if is_crawl_pipeline_log(item):
        return "crawl"

    system_sources = (
        "gui",
        "mainwindow",
        "frontendstateservice",
        "uiupdatescheduler",
        "system",
    )
    system_status_prefixes = (
        "APP_INIT",
        "APP_READY",
        "APP_SCAN",
        "APP_DIR",
        "UI_",
        "FRONTEND_",
    )

    if any(token in source for token in system_sources):
        return "system"

    if status.startswith(system_status_prefixes) or event_code.startswith(system_status_prefixes):
        return "system"

    if legacy_category == "download":
        if is_download_boundary_log(item):
            return "download"
        if is_platform_root_crawl_log(item) or is_crawl_pipeline_log(item):
            return "crawl"
        return "system"

    if legacy_category == "crawl":
        if not is_download_boundary_log(item):
            return "crawl"
        return "download"

    if legacy_category == "performance":
        return "performance" if is_performance_log(item) else "system"

    if legacy_category == "error":
        return "error" if raw_level in {"ERROR", "FATAL", "CRITICAL"} else "system"

    if legacy_category == "system":
        return "system"

    return "system"

def derive_event_stage(item: dict[str, Any]) -> str:
    """按首命中规则返回事件阶段，未知事件回退 ``step``。

    error、performance、config 先处理；随后从 init/scan/login 到爬取、请求、
    入队、下载与收尾阶段逐步匹配。具体阶段必须位于通用 ``success/FINISH`` 和
    ``START`` 判断之前，否则 merge、release 等事件会被过早吞并。规则顺序是
    输出契约的一部分。
    """
    facts = classification_facts(item)
    result_type = derive_result_type(item)

    raw_level = facts["raw_level"]
    action = facts["action_lower"]
    combined = facts["combined_upper"]
    message = facts["message_lower"]

    if result_type == "error" or raw_level in {"ERROR", "FATAL", "CRITICAL"}:
        return "error"

    if is_performance_log(item):
        return "performance"

    if is_system_config_log(item):
        return "config"

    if "APP_INIT" in combined or action == "app_init":
        return "init"

    if "SCAN" in combined or "scan" in action or "扫描结束" in message or "扫描完成" in message:
        return "scan"

    if "CHECK_LOGIN" in combined or "check_login" in action or "登录状态" in message:
        return "login"

    if "最终确认" in message:
        return "confirm"

    if any(token in message for token in ("已聚合", "聚合", "有效资源", "候选资源")):
        return "aggregate"

    if any(token in message for token in ("正在展开", "展开")):
        return "expand"

    if "确认" in message:
        return "confirm"

    if "GET_VIDEO_INFO" in combined or "get_video_info" in action or "video detail" in message or "解析" in message:
        return "parse"

    if "GET_PLAY_URL" in combined or "get_play_url" in action or "播放流" in message or "获取" in message:
        return "fetch"

    if "STREAM_AUDIO" in combined or "STREAM_VIDEO" in combined or "流请求" in message:
        return "request"

    if "ITEM_FOUND" in combined or "item_found" in action or "发现可下载资源" in message:
        return "found"

    if "发现" in message and "页" in message:
        return "found"

    if "TASK_EMIT" in combined or "emit_download_task" in action or "提交到下载队列" in message:
        return "emit"

    if "QUEUE" in combined or "queue_task" in action or "进入队列" in message:
        return "queue"

    if "DISPATCH" in combined or "dispatch_task" in action or "分发" in message:
        return "dispatch"

    if "PREPARE" in combined or "prepare_download" in action or "准备下载" in message:
        return "prepare"

    if "START_DOWNLOAD" in combined or "DL_START" in combined or "下载任务开始" in message:
        return "download"

    if "MERGE" in combined or "FFMPEG" in combined or "合并" in message:
        return "merge"

    if "NORMALIZED" in combined or "normalize" in action or "修正扩展名" in message:
        return "normalize"

    if "RELEASE" in combined or "release_slot" in action or "槽位已释放" in message:
        return "release"

    if any(token in message for token in ("下载任务已进入队列", "进入队列", "已进入队列")):
        return "queue"

    if any(token in message for token in ("任务已从队列分发", "从队列分发", "分发到下载线程")):
        return "dispatch"

    if any(token in message for token in ("下载任务开始执行", "开始执行", "开始下载")):
        return "download"

    if any(token in message for token in ("准备下载", "准备下载 bilibili")):
        return "prepare"

    if any(token in message for token in ("下载完成", "下载任务完成")):
        return "finish"

    if any(token in message for token in ("下载并发槽位已释放", "槽位已释放")):
        return "release"

    if result_type == "success" or "FINISH" in combined or "完成" in message:
        return "finish"

    if "START" in combined or action.endswith("_start") or "启动" in message:
        return "start"

    return "step"
