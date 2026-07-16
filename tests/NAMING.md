# 测试命名规范

> 更新时间：2026-07-16
> 适用范围：`tests/` 目录下所有 pytest 测试文件与辅助脚本

## 目标

测试套件由目录表达职责，目录后的路径表达生产代码归属，pytest marker 只表达跨领域的运行约束。新增测试不再依赖文件名前缀白名单，也不需要把文件逐个登记到内置分类。

当前事实来源是 [support/catalog.py](support/catalog.py)，长期 Agent 约束见 [AGENTS.md](AGENTS.md)。修改布局或命名规则前后运行：

```bash
python tests/support/catalog.py
python tests/launcher.py --list
python -m pytest tests/architecture/test_test_suite_layout.py -q
```

## 三维命名模型

```text
tests/<suite>/<production namespace>/test_<observable responsibility>.py
```

三个维度互不混用：

1. 第一层目录决定测试套件。
2. 后续目录镜像生产命名空间或稳定的外部边界。
3. marker 描述浏览器、网络、串行、慢速等运行能力与约束。

例如：

```text
tests/unit/app/spiders/missav/test_challenge_browser.py
tests/unit/app/spiders/kuaishou/test_auth_persistence.py
tests/integration/app/core/downloaders/m3u8/test_lifecycle.py
tests/contract/web/test_fastapi_endpoints.py
tests/e2e/web/test_browser_journeys.py
tests/release/packaging/test_assets.py
```

文件名无需重复 `unit`、`app_spiders`、平台名全路径等已经由父目录表达的信息。

## 八个内置套件

| 根目录 | 判定标准 | 典型内容 |
| --- | --- | --- |
| `tests/unit/` | 单一行为被隔离，外部进程、网络、浏览器、时间和持久化边界被替换或受控 | 模型、服务、控制器、Spider 分支、UI 组件逻辑 |
| `tests/integration/` | 多个真实项目组件或本地进程/存储边界协作 | 控制器流程、下载生命周期、WebSocket、发布竞态 |
| `tests/contract/` | 验证稳定且对外可观察的协议或兼容承诺 | CLI/API/配置/入口/前端静态与交互契约 |
| `tests/e2e/` | 从真实入口完成完整用户旅程 | Chromium WebUI 关键路径、未来的完整应用旅程 |
| `tests/architecture/` | 静态约束仓库结构或设计边界 | 依赖方向、文件规模、目录布局、命名规则 |
| `tests/performance/` | 断言耗时、吞吐、分配或性能预算 | 无覆盖率插桩的显式性能基准 |
| `tests/release/` | 验证交付工程 | CI、打包、安装、更新、发布资源 |
| `tests/testkit/` | 验证测试体系自身 | catalog、launcher、runner、插件扩展接口 |

判定有歧义时先问“失败说明哪个责任层出了问题”，再看依赖规模：

- mock 了浏览器并不自动等于 E2E；如果只验证 Spider 的一个分支，通常仍是 unit。
- 使用 `TestClient` 并不自动等于 integration；如果核心目标是 HTTP 对外契约，放 contract。
- 文件名带 `integration` 或 `e2e` 不决定套件，实际边界和可观察行为才决定。
- 平台名（Bilibili、Kuaishou、MissAV）属于生产路径，不是套件或 marker。

## 文件、类和方法命名

- 可被 pytest 收集的模块必须使用 `test_*.py`。
- 模块使用 `test_<observable responsibility>.py`，一个模块表达一个稳定职责。
- 测试类使用 `Test<CapabilityOrScenario>`。
- 测试方法使用 `test_<observable_behavior>`；条件重要时使用 `test_<observable_result>_when_<condition>`。
- 优先写用户或调用方可观察的结果，不把临时实现细节写进名字。

推荐：

- `test_theme_toggle_coalesces_rapid_clicks_to_latest_state`
- `test_frontend_delta_returns_recoverable_snapshot_when_version_missing`
- `test_download_worker_releases_slot_after_failure`
- `test_rejects_private_address_when_dns_rebinds`

不推荐：

- `test_case_1`
- `test_logic`
- `test_fix_bug`
- `test_new`
- `test_misc`
- `test_works`

这些模糊名称由架构契约阻止。

## Marker 规则

已注册 marker 只表达运行约束：

- `architecture`
- `benchmark`
- `browser`
- `gui`
- `network`
- `security`
- `serial`
- `slow`
- `windows`

禁止把产品域或文件归属做成 marker，例如 `bilibili`、`kuaishou`、`missav`、`web_api`、`downloader`。新增 marker 必须先在 `pyproject.toml` 注册；`--strict-markers` 必须保持启用。

## 辅助代码命名

可复用的非测试 helper 放在 `tests/support/`，不得使用 `test_` 前缀：

- 浏览器 case：`tests/support/browser_cases/*.py`
- 浏览器生命周期：`tests/support/browser_runtime.py`
- 测试 Web 应用：`tests/support/web_test_app.py`
- 前端静态契约 helper：`tests/support/frontend_static_assets.py`
- 目录 catalog / runner：`tests/support/catalog.py`、`tests/support/runner.py`

根目录只保留 pytest 特殊入口和非收集型运行脚本：

- `tests/conftest.py`
- `tests/launcher.py`
- `tests/run_*.py`

复现脚本使用 `reproduce_*.py`，运行脚本使用 `run_*.py`。

## 内置套件禁止白名单

内置套件只能在 `BUILTIN_SUITE_ROOTS` 中声明目录根。不得为 CI 通过而加入：

- 精确文件列表；
- 业务前缀 glob；
- include/exclude 例外；
- 根目录测试白名单；
- 将新文件塞入 `misc` 的兜底规则。

插件或第三方扩展在运行时注册外部文件/目录时仍可使用显式文件和 glob，因为它们不属于内置分类。

如果确实出现第九种长期稳定的测试职责，需要先完成架构决策，并同步 catalog、CI、launcher、架构契约和活动文档；不要只改一个列表。

## 新增测试检查清单

新增测试前：

1. 按隔离程度和行为责任选择八个套件之一。
2. 镜像生产命名空间或稳定边界。
3. 选择能描述可观察职责的模块名。
4. 判断是否需要已注册的运行约束 marker。

新增测试后：

```bash
python -m pytest tests/<suite>/<namespace>/test_<responsibility>.py -q
python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q
python tests/launcher.py --list
python -m pytest tests --collect-only -q
```

`auto_discover_tests()` 必须返回空列表。性能套件必须脱离覆盖率插桩运行，浏览器 E2E 必须在 Chromium 环境单独运行。

## 变更命名体系

只有测试的稳定责任模型确实发生变化时才修改本规范。变更后同步：

- [AGENTS.md](AGENTS.md)
- [support/catalog.py](support/catalog.py)
- [architecture/test_test_suite_layout.py](architecture/test_test_suite_layout.py)
- [testkit/test_catalog.py](testkit/test_catalog.py)
- [testkit/test_launcher_ui.py](testkit/test_launcher_ui.py)（影响展示时）
- [README.md](README.md)
- [../docs/guides/testing.md](../docs/guides/testing.md)
- `.github/workflows/python-tests.yml`

历史实施记录不随当前规则回写；活动文档和代码必须只使用当前目录体系。
