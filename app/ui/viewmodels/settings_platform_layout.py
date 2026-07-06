from __future__ import annotations

from typing import Any, Callable, Mapping

from PyQt6.QtGui import QFontMetrics

from app.ui.viewmodels.settings_options import normalize_combo_options


PLATFORM_DETAIL_COL_WIDTHS: dict[str, int] = {
    "name": 122,
    "auth": 112,
    "count": 210,
    "timeout": 132,
    "proxy": 294,
}
CUSTOM_PROXY_CONTROL_MIN_WIDTH = 230


def combo_label_min_width(
    options: list[Any],
    current: Any,
    *,
    translate: Callable[[Any], str],
    metrics: QFontMetrics,
    floor: int,
    label_padding: int,
) -> int:
    labels = [translate(label) for _value, label in normalize_combo_options(options, current)]
    widest = max((metrics.horizontalAdvance(label) for label in labels), default=0)
    return max(int(floor), widest + int(label_padding))


def platform_option_min_width(
    rows: list[dict[str, Any]] | None,
    option_key: str,
    default_options: list[Any],
    current_key: str,
    default_current: Any,
    *,
    translate: Callable[[Any], str],
    metrics: QFontMetrics,
    floor: int,
    label_padding: int,
) -> int:
    width = combo_label_min_width(
        default_options,
        default_current,
        translate=translate,
        metrics=metrics,
        floor=floor,
        label_padding=label_padding,
    )
    for row in rows or []:
        width = max(
            width,
            combo_label_min_width(
                list(row.get(option_key) or default_options),
                row.get(current_key, default_current),
                translate=translate,
                metrics=metrics,
                floor=floor,
                label_padding=label_padding,
            ),
        )
    return width


def platform_column_widths(
    rows: list[dict[str, Any]] | None,
    *,
    content_width: int,
    translate: Callable[[Any], str],
    metrics: QFontMetrics,
    count_options: list[Any],
    timeout_options: list[Any],
    label_padding: int,
    base_widths: Mapping[str, int] | None = None,
) -> dict[str, int]:
    base = dict(base_widths or PLATFORM_DETAIL_COL_WIDTHS)
    base["count"] = max(
        base["count"],
        platform_option_min_width(
            rows,
            "count_options",
            count_options,
            "default_count",
            20,
            translate=translate,
            metrics=metrics,
            floor=180,
            label_padding=label_padding,
        ),
    )
    base["timeout"] = max(
        base["timeout"],
        platform_option_min_width(
            rows,
            "timeout_options",
            timeout_options,
            "default_timeout",
            60,
            translate=translate,
            metrics=metrics,
            floor=132,
            label_padding=label_padding,
        ),
    )
    has_custom_proxy = any(bool(row.get("proxy_custom_allowed")) for row in rows or [])

    content_width = max(280, int(content_width))
    base_total = sum(base.values())
    if content_width >= base_total:
        return base

    minimums = {
        "name": 70,
        "auth": 78,
        "count": min(base["count"], max(160, base["count"] - 28)),
        "timeout": min(base["timeout"], max(132, base["timeout"] - 12)),
        "proxy": CUSTOM_PROXY_CONTROL_MIN_WIDTH if has_custom_proxy else 112,
    }
    min_total = sum(minimums.values())
    if content_width <= min_total:
        if has_custom_proxy:
            proxy_width = min(CUSTOM_PROXY_CONTROL_MIN_WIDTH, max(150, int(content_width * 0.30)))
            name_width = 48
            auth_width = 54
            timeout_width = min(base["timeout"], 132)
            count_width = content_width - name_width - auth_width - timeout_width - proxy_width
            if count_width < 72:
                shortage = 72 - count_width
                borrow = min(shortage, max(0, timeout_width - 104))
                timeout_width -= borrow
                count_width += borrow
            if count_width < 72:
                shortage = 72 - count_width
                borrow = min(shortage, max(0, proxy_width - 140))
                proxy_width -= borrow
                count_width += borrow
            if count_width < 72:
                shortage = 72 - count_width
                borrow = min(shortage, max(0, auth_width - 48))
                auth_width -= borrow
                count_width += borrow
            if count_width < 72:
                shortage = 72 - count_width
                borrow = min(shortage, max(0, name_width - 44))
                name_width -= borrow
                count_width += borrow
            count_width = max(52, count_width)
        else:
            name_width = 58
            auth_width = 64
            proxy_floor = 72
            count_floor = 100
            timeout_floor = 132
            timeout_width = min(
                base["timeout"],
                max(timeout_floor, content_width - name_width - auth_width - proxy_floor - count_floor),
            )
            count_width = max(
                count_floor,
                min(base["count"], content_width - name_width - auth_width - proxy_floor - timeout_width),
            )
            proxy_width = max(
                52,
                content_width - name_width - auth_width - timeout_width - count_width,
            )
        widths = {
            "name": name_width,
            "auth": auth_width,
            "count": count_width,
            "timeout": timeout_width,
            "proxy": proxy_width,
        }
    else:
        extra = content_width - min_total
        base_extra = base_total - min_total
        widths = {
            key: minimums[key] + int(extra * (base[key] - minimums[key]) / max(1, base_extra))
            for key in base
        }

    used_without_proxy = widths["name"] + widths["auth"] + widths["count"] + widths["timeout"]
    remaining_proxy_width = content_width - used_without_proxy
    if has_custom_proxy:
        proxy_floor = min(CUSTOM_PROXY_CONTROL_MIN_WIDTH, max(52, remaining_proxy_width))
    else:
        proxy_floor = 80 if remaining_proxy_width >= 80 else 52
    widths["proxy"] = max(proxy_floor, content_width - used_without_proxy)
    return widths
