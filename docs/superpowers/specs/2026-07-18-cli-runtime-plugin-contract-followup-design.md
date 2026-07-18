# CLI Runtime 与插件交互契约二期设计

## 背景

上一轮已经完成 CLI 平台目录动态化、公开包边界清理、退出码细分、
search/download 参数收敛和 interactive 模块拆分。本轮核查发现，剩余问题主要
集中在“平台注册表只驱动平台列表，尚未驱动完整交互体验”和“部分命令/测试/文档
仍停留在迁移中间态”。

当前证据如下：

- `shared.search_command_runtime.run_search_command()` 在 `source` 与
  `_platform` 都缺失时把平台静默设为 `douyin`；直接调用 runtime 可得到
  `status=ok`，且 Runner 收到 `source=douyin`。
- search 的 `--timeout` 表示整次命令截止时间；download 的帮助文本写成
  “下载超时”。实际 `UcrawlSDK.download_video()` 从任务入队开始覆盖排队、
  活动 worker 和停止清理，是整次直接下载调用的截止时间，不是 HTTP 单请求超时。
- `cli/interactive/catalog.py` 保存五个平台的引导文案，
  `cli/interactive/configuration.py` 保存五个平台的鉴权文件和 Cookie 规则，
  `cli/interactive/workflow.py` 保存五个平台的参数菜单分支。外部插件虽然能被
  `platforms` 和 interactive 平台选择器列出，却无法声明完整引导、参数菜单、
  鉴权预检与确认摘要。
- `cli/commands/scan.py` 仍承担配置读取、参数归一化、SDK 生命周期、结构校验、
  输出格式化和退出状态映射，而 search/download 已把相同行为下沉到
  `shared/*_command_runtime.py`。
- `cli/script_runner.py` 没有生产调用，是 `app/web/script_api.py` 的旧重复实现；
  Web `--script` 已直接使用后者。
- `tests/unit/cli/test_defaults.py`、`test_pipe.py`、`test_runner.py`、
  `test_sdk.py`、`test_selection.py` 只测试 `shared.*`，不符合测试路径镜像生产
  命名空间的仓库契约。
- `mermaid/07-cli-sdk-runtime.md` 仍把 `cli/__init__.py` 描述为 SDK 再导出与
  历史别名入口；活跃测试指南仍引用上述旧测试路径。

## 目标

1. 让平台插件注册表同时成为平台交互、鉴权和确认摘要的唯一事实来源。
2. 让未提供高级元数据的外部插件仍获得安全、可用的通用引导；插件作者可通过
   强类型 SPI 获得与内置平台等价的交互体验。
3. 明确 `--timeout` 在所有 CLI 命令中都表示整次命令截止时间。
4. source 缺失必须在 shared runtime 边界返回 usage error，不能猜测平台。
5. scan 与 search/download 一样使用 shared command runtime，CLI 只做装配。
6. 删除 Web 脚本注入在 CLI 包中的重复副本。
7. 测试路径、活跃文档和架构图与当前生产边界一致，并以架构测试防止回退。

## 非目标

- 不改变 `UcrawlSDK.download_video(timeout=...)` 的公开参数名；该参数已经是
  整次直接下载调用的截止时间，重命名会造成不必要的 SDK 破坏。
- 不新增 `--command-timeout` 或 `--download-timeout`，避免在刚完成
  `--run-timeout` 迁移后再次制造 CLI 参数迁移。
- 不从任意 `get_default_config()` 字典猜测可交互字段，避免把 Cookie、token 或
  插件私有配置展示到终端。
- 不改写历史计划、规格、发布记录和复盘文档；只更新活跃指南与 Mermaid。
- 不把 Qt、终端颜色或 argparse 类型引入插件核心元数据层。

## 插件元数据契约

### 强类型模型

新增 `app/core/plugins/metadata.py`，定义以下不可变、无 UI 依赖的数据类型：

- `InteractiveChoice`
  - `label: str`
  - `value: str | int | float | bool | None`
  - `custom: bool = False`
- `InteractiveField`
  - `key: str`
  - `prompt: str`
  - `summary_label: str`
  - `choices: tuple[InteractiveChoice, ...]`
  - `custom_prompt: str = ""`
- `PlatformAuthSpec`
  - `mode: Literal["cookie", "none", "unspecified"]`
  - `config_key: str = ""`
  - `default_file: str = ""`
  - `cookie_names: tuple[str, ...] = ()`
  - `login_url: str = ""`
  - `login_description: str = ""`
  - `summary: str = ""`
- `PlatformInteractiveSpec`
  - `input_label: str`
  - `examples: tuple[str, ...]`
  - `empty_tip: str`
  - `result_tip: str`
  - `fields: tuple[InteractiveField, ...]`
  - `auth: PlatformAuthSpec`

这些类型提供 JSON-safe 的 `to_dict()`，供 SDK、Web 和 CLI 消费。模型只包含公开
说明和配置键名，不包含 Cookie 内容或绝对认证文件路径。

### BasePlugin 行为

`BasePlugin` 新增：

```python
interactive_spec: PlatformInteractiveSpec | None = None

def get_interactive_spec(self) -> PlatformInteractiveSpec:
    ...

def get_manifest(self) -> dict[str, Any]:
    ...
```

未声明 `interactive_spec` 的插件得到通用规范：

- 输入标签来自 `get_search_placeholder()`；
- examples 为空；
- 空结果提示用户检查输入、登录状态和插件配置；
- fields 为空，不猜测插件私有配置；
- auth 为 `unspecified`，终端显示“插件未声明鉴权规则”，而不是误报“不需要鉴权”。

内置五个平台在各自 `BasePlugin` 子类旁声明完整规范。新增平台只修改自身插件
定义，不修改 CLI workflow/configuration/catalog。

### 统一 manifest

`BasePlugin.get_manifest()` 返回：

```python
{
    "id": "...",
    "name": "...",
    "aliases": [...],
    "search_placeholder": "...",
    "description": "...",          # 非空时
    "settings": [...],             # 可用时
    "interactive": {...},
}
```

`UcrawlSDK.list_platforms()` 与 `WebController.get_platforms()` 都直接使用这个
manifest，不再各自复制字段投影逻辑。新增字段是非破坏性的；已有消费者继续读取
`id/name/search_placeholder`。

## Interactive 消费模型

`cli/interactive/catalog.py` 不再包含平台 ID 映射，只负责：

1. 从 `platform_info["interactive"]` 读取并规范化公开数据；
2. 对旧插件或测试桩缺失字段的情况应用安全通用默认值；
3. 拒绝错误类型并忽略无效 choice，而不是让引导崩溃。

`cli/interactive/workflow.py` 的平台配置阶段遍历 `fields`：

- 普通 choice 使用终端选择器；
- 当前值不在数值 choices 中时选择数值最近项；
- `custom=True` 的 choice 选中后调用 `input_with_default()`；
- 最终值写回字段的 `key`；
- workflow 不出现 `douyin/xiaohongshu/bilibili/kuaishou/missav` 分支。

`cli/interactive/configuration.py`：

- 根据 `PlatformAuthSpec` 查找配置文件、校验任一声明的 Cookie key；
- `cookie`、`none`、`unspecified` 三种模式分别展示已配置/无需鉴权/未声明；
- 确认摘要遍历字段规范并使用 choice label 展示当前值；
- MissAV proxy 的运行时规范化仍由共享 `compose_runtime_config()` 负责，不把
  平台特殊逻辑重新放回交互层。

## Timeout 契约

CLI 统一规则：

- `--timeout`：整次命令截止时间。
- `search --http-timeout`：spider HTTP 单请求超时。
- search/interactive 未指定 `--timeout` 时无限等待。
- download 未指定 `--timeout` 时保留当前 300 秒默认，避免直接下载无限挂起。
- search 的弃用参数 `--run-timeout` 继续保留既定兼容周期。

download argparse 的目标字段改为 `command_timeout`，shared runtime 内部也只使用
这一名称，再把值传给 SDK 的公开 `timeout` 参数。帮助文本、错误信息、CLI 指南和
AI Skill 都说明“整次下载命令超时”，从内部命名到用户文案保持一致。

## Search source 契约

`shared.search_command_runtime.resolve_source(args)` 只接受显式、非空的
`args.source`。缺失或空白时：

```python
("usage", {"status": "error", "error": "必须指定 --source 平台 ID"})
```

并保证：

- 不创建 selection strategy；
- 不读取平台默认配置；
- 不创建 `CLIRunner`；
- 不保留 `_platform` 或 `douyin` 隐式兜底。

通用 parser 用 required `--source`，平台快捷 parser 用
`set_defaults(source=<plugin id>)`，因此正常 CLI 入口不受影响。

## Scan shared runtime

新增 `shared/scan_command_runtime.py`：

- `ScanCommandEnv`
  - `UcrawlSDK_cls`
  - `get_default_scan_limit`
- `add_scan_arguments(parser)`
- `resolve_scan_limit(args, env)`
- `run_scan_command(args, env) -> tuple[str, dict | None, str | None]`
- `emit_result(result, pretty)`

runtime 负责参数校验、SDK 生命周期、结果结构校验、pretty/JSON 输出；返回
`ok/error/timeout/cancelled/usage` 语义状态。`cli/commands/scan.py` 只装配真实
依赖、调用 runtime 并映射 `CliExitCode`。

## 代码与测试归属

删除：

- `cli/script_runner.py`
- `tests/unit/cli/test_script_runner.py`

保留并继续验证规范实现：

- `app/web/script_api.py`
- `tests/contract/web/test_script_api.py`

迁移：

- `tests/unit/cli/test_defaults.py`
  → `tests/unit/shared/test_runtime_options.py`
- `tests/unit/cli/test_pipe.py`
  → `tests/unit/shared/test_pipe_selection.py`
- `tests/unit/cli/test_runner.py`
  → `tests/unit/shared/test_cli_runner_runtime.py`
- `tests/unit/cli/test_sdk.py`
  → `tests/unit/shared/test_sdk_runtime.py`
- `tests/unit/cli/test_selection.py`
  → `tests/unit/shared/test_selection_runtime.py`

必要时把现有 `tests/unit/shared/test_runtime_helpers.py` 中混合的
runtime adapters/selection 测试分别归并到对应 owner，避免新旧文件继续重叠。

## 文档与防回退

更新以下活跃文档：

- `app/core/plugins/README.md`
- `cli/README.md`
- `docs/cli/cli-guide.md`
- `docs/guides/testing.md`
- `cli/skill/SKILL.md`
- `mermaid/02-entrypoints-and-hosts.md`
- `mermaid/07-cli-sdk-runtime.md`

架构测试增加以下约束：

- `cli/script_runner.py` 不存在；
- search/download/scan 三个命令都直接装配 shared command runtime；
- `cli/interactive` 不再拥有五个平台 ID 映射；
- `cli/__init__.py` 与 `ucrawl/__init__.py` 不依赖 `app.ui`；
- CLI runtime Mermaid 不再包含“公开再导出/历史别名”，并包含
  `scan_command_runtime` 和 `ucrawl/__init__.py` 公共 SDK 边界。

## 兼容性

- CLI 命令名、位置参数和 `--timeout` 拼写不变。
- SDK `download_video(timeout=...)` 不变。
- 平台 manifest 只增加字段，不删除已有字段。
- 未升级的外部插件无需修改即可继续运行，并获得通用 interactive manifest。
- 外部插件升级后可声明强类型交互/鉴权规范，无需修改 UCrawl CLI。
- 测试文件迁移只改变收集路径，不改变测试语义和套件归属。

## 验收标准

1. 直接调用 search runtime 且 source 缺失时返回 usage，Runner 未创建。
2. search/download 的 `args.command_timeout` 都表示整次命令时间。
3. 外部测试插件的 guide、choice、custom input、auth 和摘要能通过 manifest
   驱动 interactive，不修改 CLI 平台分支。
4. 五个内置平台的现有引导、数量/页数/偏好/代理菜单和 Cookie 状态不退化。
5. `cli/commands/scan.py` 不再定义 SDK 运行与输出格式化逻辑。
6. `cli/script_runner.py` 和其 CLI 单测不存在，Web script API 套件通过。
7. shared 测试全部位于 `tests/unit/shared/`，CLI 测试只验证 CLI owner。
8. 活跃 Mermaid 和指南显示 `ucrawl` 为 SDK 公共入口、`cli` 为命令实现包。
9. 相关单元、契约、架构、测试目录、收集、Ruff 和全量测试通过。
