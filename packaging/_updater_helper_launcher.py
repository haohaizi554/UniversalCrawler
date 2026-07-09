#!/usr/bin/env python3
"""updater_helper.exe 入口：独立安装 helper。
由 packaging/portable.spec 在打包时自动生成。
"""
import sys

from entry.updater_helper import main as _main
sys.exit(_main(sys.argv[1:]))
