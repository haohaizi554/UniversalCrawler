from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run([sys.executable, "packaging/build_portable.py"], cwd=PROJECT_ROOT, check=True)
    subprocess.run([sys.executable, "packaging/build_installer.py"], cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    main()
