#!/usr/bin/env python3
"""UniversalCrawlerPro.exe 入口：直接启动 GUI 模式。
作为受 Git 管理的 canonical 构建入口，由 packaging/portable.spec 只读消费。

设计要点：
- 直接调用 entry.gui_entry.main()，完全绕过 dispatcher。
- 双击 EXE 时**直接进入 GUI**，不再弹"模式选择菜单"（TUI 或 Qt 弹窗）。
- 用户从命令行传入的参数原样透传给 gui_entry（虽然 GUI 模式不消费参数，
  但保持与其它 entry 一致的 argv 转发语义）。
"""
import sys

from entry.gui_entry import main as _main
sys.exit(_main(sys.argv[1:] if len(sys.argv) > 1 else None))
