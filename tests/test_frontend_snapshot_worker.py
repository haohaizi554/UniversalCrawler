from __future__ import annotations

import unittest

from app.ui.viewmodels.frontend_snapshot_worker import FrontendSnapshotRequest, build_frontend_snapshot


class FrontendSnapshotWorkerTests(unittest.TestCase):
    def test_build_frontend_snapshot_uses_delta_when_cached_snapshot_exists(self):
        class FakeService:
            def __init__(self):
                self.delta_calls = []
                self.snapshot_calls = []

            def get_delta(self, since_version=0, sections=None):
                self.delta_calls.append({"since_version": since_version, "sections": sections})
                return {
                    "version": 4,
                    "base_version": since_version,
                    "full": False,
                    "changed_sections": ["active_downloads", "app_status"],
                    "sections": {
                        "active_downloads": [{"id": "v1", "progress": 40}],
                        "app_status": {"active_count": 1},
                    },
                }

            def get_snapshot(self, *, mock=False, sections=None):
                self.snapshot_calls.append({"mock": mock, "sections": sections})
                return {}

        service = FakeService()
        cached = {
            "version": 3,
            "queue_items": [{"id": "q1"}],
            "active_downloads": [{"id": "v1", "progress": 10}],
            "app_status": {"active_count": 1},
        }
        request = FrontendSnapshotRequest(
            sequence=1,
            service=service,
            service_token=id(service),
            mock=False,
            sections=None,
            cached_snapshot=cached,
            section_signatures={},
            use_delta=True,
            base_version=3,
        )

        result = build_frontend_snapshot(request)

        self.assertEqual(service.delta_calls, [{"since_version": 3, "sections": None}])
        self.assertEqual(service.snapshot_calls, [])
        self.assertEqual(result.snapshot["queue_items"], [{"id": "q1"}])
        self.assertEqual(result.snapshot["active_downloads"], [{"id": "v1", "progress": 40}])
        self.assertEqual(result.snapshot["version"], 4)
        self.assertEqual(result.changed_sections, {"active_downloads", "app_status"})
        self.assertFalse(result.skip_render)

    def test_build_frontend_snapshot_fetches_explicit_section_when_delta_is_current(self):
        class FakeService:
            def __init__(self):
                self.delta_calls = []
                self.snapshot_calls = []

            def get_delta(self, since_version=0, sections=None):
                self.delta_calls.append({"since_version": since_version, "sections": sections})
                return {
                    "version": 3,
                    "base_version": since_version,
                    "full": False,
                    "changed_sections": [],
                    "sections": {},
                }

            def get_snapshot(self, *, mock=False, sections=None):
                self.snapshot_calls.append({"mock": mock, "sections": sections})
                return {"failed_items": [{"id": "f1"}], "version": 3}

        service = FakeService()
        request = FrontendSnapshotRequest(
            sequence=1,
            service=service,
            service_token=id(service),
            mock=False,
            sections=frozenset({"failed_items"}),
            cached_snapshot={"version": 3, "queue_items": []},
            section_signatures={},
            use_delta=True,
            base_version=3,
        )

        result = build_frontend_snapshot(request)

        self.assertEqual(service.delta_calls, [{"since_version": 3, "sections": frozenset({"failed_items"})}])
        self.assertEqual(service.snapshot_calls, [{"mock": False, "sections": frozenset({"failed_items"})}])
        self.assertEqual(result.snapshot["failed_items"], [{"id": "f1"}])
        self.assertEqual(result.changed_sections, {"failed_items"})

    def test_build_frontend_snapshot_merges_cached_sections_and_detects_changes(self):
        class FakeService:
            def __init__(self):
                self.calls = []

            def get_snapshot(self, *, mock=False, sections=None):
                self.calls.append({"mock": mock, "sections": sections})
                return {"failed_items": [{"id": "f2"}], "version": 2}

        service = FakeService()
        cached = {"version": 1, "queue_items": [{"id": "q1"}], "failed_items": [{"id": "f1"}]}
        request = FrontendSnapshotRequest(
            sequence=1,
            service=service,
            service_token=id(service),
            mock=False,
            sections=frozenset({"failed_items"}),
            cached_snapshot=cached,
            section_signatures={},
        )

        result = build_frontend_snapshot(request)

        self.assertEqual(service.calls, [{"mock": False, "sections": frozenset({"failed_items"})}])
        self.assertEqual(result.snapshot["queue_items"], [{"id": "q1"}])
        self.assertEqual(result.snapshot["failed_items"], [{"id": "f2"}])
        self.assertEqual(result.changed_sections, {"failed_items"})
        self.assertFalse(result.skip_render)
        self.assertIn("failed_items", result.section_signatures)

    def test_build_frontend_snapshot_can_skip_unchanged_section_render(self):
        class FakeService:
            def get_snapshot(self, *, mock=False, sections=None):
                return {"failed_items": [{"id": "f1"}], "version": 2}

        service = FakeService()
        first = build_frontend_snapshot(
            FrontendSnapshotRequest(
                sequence=1,
                service=service,
                service_token=id(service),
                mock=False,
                sections=frozenset({"failed_items"}),
                cached_snapshot={"version": 1, "failed_items": [{"id": "f1"}]},
                section_signatures={},
            )
        )
        second = build_frontend_snapshot(
            FrontendSnapshotRequest(
                sequence=2,
                service=service,
                service_token=id(service),
                mock=False,
                sections=frozenset({"failed_items"}),
                cached_snapshot=first.snapshot,
                section_signatures=first.section_signatures,
            )
        )

        self.assertEqual(second.changed_sections, set())
        self.assertTrue(second.skip_render)


if __name__ == "__main__":
    unittest.main()
