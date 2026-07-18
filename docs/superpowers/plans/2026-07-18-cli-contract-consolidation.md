# CLI Contract Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace duplicated, hard-coded CLI definitions with a registry-driven command contract, clarify download and timeout semantics, separate CLI/SDK from GUI imports, distinguish process exit states, and split the interactive command by responsibility.

**Architecture:** `cli.main` builds one parser from a validated plugin-derived platform catalog. Generic and platform-scoped commands call the same argument builders and handlers, while shared runtimes return semantic outcomes that the CLI maps to stable process exit codes. The public `ucrawl` package remains the SDK surface, `cli` becomes a lightweight command implementation package, and the interactive workflow is decomposed into catalog, configuration, prompt, and orchestration modules.

**Tech Stack:** Python 3.10+, stdlib `argparse`, existing plugin registry and shared runtimes, `pytest`, `unittest.mock`, Ruff.

## Global Constraints

- Keep `argparse`; add no command-framework dependency.
- Platform IDs and aliases must come from the plugin registry, never a CLI-maintained platform list.
- Keep JSON result shapes and stdout/stderr separation stable.
- Use exit codes `0`, `1`, `2`, `124`, and `130` for success, runtime error, usage error, timeout, and cancellation.
- `download` is stateless direct URL download; do not add persisted search-result state.
- `scan` is top-level only.
- `import cli` and `import ucrawl` must not import any `app.ui` module.
- Preserve unrelated dirty-worktree changes and do not stage them.
- Follow TDD for every behavior change: add a focused failing test, verify the expected failure, implement minimally, then run the affected test set.

---

## File Structure

### New files

- `shared/version.py`: single UI-free version constant.
- `cli/exit_codes.py`: process exit enum and semantic status mapping.
- `cli/platform_catalog.py`: validated immutable projection of plugin metadata for argparse.
- `cli/interactive/__init__.py`: interactive implementation package marker.
- `cli/interactive/catalog.py`: platform-specific guide copy and generic fallback.
- `cli/interactive/configuration.py`: cookie/config/save-directory helpers.
- `cli/interactive/prompts.py`: terminal input and presentation helpers.
- `cli/interactive/workflow.py`: interactive state loop and runner orchestration.
- `tests/unit/cli/test_exit_codes.py`: exit mapping unit contract.
- `tests/unit/cli/test_platform_catalog.py`: dynamic platform and collision contract.
- `tests/contract/cli/test_public_package_boundaries.py`: UI-free CLI/SDK import boundary.

### Modified files

- `app/core/plugins/base.py`: add generic immutable alias metadata.
- `app/core/plugins/definitions.py`: declare built-in aliases.
- `cli/__init__.py`: reduce to the CLI package/version boundary.
- `ucrawl/__init__.py`: remove GUI strategy export.
- `cli/script_runner.py`: import SDK from the public SDK package.
- `cli/main.py`: build and dispatch one registry-driven parser.
- `cli/commands/platform_base.py`: register dynamic platform `search`/`download` wrappers only.
- `shared/search_command_runtime.py`: shared parser fields, timeout normalization, semantic outcomes.
- `shared/download_command_runtime.py`: direct URL parser contract and semantic outcomes.
- `cli/commands/search.py`: map semantic outcomes to process exit codes.
- `cli/commands/download.py`: map semantic outcomes to process exit codes.
- `cli/commands/scan.py`: return usage/runtime/status-specific exit codes.
- `cli/commands/platforms.py`: return usage exit code for unknown `--describe`.
- `cli/commands/interactive.py`: become a thin parser/dependency adapter.
- `entry/interactive_entry.py`: continue using the canonical thin command adapter.
- `tests/unit/cli/test_main.py`: parser, alias, timeout, interrupt, and dispatch contract.
- `tests/unit/cli/test_interactive_command.py`: import helpers from their new owners.
- Existing search/download runtime tests under `tests/unit/cli/`: update expected field names and outcomes.
- `tests/contract/entry/test_cross_entry_consistency.py`: update direct-download CLI shape where asserted.
- `tests/contract/cross_interface/test_cli_sdk_api.py`: update package and dynamic-platform expectations.
- `README.md`, `README_EN.md`, `cli/README.md`, `docs/cli/cli-guide.md`, `docs/cli/python-sdk-guide.md`, `docs/cli/README.md`, `docs/guides/ai-skill-guide.md`, `cli/skill/SKILL.md`, and `cli/skill/examples/*.py`: publish the canonical syntax.

### Deleted files

- `cli/commands/_alias.py`: production-orphan alias implementation.
- `tests/unit/cli/commands/test_alias.py`: tests that only preserve the orphan.
- `tests/contract/cli/test_public_module_aliases.py`: obsolete polluted-boundary contract, replaced by the new package-boundary contract.

---

### Task 1: Establish the Dynamic Platform Catalog

**Files:**
- Modify: `app/core/plugins/base.py`
- Modify: `app/core/plugins/definitions.py`
- Create: `cli/platform_catalog.py`
- Create: `tests/unit/cli/test_platform_catalog.py`
- Test: `tests/unit/app/core/plugins/test_registry.py`

**Interfaces:**
- Consumes: `registry.get_all_plugins()` and plugin fields `id`, `name`, `sort_order`.
- Produces:
  - `BasePlugin.aliases: tuple[str, ...]`
  - `CliPlatform(id: str, name: str, aliases: tuple[str, ...])`
  - `load_cli_platforms(plugin_registry=None) -> tuple[CliPlatform, ...]`
  - `platform_ids(platforms) -> tuple[str, ...]`

- [ ] **Step 1: Write failing catalog tests**

```python
from types import SimpleNamespace

import pytest

from cli.platform_catalog import load_cli_platforms, platform_ids


class FakeRegistry:
    def __init__(self, plugins):
        self._plugins = plugins

    def get_all_plugins(self):
        return list(self._plugins)


def _plugin(pid, name, order, aliases=()):
    return SimpleNamespace(id=pid, name=name, sort_order=order, aliases=aliases)


def test_catalog_is_sorted_and_includes_external_plugin_aliases():
    catalog = load_cli_platforms(
        FakeRegistry(
            [
                _plugin("third", "Third", 30, ("t3",)),
                _plugin("first", "First", 10, ("f1",)),
            ]
        )
    )

    assert platform_ids(catalog) == ("first", "third")
    assert catalog[1].aliases == ("t3",)


@pytest.mark.parametrize(
    "plugins",
    [
        [_plugin("one", "One", 1, ("shared",)), _plugin("two", "Two", 2, ("shared",))],
        [_plugin("one", "One", 1, ("two",)), _plugin("two", "Two", 2)],
        [_plugin("Bad Name", "Bad", 1)],
    ],
)
def test_catalog_rejects_invalid_or_conflicting_command_names(plugins):
    with pytest.raises(ValueError):
        load_cli_platforms(FakeRegistry(plugins))
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/cli/test_platform_catalog.py -q
```

Expected: collection/import failure because `cli.platform_catalog` does not exist.

- [ ] **Step 3: Add plugin aliases and the catalog implementation**

Add to `BasePlugin`:

```python
aliases: tuple[str, ...] = ()
```

Add to the five built-in definitions:

```python
class DouyinPlugin(BasePlugin):
    aliases = ("dy",)

class XiaohongshuPlugin(BasePlugin):
    aliases = ("xhs",)

class BilibiliPlugin(BasePlugin):
    aliases = ("bili", "bl")

class KuaishouPlugin(BasePlugin):
    aliases = ("ks",)

class MissAVPlugin(BasePlugin):
    aliases = ("miss",)
```

Create `cli/platform_catalog.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_COMMAND_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class CliPlatform:
    id: str
    name: str
    aliases: tuple[str, ...] = ()


def load_cli_platforms(plugin_registry=None) -> tuple[CliPlatform, ...]:
    if plugin_registry is None:
        from app.core.plugin_registry import registry

        plugin_registry = registry

    result: list[CliPlatform] = []
    claimed: dict[str, str] = {}
    plugins = sorted(
        plugin_registry.get_all_plugins(),
        key=lambda plugin: (getattr(plugin, "sort_order", 1000), plugin.id),
    )
    for plugin in plugins:
        pid = str(plugin.id).strip().lower()
        aliases = tuple(str(value).strip().lower() for value in getattr(plugin, "aliases", ()))
        names = (pid, *aliases)
        if any(not value or not _COMMAND_NAME.fullmatch(value) for value in names):
            raise ValueError(f"非法 CLI 平台名称: {names!r}")
        for value in names:
            previous = claimed.get(value)
            if previous is not None:
                raise ValueError(f"CLI 平台名称冲突: {value} ({previous}, {pid})")
            claimed[value] = pid
        result.append(CliPlatform(id=pid, name=str(plugin.name), aliases=aliases))
    return tuple(result)


def platform_ids(platforms: Iterable[CliPlatform]) -> tuple[str, ...]:
    return tuple(platform.id for platform in platforms)
```

- [ ] **Step 4: Run catalog and registry tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/cli/test_platform_catalog.py tests/unit/app/core/plugins/test_registry.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the catalog task**

```powershell
git add app/core/plugins/base.py app/core/plugins/definitions.py cli/platform_catalog.py tests/unit/cli/test_platform_catalog.py
git commit -m "refactor(cli): derive platform catalog from plugins"
```

---

### Task 2: Define Exit Codes and Restore Public Package Boundaries

**Files:**
- Create: `shared/version.py`
- Create: `cli/exit_codes.py`
- Modify: `cli/__init__.py`
- Modify: `ucrawl/__init__.py`
- Modify: `cli/script_runner.py`
- Create: `tests/unit/cli/test_exit_codes.py`
- Delete: `tests/contract/cli/test_public_module_aliases.py`
- Create: `tests/contract/cli/test_public_package_boundaries.py`

**Interfaces:**
- Produces:
  - `shared.version.__version__: str`
  - `CliExitCode(IntEnum)`
  - `exit_code_for_status(status: str) -> CliExitCode`
- Package promise:
  - `cli` exports only `__version__`.
  - `ucrawl` exports SDK and non-GUI selection contracts.

- [ ] **Step 1: Write failing exit-code and import-boundary tests**

Create `tests/unit/cli/test_exit_codes.py`:

```python
import pytest

from cli.exit_codes import CliExitCode, exit_code_for_status


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", CliExitCode.OK),
        ("error", CliExitCode.ERROR),
        ("usage", CliExitCode.USAGE),
        ("timeout", CliExitCode.TIMEOUT),
        ("cancelled", CliExitCode.CANCELLED),
    ],
)
def test_statuses_map_to_stable_process_codes(status, expected):
    assert exit_code_for_status(status) is expected


def test_unknown_status_is_a_runtime_error():
    assert exit_code_for_status("unexpected") is CliExitCode.ERROR
```

Replace the obsolete public-alias contract with:

```python
from __future__ import annotations

import subprocess
import sys

import cli
import ucrawl


def test_cli_package_only_exposes_version():
    assert cli.__all__ == ["__version__"]
    assert not hasattr(cli, "GUISelection")
    assert not hasattr(cli, "UcrawlSDK")


def test_sdk_package_does_not_expose_gui_selection():
    assert not hasattr(ucrawl, "GUISelection")
    assert hasattr(ucrawl, "UcrawlSDK")


def test_fresh_cli_and_sdk_imports_do_not_load_app_ui():
    probe = (
        "import sys; import cli; import ucrawl; "
        "assert not any(name == 'app.ui' or name.startswith('app.ui.') for name in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/cli/test_exit_codes.py tests/contract/cli/test_public_package_boundaries.py -q
```

Expected: missing `cli.exit_codes` plus current `GUISelection`/SDK exports fail.

- [ ] **Step 3: Implement the UI-free version and exit-code contracts**

Create `shared/version.py`:

```python
__version__ = "3.6.17"

__all__ = ["__version__"]
```

Create `cli/exit_codes.py`:

```python
from __future__ import annotations

from enum import IntEnum


class CliExitCode(IntEnum):
    OK = 0
    ERROR = 1
    USAGE = 2
    TIMEOUT = 124
    CANCELLED = 130


_STATUS_CODES = {
    "ok": CliExitCode.OK,
    "error": CliExitCode.ERROR,
    "usage": CliExitCode.USAGE,
    "timeout": CliExitCode.TIMEOUT,
    "cancelled": CliExitCode.CANCELLED,
}


def exit_code_for_status(status: str) -> CliExitCode:
    return _STATUS_CODES.get(str(status or "").lower(), CliExitCode.ERROR)
```

Replace `cli/__init__.py` with:

```python
"""UCrawl command-line implementation package."""

from shared.version import __version__

__all__ = ["__version__"]
```

Remove `GUISelection` from `ucrawl/__init__.py`, import `__version__` from `shared.version`, and retain only SDK/non-GUI exports. Change `cli/script_runner.py` from `from cli import UcrawlSDK` to `from ucrawl import UcrawlSDK`.

- [ ] **Step 4: Run package, version, and architecture tests**

Run:

```powershell
python -m pytest tests/unit/cli/test_exit_codes.py tests/contract/cli/test_public_package_boundaries.py tests/contract/cli/test_module_entrypoint.py tests/contract/entry/test_cli_entry.py tests/architecture/test_dependency_direction.py -q
```

Expected: all tests pass and fresh imports contain no `app.ui` modules.

- [ ] **Step 5: Commit the boundary task**

```powershell
git add shared/version.py cli/exit_codes.py cli/__init__.py ucrawl/__init__.py cli/script_runner.py tests/unit/cli/test_exit_codes.py tests/contract/cli/test_public_package_boundaries.py tests/contract/cli/test_public_module_aliases.py
git commit -m "refactor(cli): separate CLI SDK and GUI boundaries"
```

---

### Task 3: Consolidate Search and Dynamic Platform Commands

**Files:**
- Modify: `shared/search_command_runtime.py`
- Modify: `cli/commands/search.py`
- Modify: `cli/commands/platform_base.py`
- Modify: `cli/main.py`
- Modify: `tests/unit/cli/test_main.py`
- Modify: existing search runtime tests under `tests/unit/cli/`
- Delete: `cli/commands/_alias.py`
- Delete: `tests/unit/cli/commands/test_alias.py`

**Interfaces:**
- Consumes: `tuple[CliPlatform, ...]`.
- Produces:
  - `add_search_arguments(parser, *, platform_ids, fixed_source=None)`.
  - `resolve_command_timeout(args) -> tuple[float | None, bool]`, where the bool means the legacy alias was used.
  - `run_search_command(...) -> tuple[str, dict]`, returning semantic outcome, not a numeric exit code.
  - `add_platform_subparsers(subparsers, platforms)`.
  - `build_parser(platforms=None)`.

- [ ] **Step 1: Add failing dynamic parser and timeout tests**

Add focused tests to `tests/unit/cli/test_main.py`:

```python
from cli.platform_catalog import CliPlatform


def test_build_parser_uses_injected_external_platform():
    from cli.main import build_parser

    parser = build_parser((CliPlatform("external", "External", ("ext",)),))

    generic = parser.parse_args(["search", "--source", "external", "query"])
    scoped = parser.parse_args(["ext", "search", "query"])
    assert generic.source == scoped.source == "external"


def test_platform_search_has_the_same_business_fields_as_generic_search():
    from cli.main import build_parser

    platforms = (CliPlatform("douyin", "抖音", ("dy",)),)
    parser = build_parser(platforms)
    generic = parser.parse_args(
        ["search", "--source", "douyin", "query", "--http-timeout", "11", "--timeout", "22"]
    )
    scoped = parser.parse_args(
        ["dy", "search", "query", "--http-timeout", "11", "--timeout", "22"]
    )
    ignored = {"main_command"}
    generic_values = {k: v for k, v in vars(generic).items() if k not in ignored}
    scoped_values = {k: v for k, v in vars(scoped).items() if k not in ignored}
    assert generic_values == scoped_values


def test_platform_commands_do_not_offer_scan():
    from cli.main import build_parser

    parser = build_parser((CliPlatform("douyin", "抖音", ("dy",)),))
    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["douyin", "scan", "."])
    assert raised.value.code == 2


def test_keyboard_interrupt_returns_cancelled_code(monkeypatch):
    from cli.main import main

    monkeypatch.setattr("cli.commands.search.handle_search_command", lambda _args: (_ for _ in ()).throw(KeyboardInterrupt))
    assert main(["search", "--source", "douyin", "query"]) == 130
```

Add runtime assertions:

```python
def test_http_timeout_enters_config_and_command_timeout_enters_runner():
    args = parser.parse_args(
        ["--source", "douyin", "query", "--http-timeout", "12", "--timeout", "34"]
    )
    outcome, result = run_search_command(args, env=fake_env)
    assert outcome == "ok"
    assert fake_runner.kwargs["config"]["timeout"] == 12
    assert fake_runner.kwargs["timeout"] == 34


def test_legacy_run_timeout_warns_and_conflicts_with_timeout(capsys):
    legacy = parser.parse_args(["--source", "douyin", "query", "--run-timeout", "9"])
    assert resolve_command_timeout(legacy) == (9.0, True)

    conflict = parser.parse_args(
        ["--source", "douyin", "query", "--timeout", "8", "--run-timeout", "9"]
    )
    outcome, _result = run_search_command(conflict, env=fake_env)
    assert outcome == "usage"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/cli/test_main.py tests/unit/cli/test_defaults.py tests/unit/cli/test_selection.py -q
```

Expected: failures for missing `build_parser`, old timeout destinations, duplicate platform parser fields, and `scan`.

- [ ] **Step 3: Implement one search argument contract**

Change the search builder signature and source/timeout fields:

```python
def add_search_arguments(
    parser: argparse.ArgumentParser,
    *,
    platform_ids: tuple[str, ...],
    fixed_source: str | None = None,
) -> None:
    if fixed_source is None:
        parser.add_argument("--source", "-s", required=True, choices=platform_ids, help="平台 ID")
    else:
        parser.set_defaults(source=fixed_source)

    parser.add_argument("keyword", nargs="?", help="搜索关键词 / 链接 / 用户 ID")
    parser.add_argument("--keyword", dest="keyword_option", help="搜索关键词 / 链接 / 用户 ID（兼容旧脚本）")
    parser.add_argument("--http-timeout", type=float, default=None, help="HTTP 请求超时秒")
    parser.add_argument("--timeout", dest="command_timeout", type=float, default=None, help="整次命令超时秒")
    parser.add_argument(
        "--run-timeout",
        dest="legacy_run_timeout",
        type=float,
        default=None,
        help="已弃用；使用 --timeout",
    )
```

The remainder of the function is the complete shared search surface:

```python
    parser.add_argument("--save-dir", "-d", default=None, help="保存目录 (默认: 从配置读取，通常为 downloads)")
    parser.add_argument("--max-items", type=int, default=None, help="最大资源数")
    parser.add_argument("--max-pages", type=int, default=None, help="翻页数 (仅 bilibili)")
    parser.add_argument("--individual-only", action="store_true", help="只看单体作品 (仅 missav)")
    parser.add_argument(
        "--priority",
        choices=["中文字幕优先", "无码流出优先"],
        default=None,
        help="筛选优先级 (仅 missav)",
    )
    parser.add_argument("--proxy", default=None, help="代理 URL")
    parser.add_argument("--config", type=str, default=None, help="平台特定配置 JSON 对象")
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery)")

    selection = parser.add_argument_group("二次选择")
    selection.add_argument("--select", help="指定选中的索引")
    selection.add_argument("--exclude", help="指定排除的索引")
    selection.add_argument("--all", dest="select_all", action="store_true", help="全选")
    selection.add_argument("--first", action="store_true", help="只选第一个")
    selection.add_argument("--last", action="store_true", help="只选最后一个")
    selection.add_argument("--interactive", "-i", action="store_true", help="强制 TTY 交互式选择")
    selection.add_argument("--pipe", action="store_true", help="强制 stdin 管道选择")
    selection.add_argument("--preload-choices", help="预加载多次选择")

    output = parser.add_argument_group("输出")
    output.add_argument("--quiet", "-q", action="store_true", help="不输出 spider 日志")
    output.add_argument("--pretty", action="store_true", help="人类可读格式")
    output.add_argument("--no-download", action="store_true", help="只搜索不下载")
```

Remove the old `timeout` and `run_timeout` registrations after adding the new timeout fields.

Add timeout normalization:

```python
def resolve_command_timeout(args: argparse.Namespace) -> tuple[float | None, bool]:
    current = getattr(args, "command_timeout", None)
    legacy = getattr(args, "legacy_run_timeout", None)
    if current is not None and legacy is not None:
        raise ValueError("--timeout 与已弃用的 --run-timeout 不能同时使用")
    value = current if current is not None else legacy
    return value, legacy is not None
```

In config construction:

```python
http_timeout = getattr(args, "http_timeout", None)
if http_timeout is not None:
    convenience_body["timeout"] = http_timeout
```

In search execution, return `"usage"` for pre-run validation/selection errors, emit one legacy warning to stderr when used, pass normalized command timeout to the runner, and return `result["status"]` for runner results.

- [ ] **Step 4: Replace platform branching with uniform handler dispatch**

Implement `cli/commands/platform_base.py` around the common builders:

```python
def add_platform_subparsers(subparsers, platforms):
    from cli.commands.download import handle_download_command
    from cli.commands.search import handle_search_command
    from shared.search_command_runtime import add_search_arguments

    ids = tuple(platform.id for platform in platforms)
    for platform in platforms:
        platform_parser = subparsers.add_parser(
            platform.id,
            aliases=list(platform.aliases),
            help=f"{platform.name} 平台快捷命令",
        )
        commands = platform_parser.add_subparsers(dest="platform_command", required=True)

        search = commands.add_parser("search", help=f"在 {platform.name} 搜索")
        add_search_arguments(search, platform_ids=ids, fixed_source=platform.id)
        search.set_defaults(_handler=handle_search_command)

        download = commands.add_parser("download", help=f"从 {platform.name} 直链下载")
        from shared.download_command_runtime import add_download_arguments

        add_download_arguments(download)
        download.set_defaults(_platform=platform.id, _handler=handle_download_command)
```

Refactor `cli/main.py`:

```python
def build_parser(platforms=None) -> argparse.ArgumentParser:
    from cli.commands.download import handle_download_command
    from cli.commands.interactive import add_interactive_arguments, handle_interactive_command
    from cli.commands.platform_base import add_platform_subparsers
    from cli.commands.platforms import add_platforms_arguments, handle_platforms_command
    from cli.commands.scan import add_scan_arguments, handle_scan_command
    from cli.commands.search import handle_search_command
    from cli.platform_catalog import load_cli_platforms, platform_ids
    from shared.download_command_runtime import add_download_arguments
    from shared.search_command_runtime import add_search_arguments

    catalog = tuple(platforms) if platforms is not None else load_cli_platforms()
    ids = platform_ids(catalog)
    parser = argparse.ArgumentParser(
        prog="ucrawl",
        description="UCrawl 通用爬虫命令行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", "-V", action="store_true", help="显示版本")
    subparsers = parser.add_subparsers(dest="main_command", title="子命令")

    search = subparsers.add_parser("search", help="搜索并下载")
    add_search_arguments(search, platform_ids=ids)
    search.set_defaults(_handler=handle_search_command)

    scan = subparsers.add_parser("scan", help="扫描本地目录")
    add_scan_arguments(scan)
    scan.set_defaults(_handler=handle_scan_command)

    download = subparsers.add_parser("download", help="下载指定 URL")
    add_download_arguments(download)
    download.set_defaults(_handler=handle_download_command)

    platforms_parser = subparsers.add_parser("platforms", help="列出可用平台")
    add_platforms_arguments(platforms_parser)
    platforms_parser.set_defaults(_handler=handle_platforms_command)

    interactive = subparsers.add_parser("interactive", aliases=["i"], help="交互式引导")
    add_interactive_arguments(interactive)
    interactive.set_defaults(_handler=handle_interactive_command)

    add_platform_subparsers(subparsers, catalog)
    return parser


def main(argv=None) -> int:
    try:
        parser = build_parser()
    except ValueError as exc:
        sys.stderr.write(f"CLI 初始化失败: {exc}\n")
        return int(CliExitCode.ERROR)
    args = parser.parse_args(argv)
    if args.version:
        from shared.version import __version__

        sys.stdout.write(f"ucrawl {__version__}\n")
        return int(CliExitCode.OK)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return int(CliExitCode.OK)
    try:
        return int(handler(args))
    except KeyboardInterrupt:
        sys.stderr.write("已取消\n")
        return int(CliExitCode.CANCELLED)
```

Delete `_ensure_search_defaults`, `resolve_platform`, the static platform table, `cli/commands/_alias.py`, and its orphan test.

- [ ] **Step 5: Map search outcomes at the CLI boundary**

Update `cli/commands/search.py`:

```python
from cli.exit_codes import exit_code_for_status


def handle_search_command(args: argparse.Namespace) -> int:
    outcome, result = runtime.run_search_command(args, env=_runtime_env())
    runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return int(exit_code_for_status(outcome))
```

- [ ] **Step 6: Run search/parser tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/cli/test_main.py tests/unit/cli/test_defaults.py tests/unit/cli/test_selection.py tests/unit/cli/test_runner.py tests/contract/cli/test_module_entrypoint.py -q
```

Expected: all tests pass; no test imports `_ensure_search_defaults` or `_alias`.

- [ ] **Step 7: Commit the search/parser task**

```powershell
git add cli/main.py cli/commands/platform_base.py cli/commands/search.py shared/search_command_runtime.py tests/unit/cli
git add -u cli/commands/_alias.py tests/unit/cli/commands/test_alias.py
git commit -m "refactor(cli): unify registry driven search commands"
```

---

### Task 4: Replace Download’s Pseudo-ID Contract with Direct URL Semantics

**Files:**
- Modify: `shared/download_command_runtime.py`
- Modify: `cli/commands/download.py`
- Modify: `cli/commands/platform_base.py`
- Modify: download-related tests under `tests/unit/cli/`
- Modify: `tests/contract/entry/test_cross_entry_consistency.py`

**Interfaces:**
- Produces:
  - `add_download_arguments(parser, *, platform_ids, fixed_source=None)`.
  - Namespace fields `url`, `title`, `source`, `timeout`.
  - `run_download_command(...) -> tuple[str, dict | None, str | None]`.

- [ ] **Step 1: Write failing direct-download tests**

Add parser tests:

```python
def test_generic_download_uses_positional_url_and_optional_title():
    parser = build_parser((CliPlatform("douyin", "抖音", ("dy",)),))
    args = parser.parse_args(
        ["download", "--source", "douyin", "https://example.test/video.mp4", "--title", "示例"]
    )
    assert args.url == "https://example.test/video.mp4"
    assert args.title == "示例"
    assert not hasattr(args, "video_id")


def test_platform_download_supplies_source_and_matches_generic_fields():
    parser = build_parser((CliPlatform("douyin", "抖音", ("dy",)),))
    generic = parser.parse_args(["download", "--source", "douyin", "https://example.test/v"])
    scoped = parser.parse_args(["dy", "download", "https://example.test/v"])
    assert generic.url == scoped.url
    assert generic.source == scoped.source == "douyin"
```

Add runtime tests:

```python
def test_download_passes_url_and_title_to_sdk(fake_env):
    args = argparse.Namespace(
        url="https://example.test/video.mp4",
        title="Display title",
        source="douyin",
        timeout=30.0,
        save_dir=None,
        config=None,
        quiet=True,
        pretty=False,
    )
    outcome, result, error = run_download_command(args, env=fake_env)
    assert outcome == "ok"
    assert error is None
    assert fake_env.sdk.download_video.call_args.kwargs["url"] == args.url
    assert fake_env.sdk.download_video.call_args.kwargs["title"] == args.title


def test_download_validation_is_usage_error_before_sdk_construction(fake_env):
    args = valid_args(url="   ")
    outcome, result, error = run_download_command(args, env=fake_env)
    assert outcome == "usage"
    assert result is None
    assert error
    fake_env.UcrawlSDK_cls.assert_not_called()
```

- [ ] **Step 2: Run download tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/cli/test_sdk.py tests/unit/cli/test_main.py tests/contract/entry/test_cross_entry_consistency.py -q
```

Expected: parser still requires `video_id`/`--url`, and runtime passes the pseudo-ID as title.

- [ ] **Step 3: Implement the direct URL parser**

Replace the leading download arguments:

```python
def add_download_arguments(
    parser: argparse.ArgumentParser,
    *,
    platform_ids: tuple[str, ...],
    fixed_source: str | None = None,
) -> None:
    if fixed_source is None:
        parser.add_argument("--source", "-s", required=True, choices=platform_ids, help="平台 ID")
    else:
        parser.set_defaults(source=fixed_source)
    parser.add_argument("url", help="要下载的资源 URL")
    parser.add_argument("--title", default="", help="可选展示标题；默认使用 URL")
    parser.add_argument("--save-dir", "-d", default=None, help="保存目录")
    parser.add_argument("--timeout", type=float, default=300, help="整次下载超时秒数")
    parser.add_argument("--config", type=str, default=None, help="平台特定配置 JSON 对象")
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型")
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL")
    parser.add_argument("--individual-only", action="store_true", default=None, help="只看单体作品")
    parser.add_argument("--priority", type=str, default=None, help="优先级")

    output = parser.add_argument_group("输出")
    output.add_argument("--quiet", "-q", action="store_true", help="不输出下载进度")
    output.add_argument("--pretty", action="store_true", help="人类可读格式")
```

Delete `build_missing_url_result()`. In `run_download_command()`:

```python
url = str(getattr(args, "url", "") or "").strip()
title = str(getattr(args, "title", "") or "")
if not url:
    return "usage", None, "❌ URL 不能为空"
if args.timeout <= 0:
    return "usage", None, "❌ --timeout 必须大于 0"

source = resolve_source(args)
if not source or not env.get_plugin(source):
    return "usage", None, f"❌ 无效平台: {source}"

sdk = env.UcrawlSDK_cls(save_dir=save_dir)
try:
    result = sdk.download_video(
        url=url,
        source=source,
        title=title,
        save_dir=save_dir,
        timeout=args.timeout,
        verbose=not getattr(args, "quiet", False),
        config=config or None,
    )
finally:
    sdk.close()
return str(result.get("status", "error")), result, None
```

Return `"usage"` for config/type validation caught before work starts, and `"error"` for unexpected runtime status.

- [ ] **Step 4: Map download outcomes and update platform registration**

Update `cli/commands/download.py`:

```python
from cli.exit_codes import exit_code_for_status


def handle_download_command(args: argparse.Namespace) -> int:
    outcome, result, error_message = runtime.run_download_command(args, env=_runtime_env())
    if error_message:
        sys.stderr.write(f"{error_message}\n")
    if result is not None:
        runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return int(exit_code_for_status(outcome))
```

Ensure both top-level and platform download parsers call the same new builder signature.

- [ ] **Step 5: Run download and cross-entry tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/cli/test_sdk.py tests/unit/cli/test_main.py tests/unit/cli/test_defaults.py tests/contract/entry/test_cross_entry_consistency.py tests/contract/cross_interface/test_cli_sdk_api.py -q
```

Expected: all tests pass using positional URL and optional title.

- [ ] **Step 6: Commit the download task**

```powershell
git add shared/download_command_runtime.py cli/commands/download.py cli/commands/platform_base.py tests/unit/cli tests/contract/entry/test_cross_entry_consistency.py tests/contract/cross_interface/test_cli_sdk_api.py
git commit -m "refactor(cli): make download a direct URL command"
```

---

### Task 5: Apply Exit Semantics to Remaining Commands

**Files:**
- Modify: `cli/commands/scan.py`
- Modify: `cli/commands/platforms.py`
- Modify: `tests/unit/cli/test_main.py`
- Modify or create focused scan/platform command tests under `tests/unit/cli/`

**Interfaces:**
- Consumes: `CliExitCode`, `exit_code_for_status`.
- Produces: usage errors before SDK construction and status-specific timeout/cancel codes.

- [ ] **Step 1: Write failing scan/platform exit tests**

```python
def test_scan_invalid_limit_is_usage_error(monkeypatch):
    from cli.main import main

    sdk = Mock()
    monkeypatch.setattr("cli.commands.scan.UcrawlSDK", sdk)
    assert main(["scan", ".", "--limit", "0"]) == 2
    sdk.assert_not_called()


@pytest.mark.parametrize(
    ("status", "expected"),
    [("error", 1), ("timeout", 124), ("cancelled", 130)],
)
def test_scan_maps_structured_status(status, expected, monkeypatch):
    fake = Mock()
    fake.return_value.scan_directory.return_value = {"status": status, "error": status}
    monkeypatch.setattr("cli.commands.scan.UcrawlSDK", fake)
    assert main(["scan", "."]) == expected


def test_unknown_platform_description_is_usage_error():
    assert main(["platforms", "--describe", "missing"]) == 2
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/cli/test_main.py -q
```

Expected: current handlers return `1` for invalid limit, timeout, cancellation, and unknown describe.

- [ ] **Step 3: Implement consistent mappings**

In `scan.py`, return `CliExitCode.USAGE` for invalid `--limit` and pre-SDK type/value errors. For structured SDK results:

```python
status = str(result.get("status", "error"))
if status != "ok" and getattr(args, "pretty", False):
    sys.stderr.write(f"❌ {result.get('error', '未知错误')}\n")
return int(exit_code_for_status(status))
```

In `platforms.py`, return `CliExitCode.USAGE` for unknown `--describe`, and preserve `OK` for valid output.

- [ ] **Step 4: Run CLI command tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/cli/test_main.py tests/contract/entry/test_cli_entry.py -q
```

Expected: all tests pass with distinct status codes.

- [ ] **Step 5: Commit remaining exit semantics**

```powershell
git add cli/commands/scan.py cli/commands/platforms.py tests/unit/cli/test_main.py
git commit -m "refactor(cli): standardize command exit codes"
```

---

### Task 6: Split the Interactive Command by Responsibility

**Files:**
- Create: `cli/interactive/__init__.py`
- Create: `cli/interactive/catalog.py`
- Create: `cli/interactive/configuration.py`
- Create: `cli/interactive/prompts.py`
- Create: `cli/interactive/workflow.py`
- Modify: `cli/commands/interactive.py`
- Modify: `entry/interactive_entry.py`
- Modify: `tests/unit/cli/test_interactive_command.py`
- Add focused tests below `tests/unit/cli/interactive/` if one module exceeds a single clear test responsibility.

**Interfaces:**
- Produces:
  - `guide_for(platform_id, platform_info=None) -> dict`
  - `find_cookie_file`, `load_cookie`, `build_cookie_string`, `check_cookie_valid`, `persist_save_dir`, `build_config_summary_lines`, and `finalize_interactive_config`.
  - `input_with_default`, `choose`, `select_platform`, `print_examples`, `item_display_title`, `print_download_summary`, and `prompt_post_run_action`.
  - `run_interactive(args, *, sdk_cls=UcrawlSDK, runner_cls=CLIRunner) -> int`
  - thin `handle_interactive_command(args) -> int`.

- [ ] **Step 1: Add failing ownership and fallback tests**

Update imports in `tests/unit/cli/test_interactive_command.py` and add:

```python
def test_unknown_plugin_gets_generic_guide():
    from cli.interactive.catalog import guide_for

    guide = guide_for(
        "external",
        {"id": "external", "name": "External", "search_placeholder": "输入外部资源"},
    )
    assert guide["input_label"] == "输入外部资源"
    assert "External" in guide["result_tip"]


def test_command_module_is_a_thin_adapter():
    from pathlib import Path
    import cli.commands.interactive as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "def _load_cookie" not in source
    assert "def _choose" not in source
    assert "def _build_config_summary_lines" not in source
    assert len(source.splitlines()) < 230
```

Retarget existing helper tests:

```python
from cli.interactive.catalog import guide_for
from cli.interactive.configuration import (
    build_config_summary_lines,
    finalize_interactive_config,
    persist_save_dir,
)
from cli.interactive.prompts import choose, item_display_title, prompt_post_run_action
```

- [ ] **Step 2: Run interactive tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/cli/test_interactive_command.py -q
```

Expected: missing `cli.interactive` modules and thin-adapter assertion failure.

- [ ] **Step 3: Extract the catalog**

Move the complete `_PLATFORM_GUIDE` mapping at current lines 40–97 to `cli/interactive/catalog.py` and replace `_guide_for` with:

```python
def guide_for(platform_id: str, platform_info: dict | None = None) -> dict:
    specific = _PLATFORM_GUIDE.get(platform_id)
    if specific is not None:
        return dict(specific)
    info = platform_info or {}
    name = str(info.get("name") or platform_id)
    placeholder = str(info.get("search_placeholder") or "输入关键词或链接")
    return {
        "input_label": placeholder,
        "examples": [],
        "limit_label": "资源数量",
        "empty_tip": "请检查输入、登录状态和插件配置。",
        "result_tip": f"{name} 将使用插件提供的默认配置执行搜索与下载。",
    }
```

- [ ] **Step 4: Extract configuration helpers**

Move the named constants and complete current function bodies into `cli/interactive/configuration.py`, removing leading underscores from public helper names:

```text
_AUTH_FILE_MAP
_REQUIRED_COOKIE_KEY
_LOGIN_DESC
_find_cookie_file -> find_cookie_file
_load_cookie -> load_cookie
_build_cookie_string -> build_cookie_string
_check_cookie_valid -> check_cookie_valid
_is_temp_dir -> is_temp_dir
_persist_save_dir -> persist_save_dir
_build_config_summary_lines -> build_config_summary_lines
_finalize_interactive_config -> finalize_interactive_config
```

Keep imports limited to `json`, `os`, `Path`, `app.config.cfg`, runtime-path helpers, and shared config helpers. Do not import `CLIRunner`, `UcrawlSDK`, or terminal color constants.

- [ ] **Step 5: Extract terminal prompt/presentation helpers**

Move color constants and the complete current function bodies below into `cli/interactive/prompts.py`, using public names:

```text
_input -> input_with_default
_choose -> choose
_select_platform -> select_platform
_print_examples -> print_examples
_item_display_title -> item_display_title
_print_download_summary -> print_download_summary
_prompt_post_run_action -> prompt_post_run_action
```

`print_examples()` receives a guide dict rather than looking up global platform state:

```python
def print_examples(guide: dict) -> None:
    examples = list(guide.get("examples", ()))
    if not examples:
        return
    print("  示例:")
    for example in examples:
        print(f"    {DIM}{example}{RESET}")
```

- [ ] **Step 6: Move orchestration into workflow**

Create `cli/interactive/workflow.py` and move the body of the current handler into:

```python
def run_interactive(
    args: argparse.Namespace,
    *,
    sdk_cls=UcrawlSDK,
    runner_cls=CLIRunner,
) -> int:
    sdk = sdk_cls(verbose=not getattr(args, "quiet", False))
    try:
        return _run_interactive_loop(args, sdk=sdk, runner_cls=runner_cls)
    finally:
        sdk.close()
```

The internal loop uses the extracted modules and:

- reads `http_timeout` into `config["timeout"]` when explicitly provided, otherwise preserves the interactive default `30`;
- resolves `command_timeout`/`legacy_run_timeout` through `resolve_command_timeout`;
- returns `CliExitCode.USAGE` for invalid input/config/selection;
- maps runner `status` through `exit_code_for_status`;
- returns `CliExitCode.CANCELLED` when interactive input raises `EOFError` or `KeyboardInterrupt`;
- preserves “same platform”, “switch platform”, “open folder”, no-results, pretty JSON, and download-summary flows.

Reduce `cli/commands/interactive.py` to:

```python
"""Argparse adapter for the interactive terminal workflow."""

from __future__ import annotations

import argparse

from cli.interactive.workflow import run_interactive


def add_interactive_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save-dir", "-d", default=None, help="默认保存目录")
    parser.add_argument("--config", type=str, default=None, help="平台特定配置 JSON 对象")
    parser.add_argument("--http-timeout", type=float, default=None, help="HTTP 请求超时秒")
    parser.add_argument("--timeout", dest="command_timeout", type=float, default=None, help="整次命令超时秒")
    parser.add_argument("--run-timeout", dest="legacy_run_timeout", type=float, default=None, help="已弃用；使用 --timeout")
    parser.add_argument("--select", help="指定选中的索引")
    parser.add_argument("--exclude", help="指定排除的索引")
    parser.add_argument("--all", dest="select_all", action="store_true", help="全选")
    parser.add_argument("--first", action="store_true", help="只选第一个")
    parser.add_argument("--last", action="store_true", help="只选最后一个")
    parser.add_argument("--pipe", action="store_true", help="使用 stdin 管道选择")
    parser.add_argument("--preload-choices", help="预加载多次选择")
    parser.add_argument("--no-download", action="store_true", help="只搜索不下载")
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型")
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL")
    parser.add_argument("--individual-only", action="store_true", default=None, help="只看单体作品")
    parser.add_argument("--priority", type=str, default=None, help="优先级")
    parser.add_argument("--quiet", "-q", action="store_true", help="不输出运行日志")
    parser.add_argument("--pretty", action="store_true", help="人类可读格式")


def handle_interactive_command(args: argparse.Namespace) -> int:
    return int(run_interactive(args))
```

- [ ] **Step 7: Run interactive tests and verify GREEN**

Run:

```powershell
python -m pytest tests/unit/cli/test_interactive_command.py tests/unit/cli/test_main.py tests/unit/entry/test_dispatcher.py tests/contract/entry/test_cli_entry.py -q
```

Expected: all existing interaction scenarios pass, the generic plugin fallback passes, and the command adapter remains below the stated size.

- [ ] **Step 8: Commit the interactive split**

```powershell
git add cli/interactive cli/commands/interactive.py entry/interactive_entry.py tests/unit/cli/test_interactive_command.py tests/unit/entry/test_dispatcher.py
git commit -m "refactor(cli): split interactive workflow responsibilities"
```

---

### Task 7: Update Active Documentation and AI Skill

**Files:**
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `cli/README.md`
- Modify: `docs/cli/README.md`
- Modify: `docs/cli/cli-guide.md`
- Modify: `docs/cli/python-sdk-guide.md`
- Modify: `docs/guides/ai-skill-guide.md`
- Modify: `cli/skill/SKILL.md`
- Modify: `cli/skill/examples/01_basic_search.py`
- Modify: `cli/skill/examples/02_collection_download.py`
- Modify: `cli/skill/examples/03_batch_search.py`
- Modify: `tests/contract/cli/test_skill_contract.py`

**Interfaces:**
- Publishes only the canonical commands and exit-code table.
- Keeps SDK examples importing from `ucrawl`, never `cli`.

- [ ] **Step 1: Add failing documentation/skill contract assertions**

Extend `tests/contract/cli/test_skill_contract.py`:

```python
def test_skill_uses_canonical_timeout_and_download_syntax():
    text = (PROJECT_ROOT / "cli" / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "--http-timeout" in text
    assert "download --source" in text
    assert "--url" not in text
    assert "<video_id>" not in text


def test_active_cli_guides_do_not_publish_removed_platform_scan():
    for relative in ("README.md", "cli/README.md", "docs/cli/cli-guide.md"):
        text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "douyin scan" not in text
        assert "bilibili scan" not in text
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
python -m pytest tests/contract/cli/test_skill_contract.py -q
```

Expected: old timeout, `video_id`, `--url`, or platform-scan syntax causes failure.

- [ ] **Step 3: Update all active command examples**

Use these canonical shapes consistently:

```text
ucrawl search --source douyin "关键词" --http-timeout 15 --timeout 120
ucrawl douyin search "关键词" --http-timeout 15 --timeout 120
ucrawl download --source douyin "https://example/video.mp4" --title "示例"
ucrawl douyin download "https://example/video.mp4" --title "示例"
ucrawl scan "./downloads"
```

Document:

```text
0 success
1 runtime/initialization error
2 usage/config error
124 timeout
130 cancelled
```

State that `--run-timeout` is temporarily deprecated, `--http-timeout` replaces the old search HTTP meaning, platform `scan` is removed, and SDK imports use `ucrawl`.

- [ ] **Step 4: Run documentation/skill contracts and verify GREEN**

Run:

```powershell
python -m pytest tests/contract/cli/test_skill_contract.py tests/contract/cli/test_public_package_boundaries.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md README_EN.md cli/README.md docs/cli docs/guides/ai-skill-guide.md cli/skill tests/contract/cli/test_skill_contract.py
git commit -m "docs: publish consolidated CLI contract"
```

---

### Task 8: Full Verification and Diff Audit

**Files:**
- Verify only; modify production/tests only if a fresh failing regression directly identifies an omission in Tasks 1–7.

**Interfaces:**
- Confirms the complete design contract and repository test taxonomy.

- [ ] **Step 1: Run the complete affected CLI and entry suite**

```powershell
python -m pytest tests/unit/cli tests/contract/cli tests/contract/cross_interface/test_cli_sdk_api.py tests/contract/entry/test_cli_entry.py tests/contract/entry/test_cross_entry_consistency.py tests/unit/entry/test_dispatcher.py -q
```

Expected: zero failures.

- [ ] **Step 2: Run architecture and testkit contracts**

```powershell
python -m pytest tests/architecture/test_dependency_direction.py tests/architecture/test_file_size_limits.py tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run static checks**

```powershell
python -m ruff check cli shared/version.py shared/search_command_runtime.py shared/download_command_runtime.py ucrawl tests/unit/cli tests/contract/cli
```

Expected: exit code `0`, no Ruff diagnostics.

- [ ] **Step 4: Verify command help and package imports**

```powershell
python -m cli --help
python -m cli search --help
python -m cli douyin --help
python -m cli download --help
python -c "import sys, cli, ucrawl; assert not any(n == 'app.ui' or n.startswith('app.ui.') for n in sys.modules)"
```

Expected:

- root help lists dynamic built-in platforms;
- platform help lists only `search` and `download`;
- search help distinguishes `--http-timeout` and `--timeout`;
- download help shows positional URL and `--title`;
- fresh imports exit `0` without loading `app.ui`.

- [ ] **Step 5: Verify full test collection**

```powershell
python -m pytest tests --collect-only -q
```

Expected: exit code `0`, no collection errors.

- [ ] **Step 6: Audit the final diff and worktree**

```powershell
git diff --check
git status --short
git diff --stat
git log --oneline --decorate -10
```

Expected:

- no whitespace errors;
- only CLI-contract files from this plan are changed or committed in the isolated implementation branch;
- the original workspace’s unrelated dirty files are absent from this branch diff.

---

## Plan Self-Review

- Every verified shortcoming is covered: dynamic source, one argument contract, removal of default patching and orphan alias code, direct URL download, top-level-only scan, distinct timeout names, stable exit codes, UI-free package imports, and interactive decomposition.
- The plugin contract stays generic; plugins do not own argparse presentation.
- The plan introduces no new dependency and no persisted state.
- Shared runtimes return semantic outcomes; only CLI modules own process exit codes, preserving dependency direction.
- Generic and platform-scoped commands share builders and handlers.
- Tests are classified under the canonical suite roots and each behavior change has an explicit RED/GREEN cycle.
- Documentation and AI skill updates are active-document changes only; historical specs and plans remain untouched.
