# UCrawl CLI / SDK

UCrawl 提供 4 种调用方式，统一封装在 `cli/` 模块下。

## 快速使用

### 1. CLI（最快）

```bash
# 通用命令
ucrawl search --source douyin --keyword "测试" --max-items 10

# 平台别名
ucrawl douyin search "测试"

# 二次选择
ucrawl search --source bilibili --keyword "BV1xxx" --select "0,2,5"
ucrawl search --source bilibili --keyword "BV1xxx" --preload-choices "0|1,2|3"
```

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

- [cli-guide.md](../../docs/cli/cli-guide.md) - CLI 完整调用说明
- [rest-api-reference.md](../../docs/cli/rest-api-reference.md) - REST API 参考
- [python-sdk-guide.md](../../docs/cli/python-sdk-guide.md) - Python SDK 指南

## 模块结构

```
cli/
├── __init__.py          # 暴露 SDK 入口
├── main.py              # CLI 入口 (`ucrawl` 命令)
├── runner.py            # CLIRunner - 核心执行器
├── sdk.py               # UcrawlSDK - Python SDK
├── selection.py         # 4 种选择策略
├── script_runner.py     # 启动时脚本注入
├── commands/            # CLI 子命令
│   ├── search.py
│   ├── scan.py
│   ├── platforms.py
│   └── _alias.py        # 平台别名 (douyin/bilibili/...)
└── skill/               # AI Skill 封装
    ├── SKILL.md
    └── ucrawl_skill.py
```

## 安装

```bash
# 开发模式
pip install -e .

# 安装后 `ucrawl` 命令全局可用
```

## 关键设计点

1. **独立进程 + 嵌入式 Qt**：CLI 启动时创建 QApplication（spider 派生自 QThread），不依赖 web 服务
2. **同步 ask_user_selection**：monkey-patch spider.ask_user_selection，避免 Qt 信号跨线程阻塞
3. **3 种二次选择策略**：规则 / TTY 交互 / stdin 管道（合集场景用预加载）
4. **共享爬虫代码**：CLI、SDK、Web、GUI 都用相同的 app/spiders/ 和 app/core/plugins/
