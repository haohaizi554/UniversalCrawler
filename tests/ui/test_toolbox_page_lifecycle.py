from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit

from app.ui.components.settings_controls import SettingsComboBox
from app.ui.pages.toolbox_page import ToolboxPage


def _toolbox_snapshot() -> dict:
    return {
        "toolbox_items": [
            {
                "id": "file_verify",
                "title": "文件校验",
                "summary": "计算文件校验值",
                "input_example": "选择本地文件",
                "output_example": "显示 SHA256",
                "icon_file": "tool_file_verify.png",
            },
            {
                "id": "link_parser",
                "title": "链接解析",
                "summary": "解析链接",
                "input_example": "https://example.test/video",
                "output_example": "显示资源地址",
                "icon_file": "tool_link_parser.png",
            },
        ],
        "toolbox_display_projection": {
            "tool_id": "file_verify",
            "state": "ready",
            "status_text": "参数已验证",
            "form": {
                "fields": [
                    {
                        "id": "source",
                        "label": "文件",
                        "type": "text",
                        "placeholder": "选择一个文件",
                    },
                    {
                        "id": "algorithm",
                        "label": "算法",
                        "type": "choice",
                        "options": [
                            {"value": "sha256", "label": "SHA256"},
                            {"value": "md5", "label": "MD5"},
                        ],
                    },
                ],
                "values": {"source": "D:/media/demo.mp4", "algorithm": "sha256"},
            },
            "validation": {"state": "valid", "message": "参数可用"},
            "actions": {
                "tool_validate": True,
                "tool_start": True,
                "tool_cancel": False,
                "tool_open_result": False,
                "tool_clear_history": False,
            },
        },
        "toolbox_recent_items": [],
    }


class ToolboxPageLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.page = ToolboxPage()
        self.page.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_renders_parameter_controls_from_display_projection(self) -> None:
        self.page.render(_toolbox_snapshot())
        self.app.processEvents()

        self.assertEqual(self.page.current_tool_id, "file_verify")
        self.assertEqual(set(self.page.parameter_editors), {"source", "algorithm"})
        source = self.page.parameter_editors["source"]
        algorithm = self.page.parameter_editors["algorithm"]
        self.assertIsInstance(source, QLineEdit)
        self.assertEqual(source.text(), "D:/media/demo.mp4")
        self.assertEqual(source.placeholderText(), "选择一个文件")
        self.assertIsInstance(algorithm, SettingsComboBox)
        self.assertIsInstance(algorithm, QComboBox)
        self.assertEqual(algorithm.currentData(), "sha256")
        self.assertEqual(self.page.validation_label.text(), "参数可用")

    def test_emits_named_actions_and_preserves_legacy_start_signal(self) -> None:
        self.page.render(_toolbox_snapshot())
        actions: list[tuple[str, dict]] = []
        legacy: list[str] = []
        self.page.action_requested.connect(lambda action, payload: actions.append((action, payload)))
        self.page.tool_requested.connect(legacy.append)

        source = self.page.parameter_editors["source"]
        source.setText("D:/media/changed.mp4")
        self.page.validate_button.click()
        self.page.start_button.click()

        self.page.apply_display_projection(
            {
                "tool_id": "file_verify",
                "state": "running",
                "run_id": "run-7",
                "actions": {"tool_cancel": True},
            }
        )
        self.page.cancel_button.click()

        self.page.apply_display_projection(
            {
                "tool_id": "file_verify",
                "state": "success",
                "result": {"id": "result-9", "display_text": "校验完成"},
                "actions": {"tool_open_result": True, "tool_clear_history": True},
            }
        )
        self.page.open_result_button.click()
        self.page.clear_history_button.click()

        parameters = {"source": "D:/media/changed.mp4", "algorithm": "sha256"}
        self.assertEqual(
            actions,
            [
                ("tool_validate", {"tool_id": "file_verify", "parameters": parameters}),
                ("tool_start", {"tool_id": "file_verify", "parameters": parameters}),
                ("tool_cancel", {"tool_id": "file_verify", "run_id": "run-7"}),
                ("tool_open_result", {"tool_id": "file_verify", "result_id": "result-9"}),
                ("tool_clear_history", {"tool_id": "file_verify"}),
            ],
        )
        self.assertEqual(legacy, ["file_verify"])

    def test_projection_drives_running_success_result_and_history_views(self) -> None:
        snapshot = _toolbox_snapshot()
        snapshot["toolbox_display_projection"] = {
            "tool_id": "file_verify",
            "state": "running",
            "status_text": "正在计算",
            "progress": {"value": 63, "text": "63% - demo.mp4"},
            "actions": {"tool_validate": False, "tool_start": False, "tool_cancel": True},
        }
        self.page.render(snapshot)

        self.assertFalse(self.page.validate_button.isEnabled())
        self.assertFalse(self.page.start_button.isEnabled())
        self.assertTrue(self.page.cancel_button.isEnabled())
        self.assertTrue(self.page.progress_bar.isVisible())
        self.assertEqual(self.page.progress_bar.value(), 63)
        self.assertEqual(self.page.progress_label.text(), "63% - demo.mp4")

        self.page.apply_display_projection(
            {
                "tool_id": "file_verify",
                "state": "success",
                "status_text": "执行完成",
                "progress": {"value": 100, "text": "完成"},
                "result": {
                    "id": "result-9",
                    "display_text": "SHA256 校验完成",
                    "rows": [{"label": "摘要", "value": "abc123"}],
                    "raw_logs": ["RAW_LOG_MUST_NOT_RENDER"],
                },
                "history": [
                    {
                        "id": "history-1",
                        "title": "文件校验",
                        "status_text": "成功",
                        "finished_at": "2026-07-27 10:20",
                        "summary": "demo.mp4",
                    }
                ],
                "actions": {"tool_open_result": True, "tool_clear_history": True},
            }
        )

        result_text = self.page.result_view.toPlainText()
        self.assertIn("SHA256 校验完成", result_text)
        self.assertIn("摘要: abc123", result_text)
        self.assertNotIn("RAW_LOG_MUST_NOT_RENDER", result_text)
        self.assertIn("文件校验", self.page.recent.toPlainText())
        self.assertIn("成功", self.page.recent.toPlainText())
        self.assertTrue(self.page.open_result_button.isEnabled())
        self.assertTrue(self.page.clear_history_button.isEnabled())

    def test_validation_projection_clears_dirty_feedback_without_rebuilding_form(self) -> None:
        self.page.render(_toolbox_snapshot())
        source = self.page.parameter_editors["source"]
        source.setText("D:/media/changed.mp4")
        self.assertEqual(self.page.validation_label.text(), "参数已更改，请重新验证")

        self.page.apply_display_projection(
            {
                "tool_id": "file_verify",
                "state": "ready",
                "validation": {"state": "valid", "message": "参数重新有效"},
            }
        )

        self.assertIs(self.page.parameter_editors["source"], source)
        self.assertEqual(source.text(), "D:/media/changed.mp4")
        self.assertEqual(self.page.validation_label.text(), "参数重新有效")

    def test_display_batch_updates_projection_without_reading_raw_events(self) -> None:
        self.page.render(_toolbox_snapshot())

        self.page.apply_display_batch(
            {
                "projections": [
                    {
                        "tool_id": "file_verify",
                        "state": "running",
                        "status_text": "批次处理中",
                        "progress": {"value": 28, "text": "2 / 7"},
                    }
                ],
                "history": [
                    {
                        "id": "history-2",
                        "display_text": "昨天  文件校验  已取消",
                    }
                ],
                "events": [{"message": "RAW_EVENT_MUST_NOT_RENDER"}],
            }
        )

        self.assertEqual(self.page.state_label.text(), "批次处理中")
        self.assertEqual(self.page.progress_bar.value(), 28)
        self.assertIn("昨天  文件校验  已取消", self.page.recent.toPlainText())
        visible_text = "\n".join(
            (
                self.page.state_label.text(),
                self.page.progress_label.text(),
                self.page.result_view.toPlainText(),
                self.page.recent.toPlainText(),
            )
        )
        self.assertNotIn("RAW_EVENT_MUST_NOT_RENDER", visible_text)


if __name__ == "__main__":
    unittest.main()
