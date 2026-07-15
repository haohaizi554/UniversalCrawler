"""编排便携版与安装器构建，并在冻结前执行发布信任预检。"""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPDATE_TRUST_CONFIG = PROJECT_ROOT / "app" / "config" / "update_trust.py"


def _run_build(script_name: str) -> None:
    subprocess.run([sys.executable, f"packaging/{script_name}"], cwd=PROJECT_ROOT, check=True)


def _validate_production_trust(*, config_path: Path = UPDATE_TRUST_CONFIG) -> None:
    """公开信任配置不完整时在冻结生产客户端前失败，避免产出无法验证更新的版本。"""

    values = runpy.run_path(str(config_path))
    public_key = str(values.get("UPDATE_PUBLIC_KEY_PEM") or "")
    publishers = tuple(values.get("UPDATE_TRUSTED_PUBLISHERS") or ())
    thumbprints = tuple(values.get("UPDATE_TRUSTED_THUMBPRINTS") or ())
    if "BEGIN PUBLIC KEY" not in public_key or "PRIVATE KEY" in public_key:
        raise SystemExit("生产更新公钥未配置或格式无效，拒绝构建签名 Release。")
    if not publishers:
        raise SystemExit("生产更新发布者未配置，拒绝构建签名 Release。")
    if not thumbprints:
        raise SystemExit("生产更新证书指纹未配置，拒绝构建签名 Release。")

def main() -> None:
    _run_build("build_portable.py")
    _run_build("build_installer.py")
    if os.environ.get("UCRAWL_SIGN_WINDOWS") == "1":
        # 首轮安装包用于签名并提取公开证书身份；注入后必须重新冻结，
        # 否则最终客户端仍携带构建前的空信任根。
        _validate_production_trust()
        _run_build("build_portable.py")
        _run_build("build_installer.py")
        _validate_production_trust()

if __name__ == "__main__":
    main()
