"""Tests for count_project console table formatting."""

import count_project

from rich import box

from count_project import (
    _build_table,
    build_language_chart_rows,
    build_largest_chart_rows,
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
    assert 'class="hero-stat-label">Effective LOC</div>' in html
    assert "代码文件数" in html
    assert "测试代码行数" in html
    assert 'class="dashboard-grid"' in html
    assert 'class="donut"' in html
    assert "语言分布 Top 8" in html
    assert "最大文件 Top 10" in html
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
    assert 'class="text path"' in html


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
