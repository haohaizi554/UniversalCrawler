from pathlib import Path
from collections import defaultdict
import os

EXCLUDE_DIRS = {
    ".git",
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

        # 阻止进入 .git / .venv / node_modules 等目录
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

    print("=" * 100)
    print("项目代码量统计报告")
    print("=" * 100)
    print(f"项目路径: {result['root']}")
    print(f"目录数量: {result['total_dirs']}")
    print(f"文件总数: {result['total_files']}")
    print(f"代码文件数: {result['code_files']}")

    print()
    print("-" * 100)
    print("总览：含测试 / 排除测试 / 仅测试")
    print("-" * 100)

    print(
        f"{'统计口径':<18}"
        f"{'代码文件数':>12}"
        f"{'总行数':>12}"
        f"{'空行数':>12}"
        f"{'注释行数':>12}"
        f"{'有效代码行数':>14}"
    )

    print("-" * 100)

    rows = [
        ("全部代码_含测试", totals["all"]),
        ("排除测试后", totals["prod"]),
        ("仅测试代码", totals["test"]),
    ]

    for name, stat in rows:
        print(
            f"{name:<18}"
            f"{stat['files']:>12}"
            f"{stat['total']:>12}"
            f"{stat['blank']:>12}"
            f"{stat['comment']:>12}"
            f"{stat['code']:>14}"
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

    print()
    print("-" * 100)
    print("按语言统计：全部 / 排除测试 / 测试")
    print("-" * 100)

    print(
        f"{'语言':<18}"
        f"{'全部文件':>10}"
        f"{'全部行':>10}"
        f"{'全部代码':>10}"
        f"{'生产代码':>10}"
        f"{'测试代码':>10}"
        f"{'测试文件':>10}"
    )

    print("-" * 100)

    for lang in languages:
        all_stat = by_all[lang]
        prod_stat = by_prod[lang]
        test_stat = by_test[lang]
    
        print(
            f"{lang:<18}"
            f"{all_stat['files']:>10}"
            f"{all_stat['total']:>10}"
            f"{all_stat['code']:>10}"
            f"{prod_stat['code']:>10}"
            f"{test_stat['code']:>10}"
            f"{test_stat['files']:>10}"
        )


def print_largest_files(result: dict) -> None:
    print()
    print("-" * 100)
    print("最大文件 Top 30")
    print("-" * 100)

    print(
        f"{'总行数':>10}"
        f"{'代码行':>10}"
        f"{'类型':>10}"
        f"  文件"
    )

    print("-" * 100)

    for item in result["largest_files"]:
        file_type = "TEST" if item["is_test"] else "PROD"

        print(
            f"{item['total']:>10}"
            f"{item['code']:>10}"
            f"{file_type:>10}"
            f"  {item['path']}"
        )


def print_report(result: dict) -> None:
    print_total_report(result)
    print_language_report(result)
    print_largest_files(result)


if __name__ == "__main__":
    project_root = Path.cwd()
    result = scan_project(project_root)
    print_report(result)
