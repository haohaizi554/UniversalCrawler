from shared.log_classification import (
    CLASSIFICATION_FACTS_KEY,
    cache_classification_facts,
    classification_facts,
    drop_classification_facts,
    derive_result_type,
    is_performance_log,
    is_system_config_log,
    normalized_event_code,
    normalized_status_code,
    result_display_text,
    result_nature_text,
)
from shared.log_pipeline_rules import (
    derive_event_stage,
    derive_log_scope,
    derive_scope_reason,
    is_crawl_pipeline_log,
    is_download_boundary_log,
    is_download_component_source,
    is_platform_root_crawl_log,
)


def test_classification_facts_splits_source_action_and_detail_status():
    item = {
        "level": "info",
        "source": "Bilibili/API::get_video_info",
        "message": "ok",
        "detail": "说明: ✅ 下载完成\n状态码: DL_FINISH\n详情:\n- file: demo.mp4",
    }

    facts = classification_facts(item)

    assert facts["source"] == "Bilibili"
    assert facts["action"] == "API::get_video_info"
    assert facts["status"] == "DL_FINISH"
    assert normalized_status_code(item) == "DL_FINISH"
    assert normalized_event_code(item) == "DL_FINISH"


def test_classification_facts_cache_is_explicit_and_private():
    item = {"source": "Bilibili/API::get_video_info", "message": "ok"}

    facts = classification_facts(item)

    assert CLASSIFICATION_FACTS_KEY not in item
    cached = cache_classification_facts(item)
    assert cached == facts
    assert classification_facts(item) is cached
    assert drop_classification_facts(item) is item
    assert CLASSIFICATION_FACTS_KEY not in item


def test_result_type_prioritizes_explicit_levels_and_command_logs():
    assert derive_result_type({"level": "ERROR", "message": "plain"}) == "error"
    assert derive_result_type({"level": "WARN", "message": "plain"}) == "warn"
    assert derive_result_type({"level": "SUCCESS", "message": "plain"}) == "success"
    assert derive_result_type({"level": "CMD", "message": "ffmpeg -i demo.mp4"}) == "command"
    assert derive_result_type({"source": "Downloader", "action": "ffmpeg"}) == "command"


def test_result_type_does_not_treat_timeout_configuration_as_an_error():
    item = {
        "level": "INFO",
        "source": "WebController",
        "action": "start_crawl",
        "status_code": "WEB_CRAWL_START",
        "message": "Web 端启动爬虫任务",
        "detail": {
            "source_id": "bilibili",
            "active_config": {"timeout": 60, "api_workers": 8},
        },
    }

    assert derive_result_type(item) == "info"


def test_result_type_keeps_normal_timing_and_recovery_events_out_of_error():
    completed_timing = {
        "level": "INFO",
        "status_code": "THEME_TRANSITION_FINISHED",
        "message": "Theme transition finished",
        "detail": {"duration_ms": 28},
    }
    recovering_fallback = {
        "level": "INFO",
        "status_code": "M3U8_YTDLP_AFTER_BROWSER",
        "message": "Browser HLS failed; trying yt-dlp fallback",
    }

    assert derive_result_type(completed_timing) == "success"
    assert derive_result_type(recovering_fallback) == "warn"


def test_result_type_detects_performance_config_and_success_logs():
    perf_item = {"message": "FRONTEND_RENDER_SLOW duration_ms=48"}
    config_item = {"source": "ApplicationController", "action": "update_download_options"}
    success_item = {"message": "下载任务完成"}

    assert is_performance_log(perf_item)
    assert derive_result_type(perf_item) == "warn"
    assert is_system_config_log(config_item)
    assert derive_result_type(config_item) == "info"
    assert derive_result_type(success_item) == "success"


def test_result_type_treats_http_200_api_download_as_success():
    item = {
        "source": "BiliAPI",
        "action": "get_play_url",
        "status_code": "200",
    }

    assert derive_result_type(item) == "success"


def test_result_display_and_nature_text_are_stable():
    assert result_display_text("success") == "SUCCESS"
    assert result_display_text("unknown", "TRACE") == "TRACE"
    assert result_nature_text("warn") == "预警"
    assert result_nature_text("missing") == "过程"


def test_log_scope_helpers_separate_crawl_and_download_boundaries():
    crawl_item = {"source": "ApplicationController", "action": "start_crawl", "status_code": "APP_CRAWL_START"}
    handoff_item = {"source": "Bilibili", "action": "emit_download_task", "status_code": "BILI_TASK_EMIT"}
    download_item = {"source": "BilibiliDownloader", "action": "stream_video", "status_code": "BILI_DL_STREAM_VIDEO"}

    assert is_download_component_source("BilibiliDownloader")
    assert not is_download_boundary_log(handoff_item)
    assert is_platform_root_crawl_log(handoff_item)
    assert is_crawl_pipeline_log(crawl_item)
    assert is_download_boundary_log(download_item)
    assert derive_log_scope(crawl_item) == "crawl"
    assert derive_log_scope(download_item) == "download"
    assert derive_scope_reason(download_item) == "download_boundary"


def test_log_scope_helpers_prioritize_error_performance_and_system_config():
    assert derive_log_scope({"level": "ERROR", "message": "boom"}) == "error"
    assert derive_log_scope({"message": "FRONTEND_RENDER_SLOW duration_ms=52"}) == "performance"
    assert derive_log_scope({"source": "ApplicationController", "action": "update_download_options"}) == "system"


def test_web_local_media_scan_uses_the_same_system_scope_as_gui_scan():
    item = {
        "level": "INFO",
        "source": "WebController",
        "action": "async_scan_local_dir",
        "status_code": "WEB_SCAN_START",
        "message": "Web local media scan started asynchronously",
    }

    assert is_system_config_log(item)
    assert derive_log_scope(item) == "system"


def test_web_crawl_lifecycle_stays_in_crawl_scope():
    lifecycle = (
        ("start_crawl", "WEB_CRAWL_START"),
        ("item_found", "WEB_ITEM_FOUND"),
        ("_on_spider_finished_enter", "WEB_SPIDER_FINISH_ENTER"),
        ("crawl_finished", "WEB_CRAWL_FINISH"),
        ("stop_crawl", "WEB_CRAWL_STOP"),
    )

    for action, status_code in lifecycle:
        item = {
            "level": "INFO",
            "source": "WebController",
            "action": action,
            "status_code": status_code,
        }
        assert derive_log_scope(item) == "crawl"


def test_event_stage_helper_maps_pipeline_steps():
    assert derive_event_stage({"action": "app_init", "message": "start"}) == "init"
    assert derive_event_stage({"action": "scan_items", "message": "scan"}) == "scan"
    assert derive_event_stage({"action": "check_login"}) == "login"
    assert derive_event_stage({"action": "get_video_info"}) == "parse"
    assert derive_event_stage({"action": "get_play_url"}) == "fetch"
    assert derive_event_stage({"action": "stream_video"}) == "request"
    assert derive_event_stage({"action": "queue_task"}) == "queue"
    assert derive_event_stage({"action": "dispatch_task"}) == "dispatch"
    assert derive_event_stage({"action": "prepare_download"}) == "prepare"
    assert derive_event_stage({"action": "start_download"}) == "download"
    assert derive_event_stage({"action": "merge_finished"}) == "merge"
    assert derive_event_stage({"action": "release_slot"}) == "release"
