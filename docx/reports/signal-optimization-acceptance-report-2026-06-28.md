# 信号优化验收报告（2026-06-28）

## 结果

GUI 与 WebUI 的信号、事件和刷新优化通过自动化运行验证。验收范围集中在 PyQt GUI 刷新、EventBus、AppState、下载进度节流、日志批处理、WebSocket 背压、前端增量和页面刷新行为。

## 本轮接受的改动

### HTTP 与 WebSocket 前端增量对齐

- `/api/frontend/action` 支持携带 `frontend_version`。
- HTTP 动作在可用时返回 `frontend_delta`。
- WebUI 可直接应用动作返回的增量，必要时再回退请求 `/api/frontend/delta`。
- WebSocket 分发只在客户端版本过旧时发送增量。

### WebSocket 背压

- 每个连接使用有界发送队列。
- 高频噪声事件按类型和合并键去重。
- 队列溢出时优先丢弃过期噪声事件。

### GUI 日志刷新批处理

- `AppState` 保持内存日志即时写入。
- `logs.append` EventBus 通知以 100 ms 窗口批处理。
- 清空日志和调整日志缓冲时取消未发送批次，并显式发布状态。

### WebUI 直接发送事件记录

- 直接发送的旧 WebSocket 事件统一经过记录路径。
- `clear_videos`、`item_found`、`scan_result`、`video_removed`、`video_renamed` 和日志事件可与版本化增量保持一致。

## 验证证据

- Python 编译检查通过。
- `node --check app/web/static/app.js` 通过。
- Web 浏览器测试通过 40 项。
- GUI、UI 调度、WebSocket 和 FastAPI 相关测试通过 116 项。
- 可见 GUI 自动化场景通过：插入 80 个模拟任务、追加 1000 条日志、切换 7 个页面 8 轮、批量删除 40 个任务、清空队列并正常退出。
- 离屏 GUI 压力场景通过：插入 120 个任务、切换页面 30 轮、批量删除 80 个任务、清空队列。
- 真实浏览器 WebUI 场景通过：切换页面、渲染 1000 条日志、执行前端动作、观察版本推进且无页面错误。

## 结论

信号与事件刷新优化在本轮范围内通过验收。后续若发现某个 EventBus handler 持续变慢，应把长耗时工作迁移到异步或排队适配层，避免重新把同步分发路径拖慢。
