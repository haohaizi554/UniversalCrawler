"""为测试矩阵支持的 Python 版本提供统一 TOML 读取入口。"""

try:
    from tomllib import load, loads
except ModuleNotFoundError:  # Python 3.10 由 coverage[toml] 提供 tomli。
    from tomli import load, loads


__all__ = ["load", "loads"]
