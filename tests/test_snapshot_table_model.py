import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

from app.ui.pages.common import SnapshotActionDelegate
from app.ui.styles.table_rows import normalize_table_item_option
from app.ui.viewmodels.snapshot_table_model import SnapshotTableModel


class SnapshotTableModelTests(unittest.TestCase):
    def test_decoration_role_caches_loaded_icons(self):
        model = SnapshotTableModel(
            headers=["Platform"],
            columns=["platform"],
            icon_columns={"platform"},
        )
        model.set_rows([{"id": "v1", "platform": "Douyin", "platform_id": "douyin"}])
        icon = QIcon()

        with patch("app.ui.viewmodels.snapshot_table_model.load_qt_icon", Mock(return_value=icon)) as loader:
            index = model.index(0, 0)
            self.assertIs(model.data(index, Qt.ItemDataRole.DecorationRole), icon)
            self.assertIs(model.data(index, Qt.ItemDataRole.DecorationRole), icon)

        loader.assert_called_once()

    def test_decoration_role_remembers_missing_icons(self):
        model = SnapshotTableModel(
            headers=["Status"],
            columns=["status"],
            icon_columns={"status"},
        )
        model.set_rows([{"id": "v1", "status": "missing"}])

        with patch("app.ui.viewmodels.snapshot_table_model.load_qt_icon", Mock(return_value=None)) as loader:
            index = model.index(0, 0)
            self.assertIsNone(model.data(index, Qt.ItemDataRole.DecorationRole))
            self.assertIsNone(model.data(index, Qt.ItemDataRole.DecorationRole))

        loader.assert_called_once()

    def test_action_delegate_caches_action_icons(self):
        delegate = SnapshotActionDelegate(
            progress_columns=set(),
            icon_columns=set(),
            title_columns=set(),
            action_column=0,
            action_ids=("delete",),
        )
        icon = QIcon()

        with patch("app.ui.pages.common.load_qt_icon", Mock(return_value=icon)) as loader:
            self.assertIs(delegate._action_icon("delete"), icon)
            self.assertIs(delegate._action_icon("delete"), icon)

        loader.assert_called_once()

    def test_action_delegate_remembers_missing_action_icons(self):
        delegate = SnapshotActionDelegate(
            progress_columns=set(),
            icon_columns=set(),
            title_columns=set(),
            action_column=0,
            action_ids=("delete",),
        )

        with patch("app.ui.pages.common.load_qt_icon", Mock(return_value=None)) as loader:
            self.assertIsNone(delegate._action_icon("delete"))
            self.assertIsNone(delegate._action_icon("delete"))

        loader.assert_called_once()

    def test_table_item_option_removes_focus_rect_even_when_selected(self):
        option = QStyleOptionViewItem()
        option.state |= QStyle.StateFlag.State_Selected
        option.state |= QStyle.StateFlag.State_HasFocus

        normalize_table_item_option(option)

        self.assertTrue(option.state & QStyle.StateFlag.State_Selected)
        self.assertFalse(option.state & QStyle.StateFlag.State_HasFocus)


if __name__ == "__main__":
    unittest.main()
