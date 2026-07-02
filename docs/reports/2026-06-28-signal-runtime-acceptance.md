# 信号刷新与运行时验收报告（2026-06-28）

## 范围

本报告合并原“信号与刷新链路基线报告”和“信号优化验收报告”。它记录 2026-06-28 阶段 GUI、WebUI、EventBus、AppState、下载进度、日志刷新、WebSocket 推送、HTTP 前端增量和页面渲染的基线与验收结论。

当前推荐做法已沉淀到 [前端刷新与并发控制工程实践](../engineering/frontend-refresh-and-concurrency.md)。后续维护应优先阅读工程实践文档，本报告只作为阶段验收记录。

## 基线链路

### GUI

1. 用户动作从 `app/ui/main_window.py` 和 `app/ui/layout/app_shell.py` 进入。
2. 控件通过 PyQt 信号发出启动、停止、删除、设置变更和页面切换等动作。
3. 状态写入应用状态和前端状态适配层。
4. EventBus 发布变化。
5. `UiUpdateScheduler` 合并刷新主题并投递到 GUI 线程。
6. `FrontendStateService` 生成快照或增量。
7. 当前可见页面刷新内容区，不可见页面只更新角标和底部状态。

### WebUI

1. 后端事件进入 WebSocket 桥。
2. `FrontendStateService` 记录前端事件并生成版本化增量。
3. WebSocket 每连接维护有界发送队列。
4. 客户端版本过旧时恢复全量，否则发送 `frontend_delta`。
5. 浏览器端 reducer 合并 section 并按需渲染。

## 已验收能力

- HTTP 与 WebSocket 前端增量对齐。
- `/api/frontend/action` 支持携带前端版本并在可用时返回 `frontend_delta`。
- WebSocket 有界队列可以合并或丢弃过期 noisy 事件。
- 日志追加按短窗口批处理。
- 清空日志和调整日志缓冲会取消未发送批次并发布状态。
- 旧 WebSocket 直接事件统一经过记录路径，保证版本化增量一致。

## 验证证据

- Python 编译检查通过。
- `node --check app/web/static/app.js` 通过。
- Web 浏览器测试通过 40 项。
- GUI、UI 调度、WebSocket 和 FastAPI 相关测试通过 116 项。
- 可见 GUI 自动化场景通过：插入 80 个模拟任务、追加 1000 条日志、切换 7 个页面 8 轮、批量删除 40 个任务、清空队列并正常退出。
- 离屏 GUI 压力场景通过：插入 120 个任务、切换页面 30 轮、批量删除 80 个任务、清空队列。
- 真实浏览器 WebUI 场景通过：切换页面、渲染 1000 条日志、执行前端动作、观察版本推进且无页面错误。

## 后续原则

- 所有高频事件路径都优先使用合并、节流、增量和可见区域刷新。
- 任何引入同步重计算或全页重绘的改动都要补充性能或回归测试。
- EventBus handler 如果持续变慢，应把耗时工作迁移到异步任务或适配队列。
