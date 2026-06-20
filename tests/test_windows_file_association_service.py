import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.windows_file_association_service import USER_CHOICE_EXPERIENCE, WindowsFileAssociationService

class _FakeKey:
    def __init__(self, subkey):
        self.subkey = subkey

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

class WindowsFileAssociationServiceTests(unittest.TestCase):
    def test_default_apps_uri_targets_registered_user_app(self):
        service = WindowsFileAssociationService(app_name="Universal CrawlerPro")

        self.assertEqual(
            service.default_apps_settings_uri(),
            "ms-settings:defaultapps?registeredAppUser=Universal%20CrawlerPro",
        )

    def test_register_current_user_writes_supported_media_capabilities(self):
        writes = {}

        def create_key(_root, subkey, _reserved, _access):
            return _FakeKey(subkey)

        def set_value(key, value_name, _reserved, _value_type, value):
            writes[(key.subkey, value_name)] = value

        fake_winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            KEY_WRITE=1,
            REG_SZ=1,
            REG_DWORD=4,
            CreateKeyEx=create_key,
            SetValueEx=set_value,
        )

        with TemporaryDirectory() as tmp:
            executable = Path(tmp) / "UniversalCrawlerPro.exe"
            executable.write_bytes(b"exe")
            service = WindowsFileAssociationService(app_name="Universal CrawlerPro")
            with patch("app.services.windows_file_association_service.os.name", "nt"), \
                 patch.dict("sys.modules", {"winreg": fake_winreg}):
                result = service.register_current_user(
                    executable,
                    include_video=True,
                    include_image=True,
                )

        self.assertTrue(result.registered)
        self.assertEqual(
            writes[(r"Software\RegisteredApplications", "Universal CrawlerPro")],
            r"Software\UniversalCrawlerPro\Capabilities",
        )
        self.assertEqual(
            writes[(r"Software\UniversalCrawlerPro\Capabilities\FileAssociations", ".mp4")],
            "UniversalCrawlerPro.Video",
        )
        self.assertEqual(
            writes[(r"Software\UniversalCrawlerPro\Capabilities\FileAssociations", ".png")],
            "UniversalCrawlerPro.Image",
        )
        self.assertIn(
            (r"Software\Classes\Applications\UniversalCrawlerPro.exe\shell\open\command", ""),
            writes,
        )

    def test_build_userchoice_hash_matches_known_vector(self):
        user_hash = WindowsFileAssociationService._build_userchoice_hash(
            ".3g2",
            "S-1-5-21-819709642-920330688-1657285119-500",
            "WMP11.AssocFile.3G2",
            "01d4d98267246000",
            USER_CHOICE_EXPERIENCE,
        )

        self.assertEqual(user_hash, "PCCqEmkvW2Y=")

    def test_set_current_user_defaults_writes_userchoice_values(self):
        writes = {}
        deleted = []

        def create_key(_root, subkey, _reserved, _access):
            return _FakeKey(subkey)

        def set_value(key, value_name, _reserved, _value_type, value):
            writes[(key.subkey, value_name)] = value

        def query_info_key(_key):
            return 0, 0, int("01d4d98267246000", 16)

        def delete_key(_root, subkey):
            deleted.append(subkey)

        fake_winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            KEY_WRITE=2,
            KEY_QUERY_VALUE=1,
            REG_SZ=1,
            REG_DWORD=4,
            CreateKeyEx=create_key,
            SetValueEx=set_value,
            QueryInfoKey=query_info_key,
            DeleteKey=delete_key,
        )

        service = WindowsFileAssociationService(app_name="Universal CrawlerPro")
        with patch("app.services.windows_file_association_service.os.name", "nt"), \
             patch.dict("sys.modules", {"winreg": fake_winreg}), \
             patch.object(service, "_current_user_sid", return_value="S-1-5-21-819709642-920330688-1657285119-500"), \
             patch.object(service, "_user_experience_string", return_value=USER_CHOICE_EXPERIENCE), \
             patch.object(service, "_delete_current_user_tree", side_effect=lambda _winreg, subkey: deleted.append(subkey)), \
             patch.object(service, "_notify_associations_changed"):
            result = service.set_current_user_defaults(include_video=True, include_image=False)

        self.assertTrue(result.applied)
        self.assertIn(".mp4", result.defaulted_extensions)
        self.assertIn(
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mp4\UserChoice",
            deleted,
        )
        self.assertEqual(
            writes[
                (
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mp4\UserChoice",
                    "ProgId",
                )
            ],
            "UniversalCrawlerPro.Video",
        )
        self.assertIn(
            (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mp4\UserChoice",
                "Hash",
            ),
            writes,
        )
        self.assertNotIn(
            (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.jpg\UserChoice",
                "ProgId",
            ),
            writes,
        )

    def test_diagnose_current_user_reports_pending_user_choices(self):
        registry = {
            (r"Software\RegisteredApplications", "Universal CrawlerPro"): (
                r"Software\UniversalCrawlerPro\Capabilities"
            ),
            (r"Software\UniversalCrawlerPro\Capabilities\FileAssociations", ".mp4"): (
                "UniversalCrawlerPro.Video"
            ),
            (r"Software\UniversalCrawlerPro\Capabilities\FileAssociations", ".mkv"): (
                "UniversalCrawlerPro.Video"
            ),
            (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mp4\UserChoice",
                "ProgId",
            ): "UniversalCrawlerPro.Video",
            (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mkv\UserChoice",
                "ProgId",
            ): "AppXWindowsVideo",
        }

        def open_key(_root, subkey):
            return _FakeKey(subkey)

        def query_value(key, value_name):
            try:
                value = registry[(key.subkey, value_name)]
            except KeyError as exc:
                raise OSError("missing") from exc
            return value, 1

        fake_winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            OpenKey=open_key,
            QueryValueEx=query_value,
        )

        service = WindowsFileAssociationService(app_name="Universal CrawlerPro")
        with patch("app.services.windows_file_association_service.os.name", "nt"), \
             patch.dict("sys.modules", {"winreg": fake_winreg}):
            diagnostics = service.diagnose_current_user(include_video=True, include_image=False)

        self.assertTrue(diagnostics.available)
        self.assertTrue(diagnostics.registered_app)
        self.assertIn(".mp4", diagnostics.defaulted_extensions)
        self.assertIn(".mkv", diagnostics.pending_extensions)
        self.assertEqual(diagnostics.user_choices[".mkv"], "AppXWindowsVideo")

if __name__ == "__main__":
    unittest.main()
