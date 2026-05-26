# 架构说明

## 当前目标

本轮重构的目标不是彻底推翻现有项目，而是在保证现有功能可运行的前提下，把最容易继续膨胀的部分先拆开：

- 配置统一收口
- 下载器模块化
- 四个平台爬虫逐步改造成 `采集 / 解析 / 任务装配`
- 控制层持续瘦身
- 错误分类更细，日志更准

## 当前结构

- `main.py`
  - 只保留应用启动入口

- `app/config`
  - `settings.py` 提供统一配置模型和默认值
  - `constants.py` 管理常量

- `app/core`
  - `download_manager.py` 负责下载队列和 worker 调度
  - `plugin_registry.py` 作为插件注册统一入口
  - `plugins/` 负责插件定义、设置组件构建和实际注册表实现
  - `downloaders/` 负责各平台下载和外部工具封装
  - `downloaders/external.py` 统一收口外部工具命令构建

- `app/services`
  - `file_service.py` 管理本地文件扫描、重命名、删除
  - `debug_service.py` 负责日志文件打开与 trace 复制
  - `auth_service.py` 负责认证文件读写

- `app/spiders`
  - 平台主实现已下沉到 `spiders/<platform>/spider.py`
  - 新代码优先往子包的 `parser / task_builder / spider` 放

- `app/models`
  - `video_item.py` 负责下载任务与媒体条目模型

- `app/utils`
  - `filenames.py` 收口文件名清理
  - `formatting.py` 收口格式化工具

- `app/ui`
  - `components/` 放主界面复用组件
  - `dialogs/` 放弹窗
  - `styles/` 放主题样式
  - `widgets/` 放自定义控件

- `app/exceptions`
  - 提供基础异常、配置异常、服务异常、爬虫异常、下载异常

## 设计原则

- 新结构优先
  - 新增逻辑优先写进 `config / services / spiders/<platform> / core/downloaders`

- 旧接口兼容
  - 只在确有运行时引用时保留兼容层，已无引用的 shim 直接删除
  - 当前插件注册只保留 `app.core.plugin_registry` 这一层入口，不再继续维护重复壳文件

- 高耦合优先拆
  - 优先拆长文件中的“解析”和“任务装配”，因为这两块最容易和 UI、下载、日志耦合

- 外部依赖显式化
  - `ffmpeg`、`N_m3u8DL-RE` 等外部工具单独封装，避免平台下载器直接散写命令

## 平台分层约定

每个平台逐步统一为三层：

- `spider`
  - 负责页面访问、流程控制、用户交互、信号发射

- `parser`
  - 负责解析页面数据、接口返回、标题、分组、资源结构

- `task_builder`
  - 负责把解析结果转换成统一下载任务或 `VideoItem`

## 仍可继续优化

- 为 `config` 增加更多业务分组和字段验证
- 为 `exceptions` 增加更具体的错误码映射
- 为 `services` 补更多可测试的纯逻辑能力
- 把 `models` 继续细分为更多业务模型，如任务项、用户信息、媒体索引
- 把 `ui/dialogs / ui/styles / ui/widgets` 继续按主题或功能拆成更多子模块
