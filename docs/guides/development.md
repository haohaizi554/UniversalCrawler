# 开发指南

## 开发原则

- 新逻辑优先写到当前分层内，不绕过 controller / service / spider 边界。
- 优先补纯逻辑能力，再补 UI 绑定代码。
- 高风险改动必须同步补测试和文档。

## 新代码放哪里

- `app/config`
  - 配置模型、默认值、配置迁移、兼容读取。
- `app/core/downloaders`
  - 平台下载器、外部工具包装、下载策略分流。
- `app/core/plugins`
  - 平台插件定义、设置控件与注册表。
- `app/spiders/<platform>`
  - 平台采集实现，遵循 `spider / parser / task_builder`。
- `app/services`
  - 与 UI 无关的业务逻辑和文件/调试/认证服务。
- `app/models`
  - 统一数据模型。
- `app/utils`
  - 文件名清洗、格式化和路径工具。

## 新平台接入最小路径

至少新增以下文件：

- `app/spiders/<platform>/spider.py`
- `app/spiders/<platform>/parser.py`
- `app/spiders/<platform>/task_builder.py`
- `app/core/downloaders/<platform>.py`

如果平台需要 UI 配置项，再同步修改：

- `app/core/plugins/definitions.py`
- `app/core/plugins/settings_builders.py`
- `app/core/plugin_registry.py`

## 测试要求

### 必测类型

- 纯逻辑：解析、配置、路径、任务装配。
- 主流程：爬虫输入分流、登录回退、下载任务发射。
- 控制器：列表状态、入队、删除、停止、目录扫描。
- 下载：扩展名、保存路径、下载器选择、工具参数。

### 推荐命令

```bash
python -m compileall app tests main.py
python -m unittest discover -s tests
```

### 推荐原则

- 外部站点和浏览器行为尽量 mock，不把测试建立在真实网站稳定性上。
- 优先测试是否发出正确任务和是否走到正确分支，其次才是页面细节。
- 每次新增测试文件时，确保案例足够聚焦，不写占位式断言。

## 文档要求

以下情况请同步更新 Markdown：

- 目录职责变更
- 插件注册入口变更
- 新平台接入
- 新增测试策略或运行前置条件
- 构建流程、打包依赖或运行方式改变

建议优先维护：

- 根目录 `README.md`
- `architecture.md`
- `docs/guides/api.md`
- `testing.md`
- 对应目录下的 `README.md`

## 日志约定

- 任务尽量携带 `trace_id`。
- API 记录摘要，不写过量原始响应。
- 外部工具记录真实注入参数与结果。
- 错误优先使用明确异常类型，而不是统一 `Exception`。

## 兼容层策略

- 只保留真实仍被引用的兼容入口。
- 已切换完成的旧 shim 直接删除，不继续保留空壳。
- 新功能不再回填进历史大文件。

## 提交流程建议

1. 先补或更新测试。
2. 再改实现。
3. 执行完整测试。
4. 最后同步文档与目录 README。

