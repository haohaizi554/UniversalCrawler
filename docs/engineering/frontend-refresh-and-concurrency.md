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

## WebUI JavaScript 组合与生命周期

`app/web/static/app.js` 只负责共享状态和应用组合：它拥有唯一 `frontendState`、跨页面选择、AppContext、启动/导航/顶栏/状态栏/工具箱编排，以及旧 HTML 入口所需的薄包装。日志翻译表、四态列表分页、日志 worker/详情、设置控制、弹窗实现、媒体事件和 WebSocket 生命周期不再由 `app.js` 实现。

七个职责模块在 `app.js` 之前以同一 cache version 加载，并分别暴露冻结 namespace：

| 文件 | namespace | 资源与职责所有权 |
| --- | --- | --- |
| `log_i18n.js` | `UcpLogI18n` | 纯日志本地化映射与转换；不读取 DOM、文件或网络 |
| `frontend_runtime.js` | `UcpFrontendRuntime` | snapshot/delta、WebSocket、重连 timer、渲染帧与页面退出清理 |
| `list_pages.js` | `UcpListPages` | `list_page_worker.js`、四态分页、选择、当前页 row patch |
| `log_center.js` | `UcpLogCenter` | query/detail worker、fallback timer、筛选、分页、详情与导出 |
| `settings_controller.js` | `UcpSettingsController` | 设置分组、认证刷新、热更新、代理选择/输入 |
| `dialog_controller.js` | `UcpDialogController` | 三类弹窗、焦点与 Enter/Escape 生命周期 |
| `playback_controller.js` | `UcpPlaybackController` | 预览请求、media listener、自动播放/切换 timer、全屏 |

控制器统一通过 `configure(options)` 注入 `getState()`、翻译、DOM、transport、action、patch 和 render callback。模块不得缓存整份 `frontendState`，只能在需要时调用 `getState()`；共享状态变更必须回到注入 callback。每个模块只释放自己创建的 worker/socket/timer/listener，`dispose()` 必须幂等；`UcpFrontendRuntime.dispose()` 负责页面退出时协调一次全模块释放。

浏览器自动化必须用 selector、事件或可观测状态作为完成条件，例如 `#app-shell` visible、`#page-<id>.active` visible、worker sequence/result、行数、详情文本或按钮状态。禁止用固定 sleep/`wait_for_timeout()` 证明加载、导航或异步 worker 已完成；需要测试模块自身行为时先隔离 live runtime/WebSocket，避免测试 fixture 与真实 state/delta 竞争。

## 前端测试与样式责任边界

大型前端测试按资源成本选择不同的组合方式：

- `tests/e2e/web/test_browser_journeys.py` 是唯一可收集的 Playwright 聚合入口。`tests/support/browser_cases/` 只保存不继承 `TestCase` 的责任 mixin，`tests/support/browser_runtime.py` 只拥有一套 uvicorn、Playwright、Chromium context 和 page 生命周期。新增浏览器领域测试不得自行启动第二套服务或浏览器。
- 统一 GUI/WebUI 契约使用显式领域模块：shell、settings、i18n/logs、task pages、static。它们共享 `unified_frontend_contract_support.py` 的 QApplication、等待和清理基础设施，但不通过聚合入口重新导出测试类，避免 pytest 重复收集。
- 测试拆分验收必须比较原 `test_*` 方法集合，不能只看总数；新增架构守卫会合法增加测试数量，但原方法缺失或重复均视为失败。
- 浏览器 case 文件不得以 `test_` 命名，support 模块不得定义测试方法。测试责任模块硬上限 1500 行，超过上限必须继续按变化原因拆分。

WebUI CSS 不使用构建器或 `@import`，由 `index.html` 按固定顺序显式加载：

1. `app.css`：设计令牌、基础控件和应用壳层。
2. `log_layout.css`：日志双栏、检查器和页面表格壳层。
3. `task_pages.css`：共享表格交互、已完成页、失败页和任务操作。
4. `task_runtime.css`：正在下载详情、时间线、趋势、分页和运行态控制。
5. `media_logs.css`：预览、播放器、媒体控制与日志筛选列。
6. `settings.css`：设置布局、平台表格、代理和外观控件。
7. `overlays_responsive.css`：状态栏后置覆盖、弹窗、选择窗口和响应式规则。

CSS link 顺序本身是公共契约。静态测试必须从 `index.html` 解析实际 link 顺序后构建 bundle，不能硬编码只读 `app.css`。打包虽通过 `portable.spec` 递归收录静态目录，`build_installer.py` 仍必须逐项验证七个样式表，避免源码存在而安装源缺失。每个 CSS 文件硬上限 1000 行；拆分时先证明按 link 顺序拼接后的内容哈希与拆分前一致，再做任何视觉重构。

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

GUI 主窗口刷新时只向 `FrontendSnapshotWorker` 提交目标 section、当前快照引用和签名表，snapshot 构建、局部合并和 section diff 在 worker 中完成；GUI 日志页提交查询时只传递当前快照引用，行复制、筛选、排序和分页由 `LogQueryWorker` 完成；GUI 日志详情选中行后只提交当前行快照，字段派生、本地化、详情 JSON 格式化和 HTML 转义由 `LogDetailWorker` 完成，详情动作按钮必须等 worker 结果回来后再启用，不允许用 UI 线程 fallback 重新构建详情 payload；WebUI 日志查询由 `log_query_worker.js` 完成，日志详情 payload 解析、本地化和 JSON 文本构建由 `log_detail_worker.js` 完成，主线程只接收 `pageItems` / `detailResult` 并 patch 当前页与详情卡片。

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
- `FrontendSnapshotWorker`：GUI snapshot 构建、局部合并、section diff，以及 AppShell 四态列表 ID 到行号索引的物化。
- `LogQueryWorker`：GUI 日志中心筛选、排序、分页、当前页展示字段装饰与日志本地化。
- `LogDetailWorker`：GUI 日志详情字段派生、本地化、JSON 格式化和 latest-state-wins 防抖。
- `LogDetailWorker` 日志详情缓存：同一日志行、语言和平台元数据的详情解析结果先查共享 `CacheService`，miss 后在 worker 内计算并以 `persist=True` 写入 diskcache/SQLite fallback；UI 线程只接收 `LogDetailResult`。
- `LogDetailExportWorker`：GUI 日志详情文件导出，避免页面线程写大 payload。
- `ListPageWorker`：GUI 四态列表的行归一化、分页、选中项定位、最近事件切片和 id 索引。
- `log_query_worker.js`：WebUI 日志查询筛选、排序和分页。
- `log_detail_worker.js`：WebUI 日志详情 payload 解析、本地化、JSON 格式化、复制/导出文本预构建和 latest-state-wins 序号过滤。
- `list_page_worker.js`：WebUI 下载队列、已完成列表和失败列表的分页、当前页切片和选中项跨页定位。
- `WebDirectoryService` / `/api/dir/list`：Web 目录浏览路由只负责调度，目录存在性判断、枚举和子目录过滤在 executor 中完成。
- `FailedRecordStore`：失败记录后台写 SQLite，并刷新内存快照。
- `ShortTaskRunner`：GUI 控制器短任务统一入口，删除、重命名、播放文件探测、清空队列等动作不得再临时创建裸线程。
- `MediaMetadataService`：本地媒体信息探测使用有界 executor，并由拥有方生命周期统一 shutdown。

### Cache / DB

缓存和结构化存储按数据热度分工：

- `cachetools`：短 TTL 热数据，只放 UI 高频读取的小体量结果。
- `diskcache`：解析结果、本地 key-value 缓存和可重用中间结果。
- SQLite：失败记录、结构化查询、可分页和可索引的数据。
- `ParserCache`：仅缓存纯结构化 parser 投影，例如 Bilibili 视频信息/播放流、Kuaishou 候选 ID、MissAV 候选分组；不得缓存带运行态 ID、线程句柄、浏览器对象或信号的 `VideoItem` / spider 实例。

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
- spider/parser 层的可复用解析结果必须通过 `app.spiders.parser_cache.cached_parser_result()` 落到 `CacheService.set(..., persist=True)`；缓存 key 必须包含 parser namespace 和输入 payload 摘要，缓存异常只能记录 `ParserCache` 调试日志并回退到原始解析函数，不能改变平台解析异常语义。
- `CacheService.set(..., persist=True)` 写 diskcache 失败时只能记录 `write_diskcache` 异常并降级写 SQLite；只有 diskcache 和 SQLite 都失败时才允许保持旧内存值并把异常返回调用方，不能让单个 diskcache 锁/损坏直接破坏 worker 缓存链路。
- `CacheService.delete()` 同样属于降级边界；diskcache 或 SQLite 删除失败只能记录 `delete_diskcache` / `delete_sqlite`，不得把缓存清理失败冒泡到 UI、worker 或退出链路。
- SQLite 查询必须把平台、状态、时间范围、Trace ID、关键字、分页和统计尽量下推到 SQL。失败记录、日志索引或后续结构化表不允许长期只做 `SELECT *` 后在 UI / JS 里切片；分页应使用 `LIMIT/OFFSET` 或游标方案。
- 所有 SQLite 连接必须显式关闭；后台写入 worker 的 `_writing`、队列状态和 condition 通知必须在 `finally` 中恢复。异常捕获不能只覆盖 `OSError` / `sqlite3.Error`，否则 `TypeError`、数据形态错误或序列化错误会杀死 worker 并留下假忙状态。
- 媒体路径检查、播放进度 JSON 读写、MKV 修复缓存扫描和 metadata probe 都属于磁盘或外部进程热路径，不得在 UI 线程做 `read_text()`、`write_text()`、`glob()`、`unlink()`、`stat()` 或每次播放即时 probe；必须复用短任务 worker、有限线程池或服务层缓存，并提供 shutdown / cancel 边界。
- `MediaMetadataService.ensure_probe()` 不得为每个文件直接创建裸线程；必须走有界 executor，并在 `FrontendStateService.destroy()` 等拥有方生命周期内关闭。上层预算/队列只能削峰，不能替代服务自身的并发上限。
- 自动化测试不得用固定 sleep 证明异步链路稳定。WebUI 优先等待 `#app-shell`、指定行、按钮状态、worker 结果序号或详情字段；GUI 测试可以短轮询 Qt 事件，但每轮都要检查目标状态。新增等待策略必须写入测试或 guardrail，而不是靠“本机刚好够快”。
- WebUI 日志详情测试在指定 `selectedId` 后必须等待 `logDetailState.pending === false` 且 `detailResult.itemId` 与选中行一致；不得只等表格行渲染后立刻复制/导出，否则会把 worker 异步化误判成偶发失败。
- 新增 Web worker 后必须同步入口 cache bust、静态 bundle 断言和 `packaging/build_installer.py` 的随包文件校验清单；`portable.spec` 整目录打包不等于 installer 校验已覆盖。
- 每个已经下沉到 worker / service 的边界都要有可执行约束：日志查询不能把 `classification_facts` 私有缓存字段交给 UI，失败记录 worker 必须在 `finally` 复位，播放位置和 MKV 修复缓存必须通过短任务 runner 执行。仅在文档里声明“异步化了”不算完成。
- 每次声称优化完成时，必须同时给出当前证据：目标代码路径、是否有 guardrail 防止回退、针对性测试、必要时的基线时长。没有覆盖证据的“已经异步化”“已经增量刷新”“diskcache 已落地”都按未完成处理。

### 2026-07-09 当前审查证据

- AppShell 四态列表索引不再由 `AppShell.render()` 在 GUI 线程扫描四个列表生成；`FrontendSnapshotWorker` 会在 snapshot/delta 合并完成后产出 `FrontendSnapshotResult.page_item_rows` 与 `completed_item_ids`，`MainWindow._on_frontend_snapshot_finished()` 只负责传递，`AppShell._apply_worker_page_item_indexes()` 只消费 worker 结果。兼容 fallback 仅保留给直接调用 `render()` 的旧测试和降级路径，不得作为运行态主路径。对应 guardrail 为 `tests/unit/app/core/guardrails/test_runtime_policies.py::UIAsyncGuardrailTests::test_frontend_snapshot_worker_materializes_page_indexes_for_app_shell`，行为测试为 `tests/unit/app/ui/viewmodels/test_frontend_snapshot_worker.py::FrontendSnapshotWorkerTests::test_build_frontend_snapshot_materializes_page_item_indexes_off_ui_thread`。
- 失败页展示字段由前端中立的 `shared/failed_page_projection.py` 生成，并通过 `FailedPage._submit_page_request()` 提交给 `ListPageWorker`；页面层只接收 `ListPageResult` 后渲染当前页和详情，不在 UI 线程重跑日志本地化正则。`shared/localization.py`、`shared/log_i18n.py` 和 `shared/i18n_catalogs.py` 是 GUI/Web/service 共用的唯一实现；`app/ui/` 下不保留同名兼容模块，所有调用方必须直接从 `shared` 导入，服务层不得反向依赖 GUI 表示层。
- `EventBus.wait_for_async_idle()` 已覆盖两条关键路径：在 async worker 线程内调用必须立即返回 `False`，handler 超过 deadline 时也返回 `False`。对应测试位于 `tests/unit/app/core/test_event_bus.py`。
- `FrontendLogCache` 的 tail key 已包含日志路径、文件身份、大小、mtime 和显示上限；tail 缓存使用 `persist=True` 写入 diskcache，并在文件变化时清理旧 `frontend.file_log_cache.tail.*` key。对应测试位于 `tests/unit/app/services/test_frontend_log_cache.py`。
- `FrontendLogCache` 的缓存读写失败必须降级为 debug 日志并继续使用本次 source/tail 解析结果更新内存快照；缓存层异常不允许让 GUI/WebUI snapshot 热路径失去可用 batch。对应测试为 `tests/unit/app/services/test_frontend_log_cache.py::test_log_cache_read_failure_downgrades_to_source_read` 和 `tests/unit/app/services/test_frontend_log_cache.py::test_log_cache_write_failure_keeps_worker_batch_in_memory`。
- `FailedRecordStore` 的 SQLite 连接使用 `contextlib.closing()`，worker 循环用 `except Exception` 降级记录，并在 `finally` 中复位 `_writing/_refreshing`；结构化查询支持平台、状态、Trace、关键字、时间范围、排序和 `LIMIT/OFFSET`。
- `FailedRecordStore` 不是只写库：`FrontendStateService` 初始化时必须注册 refresh callback 并请求 worker 刷新失败记录内存快照；失败列表没有 live 失败项时，只能消费 `records_snapshot()` 的内存副本，不能在 GUI/WebUI 页面层同步 `query()` / `query_records()` SQLite。`failed_records.refresh` 只标脏 `failed_items` 与 `app_status`，避免把失败页恢复做成全量 snapshot。
- `FrontendStateService` 读取失败记录快照时必须容错降级：`records_snapshot()` / `snapshot_total_count` 异常只能写入 debug 日志并回退为空快照或当前 fallback 计数，不能把存储层异常传播到 GUI/WebUI 热路径。
- `FrontendStateService` 的下载运行态选项不得在每次 snapshot/delta 构建时直接读 `CacheService`。`download.auto_retry` 只允许初始化时读取一次，之后 `download_options` 与设置快照走服务内存态；用户显式更新下载选项时再同步内存态和 `cache_service.set(..., persist=False)`。对应测试为 `tests/unit/app/services/test_frontend_state_service.py::FrontendStateServiceTests::test_download_options_snapshot_uses_runtime_memory_without_cache_reads`。
- `PlaybackPositionService` 本体仍然是同步 JSON + 文件 metadata 服务，不能直接从 UI 调用；GUI 入口必须经 `MediaPreviewPanel._playback_position_task_runner` 的 `restore/save/delete/clear` 包装。对应 guardrail 为 `test_media_preview_disk_backed_state_uses_short_task_runners`，行为测试为 `test_playback_position_restore_runs_off_ui_thread`。
- `MkvPlaybackRepairService.cached_playable_path()` 会访问文件 metadata 和修复缓存，不能在 `play_video()` 当前调用栈内同步执行；GUI 入口必须经 `_submit_cached_playable_path_lookup()` 和 `sig_cached_playable_path_ready` 回投。对应 guardrail 为 `test_media_preview_play_video_uses_async_repair_cache_lookup`，行为测试为 `test_cached_playable_path_lookup_runs_off_ui_thread`。
- `CacheService` 的 `persist=True` 语义是“优先 diskcache，失败后降级 SQLite”，不是只创建 diskcache 目录；后续审查不得只看目录是否存在，也要看调用点是否用 `persist=True`、key 是否携带文件身份，以及失败路径是否记录 `write_diskcache` 后继续 SQLite fallback。
- `FrontendLogCache.wait_for_idle()` 和 `FailedRecordStore.flush()` 内部的短轮询只允许在测试、维护或显式诊断边界使用；GUI/WebUI 热路径已有 guardrail 禁止调用这些同步接口。后续新增页面逻辑时，不能把这些方法当成“异步结果等一下”的通用方案。
- 播放位置 JSON、MKV 修复缓存、播放文件存在性探测和清空下载队列均应复用短任务 runner；不得为单个控制器动作新增裸 `threading.Thread`。
- `MediaMetadataService.ensure_probe()` 使用 `ThreadPoolExecutor(max_workers=...)` 控制外部进程/文件 probe 并支持 shutdown，不能退回每个文件创建一个线程。
- `LogDetailWorker` 已接入共享 `CacheService`，日志详情 payload、本地化字段和 JSON 文本的解析结果在 worker 中复用，并以 `persist=True` 写入本地缓存；`MainWindow.set_frontend_state_service()` 负责把组合根的 cache service 注入 `AppShell -> LogCenterPage -> LogDetailWorker`，页面层不直接查缓存。
- Web / GUI 信号桥接必须做能力探测：测试桥、轻量 controller 或 Web 选择桥可能只暴露部分 handler，绑定 `sig_items_found`、`sig_progress`、`sig_error` 等信号时必须先确认目标回调可调用，不能假设所有入口都存在。
- `LongTaskRunner` 会向 worker 注入 `cancel_token`；任何交给它执行的 worker 函数都必须接受 keyword-only `cancel_token` 并把它合入已有取消事件。否则异常只会在线程执行时暴露，容易绕过静态检查。
- 播放预览的自动修复不得抢跑缓存命中：播放器报错触发 repair 前，若同一路径的 cached playable lookup 仍在途，应先挂起 repair，待缓存结果回来后再决定复用缓存或继续修复。
- 日志详情、失败页详情等嵌套滚动区在内容替换后要等 relayout 完成再复位滚动条；只在写入内容前 `setValue(0)` 会被后续布局计算覆盖，导致详情面板看似随机停在中段。
- WebUI `/api/frontend/state`、`/api/frontend/delta`、WebSocket 初始化和 REST getter 通过 executor 构建 snapshot/delta；事件循环只负责调度、发送和合并已编码消息。
- 同快照视觉验收使用 `scripts/capture_frontend_visual_matrix.py` 覆盖 GUI/WebUI 共 20 个场景，包括四态列表、日志、设置、工具箱、主题、窄视口状态栏和长标题；矩阵脚本除截图外还断言关键控件可见、无截断、无页面级横向溢出，并等待 worker/页面 ready 状态后再取证。
- 运行态压力基线包含两条独立证据：GUI 对失败页和侧栏执行 140 次真实快速点击后不得出现额外可见顶层窗口；Web 日志中心输入 1200 条日志、显示窗口限制为 500 条、快速导航 90 次后必须停留在第 25/25 页且 DOM 仅保留当前 20 行。压力测试不得用固定 sleep 代替可观测状态等待。
- Web 日志详情 worker 构造失败时只能进入可读降级态：保留当前摘要、禁用复制/导出并提供重试，浏览器主线程不得接管原始日志解析。设置事务、主题切换和更新检查均采用 latest-result-wins 或事务回滚，失败响应不得留下半应用运行态。
- 异步 worker 负责分页、筛选和大批量 display projection，但不应接管已经驻留在浏览器内存中的即时交互反馈。行选择、选中样式和当前详情必须在事件处理栈内同步对齐，再提交 worker 计算后续页；否则模型中的 `selectedId`、DOM 高亮和详情面板会在 worker 返回前短暂指向三个不同对象。对应回归必须使用延迟返回的 fake worker 证明：即使 worker 暂未响应，选中行和详情也已经一致。
- 浏览器测试服务“端口已监听”不等于应用已经可用。测试夹具必须轮询 `/api/ping` 等应用级健康端点，并同时检查子进程是否提前退出；只有健康检查成功后才能创建页面。禁止用固定 sleep 掩盖 ASGI lifespan、路由注册或缓存初始化竞态。
- CSS 的 `[hidden]` 必须保持不可见这一语义不变量，响应式规则不得用更高优先级的 `display` 意外复活隐藏页面或弹层。表格、导航、筛选栏和双控件行还必须显式处理 flex/grid 的 min-content 边界，通过 `min-width: 0`、稳定 track、允许换行或省略策略避免长语言、长路径和窄视口把相邻区域顶出容器。视觉矩阵除截图外必须校验 bounding box、页面横向溢出和隐藏元素可见性。
- 拆分后的 Web 静态模块共享同一个 cache-bust 版本。任何会改变运行时行为的 JS 修改都必须同步更新 `index.html` 中所有职责模块的版本戳，并由静态契约测试锁定；只更新入口文件会让浏览器混用新组合根和旧职责模块，形成难以复现的状态竞态。
- Playwright 责任模块拆分后仍只允许一个聚合入口和一套服务/浏览器生命周期。测试等待必须绑定 selector、选中 ID、详情 projection、worker sequence 或健康端点；文件尺寸治理不能通过复制 fixture、重复启动服务或恢复固定等待来换取表面上的小文件。

## 入口审计表

| 入口 | 数据来源 | 线程归属 | 禁止回退项 | 当前证据 |
| --- | --- | --- | --- | --- |
| GUI 日志中心 | `FrontendLogCache` 内存快照 + `LogQueryWorker` 当前页投影 | UI 只提交请求和渲染 batch；筛选、排序、分页、本地化在 worker | UI 层读日志文件、`localize_log_text`、`classification_facts`、同步缓存刷新 | `test_log_center_page_does_not_classify_logs_on_ui_thread`、`test_ui_and_web_hot_paths_do_not_call_synchronous_log_refresh` |
| GUI 失败列表 | live 失败项或 `FailedRecordStore.records_snapshot()` 内存副本 + `ListPageWorker` | UI 只消费失败页 display rows；SQLite 查询和失败日志投影留在 service/worker | 页面层 `query_records()`、日志时间 split、失败原因本地化正则 | `test_failed_page_uses_worker_display_projection_for_dynamic_logs`、`test_failed_record_store_sqlite_queries_stay_out_of_ui_layers` |
| GUI 四态列表 | `FrontendSnapshotWorker` 合并后的 section 与 `ListPageWorker` 分页结果 | UI 接收 page batch 后 patch model；索引、分页、选中项跨页定位在 worker | `page_slice()`、`page_for_item()`、`build_list_page_result()` 同步快捷路径 | `test_four_state_gui_pages_use_list_page_worker_batches`、`test_frontend_snapshot_worker_materializes_page_indexes_for_app_shell` |
| GUI 播放/预览 | `MediaPreviewPanel` 短任务 runner、`MkvPlaybackRepairService`、`PlaybackPositionService` | UI 只触发异步任务并接收结果信号；磁盘状态读写在 runner | UI 线程 `read_text()`、`write_text()`、`stat()`、同步 `cached_playable_path()`、控制器入口直接文件探测 | `test_media_preview_disk_backed_state_uses_short_task_runners`、`test_media_preview_play_video_uses_async_repair_cache_lookup`、`test_controller_media_entrypoints_do_not_probe_files_inline` |
| GUI 设置/弹窗 | `FrontendActionWorker`、配置服务和运行态内存态 | UI 只提交设置动作；配置持久化和系统 API 调用在 worker | UI 直接 `cfg.set()`、文件关联注册、同步系统调用 | `test_main_window_slow_frontend_actions_use_worker`、`test_gui_hot_paths_do_not_persist_config_inline` |
| Web `/api/frontend/state` | `WebController.get_frontend_state()` | FastAPI 事件循环只 `await run_in_executor`，snapshot 构建在线程池 | 事件循环直接 `controller.get_frontend_state()` | `test_web_frontend_routes_do_not_build_snapshots_on_event_loop`、`test_web_bootstrap_and_rest_getters_use_worker_executor` |
| Web `/api/frontend/delta` | `WebController.get_frontend_delta()` | FastAPI 事件循环只调度 executor 并返回 delta | 事件循环直接调用 delta getter 或 JSON 编码大 payload | `test_web_frontend_routes_do_not_build_snapshots_on_event_loop`、`test_websocket_transport_encodes_outbound_messages_off_loop` |
| WebSocket `frontend_action` | controller async action 或同步 action 的 executor 包装 | 事件循环只做参数校验、发送结果和调度 delta | 同步 action、配置写入、snapshot/delta getter 直接跑在事件循环 | `test_web_controller_sync_api_work_runs_in_executor`、`test_websocket_dispatcher_config_mutations_use_worker_executor` |
| Web 爬取控制 | `/api/crawl/stop`、REST router 和 WebSocket `stop_crawl` | 事件循环只提交停止动作到 executor；停止内部仍复用 controller/service 语义 | 事件循环直接 `controller.stop_crawl()` 阻塞或触发同步状态重建 | `test_web_stop_crawl_handlers_use_worker_executor`、`test_crawl_stop_when_idle`、`test_crawl_start_stop_lifecycle` |
| Web 媒体文件 | `WebFileResponseService` 和 session/controller 内存态路径映射 | `server.py` / `rest_router.py` 只委托统一文件响应服务；文件 stat、路径校验和 Range 流在服务边界 | `server.py` 重复定义 `_media_file_info()`、`_iter_file_range()` 或直接构造 `StreamingResponse` | `test_web_media_range_streaming_does_not_read_files_on_event_loop`、`MediaEndpointTests` |
| Web 日志中心 | `log_query_worker.js`、`log_detail_worker.js` | 浏览器主线程提交 worker 请求并 patch 当前页/详情 | 主线程全量筛选、排序、详情 JSON 构建 | `tests/e2e/web/test_browser_journeys.py` 日志 worker 相关断言、`tests/contract/frontend/` 静态 bundle 断言 |
| Spider/parser 解析缓存 | `ParserCache` + `CacheService` 持久缓存 | Spider/worker 线程执行纯解析和缓存读写；UI/Web 只消费解析后的任务/列表 | 缓存 `VideoItem` 运行态对象、缓存异常改变 parser 异常语义、只在测试里 `persist=True` | `test_spider_parser_cache_persists_structured_results`、`test_cache_service_delete_failures_are_downgraded` |

## 下载并发规则

- 普通并发默认 3，推荐选项为 1、3、5。
- 并发数是运行态最大同时下载任务数，应动态生效；释放槽位后必须继续派发等待队列。
- 图片资源可以走独立快速通道，但也必须有上限。当前建议图片快速通道最多 10 个同时任务。
- 下载派发信号量必须在 `finally` 路径释放，失败和取消也不能泄漏槽位。
- 解析、队列、下载、日志和前端刷新各司其职。解析产物应尽快入队，不能等一个下载任务完全结束后才生产下一个。

## 下载恢复与启动 I/O 规则

- `DownloadManager` 构造器不得读取、遍历或清理用户下载目录；启动维护只能在独立 worker 中执行，GUI 事件循环不得等待文件系统操作。
- dispatcher 可以通过事件门闩等待启动维护结束，但门闩必须在 `finally` 中释放；维护日志本身失败也不能锁死下载调度。
- worker 创建前必须把精确保存目录持久化到 `DownloadRecoveryStore`。账本提交失败时任务必须失败关闭，不能继续产生无主临时文件。
- 保存目录解析由 `resolve_task_save_directory()` 统一负责，dispatcher 和 worker 不得各维护一套合集/图集子目录规则。
- 成功任务立即删除 active 行；失败或中断任务原子移交到按目录去重的待清理队列。恢复记录不使用 TTL，也不保留已结案历史。
- 启动维护对账本目录逐个做浅层白名单清理，完成一次尝试后立即消费记录；路径不存在、没有命中或删除失败都视为“已使用”，不得无限重试和积累。
- 旧版本遗留扫描只能递归两层，使用 SQLite 持久化扫描前沿并按启动预算续跑。禁止重新引入 `os.walk()`、`rglob('*')` 或并行全盘扫描普通下载根。
- M3U8 递归只允许发生在下载器明确拥有的工作目录中，不能把 HLS 的特殊边界扩散到普通文件清理。
- 冻结态和开发态配置根不同；所有启动性能验收都必须覆盖 `%LOCALAPPDATA%` 中已有真实配置以及超大用户目录。

详细根因和恢复状态机见 [打包态启动未响应复盘](../postmortems/packaged-startup-recursive-sweep-freeze.md)。

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
python -m pytest tests/unit/app/services/test_frontend_event_aggregator.py tests/unit/app/services/test_frontend_state_service.py tests/unit/app/ui/test_update_scheduler.py -q
python -m pytest tests/unit/app/services/test_failed_record_store.py tests/unit/app/services/test_frontend_state_service.py::FrontendStateServiceTests::test_failed_snapshot_uses_persisted_worker_snapshot_when_live_page_empty -q
python -m pytest tests/unit/app/services/test_frontend_state_service.py::FrontendStateServiceTests::test_download_options_snapshot_uses_runtime_memory_without_cache_reads -q
python -m pytest tests/unit/app/ui/viewmodels/test_request_workers.py tests/unit/app/ui/viewmodels/test_frontend_snapshot_worker.py tests/unit/app/ui/viewmodels/test_log_query_worker.py tests/unit/app/ui/viewmodels/test_log_detail_worker.py tests/unit/app/ui/viewmodels/test_list_page_worker.py -q
python -m pytest tests/unit/app/core/downloaders/test_manager_core.py tests/unit/app/core/downloaders/test_manager_dispatch.py tests/contract/frontend -q
python -m pytest tests/architecture/test_frontend_file_boundaries.py tests/release/packaging/test_assets.py::InstallerScriptTests -q
node --check app/web/static/log_i18n.js
node --check app/web/static/frontend_runtime.js
node --check app/web/static/list_pages.js
node --check app/web/static/log_center.js
node --check app/web/static/settings_controller.js
node --check app/web/static/dialog_controller.js
node --check app/web/static/playback_controller.js
node --check app/web/static/app.js
```

自动化用例不得使用固定 3.5 秒等待兜底；WebUI 优先等待 `#app-shell`、行数、选中 ID、详情文本和按钮状态等可观测状态，GUI/Qt 测试可以短轮询处理事件，但每轮都必须检查目标状态，不能只靠时间推进。

### 当前验证基线

- 2026-07-10 focused：`python -m pytest tests/architecture/test_web_static_module_boundaries.py tests/contract/web/test_fastapi_endpoints.py tests/e2e/web/test_browser_journeys.py tests/contract/frontend/test_unified_frontend.py tests/release/packaging/test_assets.py -q`：`469 passed in 193.76s (0:03:13)`，`0 skipped`，`0 warnings`。
- 2026-07-10 full：`python -X faulthandler -m pytest -q`：`2368 passed, 3 skipped, 7 warnings in 366.19s (0:06:06)`。
- 2026-07-11 full：`python -X faulthandler -m pytest -q --timeout=90 --timeout-method=thread --session-timeout=900`：`2447 passed, 3 skipped, 7 warnings in 257.85s (0:04:17)`。单用例和整轮双重超时用于把线程死锁与单纯的套件耗时增长区分开。
- 2026-07-11 大文件职责拆分后 full：`python -X faulthandler -m pytest -q --timeout=90 --timeout-method=thread --session-timeout=1500`：`2455 passed, 3 skipped, 7 warnings in 252.44s (0:04:12)`。完整收集为 `2458`，等于旧基线加 8 个架构/打包守卫；浏览器测试 `136 passed in 33.40s`，统一前端契约 `144 passed in 51.65s`，打包测试 `103 passed in 49.60s`。
- 2026-07-12 GUI/Web/CLI/TUI/SDK/Skill 对齐收口后 full：`python -m pytest -q`：`2579 passed, 3 skipped, 2 warnings in 251.89s (0:04:11)`，完整收集为 `2582`。完整浏览器套件为 `150 passed in 55.46s`；GUI/Web 运行态压力组为 `155 passed in 7.32s`。本轮新增共享本地化边界、Web 更新链路、安全目录授权、键盘所有权、设置事务、同快照视觉矩阵和快速导航/日志洪峰回归。两条 warning 均来自既有的 app/UI 大文件报告型架构检查，没有新增运行时或收集 warning。
- 2026-07-14 异步选择反馈、应用级服务就绪和静态模块一致性收口后 full：`python -X faulthandler -m pytest -q --timeout=90 --timeout-method=thread --session-timeout=1500`：`2613 passed, 3 skipped, 2 warnings in 343.22s (0:05:43)`，完整收集为 `2616`。完整浏览器套件为 `153 passed in 59.09s`；新增延迟 worker 回归证明失败列表的选中 ID、DOM 高亮和详情面板无需等待分页 worker 即可同步一致，并补充 Skill 仓库外启动与小红书快捷入口契约。两条 warning 仍仅来自既有的大文件报告型架构检查，没有新增运行时、收集或线程 warning。
- 2026-07-14 shared/CI 最终收口采用与 GitHub Actions 相同的进程隔离分层：核心组 `2368 passed, 3 skipped in 183.96s (0:03:03)`，Qt 统一前端契约 `149 passed`，浏览器 `153 passed in 56.27s`，性能预算 `4 passed in 4.42s`；四组互不重叠，合计 `2674 passed, 3 skipped`。分层不是缩减测试范围，而是让每 12 个 Qt 契约节点重建一次 QApplication/native 资源，避免单进程长期积累延迟销毁对象。覆盖率门为 `73%`，wheel 隔离安装自检 `9/9`，且安装包不含 `tests/` 或已删除的 shared 旧运行时；独立运行时 venv 的 `pip-audit --strict` 为 `No known vulnerabilities found`。
- skip 数量与 Task 8 前基线同为 3；当前 2 条 warning 均为既有文件尺寸报告。2026-07-10 基线中的另外 5 条 pytest collection warning 已随测试辅助类治理消除，没有新增 warning 类型。
- 七个职责模块与 `app.js` 均通过 `node --check`；`app.js` 为 `57,118` bytes，满足 `<= 100,000` bytes 的组合根上限。
- 后续若新增 GUI/WebUI 热路径改动导致全量测试明显回退，必须先排查同步文件/SQLite/大列表重建、固定 sleep、`processEvents()` pump 或 `use_delta=False` 的非必要回退。
- 性能预算失败不能在一次高负载整轮中直接通过放宽阈值“修复”。本轮 EventBus 吞吐基准在宿主抖动时曾超预算，独立复跑通过后，第二次全量也通过；正确流程是先排除遗留进程和宿主负载、独立复跑，再以完整套件复核，只有可稳定复现时才修改生产代码或预算。

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
- 异步 worker 完成回调不得在宿主页面或窗口可能销毁后打开原生模态 `QMessageBox`。Windows 原生对话框与 Qt 父链析构并发时可能造成 `0xc0000374` 堆损坏，而不是普通 Python 异常。成功反馈必须优先使用按钮短暂文案、状态条或页面内提示；确需展示失败弹窗时必须先确认宿主仍存活，并为关闭期增加回归测试。
- 新增 GUI 后台任务时优先复用这两个 worker；只有需要独立调度协议、独立队列背压或跨进程执行时才允许新增专用线程结构。
- 非常驻 GUI 后台任务必须按需创建，不得在主窗口构造期预启动；否则测试和页面重建会堆积空闲线程，增加 Qt 退出和重建时的崩溃风险。检查更新、诊断、文件关联注册等低频动作应在用户触发后创建或提交到既有 worker，并在 `closeEvent` 中回收。

## Shared 唯一实现边界

- GUI、WebUI、service 或 CLI 中有两处以上使用的纯契约必须只在 `shared/` 保留一份实现。内部调用方直接 `from shared... import ...`；禁止在原目录保留一行 re-export、动态 fallback 或“兼容转发”物理模块。既有对外导入路径确需兼容时，只能在公开包的 `__init__.py` 边界注册指向 canonical 模块的零逻辑别名，并用对象身份测试证明没有第二份实现。
- 前端公共投影目前由 `shared/failed_page_projection.py`、`shared/log_*.py`、`shared/localization.py`、`shared/i18n_catalogs.py`、`shared/frontend_page_definitions.py`、`shared/icon_contract.py`、`shared/log_contract.py`、`shared/log_platforms.py` 和 `shared/settings_metadata.py` 统一拥有。
- 下载状态机由 `shared/controller_session.py` 唯一拥有；Web controller 直接继承该 mixin。CLI 执行器由 `shared/cli_runner_runtime.py` 唯一拥有，`cli` 包、SDK、命令和 Web 搜索入口直接导入该类，不保留 `app/controllers/session_mixin.py` 或 `cli/runner.py` 副本。
- 平台图标的文件名、顺序和静态元数据属于 shared；PyInstaller 路径解析、Qt 类型和插件注册表查询仍属于各自运行时。只有确实依赖表示层或宿主环境的行为才允许留在 `app/ui`、`app/web` 或 `app/services`。
- `tests/architecture/test_dependency_direction.py` 同时锁定三件事：服务层不得反向依赖表示层、shared 前端契约不得依赖 `app`/`cli`、已删除的旧模块不得重新出现。新增公共逻辑前必须先扩展 shared 契约和架构测试，不能复制后再补同步。

## CI 分层契约

- `quality` 在 Linux 上执行 compileall、Ruff、mypy、Bandit、全部 JavaScript 语法检查和架构/CI 契约测试；静态质量门与平台原生运行态解耦。
- `compatibility` 在 Python 3.10、3.11、3.12、3.13 上分别构建 wheel/sdist，并离开源码树执行无依赖安装、自检和公开导入验证。构建成功但安装后入口失效仍视为失败。
- `security` 在独立 Windows 虚拟环境中先升级 bootstrap pip，再只安装运行时依赖，并以 `pip-audit --strict` 审计实际解析结果；不得用开发环境中偶然存在的包代替运行时依赖集合，也不得让 runner 自带旧 pip 的漏洞污染项目审计结果。
- `core-tests` 在 Windows 上先运行非浏览器、非性能、非统一前端契约的核心组，再以 12 个节点一组运行全部 Qt 契约并合并 coverage；性能预算脱离 instrumentation 独立执行。`browser-tests` 独立缓存并安装 Chromium，运行真实 WebUI 浏览器套件。
- `required-check` 是分支保护使用的稳定聚合门；质量、兼容矩阵、安全审计、核心或浏览器任一任务失败都会失败。所有任务必须设置最长期限，并通过 workflow concurrency 取消同分支旧运行。
- Docker 工作流使用 Buildx、GitHub Actions cache 和只读仓库权限，并对 Dockerfile、compose、运行入口与 shared 变更触发验证。
- 本地验收必须至少运行 `python -m ruff check app cli entry shared scripts tests`、全部 JavaScript 的 `node --check`，并按 workflow 相同边界运行核心组、每组 12 个节点的 Qt 契约、浏览器和性能预算；不得为了追求单条 `python -m pytest -q` 命令而把全部 Qt 原生资源塞进一个长生命周期进程。CI 不能替代提交前的完整本地回归。
