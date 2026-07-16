import unittest

from app.services.media_directory_monitor import MediaDirectoryMonitor


class MediaDirectoryMonitorTests(unittest.TestCase):
    def test_poll_reports_only_changes_after_baseline(self):
        signatures = {"media": (1, 1, 0, 1)}
        changed: list[str] = []

        def signature(path: str):
            return signatures["media"] if path.lower().endswith("media") else None

        monitor = MediaDirectoryMonitor(
            signature_provider=signature,
            auto_start=False,
        )
        handle = monitor.watch(["D:/media"], changed.append)

        monitor.poll_once()
        self.assertEqual(changed, [])

        signatures["media"] = (2, 1, 0, 1)
        monitor.poll_once()
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0].lower().endswith("media"))

        monitor.poll_once()
        self.assertEqual(len(changed), 1)
        handle.close()

    def test_replacing_paths_preserves_existing_baseline(self):
        signatures = {"media": (1, 1, 0, 1), "album": (5, 1, 0, 2)}
        changed: list[str] = []

        def signature(path: str):
            key = "album" if path.lower().endswith("album") else "media"
            return signatures[key]

        monitor = MediaDirectoryMonitor(
            signature_provider=signature,
            auto_start=False,
        )
        handle = monitor.watch(["D:/media"], changed.append)
        monitor.poll_once()

        handle.replace_paths(["D:/media", "D:/media/album"])
        monitor.poll_once()
        self.assertEqual(changed, [])

        signatures["album"] = (6, 1, 0, 2)
        monitor.poll_once()
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0].lower().endswith("album"))
        handle.close()

    def test_shared_monitor_stats_duplicate_session_paths_once_per_poll(self):
        calls: list[str] = []

        def signature(path: str):
            calls.append(path)
            return (1, 1, 0, 1)

        monitor = MediaDirectoryMonitor(
            signature_provider=signature,
            auto_start=False,
        )
        first = monitor.watch(["D:/media"], lambda _path: None)
        second = monitor.watch(["D:/media"], lambda _path: None)

        monitor.poll_once()

        self.assertEqual(len(calls), 1)
        first.close()
        second.close()


if __name__ == "__main__":
    unittest.main()
