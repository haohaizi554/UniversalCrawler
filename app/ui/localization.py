from __future__ import annotations

import json
import re
from pathlib import Path

SUPPORTED_LANGUAGES = ("zh-CN", "en-US", "zh-TW")

_CATALOG_DIR = Path(__file__).with_name("i18n")


def _load_translation_catalogs() -> dict[str, dict[str, str]]:
    catalogs: dict[str, dict[str, str]] = {language: {} for language in SUPPORTED_LANGUAGES}
    for language in SUPPORTED_LANGUAGES:
        if language == "zh-CN":
            continue
        catalog_path = _CATALOG_DIR / f"{language}.json"
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        if isinstance(raw, dict):
            catalogs[language] = {str(key): str(value) for key, value in raw.items()}
    return catalogs


TRANSLATIONS: dict[str, dict[str, str]] = _load_translation_catalogs()


def normalize_language(language: str | None) -> str:
    value = str(language or "zh-CN")
    return value if value in SUPPORTED_LANGUAGES else "zh-CN"


def translation_variants(text: str) -> set[str]:
    value = str(text or "")
    variants = {value}
    for language in SUPPORTED_LANGUAGES:
        translated = TRANSLATIONS.get(language, {}).get(value)
        if translated:
            variants.add(translated)
    return variants


def is_translation_of(text: str, source: str) -> bool:
    return str(text or "") in translation_variants(str(source or ""))


def source_text_for_translation(text: str) -> str:
    value = str(text or "")
    if not value:
        return value
    candidates: list[str] = []
    for mapping in TRANSLATIONS.values():
        for source, translated in mapping.items():
            if translated == value and source not in candidates:
                candidates.append(source)
    return candidates[0] if len(candidates) == 1 else value


def tr(text: str, language: str | None) -> str:
    value = str(text or "")
    normalized = normalize_language(language)
    if "\n" in value:
        return "\n".join(tr(part, normalized) for part in value.split("\n"))
    if "\t" in value:
        return "\t".join(tr(part, normalized) for part in value.split("\t"))
    translated = TRANSLATIONS.get(normalized, {}).get(value)
    if translated is not None:
        return translated
    if normalized == "en-US":
        match = re.fullmatch(r"共\s*(\d+)\s*项", value)
        if match:
            return f"{match.group(1)} items"
        match = re.fullmatch(r"(\d+)\s*/\s*(\d+)\s*页", value)
        if match:
            return f"{match.group(1)} / {match.group(2)} pages"
        match = re.fullmatch(r"(\d+)\s*条/页", value)
        if match:
            return f"{match.group(1)} / page"
        for prefix, replacement in (
            ("工具: ", "Tool: "),
            ("说明: ", "Description: "),
            ("输入示例: ", "Input example: "),
            ("输出示例: ", "Output example: "),
            ("排队中: ", "Queued: "),
            ("排队中：", "Queued: "),
            ("已解析: ", "Parsed: "),
            ("已解析：", "Parsed: "),
            ("待下载: ", "Waiting: "),
            ("待下载：", "Waiting: "),
            ("待解析: ", "Pending parse: "),
            ("待解析：", "Pending parse: "),
            ("解析中: ", "Parsing: "),
            ("解析中：", "Parsing: "),
            ("已存在: ", "Exists: "),
            ("已存在：", "Exists: "),
        ):
            if value.startswith(prefix):
                return replacement + value[len(prefix):]
    if normalized == "zh-TW":
        match = re.fullmatch(r"共\s*(\d+)\s*项", value)
        if match:
            return f"共 {match.group(1)} 項"
        match = re.fullmatch(r"(\d+)\s*/\s*(\d+)\s*页", value)
        if match:
            return f"{match.group(1)} / {match.group(2)} 頁"
        match = re.fullmatch(r"(\d+)\s*条/页", value)
        if match:
            return f"{match.group(1)} 條/頁"
        for prefix, replacement in (
            ("工具: ", "工具: "),
            ("说明: ", "說明: "),
            ("输入示例: ", "輸入範例: "),
            ("输出示例: ", "輸出範例: "),
            ("排队中: ", "排隊中: "),
            ("排队中：", "排隊中: "),
            ("已解析: ", "已解析: "),
            ("已解析：", "已解析: "),
            ("待下载: ", "待下載: "),
            ("待下载：", "待下載: "),
            ("待解析: ", "待解析: "),
            ("待解析：", "待解析: "),
            ("解析中: ", "解析中: "),
            ("解析中：", "解析中: "),
            ("已存在: ", "已存在: "),
            ("已存在：", "已存在: "),
        ):
            if value.startswith(prefix):
                return replacement + value[len(prefix):]
    return value
