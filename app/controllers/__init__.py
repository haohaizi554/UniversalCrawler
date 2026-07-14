"""Application controller package and historical module aliases."""

import sys

from app.services import media_library_runtime as _media_library_module
from shared import controller_session as _controller_session_module

_PUBLIC_MODULE_ALIASES = {
    "media_library_mixin": _media_library_module,
    "session_mixin": _controller_session_module,
}
for _module_name, _module in _PUBLIC_MODULE_ALIASES.items():
    sys.modules.setdefault(f"{__name__}.{_module_name}", _module)
    setattr(sys.modules[__name__], _module_name, _module)
