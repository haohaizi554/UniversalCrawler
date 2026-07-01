# 最终验收报告（2026-06-28）

## 范围

本报告记录 2026-06-28 阶段 GUI、WebUI、配置中心、安装组件、测试和文档的验收结论。

## GUI 验收

- 使用真实 PyQt 控件在 `QT_QPA_PLATFORM=offscreen` 下完成 `AppShell + FrontendStateService` 烟测。
- 7 个页面切换成功：下载队列、正在下载、已完成、失败列表、日志中心、配置中心、工具箱。
- 6 个配置组渲染成功：基础、下载、平台、播放、日志、外观。
- 热加载验证：`download.max_retries` 完成 `3 -> 0 -> 3`，`common.theme` 完成 `light -> dark -> light`。
- 默认打开方式信号验证为 `[true, false]`，即默认只注册视频资源。
- 未观察到异常退出。

## WebUI 验收

- WebUI 以 `--no-qt --no-browser` 模式启动并完成 Playwright 验证。
- 桌面、移动端和宽屏视口均未发现横向溢出。
- 设置页卡片和控件可渲染，REST 热加载可恢复。
- `/api/frontend/delta` 返回 sections、version、base_version 等关键字段。
- 未观察到控制台错误、异常 HTTP 响应或异常退出。

## 配置中心验收

| 配置组 | GUI | WebUI | 后端路径 |
| --- | --- | --- | --- |
| 基础 | 渲染成功，默认打开方式信号可用 | 渲染成功 | `update_basic_setting`、`register_file_associations` |
| 下载 | 数值控件稳定 | 数值控件稳定 | `update_setting(download, key, value)` |
| 平台 | 代理启用类型修复后稳定 | 代理控件状态同步 | `update_setting(platform, key, value)` |
| 播放 | 渲染成功 | 渲染成功 | `update_setting(playback, key, value)` |
| 日志 | 渲染成功 | 渲染成功 | `update_setting(logging, key, value)` |
| 外观 | 主题可热加载 | 主题路径共享 | `update_setting(common/appearance, key, value)` |

## 安装组件验收

- 便携版入口包含 `UniversalCrawlerPro.exe` 和 `CrawlerWebPortal.exe`。
- Inno Setup 编译器路径已识别。
- 安装器产物存在，且 EXE 头校验为 `MZ`。
- 打包脚本、安装器资源和测试文档需要继续保持同步。

## 结论

阶段目标在 GUI/WebUI 设置热加载、运行基线、安装组件适配和文档记录方面通过验收。后续若继续改动配置中心、前端状态服务或打包流程，应优先复跑对应分组测试并更新本文档或新增报告。
