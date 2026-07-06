from __future__ import annotations

# ProxyManager 代码未实现，跳过：当前仓库只有 .trae/rules/anti-detection.md
# 中的接口规划，没有 app/core/proxy_manager.py 或等价运行时代码。

import unittest


@unittest.skip("ProxyManager runtime code is not implemented yet.")
class ProxyManagerMissingTests(unittest.TestCase):
    def test_proxy_manager_runtime_code_not_implemented(self) -> None:
        """Document the missing runtime module without creating fake coverage."""
        raise AssertionError("unreachable")
