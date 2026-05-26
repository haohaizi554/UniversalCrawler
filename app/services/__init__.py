"""应用服务层。"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AuthService": (".auth_service", "AuthService"),
    "DebugArtifactsService": (".debug_service", "DebugArtifactsService"),
    "MediaLibraryService": (".file_service", "MediaLibraryService"),
    "ScanResult": (".file_service", "ScanResult"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr_name = _EXPORTS[name]
    module = import_module(module_path, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    "AuthService",
    "DebugArtifactsService",
    "MediaLibraryService",
    "ScanResult",
]
