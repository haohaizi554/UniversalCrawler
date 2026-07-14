from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.config.settings import DEFAULT_OPEN_MODE, open_mode_label, playback_player_label
from app.services.frontend_video_adapter import active_chunk_progress_label, active_detail_fields
from app.services import frontend_toolbox_adapter as toolbox_adapter
from shared.frontend_page_definitions import PAGE_DEFINITIONS
from shared.icon_contract import icon_manifest
from shared.log_contract import log_contract


def build_mock_snapshot(
    settings_snapshot_factory: Callable[[], dict[str, Any]],
    settings_contract_factory: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    now_date = "2026-04-12"
    active_specs = [
        ("a1", "\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5 | \u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929", 65, "4.2 MB/s", 4_404_019, "00:01:42", 39),
        ("a2", "\u96e8\u540e\u5c71\u95f4\u7684\u6e29\u67d4\u65f6\u523b", 38, "2.7 MB/s", 2_831_155, "00:03:18", 23),
        ("a3", "\u81ea\u9a7e\u65b0\u7586 | \u661f\u7a7a\u4e0b\u7684\u665a\u9910", 22, "1.6 MB/s", 1_677_721, "00:06:45", 13),
        ("a4", "\u57ce\u5e02\u591c\u666f\u5ef6\u65f6\u6444\u5f71", 11, "1.1 MB/s", 1_153_434, "00:13:27", 7),
        ("a5", "\u5f92\u6b65\u7a7f\u8d8a\u5ce1\u8c37\u7684\u4e00\u5929", 8, "0.8 MB/s", 838_861, "00:18:56", 5),
    ]
    active_items = []
    for item_id, title, progress, speed, speed_bps, eta, chunks_done in active_specs:
        platform = "\u6296\u97f3"
        trace_id = f"dy_20260412_182452_{item_id}"
        save_dir = "D:\\Downloads\\\u6296\u97f3\\\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5"
        output_filename = "\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5_\u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929_20260412.mp4"
        source_url = "https://v.douyin.com/abc123"
        active_items.append({
            "id": item_id,
            "title": title,
            "platform": platform,
            "platform_id": "douyin",
            "progress": progress,
            "speed": speed,
            "speed_bps": speed_bps,
            "eta": eta,
            "remaining_time": eta,
            "trace_id": trace_id,
            "save_dir": save_dir,
            "output_filename": output_filename,
            "thread_count": 8,
            "retry_count": 0,
            "write_status": "\u6b63\u5728\u5199\u5165\uff0839 \u4e2a\u5206\u7247\uff09",
            "merge_status": "\u7b49\u5f85\u5168\u90e8\u5206\u7247\u5b8c\u6210\u540e\u81ea\u52a8\u5408\u5e76",
            "source_url": source_url,
            "chunk_progress": {"completed": chunks_done, "total": 60, "percent": progress},
            "chunk_progress_label": active_chunk_progress_label(progress=progress, completed=chunks_done, total=60),
            "speed_trend": [3.2, 3.6, 3.1, 4.2, 3.8, 4.9, 3.5, 4.1, 3.9, 4.5, 3.7, 4.2],
            "speed_trend_label": speed,
            "detail_fields": active_detail_fields(
                title=title,
                platform=platform,
                save_dir=save_dir,
                output_filename=output_filename,
                source_url=source_url,
                trace_id=trace_id,
            ),
            "events": [
                {"time": "20:12:03", "message": "\u5f00\u59cb\u4e0b\u8f7d\uff1a" + title},
                {"time": "20:12:03", "message": "\u5df2\u89e3\u6790\u89c6\u9891\u4fe1\u606f\uff0c\u5206\u8fa8\u7387\uff1a1920x1080"},
                {"time": "20:12:04", "message": "\u5df2\u89e3\u6790\u5206\u7247\u7d22\u5f15\uff0c\u5171 60 \u4e2a\u5206\u7247"},
                {"time": "20:12:05", "message": "\u5199\u5165\u5206\u7247\uff1a#37\uff0848.5 MB / 96\uff09"},
                {"time": "20:12:06", "message": "\u5199\u5165\u5206\u7247\uff1a#38\uff0849.8 MB / 96\uff09"},
            ],
            "actions": ["delete"],
        })
    settings_snapshot = settings_snapshot_factory()
    basic_settings = settings_snapshot.get("基础设置", {})
    basic_settings["default_open_mode"] = DEFAULT_OPEN_MODE
    basic_settings["default_open_mode_label"] = open_mode_label(DEFAULT_OPEN_MODE)
    playback_settings = settings_snapshot.get("播放设置", {})
    playback_settings["default_player"] = DEFAULT_OPEN_MODE
    playback_settings["default_player_label"] = playback_player_label(DEFAULT_OPEN_MODE)
    playback_settings["manual_image_switch"] = False
    playback_settings["image_auto_advance_interval_seconds"] = 5
    for row in settings_snapshot.get("平台设置", []):
        if row.get("id") != "missav":
            continue
        row["proxy"] = "自定义"
        row["proxy_custom_active"] = True
        row["proxy_custom_value"] = "http://127.0.0.1:7890"
    settings_contract = settings_contract_factory(settings_snapshot)
    return {
        "pages": list(PAGE_DEFINITIONS),
        "queue_items": [
            {"id": "q1", "title": '\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5 | \u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929', "subtitle": f"{now_date} 18:24", "platform": '\u6296\u97f3', "platform_id": "douyin", "status": '\u5df2\u89e3\u6790', "source_url": "https://v.douyin.com/mock1", "trace_id": "dy_mock_001", "actions": ["delete"]},
            {"id": "q2", "title": '\u96e8\u540e\u5c71\u95f4\u7684\u6e05\u6668', "subtitle": f"{now_date} 18:22", "platform": '\u6296\u97f3', "platform_id": "douyin", "status": '\u5f85\u4e0b\u8f7d', "source_url": "https://v.douyin.com/mock2", "trace_id": "dy_mock_002", "actions": ["delete"]},
            {"id": "q3", "title": '\u57ce\u5e02\u591c\u666f\u5ef6\u65f6\u6444\u5f71', "subtitle": f"{now_date} 18:20", "platform": "Bilibili", "platform_id": "bilibili", "status": '\u6392\u961f\u4e2d', "source_url": "https://www.bilibili.com/video/BVmock", "trace_id": "bilibili_mock_003", "actions": ["delete"]},
        ] + [
            {
                "id": f"q{index}",
                "title": f"\u5f85\u4e0b\u8f7d\u793a\u4f8b\u4efb\u52a1 {index}",
                "subtitle": f"{now_date} 18:{20 - index:02d}",
                "platform": '\u6296\u97f3' if index % 2 else '\u5feb\u624b',
                "platform_id": "douyin" if index % 2 else "kuaishou",
                "status": ['\u5f85\u89e3\u6790', '\u89e3\u6790\u4e2d', '\u5df2\u89e3\u6790', '\u6392\u961f\u4e2d', '\u5df2\u5b58\u5728', '\u5f85\u4e0b\u8f7d'][index % 6],
                "source_url": f"https://example.com/mock/{index}",
                "trace_id": f"dy_mock_q_{index:03d}",
                "actions": ["delete"],
            }
            for index in range(4, 10)
        ],
        "active_downloads": active_items,
        "completed_items": [
            {
                "id": "c1",
                "title": '\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5 | \u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929',
                "thumbnail": "",
                "completed_at": f"{now_date} 18:24:35",
                "completed_at_table": "04-12 18:24",
                "duration": "00:00:24",
                "resolution": "1920 x 1080",
                "size": "24.6 MB",
                "size_bytes": 24_600_000,
                "format": "MP4",
                "download_speed": "4.2 MB/s",
                "download_speed_bps": 4_404_019,
                "local_path": 'D:\\desktop\\\u89c6\u9891\\\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5_20260412.mp4',
                "filename": '\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5_20260412.mp4',
                "save_dir": 'D:\\desktop\\\u89c6\u9891',
                "content_type": "video",
                "metadata_pending": False,
                "platform": '\u6296\u97f3',
                "actions": ["play", "open_directory", "delete"],
            }
        ] + [
            {
                "id": f"c{index}",
                "title": f"\u5df2\u5b8c\u6210\u793a\u4f8b\u89c6\u9891 {index:03d}",
                "thumbnail": "",
                "completed_at": f"{now_date} 17:{index % 60:02d}:10",
                "completed_at_table": f"04-12 17:{index % 60:02d}",
                "duration": "00:01:36",
                "resolution": "1920 x 1080",
                "size": f"{18 + index % 23}.4 MB",
                "size_bytes": (18 + index % 23) * 1_048_576,
                "format": "MP4",
                "download_speed": f"{1 + index % 5}.2 MB/s",
                "download_speed_bps": (1 + index % 5) * 1_258_291,
                "local_path": f"D:\\desktop\\\u89c6\u9891\\completed_{index:03d}.mp4",
                "filename": f"completed_{index:03d}.mp4",
                "save_dir": "D:\\desktop\\\u89c6\u9891",
                "content_type": "video",
                "metadata_pending": False,
                "platform": '\u6296\u97f3' if index % 2 else "Bilibili",
                "actions": ["play", "open_directory", "delete"],
            }
            for index in range(2, 129)
        ],
        "failed_items": [
            {
                "id": "f1",
                "title": '\u5357\u5cb3\u5c71\u95f4\u7684\u6e05\u6668',
                "failed_at": f"{now_date} 07:31:12",
                "failed_at_table": "04-12 07:31",
                "reason": '\u9700\u8981\u767b\u5f55',
                "reason_detail": '\u9700\u8981\u767b\u5f55',
                "reason_label": '\u9700\u8981\u767b\u5f55',
                "reason_icon_file": "action_user.png",
                "status": '\u5931\u8d25',
                "status_label": '\u5931\u8d25',
                "status_icon_file": "status_failed.png",
                "trace_id": "dy_failed_001",
                "platform": '\u6296\u97f3',
                "platform_id": "douyin",
                "source_url": "https://v.douyin.com/fail",
                "log_excerpt": ['\u8bf7\u6c42\u89c6\u9891\u94fe\u63a5', '\u63a5\u53e3\u8fd4\u56de\u9700\u8981\u767b\u5f55', '\u4efb\u52a1\u6807\u8bb0\u4e3a\u5931\u8d25'],
                "log_excerpt_items": [
                    {"time": f"{now_date} 07:31:02", "level": "INFO", "message": '\u8bf7\u6c42\u89c6\u9891\u94fe\u63a5', "icon_file": "log_level_info.png"},
                    {"time": f"{now_date} 07:31:09", "level": "WARN", "message": '\u63a5\u53e3\u8fd4\u56de\u9700\u8981\u767b\u5f55', "icon_file": "log_level_warn.png"},
                    {"time": f"{now_date} 07:31:12", "level": "ERROR", "message": '\u4efb\u52a1\u6807\u8bb0\u4e3a\u5931\u8d25', "icon_file": "log_level_error.png"},
                ],
                "solutions": [
                    {"title": '\u786e\u8ba4\u767b\u5f55\u6001', "description": '\u90e8\u5206\u5185\u5bb9\u9700\u8981\u767b\u5f55\u540e\u624d\u80fd\u8bbf\u95ee\uff0c\u8bf7\u68c0\u67e5\u767b\u5f55\u72b6\u6001\u3002', "icon_file": "action_user.png"},
                    {"title": '\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5', "description": '\u767b\u5f55\u540e\u91cd\u65b0\u590d\u5236\u5206\u4eab\u94fe\u63a5\u5e76\u91cd\u8bd5\u3002', "icon_file": "action_trace_link.png"},
                ],
                "actions": ["copy_diagnostics", "delete"],
            }
        ] + [
            {
                "id": f"f{index}",
                "title": f"\u5931\u8d25\u793a\u4f8b\u4efb\u52a1 {index}",
                "failed_at": f"{now_date} 07:{30 + index:02d}:12",
                "failed_at_table": f"04-12 07:{30 + index:02d}",
                "reason": ['\u7f51\u7edc\u8d85\u65f6', '\u94fe\u63a5\u5df2\u5931\u6548', '\u5e73\u53f0\u9700\u8981\u767b\u5f55'][index % 3],
                "reason_detail": ['\u7f51\u7edc\u8d85\u65f6', '\u94fe\u63a5\u5df2\u5931\u6548', '\u5e73\u53f0\u9700\u8981\u767b\u5f55'][index % 3],
                "reason_label": ['\u7f51\u7edc\u8d85\u65f6', '\u94fe\u63a5\u5931\u8d25', '\u9700\u8981\u767b\u5f55'][index % 3],
                "reason_icon_file": ["status_timeout.png", "action_trace_link.png", "action_user.png"][index % 3],
                "status": '\u5931\u8d25',
                "status_label": '\u5931\u8d25',
                "status_icon_file": "status_failed.png",
                "trace_id": f"dy_failed_{index:03d}",
                "platform": '\u6296\u97f3' if index % 2 else '\u5feb\u624b',
                "platform_id": "douyin" if index % 2 else "kuaishou",
                "source_url": f"https://example.com/fail/{index}",
                "log_excerpt": ['\u5f00\u59cb\u89e3\u6790\u94fe\u63a5', '\u4e0b\u8f7d\u5668\u8fd4\u56de\u9519\u8bef', '\u4efb\u52a1\u8fdb\u5165\u5931\u8d25\u5217\u8868'],
                "log_excerpt_items": [
                    {"time": f"{now_date} 07:{30 + index:02d}:04", "level": "INFO", "message": '\u5f00\u59cb\u89e3\u6790\u94fe\u63a5', "icon_file": "log_level_info.png"},
                    {"time": f"{now_date} 07:{30 + index:02d}:09", "level": "ERROR", "message": '\u4e0b\u8f7d\u5668\u8fd4\u56de\u9519\u8bef', "icon_file": "log_level_error.png"},
                    {"time": f"{now_date} 07:{30 + index:02d}:12", "level": "WARN", "message": '\u4efb\u52a1\u8fdb\u5165\u5931\u8d25\u5217\u8868', "icon_file": "log_level_warn.png"},
                ],
                "solutions": [
                    {"title": '\u91cd\u8bd5\u4efb\u52a1', "description": '\u7f51\u7edc\u6296\u52a8\u65f6\u53ef\u7a0d\u540e\u91cd\u8bd5\u3002', "icon_file": "action_refresh.png"},
                    {"title": '\u68c0\u67e5\u94fe\u63a5', "description": '\u786e\u8ba4\u5206\u4eab\u94fe\u63a5\u4ecd\u53ef\u8bbf\u95ee\u3002', "icon_file": "action_trace_link.png"},
                ],
                "actions": ["copy_diagnostics", "delete"],
            }
            for index in range(2, 8)
        ],
        "log_items": [
            {"time": f"{now_date} 18:24:35", "level": "INFO", "source": "下载器", "thread": "download-worker-1", "trace_id": "7f8c9b0d3e1a4b2c", "message_summary": "开始下载视频", "message": "开始下载视频", "detail": "{}", "stack": ""},
            {"time": f"{now_date} 18:25:03", "level": "ERROR", "source": "下载器", "thread": "download-worker-1", "trace_id": "b7c5d8e9f0a1b2c3", "message_summary": "下载失败：无法解析视频播放地址", "message": "下载失败：无法解析视频播放地址", "detail": "code: 1001", "stack": ""},
        ],
        "settings_snapshot": settings_snapshot,
        "settings_contract": settings_contract,
        "download_options": {
            "auto_retry": True,
            "max_retries": 3,
            "max_concurrent": 3,
            "video_only": False,
            "image_respects_concurrency": False,
        },
        "toolbox_items": toolbox_adapter.toolbox_items(),
        "toolbox_recent_items": toolbox_adapter.toolbox_recent_items(),
        "icon_manifest": icon_manifest(),
        "log_contract": log_contract(),
        "app_status": {
            "running_state": "\u8fd0\u884c\u4e2d",
            "status_indicator": "running",
            "download_speed": "10.4 MB/s",
            "download_speed_bps": 10_905_190,
            "completed_count": 128,
            "failed_count": 7,
            "version": "v3.6.17",
        },
    }
