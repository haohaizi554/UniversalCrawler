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

## 测试基础设施（v2 升级）

### 测试注册表 [test_registry.py](../../tests/test_registry.py)

集中管理所有测试类别与文件，运行时可注册新类别：

- `TestCategory` dataclass：id/name/description/files/icon_color/icon_letter/priority/requires_network/requires_gui/enabled
- 当前预置 13 个类别（all/cli_sdk/web_api/app_flows/desktop_ui/browser_e2e/pipeline/packaging/core_services/architecture/benchmark/suite_infra/misc）
- 截至 2026-07-08，本地注册表显示 13 个启用类别、131 个测试文件；`misc` 当前为 0，用于收纳尚未命中规则的新脚本。
- `register_category()` 运行时注册新类别
- `register_category_rule()` 用规则自动归类新脚本
- `register_test_files()` 便于把后续测试脚本加入已有套件
- `get_enabled_categories()` 按 priority 排序
- `get_resolved_files(cat_id)` 解析 `all` 为所有其他类别
- `auto_discover_tests()` 自动发现尚未命中规则的新测试脚本

### 测试运行引擎 [test_runner.py](../../tests/test_runner.py)

封装 pytest 调用与结果解析：

- `TestResult` dataclass（passed/failed/skipped/errors/duration/failed_tests）
- `run_category()` 逐文件运行 pytest，解析输出
- `run_categories()` 顺序运行多个类别
- `format_summary()` 多行汇总文本
- 进度回调（GUI 进度条用）

### 统一测试入口 [test_launcher.py](../../tests/test_launcher.py)

**三模自适应启动器**（GUI / TUI / CLI）：

```bash
# 1. 弹 Qt 菜单（默认）
python tests/test_launcher.py

# 2. 命令行直接跑某个类别
python tests/test_launcher.py --category cli_sdk
python tests/test_launcher.py --category all
python tests/test_launcher.py --category browser_e2e

# 3. TUI 菜单（无 GUI 环境）
python tests/test_launcher.py --tui

# 4. 列出所有类别
python tests/test_launcher.py --list

# 5. 强制 GUI
python tests/test_launcher.py --gui
```

特性：
- 左侧分组套件列表 + 右侧详情/统计/日志的双栏仪表盘
- 实时运行面板（统计卡片 + 进度条 + QTextEdit 滚动日志）
- F5 运行 / Ctrl+1 全部 / Ctrl+R 推荐 / Esc 清空
- failfast / verbose 复选框
- **任务栏/窗口图标：优先使用根目录 `test.ico`，不存在时回退到 `tests/test.ico`**
- Windows AppUserModelID：`ucrawl.universalcrawlerpro.test`

### 测试图标 [test.ico](../../test.ico)

**多帧标准 ICO**（BMP 转换后用 Pillow 重存）：

- 7 帧：16/24/32/48/64/128/256 × 32-bit
- 任务栏、窗口标题、所有子窗口统一使用
- Windows 任务栏 AppUserModelID 区分（避免与主程序混用）

### 配置中心契约测试

配置中心相关改动至少覆盖以下文件：

- `tests/test_config_settings.py`：配置段默认值、类型收敛、枚举校验、重载持久化。
- `tests/test_frontend_state_service.py`：`settings_snapshot()` 快照形状、`update_setting` 热加载、`max_retries=0` 等边界。
- `tests/test_main_window.py`：GUI 设置变更进入统一前端动作，并刷新 `settings_snapshot` / `download_options` / `app_status`；顶部主题按钮必须同步设置页 Light/Dark 控件；主题快速切换必须 latest-state-wins，不能冻结 `window_root`，也不能触发完整前端快照重绘。
- `tests/test_unified_frontend_contract.py`：PyQt 设置页控件、WebUI 设置控件、GUI/WebUI 文案与动作契约；平台设置必须覆盖 `max_pages/pages`、`max_items/videos`、MissAV 独立自定义代理输入；全局 GUI QSS 需要用 Qt 实际应用一次，防止样式解析失败导致主题热加载或下拉框高亮失效。
- `tests/test_unified_frontend_contract.py` 还必须覆盖 GUI 非模态目录选择器、设置页重建后不留下隐藏 top-level 控件、主题热加载只给真实顶层窗口应用根样式、TopBar 主题 busy 按钮保持可点击，以及 Web 自定义下拉框深浅主题文字可读性。
- `tests/test_fastapi_endpoints.py`：`create_app()` 直连启动路径必须暴露 `/api/frontend/state` 和 `/api/frontend/delta`，避免与组合式 `rest_router` 漂移。
- `tests/test_web_browser.py`：WebUI 静态资源必须使用版本化 CSS/JS，并验证移动端设置页无全局横向溢出、Web 顶栏启动数量使用平台 `count_config_key`、主题按钮可同步外观页主题控件。

### Web 浏览器测试 [test_web_browser.py](../../tests/test_web_browser.py)

用 Playwright 真实浏览器测试 web UI：

- StaticAssetsTests（HTML/CSS/JS 静态结构，不需 Playwright）
- WebSocketMessageTypesTests（WS 消息类型一致性）
- WebUIBrowserTests（15+ 浏览器交互：主题切换、弹窗、键盘、删除等）
- WebUIAccessibilityTests（按钮可读性、html lang、viewport）
- WebDesignGuidelinesTests（focus 样式、hover、disabled、错误日志）

**依赖**：
- `pip install playwright`
- `playwright install chromium`

**启动方式**：用 [web_test_app.py](../../tests/web_test_app.py) 作为 uvicorn shim 暴露 `app`。

#### 浏览器 E2E 等待与性能约束

浏览器测试不得使用固定时长硬等来“赌页面加载完成”。尤其禁止用 `page.wait_for_timeout(3500)`、`time.sleep(3.5)` 这类无条件等待替代可观测状态。新增或修改 WebUI 用例时，优先等待稳定的页面条件：

- 页面壳层：`#app-shell`
- 前端核心函数：`window.renderAll`、`window.switchPage`
- 具体控件：例如 `#topBar`、`#rightPanel`、`#sourceSelect`
- 异步初始状态：只有当用例会预置或覆盖前端状态时，才额外等待 `window.__ucrawlFrontendStateSettled === true`
- 页面特定数据：例如平台下拉框需要等待 `#sourceSelect.options.length > 0`，不要塞进通用导航 helper

除非测试目标本身就是防抖、节流或定时器窗口，否则不得用 `page.wait_for_timeout(...)` 等固定超时等待 UI 稳定；弹窗、按钮状态、列表刷新、语言切换和主题切换都应等待对应 DOM 状态或前端状态标记。

测试服务的 `stdout` / `stderr` 也不能挂在无人消费的 `subprocess.PIPE` 上。长时间运行的浏览器套件会持续输出服务日志，管道填满后可能把 uvicorn 或测试进程拖住；应重定向到临时文件或显式消费输出。

2026-07 本地基线：用户原先观测 `tests/test_web_browser.py` 约需 7 到 8 分钟。移除 3.5 秒硬等并修正测试服务输出后，历史实测：

```bash
python -m pytest tests/test_web_browser.py -q
# 2026-07-07 基线：97 passed in 247.64s (0:04:07)
# 2026-07 早前热运行：97 passed in 185.66s (外部秒表约 187.9s)
```

即浏览器 E2E 从约 420-480 秒降至约 188-248 秒，节省约 172-292 秒，约快 41%-61%。该数字受机器负载、Playwright 首次启动状态和浏览器缓存影响；后续变更若显著回退，应优先检查是否重新引入了固定等待、整页重绘或服务输出阻塞。

## 测试分层

### CLI / SDK（cli_sdk）

适合对象：

- `cli/selection_base.py` / `cli/pipe.py` / `cli/interactive.py`
- `cli/defaults.py` / `cli/runner.py` / `cli/sdk.py`
- `entry/dispatcher.py` / `entry/web_entry.py`
- `app/core/download_manager.py`（纯逻辑）
- 配置与文件名工具

特征：

- 无真实网络
- 无真实站点
- 只验证输入输出与异常行为

测试文件：

- `tests/test_cli_entry.py`
- `tests/test_cli_main.py`
- `tests/test_cli_selection.py`
- `tests/test_cli_pipe.py`
- `tests/test_cli_defaults.py`
- `tests/test_cli_sdk.py`
- `tests/test_cli_runner.py`

### Web / API（web_api）

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

- `tests/test_fastapi_endpoints.py`（20+ 端点）
- `tests/test_web_entry.py`
- `tests/test_contract.py`（CLI/SDK/API 三层契约）

### 应用流程（app_flows）

适合对象：

- 完整 scan → dir/change → search → state 链路
- SDK 资源管理（with / close / QApplication）
- 配置持久化 PUT/GET 循环

特征：

- 用 mock 隔离外部依赖（爬虫、网络）
- 模拟完整用户操作流程

测试文件：

- `tests/test_e2e.py`

### 打包验证（packaging）

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

- `tests/test_packaging.py`

### 桌面界面（desktop_ui）

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

当前注册表按规则收纳 21 个文件；新增桌面 UI 回归不要只挂到 `tests/test_ui_dialogs.py`，应让文件名命中 `test_main_window.py`、`test_*_panel.py`、`test_gui_*.py`、`test_desktop_*.py`、`test_ui_*.py` 等既有规则。

### 管道测试（pipeline）

适合对象：

- `cli/pipe.py` 的 PipeSelection（stdin 读 JSON）
- `cli/pipe.py` 的 PipeOutput（stdout 写 JSON）
- 多轮预加载（合集场景）

特征：

- 用 io.StringIO 替换 stdin/stdout
- 不真爬虫，只测输入输出格式
- 验证各种 JSON 格式（list / dict with indices / items）

测试文件：

- `tests/test_pipeline.py`

### 半集成测试

适合对象：

- `ApplicationController`
- `BiliAPI.get_play_url()` 回退
- `KuaishouSpider._run_capture_pipeline()`
- `MissAVSpider._scan_pages()`

特征：

- mock 浏览器 page/context
- mock 下载器和 UI
- 验证跨模块编排是否正确

### 浏览器 E2E（browser_e2e）

适合对象：

- `app/web/static/index.html` 静态资源（HTML/CSS/JS 结构）
- WebSocket 消息类型一致性（前后端契约）
- 真实 Chromium 浏览器交互（主题切换、弹窗、键盘、删除）
- 可访问性（按钮可读、html lang、viewport）
- 设计指南（focus 样式、hover、disabled、错误日志）

特征：

- @skipUnless(playwright installed)，未安装时优雅降级
- 用 uvicorn + tests.web_test_app:app 在后台启动
- sync_playwright + headless Chromium
- 5s 默认超时（避免 CI 卡死）
- 不真爬虫（断网或失败时优雅降级）

测试文件：

- `tests/test_web_browser.py`（浏览器交互、可访问性与设计规范回归）
- `tests/web_test_app.py`（uvicorn shim）

### 架构适应度（architecture）

适合对象：

- 依赖方向、Spider 协议、跨层引用边界和文件大小约束。
- `tests/architecture/test_*.py` 下的结构性规则。

特征：

- 不依赖真实网络或 GUI。
- 用轻量静态检查兜住“越层调用”“历史大文件继续膨胀”等回归。

### 性能基准（benchmark）

适合对象：

- `tests/test_performance_benchmarks.py` 中显式运行的轻量性能基准。
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
python tests/test_launcher.py

# CLI 模式（指定类别）
python tests/test_launcher.py --category cli_sdk
python tests/test_launcher.py --category all
python tests/test_launcher.py --category browser_e2e

# TUI 模式（无 GUI 环境）
python tests/test_launcher.py --tui

# 列出所有类别
python tests/test_launcher.py --list
```

### 一键全量（CLI）

```bash
python tests/run_all_tests.py
```

### 按类别（CLI）

```bash
python tests/run_all_tests.py --category cli_sdk       # CLI / SDK
python tests/run_all_tests.py --category web_api       # Web / API
python tests/run_all_tests.py --category app_flows     # 应用流程
python tests/run_all_tests.py --category desktop_ui    # 桌面界面
python tests/run_all_tests.py --category packaging     # 打包发布
python tests/run_all_tests.py --category pipeline      # 数据管道
python tests/run_all_tests.py --category browser_e2e   # 浏览器 E2E
python tests/run_all_tests.py --category core_services # 核心服务
python tests/run_all_tests.py --category architecture  # 架构适应度
python tests/run_all_tests.py --category benchmark     # 性能基准
python tests/run_all_tests.py --category suite_infra   # 测试套件
```

### 单个文件

```bash
python -m pytest tests/test_fastapi_endpoints.py -v
```

### 详细输出

```bash
python -m pytest tests/ -v
```

### 不遇失败停止

```bash
python -m pytest tests/ --no-failfast
```

## 执行约定

- 统一使用 `pytest` 作为运行入口
- 历史测试主体仍可保持 `unittest.TestCase` 风格
- 新测试优先按 `tests/NAMING.md` 命名，并接入 `tests/test_registry.py` 自动分类

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
- MissAV 双轮扫描与优先级选择
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

新增测试文件或改变测试策略后，请同步更新：

- `tests/README.md`
- 根目录 `README.md`
- 本文档

## 新增脚本接入方式

优先使用 `tests/test_registry.py` 提供的接口，而不是继续维护静态文件长列表：

```python
from tests.test_registry import (
    register_category,
    register_category_rule,
    register_test_files,
)

register_category(
    id="perf",
    name="性能测试",
    description="手工定义一组测试脚本",
    files=["tests/test_perf_bench.py"],
)

register_category_rule(
    id="plugin_api",
    name="插件接口",
    description="自动纳入匹配规则的新脚本",
    include=["tests/test_plugin_*.py"],
)

register_test_files(
    "suite_infra",
    ["tests/test_new_suite_case.py"],
)
```

## 历史测试发现的生产 Bug

历史全量测试曾发现并修复 3 个生产 bug，作为“测试能主动发现生产风险”的案例保留：

1. **RuleSelection.__init__ 中 `self.select = select` 覆盖了 `def select()` 方法**
   - 修复：用 `self._select_rule = select`
   - 发现于：`tests/test_cli_selection.py`

2. **cli/main.py 顶部 `sys.path.insert(0, ROOT)` 不去重**
   - 修复：加 `if _PROJECT_ROOT not in sys.path:` 去重检查
   - 发现于：`tests/test_cli_main.py`

3. **SDK `_resolve_selection` 中 `isinstance(selection, SelectionStrategy)` 在 Protocol 没 @runtime_checkable 时崩 TypeError**
   - 修复：加 `is_selection_strategy()` duck-type check 函数
   - 发现于：`tests/test_contract.py`

这些发现说明：测试不仅验证代码正确性，还能**主动发现潜在生产 bug**，这就是"全量测试"的价值。
