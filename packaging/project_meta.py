"""打包链路共享的项目元数据。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.version import __version__

APP_NAME = "UniversalCrawlerPro"
WEBUI_NAME = "CrawlerWebPortal"
LAUNCHER_NAME = "UCrawlLauncher"
CLI_LAUNCHER_NAME = "UCrawlCLI"
UPDATER_HELPER_NAME = "updater_helper"
APP_DISPLAY_NAME = "Universal Crawler Pro"
WEBUI_DISPLAY_NAME = "Crawler Web Portal"
LAUNCHER_DISPLAY_NAME = f"{APP_DISPLAY_NAME} 启动中心"
CLI_LAUNCHER_DISPLAY_NAME = f"{APP_DISPLAY_NAME} 命令行"
APP_PUBLISHER = "UCrawl Team"
APP_USER_MODEL_ID = "ucrawl.universalcrawlerpro.main"
WEBUI_USER_MODEL_ID = "ucrawl.universalcrawlerpro.web"
APP_EXE_NAME = f"{APP_NAME}.exe"
WEBUI_EXE_NAME = f"{WEBUI_NAME}.exe"
LAUNCHER_EXE_NAME = f"{LAUNCHER_NAME}.exe"
CLI_LAUNCHER_EXE_NAME = f"{CLI_LAUNCHER_NAME}.exe"
UPDATER_HELPER_EXE_NAME = f"{UPDATER_HELPER_NAME}.exe"
APP_ICON_NAME = "favicon.ico"
WEBUI_ICON_NAME = "Web.ico"
REPORT_ICON_NAME = "analytics.ico"
DIST_DIR_NAME = APP_NAME
INSTALL_DIR_NAME = APP_NAME
FORBIDDEN_USER_DATA_BASENAMES = (
    "config.json",
    "bili_auth.json",
    "ks_auth.json",
    "dy_auth.json",
    "xhs_auth.json",
)


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
PACKAGE_VERSION = __version__

def sanitize_for_filename(value: str) -> str:
    """将版本号等字段转为适合文件名的安全片段。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)

INSTALLER_BASENAME = f"{APP_NAME}_Setup_{sanitize_for_filename(PACKAGE_VERSION)}"
