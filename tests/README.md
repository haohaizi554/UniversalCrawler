# 测试目录说明

本目录是项目统一测试入口，覆盖隔离行为、组件协作、公共契约、真实用户旅程、架构适应度、性能预算、发布工程和测试基础设施。pytest 是唯一执行器；[support/catalog.py](support/catalog.py) 按八个规范目录发现内置套件，[launcher.py](launcher.py) 提供 GUI / TUI / CLI 三模入口。

完整命名规范见 [NAMING.md](NAMING.md)，Agent 必须遵守 [AGENTS.md](AGENTS.md)。

## 目录总览

```text
tests/
├── unit/          # 隔离、确定的单元行为
├── integration/   # 多个真实组件或本地边界协作
├── contract/      # API、CLI、配置、入口、前端与兼容契约
├── e2e/           # 完整入口和真实浏览器用户旅程
├── architecture/  # 依赖、布局、规模和命名适应度规则
├── performance/   # 显式、无覆盖率插桩的性能预算
├── release/       # CI、打包、安装、更新和发布资产
├── testkit/       # catalog、launcher、runner 自身测试
├── support/       # 不被 pytest 收集的共享 helper
├── conftest.py    # pytest 全局 fixture
├── launcher.py    # GUI / TUI / CLI 统一入口
└── run_*.py       # 兼容运行脚本
```

套件目录是分类事实来源。新增 `test_*.py` 后会被所属根目录自动发现，不需要向内置文件列表或前缀白名单登记。

迁移验收时 catalog 报告 8 个内置套件、182 个测试模块，pytest 收集 3104 个测试。数量会随功能演进而变化，布局契约和启动器均动态计算，不把快照当作硬编码门槛。

## 八个内置套件

| ID | 中文名 | 责任 |
| --- | --- | --- |
| `unit` | 单元测试 | 隔离、确定且默认不访问真实外部资源的行为 |
| `integration` | 集成测试 | 多个真实项目组件或本地进程/存储边界协作 |
| `contract` | 契约测试 | 公共 API、CLI、配置、入口、前后端协议和兼容性承诺 |
| `e2e` | 端到端测试 | 完整入口与真实浏览器关键旅程 |
| `architecture` | 架构适应度 | 依赖方向、目录、命名、规模和仓库结构契约 |
| `performance` | 性能预算 | 耗时、吞吐或性能预算，独立于覆盖率插桩运行 |
| `release` | 发布验证 | CI、打包、安装、升级和发布资产完整性 |
| `testkit` | 测试基础设施 | catalog、launcher、runner 和插件 API 自身行为 |

`all` 是八个内置套件与已注册插件的联合运行视图，不是第九个套件。`misc` 是禁用的布局违规视图，正常情况下必须为空。

## 核心基础设施

### [support/catalog.py](support/catalog.py)

- `BUILTIN_SUITE_ROOTS` 是八个内置目录的唯一声明。
- `get_resolved_files(suite_id)` 从目录递归解析测试模块。
- `auto_discover_tests()` 报告不在规范套件根目录下的测试；它必须返回空列表。
- `summary()` 输出套件、模块、插件和支持文件统计。
- 运行时插件仍可注册显式文件或 glob；内置套件禁止这样做。

### [support/runner.py](support/runner.py)

- `run_category()` 运行单个套件或插件分类。
- `run_categories()` 顺序运行多个选择项。
- `TestResult` 保存通过、失败、跳过、错误、耗时和失败明细。
- `format_summary()` 供 CLI、TUI、GUI 共用。

### [launcher.py](launcher.py)

```bash
python tests/launcher.py                  # 默认 GUI
python tests/launcher.py --gui            # 强制 GUI
python tests/launcher.py --tui            # TUI 菜单
python tests/launcher.py --list           # 列出八个套件及 all 视图
python tests/launcher.py --category unit
python tests/launcher.py --category contract
python tests/launcher.py --category e2e
python tests/launcher.py --category all
```

GUI 左侧按责任分组展示套件，卡片数和脚本数直接来自 catalog；右侧显示执行范围、统计、进度和日志。滚动区、分组计数、浅/深色对比、90%–125% 缩放、最小窗口宽度和运行按钮可见性都由 `tests/testkit/test_launcher_ui.py` 回归。

### 兼容运行脚本

```bash
python tests/run_all_tests.py --list
python tests/run_all_tests.py --category unit
python tests/run_all_tests.py --category integration
python tests/run_core_suite.py
python tests/run_blackbox_whitebox_tests.py
```

这些脚本从 catalog 读取目录套件，不维护静态文件清单。`run_core_suite.py` 运行 `unit + integration`；黑盒/白盒兼容入口分别映射到 `contract` / `unit`。

## 常用运行方式

```bash
# 定向模块
python -m pytest tests/unit/app/ui/components/test_media_preview_panel.py -q

# 单个套件
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python -m pytest tests/contract -q

# 结构与测试基础设施
python -m pytest tests/architecture tests/testkit -q

# 单独运行，避免覆盖率插桩影响预算
python -X faulthandler -m pytest tests/performance -q

# 需要 Chromium 的真实浏览器套件
python -X faulthandler -m pytest tests/e2e -q

# 检查完整收集与目录违规
python -m pytest tests --collect-only -q
python tests/support/catalog.py
```

CI 对 `app`、`cli`、`entry`、`shared` 四个核心生产包执行分支覆盖率门槛 75%；唯一门槛配置位于 `pyproject.toml` 的 `tool.coverage.report.fail_under`，性能和浏览器套件分别运行，不能为提高覆盖率而混入或忽略。

## 浏览器 E2E

真实 Chromium 聚合入口是 [e2e/web/test_browser_journeys.py](e2e/web/test_browser_journeys.py)。交互 case 位于 `tests/support/browser_cases/`，共享 uvicorn/Chromium 生命周期位于 `tests/support/browser_runtime.py`，测试应用 shim 位于 `tests/support/web_test_app.py`。

用例必须等待可观察状态，不得用固定 3.5 秒硬等来赌页面稳定。服务输出不能长期挂在无人消费的 `subprocess.PIPE` 上，避免日志管道填满造成假性卡死。Playwright 公网防护相关回归同时覆盖 BrowserContext 路由、popup 首请求、WebSocket、Worker、SharedWorker 和 Service Worker 绕过。

## 编写约定

- 按隔离程度和可观察责任选择套件，不能按文件名前缀、平台名或当前 CI job 选择。
- 套件后的目录镜像生产命名空间，例如 `tests/unit/app/services/`。
- marker 只描述运行约束；当前严格注册 `architecture`、`benchmark`、`browser`、`gui`、`network`、`security`、`serial`、`slow`、`windows`。
- 一个测试聚焦一个行为重点；历史主体可继续使用 `unittest.TestCase`。
- 外部站点、浏览器上下文、下载器和文件系统副作用优先使用 mock、fake 或临时目录。
- 不把测试建立在真实站点稳定性上；真实登录、风控和外部工具环境仍需人工验证。
- 共享 helper 放 `tests/support/` 且不使用 `test_` 前缀。
- 禁止给内置套件增加精确文件、业务前缀 glob、include/exclude 或 `misc` 白名单。

新增测试后至少运行：

```bash
python -m pytest tests/<suite>/<namespace>/test_<responsibility>.py -q
python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q
python tests/launcher.py --list
python -m pytest tests --collect-only -q
```

## 插件扩展

目录套件是项目内置测试的唯一分类方式。只有第三方或运行时插件分类可使用显式文件和 glob：

```python
from tests.support.catalog import register_plugin_directory, register_category

register_plugin_directory(
    id="plugin_api",
    name="插件接口",
    directory="external-tests/plugin_api",
    pattern="test_*.py",
)

register_category(
    id="manual_extension",
    name="手工扩展",
    description="外部扩展测试",
    files=["external-tests/test_extension.py"],
)
```

插件分类不得修改八个内置根目录的含义。若出现真正的新内置责任层，必须同步架构决策、catalog、CI、launcher、架构测试和活动文档。

## 历史测试发现的生产 Bug

以下案例作为测试价值说明保留：

1. `RuleSelection.__init__` 中 `self.select = select` 覆盖 `def select()` 方法，后续改为 `self._select_rule`。
2. `cli/main.py` 顶部重复插入项目根目录，后续增加 `if _PROJECT_ROOT not in sys.path:` 检查。
3. SDK `_resolve_selection` 对未 `@runtime_checkable` 的 Protocol 做 `isinstance` 导致 TypeError，后续改为 duck-type check。

## 维护建议

测试目录、suite 职责、GUI 启动器布局、Web API 入口、主题/日志/前端契约或 CI 选择发生变化时，增量更新本文档、[NAMING.md](NAMING.md)、[AGENTS.md](AGENTS.md) 和 [../docs/guides/testing.md](../docs/guides/testing.md)。历史记录不回写成当前状态。
