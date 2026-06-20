"""Backward-compatible import path for Qt runtime helpers.

The implementation lives in :mod:`app.utils.qt_runtime` so app/UI/controller
code does not depend back on the entry layer.
"""

from app.utils.qt_runtime import (
    MAIN_APP_USER_MODEL_ID,
    WEB_APP_USER_MODEL_ID,
    ensure_windows_app_user_model_id,
    load_qt_icon,
    resolve_icon_path,
)

__all__ = [
    "MAIN_APP_USER_MODEL_ID",
    "WEB_APP_USER_MODEL_ID",
    "ensure_windows_app_user_model_id",
    "load_qt_icon",
    "resolve_icon_path",
]
