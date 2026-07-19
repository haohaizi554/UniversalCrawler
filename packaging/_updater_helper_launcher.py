#!/usr/bin/env python3
"""updater_helper.exe 入口：独立安装 helper。
作为受 Git 管理的 canonical 构建入口，由 packaging/portable.spec 只读消费。
"""
import sys

from entry.updater_helper import main as _main
sys.exit(_main(sys.argv[1:]))
