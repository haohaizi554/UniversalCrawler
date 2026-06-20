import unittest

from app.models import VideoItem
from app.services.download_telemetry import DownloadProgressSnapshot, DownloadTelemetryService

class DownloadTelemetryServiceTests(unittest.TestCase):
    def test_record_computes_speed_and_eta(self):
        service = DownloadTelemetryService()
        item = VideoItem(url="https://example.com/a.mp4", title="demo", source="douyin")
        item.meta["size_bytes"] = 10_000_000

        first = service.record(item, progress=10, bytes_downloaded=1_000_000, now=0.0)
        second = service.record(item, progress=20, bytes_downloaded=2_000_000, now=1.0)

        self.assertGreater(second.speed_bps, 0)
        self.assertEqual(item.meta["speed"], second.speed)
        self.assertNotEqual(second.remaining_time, "--")
        self.assertEqual(first.video_id, item.id)

    def test_status_indicator_idle_running_error(self):
        from app.services.frontend_state_service import FrontendStateService

        service = FrontendStateService()
        idle = service.app_status(completed_count=0, failed_count=0, active_downloads=[])
        self.assertEqual(idle["status_indicator"], "idle")

        failed = service.app_status(completed_count=0, failed_count=2, active_downloads=[])
        self.assertEqual(failed["status_indicator"], "error")

    def test_snapshot_serializes_for_api(self):
        service = DownloadTelemetryService()
        item = VideoItem(url="https://example.com/a.mp4", title="demo", source="douyin")
        snapshot = service.record(item, progress=50, bytes_downloaded=500, bytes_total=1000, now=1.0)
        payload = snapshot.to_dict()
        self.assertIn("eta_seconds", payload)
        self.assertIn("speed_bps", payload)

    def test_speed_trend_keeps_repeated_samples_as_rolling_window(self):
        service = DownloadTelemetryService()
        item = VideoItem(url="https://example.com/a.mp4", title="demo", source="douyin")

        for index in range(65):
            snapshot = DownloadProgressSnapshot(
                video_id=item.id,
                progress=min(index, 100),
                speed_bps=1024,
                speed="1.0 KB/s",
                bytes_downloaded=index * 1024,
                bytes_total=100 * 1024,
                eta_seconds=None,
                eta="--",
                remaining_time="--",
                updated_at=float(index),
            )
            service.apply_to_meta(item, snapshot)

        self.assertEqual(len(item.meta["speed_trend"]), 60)
        self.assertEqual(item.meta["speed_trend"], [1024] * 60)

if __name__ == "__main__":
    unittest.main()
