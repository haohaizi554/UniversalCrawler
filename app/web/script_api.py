"""启动时脚本注入 API，在 Web 服务就绪后调用脚本的 main(controller, **kwargs)。"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import threading
from typing import Any

def run_injected_script(script_path: str, controller: Any, **extra) -> int:
    """加载并执行注入脚本。

    参数:
        script_path: 脚本路径 (绝对或相对)
        controller: WebController 实例
        **extra: 额外参数 (命令行 --script-arg 传入)

    返回:
        脚本 main() 函数的返回值
    """
    if not os.path.exists(script_path):
        sys.stderr.write(f"❌ 脚本不存在: {script_path}\n")
        return 1

    spec = importlib.util.spec_from_file_location("injected_script", script_path)
    if spec is None or spec.loader is None:
        sys.stderr.write(f"❌ 无法加载脚本: {script_path}\n")
        return 1

    module = importlib.util.module_from_spec(spec)
    sys.stderr.write(f"[注入] 加载脚本: {script_path}\n")
    spec.loader.exec_module(module)

    if not hasattr(module, "main"):
        sys.stderr.write("❌ 脚本必须定义 main(controller, **kwargs) 函数\n")
        return 1

    main_fn = module.main
    sys.stderr.write(f"[注入] 调用 main(controller, {list(extra.keys())})\n")
    result = main_fn(controller, **extra)
    sys.stderr.write(f"[注入] 脚本返回: {result}\n")
    return result if isinstance(result, int) else 0

def parse_script_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 --script 和 --script-arg 参数。"""
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
    """依次识别布尔值、整数和浮点数，无法识别时保留原字符串。"""
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v

def inject_script_async(
    script_path: str,
    controller: Any,
    strict: bool = False,
    delay: float = 0.0,
    **kwargs,
) -> threading.Thread:
    """异步执行注入脚本（不阻塞 Web 服务）。

    参数:
        script_path: 脚本路径
        controller: WebController 实例
        strict: 脚本失败时是否退出 Web 服务
        delay: 执行前延迟秒数
        **kwargs: 传递给脚本的参数

    返回:
        脚本执行线程
    """
    def _run():
        import time
        if delay > 0:
            time.sleep(delay)
        try:
            rc = run_injected_script(script_path, controller, **kwargs)
        except Exception as e:
            print(f"❌ 注入脚本异常: {e}")
            rc = 1
        if rc != 0 and strict:
            print(f"❌ 注入脚本退出码 {rc}，按 --script-strict 退出")
            import os
            os._exit(rc)
        else:
            print(f"✅ 注入脚本完成 (rc={rc})")

    thread = threading.Thread(target=_run, daemon=True, name="injected-script")
    thread.start()
    print(f"[注入] 启动脚本线程: {script_path}")
    return thread
