# UCrawl Python SDK 指南

> **重要**：请先阅读 [cli-guide.md](./cli-guide.md) 了解 UCrawl 的整体设计。

SDK 是 UCrawl 的 Python 函数式入口，让你可以用最少的代码集成爬虫能力。
公开 API 始终从 `ucrawl` 导入，不要从 `cli` 导入 SDK。CLI 的
`--timeout` 对应 SDK `run_timeout`；CLI `--http-timeout` 对应 SDK
默认配置中的 `{"timeout": N}`。

## 快速开始

### 安装

```bash
# CLI 安装后，SDK 即可用
pip install -e .
```

### 第一次调用

```python
from ucrawl import search

# 最简单的搜索
result = search("douyin", "测试", max_items=10)
print(f"找到 {len(result['items'])} 个视频")
for item in result["items"]:
    print(f"  {item['title']}: {item['url']}")
```

### 进阶：使用 SDK 类

```python
from ucrawl import UcrawlSDK

# 创建 SDK 实例
sdk = UcrawlSDK(save_dir="downloads", verbose=True)

# 多次调用（共享 QApplication）
r1 = sdk.search("douyin", "测试1", max_items=5)
r2 = sdk.search("bilibili", "测试2", max_items=10)
r3 = sdk.search("missav", "ABC-123", individual_only=True)

# 上下文管理器（自动清理）
with UcrawlSDK() as sdk:
    r = sdk.search("douyin", "测试")
```

## 核心 API

### UcrawlSDK 类

```python
class UcrawlSDK:
    def __init__(
        self,
        save_dir: str = "downloads",
        verbose: bool = False,
        config: dict | None = None,
    ):
        """初始化 SDK。"""

    def search(
        self,
        source: str,
        keyword: str,
        save_dir: str | None = None,
        selection: SelectionStrategy | str | list[int] | None = None,
        timeout: float | None = None,
        download: bool = True,
        run_timeout: float | None = None,
        **config,
    ) -> dict:
        """执行一次搜索并返回结果。"""

    def list_platforms(self) -> list[dict]:
        """列出所有可用平台。"""

    def scan_directory(self, directory: str, scan_limit: int = 1000) -> dict:
        """扫描本地目录。"""
```

### 函数式 API

```python
from ucrawl import search, list_platforms, scan_directory

result = search(source, keyword, **config)
platforms = list_platforms()
items = scan_directory(directory, scan_limit)
```

## 二次选择详解

### 4 种策略

```python
from ucrawl import (
    RuleSelection,        # 规则
    InteractiveSelection, # TTY 交互
    PipeSelection,        # stdin 管道
    AutoSelection,        # 自动选择
)
```

#### 1. RuleSelection

```python
# 全选
sel = RuleSelection(all_items=True)

# 只选第一个
sel = RuleSelection(first=True)

# 只选最后一个
sel = RuleSelection(last=True)

# 指定索引
sel = RuleSelection(select="0,2,5")
sel = RuleSelection(select="0,2-5")  # 范围

# 排除
sel = RuleSelection(all_items=True, exclude="1,3")

# 组合：全选但排除某些
sel = RuleSelection(select=None, exclude="1,3")
```

#### 2. InteractiveSelection

```python
# TTY 终端交互（用户在终端看到候选列表并输入索引）
sel = InteractiveSelection()
```

#### 3. PipeSelection

```python
# 单次选择（从 stdin 读一次）
sel = PipeSelection()

# 预加载（用于合集场景的多次选择）
sel = PipeSelection(preloaded_choices=[
    [0, 1, 2],  # 第 1 轮选 0,1,2
    [3],         # 第 2 轮选 3
    [],          # 第 3 轮不选
    list(range(10)),  # 第 4 轮选 0-9
])
```

#### 4. AutoSelection

```python
# 自动选择：有 TTY→交互，无 TTY→管道，否则→全选
sel = AutoSelection()
```

### 简化字符串

```python
sdk.search("douyin", "测试", selection="all")     # 全选
sdk.search("douyin", "测试", selection="first")   # 只选第一个
sdk.search("douyin", "测试", selection="last")    # 只选最后一个
sdk.search("douyin", "测试", selection="0,2,5")   # 指定索引
sdk.search("douyin", "测试", selection=[0,2,5])   # 列表
```

## 各平台参数

### 抖音 (douyin)

```python
with UcrawlSDK(config={"timeout": 10}) as sdk:
    result = sdk.search(
        "douyin",
        "测试关键词",  # 或抖音号 / 视频链接
        max_items=20,        # 最大视频数
        run_timeout=120,     # 整次运行超时
    )
```

### B站 (bilibili)

```python
result = sdk.search(
    "bilibili",
    "BV1xxx",  # BV 号 / 搜索关键词 / 用户 mid
    max_pages=1,         # 翻页数
    max_items=30,        # 最大视频数
)
```

### 快手 (kuaishou)

```python
result = sdk.search(
    "kuaishou",
    "测试关键词",  # 或快手号 / 视频链接
    max_items=20,
)
```

### MissAV (missav)

```python
result = sdk.search(
    "missav",
    "ABC-123",  # 作品 ID / 搜索关键词 / URL
    individual_only=False,        # 只看单体
    priority="中文字幕优先",       # "中文字幕优先" / "无码流出优先"
    proxy="http://127.0.0.1:7890", # 代理 URL
)
```

## 返回结构

```python
{
    "status": "ok" | "error" | "timeout" | "cancelled",
    "source": "douyin",
    "keyword": "测试",
    "save_dir": "downloads",
    "items": [
        {
            "id": "v_abc123",
            "url": "https://...",
            "title": "视频标题",
            "source": "douyin",
            "status": "✅ 完成",
            "progress": 100,
            "local_path": "/path/to/file.mp4",
            "content_type": "video",
            "meta": {...},
        }
    ],
    "logs": ["📡 开始搜索...", "✅ 已加载 10 个项目"],
    "selection_count": 1,  # 二次选择调用次数
    "elapsed": 12.34,      # 耗时（秒）
    "error": None,
}
```

## 合集场景实战

### 场景 1：B 站合集

```python
from ucrawl import UcrawlSDK, PipeSelection

sdk = UcrawlSDK()

# 假设爬虫在一次运行中会调用 3 次 ask_user_selection：
# - 第 1 次：合集包含 3 个分季 (selection of seasons)
# - 第 2 次：第 1 季的视频
# - 第 3 次：第 2 季的视频

sel = PipeSelection(preloaded_choices=[
    [0, 1, 2],          # 全选所有分季
    list(range(10)),    # 第 1 季全选
    [3, 4, 5],          # 第 2 季选 3,4,5
])

result = sdk.search("bilibili", "BV1xxx合集标题", selection=sel)
```

### 场景 2：抖音多用户

```python
sel = PipeSelection(preloaded_choices=[
    [0],                 # 选第一个用户
    list(range(50)),     # 全选该用户视频
])

result = sdk.search("douyin", "搜索关键词", selection=sel)
```

### 场景 3：MissAV 多作品

```python
sel = PipeSelection(preloaded_choices=[
    [0, 1, 2, 3],       # 前 4 个作品都下
])

result = sdk.search("missav", "ABC", selection=sel)
```

## 批量处理

```python
from ucrawl import UcrawlSDK
import json

sdk = UcrawlSDK()

keywords = ["关键词1", "关键词2", "关键词3"]
results = []

for kw in keywords:
    result = sdk.search("douyin", kw, max_items=5, selection="all")
    results.append({
        "keyword": kw,
        "count": len(result["items"]),
        "items": result["items"],
    })

# 写入文件
with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
```

## 异步 / 并发（单实例）

UCrawl SDK 是**同步**的（基于 QThread + Qt 信号）。如果需要并发，需要**多进程**或**多实例**：

```python
import multiprocessing

def worker(keyword):
    from ucrawl import UcrawlSDK
    sdk = UcrawlSDK()  # 每个进程一个 QApplication
    return sdk.search("douyin", keyword, max_items=5)

keywords = ["kw1", "kw2", "kw3", "kw4"]

with multiprocessing.Pool(4) as pool:
    results = pool.map(worker, keywords)
```

## 自定义 Selection 策略

```python
from ucrawl import UcrawlSDK

class TitleFilter:
    """只选标题包含特定关键词的。"""

    def __init__(self, must_contain: str, case_sensitive: bool = False):
        self.must_contain = must_contain
        self.case_sensitive = case_sensitive

    def select(self, items, prompt=""):
        indices = []
        needle = self.must_contain if self.case_sensitive else self.must_contain.lower()
        for i, item in enumerate(items):
            title = item.get("title", "") if isinstance(item, dict) else str(item)
            if not self.case_sensitive:
                title = title.lower()
            if needle in title:
                indices.append(i)
        return indices

sel = TitleFilter(must_contain="测试", case_sensitive=False)
sdk = UcrawlSDK()
result = sdk.search("douyin", "测试", selection=sel)
```

## 错误处理

```python
from ucrawl import UcrawlSDK

sdk = UcrawlSDK()
result = sdk.search("douyin", "测试", max_items=10, run_timeout=30)

if result["status"] != "ok":
    print(f"❌ 错误: {result.get('error', '未知')}")
else:
    print(f"✅ 找到 {len(result['items'])} 个项目")
    for item in result["items"]:
        print(f"  - {item['title']}")
```

`status` 可能的值：
- `ok` 成功
- `error` 错误（看 `error` 字段）
- `timeout` 超时
- `cancelled` 用户取消

## 与其他模块的集成

### Flask / FastAPI

```python
from flask import Flask, request, jsonify
from ucrawl import UcrawlSDK

app = Flask(__name__)
sdk = UcrawlSDK()  # 全局共享

@app.route("/api/search")
def search():
    source = request.args.get("source", "douyin")
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"status": "error", "error": "keyword 必填"}), 400
    result = sdk.search(source, keyword, max_items=20, selection="all")
    return jsonify(result)
```

### Celery 任务

```python
from celery import shared_task
from ucrawl import UcrawlSDK

@shared_task
def crawl_task(source, keyword):
    sdk = UcrawlSDK(save_dir="/data/crawl")
    return sdk.search(source, keyword, max_items=50, selection="all")
```

### Jupyter Notebook

```python
from ucrawl import UcrawlSDK

# Jupyter 内核自带事件循环
sdk = UcrawlSDK(verbose=True)
result = sdk.search("douyin", "测试", max_items=10)

# 在 notebook 中显示
from IPython.display import display, HTML
display(HTML(f"<h3>找到 {len(result['items'])} 个视频</h3>"))
for item in result["items"]:
    display(HTML(f"<a href='{item['url']}' target='_blank'>{item['title']}</a>"))
```

## 调试技巧

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from ucrawl import UcrawlSDK

# 详细模式（spider 日志会输出到 stderr）
sdk = UcrawlSDK(verbose=True)
result = sdk.search("douyin", "测试")
```

或者用 `pretty=True` 风格输出（CLI 中可用）：

```python
result = sdk.search("douyin", "测试")
print(json.dumps(result, ensure_ascii=False, indent=2))
```
