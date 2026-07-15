"""认证/Cookie 文件读写与 Playwright 登录态持久化。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit

from app.exceptions import CookieLoadError, CookieSaveError

class AuthService:
    """统一处理 Cookie JSON 格式，并把文件 IO/JSON 异常收敛为领域异常。

    Cookie 以明文 JSON 保存；``file_path``/``save_path`` 必须来自受信配置，目录权限
    由部署方负责。本服务不执行路径授权，也不加密 Cookie 内容。
    """

    @staticmethod
    def _safe_to_string(value: Any) -> str | None:
        try:
            return str(value)
        except (TypeError, ValueError):
            return None

    def load_json_file(self, file_path: str) -> Any:
        """文件不存在视为尚未登录；读取或 JSON 解析失败统一抛出 CookieLoadError。"""
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CookieLoadError(str(exc)) from exc

    def save_json_file(self, file_path: str, payload: Any) -> None:
        """先在目标目录写入并 fsync 临时文件，再用 os.replace 发布完整 JSON。"""
        temp_path: str | None = None
        try:
            serialized = json.dumps(payload, indent=4, ensure_ascii=False)
            destination = os.path.abspath(file_path)
            directory = os.path.dirname(destination)
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory,
                prefix=f".{os.path.basename(destination)}.",
                suffix=".tmp",
                delete=False,
            ) as fp:
                temp_path = fp.name
                fp.write(serialized)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(temp_path, destination)
            temp_path = None
        except (OSError, TypeError, ValueError) as exc:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise CookieSaveError(str(exc)) from exc

    @staticmethod
    def extract_cookie_list(payload: list[dict] | dict | None) -> list[dict]:
        """兼容 Cookie 列表和 Playwright storage_state 的 cookies 包装。"""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
            return payload["cookies"]
        return []

    @classmethod
    def extract_cookie_dict(cls, payload: list[dict] | dict | None) -> dict[str, str]:
        """接受平面字典或 Playwright Cookie 列表，并过滤无法安全转成字符串的项。"""
        if isinstance(payload, dict) and "cookies" not in payload:
            result: dict[str, str] = {}
            for key, value in payload.items():
                safe_key = cls._safe_to_string(key)
                safe_value = cls._safe_to_string(value)
                if safe_key is not None and safe_value is not None:
                    result[safe_key] = safe_value
            return result
        cookies = cls.extract_cookie_list(payload)
        result: dict[str, str] = {}
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value is not None:
                safe_name = cls._safe_to_string(name)
                safe_value = cls._safe_to_string(value)
                if safe_name is not None and safe_value is not None:
                    result[safe_name] = safe_value
        return result

    @classmethod
    def extract_cookie_dict_for_url(
        cls,
        payload: list[dict] | dict | None,
        url: str,
        *,
        now: float | None = None,
    ) -> dict[str, str]:
        """按浏览器域名、路径、Secure 与过期规则筛出目标 URL 可用的 Cookie。"""
        if isinstance(payload, dict) and "cookies" not in payload:
            return cls.extract_cookie_dict(payload)
        parsed = urlsplit(str(url or ""))
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return {}
        request_path = parsed.path or "/"
        current_time = time.time() if now is None else float(now)
        result: dict[str, str] = {}
        for cookie in cls.extract_cookie_list(payload):
            if not isinstance(cookie, dict):
                continue
            domain = str(cookie.get("domain") or "").strip().lower().rstrip(".")
            if domain:
                include_subdomains = domain.startswith(".")
                normalized_domain = domain.lstrip(".")
                domain_matches = host == normalized_domain or (
                    include_subdomains and host.endswith(f".{normalized_domain}")
                )
                if not domain_matches:
                    continue
            cookie_path = str(cookie.get("path") or "/")
            if not request_path.startswith(cookie_path):
                continue
            if bool(cookie.get("secure")) and parsed.scheme.lower() != "https":
                continue
            try:
                expires = float(cookie.get("expires", -1) or -1)
            except (TypeError, ValueError):
                expires = -1
            if expires > 0 and expires <= current_time:
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            safe_name = cls._safe_to_string(name)
            safe_value = cls._safe_to_string(value)
            if safe_name is not None and safe_value is not None:
                result[safe_name] = safe_value
        return result

    @classmethod
    def build_cookie_string(cls, payload: list[dict] | dict | None, required_cookie: str | None = None) -> str:
        """缺少 required_cookie 时返回空串，避免携带不完整登录态发起请求。"""
        cookie_dict = cls.extract_cookie_dict(payload)
        if required_cookie and required_cookie not in cookie_dict:
            return ""
        return "; ".join(f"{name}={value}" for name, value in cookie_dict.items())

    def restore_playwright_cookies(self, context, file_path: str) -> bool:
        """兼容仍需向已创建 context 注入 Cookie 的旧调用方。"""
        payload = self.load_json_file(file_path)
        cookies = self.extract_cookie_list(payload)
        if not cookies:
            return False
        context.add_cookies(cookies)
        return True

    def load_playwright_storage_state(self, file_path: str) -> dict[str, list[dict]] | None:
        """读取可直接交给 ``browser.new_context`` 的完整登录态。

        新版文件保留 Playwright 的 cookies 和 origins/localStorage；旧版裸 Cookie
        列表会补成合法 storage_state，避免升级后要求用户重新登录。
        """
        payload = self.load_json_file(file_path)
        cookies = self.extract_cookie_list(payload)
        if not cookies:
            return None
        origins = payload.get("origins", []) if isinstance(payload, dict) else []
        if not isinstance(origins, list):
            origins = []
        return {
            "cookies": list(cookies),
            "origins": list(origins),
        }

    def wait_for_cookie_and_persist(
        self,
        *,
        context,
        cookie_name: str,
        save_path: str,
        save_mode: str = "cookies",
        max_attempts: int = 120,
        interval_seconds: float = 1.0,
        stop_check=None,
        wait_callback=None,
    ) -> bool:
        """轮询 Playwright context；stop_check 可中止，wait_callback 由调用方接管等待节奏。"""

        for _ in range(max_attempts):
            if stop_check and stop_check():
                return False
            cookies = context.cookies()
            if self.has_cookie(cookies, cookie_name):
                payload = context.storage_state() if save_mode == "storage_state" else cookies
                self.save_json_file(save_path, payload)
                return True
            if wait_callback:
                wait_callback()
            else:
                time.sleep(interval_seconds)
        return False

    @staticmethod
    def has_cookie(cookies: list[dict] | dict | None, cookie_name: str) -> bool:
        
        if isinstance(cookies, list):
            return any(cookie.get("name") == cookie_name for cookie in cookies)
        if isinstance(cookies, dict):
            return cookie_name in cookies
        return False
