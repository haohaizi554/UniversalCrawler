"""UCrawl 桌面 GUI 入口（薄适配层）。

行业对齐（PyPA 规范）：
- 在 `pyproject.toml` 的 `[project.gui-scripts]` 中注册为 `ucrawl-gui` 命令
- Windows 上启动**不弹黑窗**（与 console_scripts 区别）
- 透传到 `app.controllers.application_controller.ApplicationController`

历史对应：原 `main.py` (44 行)

调用链：
    ucrawl-gui (gui_script) -> entry.gui_entry:main() -> ApplicationController.run()
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from app.utils.qt_runtime import MAIN_APP_USER_MODEL_ID, ensure_windows_app_user_model_id

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

def _set_windows_app_user_model_id() -> None:
    """尽早设置 Windows AppUserModelID，避免任务栏图标分组取错。"""
    ensure_windows_app_user_model_id(MAIN_APP_USER_MODEL_ID)

def _normalize_argv(argv: Sequence[str] | None) -> list[str]:
    if argv is not None:
        return list(argv)
    return sys.argv[1:]

def _association_helper_requested(argv: Sequence[str]) -> bool:
    return (
        "--register-file-associations" in argv
        or "--set-default-file-associations" in argv
        or "--open-default-apps-settings" in argv
        or "--check-file-associations" in argv
    )

def _association_kinds(argv: Sequence[str]) -> set[str]:
    kinds: set[str] = set()
    items = list(argv)
    indexes = [
        index
        for index, arg in enumerate(items)
        if arg in {"--register-file-associations", "--set-default-file-associations", "--check-file-associations"}
    ]
    if not indexes:
        return kinds
    index = min(indexes)

    for arg in items[index + 1:]:
        if arg.startswith("-"):
            break
        for token in arg.replace(",", " ").split():
            if token in {"video", "image"}:
                kinds.add(token)
    return kinds

def _option_value(argv: Sequence[str], option: str) -> str | None:
    items = list(argv)
    for index, arg in enumerate(items):
        if arg == option and index + 1 < len(items):
            return items[index + 1]
        prefix = option + "="
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return None

def _handle_association_helper(argv: Sequence[str]) -> bool:
    if not _association_helper_requested(argv):
        return False

    from app.services.windows_file_association_service import APP_NAME, WindowsFileAssociationService

    service = WindowsFileAssociationService(app_name=_option_value(argv, "--app-name") or APP_NAME)
    kinds = _association_kinds(argv)
    include_video = ("video" in kinds) or not kinds
    include_image = "image" in kinds
    if "--register-file-associations" in argv:
        executable = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
        service.register_current_user(
            executable,
            include_video=include_video,
            include_image=include_image,
        )
    if "--set-default-file-associations" in argv:
        default_result = service.set_current_user_defaults(
            include_video=include_video,
            include_image=include_image,
        )
        print(f"set_default={default_result.applied}")
        print(f"defaulted={','.join(default_result.defaulted_extensions)}")
        print(f"failed={','.join(default_result.failed_extensions)}")
        if default_result.message:
            print(f"message={default_result.message}")
    if "--check-file-associations" in argv:
        diagnostics = service.diagnose_current_user(include_video=include_video, include_image=include_image)
        if not diagnostics.available:
            print(diagnostics.message)
        else:
            print(f"registered_app={diagnostics.registered_app}")
            print(f"defaulted={','.join(diagnostics.defaulted_extensions)}")
            print(f"pending={','.join(diagnostics.pending_extensions)}")
            print(f"settings_uri={diagnostics.settings_uri}")
    if "--open-default-apps-settings" in argv:
        service.open_default_apps_settings()
    return True

def main(argv: list[str] | None = None) -> int:
    """GUI 入口：启动 PyQt6 桌面应用。

    Args:
        argv: 命令行参数（透传给 ApplicationController，保留向后兼容）

    Returns:
        退出码
    """
    import multiprocessing
    import traceback

    from app.debug_logger import debug_logger

    try:
        multiprocessing.freeze_support()
        _set_windows_app_user_model_id()
        normalized_argv = _normalize_argv(argv)
        if _handle_association_helper(normalized_argv):
            return 0
        from app.controllers.application_controller import ApplicationController

        controller = ApplicationController(launch_args=normalized_argv)
        controller.run()
        return 0
    except Exception as exc:
        debug_logger.log_exception("gui_entry", "startup", exc)
        sys.stderr.write("应用启动失败，请查看 logs/latest_error_summary.md 或 latest_debug.log\n")
        traceback.print_exc(file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
