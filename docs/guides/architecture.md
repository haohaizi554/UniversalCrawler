# 架构指南

Universal Crawler Pro 是一个多平台视频、图文采集与下载系统，支持 GUI、CLI、SDK 和 Web API 四种入口。当前架构目标是：采集、解析、队列、下载、日志、前端刷新各司其职，通过统一状态适配层对 GUI 和 WebUI 暴露同一套页面语义。

## 当前分层

| 层级 | 主要模块 | 职责 |
| --- | --- | --- |
| 入口层 | `main.py`、CLI、Web 路由、PyQt 主窗口 | 启动应用、接收用户操作、连接控制器 |
| 控制层 | `app/controllers/application_controller.py`、各 mixin | 协调任务启动、停止、删除、重试和配置变更 |
| 服务层 | `app/services/frontend_state_service.py`、调试、文件、Windows 文件关联服务 | 提供 GUI/WebUI 统一状态、动作适配、文件操作和诊断能力 |
| 核心层 | `app/core/download_manager.py`、`app/core/events.py`、`app/core/state.py` | 管理任务状态、事件广播、下载并发和生命周期 |
| 平台层 | 各平台 spider / downloader / parser | 平台输入识别、资源解析、下载实现 |
| 前端层 | `app/ui`、`app/web/static` | 统一 7 页结构、局部刷新和用户交互 |

## GUI / WebUI 统一页面

GUI 和 WebUI 共享 7 个业务页面：下载队列、正在下载、已完成、失败列表、日志中心、配置中心、工具箱。页面字段、状态值和操作语义应通过 `FrontendStateService` 保持一致。

前端不得直接调用 Spider、Downloader、Parser 或 TaskBuilder。页面只读取 `queue_items`、`active_downloads`、`completed_items`、`failed_items`、`log_items`、`settings_snapshot`、`toolbox_items` 和 `app_status`，动作通过控制器或适配服务转发。

## 事件与刷新

高频下载进度和日志不能直接驱动整页重绘。当前工程使用前端事件聚合和局部快照思路：

- 关键事件立即推送，例如完成、失败、删除、停止。
- 高频事件合并推送，例如进度、速度和日志追加。
- 当前可见页面刷新内容区；不可见页面只更新侧栏角标和底部状态栏。
- GUI 表格优先按 id 更新行；WebUI 使用 keyed patch 和 reducer 合并状态。

细化执行规则见 [前端刷新与并发控制工程实践](../engineering/frontend-refresh-and-concurrency.md)。

## 下载流水线

长期原则是生产者消费者模型：解析只负责产出候选资源，队列只负责排序和状态，下载器只负责下载，日志只记录事实。并发数表示“最大同时下载任务数”，不是一次任务走完才启动下一个。图片资源可以有独立并发上限，但也必须受工程化限流保护，避免 UI 和网络洪峰。

## 配置与持久化

配置中心负责展示和修改可持久化设置。带“推荐”的选项必须与默认配置一致；平台数量限制需要按平台语义显示，例如 Bilibili 使用页数，小红书使用笔记数，视频平台使用视频数。

设置控件、下拉框、主题语言和国际化规则见 [设置、下拉框与国际化契约](../engineering/settings-ui-contract.md)。

## 兼容边界

重构前端和适配层时不得破坏 CLI、SDK、Web API、测试体系和 PyInstaller 打包。新增字段应保持非破坏性；删除字段前必须同步 GUI/WebUI、测试和文档。
