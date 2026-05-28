"""服务模块，负责 `app/services/auth_service.py` 对应的业务支撑能力。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from app.exceptions import CookieLoadError, CookieSaveError


class AuthService:
    """认证文件读写服务，统一把底层 IO/JSON 异常转成领域异常。"""

    @staticmethod
    def _safe_to_string(value: Any) -> str | None:
        """提供 `_safe_to_string` 对应的内部辅助逻辑，供 `AuthService` 使用。"""
        try:
            return str(value)
        except (TypeError, ValueError):
            return None

    def load_json_file(self, file_path: str) -> Any:
        """加载 `json_file` 对应的数据、配置或资源，供 `AuthService` 使用。"""
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CookieLoadError(str(exc)) from exc

    def save_json_file(self, file_path: str, payload: Any) -> None:
        """保存 `json_file` 对应的数据、配置或文件，供 `AuthService` 使用。"""
        try:
            directory = os.path.dirname(file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=4, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            raise CookieSaveError(str(exc)) from exc

    @staticmethod
    def extract_cookie_list(payload: list[dict] | dict | None) -> list[dict]:
        """提取 `cookie_list` 对应的关键信息，供 `AuthService` 使用。"""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
            return payload["cookies"]
        return []

    @classmethod
    def extract_cookie_dict(cls, payload: list[dict] | dict | None) -> dict[str, str]:
        """提取 `cookie_dict` 对应的关键信息，供 `AuthService` 使用。"""
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
    def build_cookie_string(cls, payload: list[dict] | dict | None, required_cookie: str | None = None) -> str:
        """构建 `cookie_string` 对应的结果、参数或对象，供 `AuthService` 使用。"""
        cookie_dict = cls.extract_cookie_dict(payload)
        if required_cookie and required_cookie not in cookie_dict:
            return ""
        return "; ".join(f"{name}={value}" for name, value in cookie_dict.items())

    def restore_playwright_cookies(self, context, file_path: str) -> bool:
        """执行 `restore_playwright_cookies` 对应的业务逻辑，供 `AuthService` 使用。"""
        payload = self.load_json_file(file_path)
        cookies = self.extract_cookie_list(payload)
        if not cookies:
            return False
        context.add_cookies(cookies)
        return True

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
        """执行 `wait_for_cookie_and_persist` 对应的业务逻辑，供 `AuthService` 使用。"""
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
        """执行 `has_cookie` 对应的业务逻辑，供 `AuthService` 使用。"""
        if isinstance(cookies, list):
            return any(cookie.get("name") == cookie_name for cookie in cookies)
        if isinstance(cookies, dict):
            return cookie_name in cookies
        return False
