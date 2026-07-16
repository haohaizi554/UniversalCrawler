import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

from app.ui.pages.common import SnapshotActionDelegate
from app.ui.pages.active_downloads_page import ActiveDownloadsModel
from app.ui.styles.table_rows import normalize_table_item_option, row_interaction_fill_color, selection_fill_color
from app.ui.styles.themes import build_palette
from app.ui.viewmodels.snapshot_table_model import SnapshotTableModel


class SnapshotTableModelTests(unittest.TestCase):
    def test_set_rows_appends_tail_without_model_reset(self):
        model = SnapshotTableModel(headers=["Title"], columns=["title"])
        model.set_rows([{"id": "v1", "title": "one"}])
        resets: list[bool] = []
        inserted: list[tuple[int, int]] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.rowsInserted.connect(lambda _parent, first, last: inserted.append((first, last)))

        changed = model.set_rows(
            [
                {"id": "v1", "title": "one"},
                {"id": "v2", "title": "two"},
                {"id": "v3", "title": "three"},
            ]
        )

        self.assertTrue(changed)
        self.assertEqual(resets, [])
        self.assertEqual(inserted, [(1, 2)])
        self.assertEqual(model.id_order(), ["v1", "v2", "v3"])

    def test_set_rows_removes_tail_without_model_reset(self):
        model = SnapshotTableModel(headers=["Title"], columns=["title"])
        model.set_rows(
            [
                {"id": "v1", "title": "one"},
                {"id": "v2", "title": "two"},
                {"id": "v3", "title": "three"},
            ]
        )
        resets: list[bool] = []
        removed: list[tuple[int, int]] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.rowsRemoved.connect(lambda _parent, first, last: removed.append((first, last)))

        changed = model.set_rows([{"id": "v1", "title": "one"}])

        self.assertTrue(changed)
        self.assertEqual(resets, [])
        self.assertEqual(removed, [(1, 2)])
        self.assertEqual(model.id_order(), ["v1"])

    def test_set_rows_removes_middle_and_pulls_next_row_without_model_reset(self):
        model = SnapshotTableModel(headers=["Title"], columns=["title"])
        model.set_rows(
            [
                {"id": "v1", "title": "one"},
                {"id": "v2", "title": "two"},
                {"id": "v3", "title": "three"},
            ]
        )
        resets: list[bool] = []
        removed: list[tuple[int, int]] = []
        inserted: list[tuple[int, int]] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.rowsRemoved.connect(lambda _parent, first, last: removed.append((first, last)))
        model.rowsInserted.connect(lambda _parent, first, last: inserted.append((first, last)))

        changed = model.set_rows(
            [
                {"id": "v1", "title": "one"},
                {"id": "v3", "title": "three"},
                {"id": "v4", "title": "four"},
            ]
        )

        self.assertTrue(changed)
        self.assertEqual(resets, [])
        self.assertEqual(removed, [(1, 1)])
        self.assertEqual(inserted, [(2, 2)])
        self.assertEqual(model.id_order(), ["v1", "v3", "v4"])

    def test_set_rows_patches_existing_rows_without_model_reset(self):
        model = SnapshotTableModel(headers=["Title"], columns=["title"])
        model.set_rows([{"id": "v1", "title": "old"}])
        resets: list[bool] = []
        changed_rows: list[tuple[int, int]] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.dataChanged.connect(lambda first, last, _roles: changed_rows.append((first.row(), last.row())))

        changed = model.set_rows([{"id": "v1", "title": "new"}])

        self.assertTrue(changed)
        self.assertEqual(resets, [])
        self.assertEqual(changed_rows, [(0, 0)])
        self.assertEqual(model.row_at(0), {"id": "v1", "title": "new"})

    def test_set_rows_reorders_same_ids_without_model_reset(self):
        model = SnapshotTableModel(headers=["Title"], columns=["title"])
        model.set_rows(
            [
                {"id": "v1", "title": "one"},
                {"id": "v2", "title": "two"},
                {"id": "v3", "title": "three"},
            ]
        )
        resets: list[bool] = []
        layouts: list[bool] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.layoutChanged.connect(lambda: layouts.append(True))

        changed = model.set_rows(
            [
                {"id": "v3", "title": "three"},
                {"id": "v1", "title": "one"},
                {"id": "v2", "title": "two"},
            ]
        )

        self.assertTrue(changed)
        self.assertEqual(resets, [])
        self.assertEqual(layouts, [True])
        self.assertEqual(model.id_order(), ["v3", "v1", "v2"])

    def test_active_downloads_model_reorders_same_ids_without_model_reset(self):
        model = ActiveDownloadsModel()
        model.set_rows(
            [
                {"id": "v1", "title": "one", "platform": "Bilibili", "progress": 10},
                {"id": "v2", "title": "two", "platform": "Bilibili", "progress": 20},
            ]
        )
        resets: list[bool] = []
        layouts: list[bool] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.layoutChanged.connect(lambda: layouts.append(True))

        changed = model.set_rows(
            [
                {"id": "v2", "title": "two", "platform": "Bilibili", "progress": 20},
                {"id": "v1", "title": "one", "platform": "Bilibili", "progress": 10},
            ]
        )

        self.assertTrue(changed)
        self.assertEqual(resets, [])
        self.assertEqual(layouts, [True])
        self.assertEqual(model.item_id_at(0), "v2")
        self.assertEqual(model.item_id_at(1), "v1")

    def test_force_reset_prevents_duplicate_append_after_signature_clear(self):
        model = SnapshotTableModel(headers=["Title"], columns=["title"])
        rows = [{"id": "v1", "title": "one"}]
        model.set_rows(rows)
        model.force_reset()
        resets: list[bool] = []
        inserted: list[tuple[int, int]] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.rowsInserted.connect(lambda _parent, first, last: inserted.append((first, last)))

        changed = model.set_rows(rows)

        self.assertTrue(changed)
        self.assertEqual(resets, [True])
        self.assertEqual(inserted, [])
        self.assertEqual(model.id_order(), ["v1"])

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

    def test_table_item_option_removes_native_hover_overlay(self):
        option = QStyleOptionViewItem()
        option.state |= QStyle.StateFlag.State_Selected
        option.state |= QStyle.StateFlag.State_MouseOver

        normalize_table_item_option(option)

        self.assertTrue(option.state & QStyle.StateFlag.State_Selected)
        self.assertFalse(option.state & QStyle.StateFlag.State_MouseOver)

    def test_table_row_interaction_selection_wins_over_hover(self):
        option = QStyleOptionViewItem()
        option.palette = build_palette(False)
        option.state |= QStyle.StateFlag.State_Selected
        option.state |= QStyle.StateFlag.State_MouseOver

        self.assertEqual(row_interaction_fill_color(option), selection_fill_color(option))


if __name__ == "__main__":
    unittest.main()
