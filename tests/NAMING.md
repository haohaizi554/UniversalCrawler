# 测试命名规范

> 更新时间：2026-06-08
> 适用范围：`tests/` 目录下所有 pytest 测试文件与辅助脚本

## 目标

测试套件的自动分类功能依赖文件命名规则工作。
命名稳定，新增测试就能自动进入正确分类；命名随意，文件就会掉进 `misc`，需要手工补分类。

## 1. 文件命名总规则

- 可被 pytest 自动发现的测试文件必须使用 `test_*.py`
- 文件名格式优先使用：`test_<subject>.py`
- 需要更细粒度时使用：`test_<module>_<feature>.py`
- 只表达一个主职责，避免把多个无关主题塞进同一个文件名

示例：

- `test_web_controller_selection.py`
- `test_download_manager_core.py`
- `test_douyin_parameter.py`
- `test_cli_interactive_command.py`

## 2. 类别前缀约定

新增测试时，优先按下面前缀命名，这样可以自动归类。

### CLI / SDK

- 前缀：`test_cli_`
- 自动归入：`cli_sdk`
- 示例：
  - `test_cli_main.py`
  - `test_cli_runner.py`
  - `test_cli_interactive_command.py`

### Web / API

- 前缀：
  - `test_fastapi_`
  - `test_web_controller_`
  - `test_websocket_`
  - `test_web_entry.py`
- 自动归入：`web_api`
- 示例：
  - `test_fastapi_endpoints.py`
  - `test_web_controller_selection.py`
  - `test_websocket_bridge.py`

### 应用流程

- 前缀：
  - `test_integration_`
  - 保留文件：`test_e2e.py`、`test_main_entry.py`
- 自动归入：`app_flows`
- 示例：
  - `test_integration_flows.py`

### 桌面界面

- 前缀：`test_ui_`
- 保留文件：
  - `test_application_controller.py`
  - `test_main_window.py`
  - `test_download_queue_panel.py`
- 自动归入：`desktop_ui`
- 示例：
  - `test_ui_dialogs.py`

### 浏览器 E2E

- 文件：`test_web_browser.py`
- 自动归入：`browser_e2e`
- 说明：这个文件保留单独命名，不与普通 `test_web_*` 混用

### 数据管道

- 文件：`test_pipeline.py`
- 自动归入：`pipeline`

### 打包发布

- 文件：`test_packaging.py`
- 自动归入：`packaging`

### 核心服务

- 前缀：
  - `test_*_service.py`
  - `test_*_parameter.py`
  - `test_download_*.py`
  - `test_*_mixin.py`
  - `test_spider_*.py`
- 以及少量保留文件：
  - `test_config_settings.py`
  - `test_debug_logger.py`
  - `test_plugin_registry.py`
  - `test_runtime_paths.py`
  - `test_settings_builders.py`
  - `test_utils_filenames.py`
  - `test_video_item.py`
- 自动归入：`core_services`
- 示例：
  - `test_auth_service.py`
  - `test_download_manager_core.py`
  - `test_douyin_parameter.py`
  - `test_controller_session_mixin.py`
  - `test_spider_base.py`

### 测试套件自身

- 前缀：`test_test_`
- 自动归入：`suite_infra`
- 示例：
  - `test_test_entry.py`
  - `test_test_launcher_ui.py`

## 3. 方法命名规则

- 测试方法必须以 `test_` 开头
- 推荐格式：`test_<action>_<condition>_<expected>`
- 名称要表达“行为 + 场景 + 预期”，而不是只写实现细节

推荐示例：

- `test_apply_plugin_dir_invalid_format`
- `test_builtin_rules_cover_current_named_tests`
- `test_create_client_only_builds_proxy_mounts_when_proxy_configured`

不推荐示例：

- `test_case_1`
- `test_misc`
- `test_logic`

## 4. 辅助脚本命名

下列文件不是 pytest 自动发现目标，不要使用 `test_` 前缀：

- 运行脚本：`run_*.py`
- 复现脚本：`reproduce_*.py`
- Web 测试应用 shim：`*_app.py`

示例：

- `run_all_tests.py`
- `run_core_suite.py`
- `reproduce_user_bug.py`
- `web_test_app.py`

## 5. 新增测试时的建议

新增测试前，先问自己两个问题：

1. 这个测试属于哪个现有分类？
2. 文件名是否已经符合该分类的自动归类前缀？

如果答案是否定的，优先调整文件名，其次才修改 `tests/test_registry.py`。

## 6. 何时修改分类规则

满足下面任一条件时，可以考虑扩展自动分类规则：

- 同一类新增测试连续出现 2 个以上新命名前缀
- 新模块将长期稳定扩展，不适合继续放入显式文件列表
- `ucrawl-test --list` 或 `auto_discover_tests()` 持续出现同类文件落入 `misc`

规则变更后，必须同步更新：

- `tests/test_registry.py`
- `tests/test_test_entry.py`
- 本文档 `tests/NAMING.md`
