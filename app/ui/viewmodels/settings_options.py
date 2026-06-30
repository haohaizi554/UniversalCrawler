from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QComboBox


def normalize_combo_options(options: list[Any], current: Any = "") -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for option in list(options or []):
        if isinstance(option, dict):
            value = str(option.get("value") or option.get("id") or option.get("label") or "")
            label = str(option.get("label") or value)
        elif isinstance(option, (tuple, list)) and option:
            value = str(option[0])
            label = str(option[1] if len(option) > 1 else option[0])
        else:
            value = str(option)
            label = value
        if value:
            normalized.append((value, label))
    current_text = str(current or "")
    if current_text and not any(value == current_text for value, _label in normalized):
        normalized.insert(0, (current_text, current_text))
    if not normalized:
        normalized.append((current_text, current_text))
    return normalized


def proxy_port_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    if "/" in text:
        text = text.split("/", 1)[0]
    if ":" in text:
        candidate = text.rsplit(":", 1)[-1].strip()
        if candidate.isdigit():
            return candidate
    if "(" in text and ")" in text:
        candidate = text.rsplit("(", 1)[-1].split(")", 1)[0].strip()
        if candidate.isdigit():
            return candidate
    if lowered.startswith(("clash", "v2ray", "sing-box", "nekoray")):
        digits = "".join(ch if ch.isdigit() else " " for ch in text).split()
        return digits[-1] if digits else ""
    return text if text.isdigit() else ""


def proxy_endpoint_from_port(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
        return text
    if text.isdigit():
        return f"http://127.0.0.1:{text}"
    if ":" in text:
        return f"http://{text}"
    return text


def compact_proxy_options(options: list[Any], current: Any = "") -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for value, label in normalize_combo_options(options, current):
        display = label
        port = proxy_port_text(label)
        if port and "(" in display:
            display = display.rsplit("(", 1)[0].strip()
        if "HTTP/SOCKS5" in display:
            display = value
        if value in {"直连", "自定义"}:
            display = value
        compact.append({"value": value, "label": display})
    return compact


def current_combo_value(combo: QComboBox) -> str:
    if combo.isEditable():
        current_index = combo.currentIndex()
        current_text = str(combo.currentText())
        if current_index >= 0 and current_text == str(combo.itemText(current_index)):
            data = combo.itemData(current_index)
            return str(data if data is not None else current_text)
        return current_text
    data = combo.currentData()
    return str(data if data is not None else combo.currentText())


def current_combo_int_value(combo: QComboBox, fallback: int = 0) -> int:
    try:
        return int(current_combo_value(combo))
    except (TypeError, ValueError):
        return int(fallback)


def platform_proxy_policy(platform_id: str, platform_name: str) -> dict[str, Any]:
    pid = str(platform_id or "").strip().lower()
    pname = str(platform_name or "").strip().lower()
    editable = pid == "missav" or "missav" in pname
    return {
        "editable": editable,
        "tooltip": "" if editable else "该平台默认使用系统代理，无需单独设置",
    }
