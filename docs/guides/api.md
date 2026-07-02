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

`app/web/rest_router.py` 负责 HTTP 接口。REST 适合初始加载、手动刷新、配置读取和明确用户动作，不适合承载每个进度信号。

典型接口语义：

- 获取前端状态快照。
- 启动、停止、删除、重试任务。
- 更新配置项。
- 执行工具箱动作。

## WebSocket

`app/web/ws_router.py` 负责实时状态推送。连接建立或恢复时发送全量 `frontend_state`；稳定运行时以 `frontend_delta` 为主。

高频事件需要合并和背压：慢客户端不得拖垮下载核心，进度类 noisy 消息允许 latest-state-wins，完成、失败、删除等关键事件不允许被 noisy 消息挤掉。

## 操作约束

- 前端动作只描述用户意图，例如删除、重试、播放、打开目录。
- 控制器负责校验动作能否执行，并把请求转到下载管理器或服务层。
- 适配层只做状态转换和动作分发，不承载平台爬取业务。
- 新增 Web 字段时要同步 GUI、WebUI、测试和文档。
