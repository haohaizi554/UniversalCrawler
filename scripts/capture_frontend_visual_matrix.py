"""从同一前端快照采集可复现的 GUI/WebUI 一致性证据。"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

if "--native-gui" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("UCRAWL_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from PIL import Image, ImageDraw
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.services.frontend_state_service import FrontendStateService
from app.ui.dialogs.selection import SelectionDialog
from app.ui.dialogs.update_check import UpdateCheckDialog
from app.ui.layout.app_shell import AppShell
from app.ui.styles.themes import apply_application_theme
from tests.web_browser_support import _running_server

OUTPUT = ROOT / "docx" / "visual_audit" / "screenshots"
GUI_SIZE = (1440, 900)


def _refresh_visual_log_times(snapshot: dict) -> None:
    now = datetime.now()
    for index, item in enumerate(snapshot.get("log_items") or []):
        item["time"] = (now - timedelta(seconds=index * 7)).strftime("%Y-%m-%d %H:%M:%S")


def _assert_image(path: Path) -> None:
    with Image.open(path) as image:
        colors = image.convert("RGB").resize((160, 100)).getcolors(maxcolors=160 * 100)
        if image.width < 600 or image.height < 400 or not colors or len(colors) < 8:
            raise RuntimeError(f"visual capture is blank or undersized: {path}")


def _shutdown_shell(shell: AppShell, app: QApplication) -> None:
    logs = shell.pages.get("logs")
    for name in ("_log_query_worker", "_log_detail_worker", "_log_detail_export_worker"):
        worker = getattr(logs, name, None)
        shutdown = getattr(worker, "shutdown", None)
        if callable(shutdown):
            shutdown()
    shell.close()
    shell.deleteLater()
    app.processEvents()


def capture_gui() -> list[Path]:
    app = QApplication.instance() or QApplication([])
    apply_application_theme(False)
    shell = AppShell(is_dark_theme=False, style_provider=app)
    shell.resize(*GUI_SIZE)
    snapshot = deepcopy(FrontendStateService.mock_snapshot())
    _refresh_visual_log_times(snapshot)
    long_failure = (
        "连接在读取媒体流时被远程主机中断；系统已经保留 Trace ID、来源平台与原始路径，"
        "可在网络恢复后重新获取链接。"
    )
    if snapshot.get("failed_items"):
        snapshot["failed_items"][0]["reason"] = long_failure * 3
        snapshot["failed_items"][0]["log_excerpt"] = [long_failure * 2]
    shell.render(snapshot)
    shell.show()
    app.processEvents()

    captures: list[Path] = []
    page_sections = {
        "queue": "queue_items",
        "active": "active_downloads",
        "completed": "completed_items",
        "failed": "failed_items",
        "logs": "log_items",
        "toolbox": "toolbox_items",
    }
    for page_id, section in page_sections.items():
        shell.show_page(page_id)
        page = shell.pages[page_id]
        expected = len(snapshot.get(section) or [])
        for _ in range(200):
            app.processEvents()
            table = getattr(page, "table", None)
            model = table.model() if table is not None else None
            if model is None or model.rowCount() >= min(expected, 20):
                break
            QTest.qWait(10)
        if page_id == "logs" and expected:
            for _ in range(200):
                app.processEvents()
                if getattr(page, "_current_detail_result", None) is not None:
                    break
                QTest.qWait(10)
            if getattr(page, "_current_detail_result", None) is None:
                raise RuntimeError("GUI log detail worker did not reach a stable rendered state")
        target = OUTPUT / f"gui_{page_id}_zh_light.png"
        shell.grab().save(os.fspath(target), "PNG")
        _assert_image(target)
        captures.append(target)

    appearance = snapshot["settings_snapshot"]["外观设置"]
    appearance.update({"language": "en-US", "theme": "dark"})
    apply_application_theme(True)
    shell.apply_theme(True)
    shell.render(snapshot)
    shell.show_page("settings")
    app.processEvents()
    target = OUTPUT / "gui_settings_en_dark.png"
    shell.grab().save(os.fspath(target), "PNG")
    _assert_image(target)
    captures.append(target)

    dialog_items = [
        {"title": "P01_ [Hi-Res] A long title that verifies the selection column and action buttons remain readable"},
        {"title": "P02_ Bilibili collection item with a second descriptive line"},
        {"title": "P03_ MissAV item with a long source description and stable checkbox alignment"},
    ]
    selection_dialog = SelectionDialog(shell, items=dialog_items, language="en-US")
    selection_dialog.show()
    app.processEvents()
    target = OUTPUT / "gui_selection_en_dark.png"
    selection_dialog.grab().save(os.fspath(target), "PNG")
    _assert_image(target)
    captures.append(target)
    selection_dialog.close()
    selection_dialog.deleteLater()

    update_dialog = UpdateCheckDialog(
        shell,
        title="检查更新",
        message="检测到新版本",
        details="A verified release is ready. Review the signed package before installing and restarting.",
        primary_text="下载并验证",
        secondary_text="确定",
        status="available",
        local_version="v3.6.17",
        latest_version="v3.6.18",
        release_url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",
        language="en-US",
    )
    update_dialog.resize(680, 560)
    update_dialog.show()
    app.processEvents()
    target = OUTPUT / "gui_update_en_dark.png"
    update_dialog.grab().save(os.fspath(target), "PNG")
    _assert_image(target)
    captures.append(target)
    update_dialog.close()
    update_dialog.deleteLater()
    _shutdown_shell(shell, app)
    return captures


def _seed_web_snapshot(page, snapshot: dict) -> None:
    page.evaluate(
        """
        snapshot => {
          replaceFrontendState(snapshot);
          renderAll();
        }
        """,
        snapshot,
    )


def _assert_web_geometry(page) -> None:
    geometry = page.evaluate(
        """
        () => {
          const active = document.querySelector('.page.active');
          const rect = active?.getBoundingClientRect();
          const status = document.querySelector('.status-bar');
          const statusRect = status?.getBoundingClientRect();
          const activeTitle = active?.id === 'page-active' ? active.querySelector('thead th:first-child') : null;
          const clippedNavigation = Array.from(document.querySelectorAll('.nav-item b'))
            .filter(label => label.scrollWidth > label.clientWidth + 1)
            .map(label => label.textContent.trim());
          const clippedFailedHeaders = active?.id === 'page-failed'
            ? Array.from(active.querySelectorAll('thead th'))
                .filter(cell => cell.scrollWidth > cell.clientWidth + 1)
                .map(cell => cell.textContent.trim())
            : [];
          const clippedFailedStatuses = active?.id === 'page-failed'
            ? Array.from(active.querySelectorAll('tbody td:nth-child(4)'))
                .filter(cell => cell.scrollWidth > cell.clientWidth + 1)
                .map(cell => cell.textContent.trim())
            : [];
          const clippedButtons = Array.from(document.querySelectorAll('button'))
            .filter(button => {
              const style = getComputedStyle(button);
              const rect = button.getBoundingClientRect();
              return button.textContent.trim()
                && style.display !== 'none'
                && style.visibility !== 'hidden'
                && rect.width > 0
                && rect.height > 0
                && button.scrollWidth > button.clientWidth + 1;
            })
            .map(button => ({
              text: button.textContent.trim(),
              clientWidth: button.clientWidth,
              scrollWidth: button.scrollWidth,
            }));
          return {
            documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
            activeRight: rect ? rect.right - window.innerWidth : 0,
            activeBottom: rect ? rect.bottom - window.innerHeight : 0,
            statusTop: statusRect ? statusRect.top : null,
            statusBottom: statusRect ? statusRect.bottom - window.innerHeight : null,
            activeTitleWidth: activeTitle ? activeTitle.getBoundingClientRect().width : null,
            clippedButtons,
            clippedNavigation,
            clippedFailedHeaders,
            clippedFailedStatuses,
            narrow: window.innerWidth <= 980,
          };
        }
        """
    )
    if geometry["documentOverflow"] > 1 or geometry["activeRight"] > 1:
        raise RuntimeError(f"WebUI horizontal clipping detected: {geometry}")
    if geometry["narrow"] and (
        geometry["statusTop"] is None
        or geometry["statusTop"] < -1
        or geometry["statusBottom"] is None
        or geometry["statusBottom"] > 1
    ):
        raise RuntimeError(f"WebUI narrow status bar left the viewport: {geometry}")
    if geometry["activeTitleWidth"] is not None and geometry["activeTitleWidth"] < 120:
        raise RuntimeError(f"WebUI active-download title column collapsed: {geometry}")
    if geometry["clippedButtons"]:
        raise RuntimeError(f"WebUI command text clipping detected: {geometry}")
    if geometry["clippedNavigation"]:
        raise RuntimeError(f"WebUI navigation text clipping detected: {geometry}")
    if geometry["clippedFailedHeaders"] or geometry["clippedFailedStatuses"]:
        raise RuntimeError(f"WebUI failed-table semantic text clipping detected: {geometry}")


def capture_web() -> list[Path]:
    from playwright.sync_api import sync_playwright

    captures: list[Path] = []
    scenarios = (
        ("queue", "zh-CN", "light", {"width": 1440, "height": 900}, "web_queue_zh_light.png"),
        ("active", "zh-CN", "light", {"width": 1120, "height": 760}, "web_active_zh_compact.png"),
        ("failed", "en-US", "dark", {"width": 980, "height": 820}, "web_failed_en_dark_long.png"),
        ("failed", "zh-CN", "light", {"width": 1440, "height": 900}, "web_failed_zh_light.png"),
        ("completed", "zh-CN", "light", {"width": 1440, "height": 900}, "web_completed_zh_light.png"),
        ("logs", "zh-CN", "light", {"width": 1440, "height": 900}, "web_logs_zh_light.png"),
        ("toolbox", "zh-CN", "light", {"width": 1440, "height": 900}, "web_toolbox_zh_light.png"),
        ("settings", "en-US", "dark", {"width": 1440, "height": 900}, "web_settings_en_dark.png"),
        ("queue", "zh-TW", "light", {"width": 640, "height": 900}, "web_queue_zh_tw_narrow.png"),
    )
    snapshot = deepcopy(FrontendStateService.mock_snapshot())
    _refresh_visual_log_times(snapshot)
    long_failure = (
        "Connection interrupted while reading a long media stream; Trace ID, platform, and source path "
        "remain available for diagnosis. "
    )
    if snapshot.get("failed_items"):
        snapshot["failed_items"][0]["reason"] = long_failure * 5
        snapshot["failed_items"][0]["log_excerpt"] = [long_failure * 3]
    with _running_server() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for page_id, language, theme, viewport, filename in scenarios:
                context = browser.new_context(viewport=viewport)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector("#app-shell", state="visible", timeout=5000)
                page.wait_for_function("window.__ucrawlFrontendStateLoaded === true", timeout=5000)
                _seed_web_snapshot(page, deepcopy(snapshot))
                page.evaluate(
                    """([pageId, language, theme]) => {
                      const appearance = frontendState.settings_snapshot['外观设置'] || {};
                      appearance.language = language;
                      appearance.theme = theme;
                      applyAppearance(appearance);
                      switchPage(pageId);
                    }""",
                    [page_id, language, theme],
                )
                if page_id == "logs":
                    page.wait_for_selector("#logDetail .log-detail-readable", state="visible", timeout=5000)
                _assert_web_geometry(page)
                target = OUTPUT / filename
                page.screenshot(path=os.fspath(target), full_page=False)
                _assert_image(target)
                captures.append(target)
                context.close()

            dialog_items = [
                {"title": "P01_ [Hi-Res] A long title that verifies the selection column and action buttons remain readable"},
                {"title": "P02_ Bilibili collection item with a second descriptive line"},
                {"title": "P03_ MissAV item with a long source description and stable checkbox alignment"},
            ]
            context = browser.new_context(viewport={"width": 1000, "height": 760})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("window.__ucrawlFrontendStateLoaded === true", timeout=5000)
            _seed_web_snapshot(page, deepcopy(snapshot))
            page.evaluate(
                """items => {
                  const appearance = frontendState.settings_snapshot['外观设置'] || {};
                  appearance.language = 'en-US';
                  appearance.theme = 'dark';
                  applyAppearance(appearance);
                  window.UcpDialogController.showSelection(items);
                }""",
                dialog_items,
            )
            page.wait_for_selector("#selectionModal", state="visible", timeout=5000)
            _assert_web_geometry(page)
            target = OUTPUT / "web_selection_en_dark.png"
            page.screenshot(path=os.fspath(target), full_page=False)
            _assert_image(target)
            captures.append(target)
            context.close()

            context = browser.new_context(viewport={"width": 1000, "height": 760})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("window.__ucrawlFrontendStateLoaded === true", timeout=5000)
            _seed_web_snapshot(page, deepcopy(snapshot))
            page.evaluate(
                """() => {
                  const appearance = frontendState.settings_snapshot['外观设置'] || {};
                  appearance.language = 'en-US';
                  appearance.theme = 'dark';
                  applyAppearance(appearance);
                  renderCurrentPage();
                }"""
            )
            page.route(
                "**/api/update/check",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"status":"available","local_version":"v3.6.17",'
                        '"latest_version":"v3.6.18","notes":"A verified release is ready. '
                        'Review the signed package before installing and restarting.",'
                        '"html_url":"https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",'
                        '"can_prepare":true}'
                    ),
                ),
            )
            page.evaluate("showUpdateCheckModal()")
            page.wait_for_function(
                "document.getElementById('updateModal')?.getAttribute('aria-busy') === 'false'",
                timeout=5000,
            )
            _assert_web_geometry(page)
            target = OUTPUT / "web_update_en_dark.png"
            page.screenshot(path=os.fspath(target), full_page=False)
            _assert_image(target)
            captures.append(target)
            context.close()
        finally:
            browser.close()
    return captures


def build_contact_sheet(paths: list[Path]) -> Path:
    cells: list[tuple[str, Image.Image]] = []
    for path in paths:
        image = Image.open(path).convert("RGB")
        image.thumbnail((700, 440), Image.Resampling.LANCZOS)
        cells.append((path.stem, image.copy()))
        image.close()
    width = 1460
    row_height = 490
    sheet = Image.new("RGB", (width, row_height * ((len(cells) + 1) // 2)), "#eef2f7")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(cells):
        x = 20 + (index % 2) * 720
        y = 36 + (index // 2) * row_height
        draw.text((x, y - 24), label, fill="#111827")
        sheet.paste(image, (x, y))
    target = OUTPUT / "gui_web_contact_sheet.png"
    sheet.save(target, "PNG")
    _assert_image(target)
    return target


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    captures = [*capture_gui(), *capture_web()]
    contact_sheet = build_contact_sheet(captures)
    print(f"captured {len(captures)} views; contact sheet: {contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
