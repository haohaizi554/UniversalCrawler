"""Web 启动脚本注入的参数解析与执行边界测试。"""

from __future__ import annotations

from pathlib import Path

from cli import script_runner


def test_missing_script_returns_failure_without_importing(capsys) -> None:
    assert script_runner.run_injected_script("missing-script.py", object()) == 1
    assert "脚本不存在" in capsys.readouterr().err


def test_script_requires_main_function(tmp_path: Path, capsys) -> None:
    script = tmp_path / "without_main.py"
    script.write_text("VALUE = 1\n", encoding="utf-8")

    assert script_runner.run_injected_script(str(script), object()) == 1
    assert "必须定义 main" in capsys.readouterr().err


def test_script_receives_controller_and_converted_arguments(tmp_path: Path) -> None:
    script = tmp_path / "automation.py"
    script.write_text(
        "def main(controller, **kwargs):\n"
        "    controller.update(kwargs)\n"
        "    return 9\n",
        encoding="utf-8",
    )
    controller: dict[str, object] = {}

    result = script_runner.run_injected_script(
        str(script),
        controller,
        **script_runner.parse_kv_args(["count=5", "ratio=1.5", "enabled=true", "name=demo"]),
    )

    assert result == 9
    assert controller == {"count": 5, "ratio": 1.5, "enabled": True, "name": "demo"}


def test_non_integer_script_result_maps_to_success(tmp_path: Path) -> None:
    script = tmp_path / "automation.py"
    script.write_text("def main(controller, **kwargs):\n    return 'done'\n", encoding="utf-8")

    assert script_runner.run_injected_script(str(script), object()) == 0


def test_unloadable_script_spec_returns_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(script_runner.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(script_runner.importlib.util, "spec_from_file_location", lambda *_args: None)

    assert script_runner.run_injected_script("broken.py", object()) == 1
    assert "无法加载脚本" in capsys.readouterr().err


def test_script_cli_parser_keeps_unknown_web_arguments() -> None:
    args = script_runner.parse_script_args(
        [
            "--script",
            "automation.py",
            "--script-arg",
            "count=5",
            "--script-strict",
            "--script-delay",
            "0.25",
            "--port",
            "8000",
        ]
    )

    assert args.script == "automation.py"
    assert args.script_arg == ["count=5"]
    assert args.script_strict is True
    assert args.script_after_ready is True
    assert args.script_delay == 0.25


def test_key_value_parser_ignores_invalid_items_and_splits_once() -> None:
    assert script_runner.parse_kv_args(["invalid", "token=a=b", "disabled=false"]) == {
        "token": "a=b",
        "disabled": False,
    }
