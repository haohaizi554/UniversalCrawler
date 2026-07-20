# 发布构建工具三模式工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将发布构建工具收束为“同版本修复发布、高版本正式发布、本地构建”三种用户模式，并按参考图实现无外层滚动条的双栏单页工作台。

**Architecture:** 保留既有五种 `ReleaseMode`、`BuildRequest`、校验器和构建控制器，新增纯 Python 的面板策略层负责版本关系、三模式推荐、底层模式映射与安全默认值。Qt 窗口只维护当前用户意图、每种模式的表单快照和批量控件投影；布局由左侧五张配置卡与右侧执行卡组成，网络和构建仍走现有异步链路。

**Tech Stack:** Python 3.10+、PyQt6、pytest、项目 `WindowChromeFrame`、`ThemedComboBox`、语义主题 token。

## Global Constraints

- 不修改 `ReleaseMode`、`BuildRequest`、CLI 和 Runner 的外部语义。
- 本地构建在任意目标版本下都不得启用签名、Git、Release 或上传动作。
- 远端版本未知时只允许本地构建，并映射为 `offline_debug=True`。
- “生成更新清单密钥”和“轮换信任锚”永远不自动勾选。
- 模式默认值只在首次进入该模式时应用；再次进入恢复该模式自己的最后状态。
- 批量投影必须使用 `QSignalBlocker`，完成后只校验一次。
- 移除整页 `QScrollArea`，默认桌面尺寸内完整显示两栏，不能用超大最小尺寸掩盖布局问题。
- 样式只能消费项目主题 token，不在页面中新增独立硬编码配色。
- 远端写入仍必须经过现有最终确认弹窗。

---

### Task 1: 三模式纯策略

**Files:**
- Create: `packaging/release_tool/panel_policy.py`
- Create: `tests/release/packaging/test_release_builder_panel_policy.py`

**Interfaces:**
- Produces: `PanelBuildIntent`, `VersionRelation`, `PanelModeResolution`, `PanelOptionDefaults`。
- Produces: `version_relation(target_version, remote) -> VersionRelation`。
- Produces: `recommended_intent(target_version, remote) -> PanelBuildIntent`。
- Produces: `available_intents(target_version, remote) -> frozenset[PanelBuildIntent]`。
- Produces: `resolve_panel_intent(intent, target_version, remote) -> PanelModeResolution`。
- Produces: `option_defaults(intent) -> PanelOptionDefaults`。

- [ ] **Step 1: Write the failing policy tests**

```python
@pytest.mark.parametrize(
    ("target", "remote", "expected"),
    (
        ("3.6.20", RemoteReleaseInfo.available("3.6.21"), PanelBuildIntent.LOCAL),
        ("3.6.21", RemoteReleaseInfo.available("3.6.21"), PanelBuildIntent.SAME_RELEASE),
        ("3.6.22", RemoteReleaseInfo.available("3.6.21"), PanelBuildIntent.NEW_RELEASE),
        ("3.6.22", RemoteReleaseInfo.unknown(), PanelBuildIntent.LOCAL),
    ),
)
def test_recommended_intent_follows_version_relation(target, remote, expected):
    assert recommended_intent(target, remote) is expected


def test_manual_local_mode_maps_higher_version_to_offline_debug():
    projection = resolve_panel_intent(
        PanelBuildIntent.LOCAL,
        "3.6.22",
        RemoteReleaseInfo.available("3.6.21"),
    )
    assert projection.release_mode is ReleaseMode.OFFLINE_DEBUG
    assert projection.offline_debug is True


def test_release_defaults_enable_safe_publication_without_rotating_trust():
    defaults = option_defaults(PanelBuildIntent.NEW_RELEASE)
    assert defaults.sign_manifest is True
    assert defaults.commit_version_changes is True
    assert defaults.push_main is True
    assert defaults.upload_release_assets is True
    assert defaults.upload_public_key is True
    assert defaults.generate_manifest_key is False
    assert defaults.rotate_trust_anchor is False
```

- [ ] **Step 2: Run the new test module and verify collection fails**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel_policy.py -q`

Expected: FAIL because `packaging.release_tool.panel_policy` does not exist.

- [ ] **Step 3: Implement the pure policy**

```python
class PanelBuildIntent(str, Enum):
    LOCAL = "local"
    SAME_RELEASE = "same_release"
    NEW_RELEASE = "new_release"


@dataclass(frozen=True, slots=True)
class PanelModeResolution:
    release_mode: ReleaseMode
    same_release_repair: bool
    offline_debug: bool


def resolve_panel_intent(
    intent: PanelBuildIntent,
    target_version: str,
    remote: RemoteReleaseInfo,
) -> PanelModeResolution:
    relation = version_relation(target_version, remote)
    if intent is PanelBuildIntent.LOCAL:
        if relation is VersionRelation.LOWER:
            return PanelModeResolution(ReleaseMode.LOCAL_DEBUG, False, False)
        if relation is VersionRelation.EQUAL:
            return PanelModeResolution(ReleaseMode.LOCAL_REBUILD, False, False)
        return PanelModeResolution(ReleaseMode.OFFLINE_DEBUG, False, True)
    if intent is PanelBuildIntent.SAME_RELEASE and relation is VersionRelation.EQUAL:
        return PanelModeResolution(ReleaseMode.SAME_RELEASE_REPAIR, True, False)
    if intent is PanelBuildIntent.NEW_RELEASE and relation is VersionRelation.HIGHER:
        return PanelModeResolution(ReleaseMode.NEW_RELEASE, False, False)
    raise ValueError("selected panel mode is incompatible with target version")
```

`PanelOptionDefaults` 必须显式列出所有布尔构建字段，三个模式共享启用版本写入、便携版、安装包和冒烟测试；两个发布模式按设计文档启用各自远端动作。

- [ ] **Step 4: Run the policy tests**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel_policy.py -q`

Expected: PASS.

---

### Task 2: 面板模式状态与请求映射

**Files:**
- Modify: `packaging/release_tool/panel.py`
- Modify: `tests/release/packaging/test_release_builder_panel.py`

**Interfaces:**
- Consumes: Task 1 的 `PanelBuildIntent`、`available_intents`、`recommended_intent`、`resolve_panel_intent` 和 `option_defaults`。
- Produces: `ReleaseBuilderWindow.panel_intent` 只读属性。
- Produces: `mode_local_button`、`mode_same_button`、`mode_release_button` 三个互斥选择控件。

- [ ] **Step 1: Add failing interaction tests**

```python
def test_equal_remote_version_recommends_same_release_with_defaults(qapp):
    window = make_panel(
        qapp,
        project_version="3.6.21",
        remote_loader=lambda *_args: RemoteReleaseInfo.available("3.6.21"),
    )
    try:
        assert window.panel_intent is PanelBuildIntent.SAME_RELEASE
        assert window.check_sign_manifest.isChecked() is True
        assert window.check_commit_version.isChecked() is False
        assert window.check_push_main.isChecked() is False
        assert window.check_upload_assets.isChecked() is True
    finally:
        window.shutdown()


def test_mode_state_is_restored_instead_of_reapplying_defaults(qapp):
    window = make_panel(qapp)
    try:
        window.check_upload_public_key.setChecked(False)
        window.mode_local_button.click()
        window.mode_release_button.click()
        assert window.check_upload_public_key.isChecked() is False
    finally:
        window.shutdown()


def test_manual_local_override_on_higher_version_never_writes_remote(qapp):
    window = make_panel(qapp)
    try:
        window.mode_local_button.click()
        request = window._request_from_controls()
        assert request.offline_debug is True
        assert request.sign_manifest is False
        assert request.push_main is False
        assert request.upload_release_assets is False
    finally:
        window.shutdown()
```

- [ ] **Step 2: Run the focused interaction tests**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel.py -k "intent or mode_state or local_override" -q`

Expected: FAIL because the three-mode controls and state store do not exist.

- [ ] **Step 3: Implement mode reconciliation and per-mode snapshots**

```python
def _switch_panel_intent(self, intent: PanelBuildIntent) -> None:
    if self._panel_intent is intent:
        return
    if self._panel_intent is not None:
        self._mode_form_states[self._panel_intent] = self._capture_mode_form_state()
    state = self._mode_form_states.get(intent)
    if state is None:
        state = asdict(option_defaults(intent))
        self._mode_form_states[intent] = dict(state)
    self._panel_intent = intent
    blockers = [QSignalBlocker(control) for control in self._mode_option_controls()]
    try:
        self._apply_mode_form_state(state)
        self._sync_mode_button_checks(intent)
    finally:
        blockers.clear()
```

目标版本或远端结果变化时，如果没有显式选择本地模式，则切换到
`recommended_intent(...)`；点击本地模式后设置 `_local_mode_forced=True`，
直到操作者点击合法的发布模式。`_request_from_controls()` 必须从
`resolve_panel_intent(...)` 取得 `same_release_repair` 与 `offline_debug`，不得再读取
旧的两个模式复选框。

- [ ] **Step 4: Run the panel mode tests**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel.py -k "mode or intent or default or remote_unknown" -q`

Expected: PASS.

---

### Task 3: 双栏卡片单页布局

**Files:**
- Modify: `packaging/release_tool/panel.py`
- Modify: `tests/release/packaging/test_release_builder_panel.py`

**Interfaces:**
- Produces: `left_configuration_column` 与 `execution_column` 两个互不交叉的布局所有者。
- Preserves: `section_widgets` 六张 `QGroupBox` 卡片以及既有控件属性名。

- [ ] **Step 1: Add failing layout contract tests**

```python
def test_release_builder_uses_two_column_workbench_without_outer_scroll(qapp):
    window = make_panel(qapp)
    try:
        assert window.findChild(QScrollArea, "ReleaseBuilderScroll") is None
        assert window.left_configuration_column is not None
        assert window.execution_column is not None
        assert window.section_widgets[:5] == window.configuration_sections
        assert window.section_widgets[5] is window.execution_section
    finally:
        window.shutdown()


def test_mode_selector_and_build_options_have_stable_card_dimensions(qapp):
    window = make_panel(qapp)
    try:
        assert window.mode_local_button.minimumHeight() >= 44
        assert window.check_build_portable.isCheckable()
        assert window.check_build_portable.minimumHeight() >= 42
    finally:
        window.shutdown()
```

- [ ] **Step 2: Run the layout tests**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel.py -k "two_column or stable_card" -q`

Expected: FAIL because the current body is a vertical `QScrollArea`.

- [ ] **Step 3: Replace the body with a two-column workbench**

```python
content = QWidget(self.chrome_frame.body)
workbench = QHBoxLayout(content)
workbench.setContentsMargins(18, 16, 18, 18)
workbench.setSpacing(12)

self.left_configuration_column = QWidget(content)
left_layout = QVBoxLayout(self.left_configuration_column)
self.execution_column = QWidget(content)
right_layout = QVBoxLayout(self.execution_column)

for builder in (
    self._build_version_section,
    self._build_build_section,
    self._build_signing_section,
    self._build_release_section,
    self._build_network_section,
):
    builder(left_layout)
self._build_execution_section(right_layout)
workbench.addWidget(self.left_configuration_column, 10)
workbench.addWidget(self.execution_column, 11)
```

每张卡片使用统一编号标题、6px 圆角、语义边框和一致内边距。构建项改为四个紧凑
可点击按钮卡，模式改为三个互斥分段卡；其他输入、复选框和代理继续复用项目控件。

- [ ] **Step 4: Increase the desktop-oriented default geometry without hiding small-screen failures**

`constrained_geometry()` 的目标尺寸调整为 `1480 x 860`，仍使用
`min(target, available)` 限制到可用桌面；最小尺寸保持不大于 `980 x 680`，布局本身
负责文本省略和列宽收缩。

- [ ] **Step 5: Run layout and geometry tests**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel.py -k "two_column or card or geometry or chinese" -q`

Expected: PASS.

---

### Task 4: 主题、状态与异步远端刷新收束

**Files:**
- Modify: `packaging/release_tool/panel.py`
- Modify: `tests/release/packaging/test_release_builder_panel.py`

**Interfaces:**
- Preserves: `_RemoteLoaderWorker` 和 `ReleaseProcessController` 的异步边界。
- Produces: 主题化模式卡、构建卡、编号徽标、执行状态和日志空态。

- [ ] **Step 1: Add failing state and theme tests**

```python
def test_remote_refresh_preserves_known_mode_until_new_result_arrives(qapp):
    window = make_panel(qapp)
    try:
        previous = window.panel_intent
        window.start_remote_lookup()
        assert window.panel_intent is previous
        assert window.remote_version_label.text().startswith("正在检查")
    finally:
        window.shutdown()


def test_mode_and_option_cards_use_semantic_properties(qapp):
    window = make_panel(qapp)
    try:
        assert window.mode_release_button.property("releaseModeChoice") == "new_release"
        assert window.check_build_installer.property("releaseOptionCard") is True
        assert "#ReleaseModeChoice" in window.styleSheet()
    finally:
        window.shutdown()
```

- [ ] **Step 2: Run the focused tests**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel.py -k "preserves_known_mode or semantic_properties" -q`

Expected: FAIL until the state-preserving refresh and semantic styling are present.

- [ ] **Step 3: Implement semantic QSS and updating-state preservation**

Remote refresh must retain the last valid `remote_info` while displaying
`正在检查…（当前 vX.Y.Z）`; the first lookup may remain unknown. QSS selectors use widget
properties and `theme_colors(...)` values for default, hover, checked, disabled, danger and
success states. No raw page-specific hex colors are introduced.

- [ ] **Step 4: Render offscreen screenshots**

Run an offscreen PyQt script that creates equal-version and high-version windows at
`1480 x 860`, saves light and dark screenshots under the test temporary directory, and asserts:

```python
assert window.findChild(QScrollArea, "ReleaseBuilderScroll") is None
assert window.execution_section.geometry().height() > 600
assert window.log_panel.height() > 300
assert window.left_configuration_column.geometry().right() < (
    window.execution_column.geometry().left()
)
```

Inspect both screenshots for clipping, overlap, incorrect popup styling and unused margins.

- [ ] **Step 5: Run the complete panel test module**

Run: `python -m pytest tests/release/packaging/test_release_builder_panel.py -q`

Expected: PASS.

---

### Task 5: 发布工具回归与文档同步

**Files:**
- Modify: `docs/guides/release-builder.md`
- Modify: `docs/superpowers/specs/2026-07-19-release-build-panel-and-version-contract-design.md` only if implementation reveals a contract correction.

**Interfaces:**
- Documents: three user modes, automatic recommendation, manual local override, remembered per-mode options, remote-write confirmation and no-outer-scroll layout.

- [ ] **Step 1: Update the maintainer guide**

Add a “三种构建模式” table with exact version conditions and defaults. Document that local
mode never signs or publishes, and that key generation/trust-anchor rotation remain manual.

- [ ] **Step 2: Run release packaging tests**

Run: `python -m pytest tests/release/packaging -q`

Expected: PASS with no newly introduced warnings.

- [ ] **Step 3: Run lint on changed Python files**

Run:

```powershell
python -m ruff check packaging/release_tool/panel.py packaging/release_tool/panel_policy.py tests/release/packaging/test_release_builder_panel.py tests/release/packaging/test_release_builder_panel_policy.py
```

Expected: PASS.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check`

Expected: no whitespace errors. Confirm no unrelated worktree changes were reverted or staged.

