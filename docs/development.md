# 开发指南

## 新代码放哪里

- 配置相关
  - 放 `app/config`

- 下载器相关
  - 放 `app/core/downloaders`

- 插件注册与平台配置组件
  - 入口放 `app/core/plugin_registry.py`
  - 实现放 `app/core/plugins`

- 平台爬虫相关
  - 放 `app/spiders/<platform>`

- 数据模型
  - 放 `app/models`

- 通用工具函数
  - 放 `app/utils`

- 与 UI 无关的业务逻辑
  - 放 `app/services`

- 错误类型
  - 放 `app/exceptions`

## 新平台接入建议

推荐最少新增：

- `app/spiders/<platform>/parser.py`
- `app/spiders/<platform>/task_builder.py`
- `app/spiders/<platform>/spider.py`
- `app/core/downloaders/<platform>.py`

如果平台需要额外设置 UI，建议同步补：

- `app/core/plugins/definitions.py`
- `app/core/plugins/settings_builders.py`

## 日志约定

- 任务必须尽量带 `trace_id`
- API 层只记录有效摘要
- 外部工具必须记录实际注入参数
- 错误优先抛出更具体的异常类型

## 测试约定

- 纯逻辑优先写单元测试
- 外部站点和浏览器逻辑尽量做接口隔离后再测
- 不要把 UI 联动测试和网络测试混在一起
- 新增测试文件时，优先保证每个测试文件至少有 4 个有效用例，避免只有占位式覆盖

## 兼容层策略

- 旧模块不立即删
- 只保留仍有真实引用的兼容入口
- 新功能不再继续往旧大文件追加
- 空壳、空文件、未被引用的历史残留应尽快清理
- 一旦引用已全部切换，旧 shim 文件应直接删除，不继续保留
