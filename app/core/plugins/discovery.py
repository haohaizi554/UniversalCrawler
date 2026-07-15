"""从 SPI、Python 入口点及外部目录发现插件。"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BasePlugin

# 内置 SPI 插件

def discover_builtin_plugins() -> list[type[BasePlugin]]:
    """导入内置定义以触发 SPI 自动注册，并返回排好序的插件类。"""
    from .base import BasePlugin

    # 单纯导入定义模块即可触发 ``BasePlugin.__init_subclass__``。
    from . import definitions  # noqa: F401

    classes = list(BasePlugin.get_subclasses().values())
    return _sort_classes(classes)

# 通过 pip 安装并声明入口点的插件

DISCOVERY_ENTRY_POINT_GROUP = "ucrawl.plugins"

def discover_entry_point_plugins() -> list[type[BasePlugin]]:
    """发现注册在 ``ucrawl.plugins`` 入口点组中的插件。"""
    from .base import BasePlugin

    classes: list[type[BasePlugin]] = []
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group=DISCOVERY_ENTRY_POINT_GROUP)
    except (ImportError, TypeError):
        return classes

    for ep in eps:
        try:
            plugin_cls = ep.load()
            if (
                inspect.isclass(plugin_cls)
                and issubclass(plugin_cls, BasePlugin)
                and plugin_cls is not BasePlugin
            ):
                classes.append(plugin_cls)
        except Exception:
            continue

    return _sort_classes(classes)

# 用户外部目录插件

_EXTERNAL_PLUGIN_DIR: str | None = None
_EXTERNAL_MTIME: dict[str, float] = {}  # 文件路径到最近修改时间的缓存

def set_external_plugin_dir(path: str | None) -> None:
    """设置外部插件目录；传入 ``None`` 时关闭该发现来源。"""
    global _EXTERNAL_PLUGIN_DIR
    _EXTERNAL_PLUGIN_DIR = path

def get_external_plugin_dir() -> str | None:
    """返回已配置的外部插件目录，未启用时返回 ``None``。"""
    return _EXTERNAL_PLUGIN_DIR

def discover_external_plugins(
    plugin_dir: str | None = None,
    *,
    force: bool = False,
) -> list[type[BasePlugin]]:
    """从目录中的 ``.py`` 文件发现插件类。

    导入时临时把目录加入 ``sys.path``，且只收集当前文件实际定义的
    ``BasePlugin`` 具体子类。文件修改时间会被缓存，常规调用仅重新导入发生
    变化的文件；``force=True`` 可强制全部重载。
    """
    from .base import BasePlugin

    target_dir = plugin_dir or _EXTERNAL_PLUGIN_DIR
    if not target_dir or not os.path.isdir(target_dir):
        return []

    target_dir = os.path.abspath(target_dir)
    old_mtimes = dict(_EXTERNAL_MTIME)

    classes: list[type[BasePlugin]] = []

    py_files = sorted(
        f for f in os.listdir(target_dir)
        if f.endswith(".py") and not f.startswith("_")
    )

    for fname in py_files:
        fpath = os.path.join(target_dir, fname)
        try:
            mtime = os.path.getmtime(fpath)
        except OSError:
            continue

        mod_name = f"ucrawl_ext_plugin_{fname[:-3]}"

        # 未变更文件沿用已加载模块，避免热重载反复执行模块级副作用。
        if not force and old_mtimes.get(fpath) == mtime and mod_name in sys.modules:
            _EXTERNAL_MTIME[fpath] = mtime
            # 即使不重新导入，也要从已加载模块重新收集插件类。
            module = sys.modules[mod_name]
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, BasePlugin)
                    and obj is not BasePlugin
                    and obj.__module__ == module.__name__
                ):
                    classes.append(obj)
            continue

        # 删除旧模块后重新导入，确保文件修改能够生效。
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        if target_dir not in sys.path:
            sys.path.insert(0, target_dir)

        try:
            module = importlib.import_module(mod_name)
            _EXTERNAL_MTIME[fpath] = mtime
        except Exception:
            _EXTERNAL_MTIME.pop(fpath, None)
            continue

        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BasePlugin)
                and obj is not BasePlugin
                and obj.__module__ == module.__name__
            ):
                classes.append(obj)

    return _sort_classes(classes)

# 汇总所有发现来源

def iter_plugin_classes() -> list[type[BasePlugin]]:
    """汇总内置 SPI、Python 入口点与外部目录插件。

    结果按 ``(sort_order, name, class_name)`` 稳定排序。
    """
    seen: set[str] = set()
    all_classes: list[type[BasePlugin]] = []

    for discover_fn in (
        discover_builtin_plugins,
        discover_entry_point_plugins,
        discover_external_plugins,
    ):
        for cls in discover_fn():
            pid = getattr(cls, "id", None)
            if pid and pid not in seen:
                seen.add(pid)
                all_classes.append(cls)

    return _sort_classes(all_classes)

def discover_builtin_plugin_instances() -> list:
    """实例化全部已发现的插件类。"""
    return [cls() for cls in iter_plugin_classes()]

# 内部排序规则

def _sort_classes(
    classes: list[type["BasePlugin"]],
) -> list[type["BasePlugin"]]:
    """依次按排序值、显示名称和类名排列插件类。"""
    return sorted(
        classes,
        key=lambda cls: (
            getattr(cls, "sort_order", 1000),
            getattr(cls, "name", cls.__name__),
            cls.__name__,
        ),
    )
