# 接口指南

本文记录当前工程对 GUI、WebUI、CLI 和 SDK 暴露的主要接口边界。更细的 CLI/REST/SDK 调用示例见 [cli/](../cli/README.md)。

## 前端状态服务

`app/services/frontend_state_service.py` 是 GUI 和 WebUI 的统一适配层，负责把内部状态转换成前端可消费的结构。核心输出包括：

| 字段 | 说明 |
| --- | --- |
| `queue_items` | 下载队列页数据 |
| `active_downloads` | 正在下载页数据 |
| `completed_items` | 已完成页数据 |
| `failed_items` | 失败列表页数据 |
| `log_items` | 日志中心数据 |
| `settings_snapshot` | 配置中心数据 |
| `toolbox_items` | 工具箱数据 |
| `app_status` | 底部状态栏和侧栏角标数据 |

保留 `get_snapshot()` 作为兼容入口；高频刷新应优先使用版本化 delta，避免每次进度变更都扫描全量状态。

## Web REST

`app/web/server.py:create_app()` 是用户真实访问 WebUI 的直连入口，`app/web/rest_router.py` 是组合式路由入口。两边必须保持端点语义一致，尤其是前端状态、delta、图标、国际化和动作接口；新增接口时要同步 `tests/contract/web/test_fastapi_endpoints.py`，避免只修组合路由或只修直连入口。

开发态入口使用 `python -m entry.web_entry --host 127.0.0.1 --port 8000`，打包态入口使用 `CrawlerWebPortal.exe`。REST 适合初始加载、手动刷新、配置读取和明确用户动作，不适合承载每个进度信号。

典型接口语义：

- `GET /api/ping`、`GET /api/platforms`：健康检查和平台列表。
- `GET /api/config`、`PUT /api/config`：配置读取和更新。
- `GET /api/state`：兼容状态入口。
- `GET /api/frontend/state`：前端全量快照。
- `GET /api/frontend/delta?since_version=...`：版本化前端增量；没有可用 delta 时返回可恢复的全量语义。
- `GET /api/frontend/icons`、`GET /api/i18n/{language}`：图标与国际化资源。
- `POST /api/frontend/action`：统一前端动作入口。请求可带 `frontend_version`，响应可带 `frontend_delta`，用于 GUI/WebUI 减少全量刷新。
- `POST /api/scan`、`POST /api/search`、`POST /api/crawl/start`、`POST /api/crawl/stop`、`POST /api/crawl/select`：采集和爬取控制。
- `POST /api/download`、`DELETE /api/video/{video_id}`、`POST /api/video/rename`、`GET /api/media/{video_id}`：下载与本地媒体操作。
- `GET /api/dir/list`、`POST /api/dir/change`、`POST /api/dir/pick-native`：目录浏览与保存目录变更。
- `GET /api/debug/latest-log`、`GET /api/debug/error-summary`：诊断接口。

## WebSocket

`app/web/ws_router.py` 负责连接路由，`app/web/ws_dispatcher.py` 负责实时状态分发，`app/web/ws_runtime.py` 管理运行期会话。连接建立或恢复时发送全量 `frontend_state`；稳定运行时以 `frontend_delta` 为主。

高频事件需要合并和背压：慢客户端不得拖垮下载核心，进度类 noisy 消息允许 latest-state-wins，完成、失败、删除等关键事件不允许被 noisy 消息挤掉。

## 操作约束

- 前端动作只描述用户意图，例如删除、重试、播放、打开目录。
- 控制器负责校验动作能否执行，并把请求转到下载管理器或服务层。
- 适配层只做状态转换和动作分发，不承载平台爬取业务。
- 新增 Web 字段时要同步 GUI、WebUI、测试和文档。
- 状态快照、日志查询、列表分页和可能较重的格式化工作不得阻塞 UI 主线程；GUI 走 `FrontendSnapshotWorker` / `ListPageWorker` / `LogQueryWorker`，Web 侧也要避免在高频请求里重复做全量昂贵计算。
