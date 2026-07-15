"""GUI/WebUI 共用的纯状态栏投影，不读取或修改运行时对象。"""

from __future__ import annotations

import re
from typing import Any, Mapping


def format_transfer_speed(bps: int) -> str:
    if bps <= 0:
        return "0 B/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(bps)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.1f} {units[index]}"


def parse_speed_string(value: str | None) -> int:
    """解析前端已有的速度字符串，兼容旧下载器只上报文本速度的路径。"""
    text = str(value or "").strip()
    if not text:
        return 0
    match = re.search(
        r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>B|KB|KIB|MB|MIB|GB|GIB)(?:/S|PS)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0
    try:
        amount = float(match.group("amount"))
    except ValueError:
        return 0
    if amount <= 0:
        return 0
    unit = match.group("unit").upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024**2,
        "MIB": 1024**2,
        "GB": 1024**3,
        "GIB": 1024**3,
    }
    return int(amount * multipliers.get(unit, 1))


def aggregate_speed_bps(active_downloads: list[Mapping[str, Any]]) -> int:
    """汇总活动下载速度；优先使用结构化 bps，缺失时解析展示字符串。"""
    total_bps = 0
    for item in active_downloads:
        speed_bps = item.get("speed_bps")
        if speed_bps:
            total_bps += int(speed_bps)
            continue
        total_bps += parse_speed_string(str(item.get("speed") or ""))
    return total_bps


def aggregate_speed(active_downloads: list[Mapping[str, Any]]) -> str:
    return format_transfer_speed(aggregate_speed_bps(active_downloads))


def build_app_status(
    *,
    running: bool,
    running_state: str,
    queue_count: int,
    active_count: int,
    completed_count: int,
    failed_count: int,
    active_downloads: list[Mapping[str, Any]],
    version: str,
) -> dict[str, Any]:
    """构建状态栏摘要，失败数只影响 indicator，不覆盖运行态文本。"""
    speed_bps = aggregate_speed_bps(active_downloads)
    indicator = "running" if running else ("error" if failed_count > 0 else "idle")
    return {
        "running_state": "运行中" if running else running_state,
        "status_indicator": indicator,
        "download_speed": format_transfer_speed(speed_bps),
        "download_speed_bps": speed_bps,
        "queue_count": queue_count,
        "active_count": active_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "version": f"v{version}",
    }
