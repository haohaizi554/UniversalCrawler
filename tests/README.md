# 测试目录说明

本目录覆盖项目的所有风险路径，从单元到端到端、UI 弹窗、Web 浏览器真实交互全套测试。

## 行业测试标准参考

本项目测试遵循以下行业规范：

- **测试金字塔**（Mike Cohn）：底层单元测试最多，往上集成、E2E 逐渐减少
- **FIRST 原则**：Fast、Independent、Repeatable、Self-validating、Timely
- **AAA 模式**：Arrange（准备）/ Act（执行）/ Assert（断言）
- **测试隔离**：每个测试独立 setUp/tearDown，主要以 `unittest.TestCase` 风格编写，由 `pytest` 统一执行
- **黑盒 vs 白盒**：黑盒只看 API 行为，白盒 mock 内部实现
- **契约测试**：验证多个入口（CLI/SDK/API）的输出一致
- **Pipeline 测试**：验证 stdin/stdout 数据流转换
- **Web E2E**：Playwright + 真实浏览器（参考 Vercel Web Interface Guidelines）

## 测试类别

| 类别 | 文件数 | 用例数 | 说明 |
|------|------|------|------|
| **all** | 34 | 全部 | 当前 `tests/` 目录下所有可执行测试脚本 |
| cli_sdk | 7 | 130+ | CLI、SDK、选择策略、默认值与 Runner |
| web_api | 3 | 150+ | FastAPI 端点、Web 入口、多入口契约 |
| app_flows | 3 | 30+ | 端到端流程、入口调度、跨模块流程 |
| desktop_ui | 4 | 40+ | Qt 主窗口、控制器、队列面板、对话框 |
| browser_e2e | 1 | 30+ | Playwright 真实浏览器前端交互回归 |
| pipeline | 1 | 30+ | stdin/stdout JSON 管道与多轮预加载 |
| packaging | 1 | 40+ | spec、runtime hook、资源与发布入口 |
| core_services | 13 | 100+ | 下载器、文件服务、配置、日志、核心服务 |
| suite_infra | 1 | 30+ | 测试入口、插件接入、测试套件自身行为 |
| misc | 自动 | 自动 | 未命中规则的新测试脚本，便于后续补分类 |

**总用例数：数百个，持续增长**

## 核心测试基础设施（v2 升级）

### 1. 测试注册表 [test_registry.py](test_registry.py)

集中管理所有测试类别与文件：

- `TestCategory` dataclass（id/name/description/files/icon_color/icon_letter/priority/requires_network/requires_gui/enabled）
- 预置 11 个类别（all/cli_sdk/web_api/app_flows/desktop_ui/browser_e2e/pipeline/packaging/core_services/suite_infra/misc）
- `register_category()` 运行时注册新类别
- `register_category_rule()` 用 glob 规则自动归类
- `register_test_files()` 便于后续把测试脚本接入现有套件
- `get_enabled_categories()` 按 priority 排序
- `get_resolved_files(cat_id)` 解析 `all` 为所有其他类别
- `auto_discover_tests()` 自动发现未命中规则的新测试脚本

### 2. 测试运行引擎 [test_runner.py](test_runner.py)

封装 pytest 调用与结果解析：

- `TestResult` dataclass（passed/failed/skipped/errors/duration/failed_tests）
- `run_category()` 逐文件运行 pytest，解析输出
- `run_categories()` 顺序运行多个类别
- `format_summary()` 多行汇总文本
- 进度回调（GUI 进度条用）

### 3. 统一测试入口 [test_launcher.py](test_launcher.py)

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
- 左侧分组套件列表 + 右侧统计/详情/控制台的现代双栏布局
- 实时运行面板（统计卡片 + 进度条 + QTextEdit 滚动日志）
- F5 运行 / Ctrl+1 全部 / Ctrl+R 推荐 / Esc 清空
- failfast / verbose 复选框
- **任务栏/窗口图标：优先使用根目录 `test.ico`，不存在时回退到 `tests/test.ico`**
- Windows AppUserModelID：`ucrawl.universalcrawlerpro.test`

### 4. 测试图标 [test.ico](../test.ico)

**多帧标准 ICO**（BMP 转换后用 Pillow 重存）：

- 7 帧：16/24/32/48/64/128/256 × 32-bit
- 任务栏、窗口标题、所有子窗口统一使用
- Windows 任务栏 AppUserModelID 区分（避免与主程序混用）

### 5. CLI 兼容入口 [run_all_tests.py](run_all_tests.py)

旧的 CLI 入口，重构后从 `test_registry` 读取类别：

```bash
python tests/run_all_tests.py                         # 全量
python tests/run_all_tests.py --category cli_sdk      # 按类别
python tests/run_all_tests.py --list                  # 列出
python tests/run_all_tests.py --verbose               # 详细
python tests/run_all_tests.py --no-failfast           # 不遇失败停止
```

## 测试文件总览

命名与自动分类规则见 [NAMING.md](NAMING.md)。

### CLI / SDK / 选择策略（cli_sdk 类别）
- [test_cli_entry.py](test_cli_entry.py) - cli_entry 透传
- [test_cli_main.py](test_cli_main.py) - argparse 解析 + 平台别名
- [test_cli_selection.py](test_cli_selection.py) - RuleSelection/AutoSelection
- [test_cli_pipe.py](test_cli_pipe.py) - PipeSelection 预加载
- [test_cli_defaults.py](test_cli_defaults.py) - defaults + validate + proxy
- [test_cli_sdk.py](test_cli_sdk.py) - UcrawlSDK
- [test_cli_runner.py](test_cli_runner.py) - CLIRunner 生命周期

### Web / API（web_api 类别）
- [test_fastapi_endpoints.py](test_fastapi_endpoints.py) - FastAPI 全部 REST 端点
- [test_web_entry.py](test_web_entry.py) - Web 入口
- [test_contract.py](test_contract.py) - CLI/SDK/API 三层契约

### 端到端 / 打包 / UI / 管道
- [test_e2e.py](test_e2e.py) - 完整流程
- [test_packaging.py](test_packaging.py) - 打包配置
- [test_ui_dialogs.py](test_ui_dialogs.py) - 弹窗与界面
- [test_pipeline.py](test_pipeline.py) - 管道选择

### 浏览器 E2E（browser_e2e 类别）
- [test_web_browser.py](test_web_browser.py) - Playwright 真实浏览器测试
  - StaticAssetsTests（HTML/CSS/JS 静态结构，不需 Playwright）
  - WebSocketMessageTypesTests（WS 消息类型一致性）
  - WebUIBrowserTests（15+ 浏览器交互：主题切换、弹窗、键盘、删除等）
  - WebUIAccessibilityTests（按钮可读性、html lang、viewport）
  - WebDesignGuidelinesTests（focus 样式、hover、disabled、错误日志）
- [web_test_app.py](web_test_app.py) - uvicorn 启动 shim（暴露 `app` 给 `tests.web_test_app:app`）

### 核心组件（core_services 类别）
- test_application_controller.py - 控制器
- test_downloaders.py / test_download_manager_dispatch.py - 下载器
- test_spider_helpers.py - 爬虫辅助
- test_file_service.py - 文件服务
- test_main_window.py / test_main_entry.py - 主窗口与入口

### 历史其他测试
- test_auth_service.py / test_settings_builders.py - 服务
- test_runtime_paths.py - 路径解析
- test_download_queue_panel.py - 队列面板
- test_cli_pipe.py / test_cli_sdk.py - 管道与 SDK
- 等等...

## 运行方式

### 推荐：统一测试启动器

```bash
# 弹 Qt 菜单（默认）
python tests/test_launcher.py

# 命令行
python tests/test_launcher.py --category all
python tests/test_launcher.py --category cli_sdk
python tests/test_launcher.py --category browser_e2e
```

### 全量（CLI）

```bash
python tests/run_all_tests.py
```

### 按类别（CLI）

```bash
python tests/run_all_tests.py --category cli_sdk       # CLI / SDK
python tests/run_all_tests.py --category web_api       # Web / API
python tests/run_all_tests.py --category app_flows     # 应用流程
python tests/run_all_tests.py --category desktop_ui    # 桌面界面
python tests/run_all_tests.py --category pipeline      # 管道
python tests/run_all_tests.py --category packaging     # 打包
python tests/run_all_tests.py --category browser_e2e   # 浏览器 E2E
python tests/run_all_tests.py --category core_services # 核心服务
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

## 编写约定

- 统一用 `pytest` 作为执行入口
- 测试主体可继续使用 `unittest.TestCase` 风格（与历史资产兼容）
- 测试文件名以 `test_` 开头
- 类名以 `Test` 结尾（单元测试）或描述性名词
- 方法名以 `test_` 开头
- 一个测试一个断言重点
- 优先 mock 外部依赖（爬虫、网络）
- 不真爬虫（避免线程崩溃 + 测试慢）

## 扩展测试类别

新增测试类别或把新脚本纳入现有套件，优先走注册接口：

```python
from tests.test_registry import (
    register_category,
    register_category_rule,
    register_test_files,
)

register_category(
    id="perf",
    name="性能测试",
    description="基准测试 + 内存分析",
    files=["tests/test_perf_bench.py"],
)

register_category_rule(
    id="plugin_api",
    name="插件接口",
    description="自动纳入某个命名规则下的新测试脚本",
    include=["tests/test_plugin_*.py"],
)

register_test_files(
    "suite_infra",
    ["tests/test_new_suite_case.py"],
)
```

## 测试覆盖范围

### 黑盒测试
- 所有 REST API 端点的输入校验 + 响应结构
- CLI 子命令的参数解析 + 调用路径
- SDK 函数调用的输入校验 + 返回值结构
- Web 浏览器真实交互（Playwright）

### 白盒测试
- SelectionStrategy 协议（duck-type check）
- PipeSelection 的 stdin 解析逻辑
- WebController 的端口处理
- 打包 spec 的 hiddenimports / datas 配置

### 单元测试
- 各种选择策略（Rule/Pipe/Interactive/Auto）
- 配置校验函数
- argparse 子命令

### 集成测试
- TestClient 完整 HTTP 流程
- 跨层调用链路（CLI → handler → SDK → Runner）
- 多端点协作（scan → dir/change → state）

### API 测试
- FastAPI 20+ 端点
- HTTP 状态码 + 响应体结构
- 跨域（CORS）头

### 管道测试
- stdin JSON 多种格式（list / dict with indices / items）
- stdout 结构化 JSON 输出
- 多轮预加载（合集场景）

### E2E 测试
- 完整 scan → dir/change → state 链路
- 配置持久化 PUT/GET 循环
- SDK 资源管理（with / close / QApplication）

### Web 浏览器测试（新增）
- 静态资源（HTML/CSS/JS 结构）
- WebSocket 消息类型一致性
- 真实浏览器交互（主题切换、弹窗、键盘、删除）
- 可访问性（按钮可读、html lang、viewport）
- 设计指南（focus、hover、disabled、错误日志）

## 修复的生产 Bug

通过本次全量测试，发现并修复了 3 个生产 bug：

1. **RuleSelection.__init__ 中 `self.select = select` 覆盖了 `def select()` 方法**
   - 修复：用 `self._select_rule = select`
   - 发现于：test_cli_selection.py

2. **cli/main.py 顶部 `sys.path.insert(0, ROOT)` 不去重**
   - 修复：加 `if _PROJECT_ROOT not in sys.path:` 去重检查
   - 发现于：test_cli_main.py

3. **SDK `_resolve_selection` 中 `isinstance(selection, SelectionStrategy)` 在 Protocol 没 @runtime_checkable 时崩 TypeError**
   - 修复：加 `is_selection_strategy()` duck-type check 函数
   - 发现于：test_contract.py

## 维护建议

新增平台或重构目录时，请同步更新本文件与 `docs/testing.md`。
