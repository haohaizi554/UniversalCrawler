"""所有前端共用的稳定日志中心标签与分类顺序。"""

from __future__ import annotations

LOG_CATEGORY_LABELS: dict[str, str] = {
    "all": "全部日志",
    "crawl": "采集日志",
    "download": "下载日志",
    "system": "系统日志",
    "performance": "性能日志",
    "error": "错误日志",
}


def log_contract() -> dict[str, object]:
    return {
        "category_order": list(LOG_CATEGORY_LABELS),
        "category_labels": dict(LOG_CATEGORY_LABELS),
    }
