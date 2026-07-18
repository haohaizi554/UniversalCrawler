# CLI 契约收敛设计

## 背景与核验结论

当前 CLI 已具备通用搜索、平台快捷命令、直接下载、本地扫描、平台枚举和交互式引导，但命令契约存在多个事实来源：

- `shared/search_command_runtime.py` 为 `--source` 硬编码五个平台，而 SDK 和 `platforms` 命令依赖 plugin registry。
- `cli/commands/platform_base.py` 独立复制 search/download 参数，再由 `cli/main.py::_ensure_search_defaults()` 补齐遗漏字段。
- `cli/commands/_alias.py` 未被生产入口引用，仅由一组针对自身的测试保活。
- `download` 的位置参数名为 `video_id`，实际作为标题传给 SDK，同时又要求 `--url`；命令没有任何“上次搜索结果”状态。
- 每个平台快捷命令都暴露与平台无关的本地目录 `scan`。
- search 同时使用 `--timeout` 表示 HTTP 超时、`--run-timeout` 表示整次运行超时。
- `error`、`timeout` 和 `cancelled` 都映射为退出码 `1`。
- `import cli` 和 `import ucrawl` 都会主动导入并导出 `app.ui.gui_selection_strategy.GUISelection`。
- `cli/commands/interactive.py` 共 760 行，混合参数、TTY 展示、cookie/config 处理和工作流编排。

现有相关测试全部通过，但部分测试固定了孤儿实现和受污染的公共导出，因此“测试通过”并不代表这些边界适合长期演进。

## 目标

- 让 plugin registry 成为平台 ID、显示名和快捷别名的单一事实来源。
- 让通用命令与平台快捷命令复用完全相同的参数契约和 handler。
- 明确 `download` 是无状态直链下载，不暗示存在跨进程搜索状态。
- 让 HTTP 请求超时与整次命令超时在名称和数据流上无歧义。
- 为脚本编排提供稳定、可区分的退出码。
- 恢复 CLI、SDK 与 GUI 的包边界，导入 CLI/SDK 不产生 GUI 策略副作用。
- 将交互式引导拆成可独立理解和测试的职责单元。
- 更新活跃文档、AI skill 和示例，使公开用法与实际解析器一致。

## 非目标

- 不迁移到 Click、Typer 或其他命令行框架。
- 不让插件声明任意 argparse 参数；平台特定运行配置继续通过既有通用选项和 `--config` 传递。
- 不增加“保存上次搜索结果并继续下载”的持久化状态。
- 不改变 spider、downloader、SDK 返回 JSON 的字段结构。
- 不重构 GUI、WebUI 或插件发现机制本身。
- 不保留错误的 `ucrawl <platform> scan` 兼容入口。
- 不保留 `cli` 包作为 SDK 公共导入面的历史兼容层。

## 总体架构

CLI 收敛为入口、命令契约和共享运行时三层：

```text
entry/cli_entry.py / cli/__main__.py
  -> cli/main.py：构建根解析器、统一派发、处理中断
  -> cli/commands/*：argparse 契约、终端输出、退出码映射
  -> shared/* + app.core.plugin_registry：搜索、下载、选择、配置和平台能力
```

`BasePlugin` 增加与界面无关的 `aliases: tuple[str, ...]` 元数据。内置插件声明当前公开快捷别名：

- `douyin`: `dy`
- `xiaohongshu`: `xhs`
- `bilibili`: `bili`, `bl`
- `kuaishou`: `ks`
- `missav`: `miss`

插件的规范 ID 始终自动成为平台快捷命令；`aliases` 只补充额外拼写。CLI 构建解析器时从 registry 获取稳定快照，按 `sort_order` 排序，并验证平台 ID 与别名不冲突。外部插件无需修改 argparse 即可出现在 `--source` choices、平台快捷命令和 `platforms` 输出中。无效或冲突的插件元数据产生明确的 CLI 初始化错误，不静默丢失平台。

## 文件职责

### 根入口与平台目录

- `cli/main.py`
  - 提供可测试的 `build_parser()`。
  - 注册顶级 `search`、`download`、`scan`、`platforms`、`interactive`。
  - 调用动态平台快捷命令注册器。
  - 只通过解析后的 `_handler` 派发，不再按平台名称写条件分支。
  - 捕获 `KeyboardInterrupt` 并返回取消退出码。
- `cli/platform_catalog.py`
  - 把 plugin registry 快照投影为不可变 CLI 平台描述。
  - 校验 ID、别名和冲突。
  - 不导入 GUI。
- `cli/commands/platform_base.py`
  - 动态注册 `ucrawl <platform> search` 和 `ucrawl <platform> download`。
  - 调用通用 search/download 参数注册函数并预设 `source`。
  - 不再保存平台表，不再定义业务参数，不注册 `scan`。
- 删除 `cli/commands/_alias.py` 及其孤立测试。

### 命令参数与运行时

- `shared/search_command_runtime.py`
  - `add_search_arguments()` 接收动态平台 ID 集合以及可选的固定 `source`。
  - 固定平台入口不暴露可覆盖当前平台的 `--source`。
  - 所有入口都会得到完整且一致的 Namespace，无需补默认字段。
  - `http_timeout` 映射到 spider config 的 `timeout`；`command_timeout` 传给 `CLIRunner.timeout`。
- `shared/download_command_runtime.py`
  - 唯一注册 download 参数。
  - 位置参数改为 `url`，可选 `--title`；未提供标题时使用稳定的 URL 派生回退值。
  - 通用入口要求动态 choices 中的 `--source`，固定平台入口直接预设 `source`。
  - URL、source、timeout 和 config 在创建 SDK 前完成校验。
- `cli/commands/search.py` 与 `cli/commands/download.py`
  - 继续作为真实依赖装配和 stdout/stderr 输出的薄层。
  - 使用统一退出码映射，不自行发明状态规则。

### 公共包边界

- `shared/version.py`
  - 保存唯一 `__version__`，不导入 SDK、CLI 或 UI。
- `cli/__init__.py`
  - 仅标识 CLI 实现包并导出版本；不再导出 SDK、runner、选择策略或模块别名。
- `ucrawl/__init__.py`
  - 作为 SDK 公共入口，导出 SDK、runner 和非 GUI 选择策略。
  - 不导入或导出 `GUISelection`。
- `GUISelection`
  - 仅从 `app.ui.gui_selection_strategy` 使用，不属于 CLI/SDK 公共契约。
- 内部 `from cli import UcrawlSDK` 调用迁移到 `from ucrawl import UcrawlSDK` 或直接依赖规范 `shared` 模块。

这是一次有意的公共边界清理。明显污染架构的旧 `cli.*` SDK 模块别名和 GUI 导出直接移除；不为它们新增长期弃用代理。

## 命令契约

### 搜索

```text
ucrawl search --source <platform> <query> [options]
ucrawl <platform> search <query> [options]
```

- 两种形式共享同一参数注册函数和 handler。
- 默认搜索并下载；`--no-download` 只返回搜索结果。
- `--http-timeout <seconds>` 设置 spider HTTP 请求超时，并写入平台 config 的 `timeout`。
- `--timeout <seconds>` 设置整次搜索的截止时间，并传给 `CLIRunner`。
- 旧 `--run-timeout` 保留一个发布周期，作为 `--timeout` 的弃用别名；同时提供 stderr 弃用提示。
- 原 search `--timeout=HTTP` 直接迁移为 `--http-timeout`。同名参数无法同时表达新旧语义，因此不做含糊兼容。

### 直接下载

```text
ucrawl download --source <platform> <url> [--title <text>] [options]
ucrawl <platform> download <url> [--title <text>] [options]
```

- `download` 是无状态直链下载。
- URL 是必需位置参数，不再使用 `video_id` 或额外 `--url`。
- `--title` 只控制展示和文件标题；不承担资源身份语义。
- `--timeout` 表示整次直接下载截止时间。
- 平台快捷形式预设 source；通用形式从动态 registry choices 解析 source。
- search 结果的选择与下载仍由 search 自身的 selection 机制负责，不引入“上次搜索”状态。

### 本地与辅助命令

```text
ucrawl scan <directory>
ucrawl platforms
ucrawl interactive
```

- `scan` 只属于顶级本地命令。
- `platforms` 继续从 SDK/registry 输出当前平台。
- `interactive` 使用与 search 相同的 timeout 和配置语义。

## 退出码与输出契约

新增单一 `CliExitCode` 契约及状态映射：

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 运行失败或 CLI 初始化失败 |
| `2` | 参数、配置或命令用法错误 |
| `124` | 超时 |
| `130` | 用户取消、选择取消或 `KeyboardInterrupt` |

argparse 继续负责缺参、未知 choice 和非法标量类型，并自然退出 `2`。handler 在启动 runner/SDK 前校验 JSON config、正数 timeout、互斥选择规则和 URL；这些错误同样退出 `2`。runner/SDK 的 `ok`、`error`、`timeout`、`cancelled` 通过唯一映射函数转换为进程退出码。

机器可读 JSON 只写 stdout。spider 日志、人类可读错误、弃用提示和诊断信息写 stderr。结构化结果继续保留 `status` 字段，退出码不替代 JSON 状态。

## 交互式引导拆分

现有 `cli/commands/interactive.py` 拆为：

- `cli/commands/interactive.py`
  - 仅注册参数、装配依赖并调用工作流。
- `cli/interactive/prompts.py`
  - TTY 输入、编号选择、确认、颜色和终端展示。
- `cli/interactive/configuration.py`
  - cookie 定位与读取、平台配置合并、配置摘要。
- `cli/interactive/workflow.py`
  - 引导步骤、取消传播、执行与多轮循环。
- `cli/interactive/catalog.py`
  - 平台专属提示、示例和结果说明。
  - 未声明专属文案的外部插件使用根据 plugin name、placeholder 和 defaults 生成的通用引导。

拆分保持现有关键交互行为：平台选择、关键词输入、cookie 状态提示、配置编辑、保存目录、二次选择、确认、执行、取消以及“继续下一轮”。模块通过小型数据结构和显式函数参数传递状态，不新增全局可变状态。

## 错误与资源处理

- URL、source、timeout 和 config 必须在创建 runner/SDK 前校验。
- SDK、runner 或插件返回的运行错误保留原结构化结果，并映射为运行失败。
- timeout 映射为 `124`，不再依赖错误文本包含“超时”才能决定退出码。
- selection 返回 cancelled 或用户在交互流程取消时映射为 `130`。
- CLI 最外层捕获 `KeyboardInterrupt`，写一条简短 stderr 消息并返回 `130`。
- download 的 SDK 实例继续在 `finally` 中关闭。
- parser 构建阶段发现重复平台 ID、别名冲突或非法 alias 时，写明确 stderr 诊断并返回 `1`。
- JSON 输出模式下不得把警告或日志混入 stdout。

## 兼容与迁移

长期边界优先于维持错误契约：

- 保留平台规范 ID 和现有友好 aliases，但改由插件元数据生成。
- `--run-timeout` 只保留一个发布周期，提示迁移到 `--timeout`。
- search 原 `--timeout` HTTP 语义迁移到 `--http-timeout`。
- 删除 `--url` 与 `video_id` 位置参数语义，改为位置 URL 和 `--title`。
- 删除全部 `ucrawl <platform> scan`。
- 删除 `_alias.py`。
- 删除 `cli` 作为 SDK 导入面的旧模块 aliases，以及 CLI/SDK 顶层 `GUISelection` 导出。

活跃 CLI 指南、SDK 指南、README、AI skill 与示例同步更新。历史设计、计划和发布记录不回写。

## 测试策略

所有行为变更按 TDD 先增加失败测试，再实现最小改动。

### 平台与解析器契约

- 向隔离 registry 加入假平台后，通用 `--source` choices、规范平台快捷命令和额外 alias 自动出现。
- 平台 ID 或 alias 冲突产生明确初始化错误。
- 通用与平台快捷 search 解析出等价业务字段。
- 通用与平台快捷 download 解析出等价业务字段。
- 平台快捷帮助只包含 `search` 和 `download`，不包含 `scan`。
- 删除 `_alias.py` 后，生产代码与测试均无引用。

### 命令语义

- search 的 `--http-timeout` 进入 spider config，`--timeout` 进入 runner deadline。
- `--run-timeout` 仍能工作并向 stderr 发出弃用提示；与 `--timeout` 同时提供时退出 `2`。
- download 接受位置 URL 和可选 title，不再接受旧 `video_id --url` 组合。
- URL、source、timeout 和 config 校验在 SDK 构造前失败。

### 退出与输出

- `ok`、`error`、`timeout`、`cancelled` 分别映射为 `0`、`1`、`124`、`130`。
- 参数/config 错误映射为 `2`。
- `KeyboardInterrupt` 映射为 `130`。
- JSON 结果只进入 stdout；日志、错误和弃用提示只进入 stderr。

### 包边界

- 全新解释器中的 `import cli` 不加载任何 `app.ui` 模块。
- 全新解释器中的 `import ucrawl` 不加载任何 `app.ui` 模块。
- CLI 和 SDK 不再导出 `GUISelection`。
- 架构测试禁止 `cli/__init__.py` 和 `ucrawl/__init__.py` 依赖 `app.ui`。

### 交互式引导

- 现有平台引导文案、cookie/config 处理、摘要、取消和执行测试迁移到对应职责模块。
- 外部假插件没有专属 catalog 文案时仍可完成通用引导。
- 拆分后的 `cli/commands/interactive.py` 只保留 argparse 和依赖装配职责。

### 验证范围

至少运行：

```powershell
python -m pytest tests/unit/cli tests/contract/cli tests/contract/cross_interface/test_cli_sdk_api.py tests/contract/entry/test_cli_entry.py -q
python -m pytest tests/architecture/test_dependency_direction.py tests/architecture/test_file_size_limits.py tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q
python -m pytest tests --collect-only -q
python -m ruff check cli shared ucrawl tests/unit/cli tests/contract/cli
```

若 CLI 契约改动触及跨入口测试，再运行对应的 `tests/contract/entry/test_cross_entry_consistency.py`。最终验收使用受影响测试的完整集合，并检查工作树 diff 未包含用户现有的无关修改。

## 验收标准

- 新平台注册后无需修改 argparse 即可被通用 search、平台快捷命令和 `platforms` 识别。
- search/download 的通用与平台快捷形式只有一份参数定义和一条 handler 路径。
- `_ensure_search_defaults`、`_alias.py` 和重复平台表被删除。
- `download` 帮助和实现一致表达直链 URL 语义。
- `scan` 不再出现在任何平台快捷命令下。
- HTTP 与整次运行 timeout 名称、help、Namespace 和运行时传递一致。
- 编排方可稳定区分成功、运行失败、用法错误、超时和取消。
- 导入 CLI 或 SDK 不加载 GUI 策略。
- 交互式命令被拆成职责清楚、可独立测试的模块，现有关键行为不回退。
- 活跃文档与 AI skill 示例全部使用新命令契约。
- 受影响测试、架构契约、静态检查和测试收集验证通过。
