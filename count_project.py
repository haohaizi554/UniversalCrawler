import argparse
import ast
import base64
import os
import site
import subprocess
import sys
import time
import webbrowser
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Sequence

REPORT_WIDTH = 140
REPORT_ICON_NAME = "analytics.ico"

EXCLUDE_DIRS = {
    ".git",
    ".worktrees",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    "out",
    "graphify-out",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    "coverage",
    "logs",
    "log",
    "Cache",
    ".cache",
}


# 锁文件和生成清单不代表项目维护的源码，不计入代码量。

EXCLUDE_FILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
}


def resolve_report_icon_path() -> Path | None:
    """查找源码与冻结环境中的报告图标。"""
    roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    module_root = Path(__file__).resolve().parent
    roots.extend(
        (
            module_root,
            module_root / "share" / "ucrawl",
            Path(sys.prefix) / "share" / "ucrawl",
            Path.cwd(),
        )
    )
    if site.USER_BASE:
        roots.insert(-1, Path(site.USER_BASE) / "share" / "ucrawl")

    visited: set[Path] = set()
    for root in roots:
        candidate = (root / REPORT_ICON_NAME).resolve()
        if candidate in visited:
            continue
        visited.add(candidate)
        if candidate.is_file():
            return candidate
    return None


def render_report_favicon() -> str:
    """将图标嵌入 HTML，避免报告移动后丢失浏览器标签页图标。"""
    icon_path = resolve_report_icon_path()
    if icon_path is None:
        return ""
    try:
        encoded = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return (
        '<link rel="icon" type="image/x-icon" '
        f'href="data:image/x-icon;base64,{encoded}">'
    )


def normalize_repository_url(remote_url: str) -> str:
    """将常见 Git 远程地址规范化为浏览器可访问的仓库 URL。"""
    normalized = str(remote_url or "").strip().rstrip("/")
    if not normalized:
        return ""

    if normalized.startswith("git@"):
        host_part, separator, repository_path = normalized.partition(":")
        if not separator or not repository_path:
            return ""
        host = host_part.split("@", 1)[-1]
        normalized = f"https://{host}/{repository_path}"
    elif normalized.startswith("ssh://git@"):
        ssh_target = normalized.removeprefix("ssh://git@")
        host, separator, repository_path = ssh_target.partition("/")
        if not separator or not repository_path:
            return ""
        normalized = f"https://{host}/{repository_path}"
    elif not normalized.startswith(("https://", "http://")):
        return ""

    return normalized.removesuffix(".git").rstrip("/")


def detect_repository_url(root: Path) -> str:
    """从本地 Git 配置读取 origin，不发起网络请求。"""
    try:
        completed = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    if completed.returncode != 0:
        return ""
    return normalize_repository_url(completed.stdout)


# 目录名匹配用于识别不同技术栈的测试代码。

TEST_DIR_NAMES = {
    "test",
    "tests",
    "__tests__",
    "spec",
    "specs",
}


# 只统计能够可靠归类的源码与工程配置文件。

CODE_EXTS = {
    ".py": "Python",
    ".java": "Java",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "React JSX",
    ".tsx": "React TSX",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".sql": "SQL",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".bat": "Batch",
    ".ps1": "PowerShell",
    ".sh": "Shell",
}


# 这些前缀仅用于粗略 LOC 统计，不承担完整语法解析。

COMMENT_PREFIXES = {
    ".py": ["#"],
    ".java": ["//"],
    ".js": ["//"],
    ".ts": ["//"],
    ".jsx": ["//"],
    ".tsx": ["//"],
    ".css": ["/*", "*"],
    ".scss": ["//", "/*", "*"],
    ".c": ["//", "/*", "*"],
    ".cpp": ["//", "/*", "*"],
    ".cc": ["//", "/*", "*"],
    ".h": ["//", "/*", "*"],
    ".hpp": ["//", "/*", "*"],
    ".cs": ["//", "/*", "*"],
    ".go": ["//", "/*", "*"],
    ".rs": ["//", "/*", "*"],
    ".php": ["//", "#", "/*", "*"],
    ".sql": ["--"],
    ".html": ["<!--"],
    ".yaml": ["#"],
    ".yml": ["#"],
    ".toml": ["#"],
    ".ini": [";", "#"],
    ".bat": ["rem", "::"],
    ".ps1": ["#"],
    ".sh": ["#"],
}


MODULE_BUCKETS = (
    "app/config",
    "app/controllers",
    "app/core",
    "app/services",
    "app/spiders",
    "app/ui",
    "app/web",
    "app/models",
    "app/utils",
    "app/other",
    "shared",
    "cli",
    "entry",
    "packaging",
    "scripts",
    "tests",
    "docs",
    "other",
)

TEST_SUITE_ROOTS = (
    "unit",
    "integration",
    "contract",
    "e2e",
    "architecture",
    "performance",
    "release",
    "testkit",
    "support",
    "other",
)

PROD_FILE_WATCH_LINES = 1500
PROD_FILE_RISK_LINES = 3000
TEST_FILE_WATCH_LINES = 2500
TEST_FILE_RISK_LINES = 4000
DEFAULT_GATE_PROD_MAX_LINES = 3000
DEFAULT_GATE_TEST_RATIO_MIN = 10.0
COMPLEXITY_HOTSPOT_LIMIT = 20
LARGEST_FILES_LIMIT = 5
HISTORY_DEFAULT_NAME = "code_report.json"


def empty_stat() -> dict:
    return {
        "files": 0,
        "total": 0,
        "blank": 0,
        "comment": 0,
        "code": 0,
    }


def empty_suite_stat() -> dict:
    return {
        "files": 0,
        "total": 0,
        "blank": 0,
        "comment": 0,
        "code": 0,
        "test_cases": 0,
    }


def add_stat(target: dict, stat: dict) -> None:
    target["files"] += 1
    target["total"] += stat["total"]
    target["blank"] += stat["blank"]
    target["comment"] += stat["comment"]
    target["code"] += stat["code"]


def _build_console():
    from rich.console import Console

    return Console(
        width=REPORT_WIDTH,
        highlight=False,
        color_system=None,
        force_terminal=True,
        soft_wrap=False,
        safe_box=True,
    )


def _build_table(title: str, columns: list[tuple[str, str]], rows: list[list[object]]):
    from rich import box
    from rich.table import Table

    table = Table(
        title=title,
        box=box.SIMPLE_HEAD,
        show_edge=False,
        show_lines=False,
        header_style="",
        title_style="",
        title_justify="center",
        pad_edge=False,
        expand=True,
        safe_box=True,
    )
    wrap_headers = {"文件", "位置", "路径", "项", "说明"}
    for header, _justify in columns:
        table.add_column(header, justify="center", no_wrap=header not in wrap_headers)
    for row in rows:
        table.add_row(*(str(value) for value in row))
    return table


def _print_table(title: str, columns: list[tuple[str, str]], rows: list[list[object]]) -> None:
    table = _build_table(title, columns, rows)
    console = _build_console()
    console.print(table)


def should_skip_dir(path: Path) -> bool:
    return path.name in EXCLUDE_DIRS


def should_skip_file(path: Path) -> bool:
    return path.name in EXCLUDE_FILE_NAMES


def is_code_file(path: Path) -> bool:
    return path.suffix.lower() in CODE_EXTS


def is_test_file(path: Path, root: Path) -> bool:
    """
    判断是否为测试文件。

    支持识别：
    1. tests/xxx.py
    2. test/xxx.py
    3. __tests__/xxx.js
    4. test_xxx.py
    5. xxx_test.py
    6. xxx.test.js
    7. xxx.spec.ts
    8. UserServiceTest.java
    9. conftest.py
    """
    try:
        relative_path = path.relative_to(root)
    except ValueError:
        relative_path = path

    parts = [p.lower() for p in relative_path.parts]
    dir_parts = parts[:-1]

    # 目录命中 tests / test / __tests__
    for part in dir_parts:
        if part in TEST_DIR_NAMES:
            return True

    name = path.name.lower()
    stem = path.stem.lower()
    ext = path.suffix.lower()

    # Python 常见测试命名
    if name == "conftest.py":
        return True

    if stem.startswith("test_"):
        return True

    if stem.endswith("_test"):
        return True

    # 前端常见测试命名
    if ".test." in name:
        return True

    if ".spec." in name:
        return True

    # Java / C# / Go / Rust 常见测试命名，例如 UserServiceTest.java
    if ext in {".java", ".cs", ".go", ".rs", ".kt"} and stem.endswith("test"):
        return True

    return False


def read_text_safely(path: Path) -> str:
    # utf-8-sig 优先：避免带 BOM 的源文件被 utf-8 读入后残留 U+FEFF，导致 AST 解析失败。
    encodings = ["utf-8-sig", "utf-8", "gbk", "latin-1"]

    for enc in encodings:
        try:
            text = path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            return ""
        return text.lstrip("\ufeff")

    return ""


def count_lines(path: Path) -> dict:
    text = read_text_safely(path)

    if not text:
        return {
            "total": 0,
            "blank": 0,
            "comment": 0,
            "code": 0,
        }

    lines = text.splitlines()

    total = len(lines)
    blank = 0
    comment = 0

    ext = path.suffix.lower()
    prefixes = COMMENT_PREFIXES.get(ext, [])

    for line in lines:
        stripped = line.strip()

        if not stripped:
            blank += 1
            continue

        lower_line = stripped.lower()

        if any(lower_line.startswith(prefix.lower()) for prefix in prefixes):
            comment += 1

    code = total - blank - comment

    return {
        "total": total,
        "blank": blank,
        "comment": comment,
        "code": code,
    }


def _parametrize_case_count(decorator_list: list[ast.expr], module: ast.AST) -> int:
    """估算 @pytest.mark.parametrize 展开数；无法静态识别时按 1 计。"""
    total = 1
    found = False

    def resolve_sequence_length(node: ast.AST) -> int:
        if isinstance(node, (ast.List, ast.Tuple)):
            return len(node.elts)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "range"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, int)
            and node.args[0].value >= 0
        ):
            return int(node.args[0].value)
        if isinstance(node, ast.Name):
            for stmt in getattr(module, "body", []):
                if not isinstance(stmt, ast.Assign):
                    continue
                if any(isinstance(target, ast.Name) and target.id == node.id for target in stmt.targets):
                    if isinstance(stmt.value, (ast.List, ast.Tuple)):
                        return len(stmt.value.elts)
        return 0

    for decorator in decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        is_parametrize = (
            (isinstance(func, ast.Attribute) and func.attr == "parametrize")
            or (isinstance(func, ast.Name) and func.id == "parametrize")
        )
        if not is_parametrize:
            continue
        found = True
        if len(decorator.args) < 2:
            continue
        length = resolve_sequence_length(decorator.args[1])
        if length > 0:
            total *= length
    return total if found else 1


def count_test_cases(path: Path) -> int:
    """Count Python test definitions statically without importing test modules."""
    if path.suffix.lower() != ".py":
        return 0
    text = read_text_safely(path)
    if not text:
        return 0
    try:
        module = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return 0

    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)

    def walk(nodes: list[ast.stmt]) -> int:
        count = 0
        for node in nodes:
            if isinstance(node, function_nodes) and node.name.startswith("test_"):
                count += _parametrize_case_count(node.decorator_list, module)
            elif isinstance(node, ast.ClassDef):
                count += walk(node.body)
        return count

    return walk(module.body)


def normalize_rel_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def classify_module(rel_path: str | Path) -> str:
    """按仓库顶层/一级业务目录归类，便于观察架构重心。"""
    parts = [part for part in normalize_rel_path(rel_path).split("/") if part]
    if not parts:
        return "other"
    top = parts[0]
    if top == "app":
        if len(parts) == 1:
            return "app/other"
        second = parts[1]
        candidate = f"app/{second}"
        if candidate in MODULE_BUCKETS:
            return candidate
        return "app/other"
    if top in {"shared", "cli", "entry", "packaging", "scripts", "tests", "docs"}:
        return top
    return "other"


def classify_test_suite(rel_path: str | Path, *, is_test: bool) -> str:
    """识别 tests/ 下的套件根；非测试文件返回空串。"""
    if not is_test:
        return ""
    parts = [part for part in normalize_rel_path(rel_path).split("/") if part]
    if not parts:
        return "other"
    if parts[0] != "tests":
        return "other"
    if len(parts) == 1:
        return "other"
    suite = parts[1]
    if suite in TEST_SUITE_ROOTS:
        return suite
    return "other"


def file_risk_level(*, total_lines: int, is_test: bool) -> str:
    if is_test:
        if total_lines >= TEST_FILE_RISK_LINES:
            return "risk"
        if total_lines >= TEST_FILE_WATCH_LINES:
            return "watch"
        return "ok"
    if total_lines >= PROD_FILE_RISK_LINES:
        return "risk"
    if total_lines >= PROD_FILE_WATCH_LINES:
        return "watch"
    return "ok"


def _complexity_increment(node: ast.AST) -> int:
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.Assert)):
        return 1
    if isinstance(node, ast.BoolOp):
        return max(0, len(node.values) - 1)
    if isinstance(node, ast.IfExp):
        return 1
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return sum(1 for _ in node.generators)
    if isinstance(node, ast.comprehension):
        return len(node.ifs)
    return 0


def analyze_python_complexity(path: Path) -> list[dict]:
    """用 AST 估算函数圈复杂度，不引入 radon 依赖。"""
    if path.suffix.lower() != ".py":
        return []
    text = read_text_safely(path)
    if not text:
        return []
    try:
        module = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return []

    hotspots: list[dict] = []
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)

    def walk_function(fn_node: ast.AST, qualname: str) -> None:
        score = 1
        for child in ast.walk(fn_node):
            if child is fn_node:
                continue
            score += _complexity_increment(child)
        lineno = getattr(fn_node, "lineno", 0) or 0
        hotspots.append(
            {
                "name": qualname,
                "complexity": score,
                "lineno": lineno,
            }
        )

    for node in module.body:
        if isinstance(node, function_nodes):
            walk_function(node, node.name)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, function_nodes):
                    walk_function(member, f"{node.name}.{member.name}")
    return hotspots


def collect_project_surface(root: Path) -> dict:
    """读取 pyproject 中的脚本入口与运行时依赖面。"""
    surface = {
        "scripts": [],
        "gui_scripts": [],
        "dependencies": [],
        "optional_dependency_groups": 0,
        "python_requires": "",
        "package_name": "",
        "version": "",
    }
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return surface
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return surface
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return surface

    project = data.get("project") or {}
    surface["package_name"] = str(project.get("name") or "")
    surface["version"] = str(project.get("version") or "")
    surface["python_requires"] = str(project.get("requires-python") or "")
    surface["dependencies"] = [str(item) for item in (project.get("dependencies") or [])]
    optional = project.get("optional-dependencies") or {}
    surface["optional_dependency_groups"] = len(optional)
    scripts = project.get("scripts") or {}
    gui_scripts = project.get("gui-scripts") or {}
    surface["scripts"] = [
        {"name": str(name), "target": str(target)}
        for name, target in scripts.items()
    ]
    surface["gui_scripts"] = [
        {"name": str(name), "target": str(target)}
        for name, target in gui_scripts.items()
    ]
    return surface


def _stat_mapping(raw: dict) -> dict:
    return {key: dict(value) for key, value in raw.items()}


def ensure_report_result(result: dict) -> dict:
    """补齐扩展字段，兼容旧测试夹具与历史 JSON。"""
    enriched = dict(result)
    totals = enriched.setdefault(
        "totals",
        {"all": empty_stat(), "prod": empty_stat(), "test": empty_stat()},
    )
    for key in ("all", "prod", "test"):
        totals.setdefault(key, empty_stat())
    enriched.setdefault("by_language", {"all": {}, "prod": {}, "test": {}})
    enriched.setdefault("by_module", {})
    enriched.setdefault("by_suite", {})
    enriched.setdefault("largest_files", [])
    enriched.setdefault("complexity_hotspots", [])
    enriched.setdefault(
        "project_surface",
        {
            "scripts": [],
            "gui_scripts": [],
            "dependencies": [],
            "optional_dependency_groups": 0,
            "python_requires": "",
            "package_name": "",
            "version": "",
        },
    )
    enriched.setdefault("history_delta", None)
    enriched.setdefault("gates", {"enabled": False, "passed": True, "failures": []})
    enriched.setdefault("test_cases", 0)
    enriched.setdefault("code_files", 0)
    enriched.setdefault("total_files", 0)
    enriched.setdefault("total_dirs", 0)
    enriched.setdefault("repository_url", "")
    for item in enriched["largest_files"]:
        item.setdefault("module", classify_module(item.get("path", "")))
        item.setdefault("suite", classify_test_suite(item.get("path", ""), is_test=bool(item.get("is_test"))))
        item.setdefault(
            "risk",
            file_risk_level(total_lines=int(item.get("total", 0) or 0), is_test=bool(item.get("is_test"))),
        )
        item.setdefault("lang", "")
        item.setdefault("code", 0)
        item.setdefault("total", 0)
        item.setdefault("is_test", False)

    # 旧夹具/历史 JSON 可能缺少模块与套件聚合，用 largest_files 回填一份近似视图。
    if not enriched["by_module"] and enriched["largest_files"]:
        module_stats: dict[str, dict] = defaultdict(empty_stat)
        for item in enriched["largest_files"]:
            add_stat(
                module_stats[item["module"]],
                {
                    "total": int(item.get("total") or 0),
                    "blank": 0,
                    "comment": 0,
                    "code": int(item.get("code") or 0),
                },
            )
        enriched["by_module"] = {key: dict(value) for key, value in module_stats.items()}
    if not enriched["by_suite"] and enriched["largest_files"]:
        suite_stats: dict[str, dict] = defaultdict(empty_suite_stat)
        for item in enriched["largest_files"]:
            suite = item.get("suite") or ""
            if not suite:
                continue
            add_stat(
                suite_stats[suite],
                {
                    "total": int(item.get("total") or 0),
                    "blank": 0,
                    "comment": 0,
                    "code": int(item.get("code") or 0),
                },
            )
            suite_stats[suite]["test_cases"] += int(item.get("test_cases") or 0)
        enriched["by_suite"] = {key: dict(value) for key, value in suite_stats.items()}
    for suite_stat in enriched["by_suite"].values():
        suite_stat.setdefault("test_cases", 0)
    return enriched


def scan_project(root: Path, *, analyze_complexity: bool = True) -> dict:
    total_dirs = 0
    total_files = 0
    code_files = 0
    test_cases = 0

    totals = {
        "all": empty_stat(),
        "prod": empty_stat(),
        "test": empty_stat(),
    }

    by_language = {
        "all": defaultdict(empty_stat),
        "prod": defaultdict(empty_stat),
        "test": defaultdict(empty_stat),
    }
    by_module: dict[str, dict] = defaultdict(empty_stat)
    by_suite: dict[str, dict] = defaultdict(empty_suite_stat)
    largest_files = []
    complexity_hotspots: list[dict] = []

    for current_root, dirs, files in os.walk(root):
        current_path = Path(current_root)

        # 阻止进入 .git / .worktrees / .venv / node_modules 等目录
        dirs[:] = [
            d for d in dirs
            if not should_skip_dir(current_path / d)
        ]

        total_dirs += len(dirs)

        for filename in files:
            file_path = current_path / filename
            total_files += 1

            if should_skip_file(file_path):
                continue

            if not is_code_file(file_path):
                continue

            code_files += 1

            stat = count_lines(file_path)
            lang = CODE_EXTS.get(file_path.suffix.lower(), file_path.suffix.lower())
            test_flag = is_test_file(file_path, root)
            file_cases = count_test_cases(file_path) if test_flag else 0
            if test_flag:
                test_cases += file_cases

            group = "test" if test_flag else "prod"
            rel_path = normalize_rel_path(file_path.relative_to(root))
            module = classify_module(rel_path)
            suite = classify_test_suite(rel_path, is_test=test_flag)

            add_stat(totals["all"], stat)
            add_stat(totals[group], stat)

            add_stat(by_language["all"][lang], stat)
            add_stat(by_language[group][lang], stat)
            add_stat(by_module[module], stat)
            if suite:
                add_stat(by_suite[suite], stat)
                by_suite[suite]["test_cases"] += file_cases

            risk = file_risk_level(total_lines=stat["total"], is_test=test_flag)
            largest_files.append({
                "path": rel_path,
                "total": stat["total"],
                "code": stat["code"],
                "is_test": test_flag,
                "lang": lang,
                "module": module,
                "suite": suite,
                "risk": risk,
                "test_cases": file_cases,
            })

            if analyze_complexity and lang == "Python" and not test_flag:
                for hotspot in analyze_python_complexity(file_path):
                    complexity_hotspots.append(
                        {
                            "path": rel_path,
                            "module": module,
                            "name": hotspot["name"],
                            "complexity": hotspot["complexity"],
                            "lineno": hotspot["lineno"],
                        }
                    )

    largest_files.sort(key=lambda x: x["total"], reverse=True)
    complexity_hotspots.sort(key=lambda x: x["complexity"], reverse=True)

    ordered_modules = {
        key: dict(by_module[key])
        for key in MODULE_BUCKETS
        if key in by_module
    }
    for key, value in by_module.items():
        if key not in ordered_modules:
            ordered_modules[key] = dict(value)

    ordered_suites = {
        key: dict(by_suite[key])
        for key in TEST_SUITE_ROOTS
        if key in by_suite
    }
    for key, value in by_suite.items():
        if key not in ordered_suites:
            ordered_suites[key] = dict(value)

    return {
        "root": str(root),
        "repository_url": detect_repository_url(root),
        "total_dirs": total_dirs,
        "total_files": total_files,
        "code_files": code_files,
        "test_cases": test_cases,
        "totals": totals,
        "by_language": {
            "all": _stat_mapping(by_language["all"]),
            "prod": _stat_mapping(by_language["prod"]),
            "test": _stat_mapping(by_language["test"]),
        },
        "by_module": ordered_modules,
        "by_suite": ordered_suites,
        "largest_files": largest_files[:LARGEST_FILES_LIMIT],
        "complexity_hotspots": complexity_hotspots[:COMPLEXITY_HOTSPOT_LIMIT],
        "project_surface": collect_project_surface(root),
        "history_delta": None,
        "gates": {"enabled": False, "passed": True, "failures": []},
    }


def print_total_report(result: dict) -> None:
    print("项目代码量统计报告")
    print(f"项目路径: {result['root']}")
    print(f"目录数量: {result['total_dirs']}")
    print(f"文件总数: {result['total_files']}")
    print(f"代码文件数: {result['code_files']}")
    print(f"\u6d4b\u8bd5\u7528\u4f8b\u6570: {result['test_cases']}")
    print()
    _print_table(
        "总览：含测试 / 排除测试 / 仅测试",
        [
            ("统计口径", "center"),
            ("代码文件数", "center"),
            ("总行数", "center"),
            ("空行数", "center"),
            ("注释行数", "center"),
            ("有效代码行数", "center"),
        ],
        build_total_rows(result),
    )


def print_language_report(result: dict) -> None:
    print()
    _print_table(
        "按语言统计：全部 / 排除测试 / 测试",
        [
            ("语言", "center"),
            ("全部文件", "center"),
            ("全部行", "center"),
            ("全部代码", "center"),
            ("生产代码", "center"),
            ("测试代码", "center"),
            ("测试文件", "center"),
        ],
        build_language_rows(result),
    )


def print_module_report(result: dict) -> None:
    rows = build_module_rows(result)
    if not rows:
        return
    print()
    _print_table(
        "按模块统计",
        [
            ("模块", "center"),
            ("文件数", "center"),
            ("总行数", "center"),
            ("有效代码", "center"),
            ("占比", "center"),
        ],
        rows,
    )


def print_suite_report(result: dict) -> None:
    rows = build_suite_rows(result)
    if not rows:
        return
    print()
    _print_table(
        "测试套件分布",
        [
            ("套件", "center"),
            ("文件数", "center"),
            ("用例数", "center"),
            ("总行数", "center"),
            ("有效代码", "center"),
            ("占比", "center"),
        ],
        rows,
    )


def print_complexity_report(result: dict) -> None:
    rows = build_complexity_rows(result)
    if not rows:
        return
    print()
    _print_table(
        f"Python 复杂度热点 Top {COMPLEXITY_HOTSPOT_LIMIT}",
        [
            ("复杂度", "center"),
            ("模块", "center"),
            ("符号", "center"),
            ("位置", "center"),
        ],
        rows,
    )


def print_surface_report(result: dict) -> None:
    rows = build_surface_rows(result)
    if not rows:
        return
    print()
    _print_table(
        "项目表面（pyproject）",
        [
            ("项", "center"),
            ("值", "center"),
        ],
        rows,
    )


def print_delta_report(result: dict) -> None:
    rows = build_delta_rows(result)
    if not rows:
        return
    print()
    _print_table(
        "与历史快照对比",
        [
            ("指标", "center"),
            ("上次", "center"),
            ("本次", "center"),
            ("变化", "center"),
            ("变化率", "center"),
        ],
        rows,
    )
    delta = result.get("history_delta") or {}
    new_top = delta.get("new_top_files") or []
    left_top = delta.get("left_top_files") or []
    if new_top:
        print(f"新进 Top{LARGEST_FILES_LIMIT} 大文件:")
        for path in new_top:
            print(f"  + {path}")
    if left_top:
        print(f"离开 Top{LARGEST_FILES_LIMIT} 大文件:")
        for path in left_top:
            print(f"  - {path}")


def print_gates_report(result: dict) -> None:
    gates = result.get("gates") or {}
    if not gates.get("enabled"):
        return
    status = "通过" if gates.get("passed") else "未通过"
    print()
    print(f"质量门禁: {status}")
    for item in gates.get("failures") or []:
        print(f"  - {item}")


def format_num(value: int) -> str:
    return f"{value:,}"


def percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return part / total * 100


def build_total_rows(result: dict) -> list[list[object]]:
    totals = result["totals"]
    return [
        [
            "全部代码_含测试",
            totals["all"]["files"],
            totals["all"]["total"],
            totals["all"]["blank"],
            totals["all"]["comment"],
            totals["all"]["code"],
        ],
        [
            "排除测试后",
            totals["prod"]["files"],
            totals["prod"]["total"],
            totals["prod"]["blank"],
            totals["prod"]["comment"],
            totals["prod"]["code"],
        ],
        [
            "仅测试代码",
            totals["test"]["files"],
            totals["test"]["total"],
            totals["test"]["blank"],
            totals["test"]["comment"],
            totals["test"]["code"],
        ],
    ]


def build_language_rows(result: dict) -> list[list[object]]:
    by_all = result["by_language"]["all"]
    by_prod = result["by_language"]["prod"]
    by_test = result["by_language"]["test"]
    rows = []
    for lang in sorted(by_all.keys(), key=lambda item: by_all[item]["total"], reverse=True):
        all_stat = by_all[lang]
        prod_stat = by_prod.get(lang, empty_stat())
        test_stat = by_test.get(lang, empty_stat())
        rows.append(
            [
                lang,
                all_stat["files"],
                all_stat["total"],
                all_stat["code"],
                prod_stat["code"],
                test_stat["code"],
                test_stat["files"],
            ]
        )
    return rows


def build_module_rows(result: dict) -> list[list[object]]:
    by_module = result.get("by_module") or {}
    total_code = result["totals"]["all"]["code"]
    rows = []
    for module, stat in by_module.items():
        rows.append(
            [
                module,
                stat["files"],
                stat["total"],
                stat["code"],
                f"{percent(stat['code'], total_code):.1f}%",
            ]
        )
    rows.sort(key=lambda row: row[3], reverse=True)
    return rows


def build_suite_rows(result: dict) -> list[list[object]]:
    by_suite = result.get("by_suite") or {}
    total_test_code = result["totals"]["test"]["code"]
    rows = []
    for suite in TEST_SUITE_ROOTS:
        stat = by_suite.get(suite)
        if not stat:
            continue
        rows.append(
            [
                suite,
                stat["files"],
                int(stat.get("test_cases") or 0),
                stat["total"],
                stat["code"],
                f"{percent(stat['code'], total_test_code):.1f}%",
            ]
        )
    for suite, stat in by_suite.items():
        if suite in TEST_SUITE_ROOTS:
            continue
        rows.append(
            [
                suite,
                stat["files"],
                int(stat.get("test_cases") or 0),
                stat["total"],
                stat["code"],
                f"{percent(stat['code'], total_test_code):.1f}%",
            ]
        )
    return rows


def build_complexity_rows(result: dict) -> list[list[object]]:
    return [
        [
            item["complexity"],
            item.get("module") or classify_module(item["path"]),
            item["name"],
            f"{item['path']}:{item.get('lineno', 0)}",
        ]
        for item in (result.get("complexity_hotspots") or [])
    ]


def build_surface_rows(result: dict) -> list[list[object]]:
    surface = result.get("project_surface") or {}
    rows = [
        ["包名", surface.get("package_name") or "-"],
        ["版本", surface.get("version") or "-"],
        ["Python 要求", surface.get("python_requires") or "-"],
        ["运行时依赖数", len(surface.get("dependencies") or [])],
        ["可选依赖组", surface.get("optional_dependency_groups") or 0],
        ["console scripts", len(surface.get("scripts") or [])],
        ["gui scripts", len(surface.get("gui_scripts") or [])],
    ]
    for item in (surface.get("scripts") or [])[:12]:
        rows.append([f"script:{item['name']}", item["target"]])
    for item in (surface.get("gui_scripts") or [])[:8]:
        rows.append([f"gui:{item['name']}", item["target"]])
    return rows


def build_delta_rows(result: dict) -> list[list[object]]:
    delta = result.get("history_delta") or {}
    metrics = delta.get("metrics") or []
    return [
        [item["label"], item["previous"], item["current"], item["delta"], item["delta_ratio"]]
        for item in metrics
    ]


def compute_history_delta(current: dict, previous: dict) -> dict:
    """对比两份报告快照，生成规模与结构变化摘要。"""
    cur_totals = current.get("totals") or {}
    prev_totals = previous.get("totals") or {}

    def _metric(label: str, cur: int, prev: int) -> dict:
        delta = cur - prev
        ratio = "n/a" if prev == 0 else f"{percent(delta, prev):+.1f}%"
        return {
            "label": label,
            "previous": prev,
            "current": cur,
            "delta": delta,
            "delta_ratio": ratio,
        }

    metrics = [
        _metric("有效代码行(全部)", cur_totals.get("all", {}).get("code", 0), prev_totals.get("all", {}).get("code", 0)),
        _metric("有效代码行(生产)", cur_totals.get("prod", {}).get("code", 0), prev_totals.get("prod", {}).get("code", 0)),
        _metric("有效代码行(测试)", cur_totals.get("test", {}).get("code", 0), prev_totals.get("test", {}).get("code", 0)),
        _metric("代码文件数", int(current.get("code_files") or 0), int(previous.get("code_files") or 0)),
        _metric("测试用例数", int(current.get("test_cases") or 0), int(previous.get("test_cases") or 0)),
    ]
    cur_top = {item["path"] for item in (current.get("largest_files") or [])[:LARGEST_FILES_LIMIT]}
    prev_top = {item["path"] for item in (previous.get("largest_files") or [])[:LARGEST_FILES_LIMIT]}
    return {
        "previous_root": previous.get("root") or "",
        "metrics": metrics,
        "new_top_files": sorted(cur_top - prev_top),
        "left_top_files": sorted(prev_top - cur_top),
    }


def evaluate_gates(
    result: dict,
    *,
    prod_max_lines: int | None,
    test_ratio_min: float | None,
) -> dict:
    failures: list[str] = []
    enabled = prod_max_lines is not None or test_ratio_min is not None
    if prod_max_lines is not None:
        offenders = [
            item
            for item in (result.get("largest_files") or [])
            if (not item.get("is_test")) and int(item.get("total") or 0) > prod_max_lines
        ]
        for item in offenders[:8]:
            failures.append(
                f"生产文件超过 {prod_max_lines} 行: {item['path']} ({item['total']})"
            )
        if len(offenders) > 8:
            failures.append(f"另有 {len(offenders) - 8} 个生产大文件超限")
    if test_ratio_min is not None:
        total_code = result["totals"]["all"]["code"]
        test_code = result["totals"]["test"]["code"]
        ratio = percent(test_code, total_code)
        if ratio + 1e-9 < test_ratio_min:
            failures.append(f"测试代码占比 {ratio:.1f}% 低于阈值 {test_ratio_min:.1f}%")
    return {
        "enabled": enabled,
        "passed": not failures,
        "failures": failures,
        "prod_max_lines": prod_max_lines,
        "test_ratio_min": test_ratio_min,
    }


def load_history_report(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def save_report_json(result: dict, output_path: str | Path) -> Path:
    import json

    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = ensure_report_result(result)
    path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path.resolve()


def build_language_chart_rows(result: dict, limit: int = 8) -> list[dict]:
    by_all = result["by_language"]["all"]
    ranked = sorted(
        (
            {"lang": lang, "code": stat["code"]}
            for lang, stat in by_all.items()
            if stat["code"] > 0
        ),
        key=lambda item: item["code"],
        reverse=True,
    )[:limit]
    total_code = result["totals"]["all"]["code"]
    max_code = ranked[0]["code"] if ranked else 0
    rows = []
    for item in ranked:
        width = percent(item["code"], max_code)
        if item["code"] > 0:
            width = max(width, 3.0)
        rows.append({
            "lang": item["lang"],
            "code": item["code"],
            "ratio": percent(item["code"], total_code),
            "width": width,
        })
    return rows


def build_largest_chart_rows(result: dict, limit: int = LARGEST_FILES_LIMIT) -> list[dict]:
    items = result["largest_files"][:limit]
    max_total = items[0]["total"] if items else 0
    rows = []
    for item in items:
        path = str(item["path"])
        name = path.replace("\\", "/").split("/")[-1]
        rows.append({
            "path": path,
            "name": name,
            "total": item["total"],
            "code": item["code"],
            "is_test": item["is_test"],
            "type": "TEST" if item["is_test"] else "PROD",
            "width": percent(item["total"], max_total),
        })
    return rows


GITHUB_MARK_PATH = (
    "M12 .7C5.7.7.9 5.5.9 11.8c0 4.9 3.1 9.1 7.4 10.6.6.1.8-.3.8-.6v-2.1"
    "c-3 .7-3.7-1.3-3.7-1.3-.5-1.2-1.2-1.5-1.2-1.5-1-.7.1-.7.1-.7 1.1.1 1.7 1.1"
    " 1.7 1.1 1 1.7 2.7 1.2 3.4.9.1-.8.4-1.2.7-1.5-2.4-.3-4.9-1.2-4.9-5.3"
    " 0-1.2.4-2.1 1.1-2.9-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 3 1.1a10.4 10.4 0 0 1"
    " 5.5 0c2.1-1.4 3-1.1 3-1.1.6 1.5.2 2.6.1 2.9.7.8 1.1 1.8 1.1 2.9"
    " 0 4.1-2.5 5-4.9 5.3.4.3.7 1 .7 2v3c0 .4.2.8.8.6a11.1 11.1 0 0 0"
    " 7.4-10.6C23.1 5.5 18.3.7 12 .7Z"
)


def render_repository_link(repository_url: str) -> str:
    normalized_url = normalize_repository_url(repository_url)
    if not normalized_url:
        return ""

    display_text = normalized_url.removeprefix("https://").removeprefix("http://")
    safe_url = escape(normalized_url, quote=True)
    safe_text = escape(display_text)
    safe_label = escape(f"打开 GitHub 仓库：{display_text}", quote=True)
    return f"""
<a class="hero-repository" href="{safe_url}" target="_blank"
   rel="noopener noreferrer" aria-label="{safe_label}" title="{safe_url}">
<svg class="github-logo" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
<path d="{GITHUB_MARK_PATH}"></path>
</svg>
<span>{safe_text}</span>
</a>
"""


def render_kpi_card(label: str, value: int, hint: str, icon: str, tone: str = "sky") -> str:
    return f"""
<article class="metric-card metric-{escape(tone)}">
<div class="metric-top">
<span class="metric-icon">{escape(icon)}</span>
<span class="metric-label">{escape(label)}</span>
</div>
<div class="metric-value">{escape(format_num(value))}</div>
<div class="metric-hint">{escape(hint)}</div>
</article>
"""


def render_donut_card(prod_code: int, test_code: int) -> str:
    total_code = prod_code + test_code
    test_ratio = percent(test_code, total_code)
    prod_ratio = percent(prod_code, total_code)
    test_deg = round(test_ratio / 100 * 360, 2)
    return f"""
<article class="chart-card chart-card-donut">
<div class="chart-head">
<div>
<h2>代码构成</h2>
<p>生产代码与测试代码有效行数占比</p>
</div>
</div>
<div class="donut-layout">
<div class="donut" style="--test-deg: {test_deg}deg;">
<div class="donut-hole">
<div class="donut-value">{test_ratio:.1f}%</div>
<div class="donut-label">测试占比</div>
</div>
</div>
<div class="legend">
<div class="legend-item">
<span class="legend-dot legend-prod"></span>
<span>生产代码</span>
<strong>{format_num(prod_code)} 行</strong>
<em>{prod_ratio:.1f}%</em>
</div>
<div class="legend-item">
<span class="legend-dot legend-test"></span>
<span>测试代码</span>
<strong>{format_num(test_code)} 行</strong>
<em>{test_ratio:.1f}%</em>
</div>
</div>
</div>
</article>
"""


def render_language_chart(rows: list[dict]) -> str:
    body = []
    for index, row in enumerate(rows):
        highlight = " bar-fill-primary" if index == 0 else ""
        body.append(f"""
<div class="bar-row">
<div class="bar-name">{escape(str(row["lang"]))}</div>
<div class="bar-track"><div class="bar-fill{highlight}" style="width: {row["width"]:.2f}%"></div></div>
<div class="bar-value">{format_num(row["code"])}</div>
<div class="bar-ratio">{row["ratio"]:.1f}%</div>
</div>
""")
    if not body:
        body.append('<div class="empty-note">暂无可统计的语言数据</div>')
    return f"""
<article class="chart-card">
<div class="chart-head">
<div>
<h2>语言分布 Top 8</h2>
<p>按有效代码行数排序</p>
</div>
</div>
<div class="bar-chart">
{''.join(body)}
</div>
</article>
"""


def render_largest_files_chart(rows: list[dict]) -> str:
    body = []
    for row in rows:
        badge_class = "badge-test" if row["is_test"] else "badge-prod"
        body.append(f"""
<div class="bar-row file-bar-row">
<div class="file-label" title="{escape(row["path"], quote=True)}">
<span class="file-name">{escape(row["name"])}</span>
<span class="file-path">{escape(row["path"])}</span>
</div>
<span class="badge {badge_class}">{escape(row["type"])}</span>
<div class="bar-track"><div class="bar-fill bar-fill-file" style="width: {row["width"]:.2f}%"></div></div>
<div class="bar-value">{format_num(row["total"])}</div>
</div>
""")
    if not body:
        body.append('<div class="empty-note">暂无大文件数据</div>')
    return f"""
<article class="chart-card">
<div class="chart-head">
<div>
<h2>最大文件 Top {LARGEST_FILES_LIMIT}</h2>
<p>按文件总行数排序，提示潜在拆分风险</p>
</div>
</div>
<div class="bar-chart largest-chart">
{''.join(body)}
</div>
</article>
"""


def render_insights(result: dict) -> str:
    result = ensure_report_result(result)
    total_code = result["totals"]["all"]["code"]
    prod_code = result["totals"]["prod"]["code"]
    test_code = result["totals"]["test"]["code"]
    test_ratio = percent(test_code, total_code)

    if test_ratio >= 25:
        test_message = "测试占比较高，回归保护较充分"
        test_tone = "good"
    elif test_ratio >= 10:
        test_message = "测试占比中等，可继续补充关键路径测试"
        test_tone = "watch"
    else:
        test_message = "测试占比较低，建议补充核心模块测试"
        test_tone = "risk"

    largest_items = result["largest_files"]
    largest_file = largest_items[0] if largest_items else None
    largest_total = largest_file["total"] if largest_file else 0
    largest_path = str(largest_file["path"]) if largest_file else "无"
    largest_risk = str((largest_file or {}).get("risk") or file_risk_level(total_lines=largest_total, is_test=False))
    if largest_risk == "risk" or largest_total >= PROD_FILE_RISK_LINES:
        largest_message = "存在超大文件，建议评估拆分"
        largest_tone = "risk"
    elif largest_risk == "watch" or largest_total >= PROD_FILE_WATCH_LINES:
        largest_message = "存在较大文件，建议关注复杂度"
        largest_tone = "watch"
    else:
        largest_message = "单文件规模较可控"
        largest_tone = "good"

    language_rows = build_language_chart_rows(result, limit=1)
    if language_rows:
        primary_lang = str(language_rows[0]["lang"])
        primary_ratio = language_rows[0]["ratio"]
    else:
        primary_lang = "无"
        primary_ratio = 0.0

    language_message = f"主语言：{primary_lang}，占比 {primary_ratio:.1f}%"
    prod_ratio = percent(prod_code, total_code)

    cards = [
        ("测试代码占比", f"{test_ratio:.1f}%", test_message, test_tone),
        ("最大文件风险", f"{format_num(largest_total)} 行", largest_message, largest_tone),
        ("主语言", primary_lang, language_message, "neutral"),
        ("生产代码占比", f"{prod_ratio:.1f}%", "用于观察业务代码与测试代码结构", "neutral"),
    ]
    markup = []
    for label, value, message, tone in cards:
        title = largest_path if label == "最大文件风险" else message
        markup.append(f"""
<article class="insight-card insight-{tone}" title="{escape(str(title), quote=True)}">
<div class="insight-label">{escape(label)}</div>
<div class="insight-value">{escape(str(value))}</div>
<p>{escape(message)}</p>
</article>
""")
    return f"""
<section class="insights">
<div class="section-title">
<h2>代码质量 / 风险摘要</h2>
<p>基于当前统计结果自动生成的结构观察</p>
</div>
<div class="insight-grid">
{''.join(markup)}
</div>
</section>
"""


def render_table(title: str, columns: list[tuple[str, str]], rows: list[list[object]]) -> str:
    path_headers = {"文件", "位置", "路径"}

    def column_classes(index: int) -> str:
        if index >= len(columns):
            return "center"
        header, _justify = columns[index]
        if header in path_headers:
            return "center path"
        return "center"

    def render_cell(value: object, index: int) -> str:
        text = str(value)
        classes = column_classes(index)
        title_attr = ""
        if index < len(columns) and columns[index][0] in path_headers:
            title_attr = f' title="{escape(text, quote=True)}"'
        badge_map = {
            "TEST": "badge-test",
            "PROD": "badge-prod",
            "RISK": "badge-risk",
            "WATCH": "badge-watch",
            "OK": "badge-ok",
        }
        if text in badge_map:
            content = f'<span class="badge {badge_map[text]}">{escape(text)}</span>'
        else:
            content = escape(text)
        return f'<td class="{classes}"{title_attr}>{content}</td>'

    header_cells = [
        f'<th class="{column_classes(index)}">{escape(str(header))}</th>'
        for index, (header, _justify) in enumerate(columns)
    ]
    body_rows = [
        f"<tr>{''.join(render_cell(value, index) for index, value in enumerate(row))}</tr>"
        for row in rows
    ]

    return f"""
<section class="report-section">
<h2>{escape(title)}</h2>
<div class="table-wrap">
<table>
<thead><tr>{''.join(header_cells)}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
</div>
</section>
"""


REPORT_CSS = """
:root {
    color-scheme: light;
    --bg: #fff5f8;
    --panel: #fffafc;
    --text: #3b2a35;
    --muted: #8b7380;
    --line: #f3d5e2;
    --blue: #7eb6ff;
    --blue2: #b8e0ff;
    --green: #7dd3b0;
    --orange: #ffb4a2;
    --red: #ff8fab;
    --pink: #ff9ec8;
    --peach: #ffc9a3;
    --mint: #9be7c4;
    --sky: #9fd4ff;
    --lavender: #d4b8ff;
    --cream: #fff7fb;
    --shadow: 0 18px 40px rgba(255, 158, 200, 0.18);
    --shadow-soft: 0 10px 28px rgba(255, 182, 193, 0.22);
}
* {
    box-sizing: border-box;
}
html {
    min-height: 100%;
    background-color: #ffe9f2;
    scroll-behavior: auto;
}
body {
    margin: 0;
    min-height: 100vh;
    color: var(--text);
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", sans-serif;
    font-size: 15px;
    /* 随文档滚动平铺，不再用 fixed 四角光斑（长页滚动会上下截断） */
    background-color: #ffe9f2;
    background-image:
        radial-gradient(circle, rgba(255, 196, 220, 0.95) 1.05px, transparent 1.05px),
        repeating-linear-gradient(
            180deg,
            #ffd6e8 0px,
            #ffe9f2 220px,
            #eaf4ff 440px,
            #f3eaff 660px,
            #fff1e8 880px,
            #ffd6e8 1100px
        );
    background-size: 22px 22px, 100% 1100px;
    background-repeat: repeat, repeat;
    background-attachment: scroll;
}
.page {
    width: min(1280px, calc(100% - 48px));
    margin: 32px auto 48px;
    padding: 0;
}
.hero {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 32px;
    overflow: hidden;
    padding: 34px;
    min-height: 260px;
    color: #ffffff;
    background:
        linear-gradient(rgba(255, 255, 255, 0.065) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.065) 1px, transparent 1px),
        linear-gradient(135deg, #0f172a 0%, #1d4ed8 72%, #38bdf8 130%);
    background-size: 34px 34px, 34px 34px, auto;
    border-radius: 20px;
    box-shadow: 0 20px 55px rgba(15, 23, 42, 0.16);
}
.hero::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, transparent, rgba(255, 255, 255, 0.14));
    pointer-events: none;
}
.hero-content,
.hero-stat {
    position: relative;
    z-index: 1;
    min-width: 0;
}
.hero-title {
    margin: 0;
    font-size: clamp(32px, 4vw, 54px);
    line-height: 1.05;
    letter-spacing: 0;
}
.hero-subtitle {
    width: min(760px, 100%);
    margin: 16px 0 24px;
    color: rgba(255, 255, 255, 0.80);
    font-size: 17px;
    line-height: 1.75;
    text-wrap: pretty;
}
.hero-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    max-width: 100%;
}
.hero-path {
    display: inline-flex;
    flex: 0 1 auto;
    min-width: 0;
    width: fit-content;
    max-width: 100%;
    padding: 9px 12px;
    color: rgba(255, 255, 255, 0.88);
    background: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 999px;
    overflow-wrap: anywhere;
}
.hero-repository {
    display: inline-flex;
    align-items: center;
    flex: 0 1 auto;
    gap: 8px;
    min-width: 0;
    max-width: 100%;
    padding: 9px 12px;
    color: #ffffff;
    background: rgba(15, 23, 42, 0.36);
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 999px;
    text-decoration: none;
    overflow-wrap: anywhere;
    transition: background-color 160ms ease, border-color 160ms ease, transform 160ms ease;
}
.hero-repository:hover {
    background: rgba(15, 23, 42, 0.56);
    border-color: rgba(255, 255, 255, 0.44);
    transform: translateY(-1px);
}
.hero-repository:focus-visible {
    outline: 2px solid #ffffff;
    outline-offset: 3px;
}
.github-logo {
    width: 19px;
    height: 19px;
    flex: 0 0 19px;
    fill: currentColor;
}
.hero-stat {
    align-self: stretch;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 24px;
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 18px;
    backdrop-filter: blur(14px);
}
.hero-stat-label {
    color: rgba(255, 255, 255, 0.72);
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.hero-stat-value {
    margin-top: 12px;
    font-size: clamp(36px, 5vw, 58px);
    font-weight: 800;
    line-height: 1;
    font-variant-numeric: tabular-nums;
}
.hero-stat-note {
    margin-top: 10px;
    color: rgba(255, 255, 255, 0.72);
}
.metrics {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 16px;
    margin-top: 18px;
}
.metric-card,
.chart-card,
.report-section,
.insights {
    position: relative;
    overflow: hidden;
    background:
        linear-gradient(165deg, rgba(255, 255, 255, 0.96), rgba(255, 248, 252, 0.94));
    border: 2px solid #ffd6e7;
    border-radius: 28px;
    box-shadow: var(--shadow-soft);
}
.metric-card::before,
.chart-card::before,
.report-section::before,
.insights::before {
    content: "";
    position: absolute;
    top: -18px;
    right: -12px;
    width: 72px;
    height: 72px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(255, 182, 213, 0.45), transparent 68%);
    pointer-events: none;
}
.metric-card {
    padding: 18px 18px 16px;
    transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
}
.metric-card:hover {
    transform: translateY(-4px) scale(1.01);
    box-shadow: 0 18px 36px rgba(255, 158, 200, 0.28);
    border-color: #ffb7d5;
}
.metric-strawberry { border-color: #ffc1d9; }
.metric-peach { border-color: #ffd2b5; }
.metric-mint { border-color: #b8efd4; }
.metric-sky { border-color: #b9e0ff; }
.metric-lavender { border-color: #e0ccff; }
.metric-strawberry .metric-icon { color: #e85a8c; background: #ffe0ec; }
.metric-peach .metric-icon { color: #e8894c; background: #ffe8d6; }
.metric-mint .metric-icon { color: #2f9d6a; background: #d9f8e8; }
.metric-sky .metric-icon { color: #3b82c4; background: #dff0ff; }
.metric-lavender .metric-icon { color: #8b5bb8; background: #efe4ff; }
.metric-top {
    display: flex;
    align-items: center;
    gap: 10px;
}
.metric-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    border-radius: 999px;
    border: 2px solid rgba(255, 255, 255, 0.85);
    box-shadow: 0 6px 14px rgba(255, 158, 200, 0.18);
    font-weight: 800;
}
.metric-label,
.meta-label {
    color: var(--muted);
    font-size: 13px;
    font-weight: 650;
}
.metric-value {
    margin-top: 14px;
    font-size: 30px;
    font-weight: 800;
    line-height: 1;
    color: #4a3040;
    font-variant-numeric: tabular-nums;
}
.metric-hint {
    margin-top: 12px;
    color: var(--muted);
    line-height: 1.55;
}
.dashboard-grid {
    display: grid;
    grid-template-columns: 1fr 1.15fr 1.25fr;
    gap: 18px;
    margin-top: 18px;
}
.chart-card {
    min-height: 390px;
    padding: 20px;
}
.chart-card-donut {
    border-color: #ffc9dd;
}
.dashboard-grid .chart-card:nth-child(2) {
    border-color: #bfe9ff;
}
.dashboard-grid .chart-card:nth-child(3) {
    border-color: #c8f0da;
}
.chart-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
}
.chart-head h2,
.report-section h2,
.section-title h2 {
    margin: 0;
    font-size: 18px;
    line-height: 1.35;
    color: #5a3a4a;
}
.chart-head h2::before,
.report-section h2::before,
.section-title h2::before {
    content: "♡ ";
    color: #ff8fbf;
    font-weight: 500;
}
.chart-head p,
.section-title p {
    margin: 5px 0 0;
    color: var(--muted);
}
.donut-layout {
    display: grid;
    gap: 18px;
    place-items: center;
}
.donut {
    display: grid;
    place-items: center;
    width: 196px;
    height: 196px;
    border-radius: 999px;
    background: conic-gradient(#ffb4c8 0deg var(--test-deg), #9fd4ff var(--test-deg) 360deg);
    box-shadow:
        inset 0 0 0 3px rgba(255, 255, 255, 0.65),
        0 12px 28px rgba(255, 158, 200, 0.25);
}
.donut-hole {
    display: grid;
    place-items: center;
    width: 126px;
    height: 126px;
    background: linear-gradient(180deg, #ffffff, #fff5f9);
    border-radius: 999px;
    box-shadow: 0 10px 22px rgba(255, 158, 200, 0.18);
}
.donut-value {
    font-size: 30px;
    font-weight: 800;
    color: #e85a8c;
    font-variant-numeric: tabular-nums;
}
.donut-label {
    margin-top: -22px;
    color: var(--muted);
    font-size: 13px;
}
.legend {
    width: 100%;
    display: grid;
    gap: 10px;
}
.legend-item {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    gap: 8px;
    align-items: center;
    padding: 8px 10px;
    color: var(--muted);
    background: rgba(255, 245, 250, 0.8);
    border: 1px solid #ffe0ec;
    border-radius: 14px;
}
.legend-item strong,
.legend-item em {
    color: var(--text);
    font-style: normal;
    font-variant-numeric: tabular-nums;
}
.legend-dot {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.8);
}
.legend-prod {
    background: #9fd4ff;
}
.legend-test {
    background: #ffb4c8;
}
.bar-chart {
    display: grid;
    gap: 13px;
}
.bar-row {
    display: grid;
    grid-template-columns: 98px minmax(90px, 1fr) 78px 52px;
    gap: 10px;
    align-items: center;
}
.bar-name,
.bar-value,
.bar-ratio {
    font-variant-numeric: tabular-nums;
}
.bar-name {
    overflow: hidden;
    color: #5a3a4a;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.bar-track {
    height: 12px;
    overflow: hidden;
    background: #ffe9f1;
    border-radius: 999px;
    box-shadow: inset 0 1px 2px rgba(255, 143, 191, 0.15);
}
.bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #ffc2d9, #ff8fbf);
    border-radius: inherit;
}
.bar-fill-primary {
    background: linear-gradient(90deg, #ffb4c8, #ff8fab 55%, #ffc9a3);
}
.bar-fill-file {
    background: linear-gradient(90deg, #9be7c4, #9fd4ff);
}
.bar-value,
.bar-ratio {
    text-align: right;
    color: #5a3a4a;
}
.file-bar-row {
    grid-template-columns: minmax(120px, 1.4fr) auto minmax(90px, 1fr) 72px;
}
.file-label {
    min-width: 0;
}
.file-name,
.file-path {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.file-name {
    color: #4a3040;
    font-weight: 700;
}
.file-path {
    margin-top: 2px;
    color: var(--muted);
    font-size: 12px;
}
.insights {
    margin-top: 18px;
    padding: 20px;
}
.section-title {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
}
.insight-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
}
.insight-card {
    padding: 16px;
    background: #fff7fb;
    border: 2px solid #ffd6e7;
    border-radius: 22px;
    box-shadow: 0 8px 18px rgba(255, 182, 193, 0.14);
    transition: transform 160ms ease;
}
.insight-card:hover {
    transform: translateY(-2px);
}
.insight-label {
    color: var(--muted);
    font-size: 13px;
    font-weight: 650;
}
.insight-value {
    margin-top: 8px;
    font-size: 23px;
    font-weight: 800;
    color: #4a3040;
    font-variant-numeric: tabular-nums;
}
.insight-card p {
    margin: 10px 0 0;
    color: #7a5a68;
    line-height: 1.55;
}
.insight-good {
    border-color: #b8efd4;
    background: linear-gradient(165deg, #f3fff8, #e8fbf1);
}
.insight-watch {
    border-color: #ffd2b5;
    background: linear-gradient(165deg, #fff8f1, #ffefdf);
}
.insight-risk {
    border-color: #ffc1d9;
    background: linear-gradient(165deg, #fff5f8, #ffe4ef);
}
.insight-neutral {
    border-color: #b9e0ff;
    background: linear-gradient(165deg, #f5fbff, #e8f5ff);
}
.report-section {
    margin-top: 18px;
    padding: 20px;
}
.table-wrap {
    overflow-x: auto;
    border: 2px solid #ffe0ec;
    border-radius: 18px;
    background: #fffafc;
}
table {
    width: 100%;
    min-width: 0;
    table-layout: auto;
    border-collapse: collapse;
}
th,
td {
    padding: 11px 13px;
    border-bottom: 1px solid #ffe6f0;
    text-align: center;
    vertical-align: middle;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
    font-variant-numeric: tabular-nums;
}
th {
    color: #7a4a62;
    background: linear-gradient(180deg, #ffe9f2, #ffdceb);
    font-weight: 700;
}
tbody tr:hover {
    background: #fff3f8;
}
tr:last-child td {
    border-bottom: none;
}
.center {
    text-align: center;
}
.path {
    min-width: 0;
    line-height: 1.45;
}
.badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 46px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
    line-height: 1.2;
    letter-spacing: 0;
    box-shadow: 0 4px 10px rgba(255, 158, 200, 0.12);
}
.badge-test {
    color: #c45c2a;
    background: #ffe8d6;
    border: 1px solid #ffc9a3;
}
.badge-prod {
    color: #3b82c4;
    background: #dff0ff;
    border: 1px solid #9fd4ff;
}
.badge-risk {
    color: #d63b6a;
    background: #ffe0ec;
    border: 1px solid #ffb4c8;
}
.badge-watch {
    color: #d07a2e;
    background: #fff0dd;
    border: 1px solid #ffd2b5;
}
.badge-ok {
    color: #2f9d6a;
    background: #d9f8e8;
    border: 1px solid #9be7c4;
}
.gate-banner {
    margin-top: 18px;
    padding: 16px 18px;
    border-radius: 24px;
    border: 2px solid #ffd6e7;
    background: #fff7fb;
    box-shadow: var(--shadow-soft);
}
.gate-banner.gate-pass {
    border-color: #b8efd4;
    background: linear-gradient(165deg, #f3fff8, #e8fbf1);
}
.gate-banner.gate-fail {
    border-color: #ffc1d9;
    background: linear-gradient(165deg, #fff5f8, #ffe4ef);
}
.gate-banner h2 {
    margin: 0 0 8px;
    font-size: 18px;
}
.gate-banner ul {
    margin: 0;
    padding-left: 18px;
}
.gate-banner li {
    margin: 4px 0;
    color: #334155;
}
.empty-note {
    padding: 14px;
    color: var(--muted);
    background: #f8fafc;
    border: 1px dashed var(--line);
    border-radius: 12px;
}
@media (max-width: 1100px) {
    .hero,
    .dashboard-grid,
    .metrics,
    .insight-grid {
        grid-template-columns: 1fr 1fr;
    }
    .hero-stat {
        align-self: stretch;
    }
}
@media (max-width: 720px) {
    .page {
        width: min(100% - 28px, 1280px);
        margin: 20px auto 32px;
        padding: 0;
    }
    .hero,
    .dashboard-grid,
    .metrics,
    .insight-grid {
        grid-template-columns: 1fr;
    }
    .hero {
        padding: 24px;
    }
    .hero-path,
    .hero-repository {
        width: 100%;
        border-radius: 14px;
    }
    .bar-row,
    .file-bar-row {
        grid-template-columns: 1fr;
        gap: 7px;
    }
    .bar-value,
    .bar-ratio {
        text-align: left;
    }
    .section-title {
        display: block;
    }
}
@media print {
    body {
        background: #ffffff;
        background-image: none;
    }
    .hero,
    .metric-card,
    .chart-card,
    .insights,
    .report-section {
        box-shadow: none;
    }
}
"""


def render_gates_banner(result: dict) -> str:
    gates = result.get("gates") or {}
    if not gates.get("enabled"):
        return ""
    passed = bool(gates.get("passed"))
    tone = "gate-pass" if passed else "gate-fail"
    title = "质量门禁：通过" if passed else "质量门禁：未通过"
    failures = gates.get("failures") or []
    if failures:
        items = "".join(f"<li>{escape(str(item))}</li>" for item in failures)
        body = f"<ul>{items}</ul>"
    else:
        body = "<p>已启用门禁检查，当前无违规项。</p>"
    return f"""
<section class="gate-banner {tone}">
<h2>{escape(title)}</h2>
{body}
</section>
"""


def render_optional_table(
    title: str,
    columns: list[tuple[str, str]],
    rows: list[list[object]],
) -> str:
    if not rows:
        return ""
    return render_table(title, columns, rows)


def save_report_html(result: dict, output_path: str | Path = "code_report.html") -> Path:
    result = ensure_report_result(result)
    totals = result["totals"]
    all_totals = totals["all"]
    prod_code = totals["prod"]["code"]
    test_code = totals["test"]["code"]
    kpi_cards = [
        render_kpi_card("代码文件数", result["code_files"], "纳入统计的源代码文件", "✦", "strawberry"),
        render_kpi_card("总行数", all_totals["total"], "包含空行与注释", "Σ", "peach"),
        render_kpi_card("有效代码行数", all_totals["code"], "排除空行与注释", "</>", "mint"),
        render_kpi_card("测试代码行数", test_code, "识别为测试文件的有效代码", "★", "sky"),
        render_kpi_card(
            "\u6d4b\u8bd5\u7528\u4f8b\u6570",
            result["test_cases"],
            "\u9759\u6001\u8bc6\u522b\u7684\u6d4b\u8bd5\u7528\u4f8b\u5b9a\u4e49",
            "♡",
            "lavender",
        ),
    ]

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>项目代码量统计报告</title>
{render_report_favicon()}
<style>
{REPORT_CSS}
</style>
</head>
<body>
<main class="page" id="report-top">
<section class="hero" aria-label="报告概览">
<div class="hero-content">
<h1 class="hero-title">项目代码量统计报告</h1>
<p class="hero-subtitle">静态代码规模、模块分布、测试占比、复杂度热点与大文件风险概览</p>
<div class="hero-meta">
<div class="hero-path">{escape(str(result["root"]))}</div>
{render_repository_link(str(result.get("repository_url") or ""))}
</div>
</div>
<aside class="hero-stat">
<div class="hero-stat-label">Effective LOC</div>
<div class="hero-stat-value">{format_num(all_totals["code"])}</div>
<div class="hero-stat-note">有效代码行数</div>
</aside>
</section>
<section class="metrics">
{''.join(kpi_cards)}
</section>
<section class="dashboard-grid">
{render_donut_card(prod_code, test_code)}
{render_language_chart(build_language_chart_rows(result))}
{render_largest_files_chart(build_largest_chart_rows(result))}
</section>
{render_insights(result)}
{render_gates_banner(result)}
{render_table(
    "总览：含测试 / 排除测试 / 仅测试",
    [
        ("统计口径", "center"),
        ("代码文件数", "center"),
        ("总行数", "center"),
        ("空行数", "center"),
        ("注释行数", "center"),
        ("有效代码行数", "center"),
    ],
    build_total_rows(result),
)}
{render_table(
    "按语言统计：全部 / 排除测试 / 测试",
    [
        ("语言", "center"),
        ("全部文件", "center"),
        ("全部行", "center"),
        ("全部代码", "center"),
        ("生产代码", "center"),
        ("测试代码", "center"),
        ("测试文件", "center"),
    ],
    build_language_rows(result),
)}
{render_optional_table(
    "按模块统计",
    [
        ("模块", "center"),
        ("文件数", "center"),
        ("总行数", "center"),
        ("有效代码", "center"),
        ("占比", "center"),
    ],
    build_module_rows(result),
)}
{render_optional_table(
    "测试套件分布",
    [
        ("套件", "center"),
        ("文件数", "center"),
        ("用例数", "center"),
        ("总行数", "center"),
        ("有效代码", "center"),
        ("占比", "center"),
    ],
    build_suite_rows(result),
)}
{render_optional_table(
    f"Python 复杂度热点 Top {COMPLEXITY_HOTSPOT_LIMIT}",
    [
        ("复杂度", "center"),
        ("模块", "center"),
        ("符号", "center"),
        ("位置", "center"),
    ],
    build_complexity_rows(result),
)}
{render_optional_table(
    "项目表面（pyproject）",
    [
        ("项", "center"),
        ("值", "center"),
    ],
    build_surface_rows(result),
)}
{render_optional_table(
    "与历史快照对比",
    [
        ("指标", "center"),
        ("上次", "center"),
        ("本次", "center"),
        ("变化", "center"),
        ("变化率", "center"),
    ],
    build_delta_rows(result),
)}
</main>
</body>
</html>
"""

    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path.resolve()


def print_report(result: dict) -> None:
    result = ensure_report_result(result)
    print_total_report(result)
    print_language_report(result)
    print_module_report(result)
    print_suite_report(result)
    print_complexity_report(result)
    print_surface_report(result)
    print_delta_report(result)
    print_gates_report(result)


def open_report_html(report_path: str | Path) -> bool:
    """使用系统默认浏览器打开生成后的本地 HTML 报告。"""
    path = Path(report_path).expanduser().resolve()
    try:
        # 唯一 query 避免沿用旧会话滚动缓存；#report-top 定位报告顶部
        url = f"{path.as_uri()}?v={time.time_ns()}#report-top"
        return bool(webbrowser.open_new_tab(url))
    except (OSError, ValueError, webbrowser.Error):
        return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计当前项目代码量")
    parser.add_argument(
        "--root",
        default=".",
        metavar="PATH",
        help="待统计的项目根目录；默认使用当前工作目录",
    )
    parser.add_argument(
        "--html",
        nargs="?",
        const="code_report.html",
        default="code_report.html",
        metavar="PATH",
        help="导出 HTML 报告；默认生成项目根目录下的 code_report.html",
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const=HISTORY_DEFAULT_NAME,
        default=None,
        metavar="PATH",
        help=f"导出 JSON 快照；省略路径时默认写入 {HISTORY_DEFAULT_NAME}",
    )
    parser.add_argument(
        "--history",
        default=None,
        metavar="PATH",
        help="读取上一份 JSON 报告并生成规模变化对比",
    )
    parser.add_argument(
        "--no-complexity",
        action="store_true",
        help="跳过 Python AST 复杂度热点分析以加快扫描",
    )
    parser.add_argument(
        "--gates",
        action="store_true",
        help=(
            f"启用默认质量门禁（生产文件 >{DEFAULT_GATE_PROD_MAX_LINES} 行，"
            f"测试占比 <{DEFAULT_GATE_TEST_RATIO_MIN:.0f}%%）"
        ),
    )
    parser.add_argument(
        "--gate-prod-max-lines",
        type=int,
        default=None,
        metavar="N",
        help="生产文件总行数上限；超过则门禁失败",
    )
    parser.add_argument(
        "--gate-test-ratio-min",
        type=float,
        default=None,
        metavar="PCT",
        help="测试有效代码占比下限（百分比）；低于则门禁失败",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="生成报告后立即使用默认浏览器打开 HTML",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.root).expanduser().resolve()
    if not project_root.is_dir():
        print(f"项目目录不存在或不是目录：{project_root}", file=sys.stderr)
        return 2

    result = scan_project(project_root, analyze_complexity=not args.no_complexity)

    if args.history:
        previous = load_history_report(Path(args.history).expanduser())
        if previous is None:
            print(f"无法读取历史报告：{args.history}", file=sys.stderr)
        else:
            result["history_delta"] = compute_history_delta(result, previous)

    prod_max_lines = args.gate_prod_max_lines
    test_ratio_min = args.gate_test_ratio_min
    if args.gates:
        if prod_max_lines is None:
            prod_max_lines = DEFAULT_GATE_PROD_MAX_LINES
        if test_ratio_min is None:
            test_ratio_min = DEFAULT_GATE_TEST_RATIO_MIN
    result["gates"] = evaluate_gates(
        result,
        prod_max_lines=prod_max_lines,
        test_ratio_min=test_ratio_min,
    )

    print_report(result)

    if args.html:
        html_path = save_report_html(result, args.html)
        print(f"HTML 报告已生成：{html_path}")
        if args.open and not open_report_html(html_path):
            print(f"无法自动打开浏览器，请手动打开：{html_path}", file=sys.stderr)
            return 1
    elif args.open:
        print("未生成 HTML，无法打开浏览器。请指定 --html。", file=sys.stderr)
        return 1

    if args.json:
        json_path = save_report_json(result, args.json)
        print(f"JSON 报告已生成：{json_path}")

    gates = result.get("gates") or {}
    if gates.get("enabled") and not gates.get("passed"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
