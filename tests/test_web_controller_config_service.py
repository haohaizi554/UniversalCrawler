from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.web.controller_config_service import WebControllerConfigService


class WebControllerConfigServiceTests(unittest.TestCase):
    def test_update_config_rejects_save_directory_outside_approved_roots(self) -> None:
        service = WebControllerConfigService()
        with tempfile.TemporaryDirectory() as approved_dir, tempfile.TemporaryDirectory() as outside_dir:
            with patch("app.web.controller_config_service.cfg.set") as mocked_set:
                errors = service.update_config(
                    {"common": {"save_directory": str(Path(outside_dir, "downloads"))}},
                    approved_roots=(approved_dir,),
                )

        self.assertEqual(len(errors), 1)
        self.assertIn("授权", errors[0].error)
        mocked_set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
