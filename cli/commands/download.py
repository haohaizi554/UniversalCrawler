"""download 子命令：下载指定的视频。

ucrawl download <video_id> [--save-dir <dir>] [--url <url>]
"""

from __future__ import annotations

import argparse
import json
import sys

from cli.sdk import UcrawlSDK


def add_download_arguments(parser: argparse.ArgumentParser) -> None:
    """为 download 子命令添加参数。"""
    parser.add_argument("video_id", help="视频 ID")
    parser.add_argument(
        "--save-dir", "-d",
        default="downloads",
        help="保存目录 (默认: downloads)",
    )
    parser.add_argument("--url", help="视频 URL (如果已有)")


def handle_download_command(args: argparse.Namespace) -> int:
    """执行 download 命令。"""
    sdk = UcrawlSDK(save_dir=args.save_dir, verbose=True)

    # 如果提供了 URL，直接下载
    if args.url:
        # 创建一个临时的 VideoItem
        from app.models.video_item import VideoItem
        item = VideoItem(
            id=args.video_id,
            url=args.url,
            title=args.video_id,
            source="",
            status="⏳ 等待中",
            progress=0,
        )
        # 添加到下载队列
        from app.config import cfg
        from app.core.download_manager import DownloadManager

        dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))
        dl_manager.add_task(item, args.save_dir)

        # 等待下载完成
        _wait_download(dl_manager)

        if item.status == "✅ 完成":
            sys.stdout.write(json.dumps({
                "status": "ok",
                "video_id": args.video_id,
                "local_path": item.local_path,
            }, ensure_ascii=False, indent=2) + "\n")
            return 0
        else:
            sys.stderr.write(f"❌ 下载失败: {item.status}\n")
            return 1

    # 否则，从已知视频中查找
    sys.stderr.write(f"❌ 视频 {args.video_id} 未找到，请先搜索获取\n")
    return 1


def _wait_download(dl_manager, timeout: float = 300) -> None:
    """等待下载完成。"""
    import time
    from PyQt6.QtWidgets import QApplication

    deadline = time.time() + timeout
    while time.time() < deadline:
        with dl_manager._workers_lock:
            active = len(dl_manager.workers)
        queued = dl_manager.queue.qsize()
        if active == 0 and queued == 0:
            break
        app = QApplication.instance()
        if app:
            app.processEvents()
        time.sleep(0.5)
