"""测试辅助：用 uvicorn 启动 web_entry 的 FastAPI 应用。

app.web.server 没有模块级 app（用 create_app() 工厂），
uvicorn 启动需要模块名:变量名 格式，所以这里写一个 shim：

    uvicorn tests.support.web_test_app:app --host 127.0.0.1 --port 8000

测试不需要真启动 web_entry（避免 Qt 弹窗），只需要 web FastAPI app 起来。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 让 app.web.server 可被 import
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 测试环境：禁用真爬虫
os.environ.setdefault("UCRAWL_OFFLINE", "1")

from app.web.server import create_app  # noqa: E402

# 暴露给 uvicorn 的 app 对象
app = create_app()
