# 测试目录说明

本目录是项目的测试套件入口，覆盖 CLI/SDK、Web API、GUI、浏览器 E2E、下载核心、配置、日志、打包、架构约束和性能基准。当前测试体系以 `pytest` 为统一执行器，通过 [test_registry.py](test_registry.py) 做分类注册，通过 [test_launcher.py](test_launcher.py) 提供 GUI / TUI / CLI 三模启动器。

## 当前快照

以下数据来自 `python tests/test_registry.py`，更新时间为 2026-07-08：

| 指标 | 当前值 |
| --- | --- |
| 启用分类 | 13 |
| 可运行测试文件 | 131 |
| 套件实现文件 | `test_launcher.py` / `test_registry.py` / `test_runner.py` |
| 未归类测试 | 0 |

测试套件实现文件位于 `tests/` 目录内，但不会作为普通 pytest 测试脚本运行。

## 分类总览

| ID | 名称 | 文件数 | 分组 | 说明 |
| --- | --- | ---: | --- | --- |
| `all` | 全部测试 | 131 | 开始使用 | 运行当前测试目录下所有可执行测试脚本 |
| `cli_sdk` | CLI / SDK | 8 | 接口层 | 命令行、SDK、选择策略、默认值和 Runner |
| `web_api` | Web / API | 14 | 接口层 | FastAPI 端点、Web 入口、Web 控制器桥接和多入口契约 |
| `app_flows` | 应用流程 | 9 | 流程层 | 端到端流程、入口调度与跨模块集成流 |
| `desktop_ui` | 桌面界面 | 21 | 体验层 | Qt 主窗口、控制器、队列面板、宿主适配层、日志和对话框 |
| `browser_e2e` | 浏览器 E2E | 1 | 体验层 | Playwright 驱动的真实浏览器测试与前端交互回归 |
| `pipeline` | 数据管道 | 1 | 流程层 | stdin/stdout JSON 管道、多轮选择与预加载链路 |
| `packaging` | 打包发布 | 1 | 保障层 | spec、runtime hook、资源文件和发布入口完整性 |
| `core_services` | 核心服务 | 75 | 保障层 | 业务核心、下载器、文件服务、配置和基础设施 |
| `architecture` | 架构适应度 | 3 | 保障层 | 依赖方向、Spider 协议和文件大小等结构性约束 |
| `benchmark` | 性能基准 | 1 | 保障层 | 显式运行的轻量性能基准 |
| `suite_infra` | 测试套件 | 2 | 套件自身 | 测试入口、分类注册、启动器 UI 与测试套件自身行为 |
| `misc` | 未归类 | 0 | 扩展测试 | 自动收纳尚未命中规则的新脚本 |

`desktop_ui` 标记为需要 GUI 环境，`browser_e2e` 标记为需要浏览器/网络能力。其它分类默认不依赖真实外部站点。

## 核心基础设施

### [test_registry.py](test_registry.py)

测试注册表是分类事实来源：

- `TestCategory` 保存 id、名称、描述、文件规则、图标、分组、是否需要 GUI / 网络等元数据。
- `register_category_rule()` 通过 glob 规则自动归类测试文件。
- `get_resolved_files(cat_id)` 解析某个分类最终会运行的脚本。
- `auto_discover_tests()` 找出尚未命中任何内置规则的新测试脚本。
- `summary()` 输出当前分类、文件数量和动态插件目录。

新增测试时，优先改文件名让它命中现有规则；只有长期稳定的新职责才扩展注册表规则。

### [test_runner.py](test_runner.py)

测试运行引擎封装 pytest 调用和结果解析：

- `run_category()` 运行单个分类。
- `run_categories()` 顺序运行多个分类。
- `TestResult` 保存通过、失败、跳过、错误、耗时和失败明细。
- `format_summary()` 生成文本汇总，供 CLI/TUI/GUI 共用。

### [test_launcher.py](test_launcher.py)

统一测试启动器，支持 GUI / TUI / CLI：

```bash
python tests/test_launcher.py                 # 默认 GUI
python tests/test_launcher.py --gui           # 强制 GUI
python tests/test_launcher.py --tui           # TUI 菜单
python tests/test_launcher.py --list          # 列出分类
python tests/test_launcher.py --category all
python tests/test_launcher.py --category desktop_ui
python tests/test_launcher.py --category browser_e2e
```

GUI 启动器使用 `test.ico`、独立 AppUserModelID `ucrawl.universalcrawlerpro.test`，并在左侧按分组展示测试分类，右侧显示执行范围、统计、进度和日志。主题切换、浅色模式可读性、缩放最小宽度和运行按钮可见性都属于启动器自身回归范围。

### [run_all_tests.py](run_all_tests.py)

兼容 CLI 入口，仍从注册表读取分类：

```bash
python tests/run_all_tests.py
python tests/run_all_tests.py --list
python tests/run_all_tests.py --category cli_sdk
python tests/run_all_tests.py --category core_services
python tests/run_all_tests.py --no-failfast
```

## 常用运行方式

```bash
# 查看当前分类和文件数
python tests/test_launcher.py --list
python tests/test_registry.py

# 单个分类
python tests/test_launcher.py --category cli_sdk
python tests/test_launcher.py --category web_api
python tests/test_launcher.py --category desktop_ui
python tests/test_launcher.py --category architecture
python tests/test_launcher.py --category benchmark

# 单个文件
python -m pytest tests/test_fastapi_endpoints.py -q
python -m pytest tests/test_main_window.py -q

# 主题 / 顶栏相关快速回归
python -m pytest tests/test_main_window.py -q
python -m pytest tests/test_unified_frontend_contract.py -q -k "theme or top_bar"
```

## 重点分类说明

### CLI / SDK

覆盖 `test_cli_*.py`，包括 CLI 参数、选择策略、管道输入、SDK 生命周期、Runner 默认值和异常边界。

### Web / API

覆盖 FastAPI、WebController、WebSocket、脚本 API、Web session 和多入口契约。`app/web/server.py:create_app()` 是用户真实访问 WebUI 的入口，`app/web/rest_router.py` 是组合式路由入口，两者的 `/api/frontend/state`、`/api/frontend/delta`、`/api/frontend/action`、图标和 i18n 语义必须同步验证。

### 桌面界面

覆盖 PyQt 主窗口、GUI 入口、日志中心、列表分页 worker、媒体预览、队列面板、统一前端契约和 UI 更新调度。主题切换相关测试必须防止以下回归：

- 冻结 `window_root` 导致 shell 黑屏。
- 主题按钮图标先变但页面重绘滞后。
- TopBar / Sidebar / PageStack / StatusBar 或外层 island 消失。
- 主题 busy 状态禁用按钮，导致快速点击后无法恢复。

### 浏览器 E2E

`test_web_browser.py` 使用 Playwright 真实浏览器。用例必须等待可观测状态，不得用固定 3.5 秒硬等兜底。服务输出不能长期挂在无人消费的 `PIPE` 上，避免日志管道填满导致假性变慢或卡住。

历史本地基线：移除固定硬等后，`python -m pytest tests/test_web_browser.py -q` 曾从约 7-8 分钟降至约 188-248 秒。这个数字只作为历史参考，不作为硬性通过标准。

### 架构适应度

`tests/architecture/test_*.py` 用轻量静态检查约束依赖方向、Spider 协议和文件大小。新增大模块或重构分层时，优先补这里，而不是只依赖人工 review。

### 性能基准

`test_performance_benchmarks.py` 是显式运行的轻量基准。它适合发现明显回退，但不能替代真实 GUI/Web 交互验证。

## 编写约定

- 执行入口统一使用 `pytest`。
- 历史测试可继续使用 `unittest.TestCase` 风格。
- 测试文件必须以 `test_` 开头，具体命名规则见 [NAMING.md](NAMING.md)。
- 一个测试聚焦一个行为重点，避免“顺手测很多东西”的大断言。
- 外部站点、浏览器上下文、下载器和文件系统副作用优先 mock 或使用临时目录。
- 不要把测试建立在真实站点稳定性上；真实登录、风控和外部工具可用性仍需要人工验证。
- 新增测试文件后运行 `python tests/test_registry.py`，确认没有落入 `misc`。

## 扩展分类

新增分类或把新脚本接入现有套件时，优先使用注册接口：

```python
from tests.test_registry import register_category, register_category_rule, register_test_files

register_category_rule(
    id="plugin_api",
    name="插件接口",
    description="自动纳入插件接口相关脚本",
    include=["tests/test_plugin_api_*.py"],
)

register_test_files(
    "suite_infra",
    ["tests/test_new_suite_case.py"],
)
```

扩展分类规则后必须同步：

- [test_registry.py](test_registry.py)
- [test_test_entry.py](test_test_entry.py)
- [test_test_launcher_ui.py](test_test_launcher_ui.py)（如果影响启动器 UI）
- [NAMING.md](NAMING.md)
- [../docs/guides/testing.md](../docs/guides/testing.md)

## 历史测试发现的生产 Bug

以下案例作为测试价值说明保留：

1. `RuleSelection.__init__` 中 `self.select = select` 覆盖 `def select()` 方法，后续改为 `self._select_rule`。
2. `cli/main.py` 顶部重复插入项目根目录，后续增加 `if _PROJECT_ROOT not in sys.path:` 检查。
3. SDK `_resolve_selection` 对未 `@runtime_checkable` 的 Protocol 做 `isinstance` 导致 TypeError，后续改为 duck-type check。

## 维护建议

测试目录结构、分类规则、GUI 启动器布局、Web API 入口或主题/日志/前端刷新契约变化时，请同步更新本文档、[NAMING.md](NAMING.md) 和 [../docs/guides/testing.md](../docs/guides/testing.md)。
