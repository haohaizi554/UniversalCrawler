# 发布构建面板与统一版本契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `packaging/build_release.py` 升级为同时支持工业化 Qt 面板和无界面流水线的唯一发布入口，并以 `shared/version.py` 作为 GUI、WebUI、Python 包、安装器和发布资产的唯一版本事实源。

**Architecture:** `packaging/build_release.py` 只保留入口分流和现有构建原语，新增 `packaging/release_tool/` 小模块承载版本事务、模式判定、事件协议、代理环境、GitHub Release 发布、工作流编排和 Qt 面板。面板通过 `QProcess` 启动同一脚本的 `--headless --request-file` 子进程，使用带固定前缀的 JSONL 事件驱动真实进度，同时把普通 stdout/stderr 作为脱敏日志显示和落盘。

**Tech Stack:** Python 3.10+、PyQt6、setuptools PEP 621 dynamic metadata、Inno Setup、PyInstaller、Git/GitHub CLI、Ed25519 更新清单、pytest、Ruff。

## Global Constraints

- `shared/version.py::__version__` 是唯一可编辑的产品版本值。
- 不新增运行时依赖，不复制现有 PyInstaller、Inno Setup、更新清单或 Ed25519 算法。
- 直接调用 `main([])` 必须保持当前无界面正式流水线语义；仅脚本无参数启动时打开 Qt 面板。
- 本地调试构建必须保留仓库中的生产公钥，但不得生成本地清单、签名或临时密钥。
- 标签、推送、签名、Release 创建、资产上传、同版本覆盖默认全部不勾选。
- 私钥内容、GitHub 凭据、Cookie、Authorization 和代理认证信息不得进入命令行、事件流、面板日志、持久日志、构建目录或 Git。
- Release 上传前必须具备安装包、`latest.json` 和 `latest.json.sig`；公开审计公钥作为独立可选资产上传。
- 远端版本查询失败时不得猜测发布模式；只允许用户显式启用离线本地调试。
- 总进度只能由真实阶段事件推进，不得使用定时器伪造。
- 面板使用 `WindowChromeFrame`、`FramelessWindowChromeController`、`apply_application_theme()` 和 `theme_colors()`，不得维护第二套硬编码主题。
- 维护工具图标使用 `bag_15483236.png` 生成 16、20、24、32、40、48、64、128、256 像素透明 ICO，不替换主程序图标。
- 版本应用是显式、原子、可回滚的工作区变更；后续构建失败不自动回滚已确认的版本变更。
- 历史 Release、复盘、测试夹具中的旧版本样例不得被全局替换。

---

## File Map

### 新增文件

- `packaging/release_tool/__init__.py`
  - 仅声明维护工具内部包，不导出新的产品公共 API。
- `packaging/release_tool/versioning.py`
  - 规范化 SemVer、读取唯一版本事实源、规划并原子应用版本投影、验证各消费者一致性。
- `packaging/release_tool/models.py`
  - 不可变的构建请求、远端版本、预检结果、构建结果和阶段枚举。
- `packaging/release_tool/modes.py`
  - 纯函数判定本地调试、同版本重构、同版本修复、新版本构建和远端未知状态。
- `packaging/release_tool/events.py`
  - JSONL 事件编码/解析、单调序号、日志脱敏、持久日志写入。
- `packaging/release_tool/proxy.py`
  - 把现有代理预设转换为子进程环境，不复制预设名称和端口。
- `packaging/release_tool/remote.py`
  - 只读查询 GitHub 最新 Release、检查 GitHub CLI 能力和远端资产元数据。
- `packaging/release_tool/publisher.py`
  - 通过参数数组调用 Git/GitHub CLI，幂等创建或修复 Release、上传大资产并回读验证。
- `packaging/release_tool/runner.py`
  - 预检、版本同步、构建、签名、Git、上传和验证的状态机编排。
- `packaging/release_tool/panel.py`
  - 主题化独立 Qt 窗口、表单约束、`QProcess` 生命周期、日志和进度。
- `packaging/release_tool/icon_builder.py`
  - 使用 PyQt 图像能力和标准 ICO 目录结构生成多尺寸图标。
- `packaging/release_tool/assets/release-builder.png`
  - 从仓库根目录迁入的原始透明 PNG。
- `packaging/release_tool/assets/release-builder.ico`
  - 由 `icon_builder.py` 可重复生成的维护工具图标。
- `tests/release/packaging/test_version_contract.py`
  - 唯一版本事实源、投影事务、Inno/FastAPI/Web 静态兜底和 CI 契约测试。
- `tests/release/packaging/test_release_tool_modes.py`
  - 模式矩阵与请求约束测试。
- `tests/release/packaging/test_release_tool_events.py`
  - 事件协议、脱敏和有界日志测试。
- `tests/release/packaging/test_release_tool_proxy.py`
  - 代理预设、直连清理和自定义端点测试。
- `tests/release/packaging/test_release_tool_remote.py`
  - GitHub 只读查询与远端未知降级测试。
- `tests/release/packaging/test_release_tool_publisher.py`
  - Git/GitHub CLI 参数、幂等上传和回读校验测试。
- `tests/release/packaging/test_release_tool_runner.py`
  - 阶段顺序、跳过、失败、取消和最终结果测试。
- `tests/release/packaging/test_release_builder_panel.py`
  - offscreen Qt 面板、主题、约束、事件消费和退出判定测试。
- `tests/release/packaging/test_release_tool_icon.py`
  - ICO 目录项和尺寸集合测试。
- `docs/guides/release-builder.md`
  - 中文维护者操作指南、安全边界和本地调试/远端发布说明。

### 修改文件

- `packaging/build_release.py`
  - 增加脚本入口分流、请求文件入口、结构化事件适配和工作流装配；保留现有构建原语。
- `packaging/project_meta.py`
  - 从 `shared.version` 读取版本，不再解析 `pyproject.toml` 的静态版本。
- `packaging/installer.iss`
  - 缺少 `/DAppVersion` 时直接编译失败。
- `pyproject.toml`
  - 改为 PEP 621 动态版本。
- `app/web/server.py`
  - FastAPI 元数据和首帧 HTML 版本注入读取 `shared.version.__version__`。
- `app/web/static/index.html`
  - 删除旧版本静态常量，增加首帧版本占位符。
- `app/web/static/app.js`
  - 初始状态和异常兜底不再回退到旧版本字符串。
- `app/ui/main_window.py`
  - 删除版本常量兜底，统一读取共享版本。
- `app/ui/layout/status_bar.py`
  - 删除状态栏旧版本兜底。
- `app/services/frontend_state_service.py`
  - 删除导入失败时写死版本的回退。
- `app/services/frontend_mock_snapshot.py`
  - mock 当前版本从共享版本派生。
- `app/core/plugins/run_options.py`
  - 增加通用 `normalize_proxy_url()`，保留原 `build_missav_proxy_url()` 兼容入口。
- `.github/workflows/python-tests.yml`
  - wheel 元数据断言从 `shared.version.__version__` 动态读取。
- `README.md`
- `README_EN.md`
- `docs/README.md`
- `cli/skill/SKILL.md`
  - 作为明确允许的当前版本投影，由版本事务精确更新。
- `tests/release/packaging/test_assets.py`
  - 更新动态版本、Inno fail-closed 和图标资产契约。
- `tests/release/packaging/test_release_pipeline.py`
  - 保留旧 `main([])` 语义并覆盖新请求入口。
- `docs/releases/v3.6.21.md`
  - 补充面板作为后续维护工具的说明，不改既有发布资产事实。

---

### Task 1: 建立唯一版本事实源和原子投影事务

**Files:**
- Create: `packaging/release_tool/__init__.py`
- Create: `packaging/release_tool/versioning.py`
- Create: `tests/release/packaging/test_version_contract.py`
- Modify: `shared/version.py`
- Modify: `pyproject.toml`
- Modify: `packaging/project_meta.py`
- Modify: `packaging/installer.iss`
- Modify: `.github/workflows/python-tests.yml`

**Interfaces:**
- Produces: `normalize_version(value: str) -> str`
- Produces: `read_project_version(project_root: Path) -> str`
- Produces: `plan_version_update(target_version: str, project_root: Path) -> VersionUpdatePlan`
- Produces: `apply_version_update(plan: VersionUpdatePlan) -> VersionUpdateResult`
- Produces: `verify_version_contract(project_root: Path, expected_version: str) -> tuple[str, ...]`
- Produces: immutable `VersionFileChange`, `VersionUpdatePlan`, `VersionUpdateResult`

- [ ] **Step 1: 写唯一版本与动态包元数据失败测试**

```python
def test_pyproject_uses_shared_version_as_dynamic_metadata():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "shared.version.__version__"
    }


def test_project_meta_imports_the_canonical_version():
    source = (PROJECT_ROOT / "packaging/project_meta.py").read_text(encoding="utf-8")
    assert "from shared.version import __version__" in source
    assert "PACKAGE_VERSION = __version__" in source
    assert '_project_field("version")' not in source


def test_inno_setup_requires_an_injected_app_version():
    source = (PROJECT_ROOT / "packaging/installer.iss").read_text(encoding="utf-8")
    assert "#ifndef AppVersion" in source
    assert "#error AppVersion must be supplied by build_installer.py" in source
    assert '#define AppVersion "3.' not in source
```

- [ ] **Step 2: 运行测试并确认静态版本契约失败**

Run: `python -m pytest tests/release/packaging/test_version_contract.py -v`

Expected: FAIL，指出 `pyproject.toml` 仍有静态 `version`、`project_meta.py` 仍解析字段、Inno 仍有版本回退。

- [ ] **Step 3: 把 Python 包和安装器改为唯一版本源**

```toml
[project]
name = "ucrawl"
dynamic = ["version"]

[tool.setuptools.dynamic]
version = {attr = "shared.version.__version__"}
```

```python
# packaging/project_meta.py
from shared.version import __version__

PACKAGE_NAME = _project_field("name")
PACKAGE_VERSION = __version__
```

```iss
#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.py
#endif
```

CI 的 wheel 隔离安装断言改为：

```yaml
python -c "from importlib.metadata import version; from shared.version import __version__; assert version('ucrawl') == __version__"
```

- [ ] **Step 4: 写版本规范化、精确投影和回滚失败测试**

```python
def test_version_update_changes_only_the_allowlisted_current_version_projections(tmp_path):
    root = make_version_fixture(tmp_path, current="3.6.21")
    historical = root / "docs/releases/v3.6.14.md"
    historical.write_text("v3.6.14", encoding="utf-8")

    result = apply_version_update(plan_version_update("3.6.22", root))

    assert result.previous_version == "3.6.21"
    assert result.target_version == "3.6.22"
    assert historical.read_text(encoding="utf-8") == "v3.6.14"
    assert read_project_version(root) == "3.6.22"
    assert set(result.changed_files) == {
        root / "shared/version.py",
        root / "README.md",
        root / "README_EN.md",
        root / "docs/README.md",
        root / "cli/skill/SKILL.md",
    }


def test_version_update_rolls_back_every_file_when_replace_fails(tmp_path, monkeypatch):
    root = make_version_fixture(tmp_path, current="3.6.21")
    before = snapshot_allowlisted_files(root)
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)
    with pytest.raises(VersionUpdateError, match="rolled back"):
        apply_version_update(plan_version_update("3.6.22", root))
    assert snapshot_allowlisted_files(root) == before
```

- [ ] **Step 5: 实现版本事务**

```python
SEMVER_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class VersionFileChange:
    path: Path
    before: str
    after: str


@dataclass(frozen=True)
class VersionUpdatePlan:
    project_root: Path
    previous_version: str
    target_version: str
    changes: tuple[VersionFileChange, ...]


@dataclass(frozen=True)
class VersionUpdateResult:
    previous_version: str
    target_version: str
    changed_files: tuple[Path, ...]


def normalize_version(value: str) -> str:
    match = SEMVER_RE.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError("version must use MAJOR.MINOR.PATCH")
    return ".".join(match.groups())
```

`plan_version_update()` 使用五个具名投影规则，每个规则要求旧值恰好匹配；出现零匹配或多匹配时拒绝写入。`apply_version_update()` 先在同目录写入唯一临时文件并 `flush + fsync`，再逐个 `os.replace()`；任一替换失败时使用保存的 `before` 内容原子恢复已经替换的文件，并抛出 `VersionUpdateError`。

- [ ] **Step 6: 运行版本契约测试**

Run: `python -m pytest tests/release/packaging/test_version_contract.py tests/release/packaging/test_assets.py::ProjectMetaTests -v`

Expected: PASS。

- [ ] **Step 7: 提交唯一版本契约**

```powershell
git add shared/version.py pyproject.toml packaging/project_meta.py packaging/installer.iss packaging/release_tool/__init__.py packaging/release_tool/versioning.py tests/release/packaging/test_version_contract.py tests/release/packaging/test_assets.py .github/workflows/python-tests.yml
git commit -m "feat: centralize release version contract"
```

---

### Task 2: 消除 GUI、WebUI 和运行时版本兜底漂移

**Files:**
- Modify: `app/web/server.py`
- Modify: `app/web/static/index.html`
- Modify: `app/web/static/app.js`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/layout/status_bar.py`
- Modify: `app/services/frontend_state_service.py`
- Modify: `app/services/frontend_mock_snapshot.py`
- Modify: `tests/release/packaging/test_version_contract.py`

**Interfaces:**
- Consumes: `shared.version.__version__`
- Produces: `_configured_index_html(index_path, config_manager) -> str` 同时注入主题和 `__UCRAWL_VERSION__`
- Produces: 所有 GUI/Web 状态版本统一为 `f"v{__version__}"`

- [ ] **Step 1: 写运行时消费者不含硬编码版本的失败测试**

```python
@pytest.mark.parametrize(
    "relative_path",
    [
        "app/web/server.py",
        "app/web/static/index.html",
        "app/web/static/app.js",
        "app/ui/main_window.py",
        "app/ui/layout/status_bar.py",
        "app/services/frontend_state_service.py",
        "app/services/frontend_mock_snapshot.py",
    ],
)
def test_runtime_version_consumers_do_not_embed_product_versions(relative_path):
    source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    assert re.search(r"\bv?3\.\d+\.\d+\b", source) is None


def test_server_injects_canonical_version_into_first_frame_html(tmp_path):
    index = tmp_path / "index.html"
    index.write_text('<html data-theme="light">__UCRAWL_VERSION__</html>', encoding="utf-8")
    html = _configured_index_html(index, FakeConfig(theme="dark"))
    assert 'data-theme="dark"' in html
    assert "__UCRAWL_VERSION__" not in html
    assert f"v{__version__}" in html
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/release/packaging/test_version_contract.py -k "runtime_version or injects_canonical" -v`

Expected: FAIL，列出当前 FastAPI、GUI 状态栏和 Web 静态文件中的版本常量。

- [ ] **Step 3: 统一运行时版本读取**

```python
# app/web/server.py
from shared.version import __version__

def _configured_index_html(index_path, config_manager) -> str:
    reload_if_changed = getattr(config_manager, "reload_if_changed", None)
    if callable(reload_if_changed):
        reload_if_changed()
    theme = str(config_manager.get("common", "theme", "light") or "light").lower()
    if theme not in {"light", "dark"}:
        theme = "light"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace('data-theme="light"', f'data-theme="{theme}"', 1)
    return html.replace("__UCRAWL_VERSION__", f"v{__version__}")

def create_app(lifespan=None, *, access_token: str | None = None) -> FastAPI:
    app = FastAPI(title="Universal Crawler Pro", version=__version__, lifespan=lifespan)
```

HTML 使用：

```html
<button
  id="statusVersion"
  class="status-version-button"
  type="button"
  onclick="showUpdateCheckModal()"
  title="检查更新"
>__UCRAWL_VERSION__</button>
```

JavaScript 使用中性占位：

```javascript
app_status: {
  running_state: "空闲中",
  download_speed: "0 B/s",
  completed_count: 0,
  failed_count: 0,
  version: "",
}
```

状态更新使用：

```javascript
const version = String(status.version || "").trim();
if (version) byId("statusVersion").textContent = version;
```

GUI、状态服务和 mock 快照均直接使用 `f"v{__version__}"`，不使用导入异常时的旧版本字符串。

- [ ] **Step 4: 运行版本消费者和 Web 首帧测试**

Run: `python -m pytest tests/release/packaging/test_version_contract.py tests/unit/app/web/test_server.py -v`

Expected: PASS。

- [ ] **Step 5: 提交运行时版本统一**

```powershell
git add app/web/server.py app/web/static/index.html app/web/static/app.js app/ui/main_window.py app/ui/layout/status_bar.py app/services/frontend_state_service.py app/services/frontend_mock_snapshot.py tests/release/packaging/test_version_contract.py
git commit -m "fix: derive frontend versions from shared source"
```

---

### Task 3: 定义发布请求、模式矩阵和约束

**Files:**
- Create: `packaging/release_tool/models.py`
- Create: `packaging/release_tool/modes.py`
- Create: `tests/release/packaging/test_release_tool_modes.py`

**Interfaces:**
- Consumes: `normalize_version()`
- Produces: `ReleaseMode`, `ReleaseStage`, `RemoteReleaseInfo`, `BuildRequest`, `PreflightResult`, `ReleaseResult`
- Produces: `resolve_release_mode(target_version, remote, *, same_release_repair, offline_debug) -> ReleaseMode`
- Produces: `validate_build_request(request: BuildRequest) -> tuple[str, ...]`

- [ ] **Step 1: 写完整模式矩阵失败测试**

```python
@pytest.mark.parametrize(
    ("target", "remote", "repair", "offline", "expected"),
    [
        ("3.6.20", RemoteReleaseInfo.available("3.6.21"), False, False, ReleaseMode.LOCAL_DEBUG),
        ("3.6.21", RemoteReleaseInfo.available("3.6.21"), False, False, ReleaseMode.LOCAL_REBUILD),
        ("3.6.21", RemoteReleaseInfo.available("3.6.21"), True, False, ReleaseMode.SAME_RELEASE_REPAIR),
        ("3.6.22", RemoteReleaseInfo.available("3.6.21"), False, False, ReleaseMode.NEW_RELEASE),
        ("3.6.22", RemoteReleaseInfo.unavailable("timeout"), False, True, ReleaseMode.OFFLINE_DEBUG),
    ],
)
def test_release_mode_matrix(target, remote, repair, offline, expected):
    assert resolve_release_mode(
        target,
        remote,
        same_release_repair=repair,
        offline_debug=offline,
    ) is expected


def test_remote_unknown_blocks_remote_writes():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.unavailable("timeout"),
        upload_release_assets=True,
    )
    assert "remote release state is unknown" in validate_build_request(request)


def test_dry_run_rejects_every_side_effecting_option():
    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        dry_run=True,
        sign_manifest=True,
        commit_version_changes=True,
        upload_release_assets=True,
    )
    errors = validate_build_request(request)
    assert "dry run cannot sign manifests" in errors
    assert "dry run cannot commit version changes" in errors
    assert "dry run cannot upload release assets" in errors
```

- [ ] **Step 2: 运行模式测试并确认模块缺失**

Run: `python -m pytest tests/release/packaging/test_release_tool_modes.py -v`

Expected: FAIL with import/module errors。

- [ ] **Step 3: 实现不可变模型和模式纯函数**

```python
class ReleaseMode(StrEnum):
    LOCAL_DEBUG = "local_debug"
    LOCAL_REBUILD = "local_rebuild"
    SAME_RELEASE_REPAIR = "same_release_repair"
    NEW_RELEASE = "new_release"
    OFFLINE_DEBUG = "offline_debug"


class ReleaseStage(StrEnum):
    IDLE = "idle"
    CHECKING_REMOTE = "checking_remote"
    PREFLIGHT = "preflight"
    VERSION_SYNC = "version_sync"
    BUILDING_PORTABLE = "building_portable"
    BUILDING_INSTALLER = "building_installer"
    SIGNING = "signing"
    GIT = "git"
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

`BuildRequest` 至少包含：

```python
@dataclass(frozen=True)
class BuildRequest:
    target_version: str
    repository: str = "haohaizi554/UniversalCrawler"
    release_notes_path: str = ""
    output_root: str = ""
    build_portable: bool = True
    build_installer: bool = True
    run_smoke_tests: bool = True
    dry_run: bool = False
    same_release_repair: bool = False
    offline_debug: bool = False
    apply_version: bool = True
    generate_manifest_key: bool = False
    rotate_trust_anchor: bool = False
    private_key_path: str = ""
    sign_manifest: bool = False
    commit_version_changes: bool = False
    push_main: bool = False
    create_or_reuse_tag: bool = False
    create_or_update_release: bool = False
    upload_release_assets: bool = False
    upload_public_key: bool = False
    verify_remote_assets: bool = False
    proxy_label: str = "系统代理"
    custom_proxy: str = ""
    remote: RemoteReleaseInfo = field(default_factory=RemoteReleaseInfo.unknown)
```

约束函数返回稳定顺序的错误字符串；上传要求签名、私钥、Release 操作和远端回读；本地模式拒绝所有远端写选项；轮换信任锚要求生成密钥并重建安装器。`dry_run=True` 时拒绝签名、Git、上传、公钥轮换和密钥生成，只允许远端只读检查、版本变更规划、预检与事件输出。

- [ ] **Step 4: 运行模式测试**

Run: `python -m pytest tests/release/packaging/test_release_tool_modes.py -v`

Expected: PASS。

- [ ] **Step 5: 提交模型和模式矩阵**

```powershell
git add packaging/release_tool/models.py packaging/release_tool/modes.py tests/release/packaging/test_release_tool_modes.py
git commit -m "feat: define release request mode matrix"
```

---

### Task 4: 建立结构化事件、脱敏和持久日志协议

**Files:**
- Create: `packaging/release_tool/events.py`
- Create: `tests/release/packaging/test_release_tool_events.py`

**Interfaces:**
- Consumes: `ReleaseStage`
- Produces: `EVENT_PREFIX = "@@UCRAWL_RELEASE_EVENT@@"`
- Produces: `ReleaseEvent`
- Produces: `ReleaseEventEmitter.emit(kind, *, stage, progress, message, data) -> ReleaseEvent`
- Produces: `parse_event_line(line: str) -> ReleaseEvent | None`
- Produces: `redact_release_text(text: str) -> str`
- Produces: `ReleaseLogWriter(path: Path).write_line(text: str) -> None`

- [ ] **Step 1: 写事件往返、单调进度和秘密脱敏失败测试**

```python
def test_event_round_trip_uses_fixed_prefix_and_monotonic_sequence(capsys):
    emitter = ReleaseEventEmitter(stream=sys.stdout, clock=lambda: FIXED_UTC)
    first = emitter.emit("stage", stage=ReleaseStage.PREFLIGHT, progress=10)
    second = emitter.emit("progress", stage=ReleaseStage.PREFLIGHT, progress=15)
    lines = capsys.readouterr().out.splitlines()
    assert all(line.startswith(EVENT_PREFIX) for line in lines)
    assert [parse_event_line(line).sequence for line in lines] == [1, 2]
    assert second.progress >= first.progress


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz",
        "Cookie: session=top-secret",
        "https://alice:password@127.0.0.1:7890",
        "-----BEGIN " + "PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----",
    ],
)
def test_release_logs_redact_sensitive_material(secret):
    redacted = redact_release_text(secret)
    assert secret not in redacted
    assert "[REDACTED]" in redacted
```

- [ ] **Step 2: 运行事件测试并确认失败**

Run: `python -m pytest tests/release/packaging/test_release_tool_events.py -v`

Expected: FAIL with missing module。

- [ ] **Step 3: 实现事件和日志**

```python
@dataclass(frozen=True)
class ReleaseEvent:
    kind: str
    sequence: int
    timestamp: str
    stage: ReleaseStage
    progress: int
    message: str = ""
    data: Mapping[str, JSONValue] = field(default_factory=dict)


def parse_event_line(line: str) -> ReleaseEvent | None:
    text = str(line).rstrip("\r\n")
    if not text.startswith(EVENT_PREFIX):
        return None
    payload = json.loads(text[len(EVENT_PREFIX):])
    return ReleaseEvent.from_payload(payload)
```

`ReleaseEventEmitter` 在锁内增加序号和保存最后进度；进度范围为 0..100 且不得下降。所有 message/data 字符串先经 `redact_release_text()`。`ReleaseLogWriter` 以 UTF-8 追加写、每行 flush，写失败抛出具名 `ReleaseLogError` 供 runner 降级为 warning 事件。

- [ ] **Step 4: 运行事件测试**

Run: `python -m pytest tests/release/packaging/test_release_tool_events.py -v`

Expected: PASS。

- [ ] **Step 5: 提交事件协议**

```powershell
git add packaging/release_tool/events.py tests/release/packaging/test_release_tool_events.py
git commit -m "feat: add structured release event stream"
```

---

### Task 5: 复用项目代理契约并隔离子进程环境

**Files:**
- Create: `packaging/release_tool/proxy.py`
- Create: `tests/release/packaging/test_release_tool_proxy.py`
- Modify: `app/core/plugins/run_options.py`
- Modify: existing proxy unit tests under `tests/unit/app/core/plugins/`

**Interfaces:**
- Produces: `normalize_proxy_url(proxy_str: str) -> str`
- Preserves: `build_missav_proxy_url(proxy_str: str) -> str`
- Produces: `ProxySelection`
- Produces: `project_proxy_options() -> tuple[dict[str, str], ...]`
- Produces: `build_proxy_environment(selection: ProxySelection, base_env: Mapping[str, str]) -> dict[str, str]`

- [ ] **Step 1: 写兼容别名和环境矩阵失败测试**

```python
def test_legacy_missav_proxy_builder_delegates_to_generic_normalizer():
    assert build_missav_proxy_url("Clash (7890)") == normalize_proxy_url("Clash (7890)")


def test_direct_proxy_choice_removes_upper_and_lowercase_proxy_variables():
    base = {
        "HTTP_PROXY": "http://old",
        "https_proxy": "http://old",
        "NO_PROXY": "localhost",
    }
    env = build_proxy_environment(ProxySelection.direct(), base)
    assert "HTTP_PROXY" not in env
    assert "https_proxy" not in env
    assert env["NO_PROXY"] == "localhost"


def test_clash_proxy_choice_sets_all_supported_variables():
    env = build_proxy_environment(
        ProxySelection(label="Clash (7890)"),
        {},
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert env[name] == "http://127.0.0.1:7890"
```

- [ ] **Step 2: 运行代理测试并确认失败**

Run: `python -m pytest tests/release/packaging/test_release_tool_proxy.py -v`

Expected: FAIL，缺少通用 normalizer 和 release proxy 模块。

- [ ] **Step 3: 提取通用 normalizer 并构建环境**

```python
def normalize_proxy_url(proxy_str: str) -> str:
    normalized = str(proxy_str or "").strip().strip("\"'")
    if normalized in PROXY_PRESET_URLS:
        return PROXY_PRESET_URLS[normalized]
    if not normalized or normalized == "自定义":
        return ""
    lowered = normalized.lower()
    if lowered in {"system", "system proxy", "direct", "none", "no proxy"}:
        return ""
    if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
        parsed = urlparse(normalized)
        return normalized if parsed.hostname and parsed.port else ""
    port_hint = _proxy_port_hint(normalized)
    if port_hint:
        return f"http://127.0.0.1:{port_hint}"
    if ":" in normalized:
        if normalized.startswith(":"):
            return ""
        return f"http://{normalized}"
    return "http://127.0.0.1:7890"


def build_missav_proxy_url(proxy_str: str) -> str:
    return normalize_proxy_url(proxy_str)
```

`project_proxy_options()` 直接调用 `app.config.settings.proxy_app_options()` 并返回不可变副本；`build_proxy_environment()` 对系统代理原样继承，对直连删除六个代理变量，对预设/自定义端点调用 `normalize_proxy_url()` 后设置六个变量。无效自定义端点抛 `ValueError`。

- [ ] **Step 4: 运行代理测试**

Run: `python -m pytest tests/release/packaging/test_release_tool_proxy.py tests/unit/app/core/plugins -q`

Expected: PASS。

- [ ] **Step 5: 提交代理契约**

```powershell
git add app/core/plugins/run_options.py packaging/release_tool/proxy.py tests/release/packaging/test_release_tool_proxy.py tests/unit/app/core/plugins
git commit -m "refactor: share proxy normalization with release tool"
```

---

### Task 6: 实现远端版本查询和 GitHub Release 大资产发布

**Files:**
- Create: `packaging/release_tool/remote.py`
- Create: `packaging/release_tool/publisher.py`
- Create: `tests/release/packaging/test_release_tool_remote.py`
- Create: `tests/release/packaging/test_release_tool_publisher.py`

**Interfaces:**
- Consumes: `RemoteReleaseInfo`, proxy environment, `redact_release_text()`
- Produces: `fetch_latest_release(repository: str, *, environment: Mapping[str, str], timeout_seconds: float = 10.0) -> RemoteReleaseInfo`
- Produces: `ReleaseAssetInfo`
- Produces: `GitHubReleasePublisher(repository, environment, output)`
- Produces: `GitHubReleasePublisher.ensure_tag(tag, commit) -> None`
- Produces: `GitHubReleasePublisher.ensure_release(tag, title, notes_path, *, repair) -> None`
- Produces: `GitHubReleasePublisher.upload_assets(tag, assets, *, repair) -> None`
- Produces: `GitHubReleasePublisher.verify_assets(tag, expected) -> tuple[ReleaseAssetInfo, ...]`

- [ ] **Step 1: 写只读远端查询失败和降级测试**

```python
def test_fetch_latest_release_normalizes_tag_version(monkeypatch):
    monkeypatch.setattr(
        remote,
        "_open_json",
        lambda *_args, **_kwargs: {
            "tag_name": "v3.6.21",
            "html_url": "https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.21",
        },
    )
    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})
    assert info.available is True
    assert info.version == "3.6.21"


def test_fetch_latest_release_returns_unknown_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(remote, "_open_json", Mock(side_effect=TimeoutError("offline")))
    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})
    assert info.available is False
    assert info.error == "offline"
```

- [ ] **Step 2: 写 publisher 参数安全和幂等资产测试**

```python
def test_publisher_uses_argument_arrays_and_never_shell(tmp_path):
    run = Mock(return_value=CompletedProcess([], 0, stdout="", stderr=""))
    publisher = GitHubReleasePublisher(
        "haohaizi554/UniversalCrawler",
        environment={},
        output=lambda _line: None,
        run_process=run,
    )
    publisher.ensure_release("v3.6.22", "v3.6.22", tmp_path / "notes.md", repair=False)
    args, kwargs = run.call_args
    assert args[0][:3] == ["gh", "release", "create"]
    assert kwargs["shell"] is False
    assert "--notes-file" in args[0]


def test_upload_skips_remote_asset_with_same_name_size_and_hash(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    publisher = make_publisher(
        remote_assets=[ReleaseAssetInfo.from_path(asset)],
    )
    publisher.upload_assets("v3.6.22", [asset], repair=False)
    assert publisher.executed_uploads == []
```

- [ ] **Step 3: 运行远端和 publisher 测试并确认失败**

Run: `python -m pytest tests/release/packaging/test_release_tool_remote.py tests/release/packaging/test_release_tool_publisher.py -v`

Expected: FAIL with missing modules。

- [ ] **Step 4: 实现只读查询和 GitHub CLI 发布**

只读查询使用 GitHub Releases REST API，设置固定 `User-Agent` 和 `Accept`，仅返回公开字段。写操作仅通过：

```python
def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    completed = self._run_process(
        list(argv),
        cwd=self.project_root,
        env=dict(self.environment),
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    for line in completed.stdout.splitlines():
        self.output(redact_release_text(line))
    for line in completed.stderr.splitlines():
        self.output(redact_release_text(line))
    if completed.returncode:
        raise PublishError(f"command failed with exit code {completed.returncode}")
    return completed
```

大文件使用 `gh release upload <tag> <asset-path-1> <asset-path-2> --repo <owner/repo>`；修复同版本 Release 时显式附加 `--clobber`。上传前通过 `gh release view --json assets` 获取名称和大小；同名同大小资产再下载/读取 GitHub digest 字段或通过 Release API 的 `digest` 校验 SHA-256。缺少可验证 digest 时不得静默跳过，进入上传或报出需要 repair。

- [ ] **Step 5: 运行远端和 publisher 测试**

Run: `python -m pytest tests/release/packaging/test_release_tool_remote.py tests/release/packaging/test_release_tool_publisher.py -v`

Expected: PASS。

- [ ] **Step 6: 提交远端发布层**

```powershell
git add packaging/release_tool/remote.py packaging/release_tool/publisher.py tests/release/packaging/test_release_tool_remote.py tests/release/packaging/test_release_tool_publisher.py
git commit -m "feat: add idempotent GitHub release publisher"
```

---

### Task 7: 编排可取消的发布状态机

**Files:**
- Create: `packaging/release_tool/runner.py`
- Create: `tests/release/packaging/test_release_tool_runner.py`
- Modify: `packaging/build_release.py`

**Interfaces:**
- Consumes: `BuildRequest`, mode resolver, version transaction, proxy, publisher, key bootstrap and existing build functions.
- Produces: `ReleasePipelineHooks`
- Produces: `run_release_request(request, hooks, emitter, cancel_token) -> ReleaseResult`
- Produces: `CancellationToken.cancel()` / `CancellationToken.raise_if_cancelled()`
- Produces: `load_request_file(path: Path) -> BuildRequest`

- [ ] **Step 1: 写阶段顺序、跳过和结果双确认失败测试**

```python
def test_local_debug_runs_only_version_and_selected_build_stages():
    hooks = RecordingHooks()
    events = RecordingEmitter()
    result = run_release_request(local_debug_request(), hooks, events, CancellationToken())
    assert result.succeeded is True
    assert hooks.calls == ["apply_version", "build_portable", "build_installer", "smoke_test"]
    assert events.stages == [
        ReleaseStage.PREFLIGHT,
        ReleaseStage.VERSION_SYNC,
        ReleaseStage.BUILDING_PORTABLE,
        ReleaseStage.BUILDING_INSTALLER,
        ReleaseStage.VERIFYING,
        ReleaseStage.SUCCEEDED,
    ]
    assert "sign_manifest" not in hooks.calls
    assert "upload_assets" not in hooks.calls


def test_cancelled_pipeline_never_reports_success():
    token = CancellationToken()
    hooks = RecordingHooks(on_build_portable=token.cancel)
    result = run_release_request(local_debug_request(), hooks, RecordingEmitter(), token)
    assert result.cancelled is True
    assert result.succeeded is False


def test_dry_run_plans_version_and_skips_every_side_effect():
    hooks = RecordingHooks()
    events = RecordingEmitter()
    request = replace(local_debug_request(), dry_run=True)
    result = run_release_request(request, hooks, events, CancellationToken())
    assert result.succeeded is True
    assert hooks.calls == ["plan_version"]
    assert ReleaseStage.VERSION_SYNC in events.stages
    assert events.skipped_stages == [
        ReleaseStage.BUILDING_PORTABLE,
        ReleaseStage.BUILDING_INSTALLER,
        ReleaseStage.SIGNING,
        ReleaseStage.GIT,
        ReleaseStage.UPLOADING,
        ReleaseStage.VERIFYING,
    ]
```

- [ ] **Step 2: 写构建失败保留已应用版本测试**

```python
def test_build_failure_does_not_rollback_an_applied_version():
    hooks = RecordingHooks(build_installer_error=RuntimeError("inno failed"))
    result = run_release_request(new_version_local_request(), hooks, RecordingEmitter(), CancellationToken())
    assert hooks.version_after_failure == "3.6.22"
    assert result.failed_stage is ReleaseStage.BUILDING_INSTALLER
```

- [ ] **Step 3: 运行 runner 测试并确认失败**

Run: `python -m pytest tests/release/packaging/test_release_tool_runner.py -v`

Expected: FAIL with missing runner。

- [ ] **Step 4: 实现 hooks 和状态机**

```python
@dataclass(frozen=True)
class ReleasePipelineHooks:
    plan_version: Callable[[str], VersionUpdatePlan]
    apply_version: Callable[[str], VersionUpdateResult]
    generate_key: Callable[[bool, bool], ManifestKeyResult]
    build_portable: Callable[[], None]
    build_installer: Callable[[], None]
    run_smoke_tests: Callable[[], None]
    sign_manifest: Callable[[BuildRequest], tuple[Path, ...]]
    commit_version_changes: Callable[[BuildRequest], str]
    push_main: Callable[[BuildRequest], None]
    ensure_tag: Callable[[BuildRequest, str], None]
    ensure_release: Callable[[BuildRequest], None]
    upload_assets: Callable[[BuildRequest, tuple[Path, ...]], None]
    verify_remote_assets: Callable[[BuildRequest, tuple[Path, ...]], None]
```

每个阶段统一使用：

```python
def _run_stage(stage, progress, action):
    cancel_token.raise_if_cancelled()
    emitter.emit("stage", stage=stage, progress=progress)
    value = action()
    cancel_token.raise_if_cancelled()
    return value
```

阶段异常映射到 `ReleaseResult(succeeded=False, failed_stage=stage, error=redact_release_text(str(exc)))`，并发出唯一 `error` 和 `result` 事件。跳过阶段发出 `kind="stage", data={"status": "skipped"}`，总进度保持单调。`dry_run=True` 时只运行远端只读检查、预检和 `plan_version(target_version)`，随后为构建、签名、Git、上传和回读阶段发出 `skipped`，不得调用 `apply_version()` 或任何有副作用的 hook。

- [ ] **Step 5: 让 `build_release.py` 装配现有构建原语**

`build_release.py` 保留 `_build_binaries()`、`_prepare_release_assets()`、锁和 source snapshot 校验；新增 `_build_pipeline_hooks(request, environment, emitter)`，把这些函数注入 runner。正式签名仍调用现有 `_prepare_release_assets()`；本地调试 hook 直接调用现有 `_build_binaries`，并把 `enforce_source_immutability` 设为 `False`，且不调用清单工具。

- [ ] **Step 6: 运行 runner 与现有流水线测试**

Run: `python -m pytest tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_pipeline.py -v`

Expected: PASS；既有 `tool.main([])` 和 `tool.main(["--build-only"])` 行为不变。

- [ ] **Step 7: 提交发布状态机**

```powershell
git add packaging/release_tool/runner.py packaging/build_release.py tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_pipeline.py
git commit -m "feat: orchestrate release workflow stages"
```

---

### Task 8: 增加脚本 GUI/Headless 分流和请求文件入口

**Files:**
- Modify: `packaging/build_release.py`
- Modify: `tests/release/packaging/test_release_pipeline.py`

**Interfaces:**
- Preserves: `main(argv: list[str] | None = None) -> int` 为无界面 API。
- Produces: `script_main(argv: list[str]) -> int`
- Produces CLI flags: `--gui`, `--headless`, `--request-file`, `--dry-run`

- [ ] **Step 1: 写入口分流失败测试**

```python
def test_python_main_empty_argv_keeps_headless_release_semantics():
    tool = _load_tool()
    with patch.object(tool, "_run_headless_legacy", return_value=17) as headless:
        assert tool.main([]) == 17
    headless.assert_called_once()


def test_script_no_args_opens_panel():
    tool = _load_tool()
    with patch.object(tool, "_launch_panel", return_value=0) as launch:
        assert tool.script_main([]) == 0
    launch.assert_called_once()


def test_script_headless_request_file_runs_runner(tmp_path):
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(valid_request_payload()), encoding="utf-8")
    tool = _load_tool()
    with patch.object(tool, "_run_request_file", return_value=0) as run:
        assert tool.script_main(["--headless", "--request-file", str(request_file)]) == 0
    run.assert_called_once_with(request_file)


def test_script_headless_dry_run_builds_non_mutating_request():
    tool = _load_tool()
    with patch.object(tool, "_run_dry_run_request", return_value=0) as run:
        assert tool.script_main(
            ["--headless", "--dry-run", "--version", "3.6.21", "--build-only"]
        ) == 0
    run.assert_called_once_with(version="3.6.21", build_only=True)
```

- [ ] **Step 2: 运行入口测试并确认失败**

Run: `python -m pytest tests/release/packaging/test_release_pipeline.py -k "script_no_args or request_file or python_main_empty or dry_run" -v`

Expected: FAIL because `script_main` is missing。

- [ ] **Step 3: 实现两层入口**

```python
def main(argv: list[str] | None = None) -> int:
    return _run_headless_legacy([] if argv is None else argv)


def script_main(argv: list[str]) -> int:
    raw = list(argv)
    if "--gui" in raw or not raw:
        return _launch_panel()
    parser = build_script_parser()
    args, _ = parser.parse_known_args(raw)
    if args.request_file:
        return _run_request_file(Path(args.request_file))
    if args.dry_run:
        return _run_dry_run_request(
            version=args.version or read_project_version(PROJECT_ROOT),
            build_only=bool(args.build_only),
        )
    legacy_argv = [token for token in raw if token != "--headless"]
    return main(legacy_argv)


if __name__ == "__main__":
    raise SystemExit(script_main(sys.argv[1:]))
```

`build_script_parser()` 使用 `ArgumentParser(add_help=False)`，显式定义 `--gui`、`--headless`、`--request-file`、`--dry-run`、`--version` 和 `--build-only`，只负责入口路由。普通 headless 路径把原始参数中唯一的 `--headless` 删除后传回现有 `main()`，不得丢失被路由 parser 识别的 `--version` 或 `--build-only`。请求文件在读取后立即尝试删除；JSON 只保存路径和布尔选项，不保存 token 或私钥内容。私钥仅保存规范化路径。`_run_dry_run_request()` 构造 `BuildRequest(dry_run=True, target_version=version, build_portable=build_only, build_installer=build_only)` 并调用统一 runner。

- [ ] **Step 4: 运行完整 release pipeline 测试**

Run: `python -m pytest tests/release/packaging/test_release_pipeline.py -v`

Expected: PASS。

- [ ] **Step 5: 提交脚本入口分流**

```powershell
git add packaging/build_release.py tests/release/packaging/test_release_pipeline.py
git commit -m "feat: add GUI and headless release entry modes"
```

---

### Task 9: 生成维护工具标准 ICO

**Files:**
- Create: `packaging/release_tool/icon_builder.py`
- Move: `bag_15483236.png` to `packaging/release_tool/assets/release-builder.png`
- Create: `packaging/release_tool/assets/release-builder.ico`
- Create: `tests/release/packaging/test_release_tool_icon.py`
- Modify: `tests/release/packaging/test_assets.py`

**Interfaces:**
- Produces: `ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)`
- Produces: `build_release_builder_icon(source: Path, destination: Path) -> Path`
- Produces: `release_builder_icon_path() -> Path`

- [ ] **Step 1: 写 ICO 尺寸目录失败测试**

```python
def test_release_builder_ico_contains_all_standard_sizes(tmp_path, qapp):
    destination = tmp_path / "release-builder.ico"
    build_release_builder_icon(SOURCE_PNG, destination)
    entries = read_ico_directory(destination)
    assert [(entry.width, entry.height) for entry in entries] == [
        (16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
        (48, 48), (64, 64), (128, 128), (256, 256),
    ]
    assert all(entry.payload.startswith(b"\x89PNG\r\n\x1a\n") for entry in entries)
```

- [ ] **Step 2: 运行图标测试并确认失败**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/release/packaging/test_release_tool_icon.py -v`

Expected: FAIL with missing icon builder。

- [ ] **Step 3: 实现 PNG-in-ICO 生成器**

使用 `QImageReader` 读透明源图，按 `Qt.AspectRatioMode.KeepAspectRatio` 和 `Qt.TransformationMode.SmoothTransformation` 缩放，在透明正方形画布居中。每层编码为 PNG；ICO header 使用 `<HHH`，目录项使用 `<BBBBHHII`，256 尺寸宽高字节写 0。

```python
def build_release_builder_icon(source: Path, destination: Path) -> Path:
    layers = tuple(_png_layer(source, size) for size in ICON_SIZES)
    payload = _encode_ico(layers)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, destination)
    return destination
```

- [ ] **Step 4: 迁移源 PNG 并生成 ICO**

Run:

```powershell
New-Item -ItemType Directory -Force packaging/release_tool/assets | Out-Null
Move-Item -LiteralPath bag_15483236.png -Destination packaging/release_tool/assets/release-builder.png
python -m packaging.release_tool.icon_builder
```

Expected: `packaging/release_tool/assets/release-builder.ico` 存在且图标测试识别九个尺寸。

- [ ] **Step 5: 运行图标和打包资产测试**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/release/packaging/test_release_tool_icon.py tests/release/packaging/test_assets.py -q`

Expected: PASS。

- [ ] **Step 6: 提交维护工具图标**

```powershell
git add packaging/release_tool/icon_builder.py packaging/release_tool/assets tests/release/packaging/test_release_tool_icon.py tests/release/packaging/test_assets.py
git commit -m "feat: add multi-size release builder icon"
```

---

### Task 10: 实现主题化 Qt 发布构建面板

**Files:**
- Create: `packaging/release_tool/panel.py`
- Create: `tests/release/packaging/test_release_builder_panel.py`
- Modify: `app/ui/components/log_panel.py`
- Modify: `tests/unit/app/ui/components/test_log_panel.py`

**Interfaces:**
- Consumes: model/mode/version/proxy/remote/event APIs and release-builder ICO.
- Produces: `ReleaseBuilderWindow(QWidget)`
- Produces: `launch_release_builder_panel() -> int`
- Produces: `ReleaseProcessController(QObject)`
- Extends: `LogPanel.append_logs(messages: Iterable[str]) -> None`

- [ ] **Step 1: 为日志批量追加补失败测试**

```python
def test_append_logs_batches_lines_and_keeps_block_limit():
    panel = LogPanel()
    panel.setMaximumBlockCount(3)
    panel.append_logs(["one", "two", "three", "four"])
    assert panel.toPlainText().splitlines() == ["two", "three", "four"]
```

- [ ] **Step 2: 写面板 chrome、主题和默认安全选项失败测试**

```python
def test_panel_reuses_project_chrome_and_defaults_remote_writes_off(qapp):
    window = ReleaseBuilderWindow(remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"))
    assert isinstance(window.chrome_frame, WindowChromeFrame)
    assert isinstance(window._window_chrome_controller, FramelessWindowChromeController)
    assert window.check_sign_manifest.isChecked() is False
    assert window.check_push_main.isChecked() is False
    assert window.check_create_release.isChecked() is False
    assert window.check_upload_assets.isChecked() is False


def test_local_debug_mode_disables_remote_controls(qapp):
    window = make_panel(project_version="3.6.20", remote_version="3.6.21")
    window.target_version_edit.setText("3.6.20")
    window.refresh_mode()
    assert window.mode_badge.property("releaseMode") == "local_debug"
    assert window.check_upload_assets.isEnabled() is False
    assert window.private_key_edit.isEnabled() is False
```

- [ ] **Step 3: 写 QProcess 事件与退出双确认失败测试**

```python
def test_process_success_requires_result_event_and_zero_exit(qapp, tmp_path):
    controller = ReleaseProcessController(process=FakeProcess(exit_code=0))
    controller.feed_stdout(
        EVENT_PREFIX + json.dumps(success_result_event()) + "\n"
    )
    controller.on_finished(0, QProcess.ExitStatus.NormalExit)
    assert controller.result.succeeded is True

    missing_result = ReleaseProcessController(process=FakeProcess(exit_code=0))
    missing_result.on_finished(0, QProcess.ExitStatus.NormalExit)
    assert missing_result.result.succeeded is False
    assert "final result event" in missing_result.result.error
```

- [ ] **Step 4: 运行 Qt 测试并确认失败**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/release/packaging/test_release_builder_panel.py tests/unit/app/ui/components/test_log_panel.py -v`

Expected: FAIL with missing panel/batch API。

- [ ] **Step 5: 实现独立窗口 chrome**

`ReleaseBuilderWindow` 是顶层 `QWidget`，设置 `FramelessWindowHint`，中央布局只有
`WindowChromeFrame`。标题栏操作必须由共享控制器统一绑定，不能在窗口中维护第二套最大化状态：

```python
self._window_chrome_controller = FramelessWindowChromeController(
    self,
    title_bar_getter=lambda: self.window_title_bar,
    resizable=True,
    minimizable=True,
    maximizable=True,
)
self._window_chrome_controller.set_window_flags()
self._window_chrome_controller.bind_title_bar_controls()
```

窗口显示时调用 `install()` / `on_show_event()`，关闭时调用 `uninstall()`，原生事件和鼠标事件
继续转发给控制器。Windows 最大化/还原图标只能使用 `IsZoomed(hwnd)` 真值，不能使用面板自己的
`isMaximized()` 或 `_maximized` 缓存。

`showEvent` 安装 controller；`closeEvent` 在运行中先请求取消，否则卸载 controller。`nativeEvent`、`mousePressEvent` 和 `eventFilter` 转发给 controller，与主窗口一致。

- [ ] **Step 6: 实现单页表单和约束**

面板使用六个 `QGroupBox`/无嵌套卡片区块：版本、构建、签名、Git/Release、网络、执行。所有控件设置稳定最小宽度，说明文案换行，窗口默认 1180×820 并受屏幕可用区约束。主题从项目配置解析并调用：

```python
self._is_dark = resolve_is_dark_theme(configured_theme, follow_system)
apply_application_theme(self._is_dark)
self.chrome_frame.apply_theme(self._is_dark)
self._colors = theme_colors(self._is_dark)
```

控件状态完全由 `resolve_release_mode()` 和 `validate_build_request()` 投影，不在 clicked handler 重复业务判断。

- [ ] **Step 7: 实现日志、进度和 QProcess 生命周期**

`ReleaseProcessController` 使用 `QProcess.setProcessEnvironment()` 传代理变量，程序为 `sys.executable`，参数为：

```python
[
    str(PROJECT_ROOT / "packaging/build_release.py"),
    "--headless",
    "--request-file",
    str(request_file),
]
```

stdout/stderr 分别维护未完成行缓冲；`readyReadStandardOutput` 和 `readyReadStandardError` 只读取字节、解码和入有界 deque。一个 50 ms UI 合并定时器每次最多追加 200 行；结构化 stage/error/result 事件立即刷新进度和状态。持久日志逐行写入 `dist/release-logs/<UTC>-<mode>-<version>.log`。取消先 `terminate()`，5 秒后仍运行则调用 Windows `taskkill /PID <pid> /T /F` 或 `kill()`。

- [ ] **Step 8: 实现安全确认和工具动作**

远端写入开始前显示项目 `ChromedDialog` 风格摘要，列出版本、模式、tag、仓库、代理标签、Release 文档和资产名称；不显示 token、私钥内容或带认证的 URL。日志区提供复制选中、导出副本、清空视图、打开日志目录；清空视图不删除持久日志。

- [ ] **Step 9: 运行 Qt 面板测试**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/release/packaging/test_release_builder_panel.py tests/unit/app/ui/components/test_log_panel.py -v`

Expected: PASS。

- [ ] **Step 10: 提交发布面板**

```powershell
git add packaging/release_tool/panel.py app/ui/components/log_panel.py tests/release/packaging/test_release_builder_panel.py tests/unit/app/ui/components/test_log_panel.py
git commit -m "feat: add themed release builder panel"
```

---

### Task 11: 接入密钥生成、信任锚轮换和公钥资产

**Files:**
- Modify: `packaging/release_tool/runner.py`
- Modify: `packaging/release_tool/panel.py`
- Modify: `packaging/build_release.py`
- Modify: `tests/release/packaging/test_release_tool_runner.py`
- Modify: `tests/release/packaging/test_release_builder_panel.py`

**Interfaces:**
- Consumes: `generate_manifest_key()`, `inject_public_key()`, `default_manifest_private_key_path()`, `default_manifest_public_key_path()`
- Produces: `resolve_signing_material(request) -> SigningMaterial`
- Produces: `SigningMaterial(private_key_path, public_key_path, fingerprint, trust_anchor_changed)`

- [ ] **Step 1: 写本地调试不生成密钥且保留生产公钥测试**

```python
def test_local_debug_build_never_generates_or_injects_keys():
    hooks = RecordingHooks()
    result = run_release_request(local_debug_request(), hooks, RecordingEmitter(), CancellationToken())
    assert result.succeeded is True
    assert "generate_key" not in hooks.calls
    assert "inject_public_key" not in hooks.calls
    assert hooks.production_public_key_present_during_build is True
```

- [ ] **Step 2: 写显式轮换信任锚约束测试**

```python
def test_rotating_trust_anchor_requires_key_generation_and_installer_rebuild():
    request = replace(
        new_release_request(),
        rotate_trust_anchor=True,
        generate_manifest_key=False,
        build_installer=False,
    )
    assert validate_build_request(request) == (
        "trust anchor rotation requires manifest key generation",
        "trust anchor rotation requires installer rebuild",
    )
```

- [ ] **Step 3: 运行焦点测试并确认失败**

Run: `python -m pytest tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_builder_panel.py -k "key or trust_anchor or local_debug" -v`

Expected: FAIL until signing material is wired。

- [ ] **Step 4: 接入仓库外密钥和公开资产**

`resolve_signing_material()` 只接受仓库外路径；选择生成时调用：

```python
result = generate_manifest_key(
    project_root=PROJECT_ROOT,
    rotate=request.rotate_trust_anchor,
    write_public_key_to_config=request.rotate_trust_anchor,
    config_path=UPDATE_TRUST_CONFIG,
)
```

普通正式发布沿用已存在私钥，不改生产公钥。轮换信任锚只有显式勾选才注入新公钥并强制重建。上传公钥时 publisher 接收 `default_manifest_public_key_path()`，但不把它复制到 portable/installer；日志只显示文件名和 SHA-256 fingerprint。

- [ ] **Step 5: 运行密钥边界测试**

Run: `python -m pytest tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_builder_panel.py tests/release/updater -q`

Expected: PASS。

- [ ] **Step 6: 提交签名和信任锚接线**

```powershell
git add packaging/release_tool/runner.py packaging/release_tool/panel.py packaging/build_release.py tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_builder_panel.py
git commit -m "feat: wire external release signing material"
```

---

### Task 12: 更新维护文档和版本投影说明

**Files:**
- Create: `docs/guides/release-builder.md`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `docs/README.md`
- Modify: `cli/skill/SKILL.md`
- Modify: `docs/releases/v3.6.21.md`
- Modify: `tests/release/packaging/test_version_contract.py`

**Interfaces:**
- Consumes: version projection allowlist and panel behavior.
- Produces: 可执行的本地调试、新版本发布、同版本修复和公钥轮换操作说明。

- [ ] **Step 1: 写文档入口和投影守卫失败测试**

```python
def test_release_builder_guide_is_linked_from_docs_index():
    index = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "guides/release-builder.md" in index


def test_version_projection_allowlist_matches_documented_files():
    assert set(VERSION_PROJECTION_PATHS) == {
        Path("README.md"),
        Path("README_EN.md"),
        Path("docs/README.md"),
        Path("cli/skill/SKILL.md"),
    }
```

- [ ] **Step 2: 运行文档守卫并确认失败**

Run: `python -m pytest tests/release/packaging/test_version_contract.py -k "guide or projection_allowlist" -v`

Expected: FAIL until guide and links exist。

- [ ] **Step 3: 编写维护者指南**

`docs/guides/release-builder.md` 必须包含：

1. `python packaging/build_release.py` 打开面板。
2. `python packaging/build_release.py --headless --build-only --version 3.6.21` 保持 CI/脚本用法。
3. 低于、等于、高于远端版本的模式表。
4. 本地调试只构建程序、继承生产公钥、不产生签名资产。
5. 新版本发布的显式选项依赖关系。
6. 同版本修复必须人工确认 `--clobber` 语义。
7. 密钥目录默认位于 `~/.ucrawl/release-secrets`，禁止放入仓库。
8. 代理选择与 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 映射。
9. 日志位置、脱敏规则、取消行为和失败恢复。
10. 版本唯一事实源与允许投影列表。
11. 安装包、清单、签名和公钥的远端回读校验。

- [ ] **Step 4: 更新索引和当前 Release 维护说明**

README 只增加维护者入口，不重复长篇发布流程。`docs/releases/v3.6.21.md` 增加“后续维护工具”说明，明确该面板在 v3.6.21 发布后加入源码维护链路，不篡改该 Release 的安装包哈希和源提交事实。

- [ ] **Step 5: 运行文档与版本契约测试**

Run: `python -m pytest tests/release/packaging/test_version_contract.py tests/architecture -q`

Expected: PASS。

- [ ] **Step 6: 提交文档**

```powershell
git add docs/guides/release-builder.md README.md README_EN.md docs/README.md cli/skill/SKILL.md docs/releases/v3.6.21.md tests/release/packaging/test_version_contract.py
git commit -m "docs: document release builder workflow"
```

---

### Task 13: 完成焦点、回归和真实无上传烟测

**Files:**
- Modify only when a failing assertion exposes a defect in files from Tasks 1-12.

**Interfaces:**
- Verifies all interfaces produced above.

- [ ] **Step 1: 静态检查新增维护工具**

Run:

```powershell
python -m ruff check packaging/build_release.py packaging/release_tool tests/release/packaging
python -m compileall packaging/release_tool packaging/build_release.py
```

Expected: 两个命令 exit 0。

- [ ] **Step 2: 运行 release packaging 全套**

Run: `python -m pytest tests/release/packaging -q`

Expected: PASS，无新 warning。

- [ ] **Step 3: 运行更新器和代理相关回归**

Run:

```powershell
python -m pytest tests/release/updater tests/unit/app/core/plugins -q
```

Expected: PASS。

- [ ] **Step 4: 运行 Qt offscreen 面板回归**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/release/packaging/test_release_builder_panel.py tests/unit/app/ui/components/test_log_panel.py -q
```

Expected: PASS；进程结束后无残留 `QProcess` 和窗口。

- [ ] **Step 5: 运行本地调试 dry-run**

使用 Task 3、Task 7 和 Task 8 已定义的 `BuildRequest.dry_run` 与 `--dry-run`，只执行远端只读检查、预检、版本变更规划、事件流和产物路径规划，不调用版本写入、PyInstaller、Inno、签名、Git 或 GitHub。运行：

```powershell
python packaging/build_release.py --headless --dry-run --version 3.6.21 --build-only
```

Expected:

- 输出包含前缀 JSONL 的 `preflight`、`version_sync`、跳过构建和 `result`。
- 最终 exit code 0。
- 不生成 `latest.json`、`latest.json.sig`、tag 或 GitHub Release。
- 不改变 `shared/version.py`。

- [ ] **Step 6: 手工启动面板烟测**

Run: `python packaging/build_release.py`

Expected:

- 面板使用 release-builder ICO 和项目自定义标题栏。
- 窗口可最小化、最大化、Snap、缩放和关闭。
- 日志位于面板且支持复制/导出/打开目录。
- 目标版本 `3.6.21` 与远端相等时显示本地重构，所有远端写选项未勾选。
- 选择 Clash 7890 后预检子进程环境显示代理标签，不输出代理凭据。
- 关闭运行中的面板先取消子进程，不留下 Python/PyInstaller/Inno 子进程。

- [ ] **Step 7: 运行项目全量测试**

Run: `python -m pytest -q`

Expected: 全绿；测试数量和耗时记录到 `docs/guides/release-builder.md` 的验证小节。

- [ ] **Step 8: 检查工作区和秘密**

Run:

```powershell
git status --short
python -m scripts.update_bootstrap scan-secrets
```

Expected:

- 只有本计划实施产生的预期文件。
- 私钥、token、代理密码和请求临时文件均未被 Git 跟踪。
- secret scan exit 0。

- [ ] **Step 9: 提交最终验证修正**

```powershell
git add packaging app shared tests docs README.md README_EN.md cli/skill/SKILL.md pyproject.toml .github/workflows/python-tests.yml
git commit -m "test: verify release builder end to end"
```

---

## Self-Review

### Spec Coverage

- 唯一版本事实源、PEP 621 动态版本、Inno fail-closed：Tasks 1-2。
- 低/等/高/远端未知模式矩阵：Task 3。
- JSONL 事件、真实阶段进度、脱敏和持久日志：Task 4。
- 项目代理预设、直连和自定义端点：Task 5。
- GitHub 最新版本、GitHub CLI 大文件上传、同版本修复和远端回读：Task 6。
- 子进程状态机、取消和失败保留版本变更：Task 7。
- 无参数 GUI 与 `main([])` 兼容：Task 8。
- 标准多尺寸 ICO：Task 9。
- 项目 chrome、主题、面板日志、进度和默认安全选项：Task 10。
- 外部私钥、生产公钥、本地调试和显式信任锚轮换：Task 11。
- 中文维护文档和版本投影说明：Task 12。
- 静态、焦点、回归、全量与人工烟测：Task 13。

### Placeholder Scan

- 计划没有遗留未命名函数、未定义相邻接口或“稍后实现”步骤。
- 代码体量较大的 UI 和 publisher 步骤给出了精确类名、方法签名、参数数组、状态约束和测试断言；实现者不需要自行发明跨任务接口。

### Type Consistency

- `BuildRequest`、`RemoteReleaseInfo`、`ReleaseMode`、`ReleaseStage` 从 Task 3 开始保持同名。
- 事件层、runner 和 panel 都使用同一个 `ReleaseStage`。
- 版本层统一使用无前缀 `MAJOR.MINOR.PATCH`，只在显示层添加 `v`。
- publisher 接收 `Path` 资产和 `Mapping[str, str]` 环境，不接收秘密内容。
- `main()` 始终表示无界面 Python API；`script_main()` 始终表示命令行/双击入口。
