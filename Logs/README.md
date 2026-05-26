# 日志使用说明

这套日志的目标不是“记录一切”，而是帮助你在最短时间内回答这几个问题：

- 当前问题发生在 `爬虫 / 入队 / 下载 / 合并 / 程序状态` 的哪一层
- 某个任务从 API 到下载器是不是同一条链路
- 下载器实际注入了哪些参数
- 报错后应该优先看哪几段记录

## 先看哪几个文件

- `logs/`
  - 运行时实际写入目录
  - Windows 下和当前仓库里的 `Logs/` 目录等价，不影响正常使用

- `latest_debug.log`
  - 当前最新一次运行的完整调试日志
  - 日常排查先看这个

- `latest_error_summary.md`
  - 最近一次错误的摘要
  - 适合先快速判断问题大概卡在哪一层
  - 现在会包含 `错误分级` 和 `自动建议结论`
  - 每次新的 `ERROR` 日志都会覆盖成“最近一次错误”的诊断结果

- `debug_YYYYMMDD_HHMMSS.log`
  - 某一次运行的完整历史日志
  - 当你要回看旧问题时，再看这个

## 日志结构怎么看

每条日志基本都是以下结构：

- `时间`
  - 记录产生的时间

- `级别`
  - `INFO` 表示正常过程
  - `WARN` 表示可恢复问题或用户主动停止
  - `ERROR` 表示失败，通常也会刷新 `latest_error_summary.md`
  - `COMMAND` 表示外部命令执行，例如 `ffmpeg` 或 `N_m3u8DL-RE`

- `模块 / 动作`
  - 例如 `ApplicationController / start_crawl`
  - 例如 `BiliAPI / API::get_play_url`
  - 例如 `DownloadWorker / start_download`

- `状态码`
  - 是程序内部定义的阶段码
  - 用来快速判断当前处于哪个阶段

- `追踪ID`
  - 这是最关键的字段
  - 同一个下载任务从 `爬虫 -> 入队 -> 分发 -> 下载器 -> 合并 -> 完成/失败` 会尽量复用同一个 `trace_id`
  - 排查时优先全文搜索这个值

- `上下文`
  - 放任务身份信息，例如 `source`、`video_id`、`bvid`、`cid`

- `详情 / 请求 / 响应摘要 / 参数`
  - 只记录当前逻辑真正用到的字段
  - 不会故意把整包原始 JSON 全部写进去

## 推荐排查顺序

如果你不知道从哪里看，按这个顺序来：

1. 先看 `latest_error_summary.md`
2. 记下里面的 `追踪ID`
3. 去 `latest_debug.log` 里全文搜索这个 `追踪ID`
4. 按时间顺序看这条链路上的以下记录
5. `API` 记录是否正常
6. `APP_ITEM_FOUND / DL_QUEUE / DL_DISPATCH / DL_START` 是否完整
7. 对应下载器是否拿到了正确参数
8. 如果用了外部工具，再看 `COMMAND` 记录

## 常见问题看什么

### 1. 没扫到资源

优先看这些记录：

- `ApplicationController / start_crawl`
- `DouyinSpider / run_start`
- `BilibiliSpider / run_start`
- 对应平台的 `API::*`

判断方式：

- 如果连 `run_start` 都没有，说明任务没真正启动
- 如果有 `run_start`，但没有任何 `API` 记录，通常是流程还没走到接口层
- 如果有 `API`，但没有 `APP_ITEM_FOUND`，通常是接口有返回，但没有解析出有效任务

### 2. 扫到了资源，但没有开始下载

优先看这些记录：

- `ApplicationController / item_found`
- `DownloadManager / queue_task`
- `DownloadManager / dispatch_task`
- `DownloadWorker / start_download`

判断方式：

- 有 `item_found` 没有 `queue_task`，说明入队逻辑异常
- 有 `queue_task` 没有 `dispatch_task`，说明任务还在排队或调度器阻塞
- 有 `dispatch_task` 没有 `start_download`，说明 worker 没真正执行

### 3. 下载中途失败

优先看这些记录：

- `DownloadWorker / start_download`
- 平台下载器的 `prepare_download`
- 平台下载器的 `API` 或 `COMMAND`
- `ApplicationController / download_error`

判断方式：

- 如果 `prepare_download` 之前就报错，问题大多在路径、参数或任务装配
- 如果 `prepare_download` 正常，但没有后续流请求或命令记录，问题大多在下载器内部准备阶段
- 如果有外部命令记录，再重点看命令参数和工具返回结果

## 各平台怎么查

### 抖音

先看：

- `DouyinSpider / API::detail`
- `DouyinSpider / API::account_page`
- `DouyinSpider / API::search_page`
- `DouyinSpider / API::user_search`
- `DouyinSpider / emit_download_task`
- `DouyinDownloader / prepare_download`
- `DouyinDownloader / API::head_size`
- `DouyinDownloader / API::single_download`

重点关注字段：

- `aweme_id`
  - 抖音作品 ID

- `content_type`
  - `video` 表示视频
  - `gallery` 或 `image` 表示图集图片

- `media_label`
  - `视频 / 图集 / 实况`

- `source_url`
  - 实际下载地址

- `size_mb`
  - 资源预估大小

常见判断：

- `detail` 正常但没有 `emit_download_task`，说明解析到了数据但没有落成下载任务
- `prepare_download` 正常但 `single_download` 失败，通常是链接过期、Cookie 失效或请求头不对
- 图集/实况失败时，优先检查拆分出的子任务 `trace_id`

### Bilibili

先看：

- `BiliAPI / check_login`
- `BiliAPI / get_video_info`
- `BiliAPI / get_play_url`
- `BilibiliSpider / emit_download_task`
- `BilibiliDownloader / prepare_download`
- `BilibiliDownloader / API::stream_video`
- `BilibiliDownloader / API::stream_audio`
- `BilibiliDownloader / ffmpeg`

重点关注字段：

- `bvid`
  - B 站视频编号

- `cid`
  - 当前分 P 或当前稿件分段 ID

- `video_quality_id`
  - 最终拿到的画质编号

- `video_url`
  - 视频流地址

- `audio_url`
  - 音频流地址

- `accept_quality`
  - 接口返回的可用画质列表

常见判断：

- `get_video_info` 正常但 `get_play_url` 失败，通常是登录态、画质权限或请求参数问题
- `get_play_url` 正常但 `stream_audio` 缺失，可能是无音轨或接口降级
- `stream_video / stream_audio` 正常但 `ffmpeg` 失败，优先检查命令参数和输出路径

### 快手

先看：

- `KuaishouSpider / emit_download_task`
- `KuaishouDownloader / prepare_download`
- `KuaishouDownloader / API::stream_download`
- `ApplicationController / download_error`

重点关注字段：

- `stream_url`
  - 快手页面实际捕获到的视频流地址

- `download_strategy`
  - 当前按 `m3u8` 还是普通 `http` 处理

- `referer`
  - 下载请求使用的来源页地址

- `source_url`
  - 下载器实际拿去下载的 URL

常见判断：

- 如果没有 `emit_download_task`，说明播放页里没成功捕获到媒体流
- 如果有 `emit_download_task` 但没有 `prepare_download`，说明任务没进入下载执行阶段
- 如果 `stream_download` 失败，优先核对 `source_url` 是否过期、`referer` 是否正确

### MissAV

先看：

- `MissAVSpider / emit_download_task`
- `MissAVDownloader / prepare_download`
- `N_m3u8DL_RE_Downloader / N_m3u8DL-RE`
- `ApplicationController / download_error`

重点关注字段：

- `stream_url`
  - 嗅探到的 `playlist.m3u8` 地址

- `referer`
  - 当前详情页地址

- `proxy`
  - 当前使用的代理配置

- `source_url`
  - 下载器真正传给 `N_m3u8DL-RE` 的 URL

常见判断：

- 如果嗅探阶段成功但下载失败，优先看 `N_m3u8DL-RE` 参数块
- 如果没有 `emit_download_task`，说明详情页里没有成功抓到 `playlist.m3u8`

## 各下载器怎么看

### `DouyinDownloader`

主要记录：

- `prepare_download`
- `API::head_size`
- `API::single_download`

记录的参数含义：

- `source_url`
  - 当前真正下载的资源地址

- `save_path`
  - 当前目标保存路径

- `content_type`
  - 当前下载的是视频还是图片

- `aweme_id`
  - 对应抖音作品

- `range`
  - 断点续传时会带这个请求头

### `BilibiliDownloader`

主要记录：

- `prepare_download`
- `API::stream_video`
- `API::stream_audio`
- `COMMAND / ffmpeg`

记录的参数含义：

- `video_url`
  - 视频流下载地址

- `audio_url`
  - 音频流下载地址

- `save_path`
  - 最终输出文件路径

- `chunk_size`
  - 当前 Python 流下载块大小

### `N_m3u8DL_RE_Downloader`

主要记录：

- `COMMAND / N_m3u8DL-RE`

参数含义：

- `url`
  - 输入的 m3u8 地址

- `--save-dir`
  - 输出目录

- `--save-name`
  - 输出文件名，不带扩展名

- `--thread-count`
  - 分片线程数

- `--download-retry-count`
  - 失败重试次数

- `--header`
  - 当前真正注入的请求头

- `--mux-after-done format=mp4`
  - 下载完成后自动封装为 mp4

排查建议：

- 如果命令能看到但失败，优先检查 `m3u8` 地址、`Referer`、`User-Agent` 和保存目录权限
- 如果是 `MissAV` 或 `快手` 的 `m3u8` 场景，先回到对应 spider 的 `emit_download_task` 看最初捕获到的 URL 是否已经异常

### `FFmpegDownloader`

主要记录：

- `API::head_redirect`
- `COMMAND / ffmpeg`

参数含义：

- `-user_agent`
  - 注入的 UA

- `-headers`
  - 注入的请求头，目前主要是 `Referer`

- `-reconnect*`
  - 自动重连策略

- `-timeout`
  - 超时设置

- `-i`
  - 输入地址

- `-c copy`
  - 直接拷贝流，不重新编码

排查建议：

- 如果 `head_redirect` 已经异常，先确认原始 URL 是否有效
- 如果 `COMMAND / ffmpeg` 正常但失败，优先检查 `Referer`、输出路径和输入地址是否还能访问

## 状态码怎么理解

常见状态码示例：

- `APP_*`
  - 应用控制器阶段

- `DL_*`
  - 下载队列和下载 worker 阶段

- `DOUYIN_*`
  - 抖音爬虫或抖音下载器阶段

- `BILI_*`
  - B 站爬虫或 B 站下载器阶段

- `KUAISHOU_*`
  - 快手抓流或下载阶段

- `MISSAV_*`
  - MissAV 嗅探或下载阶段

- `M3U8_OK`
  - `N_m3u8DL-RE` 正常完成

- `FFMPEG_OK`
  - `ffmpeg` 正常完成

## 追踪ID怎么用

同一个任务尽量会带同一个 `trace_id`，例如：

- 抖音单视频：通常是一条固定的 `dy-<aweme_id>`
- 抖音图集子项：会在原始 `trace_id` 后补子项后缀
- B 站单任务：通常是一条固定的 `bili-<bvid>-<cid>`

排查时不要只看模块名，优先按 `trace_id` 串起来看。

## 什么时候看 `latest_error_summary.md`

适合这些情况：

- 你只想快速知道“最近一次失败在哪”
- 你要先给自己一个排查方向
- 你不想先翻整份大日志
- 你想先看系统自动给出的错误分级和建议结论

不适合这些情况：

- 你要分析完整链路
- 你要判断是哪个 API 先出问题
- 你要确认实际命令参数

这时候还是要回到 `latest_debug.log`。

## 错误分级怎么看

`latest_error_summary.md` 里的 `错误分级` 是为了快速判断优先级：

- `P1-阻断`
  - 常见于文件缺失、权限问题、核心依赖不可用
  - 一般会直接导致当前功能完全不可继续

- `P2-高`
  - 常见于接口取流失败、下载失败、外部工具执行失败
  - 优先级很高，通常直接影响本次任务是否完成

- `P3-中`
  - 常见于局部流程异常
  - 需要排查，但未必阻断整个程序

- `P4-用户操作`
  - 常见于用户主动停止任务
  - 一般不是程序缺陷

## 自动建议结论怎么看

`latest_error_summary.md` 里的 `自动建议结论` 是一段机器生成的初步判断，用来告诉你：

- 当前问题更像发生在哪一层
- 先看哪几组日志最省时间
- 是否优先怀疑 `API / 下载器 / ffmpeg / N_m3u8DL-RE / 入队调度`

它适合做“第一眼判断”，不适合替代完整排查。

## UI 调试入口

主界面顶部现在有三个调试按钮：

- `最新日志`
  - 直接打开 `latest_debug.log`

- `错误摘要`
  - 直接打开 `latest_error_summary.md`

- `复制Trace`
  - 先在下载队列表中选中一个任务
  - 点击后会复制该任务的 `trace_id`
  - 然后去 `latest_debug.log` 里全文搜索即可
