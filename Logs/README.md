# 日志使用说明

## 日志系统目标

日志的目标不是记录一切，而是帮助维护者快速回答：

- 问题发生在 `爬虫 / 入队 / 下载 / 合并 / UI` 的哪一层。
- 某个任务是不是同一条链路上的同一个资源。
- 下载器或外部工具实际注入了哪些参数。

## 重要文件

- `latest_debug.log`
  - 当前最近一次运行的完整日志。
- `latest_error_summary.md`
  - 最近一次错误摘要，适合先做快速定位。
- `debug_YYYYMMDD_HHMMSS.log`
  - 历史会话日志。

## 怎么看一条日志

每条日志通常包含：

- 时间
- 级别
- 模块 / 动作
- 状态码
- `trace_id`
- 上下文
- 详情 / 请求 / 响应摘要 / 外部命令参数

其中最关键的是 `trace_id`，排障时优先全文搜索它。

## 推荐排查顺序

1. 打开 `latest_error_summary.md`。
2. 记录其中的 `trace_id`。
3. 在 `latest_debug.log` 中搜索该 `trace_id`。
4. 沿着 `Spider -> Controller -> DownloadManager -> Downloader` 查看日志链路。

## 常见问题与入口

### 没扫到资源

优先看：

- `ApplicationController / start_crawl`
- 对应平台 `Spider / run_start`
- 平台 API 摘要日志

### 扫到了资源但没下载

优先看：

- `ApplicationController / item_found`
- `DownloadManager / queue_task`
- `DownloadManager / dispatch_task`
- `DownloadWorker / start_download`

### 下载失败

优先看：

- 对应下载器 `prepare_download`
- `COMMAND / ffmpeg`
- `COMMAND / N_m3u8DL-RE`
- `ApplicationController / download_error`

## 维护建议

- 新增关键流程时，请补状态码和 `trace_id` 透传。
- 外部工具封装变动时，请确认命令日志仍保留关键参数。
- 错误摘要结构变更时，同步更新 `latest_error_summary.md` 模板说明。
