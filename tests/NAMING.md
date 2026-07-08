# 测试命名规范

> 更新时间：2026-07-08
> 适用范围：`tests/` 目录下所有 pytest 测试文件与辅助脚本

## 目标

测试注册表按文件名和显式规则自动分类。命名稳定，新增脚本就能进入正确套件；命名随意，脚本会落入 `misc`，需要后续补分类。

当前事实来源是 [test_registry.py](test_registry.py)。修改命名规则前先运行：

```bash
python tests/test_registry.py
python tests/test_launcher.py --list
```

## 总规则

- 可被 pytest 自动发现的测试文件必须使用 `test_*.py`。
- 文件名优先使用 `test_<subject>.py`，需要细分时使用 `test_<module>_<feature>.py`。
- 一个文件表达一个主职责，不要把多个无关主题塞进同一个文件名。
- 运行脚本、复现脚本、Web 测试 shim 不使用 `test_` 前缀。

推荐示例：

- `test_fastapi_endpoints.py`
- `test_frontend_snapshot_worker.py`
- `test_log_detail_worker.py`
- `test_spider_runtime.py`
- `test_ws_transport_backpressure.py`

不推荐示例：

- `test_misc.py`
- `test_new.py`
- `test_fix.py`
- `test_all_things.py`

## 分类命名规则

### CLI / SDK：`cli_sdk`

命中规则：

- `tests/test_cli_*.py`

适合内容：

- CLI 参数解析、交互命令、默认值、选择策略、管道输入、SDK 和 Runner。

示例：

- `test_cli_main.py`
- `test_cli_interactive_command.py`
- `test_cli_selection.py`

### Web / API：`web_api`

命中规则：

- `tests/test_contract.py`
- `tests/test_fastapi_*.py`
- `tests/test_web_*.py`
- `tests/test_web_entry.py`
- `tests/test_web_controller_*.py`
- `tests/test_websocket_*.py`
- `tests/test_ws_*.py`

排除：

- `tests/test_web_browser.py`，它属于 `browser_e2e`。

适合内容：

- FastAPI 端点、WebController、WebSocket、REST/Web 入口、Web 脚本 API、多入口契约。

### 应用流程：`app_flows`

命中规则：

- `tests/test_e2e.py`
- `tests/test_main_entry.py`
- `tests/test_*_entry.py`
- `tests/test_*_entry_*.py`
- `tests/test_entry_*.py`
- `tests/test_cross_entry_*.py`
- `tests/test_integration_*.py`

适合内容：

- 跨入口一致性、端到端流程、入口调度和跨模块集成流。

注意：`test_cli_entry.py`、`test_web_entry.py`、`test_gui_entry.py` 可能同时命中接口层或 UI 相关分类，这是预期的交叉覆盖。

### 桌面界面：`desktop_ui`

命中规则：

- `tests/test_application_controller.py`
- `tests/test_download_queue_panel.py`
- `tests/test_main_window.py`
- `tests/test_desktop_host.py`
- `tests/test_gui_*.py`
- `tests/test_media_preview_panel.py`
- `tests/test_log_panel.py`
- `tests/test_log_center_semantics.py`
- `tests/test_snapshot_*.py`
- `tests/test_ui_*.py`
- `tests/test_unified_frontend_contract.py`
- `tests/test_log_*.py`
- `tests/test_list_page_worker.py`

适合内容：

- PyQt 主窗口、布局 shell、TopBar/Sidebar/StatusBar、日志中心、列表分页、媒体预览、队列面板、GUI 入口和统一前端契约。

命名建议：

- 新 GUI 入口或控件测试用 `test_gui_<subject>.py`。
- 通用 Qt UI 行为用 `test_ui_<subject>.py`。
- 日志中心显示/筛选/详情用 `test_log_<subject>.py`。
- 列表快照或表格模型用 `test_snapshot_<subject>.py`。

### 浏览器 E2E：`browser_e2e`

命中规则：

- `tests/test_web_browser.py`

说明：

- 这是 Playwright 真实浏览器套件，保持单独文件名，不与普通 `test_web_*.py` 混用。

### 数据管道：`pipeline`

命中规则：

- `tests/test_pipeline.py`

适合内容：

- stdin/stdout JSON 管道、多轮选择与预加载链路。

### 打包发布：`packaging`

命中规则：

- `tests/test_packaging.py`

适合内容：

- PyInstaller spec、runtime hook、资源文件、发布入口、临时探针残留检查。

### 核心服务：`core_services`

命中规则包括：

- `tests/test_config_*.py`
- `tests/test_count_project.py`
- `tests/test_debug_logger.py`
- `tests/test_plugin_*.py`
- `tests/test_runtime_paths.py`
- `tests/test_settings_*.py`
- `tests/test_utils_*.py`
- `tests/test_video_item.py`
- `tests/test_xiaohongshu_integration.py`
- `tests/test_core_*.py`
- `tests/test_*_service.py`
- `tests/test_*_parameter.py`
- `tests/test_download*.py`
- `tests/test_download_*.py`
- `tests/test_*_mixin.py`
- `tests/test_spider_*.py`
- `tests/test_shared_*.py`
- `tests/test_anti_detection.py`
- `tests/test_media_release_*.py`
- `tests/test_media_library_*.py`
- `tests/test_controller_*_mixin.py`
- `tests/test_concurrency_*.py`
- `tests/test_event_*.py`
- `tests/test_frontend_event_*.py`
- `tests/test_frontend_*.py`
- `tests/test_failed_record_store.py`
- `tests/test_metadata_*.py`
- `tests/test_completed_metadata_*.py`
- `tests/test_pagination_*.py`
- `tests/test_m3u8_*.py`
- `tests/test_task_runtime_*.py`
- `tests/test_request_workers.py`
- `tests/test_ws_transport_*.py`
- `tests/test_guardrails.py`
- `tests/test_mojibake_guard.py`
- `tests/test_event_bus_extended.py`
- `tests/test_proxy_manager.py`

排除：

- `tests/test_download_queue_panel.py`，它属于 `desktop_ui`。

适合内容：

- 下载器、配置、文件服务、调试服务、插件、前端状态适配、事件聚合、日志翻译、媒体元数据、控制器 mixin、并发、WebSocket 传输基础设施等非 UI 主体逻辑。

### 架构适应度：`architecture`

命中规则：

- `tests/architecture/test_*.py`

适合内容：

- 依赖方向、Spider 协议、文件大小限制、模块边界和结构性规则。

新增架构规则必须放在 `tests/architecture/` 子目录内，避免和普通业务测试混在一起。

### 性能基准：`benchmark`

命中规则：

- `tests/test_performance_benchmarks.py`

适合内容：

- 显式运行的轻量性能基准。新增性能测试先评估是否仍应放入这个文件；如果基准开始分域扩展，再新增清晰前缀并更新注册表。

### 测试套件自身：`suite_infra`

命中规则：

- `tests/test_test_*.py`

适合内容：

- 测试入口、分类注册、启动器 GUI/TUI/CLI 行为、测试套件自身契约。

示例：

- `test_test_entry.py`
- `test_test_launcher_ui.py`

### 未归类：`misc`

`misc` 是兜底分类，不是目标分类。新增文件落入 `misc` 时，按顺序处理：

1. 调整文件名命中现有规则。
2. 如果确实是长期新职责，扩展 `tests/test_registry.py`。
3. 同步更新本文档和 `tests/README.md`。

## 测试方法命名

- 测试方法必须以 `test_` 开头。
- 推荐格式：`test_<action>_<condition>_<expected>`。
- 名称表达“行为 + 场景 + 预期”，不要只描述实现细节。

推荐：

- `test_theme_toggle_coalesces_rapid_clicks_to_latest_state`
- `test_frontend_delta_returns_recoverable_snapshot_when_version_missing`
- `test_download_worker_releases_slot_after_failure`

不推荐：

- `test_case_1`
- `test_logic`
- `test_fix_bug`

## 辅助脚本命名

下列文件不是 pytest 自动发现目标，不使用 `test_` 前缀：

- 运行脚本：`run_*.py`
- 复现脚本：`reproduce_*.py`
- Web 测试应用 shim：`*_app.py`

示例：

- `run_all_tests.py`
- `run_core_suite.py`
- `reproduce_user_bug.py`
- `web_test_app.py`

## 新增测试检查清单

新增测试前：

1. 明确它属于哪个现有分类。
2. 选择能命中该分类的文件名。
3. 避免让一个文件同时承担多个不相关职责。

新增测试后：

```bash
python tests/test_registry.py
python tests/test_launcher.py --list
python -m pytest tests/<new_test_file>.py -q
```

如果 `auto_discover_tests()` 输出了新文件，说明它没有命中任何规则，需要改名或更新注册表。

## 修改分类规则

满足下面任一条件时，可以扩展自动分类规则：

- 同一类新增测试连续出现 2 个以上新命名前缀。
- 新模块会长期稳定扩展，不适合继续放入显式文件列表。
- `python tests/test_registry.py` 持续出现同类文件落入 `misc`。

规则变更后必须同步更新：

- [test_registry.py](test_registry.py)
- [test_test_entry.py](test_test_entry.py)
- [test_test_launcher_ui.py](test_test_launcher_ui.py)（如果影响启动器展示）
- [README.md](README.md)
- 本文档
- [../docs/guides/testing.md](../docs/guides/testing.md)
