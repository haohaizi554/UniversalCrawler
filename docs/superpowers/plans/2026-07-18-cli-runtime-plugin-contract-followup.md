# CLI Runtime and Plugin Interaction Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make plugin manifests drive CLI interactive guidance and authentication, make all command runtimes explicit and source-safe, remove stale CLI ownership, and align tests and active architecture documentation.

**Architecture:** `app.core.plugins` owns a host-neutral, typed platform manifest consumed by SDK, Web, and CLI. `shared` owns search, download, and scan command behavior, while `cli` only builds parsers, injects real dependencies, renders terminal prompts, and maps semantic outcomes to process exit codes. Public SDK compatibility is preserved: `ucrawl` remains the import surface and `UcrawlSDK.download_video(timeout=...)` remains unchanged.

**Tech Stack:** Python 3, dataclasses, argparse, unittest/pytest, Ruff, Mermaid, Git.

## Global Constraints

- Work directly on `main`; do not create a worktree or feature branch.
- Preserve unrelated dirty files: `code_report.html`, `code_report.json`, `count_project.py`, and `tests/release/tooling/test_count_project.py`.
- Use `apply_patch` for every source, test, and documentation edit.
- Stage and commit exact task paths only; inspect every commit with `git show`.
- `--timeout` always means the whole CLI command; search/interactive default to unlimited and download keeps the 300-second default.
- Do not rename the public SDK parameter `UcrawlSDK.download_video(timeout=...)`.
- Missing search source is a usage error; never infer `douyin` or consume `_platform`.
- Do not infer interactive fields from arbitrary plugin configuration dictionaries.
- Plugin metadata must not import Qt, argparse, terminal presentation code, Web code, or CLI code.
- Do not rewrite historical records under `docs/superpowers/`, except for this new approved specification and implementation plan.
- Tests below `tests/<suite>/` must mirror the production namespace as required by `tests/AGENTS.md`.
- Implement each behavior test-first and run the stated failing test before production edits.

---

### Task 1: Add the typed plugin manifest model

**Files:**
- Create: `app/core/plugins/metadata.py`
- Modify: `app/core/plugins/base.py`
- Modify: `app/core/plugins/__init__.py`
- Test: `tests/unit/app/core/plugins/test_metadata.py`

**Interfaces:**
- Produces: `InteractiveChoice.to_dict() -> dict[str, Any]`
- Produces: `InteractiveField.to_dict() -> dict[str, Any]`
- Produces: `PlatformAuthSpec.to_dict() -> dict[str, Any]`
- Produces: `PlatformInteractiveSpec.to_dict() -> dict[str, Any]`
- Produces: `generic_interactive_spec(name: str, search_placeholder: str) -> PlatformInteractiveSpec`
- Produces: `plugin_manifest(plugin: Any) -> dict[str, Any]`
- Produces: `BasePlugin.get_interactive_spec() -> PlatformInteractiveSpec`
- Produces: `BasePlugin.get_manifest() -> dict[str, Any]`

- [ ] **Step 1: Write failing metadata tests**

Create `tests/unit/app/core/plugins/test_metadata.py` with focused tests:

```python
from app.core.plugins.base import BasePlugin
from app.core.plugins.metadata import (
    InteractiveChoice,
    InteractiveField,
    PlatformAuthSpec,
    PlatformInteractiveSpec,
)


class ExternalPlugin(BasePlugin):
    id = "external"
    name = "External"

    def get_search_placeholder(self) -> str:
        return "输入外部资源"


class GuidedPlugin(ExternalPlugin):
    id = "guided"
    interactive_spec = PlatformInteractiveSpec(
        input_label="输入作品链接",
        examples=("https://example.test/item/1",),
        empty_tip="检查插件连接",
        result_tip="使用插件解析器",
        fields=(
            InteractiveField(
                key="max_items",
                prompt="资源数量",
                summary_label="数量",
                choices=(
                    InteractiveChoice("1", 1),
                    InteractiveChoice("5", 5),
                ),
            ),
        ),
        auth=PlatformAuthSpec(
            mode="cookie",
            config_key="guided_cookie_file",
            default_file="guided_auth.json",
            cookie_names=("session",),
            login_url="https://example.test/",
            login_description="打开浏览器登录",
            summary="浏览器登录",
        ),
    )


def test_external_plugin_gets_safe_generic_interactive_manifest():
    manifest = ExternalPlugin().get_manifest()

    assert manifest["id"] == "external"
    assert manifest["search_placeholder"] == "输入外部资源"
    assert manifest["interactive"]["input_label"] == "输入外部资源"
    assert manifest["interactive"]["fields"] == []
    assert manifest["interactive"]["auth"]["mode"] == "unspecified"


def test_declared_interactive_manifest_is_json_safe():
    manifest = GuidedPlugin().get_manifest()

    assert manifest["interactive"]["fields"][0] == {
        "key": "max_items",
        "prompt": "资源数量",
        "summary_label": "数量",
        "choices": [
            {"label": "1", "value": 1, "custom": False},
            {"label": "5", "value": 5, "custom": False},
        ],
        "custom_prompt": "",
    }
    assert manifest["interactive"]["auth"]["cookie_names"] == ["session"]
```

- [ ] **Step 2: Run metadata tests and verify the new module is missing**

Run:

```powershell
python -m pytest tests/unit/app/core/plugins/test_metadata.py -q
```

Expected: collection fails with `ModuleNotFoundError: app.core.plugins.metadata`.

- [ ] **Step 3: Implement the typed, JSON-safe metadata model**

Create `app/core/plugins/metadata.py` with these definitions:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

InteractiveValue = str | int | float | bool | None
AuthMode = Literal["cookie", "none", "unspecified"]


@dataclass(frozen=True, slots=True)
class InteractiveChoice:
    label: str
    value: InteractiveValue
    custom: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "custom": self.custom,
        }


@dataclass(frozen=True, slots=True)
class InteractiveField:
    key: str
    prompt: str
    summary_label: str
    choices: tuple[InteractiveChoice, ...]
    custom_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "summary_label": self.summary_label,
            "choices": [choice.to_dict() for choice in self.choices],
            "custom_prompt": self.custom_prompt,
        }


@dataclass(frozen=True, slots=True)
class PlatformAuthSpec:
    mode: AuthMode = "unspecified"
    config_key: str = ""
    default_file: str = ""
    cookie_names: tuple[str, ...] = ()
    login_url: str = ""
    login_description: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if self.mode not in {"cookie", "none", "unspecified"}:
            raise ValueError(f"unsupported auth mode: {self.mode}")
        if self.mode == "cookie" and (
            not self.default_file or not self.cookie_names
        ):
            raise ValueError(
                "cookie auth requires default_file and cookie_names"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "config_key": self.config_key,
            "default_file": self.default_file,
            "cookie_names": list(self.cookie_names),
            "login_url": self.login_url,
            "login_description": self.login_description,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class PlatformInteractiveSpec:
    input_label: str
    examples: tuple[str, ...] = ()
    empty_tip: str = ""
    result_tip: str = ""
    fields: tuple[InteractiveField, ...] = ()
    auth: PlatformAuthSpec = PlatformAuthSpec()

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_label": self.input_label,
            "examples": list(self.examples),
            "empty_tip": self.empty_tip,
            "result_tip": self.result_tip,
            "fields": [field.to_dict() for field in self.fields],
            "auth": self.auth.to_dict(),
        }


def generic_interactive_spec(
    name: str,
    search_placeholder: str,
) -> PlatformInteractiveSpec:
    return PlatformInteractiveSpec(
        input_label=search_placeholder or "输入关键词或链接",
        empty_tip="请检查输入、登录状态和插件配置。",
        result_tip=f"{name} 将使用插件提供的默认配置执行搜索与下载。",
    )


def plugin_manifest(plugin: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": str(plugin.id),
        "name": str(plugin.name),
        "aliases": list(getattr(plugin, "aliases", ())),
        "search_placeholder": str(plugin.get_search_placeholder()),
        "interactive": plugin.get_interactive_spec().to_dict(),
    }
    description = str(getattr(plugin, "description", "") or "")
    if description:
        info["description"] = description
    settings_builder = getattr(plugin, "settings_builder", None)
    if settings_builder is not None:
        try:
            info["settings"] = settings_builder.field_defs
        except (AttributeError, TypeError):
            pass
    return info
```

Modify `BasePlugin`:

```python
from .metadata import (
    PlatformInteractiveSpec,
    generic_interactive_spec,
    plugin_manifest,
)

interactive_spec: PlatformInteractiveSpec | None = None

def get_interactive_spec(self) -> PlatformInteractiveSpec:
    if self.interactive_spec is not None:
        return self.interactive_spec
    return generic_interactive_spec(
        self.name,
        self.get_search_placeholder(),
    )

def get_manifest(self) -> dict[str, Any]:
    return plugin_manifest(self)
```

Export the four dataclasses from `app/core/plugins/__init__.py`.

- [ ] **Step 4: Run plugin metadata and registry tests**

Run:

```powershell
python -m pytest tests/unit/app/core/plugins/test_metadata.py tests/unit/app/core/plugins/test_registry.py tests/unit/app/core/plugins/test_discovery.py -q
```

Expected: all pass and importing the registry still does not load Qt settings builders.

- [ ] **Step 5: Commit the metadata foundation**

```powershell
git add -- app/core/plugins/metadata.py app/core/plugins/base.py app/core/plugins/__init__.py tests/unit/app/core/plugins/test_metadata.py
git commit -m "feat(plugins): add interactive platform manifest"
git show --stat --oneline HEAD
```

### Task 2: Declare built-in interaction/auth specs and share the manifest

**Files:**
- Modify: `app/core/plugins/definitions.py`
- Modify: `shared/sdk_runtime.py`
- Modify: `app/web/controller.py`
- Modify: `app/services/frontend_settings_adapter.py`
- Modify: `app/services/frontend_state_service.py`
- Modify: `app/core/plugins/README.md`
- Test: `tests/unit/app/core/plugins/test_metadata.py`
- Test: `tests/contract/cross_interface/test_cli_sdk_api.py`
- Test: `tests/unit/app/services/test_frontend_settings_adapter.py`
- Test: `tests/unit/app/services/test_frontend_state_service.py`

**Interfaces:**
- Consumes: `BasePlugin.interactive_spec` and `BasePlugin.get_manifest()`
- Produces: five complete built-in `PlatformInteractiveSpec` declarations
- Produces: `resolve_platform_auth_spec(plugin_id: str) -> PlatformAuthSpec`
- Preserves: existing SDK/Web platform keys while adding `aliases` and `interactive`

- [ ] **Step 1: Add failing built-in and cross-interface manifest tests**

Extend plugin metadata tests:

```python
def test_every_builtin_declares_non_generic_interactive_metadata():
    from app.core.plugin_registry import registry

    manifests = {
        plugin.id: plugin.get_manifest()
        for plugin in registry.get_all_plugins()
    }

    assert manifests["douyin"]["interactive"]["fields"][0]["key"] == "max_items"
    assert manifests["xiaohongshu"]["interactive"]["fields"][0]["summary_label"] == "笔记数"
    assert manifests["bilibili"]["interactive"]["fields"][0]["key"] == "max_pages"
    assert [field["key"] for field in manifests["missav"]["interactive"]["fields"]] == [
        "individual_only",
        "priority",
        "proxy",
    ]
    assert manifests["kuaishou"]["interactive"]["auth"]["mode"] == "cookie"
    assert manifests["missav"]["interactive"]["auth"]["mode"] == "none"
```

Extend the cross-interface platform test so both SDK and Web manifest entries include
equal `interactive` dictionaries for every platform.

- [ ] **Step 2: Run focused tests and verify built-ins/manifests fail**

Run:

```powershell
python -m pytest tests/unit/app/core/plugins/test_metadata.py tests/contract/cross_interface/test_cli_sdk_api.py -q
```

Expected: built-in `fields` assertions fail and Web/SDK platform dictionaries differ.

- [ ] **Step 3: Add exact built-in field and authentication declarations**

In `app/core/plugins/definitions.py`, import the metadata types and define reusable
choices:

```python
ITEM_CHOICES = tuple(
    InteractiveChoice(label, value)
    for label, value in (
        ("1", 1),
        ("2", 2),
        ("5", 5),
        ("10", 10),
        ("20", 20),
        ("max (9999)", 9999),
    )
)
PAGE_CHOICES = tuple(
    InteractiveChoice(label, value)
    for label, value in (
        ("1", 1),
        ("2", 2),
        ("5", 5),
        ("10", 10),
        ("20", 20),
        ("max (500)", 500),
    )
)
```

Declare these specs on the plugin classes:

```python
DouyinPlugin.interactive_spec = PlatformInteractiveSpec(
    input_label="主页链接、分享链接或合集链接",
    examples=(
        "主页链接: https://www.douyin.com/user/xxx",
        "分享链接: https://v.douyin.com/xxxxx/",
        "合集链接: 带 collection / mix / modal_id 的链接",
    ),
    empty_tip="优先尝试主页链接或分享链接；纯数字 UID 当前仍不支持。",
    result_tip="抖音会按统一采集流程扫码、采集、选择并入队下载。",
    fields=(
        InteractiveField("max_items", "视频数量", "视频数", ITEM_CHOICES),
    ),
    auth=PlatformAuthSpec(
        mode="cookie",
        config_key="douyin_cookie_file",
        default_file="dy_auth.json",
        cookie_names=("sessionid_ss",),
        login_url="https://www.douyin.com/",
        login_description="抖音将打开浏览器，请扫码登录。",
        summary="浏览器扫码",
    ),
)

XiaohongshuPlugin.interactive_spec = PlatformInteractiveSpec(
    input_label="小红书关键词、笔记链接或作者主页链接",
    examples=(
        "关键词: 穿搭 / 探店 / 摄影",
        "笔记链接: https://www.xiaohongshu.com/explore/...",
        "作者主页: https://www.xiaohongshu.com/user/profile/...",
    ),
    empty_tip="优先使用完整笔记链接或作者主页链接；关键词模式会先搜索再选择。",
    result_tip="小红书会准备浏览器 Cookie，必要时请在页面中登录。",
    fields=(
        InteractiveField("max_items", "笔记数量", "笔记数", ITEM_CHOICES),
    ),
    auth=PlatformAuthSpec(
        mode="cookie",
        config_key="xiaohongshu_cookie_file",
        default_file="xhs_auth.json",
        cookie_names=("web_session", "a1"),
        login_url="https://www.xiaohongshu.com/",
        login_description="小红书将打开浏览器获取 Cookie，必要时请手动登录。",
        summary="浏览器 Cookie / 手动登录",
    ),
)

BilibiliPlugin.interactive_spec = PlatformInteractiveSpec(
    input_label="BV 号、UP 主页、合集链接或关键词",
    examples=(
        "BV 号: BV1xx411c7mD",
        "UP 主页: https://space.bilibili.com/123456",
        "视频链接: https://www.bilibili.com/video/BVxxxx",
    ),
    empty_tip="可直接输入 BV 号、UP 主页或视频链接，通常比模糊关键词稳定。",
    result_tip="B 站会先选择主项目，再按需展开分 P 或合集。",
    fields=(
        InteractiveField("max_pages", "搜索页数", "页数", PAGE_CHOICES),
    ),
    auth=PlatformAuthSpec(
        mode="cookie",
        config_key="bilibili_cookie_file",
        default_file="bili_auth.json",
        cookie_names=("SESSDATA",),
        login_url="https://www.bilibili.com/",
        login_description="B 站将打开浏览器，请扫码登录。",
        summary="浏览器扫码",
    ),
)

KuaishouPlugin.interactive_spec = PlatformInteractiveSpec(
    input_label="快手主页链接、分享链接、快手号或关键词",
    examples=(
        "主页链接: https://www.kuaishou.com/profile/xxx",
        "分享链接: https://v.kuaishou.com/xxxxx/",
        "快手号: 直接输入纯数字快手号",
    ),
    empty_tip="优先使用主页或分享链接；关键词会先站内搜索再进入主页。",
    result_tip="快手允许在浏览器中手动登录，分享链接可解析单条作品。",
    fields=(
        InteractiveField("max_items", "视频数量", "视频数", ITEM_CHOICES),
    ),
    auth=PlatformAuthSpec(
        mode="cookie",
        config_key="kuaishou_cookie_file",
        default_file="ks_auth.json",
        cookie_names=("userId", "kuaishou.server.web_st"),
        login_url="https://www.kuaishou.com/",
        login_description="快手将打开浏览器，请手动登录。",
        summary="浏览器手动登录",
    ),
)

MissAVPlugin.interactive_spec = PlatformInteractiveSpec(
    input_label="番号、演员名或 MissAV 链接",
    examples=(
        "番号: SSIS-001",
        "演员名: 三上悠亚",
        "列表/详情链接: https://missav.ai/...",
    ),
    empty_tip="先确认代理可用，再尝试番号或作品链接。",
    result_tip="MissAV 会扫描列表、筛选版本并嗅探 m3u8。",
    fields=(
        InteractiveField(
            "individual_only",
            "仅单体作品",
            "仅单体",
            (
                InteractiveChoice("否", False),
                InteractiveChoice("是", True),
            ),
        ),
        InteractiveField(
            "priority",
            "排序偏好",
            "偏好",
            (
                InteractiveChoice("中文字幕优先", "中文字幕优先"),
                InteractiveChoice("无码流出优先", "无码流出优先"),
            ),
        ),
        InteractiveField(
            "proxy",
            "代理",
            "代理",
            (
                InteractiveChoice("Clash (7890)", "Clash (7890)"),
                InteractiveChoice("v2rayN (10809)", "v2rayN (10809)"),
                InteractiveChoice("自定义", None, custom=True),
            ),
            custom_prompt="代理地址",
        ),
    ),
    auth=PlatformAuthSpec(mode="none"),
)
```

Place each declaration inside its corresponding class body rather than assigning it
after class creation; the snippets above define the exact values.

- [ ] **Step 4: Make SDK and Web consume `get_manifest()`**

Replace the duplicated loops in `UcrawlSDK.list_platforms()` and
`WebController.get_platforms()`:

```python
return [
    plugin.get_manifest()
    for plugin in registry.get_all_plugins()
]
```

Keep registry imports lazy where they are currently lazy.

- [ ] **Step 5: Replace frontend auth maps with plugin metadata**

In `app/services/frontend_settings_adapter.py`, remove
`PLATFORM_AUTH_REQUIREMENTS` and add:

```python
from app.core.plugins.metadata import PlatformAuthSpec


def resolve_platform_auth_spec(plugin_id: str) -> PlatformAuthSpec:
    plugin = registry.get_plugin(
        str(plugin_id or "").strip().lower()
    )
    if plugin is None:
        return PlatformAuthSpec()
    return plugin.get_interactive_spec().auth
```

Update `platform_auth_snapshot()` to use `spec.config_key`,
`spec.cookie_names`, and `spec.login_url`. Return “无需认证” for `mode=none`
and “该插件未声明 Cookie 检测规则” for `mode=unspecified`. Update
`FrontendStateService._platform_auth_signature()` to call the resolver and
derive its signature from the same spec.

- [ ] **Step 6: Document the external plugin manifest extension**

Add a complete example to `app/core/plugins/README.md` showing an external plugin
with a single `max_items` field and cookie auth. State that missing metadata gets a
safe generic contract and never exposes arbitrary default config.

- [ ] **Step 7: Run plugin, SDK/Web, and auth tests**

Run:

```powershell
python -m pytest tests/unit/app/core/plugins tests/contract/cross_interface/test_cli_sdk_api.py tests/unit/app/services/test_frontend_settings_adapter.py tests/unit/app/services/test_frontend_state_service.py -q
```

Expected: all pass; SDK and Web return identical platform manifests.

- [ ] **Step 8: Commit built-in manifests and shared projection**

```powershell
git add -- app/core/plugins/definitions.py app/core/plugins/README.md shared/sdk_runtime.py app/web/controller.py app/services/frontend_settings_adapter.py app/services/frontend_state_service.py tests/unit/app/core/plugins/test_metadata.py tests/contract/cross_interface/test_cli_sdk_api.py tests/unit/app/services/test_frontend_settings_adapter.py tests/unit/app/services/test_frontend_state_service.py
git commit -m "refactor(plugins): drive platform hosts from manifests"
git show --stat --oneline HEAD
```

### Task 3: Make interactive guidance, fields, auth, and summaries schema-driven

**Files:**
- Modify: `cli/interactive/catalog.py`
- Modify: `cli/interactive/configuration.py`
- Modify: `cli/interactive/workflow.py`
- Test: `tests/unit/cli/test_interactive_command.py`

**Interfaces:**
- Consumes: JSON-safe `platform_info["interactive"]`
- Produces: `guide_for(platform_id: str, platform_info: dict | None) -> dict`
- Produces: `_configure_platform(guide: dict, config: dict) -> None`
- Produces: auth helpers accepting an auth dictionary rather than a platform ID
- Produces: `build_config_summary_lines(guide, config, platform_name, keyword, save_dir)`

- [ ] **Step 1: Write failing external-plugin interaction tests**

Add tests that use this platform manifest:

```python
external_platform = {
    "id": "external",
    "name": "External",
    "search_placeholder": "输入外部资源",
    "interactive": {
        "input_label": "输入作品链接",
        "examples": ["https://example.test/item/1"],
        "empty_tip": "检查插件连接",
        "result_tip": "使用插件解析器",
        "fields": [
            {
                "key": "quality",
                "prompt": "清晰度",
                "summary_label": "清晰度",
                "choices": [
                    {"label": "720p", "value": "720", "custom": False},
                    {"label": "自定义", "value": None, "custom": True},
                ],
                "custom_prompt": "自定义清晰度",
            }
        ],
        "auth": {
            "mode": "cookie",
            "config_key": "external_cookie_file",
            "default_file": "external_auth.json",
            "cookie_names": ["session"],
            "login_url": "https://example.test/",
            "login_description": "打开 External 登录",
            "summary": "浏览器登录",
        },
    },
}
```

Assert:

- `guide_for()` returns the plugin copy and field unchanged.
- `_configure_platform()` calls `prompts.choose()` for `quality` and writes the
  chosen value to config.
- choosing the custom option calls `prompts.input_with_default()`.
- summary lines include `清晰度`.
- auth helpers validate `session` without an external-platform CLI branch.
- source text in workflow/configuration/catalog does not contain the five built-in IDs.

- [ ] **Step 2: Run interactive tests and verify hard-coded behavior fails**

Run:

```powershell
python -m pytest tests/unit/cli/test_interactive_command.py -q
```

Expected: external field/auth assertions fail and the source-text guard finds built-in IDs.

- [ ] **Step 3: Replace catalog platform map with a defensive manifest normalizer**

Implement `guide_for()` with these stable defaults:

```python
def guide_for(
    platform_id: str,
    platform_info: dict | None = None,
) -> dict:
    info = platform_info or {}
    name = str(info.get("name") or platform_id)
    default = {
        "input_label": str(
            info.get("search_placeholder") or "输入关键词或链接"
        ),
        "examples": [],
        "empty_tip": "请检查输入、登录状态和插件配置。",
        "result_tip": (
            f"{name} 将使用插件提供的默认配置执行搜索与下载。"
        ),
        "fields": [],
        "auth": {"mode": "unspecified"},
    }
    raw = info.get("interactive")
    if not isinstance(raw, dict):
        return default
    guide = dict(default)
    for key in ("input_label", "empty_tip", "result_tip"):
        if isinstance(raw.get(key), str) and raw[key].strip():
            guide[key] = raw[key]
    if isinstance(raw.get("examples"), list):
        guide["examples"] = [
            str(value)
            for value in raw["examples"]
            if str(value).strip()
        ]
    if isinstance(raw.get("fields"), list):
        guide["fields"] = [
            dict(value)
            for value in raw["fields"]
            if isinstance(value, dict)
            and isinstance(value.get("key"), str)
            and isinstance(value.get("choices"), list)
        ]
    if isinstance(raw.get("auth"), dict):
        guide["auth"] = dict(raw["auth"])
    return guide
```

- [ ] **Step 4: Generalize field prompting**

Change `_configure_platform()` to accept a guide and iterate fields:

```python
def _choice_default_index(
    choices: list[dict],
    current: Any,
) -> int:
    for index, choice in enumerate(choices):
        if choice.get("value") == current:
            return index
    numeric = [
        (index, choice.get("value"))
        for index, choice in enumerate(choices)
        if isinstance(choice.get("value"), (int, float))
        and not isinstance(choice.get("value"), bool)
    ]
    if numeric and isinstance(current, (int, float)):
        return min(
            numeric,
            key=lambda pair: abs(pair[1] - current),
        )[0]
    return 0


def _configure_platform(guide: dict, config: dict) -> None:
    for field in guide.get("fields", []):
        choices = [
            choice
            for choice in field.get("choices", [])
            if isinstance(choice, dict)
            and isinstance(choice.get("label"), str)
        ]
        if not choices:
            continue
        key = field["key"]
        selected = prompts.choose(
            str(field.get("prompt") or key),
            [choice["label"] for choice in choices],
            _choice_default_index(choices, config.get(key)),
        )
        choice = choices[selected]
        if choice.get("custom"):
            config[key] = prompts.input_with_default(
                str(field.get("custom_prompt") or field.get("prompt") or key),
                str(config.get(key) or ""),
            )
        else:
            config[key] = choice.get("value")
```

Call it with `guide`, not `platform_id`.

- [ ] **Step 5: Generalize auth discovery and summary rendering**

Change configuration helpers to accept `auth_spec: dict`. Resolve a configured
cookie path from `cfg.get("auth", config_key, default_file)` plus the existing
cwd, `~/.ucrawl`, project, and user-data candidates. Validate that any declared
cookie name is present.

Implement summary rendering:

```python
def _choice_label(field: dict, value: object) -> str:
    for choice in field.get("choices", []):
        if isinstance(choice, dict) and choice.get("value") == value:
            return str(choice.get("label") or value)
    return str(value)


def build_config_summary_lines(
    guide: dict,
    config: dict,
    platform_name: str,
    keyword: str,
    save_dir: str,
) -> list[str]:
    lines = [
        f"  平台:   {platform_name}",
        f"  关键词: {keyword}",
        f"  保存到: {save_dir}",
    ]
    for field in guide.get("fields", []):
        key = field.get("key")
        if key in config:
            lines.append(
                f"  {field.get('summary_label') or key}:   "
                f"{_choice_label(field, config[key])}"
            )
    auth_summary = str(guide.get("auth", {}).get("summary") or "")
    if auth_summary:
        lines.append(f"  登录:   {auth_summary}")
    return lines
```

Use `compose_runtime_config()` in `finalize_interactive_config()` so MissAV proxy
normalization remains shared rather than checking a platform ID in CLI.

- [ ] **Step 6: Run interactive and cross-entry tests**

Run:

```powershell
python -m pytest tests/unit/cli/test_interactive_command.py tests/unit/entry/test_dispatcher.py tests/contract/entry/test_cli_entry.py tests/contract/entry/test_cross_entry_consistency.py -q
```

Expected: all pass, including external plugin manifest behavior.

- [ ] **Step 7: Commit schema-driven interactive behavior**

```powershell
git add -- cli/interactive/catalog.py cli/interactive/configuration.py cli/interactive/workflow.py tests/unit/cli/test_interactive_command.py
git commit -m "refactor(cli): drive interactive flow from plugin manifests"
git show --stat --oneline HEAD
```

### Task 4: Enforce source and timeout semantics in shared runtimes

**Files:**
- Modify: `shared/search_command_runtime.py`
- Modify: `shared/download_command_runtime.py`
- Modify: `tests/unit/shared/commands/test_runtimes.py`
- Modify: `tests/unit/cli/test_main.py`
- Modify: `tests/contract/entry/test_cross_entry_consistency.py`

**Interfaces:**
- Produces: `search_command_runtime.resolve_source(args) -> str`
- Preserves: `resolve_command_timeout(args) -> tuple[float | None, bool]`
- Changes: download argparse destination from `timeout` to `command_timeout`
- Preserves: SDK call keyword `timeout=<command_timeout>`

- [ ] **Step 1: Write failing missing-source and download-destination tests**

Add to `tests/unit/shared/commands/test_runtimes.py`:

```python
def test_missing_search_source_is_usage_error_before_dependencies():
    from shared.search_command_runtime import run_search_command

    env = self._make_env()
    args = argparse.Namespace(keyword="query")

    outcome, result = run_search_command(args, env=env)

    self.assertEqual(outcome, "usage")
    self.assertIn("--source", result["error"])
    env.get_platform_defaults.assert_not_called()
    env.selection_factory.from_cli_args.assert_not_called()
    env.CLIRunner_cls.assert_not_called()


def test_download_timeout_uses_command_timeout_destination():
    from shared.download_command_runtime import add_download_arguments

    parser = argparse.ArgumentParser()
    add_download_arguments(parser, platform_ids=("douyin",))
    args = parser.parse_args(
        [
            "https://example.test/video.mp4",
            "--source",
            "douyin",
            "--timeout",
            "45",
        ]
    )

    self.assertEqual(args.command_timeout, 45)
    self.assertFalse(hasattr(args, "timeout"))
```

Update download runtime fixtures to provide `command_timeout=300.0`.

- [ ] **Step 2: Run focused runtime tests and verify failures**

Run:

```powershell
python -m pytest tests/unit/shared/commands/test_runtimes.py -q
```

Expected: missing search source still constructs a runner with `douyin`, and
download args expose `timeout` rather than `command_timeout`.

- [ ] **Step 3: Require explicit search source**

Add:

```python
def resolve_source(args: argparse.Namespace) -> str:
    source = str(getattr(args, "source", "") or "").strip()
    if not source:
        raise ValueError("必须指定 --source 平台 ID")
    return source
```

Call it first in `validate_args()`. Use it in `build_config()` and
`run_search_command()`. Remove both expressions that reference `_platform` or
default to `douyin`.

- [ ] **Step 4: Rename the download runtime destination**

Register:

```python
parser.add_argument(
    "--timeout",
    dest="command_timeout",
    type=float,
    default=300,
    help="整次下载命令超时秒数 (默认: 300)",
)
```

In `run_download_command()`:

```python
command_timeout = getattr(args, "command_timeout", 300)
if command_timeout <= 0:
    return "usage", None, "❌ --timeout 必须大于 0"
...
result = sdk.download_video(
    ...,
    timeout=command_timeout,
)
```

- [ ] **Step 5: Update CLI and cross-entry expectations**

Update parser and mock Namespace assertions to use `command_timeout`. Assert both
generic and platform-scoped download parsers expose the same destination and
default.

- [ ] **Step 6: Run CLI/runtime/entry tests**

Run:

```powershell
python -m pytest tests/unit/shared/commands/test_runtimes.py tests/unit/cli/test_main.py tests/contract/entry/test_cross_entry_consistency.py tests/contract/cross_interface/test_cli_sdk_api.py -q
```

Expected: all pass; SDK mocks receive `timeout`, while CLI Namespaces use
`command_timeout`.

- [ ] **Step 7: Commit source and timeout contracts**

```powershell
git add -- shared/search_command_runtime.py shared/download_command_runtime.py tests/unit/shared/commands/test_runtimes.py tests/unit/cli/test_main.py tests/contract/entry/test_cross_entry_consistency.py
git commit -m "fix(cli): require source and unify command timeout semantics"
git show --stat --oneline HEAD
```

### Task 5: Move scan behavior into a shared command runtime

**Files:**
- Create: `shared/scan_command_runtime.py`
- Modify: `cli/commands/scan.py`
- Modify: `cli/main.py`
- Modify: `tests/unit/shared/commands/test_runtimes.py`
- Modify: `tests/unit/cli/test_main.py`
- Modify: `tests/architecture/test_dependency_direction.py`

**Interfaces:**
- Produces: `ScanCommandEnv`
- Produces: `add_scan_arguments(parser)`
- Produces: `resolve_scan_limit(args, env) -> int`
- Produces: `run_scan_command(args, env) -> tuple[str, dict | None, str | None]`
- Produces: `emit_result(result, pretty)`

- [ ] **Step 1: Write failing scan runtime and thin-host tests**

Add tests for:

```python
def test_scan_runtime_uses_default_limit_and_closes_sdk():
    from shared.scan_command_runtime import (
        ScanCommandEnv,
        run_scan_command,
    )

    sdk_cls = Mock()
    sdk = sdk_cls.return_value
    sdk.scan_directory.return_value = {
        "status": "ok",
        "items": [],
        "directory": "downloads",
        "total_count": 0,
        "video_count": 0,
        "image_count": 0,
    }
    env = ScanCommandEnv(
        UcrawlSDK_cls=sdk_cls,
        get_default_scan_limit=Mock(return_value=321),
    )

    outcome, result, error = run_scan_command(
        argparse.Namespace(
            directory="downloads",
            limit=None,
            quiet=True,
            pretty=False,
        ),
        env=env,
    )

    self.assertEqual(outcome, "ok")
    self.assertIsNone(error)
    sdk.scan_directory.assert_called_once_with(
        "downloads",
        scan_limit=321,
    )
    sdk.close.assert_called_once_with()
```

Add architecture assertions that `cli/commands/scan.py` imports
`shared.scan_command_runtime`, does not define `add_scan_arguments`, and stays
below 55 source lines.

- [ ] **Step 2: Run scan tests and verify the module is missing**

Run:

```powershell
python -m pytest tests/unit/shared/commands/test_runtimes.py tests/architecture/test_dependency_direction.py -q
```

Expected: `ModuleNotFoundError: shared.scan_command_runtime`.

- [ ] **Step 3: Implement `shared/scan_command_runtime.py`**

Use the same semantic-result shape as download:

```python
@dataclass(slots=True)
class ScanCommandEnv:
    UcrawlSDK_cls: Any
    get_default_scan_limit: Callable[[], int]


def resolve_scan_limit(
    args: argparse.Namespace,
    *,
    env: ScanCommandEnv,
) -> int:
    raw = (
        args.limit
        if getattr(args, "limit", None) is not None
        else env.get_default_scan_limit()
    )
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("--limit 必须是整数") from exc
    if value <= 0:
        raise ValueError("--limit 必须大于 0")
    return value
```

`run_scan_command()` validates limit before constructing SDK, creates
`UcrawlSDK(verbose=not quiet)`, always closes it, converts invalid result objects
to `error`, and returns the structured status. Move the existing JSON/pretty
rendering unchanged into `emit_result()`.

- [ ] **Step 4: Reduce the CLI scan host to dependency assembly**

`cli/commands/scan.py` should contain only:

```python
from app.config import cfg
from cli.exit_codes import exit_code_for_status
from shared import scan_command_runtime as runtime
from shared.scan_command_runtime import add_scan_arguments
from shared.sdk_runtime import UcrawlSDK


def _default_scan_limit() -> int:
    return cfg.get("download", "local_scan_limit", 1000)


def _runtime_env() -> runtime.ScanCommandEnv:
    return runtime.ScanCommandEnv(
        UcrawlSDK_cls=UcrawlSDK,
        get_default_scan_limit=_default_scan_limit,
    )


def handle_scan_command(args: argparse.Namespace) -> int:
    outcome, result, error = runtime.run_scan_command(
        args,
        env=_runtime_env(),
    )
    if error:
        sys.stderr.write(f"{error}\n")
    if result is not None:
        runtime.emit_result(
            result,
            pretty=getattr(args, "pretty", False),
        )
    return int(exit_code_for_status(outcome))
```

Import `add_scan_arguments` from shared in `cli.main`.

- [ ] **Step 5: Run scan, CLI, and architecture tests**

Run:

```powershell
python -m pytest tests/unit/shared/commands/test_runtimes.py tests/unit/cli/test_main.py tests/contract/entry/test_cli_entry.py tests/architecture/test_dependency_direction.py -q
```

Expected: all pass and the CLI scan host is thin.

- [ ] **Step 6: Commit the shared scan runtime**

```powershell
git add -- shared/scan_command_runtime.py cli/commands/scan.py cli/main.py tests/unit/shared/commands/test_runtimes.py tests/unit/cli/test_main.py tests/architecture/test_dependency_direction.py
git commit -m "refactor(cli): move scan behavior into shared runtime"
git show --stat --oneline HEAD
```

### Task 6: Delete the dead Web script duplicate and correct unit-test ownership

**Files:**
- Delete: `cli/script_runner.py`
- Delete: `tests/unit/cli/test_script_runner.py`
- Move: `tests/unit/cli/test_defaults.py` → `tests/unit/shared/test_runtime_options.py`
- Move: `tests/unit/cli/test_pipe.py` → `tests/unit/shared/test_pipe_selection.py`
- Move: `tests/unit/cli/test_runner.py` → `tests/unit/shared/test_cli_runner_runtime.py`
- Move: `tests/unit/cli/test_sdk.py` → `tests/unit/shared/test_sdk_runtime.py`
- Move: `tests/unit/cli/test_selection.py` → `tests/unit/shared/test_selection_runtime.py`
- Modify: `tests/architecture/test_dependency_direction.py`
- Verify: `tests/contract/web/test_script_api.py`

**Interfaces:**
- Preserves: `app.web.script_api` as the only Web script injection implementation
- Preserves: unit test behavior while changing canonical collection paths

- [ ] **Step 1: Add failing ownership architecture assertions**

Add:

```python
def test_web_script_injection_has_no_cli_duplicate(self) -> None:
    self.assertFalse((PROJECT_ROOT / "cli" / "script_runner.py").exists())
    self.assertTrue((PROJECT_ROOT / "app" / "web" / "script_api.py").exists())


def test_shared_runtime_tests_mirror_their_production_namespace(self) -> None:
    stale = (
        "test_defaults.py",
        "test_pipe.py",
        "test_runner.py",
        "test_sdk.py",
        "test_selection.py",
        "test_script_runner.py",
    )
    remaining = [
        name
        for name in stale
        if (PROJECT_ROOT / "tests" / "unit" / "cli" / name).exists()
    ]
    self.assertEqual(remaining, [])
```

- [ ] **Step 2: Run the architecture test and verify stale files fail**

Run:

```powershell
python -m pytest tests/architecture/test_dependency_direction.py -q
```

Expected: both new assertions fail.

- [ ] **Step 3: Delete the dead duplicate with `apply_patch`**

Use `apply_patch` delete hunks for:

```text
cli/script_runner.py
tests/unit/cli/test_script_runner.py
```

Do not change `app/web/script_api.py`; its contract suite is authoritative.

- [ ] **Step 4: Move each shared test with `apply_patch` move hunks**

Use `*** Move to:` for each of the five files. Update only module docstrings that
still describe the tests as CLI-owned; keep test bodies and imports unchanged.

- [ ] **Step 5: Run moved tests, Web script tests, taxonomy, and collection**

Run:

```powershell
python -m pytest tests/unit/shared/test_runtime_options.py tests/unit/shared/test_pipe_selection.py tests/unit/shared/test_cli_runner_runtime.py tests/unit/shared/test_sdk_runtime.py tests/unit/shared/test_selection_runtime.py tests/contract/web/test_script_api.py tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q
python tests/launcher.py --list
python -m pytest tests --collect-only -q
```

Expected: tests pass, all eight suites list successfully, and collection has no
duplicate modules or import errors.

- [ ] **Step 6: Commit dead-code deletion and taxonomy migration**

```powershell
git add -u -- cli/script_runner.py tests/unit/cli
git add -- tests/unit/shared tests/architecture/test_dependency_direction.py
git commit -m "refactor: align CLI code and tests with runtime ownership"
git show --stat --oneline HEAD
```

### Task 7: Publish the active timeout, plugin, scan, and package architecture

**Files:**
- Modify: `cli/README.md`
- Modify: `docs/cli/cli-guide.md`
- Modify: `docs/guides/testing.md`
- Modify: `cli/skill/SKILL.md`
- Modify: `mermaid/02-entrypoints-and-hosts.md`
- Modify: `mermaid/07-cli-sdk-runtime.md`
- Modify: `tests/contract/cli/test_skill_contract.py`
- Modify: `tests/architecture/test_dependency_direction.py`

**Interfaces:**
- Documents: `--timeout` as whole-command timeout for search/download
- Documents: plugin `interactive` manifest extension
- Documents: shared scan runtime and `ucrawl` public SDK boundary
- Guards: no stale CLI re-export diagram or old unit-test paths

- [ ] **Step 1: Write failing active-document contract assertions**

Add architecture checks:

```python
def test_active_cli_runtime_diagram_tracks_current_boundaries(self) -> None:
    diagram = (
        PROJECT_ROOT / "mermaid" / "07-cli-sdk-runtime.md"
    ).read_text(encoding="utf-8")

    self.assertIn("shared.scan_command_runtime", diagram)
    self.assertIn("ucrawl/__init__.py", diagram)
    self.assertIn("plugin manifest", diagram.lower())
    self.assertNotIn("公开再导出 + 历史别名", diagram)
    self.assertNotIn("PackageInit --> SDKRt", diagram)


def test_active_testing_guide_uses_shared_runtime_test_paths(self) -> None:
    guide = (
        PROJECT_ROOT / "docs" / "guides" / "testing.md"
    ).read_text(encoding="utf-8")

    self.assertIn("tests/unit/shared/test_sdk_runtime.py", guide)
    self.assertIn("tests/unit/shared/test_cli_runner_runtime.py", guide)
    self.assertNotIn("tests/unit/cli/test_sdk.py", guide)
    self.assertNotIn("历史模块路径兼容别名", guide)
```

Extend the skill contract so download timeout documentation includes
`整次下载命令`.

- [ ] **Step 2: Run documentation contracts and verify stale text fails**

Run:

```powershell
python -m pytest tests/architecture/test_dependency_direction.py tests/contract/cli/test_skill_contract.py -q
```

Expected: diagram, guide path, and timeout-copy assertions fail.

- [ ] **Step 3: Update active CLI and Skill guidance**

State consistently:

```text
search --http-timeout: spider HTTP request timeout
search/interactive --timeout: whole-command deadline, unlimited by default
download --timeout: whole direct-download command deadline, 300 seconds by default
```

Explain that `ucrawl platforms` and interactive both consume plugin manifests;
external plugins can provide guide, fields, and auth metadata.

- [ ] **Step 4: Update the testing guide paths**

Replace the five old `tests/unit/cli` paths with their new
`tests/unit/shared` paths. Remove the obsolete statement that
`cli/__init__.py` owns historical SDK aliases. Keep `tests/unit/cli/test_main.py`
and interactive/platform catalog tests under CLI.

- [ ] **Step 5: Rewrite the CLI runtime Mermaid**

The first graph must show:

```text
entry.cli_entry -> cli.main -> cli.commands
cli.commands.search -> shared.search_command_runtime
cli.commands.download -> shared.download_command_runtime
cli.commands.scan -> shared.scan_command_runtime
cli.interactive -> plugin manifest + shared runner/SDK/selection
ucrawl/__init__.py -> shared.sdk_runtime/selection/runner
cli/__init__.py -> shared.version only
app.web.script_api -> Web --script
```

The command-dispatch graph must route scan through
`shared.scan_command_runtime`. The SDK graph must show structured result
dictionaries rather than obsolete list-only return types. Remove GUI selection
from the shared selection strategy diagram because it lives under `app.ui`.

Update the smaller shared-runtime graph in `mermaid/02-entrypoints-and-hosts.md`
with the same scan and plugin-manifest nodes.

- [ ] **Step 6: Run docs, architecture, and help checks**

Run:

```powershell
python -m pytest tests/architecture/test_dependency_direction.py tests/contract/cli/test_skill_contract.py -q
python -m cli search --help
python -m cli download --help
python -m cli scan --help
```

Expected: tests pass; help text has unambiguous timeout and scan options.

- [ ] **Step 7: Commit active documentation**

```powershell
git add -- cli/README.md docs/cli/cli-guide.md docs/guides/testing.md cli/skill/SKILL.md mermaid/02-entrypoints-and-hosts.md mermaid/07-cli-sdk-runtime.md tests/contract/cli/test_skill_contract.py tests/architecture/test_dependency_direction.py
git commit -m "docs: publish plugin-driven CLI runtime architecture"
git show --stat --oneline HEAD
```

### Task 8: Perform requirement-by-requirement verification

**Files:**
- Verify all files changed by Tasks 1-7
- Do not modify unrelated dirty files

**Interfaces:**
- Proves every acceptance criterion from the approved design

- [ ] **Step 1: Run focused plugin/interactive/runtime suites**

```powershell
python -m pytest tests/unit/app/core/plugins tests/unit/app/services/test_frontend_settings_adapter.py tests/unit/cli tests/unit/shared/commands tests/unit/shared/test_runtime_options.py tests/unit/shared/test_pipe_selection.py tests/unit/shared/test_cli_runner_runtime.py tests/unit/shared/test_sdk_runtime.py tests/unit/shared/test_selection_runtime.py -q
```

Expected: all pass.

- [ ] **Step 2: Run CLI, Web, SDK, and entry contracts**

```powershell
python -m pytest tests/contract/cli tests/contract/web/test_script_api.py tests/contract/cross_interface/test_cli_sdk_api.py tests/contract/entry/test_cli_entry.py tests/contract/entry/test_cross_entry_consistency.py tests/contract/entry/test_runtime_contracts.py -q
```

Expected: all pass.

- [ ] **Step 3: Run architecture, taxonomy, catalog, and collection gates**

```powershell
python -m pytest tests/architecture tests/testkit/test_catalog.py -q
python tests/launcher.py --list
python -m pytest tests --collect-only -q
```

Expected: all pass, eight suite cards are listed, and collection succeeds.

- [ ] **Step 4: Run static checks on every touched namespace**

```powershell
python -m ruff check app/core/plugins app/services/frontend_settings_adapter.py app/services/frontend_state_service.py app/web/controller.py cli shared ucrawl tests/unit/app/core/plugins tests/unit/app/services tests/unit/cli tests/unit/shared tests/contract/cli tests/contract/cross_interface tests/contract/entry tests/architecture
git diff --check origin/main...HEAD
```

Expected: no Ruff or whitespace errors.

- [ ] **Step 5: Run the full repository test suite**

```powershell
python -X faulthandler -m pytest -q --timeout=90 --timeout-method=thread --session-timeout=1500
```

Expected: full suite passes; existing documented skips/warnings may remain but no
new failure, collection error, or timeout is introduced.

- [ ] **Step 6: Audit every explicit requirement against current evidence**

Confirm with repository searches:

```powershell
rg -n 'getattr\\(args, "_platform"|\"douyin\"\\)' shared/search_command_runtime.py
rg -n '_PLATFORM_GUIDE|_AUTH_FILE_MAP|_REQUIRED_COOKIE_KEY|platform_id ==|platform_id in' cli/interactive
rg -n 'cli\\.script_runner|from cli import script_runner' cli entry app tests
rg -n 'tests/unit/cli/test_(defaults|pipe|runner|sdk|selection|script_runner)\\.py' docs mermaid README.md README_EN.md
rg -n '公开再导出 \\+ 历史别名|PackageInit --> SDKRt' mermaid/07-cli-sdk-runtime.md
```

Expected: all commands return no matches except historical documents under
`docs/superpowers/`, which are intentionally excluded from active-document checks.

- [ ] **Step 7: Review commits and working tree**

```powershell
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git status --short --branch
```

Expected: only the known unrelated dirty code-report files remain uncommitted; all
task files are committed.

- [ ] **Step 8: Mark the implementation complete only after all evidence passes**

Report:

- exact commits;
- focused and full test totals;
- CLI help/manual source-missing proof;
- the unchanged unrelated dirty files;
- any pre-existing warnings or skips.
