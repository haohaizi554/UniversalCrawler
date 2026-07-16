import unittest

from PyQt6.QtWidgets import QApplication

from app.ui.ui_update_scheduler import UiUpdateScheduler


class FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.started = 0
        self.stopped = 0
        self.raise_on_is_active = False

    def isActive(self) -> bool:
        if self.raise_on_is_active:
            raise AssertionError("QTimer was touched from schedule()")
        return self.active

    def start(self) -> None:
        self.started += 1
        self.active = True

    def stop(self) -> None:
        self.stopped += 1
        self.active = False

    def setInterval(self, _interval_ms: int) -> None:
        return None


class UiUpdateSchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_schedule_only_records_dirty_topic(self):
        scheduler = UiUpdateScheduler(interval_ms=25, on_flush=lambda topics: None)
        fake_timer = FakeTimer()
        fake_timer.raise_on_is_active = True
        scheduler._timer = fake_timer

        scheduler.schedule("videos.update")

        self.assertEqual(fake_timer.started, 0)
        self.assertEqual(fake_timer.stopped, 0)
        self.assertEqual(scheduler.metrics()["pending_topics"], ["videos.update"])

    def test_drain_schedule_starts_timer_once(self):
        scheduler = UiUpdateScheduler(interval_ms=25, on_flush=lambda topics: None)
        fake_timer = FakeTimer()
        scheduler._timer = fake_timer

        scheduler.schedule("videos.update")
        scheduler._drain_schedule(False)
        scheduler._drain_schedule(False)

        self.assertEqual(fake_timer.started, 1)
        self.assertTrue(fake_timer.active)

    def test_force_drain_flushes_and_resets_flags(self):
        flushed: list[set[str]] = []
        scheduler = UiUpdateScheduler(interval_ms=25, on_flush=lambda topics: flushed.append(topics))
        fake_timer = FakeTimer()
        scheduler._timer = fake_timer

        scheduler.schedule("videos.update")
        scheduler.schedule("task_error")
        scheduler._drain_schedule(True)

        self.assertEqual(fake_timer.stopped, 1)
        self.assertEqual(flushed, [{"videos.update", "task_error"}])
        self.assertEqual(scheduler.metrics()["pending_topics"], [])
        self.assertEqual(scheduler.metrics()["flush_count"], 1)

    def test_stale_queued_drain_does_not_start_empty_timer(self):
        scheduler = UiUpdateScheduler(interval_ms=25, on_flush=lambda topics: None)
        fake_timer = FakeTimer()
        scheduler._timer = fake_timer

        scheduler.schedule("videos.update")
        scheduler._flush()
        scheduler._drain_schedule(False)

        self.assertEqual(fake_timer.started, 0)
        self.assertEqual(scheduler.metrics()["pending_topics"], [])

    def test_repeated_progress_topics_are_coalesced_before_timer_drain(self):
        scheduler = UiUpdateScheduler(interval_ms=25, on_flush=lambda topics: None)
        fake_timer = FakeTimer()
        fake_timer.raise_on_is_active = True
        scheduler._timer = fake_timer

        for _ in range(1000):
            scheduler.schedule("videos.update")

        metrics = scheduler.metrics()
        self.assertEqual(fake_timer.started, 0)
        self.assertEqual(metrics["scheduled_count"], 1000)
        self.assertEqual(metrics["coalesced_count"], 999)
        self.assertEqual(metrics["pending_topics"], ["videos.update"])


if __name__ == "__main__":
    unittest.main()
