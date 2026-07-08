# Spider 异步流水线工程实践

> 以 `DouyinSpider` 当前实现为基线，记录平台采集、解析、任务构建和入队的异步边界。本文描述当前推荐做法；后续优化 Bilibili、Xiaohongshu 等平台时，优先按这里的边界对齐。

更新日期：2026-07-09

## 结论

抖音链路已经做过完整拆解。它不是在 UI 线程里串行爬取，而是把耗时采集放在 `BaseSpider` 后台线程中，再在该线程内用 `asyncio.run()` 驱动 DouK/httpx 异步接口。

可以直接借鉴的部分：

- 登录、采集、解析、选择、构建下载任务、提交下载任务有明确边界。
- 平台 API 请求复用异步 `httpx.AsyncClient`，无代理路径是真异步。
- 分页循环保留顺序执行和节流，避免游标翻页、风控和返回顺序被并发打乱。
- 用户选择和扫码登录是刻意保留的同步边界，不应该被硬改成后台静默并发。
- 下载执行仍交给 `DownloadManager`，Spider 只负责生成统一下载元数据。

不能直接照搬的部分：

- 抖音详情、主页、合集、搜索的 API 形态不同，Bilibili 和 Xiaohongshu 不能简单把函数改成 `async` 就算完成。
- Douyin 当前 `_submit_tasks()` 仍按单个 `emit_video()` 发射，适合选择结果不大的场景；大批量平台应优先批量发射，减少 GUI/WebUI 刷新压力。
- DouK 代理分支目前在 async 函数里调用同步 `httpx.get/post`。如果用户配置代理且请求量很大，这条路径仍可能阻塞事件循环，后续应改成异步代理客户端或放到专用线程。

## 抖音实际链路

```text
BaseSpider 后台线程
  -> run()
    -> _load_or_login()
      -> 优先读取本地 cookie
      -> cookie 不可用时启动 Playwright 子进程扫码登录
    -> asyncio.run(_async_main(cookie))
      -> Parameter.update_params()
      -> 共享 httpx.AsyncClient
      -> _route_input()
        -> _process_detail()
        -> _process_user()
        -> _process_mix()
        -> _process_search()
        -> _process_user_search()
      -> DouyinParser.parse_aweme()
      -> ask_user_selection()
      -> DouyinTaskBuilder.build_items()
      -> emit_video()/items_found
        -> GUI/Web/CLI Controller
        -> DownloadManager
```

这个结构的关键点是：异步只包住平台网络采集，不把 UI 状态、用户选择、下载队列和下载并发揉进同一个事件循环。

## 边界说明

### 登录

抖音登录使用独立子进程运行 Playwright Chromium。这样做不是为了性能，而是为了隔离 Qt、Playwright、浏览器事件循环和线程生命周期。

登录流程可以等待用户扫码，但等待不发生在 GUI 主线程里。父进程用 `Queue.get(timeout=...)` 轮询子进程结果，同时支持停止信号和超时清理。

维护要求：

- 不要在 GUI 线程直接运行 Playwright 登录。
- 不要依赖 `Queue.empty()` 判断登录结果。
- 登录窗口可以显式显示，静默采集发现 cookie 失效时应切回显式登录，再继续采集。

### 平台请求

抖音 API 请求由 DouK 接口层完成，核心路径是：

- `Parameter.update_params()` 初始化请求参数和客户端。
- `API.run_single()` 请求单页数据。
- `API.run_batch()` 处理通用分页。
- `request_data_get/post()` 使用 `await self.client.get/post(...)`。

这部分是 Bilibili 和 Xiaohongshu 最值得学习的地方：平台请求可以异步，但连接池、Cookie、签名、代理和重试必须由平台适配层管理，不能散落到 UI 或下载器。

### 分页与节流

抖音主页、合集和搜索都保留了顺序分页：

- 用户主页按接口返回的 `max_cursor` 继续翻页。
- 合集按 `cursor` 和 `has_more` 推进。
- 搜索按页码范围推进。
- 每页之间保留短 sleep。

这不是遗漏，而是平台协议决定的背压边界。盲目并发分页容易造成重复、漏页、风控或结果顺序错乱。

优化原则：

- 可以并发详情补充、签名计算、任务构建等互不依赖的工作。
- 不要并发破坏游标型分页。
- 需要提速时优先减少入队刷新和任务构建阻塞，而不是加大平台请求洪峰。

### 解析和任务构建

解析阶段把平台响应归一化为 `VideoItem`。任务构建阶段再把 `VideoItem` 转成下载器可消费的元数据。

这两个阶段通常是轻量 CPU 工作，放在 Spider 后台线程即可。只有出现大批量任务构建、额外网络补全或磁盘扫描时，才需要改成线程池或 async fan-out。

维护要求：

- Parser 不应该写下载队列。
- TaskBuilder 不应该访问 GUI。
- 每条任务必须带可追踪的 platform、title、url、trace_id 或等价上下文。

### 用户选择

`ask_user_selection()` 是有意保留的同步边界。它代表“等待用户决策”，不是性能瓶颈。

优化时不要把选择弹窗改成后台自动继续，否则会破坏交互语义。真正需要优化的是选择完成之后的大批量构建和入队。

### 下载入队

Spider 的职责到“发射下载候选项”为止。后续进入 Controller 和 `DownloadManager`：

```text
Spider -> emit_video/emit_videos -> Controller -> DownloadManager.add_task/add_tasks -> 下载队列
```

大批量场景推荐使用批量发射和 `add_tasks()`，这样可以减少：

- 信号次数
- 表格重绘次数
- Web delta 次数
- 队列 wakeup 次数

这也是 Bilibili 入队慢时优先优化的地方。

## 上一轮已落地优化

上一轮不是只做了文档分析，已经把“批量发射、批量入队、Bilibili 受限并发取流”落到了代码里。

### DownloadManager 批量入队

`DownloadManagerCore.add_task()` 已经统一委托给 `add_tasks()`。批量路径会先过滤 `video_only`、记录队列日志，然后通过 `PendingDownloadQueue.put_many()` 一次写入多条任务，并只触发一次 dispatch slot gate。

这解决的是“多条下载任务逐条入队、逐条唤醒、逐条刷新”的基础开销，但不改变下载并发上限。下载并发仍由 `DownloadManager` 的 slot 和 heavy/lightweight 规则控制。

### GUI/Web/CLI 批量接收 spider 结果

三类入口都已经接入批量发现事件：

- GUI Controller：`_on_spider_items_found()` 批量准备 pending item、批量存储、批量加表格行，再调用 `dl_manager.add_tasks()`。
- Web Controller：`_on_spider_items_found()` 批量存储，并沿用 Web bridge 发出 item_found 事件，随后批量入下载队列。
- CLI Runner：`_on_items_found()` 批量收集 VideoItem，开启下载时批量交给 DownloadManager。

单条路径仍然保留，避免普通单任务因为批处理改动而走过重流程。

### Bilibili 取流和提交优化

Bilibili 已经新增 `_process_download_tasks_async()`，但这里的 async 是工程语义上的“异步化/并发化”，具体实现是受限 `ThreadPoolExecutor`：

- `api_workers` 控制并发 worker 数。
- 每个 worker 通过 `_worker_api_for_thread()` 使用线程本地 `BiliAPI`，避免多个线程抢同一个 API/session 状态。
- 每个任务只负责 `_resolve_download_item()`，也就是互不依赖的取流和 VideoItem 构建。
- 所有 ready item 收集完成后，用一次 `emit_videos(ready_items)` 发射。
- worker 数为 1 或任务数为 1 时自动回退到旧的单条处理路径。

这个改法解决的是 Bilibili “取流 + 任务构建 + 逐条提交”叠加导致的入队慢。它没有并发收藏夹/合集的游标分页，也没有提高下载器并发，因此不会把平台请求洪峰和下载洪峰绑在一起放大。

### Xiaohongshu 图文批量发射

Xiaohongshu 的 `_emit_note_items()` 已经改成：

```text
task_builder.build_items(...) -> emit_videos(items)
```

也就是一篇笔记里的图文/视频资源统一构建后批量发射。这样可以减少多图笔记逐张图片触发 GUI/WebUI 刷新和下载队列唤醒的次数。

### 回归覆盖

上一轮补了两类关键回归：

- `test_add_tasks_batches_pending_queue_wakeup`：验证 DownloadManager 批量入队后队列中确实有多条任务。
- `test_bilibili_process_download_tasks_async_batches_ready_items`：验证 Bilibili 并发取流后走 `emit_videos()`，不再逐条 `emit_video()`。

并已跑过与 spider、DownloadManager、controller、Web controller、集成流相关的测试分组。后续如果继续扩展 Bilibili/Xiaohongshu 异步化，需要把新并发边界补进这些测试附近。

### 刻意没有改的地方

- 没有把 Douyin 分页改成并发分页，因为它依赖 cursor、has_more 和平台节流。
- 没有把用户选择弹窗改成异步自动继续，因为这是交互边界。
- 没有把下载执行塞回 Spider 事件循环，因为下载器仍是独立调度层。
- 没有提高下载并发上限，因为入队慢和下载慢是两类问题。

## 给 Bilibili 和 Xiaohongshu 的迁移准则

### Bilibili

Bilibili 的慢点通常不在最终下载，而在详情解析、分 P/合集展开、取流、任务构建和逐条入队的组合开销。

推荐顺序：

1. 保持主流程在 Spider 后台线程，不碰 GUI 线程。
2. 对互不依赖的视频详情、分 P 元数据或取流请求做受限并发。
3. 对需要顺序的收藏夹、合集或分页游标保留顺序推进。
4. 构建完成后使用批量发射，交给 `DownloadManager.add_tasks()` 一次唤醒。
5. 保持下载并发由 DownloadManager 控制，不因采集并发提高而直接增加下载洪峰。

### Xiaohongshu

Xiaohongshu 的关键点是签名、Cookie、图文/视频解析和兜底库边界。

推荐顺序：

1. 自研签名路径作为主路径，外部库只做兜底。
2. 签名计算和详情请求可受限并发，但要共享签名上下文和 Cookie 快照。
3. 图文多资源构建适合批量发射，避免每张图触发一次 UI 刷新。
4. 失败时保留原始错误类型、平台、trace_id 和签名路径，方便判断是签名、Cookie、风控还是网络问题。

## 异步改造检查清单

- 耗时平台请求不在 GUI 线程执行。
- async 函数内部不直接调用阻塞 HTTP、阻塞磁盘扫描或长时间 CPU 循环。
- 游标分页保留顺序，互不依赖的详情补充才并发。
- 并发有上限，不能让平台请求、下载队列和 UI 刷新同时放大。
- 批量结果用 `emit_videos()` 或等价批量路径发射。
- `DownloadManager.add_tasks()` 只唤醒一次队列，不逐条重复 wakeup。
- GUI/WebUI 只消费状态快照或 delta，不在入队热路径整页刷新。
- 日志不要输出 Cookie、完整敏感 headers 或不必要的完整本地路径。
- 取消、停止、登录失败、空结果和部分失败都有可诊断日志。
- 新增平台异步路径后，要补单条、多条、取消、失败和批量入队测试。

## 已知风险与后续改进

- DouK 代理请求分支仍含同步 `httpx.get/post`，代理高并发场景需要后续改为异步代理请求。
- Douyin `_submit_tasks()` 仍是逐条 `emit_video()`，如果出现大批量选择卡顿，应切换成批量发射。
- 任何平台都不要为了“看起来全异步”把用户选择、登录窗口和下载执行混入 Spider 事件循环。
- 后续优化 Bilibili/Xiaohongshu 时，应以“受限并发 + 批量入队 + UI 背压”为目标，而不是单纯堆线程或堆 `asyncio.gather()`。
