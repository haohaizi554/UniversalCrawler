# 运行基线报告（2026-06-28）

## 范围

本报告记录继续推进 GUI、WebUI 和配置中心工作前的运行基线。验证覆盖真实 PyQt6 `QApplication`、`MainWindow`、WebUI 服务入口、配置读写和前后端配置链路。

## 入口结果

| 区域 | 命令或入口 | 结果 |
| --- | --- | --- |
| GUI | `python -m entry.gui_entry` / `entry.gui_entry:main` | 入口可导入，烟测通过 `MainWindow` 执行 |
| WebUI | `python -m entry.web_entry --no-qt --no-browser --host 127.0.0.1 --port 8765` | 服务成功启动 |
| 配置文件 | `user_data/config.json` | 通过 `ConfigManager` 验证读写 |
| GUI 后端链路 | `MainWindow -> AppShell -> FrontendStateService -> ConfigManager` | GUI 烟测验证 |
| WebUI 后端链路 | `Browser -> /api/frontend/action -> WebController -> FrontendStateService -> ConfigManager` | Playwright 与 REST 验证 |

## GUI 基线

- 7 个 GUI 页面可打开：下载队列、正在下载、已完成、失败列表、日志中心、配置中心、工具箱。
- 6 个配置组可打开：基础、下载、平台、播放、日志、外观。
- `download.max_retries` 可从 `3 -> 0 -> 3` 热加载并恢复。
- `common.theme` 可从 `light -> dark -> light` 写入并恢复。
- 最终 GUI 烟测未观察到异常退出。

## WebUI 基线

- `/api/ping` 返回 `status=ok` 和版本号。
- `/api/frontend/state` 返回 `settings_snapshot`。
- `/api/frontend/delta?since_version=0` 返回 sections 和版本元数据。
- WebUI 基线产物保存在 `runtime_artifacts/baseline-webui/`。

## 后续要求

- 继续修改配置中心前，必须保持 GUI 和 WebUI 都通过同一配置快照更新。
- 影响主题、语言、代理、下载策略的改动需要同时验证 GUI 与 WebUI。
- 阶段完成后更新最终验收报告。
