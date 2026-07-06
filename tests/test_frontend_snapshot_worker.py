from __future__ import annotations

import unittest

from app.ui.viewmodels.frontend_snapshot_worker import FrontendSnapshotRequest, build_frontend_snapshot


class FrontendSnapshotWorkerTests(unittest.TestCase):
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
