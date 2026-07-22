"""Tests for count_project console table formatting."""

import json

import count_project

from rich import box

from count_project import (
    _build_table,
    build_language_chart_rows,
    build_largest_chart_rows,
    classify_module,
    classify_test_suite,
    compute_history_delta,
    count_test_cases,
    evaluate_gates,
    main,
    normalize_repository_url,
    parse_args,
    scan_project,
    save_report_html,
)


def test_build_table_uses_rich_table_when_available():
    table = _build_table(
        "Summary",
        [("Scope", "left"), ("Files", "right")],
        [["All code", 517]],
    )

    assert table.title == "Summary"
    assert table.box == box.SIMPLE_HEAD
    assert table.show_edge is False
    assert table.safe_box is True
    assert len(table.columns) == 2
    assert table.row_count == 1
    assert table.columns[0].header == "Scope"


def test_save_report_html_writes_escaped_report(tmp_path, monkeypatch):
    icon_path = tmp_path / "analytics.ico"
    icon_path.write_bytes(b"\x00\x00\x01\x00")
    monkeypatch.setattr("count_project.resolve_report_icon_path", lambda: icon_path)

    result = {
        "root": "D:/demo/<project>",
        "repository_url": "https://github.com/example/demo-project",
        "total_dirs": 1,
        "total_files": 2,
        "code_files": 1,
        "test_cases": 23,
        "totals": {
            "all": {"files": 2, "total": 15, "blank": 1, "comment": 4, "code": 10},
            "prod": {"files": 1, "total": 10, "blank": 1, "comment": 2, "code": 7},
            "test": {"files": 1, "total": 5, "blank": 0, "comment": 2, "code": 3},
        },
        "by_language": {
            "all": {
                "Python": {"files": 1, "total": 10, "blank": 1, "comment": 2, "code": 7},
                "JavaScript": {"files": 1, "total": 5, "blank": 0, "comment": 2, "code": 3},
            },
            "prod": {"Python": {"files": 1, "total": 10, "blank": 1, "comment": 2, "code": 7}},
            "test": {"JavaScript": {"files": 1, "total": 5, "blank": 0, "comment": 2, "code": 3}},
        },
        "largest_files": [
            {"total": 10, "code": 7, "is_test": False, "path": "app/<main>.py"},
            {"total": 5, "code": 3, "is_test": True, "path": "tests/<main>_test.py"},
        ],
    }

    output_path = save_report_html(result, tmp_path / "nested" / "report.html")

    assert output_path.is_absolute()
    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "<title>项目代码量统计报告</title>" in html
    assert 'rel="icon" type="image/x-icon"' in html
    assert 'href="data:image/x-icon;base64,AAABAA=="' in html
    assert 'class="hero"' in html
    assert 'id="report-top"' in html
    assert "scrollRestoration" not in html
    assert "window.scrollTo(0, 0)" not in html
    assert "min-height: 260px" in html
    assert "margin: 32px auto 48px;" in html
    assert "blur(18px)" not in html
    assert "rgba(255, 255, 255, 0.28)" not in html
    assert 'class="hero-stat-label">Effective LOC</div>' in html
    assert "代码文件数" in html
    assert "测试代码行数" in html
    assert "\u6d4b\u8bd5\u7528\u4f8b\u6570" in html
    assert "\u9759\u6001\u8bc6\u522b\u7684\u6d4b\u8bd5\u7528\u4f8b\u5b9a\u4e49" in html
    assert 'class="dashboard-grid"' in html
    assert 'class="donut"' in html
    assert "语言分布 Top 8" in html
    assert "最大文件 Top 5" in html
    assert 'class="insights"' in html
    assert "D:/demo/&lt;project&gt;" in html
    assert 'class="hero-repository"' in html
    assert 'href="https://github.com/example/demo-project"' in html
    assert 'aria-label="打开 GitHub 仓库：github.com/example/demo-project"' in html
    assert "github.com/example/demo-project" in html
    assert "width: fit-content;" in html
    assert "app/&lt;main&gt;.py" in html
    assert "tests/&lt;main&gt;_test.py" in html
    assert '<span class="badge badge-prod">PROD</span>' in html
    assert '<span class="badge badge-test">TEST</span>' in html
    assert "按模块统计" in html
    assert "规模估算 / LLM 预算" not in html
    assert html.count("最大文件 Top 5") == 1


def test_report_icon_resolves_from_installed_data_directory(tmp_path, monkeypatch):
    install_root = tmp_path / "installed"
    install_root.mkdir()
    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    installed_icon = install_root / "share" / "ucrawl" / "analytics.ico"
    installed_icon.parent.mkdir(parents=True)
    installed_icon.write_bytes(b"\x00\x00\x01\x00")

    monkeypatch.setattr(count_project, "__file__", str(install_root / "count_project.py"))
    monkeypatch.chdir(empty_cwd)

    assert count_project.resolve_report_icon_path() == installed_icon.resolve()


def test_report_icon_resolution_tolerates_missing_python_user_base(tmp_path, monkeypatch):
    install_root = tmp_path / "embedded"
    installed_icon = install_root / "share" / "ucrawl" / "analytics.ico"
    installed_icon.parent.mkdir(parents=True)
    installed_icon.write_bytes(b"\x00\x00\x01\x00")

    monkeypatch.setattr(count_project, "__file__", str(install_root / "count_project.py"))
    monkeypatch.setattr(count_project.site, "USER_BASE", None)

    assert count_project.resolve_report_icon_path() == installed_icon.resolve()


def test_normalize_repository_url_supports_github_https_and_ssh():
    assert (
        normalize_repository_url("https://github.com/example/demo-project.git")
        == "https://github.com/example/demo-project"
    )
    assert (
        normalize_repository_url("git@github.com:example/demo-project.git")
        == "https://github.com/example/demo-project"
    )
    assert (
        normalize_repository_url("ssh://git@github.com/example/demo-project.git")
        == "https://github.com/example/demo-project"
    )


def test_parse_args_generates_html_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["count_project.py"])

    args = parse_args()

    assert args.html == "code_report.html"


def test_parse_args_help_does_not_crash(capsys):
    try:
        parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected --help to exit")

    help_text = capsys.readouterr().out
    assert "--json" in help_text
    assert "--history" in help_text
    assert "--gates" in help_text
    assert "--no-complexity" in help_text
    assert "10%" in help_text


def test_main_generates_report_and_opens_it(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    report_path = tmp_path / "reports" / "code.html"
    opened_paths = []

    monkeypatch.setattr("count_project.print_report", lambda _result: None)
    monkeypatch.setattr(
        "count_project.open_report_html",
        lambda path: opened_paths.append(path) or True,
    )

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--html",
            str(report_path),
            "--open",
        ]
    )

    assert exit_code == 0
    assert report_path.exists()
    assert opened_paths == [report_path.resolve()]


def test_scan_project_excludes_xml_from_code_statistics(tmp_path):
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "coverage.xml").write_text("<coverage>\n  <file />\n</coverage>\n", encoding="utf-8")

    result = scan_project(tmp_path)

    assert result["total_files"] == 2
    assert result["code_files"] == 1
    assert "XML" not in result["by_language"]["all"]
    assert [item["path"] for item in result["largest_files"]] == ["main.py"]


def test_scan_project_excludes_graphify_output_directory(tmp_path):
    """Graphify 生成物不应污染项目文件数、代码量和大文件榜单。"""
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    generated_dir = tmp_path / "graphify-out"
    nested_dir = generated_dir / "cache"
    nested_dir.mkdir(parents=True)
    (generated_dir / "run_ast.py").write_text(
        "print('generated')\n",
        encoding="utf-8",
    )
    (nested_dir / "stat-index.json").write_text(
        '{"generated": true}\n',
        encoding="utf-8",
    )

    result = scan_project(tmp_path)

    assert result["total_dirs"] == 0
    assert result["total_files"] == 1
    assert result["code_files"] == 1
    assert result["totals"]["all"]["files"] == 1
    assert [item["path"] for item in result["largest_files"]] == ["main.py"]


def test_scan_project_counts_python_test_case_definitions(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        """
def test_module_case():
    pass

async def test_async_case():
    pass

def helper():
    pass

class TestFeature:
    def test_method_case(self):
        pass
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "def test_named_production_helper():\n    pass\n",
        encoding="utf-8",
    )

    result = scan_project(tmp_path)

    assert result["test_cases"] == 3


def test_count_test_cases_reads_utf8_bom_files(tmp_path):
    path = tmp_path / "test_bom.py"
    path.write_bytes(
        b"\xef\xbb\xbfdef test_ok():\n    assert True\n"
    )

    assert count_test_cases(path) == 1


def test_count_test_cases_expands_parametrize(tmp_path):
    path = tmp_path / "test_params.py"
    path.write_text(
        """
import pytest

CASES = [1, 2, 3]

@pytest.mark.parametrize("value", CASES)
def test_from_name(value):
    assert value

@pytest.mark.parametrize("value", ["a", "b"])
@pytest.mark.parametrize("flag", [True, False])
def test_stacked(value, flag):
    assert value or flag
""".lstrip(),
        encoding="utf-8",
    )

    # 3 + (2 * 2) = 7
    assert count_test_cases(path) == 7


def test_chart_rows_compute_widths_and_names():
    result = {
        "totals": {
            "all": {"files": 3, "total": 30, "blank": 0, "comment": 0, "code": 30},
            "prod": {"files": 2, "total": 20, "blank": 0, "comment": 0, "code": 20},
            "test": {"files": 1, "total": 10, "blank": 0, "comment": 0, "code": 10},
        },
        "by_language": {
            "all": {
                "Python": {"files": 1, "total": 20, "blank": 0, "comment": 0, "code": 20},
                "Shell": {"files": 1, "total": 1, "blank": 0, "comment": 0, "code": 1},
            },
            "prod": {},
            "test": {},
        },
        "largest_files": [
            {"total": 100, "code": 80, "is_test": False, "path": "app\\main.py"},
            {"total": 25, "code": 20, "is_test": True, "path": "tests\\main_test.py"},
        ],
    }

    language_rows = build_language_chart_rows(result)
    largest_rows = build_largest_chart_rows(result)

    assert language_rows[0]["lang"] == "Python"
    assert language_rows[0]["width"] == 100
    assert language_rows[1]["width"] >= 3
    assert largest_rows[0]["name"] == "main.py"
    assert largest_rows[0]["width"] == 100
    assert largest_rows[1]["type"] == "TEST"


def test_classify_module_and_suite():
    assert classify_module("app/web/controller.py") == "app/web"
    assert classify_module("shared/localization.py") == "shared"
    assert classify_module("unknown/x.py") == "other"
    assert classify_test_suite("tests/unit/test_a.py", is_test=True) == "unit"
    assert classify_test_suite("tests/custom/test_a.py", is_test=True) == "other"
    assert classify_test_suite("app/main.py", is_test=False) == ""


def test_evaluate_gates_and_history_delta(tmp_path):
    current = {
        "root": str(tmp_path),
        "code_files": 2,
        "test_cases": 4,
        "totals": {
            "all": {"code": 100},
            "prod": {"code": 90},
            "test": {"code": 10},
        },
        "largest_files": [
            {"path": "app/big.py", "total": 4000, "code": 3000, "is_test": False},
            {"path": "tests/a.py", "total": 10, "code": 8, "is_test": True},
        ],
    }
    previous = {
        "root": str(tmp_path),
        "code_files": 1,
        "test_cases": 2,
        "totals": {
            "all": {"code": 80},
            "prod": {"code": 70},
            "test": {"code": 10},
        },
        "largest_files": [
            {"path": "app/old.py", "total": 100, "code": 80, "is_test": False},
        ],
    }

    gates = evaluate_gates(current, prod_max_lines=3000, test_ratio_min=20.0)
    assert gates["enabled"] is True
    assert gates["passed"] is False
    assert any("生产文件超过" in item for item in gates["failures"])
    assert any("测试代码占比" in item for item in gates["failures"])

    delta = compute_history_delta(current, previous)
    assert delta["metrics"][0]["delta"] == 20
    assert "app/big.py" in delta["new_top_files"]
    assert "app/old.py" in delta["left_top_files"]


def test_scan_project_includes_extended_sections(tmp_path):
    app_dir = tmp_path / "app" / "web"
    app_dir.mkdir(parents=True)
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (app_dir / "controller.py").write_text(
        "def run(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    for i in range(3):\n"
        "        if i:\n"
        "            return i\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (tests_dir / "test_controller.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        'dependencies = ["rich"]\n[project.scripts]\ndemo = "demo:main"\n',
        encoding="utf-8",
    )

    result = scan_project(tmp_path)

    assert "app/web" in result["by_module"]
    assert "unit" in result["by_suite"]
    assert result["by_suite"]["unit"]["test_cases"] == 1
    assert result["complexity_hotspots"]
    assert result["project_surface"]["package_name"] == "demo"


def test_main_writes_json_and_fails_gates(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("print('x')\n" * 20, encoding="utf-8")
    html_path = tmp_path / "report.html"
    json_path = tmp_path / "report.json"
    monkeypatch.setattr("count_project.print_report", lambda _result: None)

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--html",
            str(html_path),
            "--json",
            str(json_path),
            "--gate-test-ratio-min",
            "50",
        ]
    )

    assert exit_code == 3
    assert html_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["gates"]["enabled"] is True
    assert payload["gates"]["passed"] is False
