"""Cookie, persistence, and runtime configuration helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import cfg
from app.utils.runtime_paths import is_temporary_path
from shared.runtime_options import (
    build_missav_proxy_url,
    compose_runtime_config,
    validate_config_types,
)


def auth_mode(auth_spec: dict) -> str:
    """Return a supported authentication mode with a safe fallback."""

    mode = str(auth_spec.get("mode") or "unspecified").strip().lower()
    return mode if mode in {"cookie", "none", "unspecified"} else "unspecified"


def auth_file_name(auth_spec: dict) -> str | None:
    """Resolve the configured authentication filename for a cookie contract."""

    if auth_mode(auth_spec) != "cookie":
        return None
    default_file = str(auth_spec.get("default_file") or "").strip()
    config_key = str(auth_spec.get("config_key") or "").strip()
    configured = None
    if config_key:
        try:
            configured = cfg.get("auth", config_key, default_file)
        except Exception:
            configured = None
    value = str(configured or default_file).strip()
    return value or None


def required_cookie_keys(auth_spec: dict) -> tuple[str, ...]:
    """Return the declared any-of Cookie keys for local preflight."""

    values = auth_spec.get("cookie_names")
    if not isinstance(values, list):
        return ()
    return tuple(
        str(value).strip()
        for value in values
        if str(value).strip()
    )


def login_description(auth_spec: dict) -> str:
    """Return plugin-provided login guidance."""

    return str(
        auth_spec.get("login_description")
        or "该插件未提供登录说明"
    )


def find_cookie_file(auth_spec: dict) -> Path | None:
    """Return the first non-empty compatible Cookie JSON path."""

    auth_name = auth_file_name(auth_spec)
    if auth_name is None:
        return None

    configured = Path(auth_name).expanduser()
    default_name = str(auth_spec.get("default_file") or "").strip()
    candidates = [
        configured,
        Path.home() / ".ucrawl" / configured.name,
        Path(__file__).resolve().parent.parent.parent / configured.name,
    ]
    if default_name and default_name != configured.name:
        candidates.extend(
            (
                Path(default_name),
                Path.home() / ".ucrawl" / default_name,
                Path(__file__).resolve().parent.parent.parent / default_name,
            )
        )
    try:
        from app.utils.runtime_paths import user_data_root

        candidates.append(user_data_root() / configured.name)
        if default_name and default_name != configured.name:
            candidates.append(user_data_root() / default_name)
    except Exception:
        pass

    for path in dict.fromkeys(candidates):
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def load_cookie(auth_spec: dict) -> dict | list | None:
    """Read a non-empty dict/list Cookie JSON document."""

    path = find_cookie_file(auth_spec)
    if path is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, (dict, list)) and data else None


def check_cookie_valid(auth_spec: dict, cookie_data) -> bool:
    """Check whether any plugin-declared Cookie key is present."""

    required = required_cookie_keys(auth_spec)
    if not required:
        return auth_mode(auth_spec) != "cookie"

    from app.services.auth_service import AuthService

    cookie_dict = AuthService.extract_cookie_dict(cookie_data)
    return any(cookie_dict.get(key) for key in required)


def is_temp_dir(path: str) -> bool:
    """Return whether a path belongs to the operating-system temp area."""

    return is_temporary_path(path)


def persist_save_dir(save_dir: str) -> None:
    """Persist a confirmed, non-temporary interactive download directory."""

    if not save_dir or is_temp_dir(save_dir):
        return
    try:
        cfg.set("common", "save_directory", save_dir)
    except Exception:
        pass


def build_config_summary_lines(
    guide: dict,
    config: dict,
    platform_name: str,
    keyword: str,
    save_dir: str,
) -> list[str]:
    """Build confirmation copy from plugin-owned field metadata."""

    lines = [
        f"  平台:   {platform_name}",
        f"  关键词: {keyword}",
        f"  保存到: {save_dir}",
    ]
    for field in guide.get("fields", []):
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if key not in config:
            continue
        value = config[key]
        display = str(value)
        for choice in field.get("choices", []):
            if (
                isinstance(choice, dict)
                and choice.get("value") == value
            ):
                display = str(choice.get("label") or value)
                break
        label = str(field.get("summary_label") or key)
        lines.append(f"  {label}: {display}")

    auth_summary = str(
        guide.get("auth", {}).get("summary") or ""
    )
    if auth_summary:
        lines.append(f"  登录:   {auth_summary}")
    return lines


def finalize_interactive_config(
    args,
    platform_id: str,
    config: dict,
) -> dict:
    """Apply all non-interactive overrides before confirmation."""

    finalized = dict(config)
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            parsed = json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--config JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("--config 必须是 JSON 对象")
        config_err = validate_config_types(parsed)
        if config_err:
            raise ValueError(config_err)
        finalized.update(
            {key: value for key, value in parsed.items() if value is not None}
        )

    value_overrides = {
        "cookie": "cookie",
        "download_strategy": "download_strategy",
        "referer": "referer",
        "ua": "ua",
        "folder_name": "folder_name",
        "file_name": "file_name",
        "content_type": "content_type",
        "proxy": "proxy",
        "priority": "priority",
    }
    for arg_name, config_name in value_overrides.items():
        value = getattr(args, arg_name, None)
        if value:
            finalized[config_name] = value

    if getattr(args, "use_subdir", None):
        finalized["use_subdir"] = True
    if getattr(args, "individual_only", None):
        finalized["individual_only"] = True
    return compose_runtime_config(
        platform_id,
        user_config=finalized,
        defaults_factory=lambda _source: {},
        proxy_normalizer=build_missav_proxy_url,
    )
