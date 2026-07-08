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
- 首次全量 snapshot 尚未返回时，后续高频刷新可能产生过期 worker 结果；过期结果不得渲染，但完整且版本不倒退的结果必须允许写入 `_cached_snapshot` 作为后续 delta 基线，避免 `use_delta` 长时间保持 `False`。
- 页面切换等显式可见页请求如果版本未变化，只允许补拉目标 section，不能因为 `changed_sections` 为空退回全量刷新。
- 下载队列、正在下载、已完成、失败列表只按 section delta 刷新。
- 视频普通操作（重排、删除、失败重试、暂停、元数据更新）必须传入 `videos.*` topic 触发局部刷新；不得使用 `force=True` 绕过 delta，除非是初始化、切换 `FrontendStateService`、主动清缓存或错误恢复。
- 大表格优先按 id 更新行，避免单个进度变化 reset 整表。
- 通用 snapshot 表格使用稳定 `id` 做行级 patch；尾部追加/移除必须使用 `rowsInserted` / `rowsRemoved`，只有乱序或中间结构变化才允许 `modelReset`。
- 日志中心使用有界缓存和增量 append；调整“UI 最大显示日志数量”时：
  - 小变大：只扩容缓存上限，不从日志文件一次性回填。
  - 大变小：直接裁掉内存中多余日志。
  - 当前不可见时不重建日志表。
- 日志文件 tail worker 负责读取、解析和写入本地缓存；读文件、解析或缓存异常只能记录为调试日志并保持 worker 存活，UI 热路径继续使用上一份快照或空快照。
- `refresh_file_log_cache()`、`FrontendLogCache.refresh_now()` 和 `wait_for_idle()` 只允许测试、维护动作或显式诊断使用；GUI/WebUI 热路径不得调用这些同步接口。
- 单次渲染超预算时应写 WARN，并降低刷新频率或缩小刷新范围。

## WebUI 刷新规则

- 初始连接和断线恢复使用 `frontend_state`。
- 稳定运行使用 `frontend_delta`。
- 浏览器端 reducer 合并 section；表格使用 keyed row patch。
- 进度、速度、日志类更新通过 `requestAnimationFrame` 批处理。
- 非当前页不重建 DOM，只更新必要角标和底部状态。
- WebSocket 每连接使用有界队列；noisy 消息可以合并或丢弃旧值，critical 消息不能被丢弃。
- WebSocket 出站消息的优先级判定、合并 key 和 JSON 编码不得阻塞事件循环；`frontend_delta`、`frontend_state` 等大 payload 必须先在 executor 中构建成 `OutboundMessage`，事件循环只负责入队和发送已编码文本。
- `/api/frontend/state`、`/api/frontend/delta` 和 WebSocket `frontend_delta` 的 snapshot/delta 构建必须离开 asyncio 事件循环，使用后台 executor 或等价 worker；事件循环只负责调度、发送和合并结果。
- WebSocket 首次连接的 `init_state`、`frontend_state`、`platforms`、`config` 和缓存视频回放也必须使用后台 executor 构建；大 snapshot 的 JSON 编码不得直接在事件循环线程执行。
- WebController 的异步 HTTP / WebSocket 动作入口不得在 asyncio 事件循环中直接执行同步 service 方法；配置写入、前端动作处理和其他可能触发文件、缓存、SQLite 或系统 API 的普通函数必须下沉到 executor 或等价 worker。
- Web 目录选择、目录扫描和本地文件枚举不得在 asyncio 事件循环中直接执行 `os.listdir()`、`os.path.exists()`、`os.path.isdir()` 等文件系统遍历；`/api/dir/list` 只能在路由中做参数校验和结果组装，实际目录枚举必须下沉到 executor 或等价 worker。
- Web 媒体预览和 Range 请求不得在 asyncio 事件循环中直接读取文件块；路径解析、大小和媒体类型判断必须下沉到 executor，Range body 使用同步 iterator 交给 ASGI 线程池消费，不得重新引入 `async def stream_range()` 包裹 `file.read()`。
- Web 媒体路径解析和异步重命名入口也不得在事件循环线程上调用 `os.path.exists()`。`get_media_path()` 只返回记录中的候选路径，真实存在性、大小、类型和重命名冲突检查统一交给 executor 中的 file service / path policy；404 或重命名失败由 worker 结果回传。
- Web debug 文件下载接口同样不能在 async route 中直接探测 `latest_debug.log` 或 `latest_error_summary.md`。REST router 必须调用 `WebFileResponseService` 的 async wrapper，legacy route 必须用 `run_in_executor` 包裹文件探测和 `FileResponse` 构造。
- WebSocket 尚未绑定运行中的事件循环时只能记录 dirty event 并等待后续异步 flush 或客户端主动拉取；不得在事件来源线程同步构建 `frontend_delta`。
- WebUI 日志中心筛选、排序、分页必须优先交给 `log_query_worker.js`；不得用“日志数量较少”作为主线程同步查询的理由。`queryLogsSync()` 只允许在浏览器不支持 Worker 或 worker 初始化/执行失败时作为降级路径。
- WebUI 日志 worker 不可用时，降级查询也必须通过 `scheduleLogQueryFallback()` 异步调度并按最新 `sequence` 生效；提交时必须冻结 `buildLogQueryRequest(...)` 快照，异步回调不得再临时读取当前过滤器、页码或可变日志数组；不得在 `renderLogs()` / `submitLogQuery()` 当前调用栈里直接同步执行过滤、排序和分页。
- WebUI 日志裁剪只允许发生在本地 append 或 delta 合并阶段；`renderLogs()` / `logQueryItems()` 不得再裁剪或改写 `frontendState.log_items`，避免渲染路径携带大数组副作用。
- WebUI 下载队列、已完成列表和失败列表不得把 `queue_items` / `completed_items` / `failed_items` 全量同步渲染到 DOM；分页、选中项跨页定位和当前页切片必须优先提交给 `list_page_worker.js`，主线程只接收 `pageItems` 并 patch 当前页。同步 `buildListPageResultSync()` 只允许作为 Worker 不可用的降级路径。

## UI / Worker / Cache / DB 职责边界

日志中心、失败列表和大表格遵循三层边界。后续改动如果跨过这些边界，必须同时补回归测试。

补充约束：
- GUI domain event 进入 EventBus 后不得直接执行可能触发弹窗、表格更新或状态重排的慢 handler；GUI 控制器应优先 `subscribe_async()`，并通过 `DesktopHostAdapter._queue_on_ui()` 把实际派发推迟到下一轮 Qt 事件循环，EventBus 发布栈只负责接收与排队。
- EventBus 提供 `subscribe_async()` 给不参与同步返回值的 handler 使用；`FrontendStateService` 与 MainWindow 都应走异步订阅，但必须保持“状态服务先入队、主窗口后调度刷新”的订阅顺序，避免刷新先于 dirty event 入队。
- `FrontendStateService.get_snapshot()` / `get_delta()` 在 flush pending AppState 事件前必须通过 `EventBus.wait_for_async_idle()` 等待异步交付完成；该等待基于条件变量和 inflight 计数，不允许用 `time.sleep()` 或 `processEvents()` 碰运气。`wait_for_async_idle()` 从 EventBus async worker 线程内被调用时必须立即返回 `False`，避免 self-call 死锁；超过 timeout 也必须返回 `False`，不得无限阻塞 flush。
- `FrontendStateService` 订阅 `app_state.changed` 时只能做有界入队；标题物化、section 推导、dirty version 记录必须在 `get_snapshot()` / `get_delta()` 入口统一 `flush_pending_app_state_events()` 后执行。初始化阶段产生的 AppState 事件需要在构造结束时合入基线版本，避免第一帧普通 delta 被误判成全量刷新。异步订阅不得在 handler 内做日志解析、快照构建、SQLite 查询或 UI 回调。
- EventBus 的高频异步 topic（如 `videos.update`、`videos.metadata`、`video_state_changed`、`task_progress`、`logs.append`、`log`）必须按 handler/topic/实体 ID 合并为 latest-state-wins；普通异步 topic 和 critical 事件仍保持 FIFO，不得为降压丢失完成、失败、删除、停止等关键状态。
- 生产代码不得引入定时 `processEvents()` pump；GUI 和 controller 热路径不得使用 `time.sleep()` 做协调等待，后台任务需要等待时优先使用 cancel token / event 的可取消等待；浏览器 E2E 不得用 3.5 秒固定等待兜底，必须等待 `#app-shell` 或页面可观测状态。
- 运行态纯视觉反馈定时器不得使用 45ms 级高频刷新；如启动按钮跑马灯这类非关键帧动画，默认周期为 120ms，并通过单次步进保持视觉速度。
- 应用退出必须按顺序释放 frontend state service、AppState 延迟通知和 CacheService/diskcache 句柄；GUI 控制器和 Web 会话控制器都必须执行这条链路，关闭失败只能降级记录调试日志，不得中断退出流程。AppState 只关闭自己创建的 CacheService，外部注入的缓存由组合根关闭。
- GUI latest-state-wins worker 应复用统一 worker 骨架；顺序写文件、系统动作派发等必须保序的任务应复用 `SequentialRequestWorker`，不得在业务 worker 中重复维护 `Condition + deque + Thread`。
- GUI 控制器层不得把 `FrontendStateService.get_snapshot()` 当作业务 fallback；需要队列 ID、状态集合或行数据时，只能读取已在内存中的 `AppState` / 控制器状态，完整 snapshot 构建必须交给 `FrontendSnapshotWorker`。
- GUI 热路径不得直接调用会触发文件、缓存、SQLite 或系统 API 的 `FrontendStateService.handle_action()`；日志操作、平台认证刷新、打开目录、失败重试、诊断复制、下载选项、已完成元数据更新、暂停下载、工具启动和文件关联注册必须提交到 `FrontendActionWorker`，完成后只回投轻量结果并触发目标 section 刷新。
- 日志中心的 `debug.log`、`error.md`、导出、清空与刷新等动作必须统一走 `FrontendActionWorker`；页面和控制器不得为了打开文件或检查路径存在性绕过 worker 直接访问文件系统或系统默认打开方式。
- GUI 热路径不得直接调用 `cfg.set()`、`cfg.set_many()` 或平台专用配置落盘方法；平台切换、主题同步、启动参数读取等交互只允许更新轻量 UI 状态或提交 `FrontendActionWorker`，配置持久化统一在 worker / service 层完成。
- GUI 主题切换不得冻结 `window_root`、隐藏 shell 父容器或触发完整 frontend snapshot；主题热加载默认只更新 Qt palette/QSS、shell theme 和设置页外观控件。需要抑制闪烁时，只允许短暂冻结已可见的 `app_shell`，并必须在 `finally` 恢复 `updatesEnabled`。
- GUI 主题按钮的图标状态不是主题切换完成信号。快速点击必须按 latest-state-wins 合并，busy 状态保持按钮可点击；完成时再统一同步图标、释放 busy，并检查 shell chrome 可见性。
- GUI shell 可见性恢复必须覆盖父级和子级：`window_root`、标题栏、`app_shell`、`control_island`、TopBar、Sidebar、PageStack、`status_island`、StatusBar。只恢复 TopBar/Sidebar/StatusBar 本体不能防止父容器隐藏或更新冻结导致的黑屏。
- 主题、媒体预览全屏和主窗口全屏是不同状态机。主题切换前后必须识别 stale media fullscreen；不能让媒体预览残留状态阻止主 shell 恢复。
- SQLite 热路径不得只写 `with sqlite3.connect(...)`；该上下文只处理事务，不关闭连接。必须使用 `contextlib.closing(sqlite3.connect(...))` 或等价显式关闭，避免 Windows 下缓存/失败记录库文件句柄泄露。
- 同一批稳定 ID 的表格行发生重排时，不得使用 `beginResetModel()`；应通过 row patch、insert/remove 或 `layoutChanged` 保留滚动、选中和悬停语义。
- 仍在使用 `QTableWidget` 的小型通用表格也必须遵守稳定 ID 更新：列结构不变且 ID 仅原位变化、尾部追加或尾部移除时，只更新受影响单元格，不得 `setRowCount(0)` 清空重建。
- 日志中心、平台筛选和其他页面初始化路径不得在无快照时访问插件注册表或做平台发现；页面只能消费 `settings_snapshot`、`platforms` 或内建静态元数据，真实平台发现由服务层或启动快照提供。
- GUI 四态列表（下载队列、正在下载、已完成、失败列表）的行归一化、选中项定位、分页切片和最近事件切片必须统一提交给 `ListPageWorker`；`build_list_page_result()` 只允许在 worker 内部和单元测试中使用，页面层不得按条数走同步快捷路径，也不得重新引入 `ASYNC_ITEM_THRESHOLD`。页面层只能接收 worker 返回的 batch 后 patch model。普通翻页不得被当前选中行拉回原页，只有显式 `select_id()` 才允许跨页定位选中项。

### UI Thread

UI 线程只负责显示和轻量交互：

- 接收后端或 worker 发来的当前页 batch。
- 四态列表页面不得直接调用 `build_list_page_result()`；即使只有 1 条记录，也必须走 `ListPageWorker`，避免小数据路径和大数据路径行为分叉。
- 批量 append / patch 到 Qt model 或 Web DOM。
- 更新选中态、按钮状态、分页状态和详情面板。
- 不读取日志文件。
- 不解析日志文本。
- 不执行大列表过滤、排序、分页。
- 不在选中行时同步规整日志详情、递归本地化或格式化大段 JSON。
- 不在日志页面层二次派生 `log_scope`、`event_stage` 或 `_scope_reason`；这些字段由 `LogQueryWorker` 随当前页 batch 一起产出。
- 不在日志页面层装饰 `source_display`、`platform_label`、`message_summary` 或执行日志本地化；这些展示字段必须由 `LogQueryWorker` 按当前语言和平台元数据随当前页 batch 一次性产出。
- 不同步构建完整 frontend snapshot，不做大段 JSON 签名 diff。
- 不在页面渲染前对日志快照做全量 tuple/list 克隆或逐行校验；GUI 日志页只传递快照 batch 引用，过滤、复制、排序、分页交给 `LogQueryWorker`。
- 不直接查询 SQLite、diskcache 或大体量本地缓存。
- 不直接写出日志详情等大 payload 文件；页面只选择路径和显示结果，文件写出交给 worker。
- 不在页面渲染路径探测图标或资源文件是否存在；平台/资源元数据进入页面前必须规整成可直接消费的字段，GUI 平台图标路径只按运行根路径计算，不能在 viewmodel/render 中做 `is_file()`。
- 不在页面层重复派生下载详情字段；正在下载详情的字段、分片文案和速度标签由 `frontend_video_adapter.active_item()` 预计算，GUI/WebUI 只消费 `detail_fields`、`chunk_progress_label` 和 `speed_trend_label`。

GUI 主窗口刷新时只向 `FrontendSnapshotWorker` 提交目标 section、当前快照引用和签名表，snapshot 构建、局部合并和 section diff 在 worker 中完成；GUI 日志页提交查询时只传递当前快照引用，行复制、筛选、排序和分页由 `LogQueryWorker` 完成；GUI 日志详情选中行后只提交当前行快照，字段派生、本地化、详情 JSON 格式化和 HTML 转义由 `LogDetailWorker` 完成，详情动作按钮必须等 worker 结果回来后再启用，不允许用 UI 线程 fallback 重新构建详情 payload；WebUI 日志查询由 `log_query_worker.js` 完成，主线程只接收 `pageItems` 并 patch 当前页。

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
- 后台写出日志详情导出文件，并把成功/失败结果回传 UI。

当前落地组件：

- `FrontendLogCache`：后台 tail 最新 debug 日志，增量解析，避免 snapshot 热路径直接读文件。
- `FrontendSnapshotWorker`：GUI snapshot 构建、局部合并和 section diff。
- `LogQueryWorker`：GUI 日志中心筛选、排序、分页、当前页展示字段装饰与日志本地化。
- `LogDetailWorker`：GUI 日志详情字段派生、本地化、JSON 格式化和 latest-state-wins 防抖。
- `LogDetailExportWorker`：GUI 日志详情文件导出，避免页面线程写大 payload。
- `ListPageWorker`：GUI 四态列表的行归一化、分页、选中项定位、最近事件切片和 id 索引。
- `log_query_worker.js`：WebUI 日志查询筛选、排序和分页。
- `list_page_worker.js`：WebUI 下载队列、已完成列表和失败列表的分页、当前页切片和选中项跨页定位。
- `WebDirectoryService` / `/api/dir/list`：Web 目录浏览路由只负责调度，目录存在性判断、枚举和子目录过滤在 executor 中完成。
- `FailedRecordStore`：失败记录后台写 SQLite，并刷新内存快照。

### Cache / DB

缓存和结构化存储按数据热度分工：

- `cachetools`：短 TTL 热数据，只放 UI 高频读取的小体量结果。
- `diskcache`：解析结果、本地 key-value 缓存和可重用中间结果。
- SQLite：失败记录、结构化查询、可分页和可索引的数据。

UI 热路径只能读取已经准备好的内存快照。维护脚本、测试或显式管理动作可以调用同步查询接口，但 GUI/WebUI 页面渲染链路不得直接查 SQLite 或重扫日志文件。

### 复盘补充：日志、失败页与缓存边界

这几轮排查证明，性能问题经常不是某个按钮或表格“看起来卡”，而是页面层重新承担了 worker / cache / DB 的职责。后续改动必须按下面的证据口径审查：

- 日志中心的数据来源是 `FrontendLogCache` 产出的内存快照，再交给 `LogQueryWorker` / `log_query_worker.js` 做过滤、排序、分页和展示字段投影。GUI/WebUI 页面不得直接 tail `latest_debug.log`、不得在页面层 split 时间戳、不得在表格绘制或选中回调里调用日志本地化正则。
- 失败列表的数据来源是失败记录快照或 `FailedRecordStore` 的结构化查询结果。失败页可以显示当前页 batch、详情和建议，但不得在 UI 线程从 SQLite 重查、不得从原始日志里二次解析失败时间、原因和日志片段。
- GUI/WebUI 页面层、controller 层不得直接调用 `FailedRecordStore.query_records()`、`records_snapshot()` 或构造 `FailedRecordQuery`；这些接口属于 service/worker/测试边界，页面只能消费已投影好的当前页 batch 和详情字段。该约束由 `test_failed_record_store_sqlite_queries_stay_out_of_ui_layers` 固化，避免失败页再次把 SQLite 查询塞回界面线程。
- 失败记录写入也必须按状态签名去重。`FrontendStateService` 可以在失败项标题、原因、Trace、平台、时间和日志片段变化时提交 `queue_upsert()`，但同一失败项的重复 snapshot 不得反复投递 SQLite worker；后台队列合并不是热路径去重的替代品。
- `classification_facts()`、`derive_log_scope()`、`derive_event_stage()`、`derive_scope_reason()` 属于日志语义规则树。单次 worker 查询内，同一行日志的分类事实必须只构造一次，并通过私有字段或查询上下文缓存复用；返回 UI 前不得暴露私有缓存字段。不得让筛选、计数、分页装饰和详情本地化各自重复跑整棵规则树。
- 日志 tail 缓存必须证明“读文件、解析、查缓存、写 diskcache”都在 worker / service 层完成。缓存 key 至少要区分日志文件路径、文件身份、大小或偏移、修改时间以及显示上限；仅创建 diskcache 目录或只在测试里 `persist=True` 不能算落地。
- 日志 tail 持久缓存只能保留当前日志流的有效解析 key；当文件大小、mtime 或身份变化生成新 tail key 后，旧 `frontend.file_log_cache.tail.*` key 必须清理，避免高频日志追加把 diskcache 变成无界历史堆积。
- diskcache 用于可复用解析结果和本地 key-value 中间结果；cachetools 用于短 TTL 热数据；SQLite 用于失败记录、结构化过滤、分页和统计。三者不能互相冒充：例如用 `frontend.file_log_cache.{limit}` 这类单一 key 覆盖多文件 tail，不满足多文件和轮转场景。
- `CacheService.set(..., persist=True)` 写 diskcache 失败时只能记录 `write_diskcache` 异常并降级写 SQLite；只有 diskcache 和 SQLite 都失败时才允许保持旧内存值并把异常返回调用方，不能让单个 diskcache 锁/损坏直接破坏 worker 缓存链路。
- SQLite 查询必须把平台、状态、时间范围、Trace ID、关键字、分页和统计尽量下推到 SQL。失败记录、日志索引或后续结构化表不允许长期只做 `SELECT *` 后在 UI / JS 里切片；分页应使用 `LIMIT/OFFSET` 或游标方案。
- 所有 SQLite 连接必须显式关闭；后台写入 worker 的 `_writing`、队列状态和 condition 通知必须在 `finally` 中恢复。异常捕获不能只覆盖 `OSError` / `sqlite3.Error`，否则 `TypeError`、数据形态错误或序列化错误会杀死 worker 并留下假忙状态。
- 媒体路径检查、播放进度 JSON 读写、MKV 修复缓存扫描和 metadata probe 都属于磁盘或外部进程热路径，不得在 UI 线程做 `read_text()`、`write_text()`、`glob()`、`unlink()`、`stat()` 或每次播放即时 probe；必须复用短任务 worker、有限线程池或服务层缓存，并提供 shutdown / cancel 边界。
- `MediaMetadataService.ensure_probe()` 不得为每个文件直接创建裸线程；必须走有界 executor，并在 `FrontendStateService.destroy()` 等拥有方生命周期内关闭。上层预算/队列只能削峰，不能替代服务自身的并发上限。
- 自动化测试不得用固定 sleep 证明异步链路稳定。WebUI 优先等待 `#app-shell`、指定行、按钮状态、worker 结果序号或详情字段；GUI 测试可以短轮询 Qt 事件，但每轮都要检查目标状态。新增等待策略必须写入测试或 guardrail，而不是靠“本机刚好够快”。
- 每个已经下沉到 worker / service 的边界都要有可执行约束：日志查询不能把 `classification_facts` 私有缓存字段交给 UI，失败记录 worker 必须在 `finally` 复位，播放位置和 MKV 修复缓存必须通过短任务 runner 执行。仅在文档里声明“异步化了”不算完成。
- 每次声称优化完成时，必须同时给出当前证据：目标代码路径、是否有 guardrail 防止回退、针对性测试、必要时的基线时长。没有覆盖证据的“已经异步化”“已经增量刷新”“diskcache 已落地”都按未完成处理。

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
python -m pytest tests/test_request_workers.py tests/test_frontend_snapshot_worker.py tests/test_log_query_worker.py tests/test_log_detail_worker.py tests/test_list_page_worker.py -q
python -m pytest tests/test_download_manager.py tests/test_unified_frontend_contract.py -q
node --check app/web/static/app.js
```

自动化用例不得使用固定 3.5 秒等待兜底；WebUI 优先等待 `#app-shell`、行数、选中 ID、详情文本和按钮状态等可观测状态，GUI/Qt 测试可以短轮询处理事件，但每轮都必须检查目标状态，不能只靠时间推进。

### 当前验证基线

- 2026-07-09 全量 `python -m pytest -q`：`2188 passed, 3 skipped, 7 warnings in 181.09s (0:03:01)`。
- 近期连续基线为 `2141 -> 2145 -> 2149 -> 2151 -> 2154 -> 2188`；耗时从 `208s -> 190s -> 117s -> 187s -> 237s -> 181s` 波动，当前实测约 3 分 1 秒。后续比较优化收益时优先记录精确秒数，不再只写“3 到 4 分钟”。
- 后续若新增 GUI/WebUI 热路径改动导致全量测试明显回退，必须先排查是否引入同步文件/SQLite/大列表重建、固定 sleep、`processEvents()` pump 或 `use_delta=False` 的非必要回退。

## GUI use_delta 判定边界

`FrontendSnapshotRequest.use_delta=False` 只允许出现在以下场景：

1. 首次启动或尚未收到任何可用 `_cached_snapshot`。
2. `mock=True` 的演示快照。
3. 明确 `force=True` 的人工强制刷新、服务切换或恢复路径。

普通运行态事件，例如 `videos.update`、`logs.append`、`videos.metadata`、`videos.terminal`、`settings.update`，只要已经有 `_cached_snapshot`，必须提交 `use_delta=True`，并由 `FrontendSnapshotWorker` 优先调用 `FrontendStateService.get_delta(base_version, sections=...)`。只有服务端返回 `full=True` 或显式 section 不在 delta 返回体中时，才允许补拉目标 section；不得因为高频事件回退到全量 `get_snapshot()`。

## EventBus 异步订阅边界

- `MainWindow` 订阅 `app_state.changed` 必须优先使用 `EventBus.subscribe_async()`，只把事件投递回 Qt 队列，不在发布线程执行刷新调度。
- `app_state.changed` 属于高频异步主题；当 payload 携带 `video_id`、`id`、`entity_id` 或 `trace_id` 时，EventBus 必须按 handler/topic/entity 采用 latest-state-wins 合并，避免进度事件在异步队列中堆积。
- `logs.append` 这类只有 topic/count、没有实体 ID 的高频事件必须按 handler/topic 做 latest-state-wins 合并；不得因为缺少实体 ID 退回 FIFO，把日志追加重新堆到 UI 刷新链路里。
- `EventBus.wait_for_async_idle()` 只用于外部 flush/ack；如果在 EventBus async worker 线程内被调用，必须短路返回 `False`，避免 handler 等待自己完成形成死锁。等待 deadline 到期也必须返回 `False`，调用方只能降级继续或记录调试信息，不得无限阻塞 UI / Web 响应。
- `spider.domain_event` 和 `download.domain_event` 的订阅 handler 必须优先使用 `subscribe_async()`，且只能通过 `DesktopHostAdapter._queue_on_ui()` 投递事件；即使事件来自非 GUI 线程，也不得在 EventBus 发布线程直接执行 `_dispatch_spider_event()` 或 `_dispatch_download_event()`，也不得用无 receiver 的 `QTimer.singleShot()` 或只判断当前线程的 `_run_on_ui()` 作为跨线程桥。
- `FrontendStateService` 对 `app_state.changed` 使用 `subscribe_async()`，并通过 `flush_pending_app_state_events()` + `wait_for_async_idle()` 保证下一次 `get_snapshot()` / `get_delta()` 先合入一致的 dirty version。不得绕过这条 flush/ack 契约直接读取旧状态，也不得在异步 handler 内构建快照。
- 新增 GUI 热路径订阅时，默认先判断是否能异步；只有直接影响版本一致性、关键事务顺序或必须同步返回结果的 handler 才允许保留同步。

## 后台 Worker 守护边界

- `LatestRequestWorker` 和 `SequentialRequestWorker` 是 GUI 异步化的通用底座；业务处理函数抛异常时只能记录到 `debug_logger` 并继续消费后续请求，不得让 worker 线程静默退出。
- `LatestRequestWorker` 是真正的 latest-state-wins：如果某个请求处理期间已经收到更新请求，旧请求即使成功产出结果也不得触发结果回调；页面层的 `sequence` 校验仍保留作为最后一道防线。
- worker 的结果回调如果遇到普通异常，同样只记录并继续；只有 Qt 对象销毁等 `RuntimeError` 代表生命周期结束时才允许停止 worker。
- 新增 GUI 后台任务时优先复用这两个 worker；只有需要独立调度协议、独立队列背压或跨进程执行时才允许新增专用线程结构。
- 非常驻 GUI 后台任务必须按需创建，不得在主窗口构造期预启动；否则测试和页面重建会堆积空闲线程，增加 Qt 退出和重建时的崩溃风险。检查更新、诊断、文件关联注册等低频动作应在用户触发后创建或提交到既有 worker，并在 `closeEvent` 中回收。
