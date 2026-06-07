"""测试注册表 — 集中管理所有测试类别与文件。

设计目标：
- 易于扩展：新增测试类别只需在 ``TEST_REGISTRY`` 中添加一项
- 自动发现：扫描 ``tests/`` 目录中所有 test_*.py 文件
- 插件目录：通过 ``register_plugin_directory()`` 把任意目录下的测试收编进来
- 元信息：每个类别带描述、图标、优先级、是否默认运行
- CLI/SDK/REST API 三层可调用同一份注册表

扩展方式
--------

**方式 1（推荐）**：直接在 ``TEST_REGISTRY`` 字典中加一项

.. code-block:: python

    TEST_REGISTRY["perf"] = TestCategory(
        id="perf",
        name="性能测试",
        description="基准测试 + 内存分析",
        files=["tests/test_perf_bench.py"],
        icon_color="#FF5722",
        priority=10,
    )

**方式 2（自动发现）**：把 ``test_*.py`` 文件丢到 ``tests/`` 即可被默认类别收录

**方式 3（程序化）**：

.. code-block:: python

    from tests.test_registry import register_category
    register_category(
        id="custom",
        name="我的自定义",
        files=["tests/test_custom.py"],
    )

**方式 4（插件目录，推荐给二次开发者）**：

.. code-block:: python

    from tests.test_registry import register_plugin_directory
    # 自动扫描 myapp/tests/ 下所有 test_*.py，归到一个新类别里
    register_plugin_directory(
        "myapp_plugin",
        "我的插件测试",
        "myapp/tests",
        icon_color="#9C27B0",
        icon_letter="M",
    )
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Protocol, runtime_checkable


# 项目根目录
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent

# 测试图标（优先项目根目录，其次 tests/ 目录）
TEST_ICON_PATH = PROJECT_ROOT / "test.ico" if (PROJECT_ROOT / "test.ico").exists() else TESTS_DIR / "test.ico"

# 插件目录根（用于向后兼容：未来插件可以放在这里）
PLUGIN_ROOT = PROJECT_ROOT / "tests" / "plugins"


@dataclass
class TestCategory:
    """单个测试类别。

    Attributes:
        id: 类别唯一 ID（用于命令行参数 / API path）
        name: 显示名称（中文）
        description: 详细描述
        files: 测试文件相对路径列表（相对于项目根）
        icon_color: 卡片左侧边条颜色（HEX）
        icon_letter: 卡片中心显示的字母
        priority: 显示优先级（小=先显示）
        requires_network: 是否需要网络（默认 False）
        requires_gui: 是否需要 GUI（默认 False）
        enabled: 是否启用（默认 True）
    """
    id: str
    name: str
    description: str
    files: List[str] = field(default_factory=list)
    icon_color: str = "#2196F3"
    icon_letter: str = "T"
    priority: int = 100
    requires_network: bool = False
    requires_gui: bool = False
    enabled: bool = True

    def file_count(self) -> int:
        """存在的测试文件数。"""
        return sum(1 for f in self.files if (PROJECT_ROOT / f).exists())

    def total_count(self) -> int:
        """存在的测试文件总数（用于显示）。"""
        return len(self.files)


# ========== 预置类别（按行业标准分类）==========

TEST_REGISTRY: dict[str, TestCategory] = {
    "all": TestCategory(
        id="all",
        name="全量测试",
        description="一次性运行所有测试类别（耗时最长）",
        files=[],  # 空表示"包含所有"
        icon_color="#9C27B0",
        icon_letter="ALL",
        priority=0,
    ),
    "unit": TestCategory(
        id="unit",
        name="单元测试",
        description="CLI/SDK/选择策略/配置/默认值的最小单元测试",
        files=[
            "tests/test_cli_entry.py",
            "tests/test_cli_main.py",
            "tests/test_cli_selection.py",
            "tests/test_cli_pipe.py",
            "tests/test_cli_defaults.py",
            "tests/test_cli_sdk.py",
            "tests/test_cli_runner.py",
        ],
        icon_color="#2196F3",
        icon_letter="U",
        priority=10,
    ),
    "integration": TestCategory(
        id="integration",
        name="集成测试",
        description="FastAPI 端点、Web 入口、CLI/SDK/API 三层契约",
        files=[
            "tests/test_fastapi_endpoints.py",
            "tests/test_web_entry.py",
            "tests/test_contract.py",
        ],
        icon_color="#4CAF50",
        icon_letter="I",
        priority=20,
    ),
    "e2e": TestCategory(
        id="e2e",
        name="端到端测试",
        description="完整流程：scan → dir/change → search → state（mock spider）",
        files=[
            "tests/test_e2e.py",
        ],
        icon_color="#FF9800",
        icon_letter="E",
        priority=30,
    ),
    "ui": TestCategory(
        id="ui",
        name="UI 弹窗测试",
        description="dispatcher 模式选择弹窗、端口冲突弹窗、TUI 菜单、托盘图标",
        files=[
            "tests/test_ui_dialogs.py",
        ],
        icon_color="#E91E63",
        icon_letter="UI",
        priority=40,
        requires_gui=True,
    ),
    "pipeline": TestCategory(
        id="pipeline",
        name="管道测试",
        description="stdin/stdout JSON 管道选择、合集场景多轮预加载",
        files=[
            "tests/test_pipeline.py",
        ],
        icon_color="#00BCD4",
        icon_letter="P",
        priority=50,
    ),
    "packaging": TestCategory(
        id="packaging",
        name="打包验证",
        description="PyInstaller spec / runtime hook / 图标 / 资源完整性",
        files=[
            "tests/test_packaging.py",
        ],
        icon_color="#795548",
        icon_letter="PK",
        priority=60,
    ),
    "web_browser": TestCategory(
        id="web_browser",
        name="Web 浏览器测试",
        description="用 Playwright 真实浏览器测试 web UI（前端交互）",
        files=[
            "tests/test_web_browser.py",
        ],
        icon_color="#673AB7",
        icon_letter="WB",
        priority=70,
        requires_gui=True,
    ),
    "core": TestCategory(
        id="core",
        name="核心组件测试",
        description="项目原有的核心组件测试（控制器、下载器、爬虫、文件服务）",
        files=[
            "tests/test_application_controller.py",
            "tests/test_downloaders.py",
            "tests/test_spider_helpers.py",
            "tests/test_file_service.py",
            "tests/test_main_window.py",
            "tests/test_main_entry.py",
            "tests/test_auth_service.py",
            "tests/test_config_settings.py",
            "tests/test_debug_logger.py",
            "tests/test_debug_service.py",
            "tests/test_download_manager_dispatch.py",
            "tests/test_download_queue_panel.py",
            "tests/test_integration_flows.py",
            "tests/test_plugin_registry.py",
            "tests/test_runtime_paths.py",
            "tests/test_settings_builders.py",
            "tests/test_utils_filenames.py",
            "tests/test_video_item.py",
        ],
        icon_color="#607D8B",
        icon_letter="C",
        priority=80,
    ),
    "test_entry": TestCategory(
        id="test_entry",
        name="测试入口",
        description="entry/test_entry.py + dispatcher 路由 + 插件 API + 测试启动器自身",
        files=[
            "tests/test_test_entry.py",
            "tests/test_launcher.py",
            "tests/test_registry.py",
            "tests/test_runner.py",
        ],
        icon_color="#E91E63",
        icon_letter="E",
        priority=75,
    ),
}


def register_category(
    id: str,
    name: str,
    description: str,
    files: list[str] | None = None,
    icon_color: str = "#2196F3",
    icon_letter: str = "T",
    priority: int = 100,
    requires_network: bool = False,
    requires_gui: bool = False,
    enabled: bool = True,
) -> TestCategory:
    """注册一个新的测试类别（运行时扩展 API）。

    Args:
        id: 类别 ID
        name: 显示名
        description: 描述
        files: 测试文件列表
        icon_color: 卡片边条颜色
        icon_letter: 卡片中心字母
        priority: 显示优先级
        requires_network: 是否需要网络
        requires_gui: 是否需要 GUI
        enabled: 是否启用

    Returns:
        创建的 TestCategory 实例
    """
    if id in TEST_REGISTRY:
        raise ValueError(f"Test category '{id}' already registered")
    cat = TestCategory(
        id=id,
        name=name,
        description=description,
        files=files or [],
        icon_color=icon_color,
        icon_letter=icon_letter,
        priority=priority,
        requires_network=requires_network,
        requires_gui=requires_gui,
        enabled=enabled,
    )
    TEST_REGISTRY[id] = cat
    return cat


def get_category(cat_id: str) -> TestCategory:
    """按 ID 获取测试类别，未找到抛 KeyError。"""
    if cat_id not in TEST_REGISTRY:
        raise KeyError(f"Unknown test category: {cat_id}. "
                       f"Available: {list(TEST_REGISTRY.keys())}")
    return TEST_REGISTRY[cat_id]


def get_enabled_categories() -> list[TestCategory]:
    """获取所有启用的类别，按 priority 排序。"""
    cats = [c for c in TEST_REGISTRY.values() if c.enabled]
    return sorted(cats, key=lambda c: (c.priority, c.id))


def get_resolved_files(cat_id: str) -> list[str]:
    """解析类别的测试文件列表。

    "all" 返回所有 enabled 类别（除自身）的文件去重。
    """
    if cat_id == "all":
        all_files: list[str] = []
        for c in get_enabled_categories():
            if c.id == "all":
                continue
            for f in c.files:
                if f not in all_files:
                    all_files.append(f)
        return all_files
    cat = get_category(cat_id)
    return list(cat.files)


def auto_discover_tests(tests_dir: Path | None = None) -> list[str]:
    """自动发现 tests/ 目录下所有 test_*.py 文件（未被注册表收录的）。"""
    tests_dir = tests_dir or TESTS_DIR
    known_files: set[str] = set()
    for c in TEST_REGISTRY.values():
        for f in c.files:
            known_files.add(f)
    discovered: list[str] = []
    for p in sorted(tests_dir.glob("test_*.py")):
        rel = f"tests/{p.name}"
        if rel not in known_files:
            discovered.append(rel)
    return discovered


def summary() -> dict:
    """返回注册表汇总信息。"""
    return {
        "total_categories": len(TEST_REGISTRY),
        "enabled_categories": sum(1 for c in TEST_REGISTRY.values() if c.enabled),
        "total_files": sum(len(c.files) for c in TEST_REGISTRY.values()),
        "plugin_directories": list(_PLUGIN_DIRS.keys()),
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "files": c.file_count(),
                "requires_gui": c.requires_gui,
                "requires_network": c.requires_network,
            }
            for c in get_enabled_categories()
        ],
    }


# ============== 插件目录扩展接口 ==============
# 设计要点（行业最佳实践 + 用户需求）：
# 1. **统一协议** TestPlugin：第三方可以继承实现自己的测试集
# 2. **目录即插件** register_plugin_directory：自动扫描 + 自动建类
# 3. **可发现** list_plugin_directories() 让 GUI 列出所有外挂测试
# 4. **可移除** unregister_plugin_directory() 运行时取消

@runtime_checkable
class TestPlugin(Protocol):
    """测试插件协议（用于高级扩展）。

    实现这个协议的类可以注册为插件，被测试启动器识别：

    .. code-block:: python

        class MyPlugin:
            id = "my_plugin"
            name = "我的插件"
            description = "..."
            icon_color = "#9C27B0"
            icon_letter = "M"
            priority = 50

            def get_files(self) -> list[str]:
                return ["myapp/tests/test_a.py", "myapp/tests/test_b.py"]

        from tests.test_registry import register_plugin
        register_plugin(MyPlugin())
    """
    id: str
    name: str
    description: str
    icon_color: str
    icon_letter: str
    priority: int

    def get_files(self) -> list[str]: ...


# 插件目录注册表（id -> 路径）
_PLUGIN_DIRS: dict[str, Path] = {}


def register_plugin_directory(
    category_id: str,
    name: str,
    directory: str | Path,
    description: str = "",
    icon_color: str = "#9C27B0",
    icon_letter: str = "P",
    priority: int = 100,
    pattern: str = "test_*.py",
    requires_gui: bool = False,
    requires_network: bool = False,
) -> TestCategory:
    """把某个目录下的所有 ``test_*.py`` 注册成一个测试类别。

    这是给**二次开发者**的扩展入口：你可以把外部模块的测试集成进来，
    不用改任何核心代码。

    Args:
        category_id: 类别唯一 ID（如 "myapp_plugin"）
        name: 显示名
        directory: 目录路径（绝对或相对项目根）
        description: 详细描述
        icon_color: 卡片边条颜色
        icon_letter: 卡片中心字母
        priority: 显示优先级（小=先）
        pattern: 文件匹配 glob（默认 "test_*.py"）
        requires_gui: 是否需要 GUI
        requires_network: 是否需要网络

    Returns:
        创建的 TestCategory 实例

    Examples:
        >>> register_plugin_directory(
        ...     "myapp_plugin",
        ...     "我的插件测试",
        ...     "myapp/tests",
        ...     description="自动扫描 myapp/tests/ 下所有 test_*.py",
        ... )
    """
    if category_id in TEST_REGISTRY:
        raise ValueError(
            f"Test category '{category_id}' already registered. "
            f"Use unregister_plugin_directory() first to override."
        )

    dir_path = Path(directory)
    if not dir_path.is_absolute():
        dir_path = PROJECT_ROOT / dir_path

    if not dir_path.exists():
        # 不抛错，避免外部模块未安装时把启动器搞挂
        # 但在启动器里会被提示 "未找到目录"
        pass

    # 扫描文件
    files: list[str] = []
    if dir_path.exists() and dir_path.is_dir():
        # 路径以 相对项目根 的形式存储，便于跨平台
        try:
            rel_root = dir_path.relative_to(PROJECT_ROOT)
        except ValueError:
            rel_root = dir_path  # 外部目录，原样存
        for p in sorted(dir_path.glob(pattern)):
            if p.is_file():
                try:
                    rel = p.relative_to(PROJECT_ROOT)
                    files.append(str(rel).replace("\\", "/"))
                except ValueError:
                    files.append(str(p))

    if not description:
        description = f"自动发现: {dir_path}（{pattern}）"

    cat = TestCategory(
        id=category_id,
        name=name,
        description=description,
        files=files,
        icon_color=icon_color,
        icon_letter=icon_letter,
        priority=priority,
        requires_gui=requires_gui,
        requires_network=requires_network,
    )
    TEST_REGISTRY[category_id] = cat
    _PLUGIN_DIRS[category_id] = dir_path
    return cat


def register_plugin(plugin: TestPlugin) -> TestCategory:
    """注册一个实现 TestPlugin 协议的对象。

    Examples:
        >>> class MyPlugin:
        ...     id = "my_plugin"
        ...     name = "我的插件"
        ...     description = "..."
        ...     icon_color = "#9C27B0"
        ...     icon_letter = "M"
        ...     priority = 50
        ...     def get_files(self):
        ...         return ["myapp/tests/test_a.py"]
        >>> register_plugin(MyPlugin())
    """
    if plugin.id in TEST_REGISTRY:
        raise ValueError(f"Test category '{plugin.id}' already registered")
    cat = TestCategory(
        id=plugin.id,
        name=plugin.name,
        description=plugin.description,
        files=plugin.get_files(),
        icon_color=getattr(plugin, "icon_color", "#9C27B0"),
        icon_letter=getattr(plugin, "icon_letter", "P"),
        priority=getattr(plugin, "priority", 100),
    )
    TEST_REGISTRY[plugin.id] = cat
    return cat


def unregister_plugin_directory(category_id: str) -> bool:
    """反注册一个插件目录（如果该类别是插件目录注册的）。

    Returns:
        True = 成功移除，False = 不是插件或不存在
    """
    if category_id not in _PLUGIN_DIRS:
        return False
    if category_id in TEST_REGISTRY:
        # 注意：如果是"all"等核心类别，refuse 移除
        if category_id in _CORE_CATEGORIES:
            return False
        del TEST_REGISTRY[category_id]
    del _PLUGIN_DIRS[category_id]
    return True


def list_plugin_directories() -> dict[str, str]:
    """列出所有插件目录（id -> 绝对路径）。"""
    return {k: str(v) for k, v in _PLUGIN_DIRS.items()}


# 核心类别（不能 unregister）
_CORE_CATEGORIES = frozenset({"all", "unit", "integration", "e2e", "ui", "pipeline", "packaging", "web_browser", "core"})


def _rescan_plugin(category_id: str) -> TestCategory | None:
    """重新扫描某个插件目录（用于插件增删文件后刷新）。"""
    if category_id not in _PLUGIN_DIRS:
        return None
    dir_path = _PLUGIN_DIRS[category_id]
    if category_id not in TEST_REGISTRY:
        return None
    cat = TEST_REGISTRY[category_id]
    files: list[str] = []
    if dir_path.exists() and dir_path.is_dir():
        for p in sorted(dir_path.glob("test_*.py")):
            if p.is_file():
                try:
                    rel = p.relative_to(PROJECT_ROOT)
                    files.append(str(rel).replace("\\", "/"))
                except ValueError:
                    files.append(str(p))
    cat.files = files
    return cat


if __name__ == "__main__":
    """直接运行：打印注册表汇总。"""
    import json
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    print()
    print("Discovered (unregistered) test files:")
    for f in auto_discover_tests():
        print(f"  - {f}")
    if _PLUGIN_DIRS:
        print()
        print("Plugin directories:")
        for cid, path in _PLUGIN_DIRS.items():
            print(f"  - {cid}: {path}")
