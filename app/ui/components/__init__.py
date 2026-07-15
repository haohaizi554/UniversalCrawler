"""导出 UI 组件，并保留稳定的兼容导入入口。"""

import sys

from app.ui.layout import top_bar as _top_bar_module

sys.modules.setdefault(f"{__name__}.top_bar", _top_bar_module)
setattr(sys.modules[__name__], "top_bar", _top_bar_module)
