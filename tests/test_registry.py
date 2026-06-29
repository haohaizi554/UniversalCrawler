"""测试注册表。

这一版把原先“手填文件列表”的方式改成了“目录自动发现 + 分类规则 + 可注册扩展”：

- UI、CLI、TUI 统一从这一份注册表拿分类
- 基于 ``tests/`` 目录自动扫描 ``test_*.py``
- 用规则把测试脚本分到更贴近实际职责的套件
- 为后续新增测试脚本提供更稳定的注册接口
- 默认排除测试套件自身的实现文件，避免把启动器源码误当成测试运行
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol, runtime_checkable

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
TEST_ICON_PATH = PROJECT_ROOT / "test.ico" if (PROJECT_ROOT / "test.ico").exists() else TESTS_DIR / "test.ico"
PLUGIN_ROOT = PROJECT_ROOT / "tests" / "plugins"

# 这些文件位于 tests/ 目录，但本质上是测试套件实现，不应该作为 pytest 测试脚本运行。
SUITE_SUPPORT_FILES = frozenset(
    {
        "tests/test_launcher.py",
        "tests/test_registry.py",
        "tests/test_runner.py",
    }
)

RECOMMENDED_CATEGORY_IDS = (
    "cli_sdk",
    "web_api",
    "app_flows",
    "pipeline",
    "core_services",
)

@dataclass
class TestCategory:
    """测试类别定义。"""

    id: str
    name: str
    description: str
    files: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    icon_color: str = "#3B82F6"
    icon_letter: str = "T"
    priority: int = 100
    section: str = "其他"
    badges: list[str] = field(default_factory=list)
    requires_network: bool = False
    requires_gui: bool = False
    enabled: bool = True
    source: str = "rule"

    def file_count(self) -> int:
        return len(get_resolved_files(self.id))

    def total_count(self) -> int:
        return self.file_count()

TEST_REGISTRY: dict[str, TestCategory] = {}
_PLUGIN_DIRS: dict[str, Path] = {}
_PLUGIN_PATTERNS: dict[str, str] = {}

def _normalize_path(path_like: str | Path) -> str:
    path = Path(path_like)
    if path.is_absolute():
        try:
            path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            return str(path).replace("\\", "/")
    return str(path).replace("\\", "/")

def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = _normalize_path(item)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result

def _matches(path_str: str, patterns: Iterable[str]) -> bool:
    posix_path = PurePosixPath(path_str)
    return any(fnmatch(path_str, pat) or posix_path.match(pat) for pat in patterns)

def discover_test_files(
    tests_dir: Path | None = None,
    *,
    include_support_files: bool = False,
) -> list[str]:
    """扫描 tests 目录下所有可运行测试脚本。"""

    tests_dir = tests_dir or TESTS_DIR
    discovered: list[str] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        if not path.is_file():
            continue
        rel = _normalize_path(path)
        if not include_support_files and rel in SUITE_SUPPORT_FILES:
            continue
        discovered.append(rel)
    return discovered

def _resolve_direct_category_files(category: TestCategory) -> list[str]:
    discovered_local = discover_test_files()
    files: list[str] = []

    for file_path in category.files:
        normalized = _normalize_path(file_path)
        if normalized in SUITE_SUPPORT_FILES:
            continue
        files.append(normalized)

    if category.include:
        files.extend(
            rel
            for rel in discovered_local
            if _matches(rel, category.include)
        )

    if category.exclude:
        files = [rel for rel in files if not _matches(rel, category.exclude)]

    return _dedupe(files)

def _assigned_local_test_files() -> set[str]:
    assigned: set[str] = set()
    for category in TEST_REGISTRY.values():
        if category.id in {"all", "misc"}:
            continue
        for rel in _resolve_direct_category_files(category):
            if rel.startswith("tests/"):
                assigned.add(rel)
    return assigned

def get_category(cat_id: str) -> TestCategory:
    if cat_id not in TEST_REGISTRY:
        raise KeyError(f"Unknown test category: {cat_id}. Available: {list(TEST_REGISTRY.keys())}")
    return TEST_REGISTRY[cat_id]

def get_enabled_categories() -> list[TestCategory]:
    categories = [category for category in TEST_REGISTRY.values() if category.enabled]
    return sorted(categories, key=lambda item: (item.priority, item.id))

def get_resolved_files(cat_id: str) -> list[str]:
    """返回某个类别最终会运行的测试脚本列表。"""

    if cat_id == "all":
        local_files = discover_test_files()
        plugin_files: list[str] = []
        for category_id in list(_PLUGIN_DIRS):
            if category_id in TEST_REGISTRY:
                plugin_files.extend(_resolve_direct_category_files(TEST_REGISTRY[category_id]))
        return _dedupe(local_files + plugin_files)

    if cat_id == "misc":
        assigned = _assigned_local_test_files()
        return [rel for rel in discover_test_files() if rel not in assigned]

    return _resolve_direct_category_files(get_category(cat_id))

def auto_discover_tests(tests_dir: Path | None = None) -> list[str]:
    """返回尚未被任何内置分类规则收录的测试脚本。"""

    tests_dir = tests_dir or TESTS_DIR
    discovered = discover_test_files(tests_dir)
    assigned = _assigned_local_test_files()
    return [rel for rel in discovered if rel not in assigned]

def register_category(
    id: str,
    name: str,
    description: str,
    files: list[str] | None = None,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    icon_color: str = "#3B82F6",
    icon_letter: str = "T",
    priority: int = 100,
    section: str = "扩展",
    badges: list[str] | None = None,
    requires_network: bool = False,
    requires_gui: bool = False,
    enabled: bool = True,
    source: str = "manual",
) -> TestCategory:
    """注册一个测试类别。"""

    if id in TEST_REGISTRY:
        raise ValueError(f"Test category '{id}' already registered")

    category = TestCategory(
        id=id,
        name=name,
        description=description,
        files=_dedupe(files or []),
        include=list(include or []),
        exclude=list(exclude or []),
        icon_color=icon_color,
        icon_letter=icon_letter,
        priority=priority,
        section=section,
        badges=list(badges or []),
        requires_network=requires_network,
        requires_gui=requires_gui,
        enabled=enabled,
        source=source,
    )
    TEST_REGISTRY[id] = category
    return category

def register_category_rule(
    id: str,
    name: str,
    description: str,
    *,
    include: list[str],
    exclude: list[str] | None = None,
    icon_color: str = "#3B82F6",
    icon_letter: str = "T",
    priority: int = 100,
    section: str = "扩展",
    badges: list[str] | None = None,
    requires_network: bool = False,
    requires_gui: bool = False,
    enabled: bool = True,
) -> TestCategory:
    """按文件规则注册类别，适合后续新增测试脚本自动入组。"""

    return register_category(
        id=id,
        name=name,
        description=description,
        include=include,
        exclude=exclude,
        icon_color=icon_color,
        icon_letter=icon_letter,
        priority=priority,
        section=section,
        badges=badges,
        requires_network=requires_network,
        requires_gui=requires_gui,
        enabled=enabled,
        source="rule",
    )

def register_test_files(category_id: str, files: list[str], *, append: bool = True) -> TestCategory:
    """向现有类别追加或覆盖测试脚本，便于后续脚本接入测试套件。"""

    category = get_category(category_id)
    normalized = _dedupe(files)
    category.files = _dedupe((category.files if append else []) + normalized)
    return category

@runtime_checkable
class TestPlugin(Protocol):
    id: str
    name: str
    description: str
    icon_color: str
    icon_letter: str
    priority: int

    def get_files(self) -> list[str]: ...

def _scan_plugin_files(directory: Path, pattern: str) -> list[str]:
    files: list[str] = []
    if directory.exists() and directory.is_dir():
        for path in sorted(directory.rglob(pattern)):
            if not path.is_file():
                continue
            files.append(_normalize_path(path))
    return _dedupe(files)

def register_plugin_directory(
    category_id: str,
    name: str,
    directory: str | Path,
    description: str = "",
    icon_color: str = "#8B5CF6",
    icon_letter: str = "P",
    priority: int = 100,
    pattern: str = "test_*.py",
    requires_gui: bool = False,
    requires_network: bool = False,
) -> TestCategory:
    """把一个目录扫描成可运行测试类别。"""

    if category_id in TEST_REGISTRY:
        raise ValueError(
            f"Test category '{category_id}' already registered. "
            f"Use unregister_plugin_directory() first to override."
        )

    directory_path = Path(directory)
    if not directory_path.is_absolute():
        directory_path = PROJECT_ROOT / directory_path

    files = _scan_plugin_files(directory_path, pattern)
    if not description:
        description = f"自动扫描目录: {directory_path} ({pattern})"

    category = register_category(
        id=category_id,
        name=name,
        description=description,
        files=files,
        icon_color=icon_color,
        icon_letter=icon_letter,
        priority=priority,
        section="扩展测试",
        badges=["插件目录"],
        requires_gui=requires_gui,
        requires_network=requires_network,
        source="plugin",
    )
    _PLUGIN_DIRS[category_id] = directory_path
    _PLUGIN_PATTERNS[category_id] = pattern
    return category

def register_plugin(plugin: TestPlugin) -> TestCategory:
    """注册一个实现 TestPlugin 协议的对象。"""

    return register_category(
        id=plugin.id,
        name=plugin.name,
        description=plugin.description,
        files=plugin.get_files(),
        icon_color=getattr(plugin, "icon_color", "#8B5CF6"),
        icon_letter=getattr(plugin, "icon_letter", "P"),
        priority=getattr(plugin, "priority", 100),
        section="扩展测试",
        badges=["插件对象"],
        source="plugin",
    )

def unregister_plugin_directory(category_id: str) -> bool:
    if category_id not in _PLUGIN_DIRS:
        return False
    if category_id in _CORE_CATEGORIES:
        return False
    TEST_REGISTRY.pop(category_id, None)
    _PLUGIN_DIRS.pop(category_id, None)
    _PLUGIN_PATTERNS.pop(category_id, None)
    return True

def list_plugin_directories() -> dict[str, str]:
    return {category_id: str(path) for category_id, path in _PLUGIN_DIRS.items()}

def _rescan_plugin(category_id: str) -> TestCategory | None:
    if category_id not in _PLUGIN_DIRS or category_id not in TEST_REGISTRY:
        return None
    category = TEST_REGISTRY[category_id]
    category.files = _scan_plugin_files(
        _PLUGIN_DIRS[category_id],
        _PLUGIN_PATTERNS.get(category_id, "test_*.py"),
    )
    return category

def refresh_registry() -> dict[str, int]:
    """刷新动态来源的类别。"""

    for category_id in list(_PLUGIN_DIRS):
        _rescan_plugin(category_id)
    return {
        "categories": len(TEST_REGISTRY),
        "runnable_files": len(get_resolved_files("all")),
        "unassigned_files": len(get_resolved_files("misc")),
    }

def summary() -> dict:
    return {
        "total_categories": len(TEST_REGISTRY),
        "enabled_categories": sum(1 for category in TEST_REGISTRY.values() if category.enabled),
        "total_files": len(get_resolved_files("all")),
        "plugin_directories": list(_PLUGIN_DIRS.keys()),
        "support_files": sorted(SUITE_SUPPORT_FILES),
        "categories": [
            {
                "id": category.id,
                "name": category.name,
                "section": category.section,
                "files": category.file_count(),
                "requires_gui": category.requires_gui,
                "requires_network": category.requires_network,
            }
            for category in get_enabled_categories()
        ],
    }

def _bootstrap_registry() -> None:
    TEST_REGISTRY.clear()

    register_category(
        id="all",
        name="全部测试",
        description="运行当前测试目录下所有可执行测试脚本。",
        icon_color="#7C3AED",
        icon_letter="ALL",
        priority=0,
        section="开始使用",
        badges=["全集"],
        source="builtin",
    )
    # ── 接口层 ──────────────────────────────────────────────
    register_category_rule(
        id="cli_sdk",
        name="CLI / SDK",
        description="命令行、SDK、选择策略、默认值和 Runner 的接口测试。",
        include=["tests/test_cli_*.py"],
        icon_color="#2563EB",
        icon_letter="CLI",
        priority=10,
        section="接口层",
        badges=["推荐", "快速"],
    )
    register_category_rule(
        id="web_api",
        name="Web / API",
        description="FastAPI 端点、Web 入口、Web 控制器桥接和多入口契约一致性。",
        include=[
            "tests/test_contract.py",
            "tests/test_fastapi_*.py",
            "tests/test_web_*.py",
            "tests/test_web_entry.py",
            "tests/test_web_controller_*.py",
            "tests/test_websocket_*.py",
        ],
        exclude=["tests/test_web_browser.py"],
        icon_color="#14B8A6",
        icon_letter="API",
        priority=20,
        section="接口层",
        badges=["推荐"],
    )
    # ── 流程层 ──────────────────────────────────────────────
    register_category_rule(
        id="app_flows",
        name="应用流程",
        description="端到端流程、入口调度与跨模块集成流。",
        include=[
            "tests/test_e2e.py",
            "tests/test_main_entry.py",
            "tests/test_*_entry.py",
            "tests/test_*_entry_*.py",
            "tests/test_entry_*.py",
            "tests/test_cross_entry_*.py",
            "tests/test_integration_*.py",
        ],
        icon_color="#F97316",
        icon_letter="FLOW",
        priority=30,
        section="流程层",
        badges=["推荐"],
    )
    # ── 体验层 ──────────────────────────────────────────────
    register_category_rule(
        id="desktop_ui",
        name="桌面界面",
        description="Qt 主窗口、控制器、队列面板、宿主适配层与对话框相关测试。",
        include=[
            "tests/test_application_controller.py",
            "tests/test_download_queue_panel.py",
            "tests/test_main_window.py",
            "tests/test_desktop_host.py",
            "tests/test_gui_*.py",
            "tests/test_media_preview_panel.py",
            "tests/test_log_panel.py",
            "tests/test_log_center_semantics.py",
            "tests/test_snapshot_*.py",
            "tests/test_ui_*.py",
            "tests/test_unified_frontend_contract.py",
        ],
        icon_color="#EC4899",
        icon_letter="UI",
        priority=40,
        section="体验层",
        badges=["桌面"],
        requires_gui=True,
    )
    register_category_rule(
        id="browser_e2e",
        name="浏览器 E2E",
        description="Playwright 驱动的真实浏览器测试与前端交互回归。",
        include=["tests/test_web_browser.py"],
        icon_color="#6366F1",
        icon_letter="WEB",
        priority=50,
        section="体验层",
        badges=["浏览器"],
        requires_network=True,
    )
    # ── 流程层（续） ───────────────────────────────────────
    register_category_rule(
        id="pipeline",
        name="数据管道",
        description="stdin/stdout JSON 管道、多轮选择与预加载链路。",
        include=["tests/test_pipeline.py"],
        icon_color="#06B6D4",
        icon_letter="PIPE",
        priority=60,
        section="流程层",
        badges=["推荐"],
    )
    # ── 保障层 ──────────────────────────────────────────────
    register_category_rule(
        id="packaging",
        name="打包发布",
        description="spec、runtime hook、资源文件和发布入口完整性检查。",
        include=["tests/test_packaging.py"],
        icon_color="#A16207",
        icon_letter="PKG",
        priority=70,
        section="保障层",
        badges=["发布"],
    )
    register_category_rule(
        id="core_services",
        name="核心服务",
        description="业务核心、下载器、文件服务、配置和基础设施测试。",
        include=[
            "tests/test_config_*.py",
            "tests/test_debug_logger.py",
            "tests/test_plugin_*.py",
            "tests/test_runtime_paths.py",
            "tests/test_settings_*.py",
            "tests/test_utils_*.py",
            "tests/test_video_item.py",
            "tests/test_xiaohongshu_integration.py",
            "tests/test_core_*.py",
            "tests/test_*_service.py",
            "tests/test_*_parameter.py",
            "tests/test_download*.py",
            "tests/test_download_*.py",
            "tests/test_*_mixin.py",
            "tests/test_spider_*.py",
            "tests/test_shared_*.py",
            "tests/test_anti_detection.py",
            "tests/test_media_release_*.py",
            "tests/test_media_library_*.py",
            "tests/test_controller_*_mixin.py",
            "tests/test_concurrency_*.py",
            "tests/test_event_*.py",
            "tests/test_frontend_event_*.py",
            "tests/test_m3u8_*.py",
            "tests/test_task_runtime_*.py",
            "tests/test_ws_transport_*.py",
        ],
        exclude=["tests/test_download_queue_panel.py"],
        icon_color="#22C55E",
        icon_letter="CORE",
        priority=80,
        section="保障层",
        badges=["推荐"],
    )
    # ── 套件自身 ────────────────────────────────────────────
    register_category_rule(
        id="suite_infra",
        name="测试套件",
        description="测试入口、分类注册、启动器 UI 与测试套件自身的行为验证。",
        include=["tests/test_test_*.py"],
        icon_color="#8B5CF6",
        icon_letter="KIT",
        priority=90,
        section="套件自身",
        badges=["扩展接口"],
    )
    # ── 兜底 ────────────────────────────────────────────────
    register_category(
        id="misc",
        name="未归类",
        description="自动收纳尚未命中任何规则的新测试脚本，方便后续补分类。",
        icon_color="#64748B",
        icon_letter="NEW",
        priority=999,
        section="扩展测试",
        badges=["自动发现"],
        source="builtin",
    )

_bootstrap_registry()

_CORE_CATEGORIES = frozenset(TEST_REGISTRY.keys())

if __name__ == "__main__":
    import json

    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    print()
    print("Unassigned tests:")
    for file_path in auto_discover_tests():
        print(f"  - {file_path}")
