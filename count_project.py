import os
import argparse
from collections import defaultdict
from html import escape
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

REPORT_WIDTH = 140

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


# =========================
# 不计入代码量的文件
# =========================

EXCLUDE_FILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
}


# =========================
# 测试目录识别规则
# =========================

TEST_DIR_NAMES = {
    "test",
    "tests",
    "__tests__",
    "spec",
    "specs",
}


# =========================
# 代码文件后缀
# =========================

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
    ".xml": "XML",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".bat": "Batch",
    ".ps1": "PowerShell",
    ".sh": "Shell",
}


# =========================
# 单行注释识别
# =========================

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
    ".xml": ["<!--"],
    ".yaml": ["#"],
    ".yml": ["#"],
    ".toml": ["#"],
    ".ini": [";", "#"],
    ".bat": ["rem", "::"],
    ".ps1": ["#"],
    ".sh": ["#"],
}


def empty_stat() -> dict:
    return {
        "files": 0,
        "total": 0,
        "blank": 0,
        "comment": 0,
        "code": 0,
    }


def add_stat(target: dict, stat: dict) -> None:
    target["files"] += 1
    target["total"] += stat["total"]
    target["blank"] += stat["blank"]
    target["comment"] += stat["comment"]
    target["code"] += stat["code"]


def _build_console():
    return Console(
        width=REPORT_WIDTH,
        highlight=False,
        color_system=None,
        force_terminal=True,
        soft_wrap=False,
        safe_box=True,
    )


def _build_table(title: str, columns: list[tuple[str, str]], rows: list[list[object]]):
    table = Table(
        title=title,
        box=box.SIMPLE_HEAD,
        show_edge=False,
        show_lines=False,
        header_style="",
        title_style="",
        title_justify="left",
        pad_edge=False,
        expand=False,
        safe_box=True,
    )
    for header, justify in columns:
        table.add_column(header, justify=justify, no_wrap=header != "文件")
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
    encodings = ["utf-8", "utf-8-sig", "gbk", "latin-1"]

    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            return ""

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


def scan_project(root: Path) -> dict:
    total_dirs = 0
    total_files = 0
    code_files = 0

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

    largest_files = []

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

            group = "test" if test_flag else "prod"

            add_stat(totals["all"], stat)
            add_stat(totals[group], stat)

            add_stat(by_language["all"][lang], stat)
            add_stat(by_language[group][lang], stat)

            largest_files.append({
                "path": str(file_path.relative_to(root)),
                "total": stat["total"],
                "code": stat["code"],
                "is_test": test_flag,
                "lang": lang,
            })

    largest_files.sort(key=lambda x: x["total"], reverse=True)

    return {
        "root": str(root),
        "total_dirs": total_dirs,
        "total_files": total_files,
        "code_files": code_files,
        "totals": totals,
        "by_language": by_language,
        "largest_files": largest_files[:30],
    }


def print_total_report(result: dict) -> None:
    totals = result["totals"]

    print("项目代码量统计报告")
    print(f"项目路径: {result['root']}")
    print(f"目录数量: {result['total_dirs']}")
    print(f"文件总数: {result['total_files']}")
    print(f"代码文件数: {result['code_files']}")

    rows = [
        ("全部代码_含测试", totals["all"]),
        ("排除测试后", totals["prod"]),
        ("仅测试代码", totals["test"]),
    ]
    print()
    _print_table(
        "总览：含测试 / 排除测试 / 仅测试",
        [
            ("统计口径", "left"),
            ("代码文件数", "right"),
            ("总行数", "right"),
            ("空行数", "right"),
            ("注释行数", "right"),
            ("有效代码行数", "right"),
        ],
        [
            [name, stat["files"], stat["total"], stat["blank"], stat["comment"], stat["code"]]
            for name, stat in rows
        ],
    )


def print_language_report(result: dict) -> None:
    by_all = result["by_language"]["all"]
    by_prod = result["by_language"]["prod"]
    by_test = result["by_language"]["test"]

    languages = sorted(
        by_all.keys(),
        key=lambda lang: by_all[lang]["total"],
        reverse=True
    )

    rows = []
    for lang in languages:
        all_stat = by_all[lang]
        prod_stat = by_prod[lang]
        test_stat = by_test[lang]
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

    print()
    _print_table(
        "按语言统计：全部 / 排除测试 / 测试",
        [
            ("语言", "left"),
            ("全部文件", "right"),
            ("全部行", "right"),
            ("全部代码", "right"),
            ("生产代码", "right"),
            ("测试代码", "right"),
            ("测试文件", "right"),
        ],
        rows,
    )


def print_largest_files(result: dict) -> None:
    rows = []
    for item in result["largest_files"]:
        file_type = "TEST" if item["is_test"] else "PROD"
        rows.append([item["total"], item["code"], file_type, item["path"]])

    print()
    _print_table(
        "最大文件 Top 30",
        [
            ("总行数", "right"),
            ("代码行", "right"),
            ("类型", "center"),
            ("文件", "left"),
        ],
        rows,
    )


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


def build_largest_rows(result: dict) -> list[list[object]]:
    return [
        [item["total"], item["code"], "TEST" if item["is_test"] else "PROD", item["path"]]
        for item in result["largest_files"]
    ]


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


def build_largest_chart_rows(result: dict, limit: int = 10) -> list[dict]:
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


def render_kpi_card(label: str, value: int, hint: str, icon: str) -> str:
    return f"""
<article class="metric-card">
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
<h2>最大文件 Top 10</h2>
<p>按文件总行数排序，提示潜在拆分风险</p>
</div>
</div>
<div class="bar-chart largest-chart">
{''.join(body)}
</div>
</article>
"""


def render_insights(result: dict) -> str:
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
    if largest_total >= 3000:
        largest_message = "存在超大文件，建议评估拆分"
        largest_tone = "risk"
    elif largest_total >= 1500:
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
<article class="insight-card insight-{tone}" title="{escape(title, quote=True)}">
<div class="insight-label">{escape(label)}</div>
<div class="insight-value">{escape(value)}</div>
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
    def align_class(justify: str) -> str:
        if justify == "right":
            return "num"
        if justify == "center":
            return "center"
        return "text"

    def column_classes(index: int) -> str:
        if index >= len(columns):
            return "text"
        header, justify = columns[index]
        classes = [align_class(justify)]
        if header == "文件":
            classes.append("path")
        return " ".join(classes)

    def render_cell(value: object, index: int) -> str:
        text = str(value)
        classes = column_classes(index)
        title_attr = ""
        if index < len(columns) and columns[index][0] == "文件":
            title_attr = f' title="{escape(text, quote=True)}"'
        if text == "TEST":
            content = '<span class="badge badge-test">TEST</span>'
        elif text == "PROD":
            content = '<span class="badge badge-prod">PROD</span>'
        else:
            content = escape(text)
        return f'<td class="{classes}"{title_attr}>{content}</td>'

    header_cells = []
    for index, (header, _justify) in enumerate(columns):
        header_cells.append(f'<th class="{column_classes(index)}">{escape(str(header))}</th>')

    body_rows = []
    for row in rows:
        cells = [render_cell(value, index) for index, value in enumerate(row)]
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

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
    --bg: #eef3f9;
    --panel: #ffffff;
    --text: #0f172a;
    --muted: #64748b;
    --line: #dbe4f0;
    --blue: #2563eb;
    --blue2: #38bdf8;
    --green: #10b981;
    --orange: #f59e0b;
    --red: #ef4444;
    --purple: #8b5cf6;
    --shadow: 0 20px 55px rgba(15, 23, 42, 0.10);
}
* {
    box-sizing: border-box;
}
body {
    margin: 0;
    background:
        linear-gradient(180deg, rgba(226, 235, 247, 0.92), var(--bg) 360px),
        var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    font-size: 15px;
}
.page {
    width: min(1280px, calc(100% - 48px));
    margin: 32px auto 56px;
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
    box-shadow: var(--shadow);
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
.hero-path {
    display: inline-flex;
    max-width: 100%;
    padding: 9px 12px;
    color: rgba(255, 255, 255, 0.88);
    background: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 999px;
    overflow-wrap: anywhere;
}
.hero-stat {
    align-self: end;
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
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
    margin-top: 18px;
}
.metric-card,
.chart-card,
.report-section,
.insights {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 18px;
    box-shadow: 0 16px 38px rgba(15, 23, 42, 0.07);
}
.metric-card {
    padding: 18px;
    transition: transform 160ms ease, box-shadow 160ms ease;
}
.metric-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 22px 44px rgba(15, 23, 42, 0.10);
}
.metric-top {
    display: flex;
    align-items: center;
    gap: 10px;
}
.metric-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    color: var(--blue);
    background: #e8f1ff;
    border-radius: 999px;
    font-weight: 800;
}
.metric-label,
.meta-label {
    color: var(--muted);
    font-size: 13px;
}
.metric-value {
    margin-top: 14px;
    font-size: 30px;
    font-weight: 800;
    line-height: 1;
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
    background: conic-gradient(var(--orange) 0deg var(--test-deg), var(--blue) var(--test-deg) 360deg);
    box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.08);
}
.donut-hole {
    display: grid;
    place-items: center;
    width: 126px;
    height: 126px;
    background: #ffffff;
    border-radius: 999px;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
}
.donut-value {
    font-size: 30px;
    font-weight: 800;
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
    color: var(--muted);
}
.legend-item strong,
.legend-item em {
    color: var(--text);
    font-style: normal;
    font-variant-numeric: tabular-nums;
}
.legend-dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
}
.legend-prod {
    background: var(--blue);
}
.legend-test {
    background: var(--orange);
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
    color: #334155;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.bar-track {
    height: 10px;
    overflow: hidden;
    background: #e7edf6;
    border-radius: 999px;
}
.bar-fill {
    height: 100%;
    background: linear-gradient(90deg, rgba(37, 99, 235, 0.48), rgba(37, 99, 235, 0.92));
    border-radius: inherit;
}
.bar-fill-primary {
    background: linear-gradient(90deg, var(--blue), var(--blue2));
}
.bar-fill-file {
    background: linear-gradient(90deg, var(--green), var(--blue2));
}
.bar-value,
.bar-ratio {
    text-align: right;
    color: #334155;
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
    color: #1e293b;
    font-weight: 650;
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
    background: #f8fafc;
    border: 1px solid var(--line);
    border-radius: 14px;
}
.insight-label {
    color: var(--muted);
    font-size: 13px;
}
.insight-value {
    margin-top: 8px;
    font-size: 23px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
}
.insight-card p {
    margin: 10px 0 0;
    color: #475569;
    line-height: 1.55;
}
.insight-good {
    border-color: rgba(16, 185, 129, 0.26);
    background: #f0fdf8;
}
.insight-watch {
    border-color: rgba(245, 158, 11, 0.28);
    background: #fffbeb;
}
.insight-risk {
    border-color: rgba(239, 68, 68, 0.26);
    background: #fff1f2;
}
.insight-neutral {
    border-color: rgba(37, 99, 235, 0.18);
    background: #eff6ff;
}
.report-section {
    margin-top: 18px;
    padding: 20px;
}
.table-wrap {
    overflow-x: auto;
    border: 1px solid var(--line);
    border-radius: 12px;
}
table {
    width: 100%;
    min-width: 720px;
    border-collapse: collapse;
}
th,
td {
    padding: 11px 13px;
    border-bottom: 1px solid var(--line);
    white-space: nowrap;
    vertical-align: top;
    font-variant-numeric: tabular-nums;
}
th {
    color: #334155;
    background: #eef5fb;
    font-weight: 700;
}
tbody tr:hover {
    background: #f8fbff;
}
tr:last-child td {
    border-bottom: none;
}
.text {
    text-align: left;
}
.num {
    text-align: right;
}
.center {
    text-align: center;
}
.path {
    min-width: 260px;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
    line-height: 1.45;
}
.badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 46px;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
    line-height: 1.2;
    letter-spacing: 0;
}
.badge-test {
    color: #9a3412;
    background: #ffedd5;
    border: 1px solid #fdba74;
}
.badge-prod {
    color: #1d4ed8;
    background: #dbeafe;
    border: 1px solid #93c5fd;
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
        margin-top: 18px;
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


def save_report_html(result: dict, output_path: str | Path = "code_report.html") -> Path:
    totals = result["totals"]
    all_totals = totals["all"]
    prod_code = totals["prod"]["code"]
    test_code = totals["test"]["code"]
    kpi_cards = [
        render_kpi_card("代码文件数", result["code_files"], "纳入统计的源代码文件", "#"),
        render_kpi_card("总行数", all_totals["total"], "包含空行与注释", "Σ"),
        render_kpi_card("有效代码行数", all_totals["code"], "排除空行与注释", "</>"),
        render_kpi_card("测试代码行数", test_code, "识别为测试文件的有效代码", "T"),
    ]

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>项目代码量统计报告</title>
<style>
{REPORT_CSS}
</style>
</head>
<body>
<main class="page">
<section class="hero">
<div class="hero-content">
<h1 class="hero-title">项目代码量统计报告</h1>
<p class="hero-subtitle">静态代码规模、语言分布、测试占比与大文件风险概览</p>
<div class="hero-path">{escape(str(result["root"]))}</div>
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
{render_table(
    "总览：含测试 / 排除测试 / 仅测试",
    [
        ("统计口径", "left"),
        ("代码文件数", "right"),
        ("总行数", "right"),
        ("空行数", "right"),
        ("注释行数", "right"),
        ("有效代码行数", "right"),
    ],
    build_total_rows(result),
)}
{render_table(
    "按语言统计：全部 / 排除测试 / 测试",
    [
        ("语言", "left"),
        ("全部文件", "right"),
        ("全部行", "right"),
        ("全部代码", "right"),
        ("生产代码", "right"),
        ("测试代码", "right"),
        ("测试文件", "right"),
    ],
    build_language_rows(result),
)}
{render_table(
    "最大文件 Top 30",
    [
        ("总行数", "right"),
        ("代码行", "right"),
        ("类型", "center"),
        ("文件", "left"),
    ],
    build_largest_rows(result),
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
    print_total_report(result)
    print_language_report(result)
    print_largest_files(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计当前项目代码量")
    parser.add_argument(
        "--html",
        nargs="?",
        const="code_report.html",
        default="code_report.html",
        metavar="PATH",
        help="导出 HTML 报告；默认生成项目根目录下的 code_report.html",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    project_root = Path.cwd()
    result = scan_project(project_root)
    print_report(result)
    html_path = save_report_html(result, args.html)
