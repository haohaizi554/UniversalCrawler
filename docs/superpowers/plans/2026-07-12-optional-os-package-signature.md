# Optional OS Package Signature Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让当前个人发布版本在没有 Authenticode 证书时仍可完成自有安全更新流程，同时保留未来一键恢复系统发布者证书校验的接口。

**Architecture:** `PackageVerifier` 始终执行已签名清单约束的大小与 SHA-256 校验，并通过安全默认值为 `True` 的显式参数决定是否继续执行操作系统签名校验。桌面 GUI 与独立 updater helper 从同一只读配置读取该策略，确保下载后和安装前两次校验一致。

**Tech Stack:** Python 3.11+、PyQt6、PyCryptodome Ed25519、pytest/unittest、Windows Authenticode PowerShell、静态 JSON/Python i18n catalog。

## Global Constraints

- `latest.json.sig` 的 Ed25519 验证始终强制，不能引入未签名 Release 降级路径。
- 清单版本、`minClientVersion`、受信 URL、安装包大小和 SHA-256 始终强制。
- `PackageVerifier` 的默认策略仍为要求系统签名，只有应用配置显式关闭。
- 当前 `UPDATE_REQUIRE_OS_SIGNATURE = False`，未来配置发布者、指纹并改为 `True` 即恢复 Authenticode。
- 不改版本选择、断点续传、安装器参数、退出或重启协议。
- 不向 Git 写入私钥、PFX/P12、PIN、密码或云签名凭据。

---

### Task 1: 为 PackageVerifier 增加显式系统签名策略

**Files:**
- Modify: `tests/test_secure_updater.py:665`
- Modify: `app/services/secure_updater.py:1057-1085`

**Interfaces:**
- Consumes: `PackageVerifier.verify(path: Path, asset: UpdateAsset) -> None`
- Produces: `PackageVerifier(..., require_os_signature: bool = True)`；无论开关值如何都先执行 `_verify_file_hash()`。

- [ ] **Step 1: 写入关闭系统签名但保留完整性校验的失败测试**

```python
from dataclasses import replace


def test_package_verifier_explicitly_skips_os_signature_after_hash_check(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("Authenticode command must not run when explicitly disabled")

    PackageVerifier(
        os_name="windows",
        require_os_signature=False,
        run_func=unexpected_run,
    ).verify(installer, asset)


def test_package_verifier_cannot_skip_hash_when_os_signature_is_disabled(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"tampered")
    asset = _windows_asset_for_file(installer)
    asset = replace(asset, sha256="0" * 64)

    with pytest.raises(VerificationError, match="hash|sha256"):
        PackageVerifier(os_name="windows", require_os_signature=False).verify(installer, asset)
```

- [ ] **Step 2: 运行定点测试并确认因缺少构造参数而失败**

Run: `python -m pytest tests/test_secure_updater.py -k "explicitly_skips_os_signature or cannot_skip_hash" -q`

Expected: FAIL，`PackageVerifier.__init__()` 报告不接受 `require_os_signature`。

- [ ] **Step 3: 实现最小策略开关并补充维护注释**

```python
class PackageVerifier:
    """校验安装包完整性，并按发布策略选择是否追加操作系统签名校验。"""

    def __init__(
        self,
        *,
        os_name: str | None = None,
        trusted_publishers: list[str] | tuple[str, ...] = (),
        trusted_thumbprints: list[str] | tuple[str, ...] = (),
        require_os_signature: bool = True,
        verify_func: Callable[[Path, UpdateAsset], None] | None = None,
        run_func: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        ...
        self.require_os_signature = bool(require_os_signature)

    def verify(self, path: Path, asset: UpdateAsset) -> None:
        # 该哈希来自 Ed25519 签名清单，即使暂缓 Authenticode 也不能跳过。
        _verify_file_hash(path, asset)
        if self._verify_func:
            self._verify_func(path, asset)
            return
        if not self.require_os_signature:
            return
        ...
```

- [ ] **Step 4: 运行新测试和现有系统签名测试**

Run: `python -m pytest tests/test_secure_updater.py -k "PackageVerifier or verifier or authenticode" -q`

Expected: PASS；现有空指纹、错误发布者、错误指纹和无效签名测试仍保持严格失败语义。

### Task 2: 将同一配置接入 GUI 与独立 helper

**Files:**
- Modify: `app/config/update_trust.py:1-13`
- Modify: `app/services/update_check_service.py:17-21`
- Modify: `app/ui/main_window.py:25-35, 911-914`
- Modify: `entry/updater_helper.py:1-20, 139-142`
- Test: `tests/test_secure_updater.py:910-1068`
- Test: `tests/test_update_check_service.py:575-590`

**Interfaces:**
- Consumes: `PackageVerifier(..., require_os_signature: bool)` from Task 1。
- Produces: `UPDATE_REQUIRE_OS_SIGNATURE: bool`，由 GUI 和 helper 共同读取；当前固定为 `False`。

- [ ] **Step 1: 写入配置和双入口接线的失败测试**

```python
def test_update_trust_config_explicitly_disables_os_signature_for_personal_releases():
    from app.config.update_trust import UPDATE_REQUIRE_OS_SIGNATURE

    assert UPDATE_REQUIRE_OS_SIGNATURE is False


def test_update_entrypoints_pass_shared_os_signature_policy():
    gui_source = Path("app/ui/main_window.py").read_text(encoding="utf-8")
    helper_source = Path("entry/updater_helper.py").read_text(encoding="utf-8")

    for source in (gui_source, helper_source):
        assert "UPDATE_REQUIRE_OS_SIGNATURE" in source
        assert "require_os_signature=UPDATE_REQUIRE_OS_SIGNATURE" in source
```

并在现有 `test_update_trust_config_contains_only_public_trust_anchors` 中断言配置包含 `UPDATE_REQUIRE_OS_SIGNATURE`，同时继续禁止敏感材料。

- [ ] **Step 2: 运行接线测试并确认缺少配置常量而失败**

Run: `python -m pytest tests/test_secure_updater.py tests/test_update_check_service.py -k "os_signature_policy or explicitly_disables_os_signature or public_trust_anchors" -q`

Expected: FAIL，导入 `UPDATE_REQUIRE_OS_SIGNATURE` 失败或入口源码缺少显式传参。

- [ ] **Step 3: 增加只读配置与中文维护说明**

```python
# Authenticode 是自有 Ed25519 清单签名之外的第二层发布者身份校验。
# 个人发布阶段暂未配置受信代码签名证书，因此显式关闭；安装包大小和
# SHA-256 仍由签名清单强制校验。取得证书后填写下方白名单并改为 True。
UPDATE_REQUIRE_OS_SIGNATURE = False
UPDATE_TRUSTED_PUBLISHERS: tuple[str, ...] = ()
UPDATE_TRUSTED_THUMBPRINTS: tuple[str, ...] = ()
```

注释不得包含任何真实私钥路径、PIN 或凭据值。

- [ ] **Step 4: 在兼容导出、GUI 和 helper 中传递同一开关**

```python
from app.config.update_trust import (
    UPDATE_PUBLIC_KEY_PEM,
    UPDATE_REQUIRE_OS_SIGNATURE,
    UPDATE_TRUSTED_PUBLISHERS,
    UPDATE_TRUSTED_THUMBPRINTS,
)

PackageVerifier(
    trusted_publishers=UPDATE_TRUSTED_PUBLISHERS,
    trusted_thumbprints=UPDATE_TRUSTED_THUMBPRINTS,
    require_os_signature=UPDATE_REQUIRE_OS_SIGNATURE,
).verify(installer_path, asset)
```

helper 的模块说明改为“始终重验清单和哈希，并按项目发布策略追加 OS 签名校验”，避免注释宣称未发生的行为。

- [ ] **Step 5: 运行接线回归测试**

Run: `python -m pytest tests/test_secure_updater.py tests/test_update_check_service.py -k "os_signature_policy or explicitly_disables_os_signature or public_trust_anchors or updater_helper" -q`

Expected: PASS。

### Task 3: 让更新界面准确描述当前强制校验

**Files:**
- Modify: `app/ui/dialogs/update_check.py:386-392, 478`
- Modify: `app/ui/main_window.py:654-659`
- Modify: `app/ui/i18n/en-US.json:483,490`
- Modify: `app/ui/i18n/zh-TW.json:483,490`
- Modify: `shared/i18n_catalogs.py`
- Test: `tests/test_update_check_service.py:575-590`
- Test: `tests/test_guardrails.py:925-939`

**Interfaces:**
- Consumes: `tr(source_text, language)` 的静态词典约定。
- Produces: 用户可见文案只承诺“更新清单签名、大小和 SHA-256 校验”。

- [ ] **Step 1: 写入禁止误导性系统签名文案的失败测试**

```python
def test_update_ui_describes_only_mandatory_verification_layers(self):
    dialog_source = Path("app/ui/dialogs/update_check.py").read_text(encoding="utf-8")
    main_source = Path("app/ui/main_window.py").read_text(encoding="utf-8")
    combined = dialog_source + main_source

    assert "更新清单签名、大小和 SHA-256 校验" in combined
    assert "系统签名校验" not in combined
```

- [ ] **Step 2: 运行文案测试并确认旧文案导致失败**

Run: `python -m pytest tests/test_update_check_service.py -k "mandatory_verification_layers" -q`

Expected: FAIL，源码仍包含“系统签名校验”。

- [ ] **Step 3: 更新简体中文源文本及英繁静态词典**

统一使用源文本：

```text
更新前建议关闭正在运行的采集任务。安装包会先完成更新清单签名、大小和 SHA-256 校验。
安装包会先完成更新清单签名、大小和 SHA-256 校验。
```

英文使用 `signed update manifest, size, and SHA-256`，繁体使用 `更新清單簽章、大小和 SHA-256 校驗`。同步更新 JSON 与 `shared/i18n_catalogs.py`，确保运行时静态 catalog 与 JSON 完全相同。

- [ ] **Step 4: 运行文案和静态 catalog 一致性测试**

Run: `python -m pytest tests/test_update_check_service.py tests/test_guardrails.py -k "mandatory_verification_layers or runtime_i18n_catalog" -q`

Expected: PASS。

### Task 4: 全链路验证与敏感信息门禁

**Files:**
- Verify only: all files modified in Tasks 1-3

**Interfaces:**
- Consumes: Tasks 1-3 的实现和测试。
- Produces: 可发布的更新校验策略变更，不包含敏感签名材料。

- [ ] **Step 1: 编译修改的 Python 文件**

Run: `python -m py_compile app/config/update_trust.py app/services/secure_updater.py app/services/update_check_service.py app/ui/main_window.py app/ui/dialogs/update_check.py entry/updater_helper.py`

Expected: exit 0。

- [ ] **Step 2: 运行更新与打包核心套件**

Run: `python -m pytest tests/test_secure_updater.py tests/test_update_check_service.py tests/test_update_bootstrap.py tests/test_packaging.py tests/test_guardrails.py tests/test_mojibake_guard.py -q`

Expected: 全部 PASS，无 warning/error 回溯。

- [ ] **Step 3: 运行静态和差异检查**

Run: `python -m ruff check app/config/update_trust.py app/services/secure_updater.py app/services/update_check_service.py app/ui/main_window.py app/ui/dialogs/update_check.py entry/updater_helper.py tests/test_secure_updater.py tests/test_update_check_service.py`

Run: `git diff --check`

Expected: 两条命令均 exit 0。

- [ ] **Step 4: 在暂存前后运行敏感信息扫描**

Run: `python -m scripts.update_bootstrap scan-secrets --project-root .`

Expected: `scan-secrets passed`，并确认 diff/index 中没有私钥、PFX、P12、密码或凭据文件。

- [ ] **Step 5: 审阅最终差异并提交**

```powershell
git diff --stat
git diff -- app/config/update_trust.py app/services/secure_updater.py app/services/update_check_service.py app/ui/main_window.py entry/updater_helper.py
git add app tests docs/superpowers/plans/2026-07-12-optional-os-package-signature.md
python -m scripts.update_bootstrap scan-secrets --project-root .
git diff --cached --check
git commit -m "允许个人发布暂缓系统签名校验"
```

Expected: 提交只包含本计划范围内文件；scan-secrets 与 cached diff 检查均通过。
