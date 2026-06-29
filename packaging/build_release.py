"""打包辅助脚本，负责 `packaging/build_release.py` 相关的构建、发布或运行时处理。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    """作为脚本入口组织整体执行流程。"""
    subprocess.run([sys.executable, "packaging/build_portable.py"], cwd=PROJECT_ROOT, check=True)
    subprocess.run([sys.executable, "packaging/build_installer.py"], cwd=PROJECT_ROOT, check=True)

if __name__ == "__main__":
    main()
