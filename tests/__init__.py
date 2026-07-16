"""测试包初始化，以及非 pytest 入口的进程级数据隔离。"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory


# pytest 会在 conftest 中为每个用例提供独立目录；这里是给 IDE 直接运行
# unittest、run_core_suite 等入口兜底，防止测试构造的失败记录写进真实 user_data。
_PROCESS_TEST_DIRECTORY = TemporaryDirectory(
    prefix="ucrawl-test-runtime-",
    ignore_cleanup_errors=True,
)
TEST_USER_DATA_ROOT = Path(_PROCESS_TEST_DIRECTORY.name) / "user_data"

if not os.environ.get("UCRAWL_USER_DATA_ROOT", "").strip():
    os.environ["UCRAWL_USER_DATA_ROOT"] = str(TEST_USER_DATA_ROOT)
