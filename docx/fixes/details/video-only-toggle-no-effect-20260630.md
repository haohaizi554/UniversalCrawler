# 仅下载视频开关无效排查记录

## 背景

GUI 设置页的“仅下载视频”开关可以保存到配置，但用户开启后，封面、图片或图集资源仍可能进入下载队列，看起来像设置没有作用。

## 根因

这不是单纯的界面状态问题，而是三层链路断开：

1. 设置中心只保存了 `download.video_only`，普通 `update_setting` 路径没有把它纳入下载运行时热加载。
2. `DownloadManagerCore` 读取并保存了 `self.video_only`，但旧逻辑没有在 `add_task()` 或调度前消费这个字段。
3. GUI 与 WebUI 的爬虫回调会在发现资源后立即写入前端列表并入队，缺少统一的非视频资源过滤入口。

## 修复

新增统一资源分类器 `app/core/media_filter.py`，根据 `content_type`、元数据标记和 URL 扩展名判断资源是视频还是图片。

修复点：

- `FrontendStateService.download_options_snapshot()` 返回运行时有效的 `video_only`。
- `FrontendStateService._action_update_download_options()` 持久化并热加载 `video_only`。
- GUI `CrawlControllerMixin._on_spider_item_found()` 在入列表和入队前过滤图片资源。
- Web `WebController._on_spider_item_found()` 使用同一规则过滤图片资源。
- `DownloadManagerCore.add_task()` 增加兜底过滤，即使入口漏判也不会把图片资源放进下载队列。

## 验证

运行针对性测试：

```powershell
python -m pytest tests\test_download_manager_core.py tests\test_frontend_state_service.py tests\test_application_controller.py tests\test_web_controller_runtime.py -q
```

结果：`125 passed`。

## 经验

设置项是否“生效”不能只看配置文件和界面控件，还要检查：

- 运行时对象是否收到热加载参数。
- 业务入口是否在副作用发生前读取该参数。
- 核心服务是否有兜底保护，避免 GUI/Web/CLI 某一路漏接。

