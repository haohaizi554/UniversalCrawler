#!/usr/bin/env python3
"""CrawlerWebPortal.exe 入口：直接启动 Web 模式。
由 packaging/portable.spec 在打包时自动生成。

设计要点：
- 直接调用 entry.web_entry.main()，完全绕过 dispatcher。
  避免 dispatcher 透传 [] 时误转 None，导致 web_entry 误读 sys.argv 的 --mode。
- 用户传入的 CLI 参数（--port / --host / --no-qt / --no-browser 等）
  全部原样转发给 web_entry。
- console=False：Qt 托盘 + 端口弹窗仍可见。
"""
import sys

from entry.web_entry import main as _main
sys.exit(_main(sys.argv[1:] if len(sys.argv) > 1 else None))
