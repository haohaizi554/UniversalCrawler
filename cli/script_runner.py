"""启动时脚本注入：python web_main.py --script my_automation.py

在 web 服务启动后自动调用指定脚本，传入 WebController 实例。
脚本可调用 SDK 操作或直接通过 controller 操作。

脚本模板 (my_automation.py)::

    from cli import UcrawlSDK

    def main(controller):
        sdk = UcrawlSDK(save_dir=controller.current_save_dir)
        result = sdk.search("douyin", "测试关键词", max_items=5)
        for item in result["items"]:
            print(item["title"])
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from typing import Any

def run_injected_script(script_path: str, controller: Any, **extra) -> int:
    """加载并执行注入脚本。

    Args:
        script_path: 脚本路径 (绝对或相对)
        controller: WebController 实例
        **extra: 额外参数 (命令行 --script-arg 传入)

    Returns:
        脚本 main() 函数的返回值
    """
    if not os.path.exists(script_path):
        sys.stderr.write(f"❌ 脚本不存在: {script_path}\n")
        return 1

    # 加载模块
    spec = importlib.util.spec_from_file_location("injected_script", script_path)
    if spec is None or spec.loader is None:
        sys.stderr.write(f"❌ 无法加载脚本: {script_path}\n")
        return 1
    module = importlib.util.module_from_spec(spec)
    sys.stderr.write(f"[注入] 加载脚本: {script_path}\n")
    spec.loader.exec_module(module)

    # 调用 main(controller, **extra)
    if not hasattr(module, "main"):
        sys.stderr.write("❌ 脚本必须定义 main(controller, **kwargs) 函数\n")
        return 1

    main_fn = module.main
    sys.stderr.write(f"[注入] 调用 main(controller, {list(extra.keys())})\n")
    result = main_fn(controller, **extra)
    sys.stderr.write(f"[注入] 脚本返回: {result}\n")
    return result if isinstance(result, int) else 0

def parse_script_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 --script 和 --script-arg 参数。

    Example:
        python web_main.py --script my.py --script-arg name=alice --script-arg count=5
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--script", help="启动后自动执行的脚本路径")
    parser.add_argument(
        "--script-arg",
        action="append",
        default=[],
        help="传递给脚本的 key=value 形式参数 (可多次)",
    )
    parser.add_argument("--script-strict", action="store_true", help="脚本失败时退出 web 服务")
    parser.add_argument("--script-after-ready", action="store_true", default=True, help="等 web 服务就绪后才执行")
    parser.add_argument("--script-delay", type=float, default=0.0, help="执行前延迟秒数")
    return parser.parse_known_args(argv)[0]

def parse_kv_args(items: list[str]) -> dict:
    """把 ['name=alice', 'count=5'] 解析为 {'name': 'alice', 'count': 5}。

    自动类型转换：int / float / bool / str。
    """
    result = {}
    for item in items:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        result[k] = _auto_convert(v)
    return result

def _auto_convert(v: str):
    """自动类型转换。"""
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v
