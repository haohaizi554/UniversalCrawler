# 开发指南

## 开发原则

- 新逻辑优先写到当前分层内，不绕过 controller / service / spider 边界。
- 优先补纯逻辑能力，再补 UI 绑定代码。
- 高风险改动必须同步补测试和文档。

当前 `3.6.21` 阶段的维护重点是 GUI/WebUI 状态一致性、前端刷新性能、下载并发控制、国际化覆盖和测试稳定性。涉及这些区域时，优先沿用 `FrontendStateService`、事件总线、后台 worker 和目录驱动的测试套件，不在页面层直接补业务分支。

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
python -m pytest -q
python tests/launcher.py --list
```

局部改动优先跑相关文件或目录套件，例如：

```bash
python -m pytest tests/unit/app/ui/test_main_window.py -q
python -m pytest tests/contract/frontend -q -k "theme or top_bar"
python tests/launcher.py --category unit
python tests/launcher.py --category contract
```

### 推荐原则

- 外部站点和浏览器行为尽量 mock，不把测试建立在真实网站稳定性上。
- 优先测试是否发出正确任务和是否走到正确分支，其次才是页面细节。
- 每次新增测试文件时，确保案例足够聚焦，不写占位式断言。
- 按隔离程度选择 `unit`、`integration`、`contract`、`e2e`、`architecture`、`performance`、`release` 或 `testkit`，并在套件后镜像生产命名空间。
- 内置套件只按目录发现；禁止通过精确文件、业务前缀 glob 或 include/exclude 白名单接入新测试。
- marker 只表达浏览器、网络、GUI、慢速、串行、Windows 等运行约束，并保持 `pyproject.toml` 严格注册。
- 具体规则以 `tests/AGENTS.md` 和 `tests/NAMING.md` 为准。

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
- `docs/fixes/README.md` 和对应复盘文档。`docs/fixes/archive/` 已合并上移，新增事故不要再放进 archive 子目录。
- `docs/engineering/frontend-refresh-and-concurrency.md`。涉及 GUI/WebUI 刷新、日志、主题、队列或 worker 的改动，应同步更新工程约束。

## 日志约定

- 任务尽量携带 `trace_id`。
- API 记录摘要，不写过量原始响应。
- 外部工具记录真实注入参数与结果。
- 错误优先使用明确异常类型，而不是统一 `Exception`。

## 兼容层策略

- 只保留真实仍被引用的兼容入口。
- 已切换完成的旧 shim 直接删除，不继续保留空壳。
- 新功能不再回填进历史大文件。

## GUI / WebUI 刷新与主题约束

- GUI 主题切换不能把按钮图标变化当成完成信号；快速点击必须按 latest-state-wins 合并到最后一次用户意图。
- 主题应用必须在 UI 构建完成后执行，不能在 `MainWindow._build_ui()` 前触碰未构建的 shell。
- 主题热路径不允许触发完整前端 snapshot；需要刷新前端状态时走 `FrontendSnapshotWorker` 或明确的 section 刷新。
- 不要冻结 `window_root`。确需临时冻结时，只能冻结已经可见的 `app_shell`，并用 `try/finally` 恢复。
- WebUI 与 GUI 的设置、主题、语言、日志翻译和自定义下拉框样式必须共享后端语义；新增字段时同时检查 `app/web/server.py` 的直连入口和 `app/web/rest_router.py` 的组合路由。

## 提交流程建议

1. 先补或更新测试。
2. 再改实现。
3. 执行完整测试。
4. 最后同步文档与目录 README。
