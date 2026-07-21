# 同版本修订与可选热更新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为更新客户端和发布工具增加 `(产品版本, 修订号)` 发布身份，使同一产品版本能够以独立 GitHub Release 连续发布，并由 GUI/WebUI 展示、选择和显式安装任意受信修订。

**Architecture:** 在 `shared/` 建立不依赖 UI 的发布身份值对象与运行时身份读取器；更新清单、候选发现、安装状态和 helper 全链路传递该身份。发布工具为每次修订创建唯一标签、清单和二进制身份文件，更新界面只消费已验签且身份一致的候选，不再把 `mandatory` 转化为强制安装行为。

**Tech Stack:** Python 3.10+、PyQt6、FastAPI/WebSocket、原生 JavaScript、PyInstaller、Inno Setup、Git/GitHub CLI、Ed25519、pytest。

## Global Constraints

- `shared/version.py::__version__` 继续作为唯一产品版本事实源，修订号不写回该文件。
- 修订号必须是非负整数，`bool` 不得被当作整数接受；旧清单和旧安装缺少修订字段时解释为 `0`。
- `vX.Y.Z` 表示修订 `0`，`vX.Y.Z-rN` 表示正修订；清单、Release tag、候选、安装请求必须完全一致。
- 每个修订使用独立标签和独立 GitHub Release；不覆盖、删除或重写历史 Release 资产。
- 更新始终由用户确认，`mandatory` 仅作为兼容字段读取，不得隐藏关闭/跳过入口或自动安装。
- 私钥、PFX/P12、密码、令牌和 secret 文件不得进入 Git diff 或 index；每次提交前运行 `python scripts/update_bootstrap.py scan-secrets`。
- 每项先增加能复现缺口的测试，再做最小实现；不顺手重构无关下载、Spider 或 CLI 行为。

---

## Task 1: 建立发布身份与运行时身份文件

**Files:**
- Create: `shared/release_identity.py`
- Test: `tests/release/updater/test_release_identity.py`
- Test: `tests/release/packaging/test_version_contract.py`

- [x] 增加失败测试：标签解析、修订排序、非法修订拒绝、缺失身份文件回退到修订 `0`、打包身份文件读取。
- [x] 运行 `python -m pytest tests/release/updater/test_release_identity.py -q`，确认新测试先失败。
- [x] 实现 `ReleaseIdentity`、`parse_release_tag()`、`format_release_tag()`、`load_runtime_release_identity()` 和面向 UI 的标签格式化。
- [x] 保证文件解析失败时安全回退到产品版本修订 `0`，不让损坏元数据阻断程序启动。
- [x] 运行本任务测试、`python -m py_compile shared/release_identity.py` 和 `git diff --check`。

## Task 2: 更新清单、策略和持久状态改用完整身份

**Files:**
- Modify: `app/services/secure_updater.py`
- Modify: `packaging/update_manifest.py`
- Test: `tests/release/updater/test_secure_updater.py`
- Test: `tests/release/packaging/test_release_pipeline.py`

- [x] 增加失败测试：`releaseRevision` 严格校验、tag/identity 一致性、旧状态迁移、同版本更高修订可更新、同身份默认不可重复安装。
- [x] 运行定向测试，记录 RED 原因。
- [x] 为 `UpdateManifest`、`PendingInstall`、`LocalUpdateState` 增加修订字段，并保持旧 JSON 兼容。
- [x] 将版本策略、跳过记录、启动健康回执和待安装记录升级为完整发布身份比较。
- [x] 让清单生成器输出 `releaseRevision`、标准 tag 和 `sourceCommit`，并永久输出 `mandatory: false`。
- [x] 运行本任务测试、相关 `py_compile`、乱码守卫和 `git diff --check`。

## Task 3: 候选发现、验签、选择与 helper 交接

**Files:**
- Modify: `app/services/update_check_service.py`
- Modify: `entry/updater_helper.py`
- Test: `tests/release/updater/test_update_check_service.py`
- Test: `tests/release/updater/test_updater_helper.py`

- [x] 增加失败测试：同版本多修订聚合、默认选择最高身份、指定候选不歧义、Release tag 与清单不一致被排除、helper 校验修订。
- [x] 运行定向测试，确认当前实现仅按版本比较而失败。
- [x] 为候选增加稳定 `candidate_id` 和完整 identity；按版本、修订降序排序并检测同身份冲突。
- [x] 自动检查只把高于本机身份的候选标记为可更新，手动流程保留已验签的其他修订供显式选择。
- [x] 下载元数据目录、准备结果、helper 参数和交接 JSON 全部携带修订，避免同版本资产互相覆盖。
- [x] 运行本任务测试、`py_compile`、乱码守卫和 `git diff --check`。

## Task 4: GUI 与 WebUI 增加修订选择并移除强制更新交互

**Files:**
- Modify: `app/ui/dialogs/update_check.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/layout/status_bar.py`
- Modify: `app/web/rest_router.py`
- Modify: `app/web/static/app.js`
- Modify: `app/web/static/i18n.js`
- Modify: `shared/i18n_catalogs.py`
- Test: `tests/unit/app/ui/test_dialogs.py`
- Test: `tests/unit/app/ui/test_main_window.py`
- Test: `tests/integration/app/web/test_websocket_server.py`
- Test: `tests/contract/frontend/test_i18n_logs.py`

- [x] 增加失败测试：候选下拉显示初始版/修订号、默认最新、提交 candidate id、任何清单都保留取消和跳过入口。
- [x] 更新 REST 公共结果和 prepare 请求，使用 `candidate_id`，调用方不能伪造本机修订。
- [x] GUI/WebUI 使用运行时身份作为当前版本，显示 `vX.Y.Z-rN`；同产品版本的修订在一个选择器中呈现。
- [x] 对回退/重装显示明确二次确认；普通升级仍是单次确认，永不自动开始安装。
- [x] 补齐双端翻译字典，运行 UI/Web 定向测试、乱码守卫和 `git diff --check`。

## Task 5: 发布面板计算下一修订并展示真实目标

**Files:**
- Modify: `packaging/release_tool/versioning.py`
- Modify: `packaging/release_tool/models.py`
- Modify: `packaging/release_tool/remote.py`
- Modify: `packaging/release_tool/panel_policy.py`
- Modify: `packaging/release_tool/modes.py`
- Modify: `packaging/release_tool/panel.py`
- Modify: `packaging/release_tool/runner.py`
- Test: `tests/release/packaging/test_release_tool_remote.py`
- Test: `tests/release/packaging/test_release_tool_modes.py`
- Test: `tests/release/packaging/test_release_builder_panel_policy.py`
- Test: `tests/release/packaging/test_release_builder_panel.py`
- Test: `tests/release/packaging/test_release_tool_runner.py`

- [x] 增加失败测试：远端 Release 列表解析同版本修订、下一修订计算、同版本修订请求、面板显示目标 tag。
- [x] 远端读取改为有界枚举 Releases，而非只依赖 `/releases/latest`；忽略不符合本项目标签协议的条目。
- [x] “同版本修复”改成“发布同版本新修订”，自动建议 `max(revision)+1`，并清楚显示即将创建的独立 tag。
- [x] 删除“源提交必须等于旧标签”的阻断逻辑；改为新修订标签若已存在则必须指向当前 HEAD，否则拒绝复用。
- [x] 请求文件严格传递 `release_revision`，非法、遗漏或远端状态未知时给出可操作错误。
- [x] 运行本任务测试、`py_compile`、乱码守卫和 `git diff --check`。

## Task 6: 构建产物写入修订身份

**Files:**
- Modify: `packaging/build_release.py`
- Modify: `packaging/build_portable.py`
- Modify: `packaging/build_installer.py`
- Modify: `packaging/installer.iss`
- Test: `tests/release/packaging/test_release_pipeline.py`
- Test: `tests/release/packaging/test_build_installer_resilience.py`
- Test: `tests/release/packaging/test_version_contract.py`

- [x] 增加失败测试：修订 tag 构建、缺失新 tag 可构建、已存在冲突 tag 拒绝、portable 身份文件、安装器四段数字版本。
- [x] 构建入口按完整身份创建发布目录和资产名，快照仍固定到本次 source commit。
- [x] portable 根目录写入 `release_identity.json`；安装包携带该文件，并将显示版本与 Windows 四段版本分别传入 Inno Setup。
- [x] staged asset 校验同时核对 version、revision、tag、sourceCommit，阻止混装不同修订资产。
- [x] 运行本任务测试、构建脚本 `py_compile`、乱码守卫和 `git diff --check`。

## Task 7: 发布独立 Release，禁止同版本资产覆盖

**Files:**
- Modify: `packaging/build_release.py`
- Modify: `packaging/release_tool/publisher.py`
- Modify: `docs/guides/release-builder.md`
- Test: `tests/release/packaging/test_release_tool_publisher.py`
- Test: `tests/release/packaging/test_release_pipeline.py`

- [x] 增加失败测试：修订模式创建独立 tag/Release、已存在同名但摘要不同的资产失败、不得传 `--clobber`。
- [x] 发布流程为当前 identity 创建 tag 和 Release；重试时只允许相同摘要的幂等跳过。
- [x] 更新发布指南，明确初版/修订标签、首次协议升级要求、旧客户端无法发现同 SemVer 修订的兼容边界。
- [x] 运行发布工具定向测试、文档/乱码守卫和 `git diff --check`。

## Task 8: 全链回归、安全审计与推送

**Files:**
- Modify: only files required by failing regressions

- [ ] 运行更新链路和发布链路完整定向套件。
- [ ] 运行 GUI/WebUI 契约、i18n、架构预算与浏览器静态契约测试。
- [ ] 运行 `python -m pytest -q`；若环境性测试不能执行，保留完整失败证据并确认不是本次回归。
- [ ] 运行 `python -m compileall app shared entry packaging -q`、`python -m pytest tests/test_mojibake_guard.py -q` 和 `git diff --check`。
- [ ] 运行 `python scripts/update_bootstrap.py scan-secrets`，检查 `git diff --cached --name-only` 和 `git diff --cached`，确认无私钥、PFX/P12、密码、token 或 secret 文件/内容。
- [ ] 用中文提交说明创建最终提交，确认工作树状态后推送当前 `main`。
