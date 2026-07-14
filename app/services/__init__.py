"""应用服务层。"""

import sys

from app.services.auth_service import AuthService
from app.services.debug_service import DebugArtifactsService
from app.services.file_service import MediaLibraryService, ScanResult
from shared import frontend_page_definitions as _frontend_page_definitions_module

__all__ = [
    "AuthService",
    "DebugArtifactsService",
    "MediaLibraryService",
    "ScanResult",
]

sys.modules.setdefault(
    f"{__name__}.frontend_page_definitions",
    _frontend_page_definitions_module,
)
setattr(
    sys.modules[__name__],
    "frontend_page_definitions",
    _frontend_page_definitions_module,
)
