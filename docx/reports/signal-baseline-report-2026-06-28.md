# 信号与刷新链路基线报告（2026-06-28）

## 范围

本报告覆盖会影响 GUI 和 WebUI 响应性的信号、事件和刷新路径，包括 PyQt 信号、EventBus、AppState、下载进度、日志刷新、WebSocket 推送、HTTP 前端增量和页面渲染。

不包含 UI 重设计、下载协议重写、平台插件重写或大型架构替换。

## GUI 刷新链路

1. 用户动作从 `app/ui/main_window.py` 和 `app/ui/layout/app_shell.py` 进入。
2. GUI 控件发出 PyQt 信号，例如启动采集、停止采集、删除、设置变更和页面切换。
3. 状态写入 `app/services/app_state.py`。
4. `AppState._publish_change()` 通过 `app/core/event_bus.py` 发布变化。
5. `MainWindow._on_app_state_changed()` 映射刷新主题，并交给 `app/ui/ui_update_scheduler.py` 合并调度。
6. `UiUpdateScheduler` 在 GUI 线程中刷新。
7. `FrontendStateService` 生成快照或增量，`AppShell.render()` 只刷新相关可见区域。
8. 表格页面使用模型更新，优先 `dataChanged`，必要时才 reset。

## WebUI 刷新链路

1. 后端事件进入 `app/web/controller.py` 的 WebSocket 桥。
2. `FrontendStateService.record_event()` 记录前端事件并生成版本化增量。
3. `app/web/ws_transport.py` 为每个连接维护有界队列。
4. `app/web/ws_dispatcher.py` 根据客户端版本发送必要增量。
5. REST 层暴露 `/api/frontend/state`、`/api/frontend/delta` 和 `/api/frontend/action`。
6. 前端通过 `requestAnimationFrame` 和 section 调度应用增量渲染。

## 已有保护

- GUI 刷新由 `UiUpdateScheduler` 合并并投递到 Qt 线程。
- 前端状态支持版本化增量和 section 级渲染。
- 表格模型在行身份稳定时避免整表 reset。
- AppState 保留有界日志缓冲。
- 下载进度在 GUI 与 WebController 侧均有节流。
- WebSocket 连接使用有界队列，并可合并或丢弃高频噪声事件。
- WebUI DOM 渲染通过 `requestAnimationFrame` 批处理。

## 仍需关注的高风险点

- 大规模本地扫描或队列替换仍可能触发表格模型重置。
- 高频下载状态变化会让任务在多个列表间移动，带来多 section 刷新压力。
- 日志过滤和排序在大量日志可见时仍可能成为热点。
- 全量 `frontend_state` 快照会重建大列表和日志区。
- 慢 WebSocket 客户端虽然有背压保护，但仍需观察队列堆积。

## 高风险文件

- `app/web/controller.py`
- `app/services/frontend_state_service.py`
- `app/services/app_state.py`
- `app/web/ws_transport.py`
- `app/ui/main_window.py`

## 后续原则

所有高频事件路径都应优先使用合并、节流、增量和可见区域刷新。任何引入同步重计算或全页重绘的改动都应补充性能或回归测试。
