"""UI components and stable historical component imports."""

import sys

from app.ui.layout import top_bar as _top_bar_module

sys.modules.setdefault(f"{__name__}.top_bar", _top_bar_module)
setattr(sys.modules[__name__], "top_bar", _top_bar_module)
