"""Qt 运行时辅助函数的向后兼容导入路径。

实现位于 :mod:`app.utils.qt_runtime`，避免 app/UI/controller 代码反向依赖
entry 层。
"""

from app.utils.qt_runtime import (
    MAIN_APP_USER_MODEL_ID,
    RELEASE_BUILDER_APP_USER_MODEL_ID,
    WEB_APP_USER_MODEL_ID,
    ensure_windows_app_user_model_id,
    load_qt_icon,
    resolve_icon_path,
)

__all__ = [
    "MAIN_APP_USER_MODEL_ID",
    "RELEASE_BUILDER_APP_USER_MODEL_ID",
    "WEB_APP_USER_MODEL_ID",
    "ensure_windows_app_user_model_id",
    "load_qt_icon",
    "resolve_icon_path",
]
