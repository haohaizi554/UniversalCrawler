"""Windows default-app registration helpers."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

APP_NAME = "Universal Crawler Pro"
APP_REGISTRATION_PATH = r"Software\UniversalCrawlerPro\Capabilities"
VIDEO_PROG_ID = "UniversalCrawlerPro.Video"
IMAGE_PROG_ID = "UniversalCrawlerPro.Image"
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
USER_CHOICE_EXPERIENCE = "User Choice set via Windows User Experience {D18B6DD5-6124-4341-9318-804003BAFA0B}"
FILETIME_TICKS_PER_MINUTE = 600_000_000
FILETIME_EPOCH_OFFSET_SECONDS = 11_644_473_600
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

@dataclass(frozen=True, slots=True)
class AssociationRegistrationResult:
    registered: bool
    opened_settings: bool = False
    message: str = ""

@dataclass(frozen=True, slots=True)
class AssociationDefaultResult:
    applied: bool
    defaulted_extensions: tuple[str, ...] = ()
    failed_extensions: tuple[str, ...] = ()
    message: str = ""

@dataclass(frozen=True, slots=True)
class AssociationDiagnostics:
    available: bool
    registered_app: bool = False
    user_choices: dict[str, str] | None = None
    defaulted_extensions: tuple[str, ...] = ()
    pending_extensions: tuple[str, ...] = ()
    missing_capability_extensions: tuple[str, ...] = ()
    settings_uri: str = ""
    message: str = ""

class WindowsFileAssociationService:
    """Register supported media types and set explicit current-user defaults."""

    def __init__(self, *, app_name: str = APP_NAME) -> None:
        self.app_name = app_name

    def register_current_user(
        self,
        executable_path: str | os.PathLike[str],
        *,
        include_video: bool = True,
        include_image: bool = True,
    ) -> AssociationRegistrationResult:
        if os.name != "nt":
            return AssociationRegistrationResult(False, message="File association registration is Windows-only")

        import winreg

        executable = str(Path(executable_path).resolve())
        executable_name = Path(executable).name
        app_prog_id = fr"Applications\{executable_name}"
        command = f'"{executable}" "%1"'
        icon = f"{executable},0"

        self._set_string(winreg, fr"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}", "", executable)
        self._set_string(winreg, fr"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}", "Path", str(Path(executable).parent))
        self._set_string(winreg, r"Software\RegisteredApplications", self.app_name, APP_REGISTRATION_PATH)
        self._set_string(winreg, APP_REGISTRATION_PATH, "ApplicationName", self.app_name)
        self._set_string(
            winreg,
            APP_REGISTRATION_PATH,
            "ApplicationDescription",
            f"Use {self.app_name} to preview supported local videos and images.",
        )
        self._set_string(winreg, fr"Software\Classes\{app_prog_id}", "FriendlyAppName", self.app_name)
        self._set_string(winreg, fr"Software\Classes\{app_prog_id}\shell\open\command", "", command)

        if include_video:
            self._register_kind(
                winreg,
                app_prog_id=app_prog_id,
                prog_id=VIDEO_PROG_ID,
                description=f"{self.app_name} Video",
                extensions=VIDEO_EXTENSIONS,
                command=command,
                icon=icon,
            )
        if include_image:
            self._register_kind(
                winreg,
                app_prog_id=app_prog_id,
                prog_id=IMAGE_PROG_ID,
                description=f"{self.app_name} Image",
                extensions=IMAGE_EXTENSIONS,
                command=command,
                icon=icon,
            )

        return AssociationRegistrationResult(True, message="Registered supported file types")

    def set_current_user_defaults(
        self,
        *,
        include_video: bool = True,
        include_image: bool = True,
    ) -> AssociationDefaultResult:
        if os.name != "nt":
            return AssociationDefaultResult(False, message="File association defaults are Windows-only")

        import winreg

        expected = self._expected_extensions(include_video=include_video, include_image=include_image)
        if not expected:
            return AssociationDefaultResult(False, message="No supported file types were selected")

        try:
            user_sid = self._current_user_sid()
        except OSError as exc:
            return AssociationDefaultResult(False, message=f"Cannot resolve current user SID: {exc}")

        user_experience = self._user_experience_string()
        defaulted: list[str] = []
        failed: list[str] = []
        for ext, prog_id in expected.items():
            try:
                self._write_user_choice(winreg, ext, prog_id, user_sid=user_sid, user_experience=user_experience)
                defaulted.append(ext)
            except OSError:
                failed.append(ext)

        if defaulted:
            self._notify_associations_changed()

        if failed:
            preview = ", ".join(failed[:4])
            suffix = "..." if len(failed) > 4 else ""
            return AssociationDefaultResult(
                applied=False,
                defaulted_extensions=tuple(defaulted),
                failed_extensions=tuple(failed),
                message=f"Failed to set defaults for {preview}{suffix}",
            )
        return AssociationDefaultResult(
            applied=bool(defaulted),
            defaulted_extensions=tuple(defaulted),
            message="Set current-user default apps",
        )

    def diagnose_current_user(
        self,
        *,
        include_video: bool = True,
        include_image: bool = True,
    ) -> AssociationDiagnostics:
        """Inspect current-user registration and default choices without changing them."""
        if os.name != "nt":
            return AssociationDiagnostics(
                available=False,
                settings_uri=self.default_apps_settings_uri(),
                message="File association diagnostics are Windows-only",
            )

        import winreg

        expected = self._expected_extensions(include_video=include_video, include_image=include_image)
        registered_app = (
            self._query_string(winreg, r"Software\RegisteredApplications", self.app_name) == APP_REGISTRATION_PATH
        )
        capability_extensions = {
            ext
            for ext, prog_id in expected.items()
            if self._query_string(winreg, fr"{APP_REGISTRATION_PATH}\FileAssociations", ext) == prog_id
        }
        missing_capability_extensions = tuple(ext for ext in expected if ext not in capability_extensions)

        user_choices = {
            ext: self._query_string(
                winreg,
                fr"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice",
                "ProgId",
            )
            or ""
            for ext in expected
        }
        defaulted_extensions = tuple(ext for ext, prog_id in expected.items() if user_choices.get(ext) == prog_id)
        pending_extensions = tuple(ext for ext in expected if ext not in defaulted_extensions)
        return AssociationDiagnostics(
            available=True,
            registered_app=registered_app,
            user_choices=user_choices,
            defaulted_extensions=defaulted_extensions,
            pending_extensions=pending_extensions,
            missing_capability_extensions=missing_capability_extensions,
            settings_uri=self.default_apps_settings_uri(),
            message="Diagnostics collected",
        )

    def open_default_apps_settings(self) -> bool:
        """Open Windows Settings on this app's Default Apps page when possible."""
        if os.name != "nt":
            return False
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            return False
        uri = self.default_apps_settings_uri()
        try:
            startfile(uri)
            return True
        except OSError:
            try:
                startfile("ms-settings:defaultapps")
                return True
            except OSError:
                return False

    def default_apps_settings_uri(self) -> str:
        return f"ms-settings:defaultapps?registeredAppUser={quote(self.app_name, safe='')}"

    def _register_kind(
        self,
        winreg,
        *,
        app_prog_id: str,
        prog_id: str,
        description: str,
        extensions: tuple[str, ...],
        command: str,
        icon: str,
    ) -> None:
        self._set_string(winreg, fr"Software\Classes\{prog_id}", "", description)
        self._set_string(winreg, fr"Software\Classes\{prog_id}\DefaultIcon", "", icon)
        self._set_string(winreg, fr"Software\Classes\{prog_id}\shell\open\command", "", command)

        for ext in extensions:
            self._set_string(winreg, fr"Software\Classes\{ext}", "", prog_id)
            self._set_string(winreg, fr"Software\Classes\{ext}\OpenWithProgids", prog_id, "")
            self._set_string(winreg, fr"Software\Classes\{app_prog_id}\SupportedTypes", ext, "")
            self._set_string(winreg, fr"{APP_REGISTRATION_PATH}\FileAssociations", ext, prog_id)
            self._set_dword(
                winreg,
                r"Software\Microsoft\Windows\CurrentVersion\ApplicationAssociationToasts",
                f"{prog_id}_{ext}",
                0,
            )

    def _write_user_choice(
        self,
        winreg,
        ext: str,
        prog_id: str,
        *,
        user_sid: str,
        user_experience: str,
    ) -> None:
        subkey = fr"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice"
        self._delete_current_user_tree(winreg, subkey)
        access = winreg.KEY_WRITE | getattr(winreg, "KEY_QUERY_VALUE", 0)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, access) as key:
            filetime_hex = self._query_key_filetime_hex(winreg, key)
            user_hash = self._build_userchoice_hash(ext, user_sid, prog_id, filetime_hex, user_experience)
            winreg.SetValueEx(key, "ProgId", 0, winreg.REG_SZ, prog_id)
            winreg.SetValueEx(key, "Hash", 0, winreg.REG_SZ, user_hash)
        self._set_dword(
            winreg,
            r"Software\Microsoft\Windows\CurrentVersion\ApplicationAssociationToasts",
            f"{prog_id}_{ext}",
            0,
        )

    @staticmethod
    def _expected_extensions(*, include_video: bool, include_image: bool) -> dict[str, str]:
        expected: dict[str, str] = {}
        if include_video:
            expected.update({ext: VIDEO_PROG_ID for ext in VIDEO_EXTENSIONS})
        if include_image:
            expected.update({ext: IMAGE_PROG_ID for ext in IMAGE_EXTENSIONS})
        return expected

    @staticmethod
    def _set_string(winreg, subkey: str, value_name: str, value: str) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)

    @staticmethod
    def _set_dword(winreg, subkey: str, value_name: str, value: int) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, value)

    @staticmethod
    def _query_string(winreg, subkey: str, value_name: str) -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                value, _value_type = winreg.QueryValueEx(key, value_name)
        except OSError:
            return None
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _delete_current_user_tree(winreg, subkey: str) -> None:
        if hasattr(ctypes, "windll"):
            try:
                result = ctypes.windll.advapi32.RegDeleteTreeW(ctypes.c_void_p(0x80000001), subkey)
                if result in (0, 2):
                    return
            except (AttributeError, OSError):
                pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except OSError:
            pass

    @staticmethod
    def _query_key_filetime_hex(winreg, key) -> str:
        try:
            _subkeys, _values, last_write_filetime = winreg.QueryInfoKey(key)
        except (AttributeError, OSError):
            last_write_filetime = WindowsFileAssociationService._current_filetime()
        return f"{last_write_filetime - (last_write_filetime % FILETIME_TICKS_PER_MINUTE):016x}"

    @staticmethod
    def _current_filetime() -> int:
        timestamp = datetime.now(timezone.utc).timestamp()
        return int((timestamp + FILETIME_EPOCH_OFFSET_SECONDS) * 10_000_000)

    @staticmethod
    def _current_user_sid() -> str:
        if hasattr(ctypes, "windll"):
            try:
                return WindowsFileAssociationService._current_user_sid_from_token()
            except OSError:
                pass
        try:
            completed = subprocess.run(
                ["whoami", "/user", "/fo", "csv", "/nh"],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
            raise OSError("whoami failed") from exc
        parts = [part.strip().strip('"') for part in completed.stdout.strip().split(",")]
        if len(parts) < 2 or not parts[1]:
            raise OSError("whoami did not return a SID")
        return parts[1].lower()

    @staticmethod
    def _current_user_sid_from_token() -> str:
        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

        class TOKEN_USER(ctypes.Structure):
            _fields_ = [("User", SID_AND_ATTRIBUTES)]

        TOKEN_QUERY = 0x0008
        TOKEN_USER_CLASS = 1
        ERROR_INSUFFICIENT_BUFFER = 122
        token = wintypes.HANDLE()
        if not ctypes.windll.advapi32.OpenProcessToken(
            ctypes.windll.kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
        ):
            raise OSError("OpenProcessToken failed")
        try:
            required = wintypes.DWORD(0)
            ctypes.windll.advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(required))
            if ctypes.windll.kernel32.GetLastError() != ERROR_INSUFFICIENT_BUFFER:
                raise OSError("GetTokenInformation size query failed")
            buffer = ctypes.create_string_buffer(required.value)
            if not ctypes.windll.advapi32.GetTokenInformation(
                token, TOKEN_USER_CLASS, buffer, required, ctypes.byref(required)
            ):
                raise OSError("GetTokenInformation failed")
            token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
            sid_ptr = wintypes.LPWSTR()
            if not ctypes.windll.advapi32.ConvertSidToStringSidW(token_user.User.Sid, ctypes.byref(sid_ptr)):
                raise OSError("ConvertSidToStringSidW failed")
            try:
                sid_value = sid_ptr.value
                if not sid_value:
                    raise OSError("ConvertSidToStringSidW returned an empty SID")
                return sid_value.lower()
            finally:
                ctypes.windll.kernel32.LocalFree(sid_ptr)
        finally:
            ctypes.windll.kernel32.CloseHandle(token)

    @staticmethod
    def _user_experience_string() -> str:
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        for shell32_path in (system_root / "SysWOW64" / "shell32.dll", system_root / "System32" / "shell32.dll"):
            try:
                data = shell32_path.read_bytes()[: 5 * 1024 * 1024]
            except OSError:
                continue
            text = data.decode("utf-16le", errors="ignore")
            marker = "User Choice set via Windows User Experience"
            start = text.find(marker)
            end = text.find("}", start)
            if start >= 0 and end > start:
                return text[start : end + 1]
        return USER_CHOICE_EXPERIENCE

    @staticmethod
    def _notify_associations_changed() -> None:
        if not hasattr(ctypes, "windll"):
            return
        try:
            ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        except (AttributeError, OSError):
            pass

    @staticmethod
    def _build_userchoice_hash(
        extension: str,
        user_sid: str,
        prog_id: str,
        filetime_hex: str,
        user_experience: str,
    ) -> str:
        payload = f"{extension}{user_sid}{prog_id}{filetime_hex}{user_experience}\0".lower()
        data = payload.encode("utf-16le")
        # Windows UserChoice 的兼容哈希固定使用 MD5；它不是完整性或信任判断。
        md5 = hashlib.md5(data, usedforsecurity=False).digest()
        part1 = WindowsFileAssociationService._ms_userchoice_hash_1(data, md5)
        part2 = WindowsFileAssociationService._ms_userchoice_hash_2(data, md5)
        return base64.b64encode(bytes(a ^ b for a, b in zip(part1, part2, strict=True))).decode("ascii")

    @staticmethod
    def _u32(value: int) -> int:
        return value & 0xFFFFFFFF

    @staticmethod
    def _dword(data: bytes, index: int) -> int:
        return int.from_bytes(data[index * 4 : index * 4 + 4], "little", signed=False)

    @staticmethod
    def _u32_bytes(value: int) -> bytes:
        return WindowsFileAssociationService._u32(value).to_bytes(4, "little", signed=False)

    @staticmethod
    def _hash_dwords(data: bytes) -> list[int]:
        length = (1 if (((len(data) >> 2) & 1) < 1) else 0) + (len(data) >> 2) - 1
        return [WindowsFileAssociationService._dword(data, index) for index in range(length)]

    @staticmethod
    def _ms_userchoice_hash_1(data: bytes, md5: bytes) -> bytes:
        u32 = WindowsFileAssociationService._u32
        dword = WindowsFileAssociationService._dword
        length = (1 if (((len(data) >> 2) & 1) < 1) else 0) + (len(data) >> 2) - 1
        result_bytes = bytearray(8)
        if length <= 1 or (length & 1):
            return bytes(result_bytes)
        data_words = WindowsFileAssociationService._hash_dwords(data)
        md5_words = [dword(md5, index) for index in range(4)]
        cache = 0
        index = 0
        counter = ((length - 2) >> 1) + 1
        result = 0
        md51 = u32((md5_words[0] | 1) + 0x69FB0000)
        md52 = u32((md5_words[1] | 1) + 0x13DB0000)
        while counter:
            value = u32(data_words[index] + result)
            index += 2
            step = u32(md51 * value - 0x10FA9605 * (value >> 16))
            step = u32(0x79F8A395 * step + 0x689B6B9F * (step >> 16))
            step = u32(0xEA970001 * step - 0x3C101569 * (step >> 16))
            mixed = u32(step + cache)
            tail = u32(data_words[index - 1] + step)
            tail = u32(md52 * tail - 0x3CE8EC25 * (tail >> 16))
            tail = u32(0x59C3AF2D * tail - 0x2232E0F1 * (tail >> 16))
            result = u32(0x1EC90001 * tail + 0x35BD1EC9 * (tail >> 16))
            cache = u32(result + mixed)
            counter -= 1
        result_bytes[0:4] = WindowsFileAssociationService._u32_bytes(result)
        result_bytes[4:8] = WindowsFileAssociationService._u32_bytes(cache)
        return bytes(result_bytes)

    @staticmethod
    def _ms_userchoice_hash_2(data: bytes, md5: bytes) -> bytes:
        u32 = WindowsFileAssociationService._u32
        dword = WindowsFileAssociationService._dword
        length = (1 if (((len(data) >> 2) & 1) < 1) else 0) + (len(data) >> 2) - 1
        result_bytes = bytearray(8)
        if length <= 1 or (length & 1):
            return bytes(result_bytes)
        data_words = WindowsFileAssociationService._hash_dwords(data)
        md5_words = [dword(md5, index) for index in range(4)]
        result = 0
        index = 0
        cache = 0
        counter = ((length - 2) >> 1) + 1
        md51 = md5_words[0] | 1
        md52 = md5_words[1] | 1
        seed1 = u32(0xB1110000 * md51)
        seed2 = u32(0x16F50000 * md52)
        while counter:
            index += 2
            value = u32(data_words[index - 2] + result)
            step = u32(seed1 * value - 0x30674EEF * (u32(md51 * value) >> 16))
            step_high = step >> 16
            mixed = u32(0x5B9F0000 * step - 0x78F7A461 * step_high)
            mixed = u32(0xE9B30000 * step_high + 0x12CEB96D * (mixed >> 16))
            mixed2 = u32(0x1D830000 * mixed + 0x257E1D83 * (mixed >> 16))
            tail = u32(mixed2 + data_words[index - 1])
            tail = u32(seed2 * tail - 0x5D8BE90B * (u32(md52 * tail) >> 16))
            tail_high = tail >> 16
            tail2 = u32(u32(0x96FF0000 * tail - 0x2C7C6901 * tail_high) >> 16)
            result = u32(0xF2310000 * tail2 - 0x405B6097 * (u32(0x7C932B89 * tail2 - 0x5C890000 * tail_high) >> 16))
            cache = u32(cache + result + mixed2)
            counter -= 1
        result_bytes[0:4] = WindowsFileAssociationService._u32_bytes(result)
        result_bytes[4:8] = WindowsFileAssociationService._u32_bytes(cache)
        return bytes(result_bytes)
