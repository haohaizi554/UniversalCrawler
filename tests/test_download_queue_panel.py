import unittest

from PyQt6.QtWidgets import QApplication, QWidget

from app.models import VideoItem
from app.ui.components.download_queue_panel import DownloadQueuePanel


class DownloadQueuePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.panel = DownloadQueuePanel("downloads", self.host)

    def test_add_find_and_remove_video_row(self):
        item = VideoItem(url="https://example.com/demo.mp4", title="demo", source="douyin")

        self.panel.add_video_row(item, on_play=lambda _video_id: None, on_delete=lambda _video_id: None)

        row = self.panel.find_row_by_video_id(item.id)
        self.assertEqual(row, 0)

        self.panel.remove_row(row)

        self.assertEqual(self.panel.find_row_by_video_id(item.id), -1)

    def test_clear_rows_removes_all_items(self):
        for index in range(2):
            item = VideoItem(url=f"https://example.com/{index}.mp4", title=f"demo-{index}", source="douyin")
            self.panel.add_video_row(item, on_play=lambda _video_id: None, on_delete=lambda _video_id: None)

        self.panel.clear_rows()

        self.assertEqual(self.panel.table.rowCount(), 0)

    def test_set_current_save_dir_updates_label_and_tooltip(self):
        self.panel.set_current_save_dir("new-downloads")

        self.assertEqual(self.panel.lbl_full_path.text(), "new-downloads")
        self.assertEqual(self.panel.lbl_full_path.toolTip(), "new-downloads")

    def test_update_video_status_updates_status_and_progress(self):
        item = VideoItem(url="https://example.com/demo.mp4", title="demo", source="douyin")
        self.panel.add_video_row(item, on_play=lambda _video_id: None, on_delete=lambda _video_id: None)

        self.panel.update_video_status(item.id, "✅ 完成", 100)

        self.assertEqual(self.panel.table.item(0, 1).text(), "✅ 完成")
        self.assertEqual(self.panel.table.cellWidget(0, 2).value(), 100)

    def test_get_selected_video_id_returns_current_row_video(self):
        item = VideoItem(url="https://example.com/demo.mp4", title="demo", source="douyin")
        self.panel.add_video_row(item, on_play=lambda _video_id: None, on_delete=lambda _video_id: None)
        self.panel.table.selectRow(0)

        self.assertEqual(self.panel.get_selected_video_id(), item.id)


if __name__ == "__main__":
    unittest.main()
