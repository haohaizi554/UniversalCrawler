# 架构说明

## 目标

当前代码基座强调两件事：

- 对 UI、采集、下载进行分层，避免单点文件继续膨胀。
- 让复杂站点逻辑可以被测试，而不是只能依赖手工点点点。

## 分层结构

```text
Main
  -> ApplicationController
  -> Spider
  -> Parser / TaskBuilder
  -> DownloadManager / DownloadWorker
  -> Downloader / External Tools
  -> Local Media Library
```

### `main.py`

- 仅负责应用入口与控制器启动。
- 不承载业务判断。

### `app/controllers`

- `ApplicationController` 是桌面端业务编排中枢。
- 负责连接 UI 信号、创建爬虫、维护当前媒体列表、承接下载回调。
- 这里适合写控制流测试，不适合堆站点解析细节。

### `app/spiders`

每个平台尽量遵循三段式：

- `spider.py`：页面访问、流程控制、登录、用户交互、信号发射。
- `parser.py`：解析 HTML / JSON / 标题 / 指纹 / 业务分组。
- `task_builder.py`：把解析结果转换成统一下载任务元数据。

这层是最值得补测试的区域，尤其是：

- B 站 API 回退与任务装配
- 快手流捕获与焦点匹配
- MissAV 两轮扫描与优先级选择
- 抖音不同输入类型的分流

### `app/core`

- `download_manager.py` 负责队列、并发槽位与工作线程回收。
- `downloaders/` 负责平台下载与外部工具封装。
- `plugins/` 负责平台定义、配置 UI 构建与注册。
- `lib/douyin/` 保留抖音底层协议能力，供现有流程复用。

### `app/services`

- `auth_service.py`：认证文件读写与 Cookie 工具。
- `file_service.py`：本地媒体扫描、重命名、删除。
- `debug_service.py`：调试日志、错误摘要和 trace 复制。

### `app/ui`

- 承载桌面窗口、面板、弹窗、主题和媒体预览。
- 业务逻辑尽量经由 controller，不直接深入 spider 或 downloader。

## 数据流

1. 用户从主界面输入关键词、链接和平台配置。
2. 控制器通过插件注册表找到平台实现并创建 `Spider`。
3. `Spider` 采集站点数据，必要时触发用户选择。
4. `Spider` 发出标准化 `VideoItem`，控制器将其加入下载列表。
5. `DownloadManager` 创建 `DownloadWorker` 并选择平台下载器。
6. 文件写入本地后，由 UI 和 `MediaLibraryService` 负责展示与管理。

## 测试视角下的职责边界

推荐按照以下边界写测试：

- `parser / task_builder`：纯单元测试。
- `ApplicationController`：半集成测试，mock UI 和下载器即可。
- `DownloadWorker`：路径、扩展名、签名识别优先写纯逻辑测试。
- `Spider` 主流程：mock 浏览器 page/context，只验证流程分支、任务发射和日志行为。

## 当前高风险点

- 浏览器事件监听与页面状态切换。
- 下载后扩展名修正与文件落盘目录选择。
- 需要多阶段用户选择的平台流程。
- 登录失效后的自动恢复与降级路径。

## 文档联动

结构调整后，请同步更新以下文档：

- `docs/development.md`
- `docs/api.md`
- `docs/testing.md`
- 对应目录下的 `README.md`
