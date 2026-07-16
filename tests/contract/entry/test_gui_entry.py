import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from entry import gui_entry

class GuiEntryAssociationHelperTests(unittest.TestCase):
    def test_association_kinds_accepts_space_and_comma_tokens(self):
        kinds = gui_entry._association_kinds(
            ["--register-file-associations", "video,image", "--open-default-apps-settings"]
        )

        self.assertEqual(kinds, {"video", "image"})

    def test_association_kinds_accepts_check_only_tokens(self):
        kinds = gui_entry._association_kinds(["--check-file-associations", "video"])

        self.assertEqual(kinds, {"video"})

    def test_association_kinds_accepts_set_default_tokens(self):
        kinds = gui_entry._association_kinds(["--set-default-file-associations", "image"])

        self.assertEqual(kinds, {"image"})

    def test_association_helper_registers_and_opens_settings_without_main_window(self):
        with patch("app.services.windows_file_association_service.WindowsFileAssociationService") as service_cls, \
             patch.object(gui_entry.sys, "frozen", True, create=True), \
             patch.object(gui_entry.sys, "executable", r"C:\App\UniversalCrawlerPro.exe"):
            service = service_cls.return_value
            service.set_current_user_defaults.return_value = SimpleNamespace(
                applied=True,
                defaulted_extensions=(".mp4",),
                failed_extensions=(),
                message="Set current-user default apps",
            )

            output = StringIO()
            with redirect_stdout(output):
                handled = gui_entry._handle_association_helper(
                    [
                        "--app-name",
                        "Custom App",
                        "--register-file-associations",
                        "video",
                        "--set-default-file-associations",
                        "--open-default-apps-settings",
                    ]
                )

        self.assertTrue(handled)
        service_cls.assert_called_once_with(app_name="Custom App")
        service.register_current_user.assert_called_once_with(
            gui_entry.Path(r"C:\App\UniversalCrawlerPro.exe"),
            include_video=True,
            include_image=False,
        )
        service.set_current_user_defaults.assert_called_once_with(include_video=True, include_image=False)
        service.open_default_apps_settings.assert_called_once_with()
        self.assertIn("set_default=True", output.getvalue())
        self.assertIn("defaulted=.mp4", output.getvalue())

    def test_association_helper_can_print_diagnostics(self):
        with patch("app.services.windows_file_association_service.WindowsFileAssociationService") as service_cls:
            service = service_cls.return_value
            service.diagnose_current_user.return_value = SimpleNamespace(
                available=True,
                registered_app=True,
                defaulted_extensions=(".mp4",),
                pending_extensions=(".mkv",),
                settings_uri="ms-settings:defaultapps?registeredAppUser=App",
            )
            output = StringIO()
            with redirect_stdout(output):
                handled = gui_entry._handle_association_helper(["--check-file-associations", "video"])

        self.assertTrue(handled)
        service.diagnose_current_user.assert_called_once_with(include_video=True, include_image=False)
        self.assertIn("registered_app=True", output.getvalue())
        self.assertIn("pending=.mkv", output.getvalue())

    def test_non_helper_arguments_are_not_handled(self):
        self.assertFalse(gui_entry._handle_association_helper([r"D:\media\demo.mp4"]))

if __name__ == "__main__":
    unittest.main()
