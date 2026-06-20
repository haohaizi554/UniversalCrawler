"""打包链路共享的项目元数据。"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"

APP_NAME = "UniversalCrawlerPro"
WEBUI_NAME = "CrawlerWebPortal"
APP_DISPLAY_NAME = "Universal CrawlerPro"
WEBUI_DISPLAY_NAME = "Crawler WebPortal"
APP_PUBLISHER = "UCrawl Team"
APP_USER_MODEL_ID = "ucrawl.universalcrawlerpro.main"
WEBUI_USER_MODEL_ID = "ucrawl.universalcrawlerpro.web"

def _project_section_text() -> str:
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^\[project\]\s*(.*?)^\[", content + "\n[", re.MULTILINE)
    if not match:
        raise RuntimeError(f"未在 {PYPROJECT_FILE} 中找到 [project] 段")
    return match.group(1)

def _project_field(field_name: str) -> str:
    section = _project_section_text()
    match = re.search(rf'^\s*{re.escape(field_name)}\s*=\s*"([^"]+)"', section, re.MULTILINE)
    if not match:
        raise RuntimeError(f"未在 pyproject.toml 的 [project] 段中找到 {field_name}")
    return match.group(1).strip()

PACKAGE_NAME = _project_field("name")
PACKAGE_VERSION = _project_field("version")

def sanitize_for_filename(value: str) -> str:
    """将版本号等字段转为适合文件名的安全片段。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)

INSTALLER_BASENAME = f"{APP_NAME}_Setup_{sanitize_for_filename(PACKAGE_VERSION)}"
