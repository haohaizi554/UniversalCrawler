# UCrawl CLI / SDK

UCrawl 提供 4 种调用方式，统一封装在 `cli/` 模块下。

## 快速使用

### 1. CLI（最快）

```bash
# 通用命令
ucrawl search --source douyin "测试" --max-items 10

# 平台别名
ucrawl douyin search "测试"

# 二次选择
ucrawl search --source bilibili "BV1xxx" --select "0,2,5"
ucrawl search --source bilibili "BV1xxx" --preload-choices "0|1,2|3"
```

`keyword` 的规范形式是 `source` 后的位置参数。历史脚本中的
`--keyword "测试"` 继续兼容；两种形式同时出现且值不一致时会直接报错。
显式 `--select` / `--exclude` 规则包含拼写错误或完全越界时会失败，绝不会退化为全选。

### 2. Python SDK

```python
from ucrawl import UcrawlSDK, RuleSelection, PipeSelection

sdk = UcrawlSDK()
result = sdk.search("douyin", "测试", max_items=10)

# 合集场景
sel = PipeSelection(preloaded_choices=[[0,1,2], [3,4]])
result = sdk.search("bilibili", "BV1xxx", selection=sel)
```

### 3. REST API + 启动时注入

```bash
python -m entry.web_entry --script my_automation.py --script-arg target=douyin
```

### 4. AI Skill（LLM）

SKILL 位置：`cli/skill/SKILL.md` 和 `.trae/skills/ucrawl/SKILL.md`

LLM 提示中提到 "ucrawl" 即可激活。

## 完整文档

- [cli-guide.md](../docs/cli/cli-guide.md) - CLI 完整调用说明
- [rest-api-reference.md](../docs/cli/rest-api-reference.md) - REST API 参考
- [python-sdk-guide.md](../docs/cli/python-sdk-guide.md) - Python SDK 指南

## 模块结构

```
cli/
├── __init__.py          # 公开包边界：再导出 SDK/选择策略，并注册历史模块别名
├── main.py              # CLI 入口 (`ucrawl` 命令)
├── script_runner.py     # 启动时脚本注入
├── commands/            # CLI 子命令
│   ├── search.py
│   ├── download.py
│   ├── interactive.py
│   ├── scan.py
│   ├── platforms.py
│   └── _alias.py        # 平台别名 (douyin/bilibili/...)
└── skill/               # AI Skill 封装
    ├── SKILL.md
    └── ucrawl_skill.py

shared/                  # 实现单源（CLI/Web/SDK 共用）
├── cli_runner_runtime.py
├── sdk_runtime.py
├── runtime_options.py
├── selection_runtime.py
├── interactive_selection.py
└── pipe_selection.py
```

## 安装

```bash
# 开发模式
pip install -e .

# 安装后 `ucrawl` 命令全局可用
```

## 关键设计点

1. **实现进 `shared/`**：`CLIRunner`、`UcrawlSDK`、选择策略与默认配置均在 `shared/`；`cli/` 只保留命令壳与公开包边界
2. **历史导入兼容**：`cli.sdk` / `cli.runner` 等旧路径由 `cli/__init__.py` 注册为零逻辑别名，对象身份与 canonical 模块一致
3. **同步 ask_user_selection**：monkey-patch spider.ask_user_selection，避免跨线程阻塞
4. **多种二次选择策略**：规则 / TTY 交互 / stdin 管道（合集场景用预加载）；GUI 选择仅在需要时桥接
5. **共享爬虫代码**：CLI、SDK、Web、GUI 都用相同的 `app/spiders/` 和 `app/core/plugins/`
