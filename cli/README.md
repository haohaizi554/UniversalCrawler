# UCrawl CLI

`cli` 是命令行实现包；Python SDK 的公开入口是 `ucrawl`。平台命令和
`--source` 选项由 plugin registry 动态生成，新增平台不需要再修改
`argparse` 的硬编码列表。`ucrawl platforms` 与交互引导都消费插件的
manifest；外部插件可声明引导文案、交互字段和鉴权元数据。

## 快速使用

```bash
# 搜索：HTTP 超时与整次命令超时含义分离
ucrawl search --source douyin "测试" --http-timeout 15 --timeout 120
ucrawl douyin search "测试" --http-timeout 15 --timeout 120

# 直接下载：URL 是位置参数，标题可选
ucrawl download --source douyin "https://example/video.mp4" --title "示例"
ucrawl douyin download "https://example/video.mp4" --title "示例"

# 本地目录扫描只属于顶层命令
ucrawl scan "./downloads"

# 动态平台目录与交互引导
ucrawl platforms --pretty
ucrawl interactive
```

超时参数遵循一套固定语义：

- search 的 `--http-timeout` 只控制 spider HTTP 请求。
- search / interactive 的 `--timeout` 控制整次命令，默认不设期限。
- download 的 `--timeout` 控制整次直接下载命令，默认 300 秒。

search / interactive 的 `--run-timeout` 暂时保留为 `--timeout` 的弃用
别名，不能与 `--timeout` 同时使用。

平台快捷入口只提供 `search` 和 `download`。本地目录扫描没有平台语义，
因此不存在 `ucrawl <platform> scan` 之类的命令。

## 二次选择

```bash
ucrawl search --source bilibili "BV1xxx" --select "0,2,5"
ucrawl search --source bilibili "BV1xxx" --preload-choices "0|1,2|3"
```

显式 `--select` / `--exclude` 规则包含非法 token 或完全越界时会按参数错误
退出，不会静默退化为全选。

## 退出码

| 退出码 | 含义 |
| ---: | --- |
| `0` | 成功 |
| `1` | 运行或初始化失败 |
| `2` | 参数、配置或其他用法错误 |
| `124` | 超时 |
| `130` | 用户或上游取消 |

## Python SDK

SDK、选择策略和函数式 API 都从 `ucrawl` 导入：

```python
from ucrawl import PipeSelection, RuleSelection, UcrawlSDK

with UcrawlSDK() as sdk:
    result = sdk.search("douyin", "测试", max_items=10)
```

不要从 `cli` 导入 SDK 或 GUI 策略。`cli/__init__.py` 只暴露版本信息，
避免命令实现、SDK 和桌面 UI 的包边界互相污染。

## 目录职责

```text
cli/
├── __init__.py          # 轻量 CLI 包边界
├── main.py              # 唯一根解析器与命令派发
├── platform_catalog.py  # plugin registry -> CLI 平台目录
├── exit_codes.py        # 语义状态 -> 稳定进程退出码
├── commands/            # argparse 适配器和命令 handler
├── interactive/         # catalog/configuration/prompts/workflow
└── skill/               # AI Skill 权威副本与包装器

shared/                  # search/download/scan、SDK、runner 与选择运行时
ucrawl/                  # Python SDK 公开包
```

## 完整文档

- [CLI 调用说明](../docs/cli/cli-guide.md)
- [Python SDK 指南](../docs/cli/python-sdk-guide.md)
- [REST API 参考](../docs/cli/rest-api-reference.md)

开发模式安装：

```bash
pip install -e .
```
