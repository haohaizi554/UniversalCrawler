# 内部接口说明

本文档描述项目中最常被调用、最值得稳定维护的内部接口，而不是枚举所有模块。

## 配置入口

### `app.config.cfg`

- 类型：`ConfigManager`
- 作用：统一读取、写入和补齐项目配置。
- 常见调用：`get()`、`set()`、`save_ui_state()`、`update_missav_proxy()`。

## 核心控制器

### `ApplicationController`

关键职责：

- `scan_local_dir()`：扫描本地媒体目录并刷新 UI。
- `on_start_crawl(keyword, source_id, config)`：创建对应平台爬虫并启动。
- `_on_spider_item_found(item)`：接收 `Spider` 发出的 `VideoItem` 并加入下载队列。
- `_on_spider_select_tasks(items)`：承接爬虫的选择请求并回传 UI 结果。
- `shutdown()`：停止爬虫、停止下载器并清理媒体资源。

## Spider 基类

### `BaseSpider`

统一能力：

- `emit_video(url, title, source, meta)`：发射标准 `VideoItem`。
- `ask_user_selection(items)`：阻塞等待 UI 返回勾选结果。
- `resume_from_ui(selected_indices)`：由控制器恢复爬虫线程。
- `new_trace_id()` / `ensure_trace_id()`：生成并维护链路追踪 ID。

## 平台 API / Spider 关键接口

### Bilibili

- `BiliAPI.check_login()`：检查 Cookie 是否可用。
- `BiliAPI.get_video_info(bvid)`：获取结构化稿件信息。
- `BiliAPI.get_play_url(bvid, cid)`：解析播放流，包含 `4048 -> 80` 回退。
- `BilibiliSpider._producer_browser_task()`：浏览器扫描 BV。
- `BilibiliSpider._worker_api_pool()`：并发拉取稿件详情。

### Douyin

- `DouyinSpider._async_main(cookie)`：根据输入类型分流到详情、主页、合集或搜索流程。
- `DouyinTaskBuilder.build_items()`：图集、实况照片等子任务拆分。

### Kuaishou

- `KuaishouSpider._ensure_login(page, context, auth_file)`：登录态恢复与人工登录等待。
- `KuaishouSpider._run_capture_pipeline(page, items, fingerprints)`：流捕获主流程。
- `KuaishouTaskBuilder.build_download_meta(trace_id, referer, stream_url)`：统一下载元数据。

### MissAV

- `MissAVSpider.run()`：两轮扫描、筛选、用户选择与 m3u8 嗅探。
- `MissAVSpider._scan_pages(page, data_dict)`：列表扫描与分页。
- `MissAVTaskBuilder.build_download_meta()`：为下载器提供 UA、Referer 与代理信息。

## 下载层

### `DownloadManager`

- `add_task(video, save_dir)`：添加下载任务。
- `cancel_task(video_id)`：取消排队或执行中的任务。
- `stop_all()`：停止所有工作线程并清空队列。

### `DownloadWorker`

关键纯逻辑方法：

- `_resolve_save_dir()`：决定是否使用子目录。
- `_infer_extension()`：根据内容类型和 URL 推断扩展名。
- `_ensure_unique_path()`：避免覆盖现有文件。
- `_detect_actual_file_type()`：按文件头修正真实扩展名。

## 服务层

### `MediaLibraryService`

- `scan_directory(directory, max_scan_count=1000)`：返回 `ScanResult`。
- `rename_media(video, new_title, save_dir)`：重命名并返回旧新路径。
- `delete_media(video)`：删除媒体文件。

### `DebugArtifactsService`

- `open_latest_log()`：打开最近日志。
- `open_latest_error_summary()`：打开最近错误摘要。
- `copy_trace_id(clipboard, trace_id)`：复制 `trace_id` 到剪贴板。

## 插件入口

### `app.core.plugin_registry.registry`

- 统一的平台注册表入口。
- UI 与 controller 都应通过该注册表查找平台能力，而不是直接硬编码类名。
