# 前端刷新与并发控制工程实践

本文是 GUI、WebUI、日志中心、下载队列和下载管理器在高频事件下的当前工程准则。若历史报告、修复记录或 Prompt 与本文冲突，以本文为准。

## 目标

- 高频进度、速度、日志事件可以合并，界面保持流畅。
- 完成、失败、删除、停止、用户选择等关键事件不能被丢失。
- GUI 主线程只做可见区域的轻量刷新。
- WebSocket 和 WebUI 不因慢客户端或日志洪峰被拖垮。
- 下载并发表示“最大同时运行任务数”，不是串行执行一整个任务后才启动下一个。

## 事件分级

| 等级 | 典型事件 | 处理方式 |
| --- | --- | --- |
| critical | 完成、失败、删除、停止、用户选择、配置关键变更 | 低延迟刷新，不被 noisy 事件挤掉 |
| normal | 队列结构变化、页面切换、设置快照变化 | 批量刷新对应 section |
| noisy | 下载进度、速度趋势、日志追加 | 固定帧率合并，latest-state-wins |

高频事件不得直接触发全量 `frontend_state` 或整页重建。除初始化、恢复和主动手动刷新外，优先使用 `frontend_delta`。

## GUI 刷新规则

- 只有当前可见页面刷新主内容区；不可见页面只更新侧栏角标和底部状态栏。
- GUI 初始化、切换 `FrontendStateService`、主动强制刷新可以走全量 snapshot；已有缓存后的普通刷新必须携带缓存 `version` 走 `FrontendSnapshotWorker(use_delta=True)`。
- GUI delta 路径先调用 `FrontendStateService.get_delta(base_version)`，只把返回的 `sections` 合并进缓存；只有服务端返回 `full=True` 时才允许退回全量 snapshot。
- 页面切换等显式可见页请求如果版本未变化，只允许补拉目标 section，不能因为 `changed_sections` 为空退回全量刷新。
- 下载队列、正在下载、已完成、失败列表只按 section delta 刷新。
- 视频普通操作（重排、删除、失败重试、暂停、元数据更新）必须传入 `videos.*` topic 触发局部刷新；不得使用 `force=True` 绕过 delta，除非是初始化、切换 `FrontendStateService`、主动清缓存或错误恢复。
- 大表格优先按 id 更新行，避免单个进度变化 reset 整表。
- 通用 snapshot 表格使用稳定 `id` 做行级 patch；尾部追加/移除必须使用 `rowsInserted` / `rowsRemoved`，只有乱序或中间结构变化才允许 `modelReset`。
- 日志中心使用有界缓存和增量 append；调整“UI 最大显示日志数量”时：
  - 小变大：只扩容缓存上限，不从日志文件一次性回填。
  - 大变小：直接裁掉内存中多余日志。
  - 当前不可见时不重建日志表。
- 单次渲染超预算时应写 WARN，并降低刷新频率或缩小刷新范围。

## WebUI 刷新规则

- 初始连接和断线恢复使用 `frontend_state`。
- 稳定运行使用 `frontend_delta`。
- 浏览器端 reducer 合并 section；表格使用 keyed row patch。
- 进度、速度、日志类更新通过 `requestAnimationFrame` 批处理。
- 非当前页不重建 DOM，只更新必要角标和底部状态。
- WebSocket 每连接使用有界队列；noisy 消息可以合并或丢弃旧值，critical 消息不能被丢弃。

## UI / Worker / Cache / DB 职责边界

日志中心、失败列表和大表格遵循三层边界。后续改动如果跨过这些边界，必须同时补回归测试。

### UI Thread

UI 线程只负责显示和轻量交互：

- 接收后端或 worker 发来的当前页 batch。
- 批量 append / patch 到 Qt model 或 Web DOM。
- 更新选中态、按钮状态、分页状态和详情面板。
- 不读取日志文件。
- 不解析日志文本。
- 不执行大列表过滤、排序、分页。
- 不在选中行时同步规整日志详情、递归本地化或格式化大段 JSON。
- 不同步构建完整 frontend snapshot，不做大段 JSON 签名 diff。
- 不直接查询 SQLite、diskcache 或大体量本地缓存。

GUI 主窗口刷新时只向 `FrontendSnapshotWorker` 提交目标 section、当前快照引用和签名表，snapshot 构建、局部合并和 section diff 在 worker 中完成；GUI 日志页提交查询时只传递当前快照引用，行复制、筛选、排序和分页由 `LogQueryWorker` 完成；GUI 日志详情选中行后只提交当前行快照，字段派生、本地化、详情 JSON 格式化和 HTML 转义由 `LogDetailWorker` 完成，详情动作按钮必须等 worker 结果回来后再启用，不允许用 UI 线程 fallback 重新构建详情 payload；WebUI 大批日志由 `log_query_worker.js` 完成，主线程只接收 `pageItems` 并 patch 当前页。

### Worker Thread

Worker 线程负责所有可能卡住 UI 的工作：

- 日志文件 tail 增量读取。
- 日志文本解析和字段规整。
- 过滤、排序、分页和选中项定位。
- 读写本地缓存。
- 写入 SQLite / diskcache。
- 构建 frontend snapshot，合并局部 section，并计算 section 签名差异。
- 生成 UI 可直接渲染的当前页 batch。
- 生成日志详情面板可直接渲染的字段、已格式化 JSON 文本和已转义 JSON 片段。

当前落地组件：

- `FrontendLogCache`：后台 tail 最新 debug 日志，增量解析，避免 snapshot 热路径直接读文件。
- `FrontendSnapshotWorker`：GUI snapshot 构建、局部合并和 section diff。
- `LogQueryWorker`：GUI 日志中心筛选、排序、分页。
- `LogDetailWorker`：GUI 日志详情字段派生、本地化、JSON 格式化和 latest-state-wins 防抖。
- `log_query_worker.js`：WebUI 大批日志查询。
- `FailedRecordStore`：失败记录后台写 SQLite，并刷新内存快照。

### Cache / DB

缓存和结构化存储按数据热度分工：

- `cachetools`：短 TTL 热数据，只放 UI 高频读取的小体量结果。
- `diskcache`：解析结果、本地 key-value 缓存和可重用中间结果。
- SQLite：失败记录、结构化查询、可分页和可索引的数据。

UI 热路径只能读取已经准备好的内存快照。维护脚本、测试或显式管理动作可以调用同步查询接口，但 GUI/WebUI 页面渲染链路不得直接查 SQLite 或重扫日志文件。

## 下载并发规则

- 普通并发默认 3，推荐选项为 1、3、5。
- 并发数是运行态最大同时下载任务数，应动态生效；释放槽位后必须继续派发等待队列。
- 图片资源可以走独立快速通道，但也必须有上限。当前建议图片快速通道最多 10 个同时任务。
- 下载派发信号量必须在 `finally` 路径释放，失败和取消也不能泄漏槽位。
- 解析、队列、下载、日志和前端刷新各司其职。解析产物应尽快入队，不能等一个下载任务完全结束后才生产下一个。

## 日志策略

- 日志文件保留策略由配置决定，默认保留 1 天，上限 7 天。
- 日志清理适合在应用初始化时执行一次；运行中不应频繁扫描历史日志。
- 日志中心的 UI 显示上限只影响前端展示，不影响日志文件本身。
- 复制、导出、Trace 诊断只操作当前筛选和当前选中上下文，不触发全量重读。

## 验收清单

1. 1000 条以上日志切换显示上限时，页面不无响应。
2. 下载队列、正在下载、已完成、失败列表不可见时不会重绘主表格。
3. 底部下载速度、已完成数、失败数仍能实时更新。
4. 进度洪峰下启动、停止、删除、重试等关键操作仍能及时响应。
5. 下载槽位释放后，等待队列会继续派发，不出现“完成几个后不再入队”的卡死。
6. WebSocket 慢客户端不会拖慢下载核心。

## 推荐验证

```bash
python -m pytest tests/test_frontend_event_aggregator.py tests/test_frontend_state_service.py tests/test_ui_update_scheduler.py -q
python -m pytest tests/test_download_manager.py tests/test_unified_frontend_contract.py -q
node --check app/web/static/app.js
```
