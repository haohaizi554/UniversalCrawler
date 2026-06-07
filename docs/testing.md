# 测试指南

## 测试目标

本项目测试承担以下职责：

- 保护高频重构区域，避免控制流回归
- 保护高风险爬虫逻辑（登录、取流、任务装配、入队）
- 保护文件落盘与 UI 编排的关键边界
- **保护多入口一致性**（CLI / SDK / REST API / Web UI）
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
- **Web E2E**（新增）：Playwright + 真实浏览器 + 静态/可访问性/设计指南审查

## 测试基础设施（v2 升级）

### 测试注册表 [test_registry.py](../tests/test_registry.py)

集中管理所有测试类别与文件，运行时可注册新类别：

- `TestCategory` dataclass：id/name/description/files/icon_color/icon_letter/priority/requires_network/requires_gui/enabled
- 预置 9 个类别（all/unit/integration/e2e/ui/pipeline/packaging/web_browser/core）
- `register_category()` 运行时注册新类别
- `get_enabled_categories()` 按 priority 排序
- `get_resolved_files(cat_id)` 解析 `all` 为所有其他类别
- `auto_discover_tests()` 自动发现未注册文件

### 测试运行引擎 [test_runner.py](../tests/test_runner.py)

封装 pytest 调用与结果解析：

- `TestResult` dataclass（passed/failed/skipped/errors/duration/failed_tests）
- `run_category()` 逐文件运行 pytest，解析输出
- `run_categories()` 顺序运行多个类别
- `format_summary()` 多行汇总文本
- 进度回调（GUI 进度条用）

### 统一测试入口 [test_launcher.py](../tests/test_launcher.py)

**三模自适应启动器**（GUI / TUI / CLI）：

```bash
# 1. 弹 Qt 菜单（默认）
python tests/test_launcher.py

# 2. 命令行直接跑某个类别
python tests/test_launcher.py --category unit
python tests/test_launcher.py --category all
python tests/test_launcher.py --category web_browser

# 3. TUI 菜单（无 GUI 环境）
python tests/test_launcher.py --tui

# 4. 列出所有类别
python tests/test_launcher.py --list

# 5. 强制 GUI
python tests/test_launcher.py --gui
```

特性：
- 卡片选择（左侧 6px 边条 + 字母 + 名称 + 描述 + 元信息）
- 实时运行面板（QTextEdit 滚动日志 + 进度条）
- F5 运行 / Ctrl+A 全选 / Esc 全不选 / "推荐" 快捷按钮
- failfast / verbose 复选框
- **任务栏/窗口图标：tests/test.ico（多帧标准 ICO）**
- Windows AppUserModelID：`ucrawl.universalcrawlerpro.test`

### 测试图标 [test.ico](../tests/test.ico)

**多帧标准 ICO**（BMP 转换后用 Pillow 重存）：

- 7 帧：16/24/32/48/64/128/256 × 32-bit
- 任务栏、窗口标题、所有子窗口统一使用
- Windows 任务栏 AppUserModelID 区分（避免与主程序混用）

### Web 浏览器测试 [test_web_browser.py](../tests/test_web_browser.py)

用 Playwright 真实浏览器测试 web UI：

- StaticAssetsTests（HTML/CSS/JS 静态结构，不需 Playwright）
- WebSocketMessageTypesTests（WS 消息类型一致性）
- WebUIBrowserTests（15+ 浏览器交互：主题切换、弹窗、键盘、删除等）
- WebUIAccessibilityTests（按钮可读性、html lang、viewport）
- WebDesignGuidelinesTests（focus 样式、hover、disabled、错误日志）

**依赖**：
- `pip install playwright`
- `playwright install chromium`

**启动方式**：用 [web_test_app.py](../tests/web_test_app.py) 作为 uvicorn shim 暴露 `app`。

## 测试分层

### 单元测试（unit）

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

### 集成测试（integration）

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

### 端到端测试（e2e）

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

测试文件：

- `tests/test_packaging.py`

### UI 弹窗测试（ui）

适合对象：

- `entry/dispatcher.py` 的 TUI 菜单 + Qt 弹窗
- `entry/web_entry.py` 的端口冲突弹窗
- `_load_app_icon` 行为
- `is_tty` / `is_gui_available` 环境检测

特征：

- PyQt6 是依赖项（不满足时 `@unittest.skipUnless` 优雅降级）
- 使用 setUpClass 共享 QApplication 实例
- 不实际 exec 弹窗（避免阻塞）
- mock input() / sys.stdin 测试 TUI

测试文件：

- `tests/test_ui_dialogs.py`

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

### Web 浏览器测试（web_browser）

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

- `tests/test_web_browser.py`（5 个测试类，30+ 用例）
- `tests/web_test_app.py`（uvicorn shim）

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
python tests/test_launcher.py --category unit
python tests/test_launcher.py --category all
python tests/test_launcher.py --category web_browser

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
python tests/run_all_tests.py --category unit       # 单元
python tests/run_all_tests.py --category integration # 集成
python tests/run_all_tests.py --category e2e         # 端到端
python tests/run_all_tests.py --category packaging   # 打包
python tests/run_all_tests.py --category ui          # UI
python tests/run_all_tests.py --category pipeline    # 管道
python tests/run_all_tests.py --category web_browser # Web 浏览器
python tests/run_all_tests.py --category core        # 核心组件
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

## 修复的生产 Bug

通过本次全量测试，发现并修复了 3 个生产 bug：

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
