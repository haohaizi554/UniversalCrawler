"""Directory-driven catalog for the repository test suites.

Built-in suites are defined exclusively by their canonical directory roots.
Filename patterns and explicit file lists remain available only for runtime
plugins and third-party extensions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import ClassVar, Iterable, Protocol, runtime_checkable


TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
TEST_ICON_PATH = PROJECT_ROOT / "test.ico" if (PROJECT_ROOT / "test.ico").exists() else TESTS_DIR / "test.ico"
PLUGIN_ROOT = TESTS_DIR / "plugins"

BUILTIN_SUITE_ROOTS = {
    "unit": "tests/unit",
    "integration": "tests/integration",
    "contract": "tests/contract",
    "e2e": "tests/e2e",
    "architecture": "tests/architecture",
    "performance": "tests/performance",
    "release": "tests/release",
    "testkit": "tests/testkit",
}

SUITE_SUPPORT_FILES = frozenset(
    {
        "tests/launcher.py",
        "tests/support/catalog.py",
        "tests/support/runner.py",
    }
)

RECOMMENDED_CATEGORY_IDS = (
    "unit",
    "integration",
    "contract",
    "architecture",
    "release",
    "testkit",
)


@dataclass
class TestCategory:
    """A runnable test category shown by the CLI, TUI, and GUI launchers."""

    __test__: ClassVar[bool] = False

    id: str
    name: str
    description: str
    roots: list[str] = field(default_factory=list)
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
    source: str = "extension"

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
    return any(fnmatch(path_str, pattern) or posix_path.match(pattern) for pattern in patterns)


def _is_below(path_str: str, root_str: str) -> bool:
    path = PurePosixPath(path_str)
    root = PurePosixPath(root_str)
    return path == root or root in path.parents


def discover_test_files(
    tests_dir: Path | None = None,
    *,
    include_support_files: bool = False,
) -> list[str]:
    """Discover every pytest module below ``tests_dir`` exactly once."""

    scan_root = Path(tests_dir or TESTS_DIR)
    discovered: list[str] = []
    for path in sorted(scan_root.rglob("test_*.py")):
        if not path.is_file():
            continue
        normalized = _normalize_path(path)
        if not include_support_files and _is_below(normalized, "tests/support"):
            continue
        discovered.append(normalized)
    return _dedupe(discovered)


def _resolve_direct_category_files(category: TestCategory) -> list[str]:
    discovered_local = discover_test_files()
    files = list(category.files)

    for root in category.roots:
        normalized_root = _normalize_path(root).rstrip("/")
        files.extend(path for path in discovered_local if _is_below(path, normalized_root))

    if category.include:
        files.extend(path for path in discovered_local if _matches(path, category.include))

    if category.exclude:
        files = [path for path in files if not _matches(_normalize_path(path), category.exclude)]

    return _dedupe(files)


def _assigned_local_test_files() -> set[str]:
    assigned: set[str] = set()
    for category in TEST_REGISTRY.values():
        if category.id in {"all", "misc"} or category.source == "plugin":
            continue
        assigned.update(
            path
            for path in _resolve_direct_category_files(category)
            if path.startswith("tests/")
        )
    return assigned


def get_category(cat_id: str) -> TestCategory:
    if cat_id not in TEST_REGISTRY:
        raise KeyError(f"Unknown test category: {cat_id}. Available: {list(TEST_REGISTRY)}")
    return TEST_REGISTRY[cat_id]


def get_enabled_categories() -> list[TestCategory]:
    categories = [category for category in TEST_REGISTRY.values() if category.enabled]
    return sorted(categories, key=lambda item: (item.priority, item.id))


def get_resolved_files(cat_id: str) -> list[str]:
    """Return the test modules selected by one suite or extension category."""

    if cat_id == "all":
        local_files = discover_test_files()
        plugin_files: list[str] = []
        for category_id in _PLUGIN_DIRS:
            category = TEST_REGISTRY.get(category_id)
            if category is not None:
                plugin_files.extend(_resolve_direct_category_files(category))
        return _dedupe([*local_files, *plugin_files])

    if cat_id == "misc":
        assigned = _assigned_local_test_files()
        return [path for path in discover_test_files() if path not in assigned]

    return _resolve_direct_category_files(get_category(cat_id))


def auto_discover_tests(tests_dir: Path | None = None) -> list[str]:
    """Return test modules that violate the canonical suite-root contract."""

    scan_root = Path(tests_dir or TESTS_DIR).resolve()
    if scan_root == TESTS_DIR.resolve():
        assigned = _assigned_local_test_files()
        return [path for path in discover_test_files() if path not in assigned]

    invalid: list[str] = []
    for path in sorted(scan_root.rglob("test_*.py")):
        relative = path.relative_to(scan_root)
        if len(relative.parts) < 2 or relative.parts[0] not in BUILTIN_SUITE_ROOTS:
            invalid.append(_normalize_path(path))
    return invalid


def register_category(
    id: str,
    name: str,
    description: str,
    files: list[str] | None = None,
    *,
    roots: list[str] | None = None,
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
    """Register a suite or extension category."""

    if id in TEST_REGISTRY:
        raise ValueError(f"Test category '{id}' already registered")

    category = TestCategory(
        id=id,
        name=name,
        description=description,
        roots=_dedupe(roots or []),
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
    """Register a glob-selected extension category.

    Built-in suites never call this API; it is retained for runtime plugins.
    """

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
        source="extension",
    )


def register_test_files(category_id: str, files: list[str], *, append: bool = True) -> TestCategory:
    """Attach explicit files to an extension category."""

    category = get_category(category_id)
    if category.source in {"builtin", "suite"}:
        raise ValueError("Built-in suites are directory-driven and cannot accept explicit files")
    normalized = _dedupe(files)
    category.files = _dedupe([*(category.files if append else []), *normalized])
    return category


@runtime_checkable
class TestPlugin(Protocol):
    __test__: ClassVar[bool] = False

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
            if path.is_file():
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
    """Register a dynamically scanned plugin directory."""

    if category_id in TEST_REGISTRY:
        raise ValueError(
            f"Test category '{category_id}' already registered. "
            "Use unregister_plugin_directory() first to override."
        )

    directory_path = Path(directory)
    if not directory_path.is_absolute():
        directory_path = PROJECT_ROOT / directory_path

    files = _scan_plugin_files(directory_path, pattern)
    category = register_category(
        id=category_id,
        name=name,
        description=description or f"自动扫描目录: {directory_path} ({pattern})",
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
    """Register an object implementing the ``TestPlugin`` protocol."""

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
    if category_id not in _PLUGIN_DIRS or category_id in _CORE_CATEGORIES:
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
    """Refresh dynamic plugin sources and return catalog counters."""

    for category_id in list(_PLUGIN_DIRS):
        _rescan_plugin(category_id)
    return {
        "categories": len(TEST_REGISTRY),
        "runnable_files": len(get_resolved_files("all")),
        "unassigned_files": len(get_resolved_files("misc")),
    }


def summary() -> dict:
    return {
        "builtin_suites": len(BUILTIN_SUITE_ROOTS),
        "total_categories": len(TEST_REGISTRY),
        "enabled_categories": sum(1 for category in TEST_REGISTRY.values() if category.enabled),
        "total_files": len(get_resolved_files("all")),
        "plugin_directories": list(_PLUGIN_DIRS),
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


def _register_suite(
    suite_id: str,
    name: str,
    description: str,
    *,
    icon_color: str,
    icon_letter: str,
    priority: int,
    section: str,
    badges: list[str],
    requires_network: bool = False,
    requires_gui: bool = False,
) -> None:
    register_category(
        id=suite_id,
        name=name,
        description=description,
        roots=[BUILTIN_SUITE_ROOTS[suite_id]],
        icon_color=icon_color,
        icon_letter=icon_letter,
        priority=priority,
        section=section,
        badges=badges,
        requires_network=requires_network,
        requires_gui=requires_gui,
        source="suite",
    )


def _bootstrap_registry() -> None:
    TEST_REGISTRY.clear()
    register_category(
        id="all",
        name="全部测试",
        description="运行所有内置套件与已注册插件测试。",
        icon_color="#7C3AED",
        icon_letter="ALL",
        priority=0,
        section="开始使用",
        badges=["全集"],
        source="builtin",
    )
    _register_suite(
        "unit",
        "单元测试",
        "隔离、确定且默认不访问真实外部资源的行为测试。",
        icon_color="#2563EB",
        icon_letter="UNIT",
        priority=10,
        section="快速反馈",
        badges=["推荐", "快速"],
    )
    _register_suite(
        "integration",
        "集成测试",
        "多个真实项目组件或本地边界协同工作的验证。",
        icon_color="#F97316",
        icon_letter="INT",
        priority=20,
        section="系统协作",
        badges=["组合"],
    )
    _register_suite(
        "contract",
        "契约测试",
        "公共 API、CLI、配置、前后端协议和兼容性契约。",
        icon_color="#14B8A6",
        icon_letter="API",
        priority=30,
        section="系统协作",
        badges=["契约"],
    )
    _register_suite(
        "e2e",
        "端到端测试",
        "完整入口与真实浏览器用户旅程。",
        icon_color="#6366F1",
        icon_letter="E2E",
        priority=40,
        section="用户旅程",
        badges=["端到端"],
        requires_network=True,
        requires_gui=True,
    )
    _register_suite(
        "architecture",
        "架构适应度",
        "依赖方向、目录、规模与仓库结构契约。",
        icon_color="#0F766E",
        icon_letter="ARCH",
        priority=50,
        section="质量保障",
        badges=["架构"],
    )
    _register_suite(
        "performance",
        "性能预算",
        "显式运行且不使用覆盖率插桩的性能基准。",
        icon_color="#B45309",
        icon_letter="PERF",
        priority=60,
        section="质量保障",
        badges=["显式运行"],
    )
    _register_suite(
        "release",
        "发布验证",
        "CI、打包、安装、升级和发布资产完整性检查。",
        icon_color="#A16207",
        icon_letter="REL",
        priority=70,
        section="质量保障",
        badges=["发布"],
    )
    _register_suite(
        "testkit",
        "测试基础设施",
        "目录、启动器、runner 与插件扩展接口自身的测试。",
        icon_color="#8B5CF6",
        icon_letter="KIT",
        priority=80,
        section="测试体系",
        badges=["基础设施"],
    )
    register_category(
        id="misc",
        name="布局违规",
        description="兼容视图：列出不在规范套件根目录下的测试。",
        priority=999,
        enabled=False,
        source="builtin",
    )


_bootstrap_registry()
_CORE_CATEGORIES = frozenset(TEST_REGISTRY)


if __name__ == "__main__":
    import json

    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    invalid = auto_discover_tests()
    if invalid:
        print("\nLayout violations:")
        for file_path in invalid:
            print(f"  - {file_path}")
        raise SystemExit(1)
