from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.utils import runtime_paths


def test_pytest_default_user_data_root_is_isolated_from_workspace():
    root = runtime_paths.user_data_root()

    assert os.environ.get(runtime_paths.USER_DATA_ROOT_ENV)
    assert root != runtime_paths.project_root() / "user_data"
    assert root.name == "user_data"


def test_unittest_package_bootstrap_supplies_runtime_root():
    """IDE 直接走 unittest 时也必须获得测试专用用户数据目录。"""

    env = os.environ.copy()
    env.pop(runtime_paths.USER_DATA_ROOT_ENV, None)
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; import tests; "
                "print(os.environ['UCRAWL_USER_DATA_ROOT'])"
            ),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    raw_root = completed.stdout.strip()
    assert raw_root
    isolated_root = Path(raw_root).resolve()
    assert isolated_root != (project_root / "user_data").resolve()
    assert isolated_root.name == "user_data"
