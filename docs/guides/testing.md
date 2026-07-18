# 测试指南

## 测试目标

本项目测试承担以下职责：

- 保护高频重构区域，避免控制流回归
- 保护高风险爬虫逻辑（登录、取流、任务装配、入队）
- 保护文件落盘与 UI 编排的关键边界
- **保护多入口一致性**（CLI / SDK / REST API / Web UI）
- **保护 GUI / WebUI 配置中心契约**（同源快照、热加载、零值边界、设置页懒加载）
- **保护打包配置完整性**（hiddenimports / datas / icon / runtime hook）
- **保护 stdin/stdout 管道选择**（合集场景的多轮交互）

## 行业测试标准

本项目测试遵循：

- **测试金字塔**（Mike Cohn）：底层单元最多，向上集成、E2E 递减
- **FIRST 原则**：Fast / Independent / Repeatable / Self-validating / Timely
- **AAA 模式**：Arrange / Act / Assert
- **黑盒 vs 白盒**：黑盒看 API 行为，白盒 mock 内部实现
- **契约测试**：验证多个入口输出一致
- **Pipeline 测试**：验证 stdin/stdout 数据流转换
- **Web E2E**：Playwright + 真实浏览器 + 静态/可访问性/设计指南审查

## 测试基础设施（目录套件）

### 目录 catalog [support/catalog.py](../../tests/support/catalog.py)

八个内置套件由目录根唯一确定：`unit`、`integration`、`contract`、`e2e`、`architecture`、`performance`、`release`、`testkit`。

- `BUILTIN_SUITE_ROOTS` 是内置套件的唯一声明，不接受精确文件、前缀 glob 或 include/exclude 白名单。
- `get_enabled_categories()` 按 priority 输出八个套件、`all` 联合视图和运行时插件。
- `get_resolved_files(suite_id)` 递归解析目录；新增测试无需登记文件名。
- `auto_discover_tests()` 报告规范根目录之外的测试，正常结果必须为空。
- `misc` 只是禁用的布局违规兼容视图，不是新增测试的目标分类。
- 显式文件与 glob 仅保留给第三方/运行时插件分类。

完整目录与命名约束见 [tests/NAMING.md](../../tests/NAMING.md)，Agent 约束见 [tests/AGENTS.md](../../tests/AGENTS.md)。

### 测试运行引擎 [support/runner.py](../../tests/support/runner.py)

封装 pytest 调用与结果解析：

- `TestResult` dataclass（passed/failed/skipped/errors/duration/failed_tests）
- `run_category()` 运行单个目录套件或插件分类
- `run_categories()` 顺序运行多个选择项
- `format_summary()` 生成 GUI/TUI/CLI 共用汇总
- 进度回调供 GUI 逐模块更新

### 统一测试入口 [launcher.py](../../tests/launcher.py)

**三模自适应启动器**（GUI / TUI / CLI）：

```bash
python tests/launcher.py                    # Qt GUI（默认）
python tests/launcher.py --category unit
python tests/launcher.py --category contract
python tests/launcher.py --category e2e
python tests/launcher.py --category all
python tests/launcher.py --tui              # 无 GUI 环境
python tests/launcher.py --list             # 列出目录套件
python tests/launcher.py --gui
```

特性：

- 左侧按责任分组显示八套件，卡片数、分组数和脚本数均来自 catalog
- 右侧显示选择范围、执行统计、进度和滚动日志
- F5 运行 / Ctrl+1 全部 / Ctrl+R 推荐 / Esc 清空
- failfast / verbose 复选框
- 浅/深色、90%–125% 缩放、最小窗口和滚动区无横向溢出均有 UI 回归
- **任务栏/窗口图标：优先使用根目录 `test.ico`，不存在时回退到 `tests/test.ico`**
- Windows AppUserModelID：`ucrawl.universalcrawlerpro.test`

### 测试图标 [test.ico](../../test.ico)

**多帧标准 ICO**（BMP 转换后用 Pillow 重存）：

- 7 帧：16/24/32/48/64/128/256 × 32-bit
- 任务栏、窗口标题、所有子窗口统一使用
- Windows 任务栏 AppUserModelID 区分（避免与主程序混用）

### 配置中心契约测试

配置中心相关改动至少覆盖以下文件：

- `tests/unit/app/config/test_settings.py`：配置段默认值、类型收敛、枚举校验、重载持久化。
- `tests/unit/app/services/test_frontend_state_service.py`：`settings_snapshot()` 快照形状、`update_setting` 热加载、`max_retries=0` 等边界。
- `tests/unit/app/ui/test_main_window.py`：GUI 设置变更进入统一前端动作，并刷新 `settings_snapshot` / `download_options` / `app_status`；顶部主题按钮必须同步设置页 Light/Dark 控件；主题快速切换必须 latest-state-wins，不能冻结 `window_root`，也不能触发完整前端快照重绘。
- `tests/contract/frontend/test_settings.py`：PyQt/WebUI 设置控件、平台数量单位、MissAV 自定义代理、目录选择、主题热加载与 TopBar 设置契约。
- `tests/contract/frontend/test_i18n_logs.py`：GUI/WebUI 语言切换、日志动态本地化和详情字段契约。
- `tests/contract/frontend/test_shell.py`、`tests/contract/frontend/test_task_pages.py`、`tests/contract/frontend/test_static.py`：分别覆盖壳层与通用控件、四态列表、Web 静态责任边界。
- `tests/contract/web/test_fastapi_endpoints.py`：`create_app()` 直连启动路径必须暴露 `/api/frontend/state` 和 `/api/frontend/delta`，避免与组合式 `rest_router` 漂移。
- `tests/e2e/web/test_browser_journeys.py`：WebUI 静态资源必须使用版本化 CSS/JS，并验证移动端设置页无全局横向溢出、Web 顶栏启动数量使用平台 `count_config_key`、主题按钮可同步外观页主题控件。

### Web 浏览器测试 [test_browser_journeys.py](../../tests/e2e/web/test_browser_journeys.py)

用 Playwright 真实浏览器测试 web UI：

- StaticAssetsTests（HTML/CSS/JS 静态结构，不需 Playwright）
- WebSocketMessageTypesTests（WS 消息类型一致性）
- WebUIBrowserTests（15+ 浏览器交互：主题切换、弹窗、键盘、删除等）
- WebUIAccessibilityTests（按钮可读性、html lang、viewport）
- WebDesignGuidelinesTests（focus 样式、hover、disabled、错误日志）

`test_browser_journeys.py` 保留静态测试和唯一 `WebUIBrowserTests` 聚合类。浏览器交互按职责位于 `tests/support/browser_cases/`，共享 uvicorn/Chromium 生命周期位于 `tests/support/browser_runtime.py`。case 模块不得继承 `TestCase` 或以 `test_` 命名，避免重复收集和重复启动浏览器。

**依赖**：
- `pip install playwright`
- `playwright install chromium`

**启动方式**：用 [web_test_app.py](../../tests/support/web_test_app.py) 作为 uvicorn shim 暴露 `app`。

#### 浏览器 E2E 等待与性能约束

浏览器测试不得使用固定时长硬等来“赌页面加载完成”。尤其禁止用 `page.wait_for_timeout(3500)`、`time.sleep(3.5)` 这类无条件等待替代可观测状态。新增或修改 WebUI 用例时，优先等待稳定的页面条件：

- 页面壳层：`#app-shell`
- 前端核心函数：`window.renderAll`、`window.switchPage`
- 具体控件：例如 `#topBar`、`#rightPanel`、`#sourceSelect`
- 异步初始状态：只有当用例会预置或覆盖前端状态时，才额外等待 `window.__ucrawlFrontendStateSettled === true`
- 页面特定数据：例如平台下拉框需要等待 `#sourceSelect.options.length > 0`，不要塞进通用导航 helper

除非测试目标本身就是防抖、节流或定时器窗口，否则不得用 `page.wait_for_timeout(...)` 等固定超时等待 UI 稳定；弹窗、按钮状态、列表刷新、语言切换和主题切换都应等待对应 DOM 状态或前端状态标记。

测试服务的 `stdout` / `stderr` 也不能挂在无人消费的 `subprocess.PIPE` 上。长时间运行的浏览器套件会持续输出服务日志，管道填满后可能把 uvicorn 或测试进程拖住；应重定向到临时文件或显式消费输出。

2026-07 本地基线：用户原先观测旧浏览器聚合入口约需 7 到 8 分钟。移除 3.5 秒硬等并修正测试服务输出后，历史实测（当前入口已迁移）：

```bash
python -X faulthandler -m pytest tests/e2e -q
# 2026-07-07 基线：97 passed in 247.64s (0:04:07)
# 2026-07 早前热运行：97 passed in 185.66s (外部秒表约 187.9s)
# 2026-07-11 职责拆分后：136 passed in 33.40s
```

即浏览器 E2E 从约 420-480 秒降至约 188-248 秒，节省约 172-292 秒，约快 41%-61%。该数字受机器负载、Playwright 首次启动状态和浏览器缓存影响；后续变更若显著回退，应优先检查是否重新引入了固定等待、整页重绘或服务输出阻塞。

2026-07-11 全量基线：`2455 passed, 3 skipped, 7 warnings in 252.44s (0:04:12)`；完整收集 `2458` 个测试。两个大型前端测试入口拆分后，原 279 个测试方法全部保留，另增加 8 个架构与打包守卫。

## 目录套件与领域示例

### CLI / SDK（`unit` + `contract`）

适合对象：

- `shared/selection_base.py` / `shared/pipe_selection.py` / `shared/interactive_selection.py`
- `shared/runtime_options.py` / `shared/cli_runner_runtime.py` / `shared/sdk_runtime.py`
- `cli/__init__.py` 的历史模块路径兼容别名（别名必须直接指向上述 canonical 模块）
- `entry/dispatcher.py` / `entry/web_entry.py`
- `app/core/download_manager.py`（纯逻辑）
- 配置与文件名工具

特征：

- 无真实网络
- 无真实站点
- 只验证输入输出与异常行为

测试文件：

- `tests/contract/entry/test_cli_entry.py`
- `tests/unit/cli/test_main.py`
- `tests/unit/cli/test_selection.py`
- `tests/unit/cli/test_pipe.py`
- `tests/unit/cli/test_defaults.py`
- `tests/unit/cli/test_sdk.py`
- `tests/unit/cli/test_runner.py`

### Web / API（`contract` + `integration`）

适合对象：

- FastAPI 全部 REST 端点（`/api/search` / `/api/download` / `/api/scan` 等）
- `WebController` 与 `ApplicationController` 协作
- 跨层调用链路（CLI → handler → SDK → Runner → spider）
- 多端点协作（scan → dir/change → state）

特征：

- TestClient 完整 HTTP 流程
- mock 浏览器 / 下载器
- 验证跨模块编排是否正确

测试文件：

- `tests/contract/web/test_fastapi_endpoints.py`（20+ 端点）
- `tests/contract/entry/test_web_entry.py`
- `tests/contract/cross_interface/test_cli_sdk_api.py`（CLI/SDK/API 三层契约）

### 应用流程（`integration`）

适合对象：

- 完整 scan → dir/change → search → state 链路
- SDK 资源管理（with / close / QApplication）
- 配置持久化 PUT/GET 循环

特征：

- 用 mock 隔离外部依赖（爬虫、网络）
- 模拟完整用户操作流程

测试文件：

- `tests/integration/entry/test_application_flows.py`

### 打包验证（`release`）

适合对象：

- `packaging/portable.spec`（hiddenimports / datas / icon / runtime_hooks）
- `packaging/build_portable.py`（REQUIRED_FILES / kill_locking_processes）
- `packaging/runtime_hook.py`（NullStream / AppUserModelID / PLAYWRIGHT_BROWSERS_PATH）
- `pyproject.toml`（entry_points）
- 资源文件存在性（favicon.ico / Web.ico / ffmpeg.exe / N_m3u8DL-RE.exe）

特征：

- 不真跑 PyInstaller（太慢）
- exec spec 验证模块级变量
- 静态分析 spec 关键字段
- 校验打包文档与 `project_meta.py` / `runtime_paths.py` 的联动口径
- 拦截 `.dbg/`、`debug-point`、`127.0.0.1:7777/event` 这类临时探针残留

测试文件：

- `tests/release/packaging/test_assets.py`

### 桌面界面（`unit` + `contract`）

适合对象：

- Qt 主窗口、控制器、队列面板、日志中心、配置中心、媒体预览和宿主适配层。
- 自绘标题栏、主题切换、侧栏/顶栏/状态栏 shell、窗口生命周期和桌面弹窗。
- `entry/dispatcher.py` 的 TUI 菜单 + Qt 弹窗、`entry/web_entry.py` 的端口冲突弹窗。
- `_load_app_icon`、`is_tty` / `is_gui_available` 等桌面环境检测。

特征：

- PyQt6 是依赖项（不满足时相关测试会优雅降级）
- 使用 setUpClass 共享 QApplication 实例
- 不实际 exec 弹窗（避免阻塞）
- mock input() / sys.stdin 测试 TUI

桌面组件行为放在 `tests/unit/app/ui/` 并镜像组件、页面、样式或 viewmodel 命名空间；GUI/WebUI 共享可观察承诺放在 `tests/contract/frontend/`。新增回归不依赖文件名前缀命中，目录职责才是分类依据。

### 管道测试（`unit` + `integration`）

适合对象：

- `shared/pipe_selection.py` 的 PipeSelection（stdin 读 JSON）
- `shared/pipe_selection.py` 的 PipeOutput（stdout 写 JSON）
- 多轮预加载（合集场景）

特征：

- 用 io.StringIO 替换 stdin/stdout
- 不真爬虫，只测输入输出格式
- 验证各种 JSON 格式（list / dict with indices / items）

测试文件：

- `tests/unit/cli/test_pipe.py`
- `tests/integration/shared/test_pipe_selection.py`

### 组件协作（`integration`）

适合对象：

- `ApplicationController`
- `BiliAPI.get_play_url()` 回退
- `KuaishouSpider._run_capture_pipeline()`
- `MissAVSpider._scan_pages()`

特征：

- mock 浏览器 page/context
- mock 下载器和 UI
- 验证跨模块编排是否正确

### 浏览器 E2E（`e2e`）

适合对象：

- `app/web/static/index.html` 静态资源（HTML/CSS/JS 结构）
- WebSocket 消息类型一致性（前后端契约）
- 真实 Chromium 浏览器交互（主题切换、弹窗、键盘、删除）
- 可访问性（按钮可读、html lang、viewport）
- 设计指南（focus 样式、hover、disabled、错误日志）

特征：

- @skipUnless(playwright installed)，未安装时优雅降级
- 用 uvicorn + `tests.support.web_test_app:app` 在后台启动
- sync_playwright + headless Chromium
- 5s 默认超时（避免 CI 卡死）
- 不真爬虫（断网或失败时优雅降级）

测试文件：

- `tests/e2e/web/test_browser_journeys.py`（浏览器交互、可访问性与设计规范回归）
- `tests/support/web_test_app.py`（uvicorn shim）

### 架构适应度（architecture）

适合对象：

- 依赖方向、Spider 协议、跨层引用边界和文件大小约束。
- `tests/architecture/test_*.py` 下的结构性规则。

特征：

- 不依赖真实网络或 GUI。
- 用轻量静态检查兜住“越层调用”“历史大文件继续膨胀”等回归。

### 性能预算（`performance`）

适合对象：

- `tests/performance/test_runtime_budgets.py` 中显式运行的轻量性能基准。
- 前端刷新、日志查询、列表分页、快照生成这类容易被同步重绘拖慢的路径。

特征：

- 默认作为保障层类别出现，但不替代真实交互验证。
- 结果受机器负载影响，发现明显回退时先排查固定等待、全量快照、UI 线程阻塞和未合并的高频事件。

### 人工验证

仍建议人工验证以下场景：

- 真实浏览器登录
- 外部工具 `ffmpeg` 与 `N_m3u8DL-RE` 的环境可用性
- UI 交互体验与主题样式
- 打包后双击 EXE 的真实行为

## 运行方式

### 推荐：统一测试启动器（三模）

```bash
# GUI 模式（默认）
python tests/launcher.py

# CLI 模式（指定目录套件）
python tests/launcher.py --category unit
python tests/launcher.py --category contract
python tests/launcher.py --category e2e
python tests/launcher.py --category all

# TUI 模式（无 GUI 环境）
python tests/launcher.py --tui

# 列出所有套件
python tests/launcher.py --list
```

### 一键全量（CLI）

```bash
python tests/run_all_tests.py
```

### 按套件（CLI）

```bash
python tests/run_all_tests.py --category unit
python tests/run_all_tests.py --category integration
python tests/run_all_tests.py --category contract
python tests/run_all_tests.py --category e2e
python tests/run_all_tests.py --category architecture
python tests/run_all_tests.py --category performance
python tests/run_all_tests.py --category release
python tests/run_all_tests.py --category testkit
```

### 单个文件

```bash
python -m pytest tests/contract/web/test_fastapi_endpoints.py -v
```

### 详细输出

```bash
python -m pytest tests/ -v
```

### 收集全部失败

```bash
python -m pytest tests/
```

`pytest` 默认不会在首个失败后停止；只有显式传入 `-x` / `--exitfirst` 时才会提前退出。

## 执行约定

- 统一使用 `pytest` 作为运行入口
- 历史测试主体仍可保持 `unittest.TestCase` 风格
- 新测试按 `tests/NAMING.md` 选择套件并镜像生产命名空间；内置套件由目录自动发现
- pytest marker 只表达运行约束，且必须在 `pyproject.toml` 注册
- 禁止为内置套件增加精确文件、业务前缀 glob 或 include/exclude 白名单

## 推荐 mock 边界

- **Spider**：mock `page`、`context`、`response`、`request`
- **ApplicationController**：mock `window`、`dl_manager`、`file_service`
- **DownloadWorker**：优先真实临时目录，少 mock 文件系统纯逻辑
- **BiliAPI**：mock `requests.Session.get()` 返回值
- **DownloadManager**：mock `add_task` / `stop_all` 避免真下载
- **QApplication**：setUpClass 共享单例 + `QT_QPA_PLATFORM=offscreen`
- **spider 实际搜索/下载**：用 mock 完全替换，避免线程崩溃

## 课程作业映射

针对"软件测试技术"课程作业的常见要求：

- **黑盒测试**：重点覆盖 CLI/API 端点、SDK 函数的输入输出、配置回读、文件服务行为
- **白盒测试**：重点覆盖 `parser.py`、`task_builder.py`、`DownloadWorker`、`runtime_paths.py`、打包 spec 内部结构
- **批量运行**：`tests/run_all_tests.py` 跨类别执行，便于展示
- **接口测试**：将 CLI/SDK/REST API 三层视为对外接口，验证契约一致性
- **UI 测试**：PyQt6 桌面应用不采用 Selenium，优先使用组件级测试 + 控制器级测试
- **管道测试**：stdin/stdout 数据流视为外部接口，验证格式一致性
- **打包测试**：将 PyInstaller 配置视为内部接口，验证完整性

## 高价值补测点

优先级较高的区域：

- B 站 API 回退与多阶段任务装配
- 快手实时流捕获与焦点匹配
- MissAV 双轮扫描、优先级选择，以及挑战期间无活动 CDP、挑战后接管、二次导航前断开再接管的浏览器状态机
- 下载完成后的扩展名修正和路径冲突处理
- controller 对爬虫与下载器之间的衔接
- 启动入口、运行环境路径与打包相关路径解析
- 插件配置控件与运行参数持久化行为
- 下载调度线程的派发、槽位释放与失败回传
- **CLI/SDK/API 三层契约一致性**（新增）
- **多入口 dispatcher 模式选择**（新增）
- **端口冲突真实 bind 验证**（新增）
- **AppUserModelID 任务栏图标**（新增）

## 新增测试时的文档要求

普通新增测试只需遵守目录与命名契约，无需改 catalog 或文档。改变套件职责、运行策略、公共命令或稳定路径时，请增量同步：

- `tests/README.md`
- `tests/NAMING.md`
- `tests/AGENTS.md`
- 根目录 `README.md`
- 本文档

## 新增脚本接入方式

项目内置测试直接放入八个规范根目录，不需要注册：

```text
tests/<suite>/<production namespace>/test_<observable responsibility>.py
```

只有第三方或运行时插件分类可使用显式目录、文件和 glob：

```python
from tests.support.catalog import (
    register_category,
    register_plugin_directory,
)

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

不能用插件 API 修改 `unit`、`integration`、`contract`、`e2e`、`architecture`、`performance`、`release` 或 `testkit` 的内置归属。

## 历史测试发现的生产 Bug

历史全量测试曾发现并修复 3 个生产 bug，作为“测试能主动发现生产风险”的案例保留：

1. **RuleSelection.__init__ 中 `self.select = select` 覆盖了 `def select()` 方法**
   - 修复：用 `self._select_rule = select`
   - 发现于：`tests/unit/cli/test_selection.py`

2. **cli/main.py 顶部 `sys.path.insert(0, ROOT)` 不去重**
   - 修复：加 `if _PROJECT_ROOT not in sys.path:` 去重检查
   - 发现于：`tests/unit/cli/test_main.py`

3. **SDK `_resolve_selection` 中 `isinstance(selection, SelectionStrategy)` 在 Protocol 没 @runtime_checkable 时崩 TypeError**
   - 修复：加 `is_selection_strategy()` duck-type check 函数
   - 发现于：`tests/contract/cross_interface/test_cli_sdk_api.py`

这些发现说明：测试不仅验证代码正确性，还能**主动发现潜在生产 bug**，这就是"全量测试"的价值。
