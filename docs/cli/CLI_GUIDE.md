# UCrawl CLI 调用说明

UCrawl 提供 4 种调用方式，让你可以从任何环境、任何程序中调用爬虫能力：

| 方式 | 适用场景 | 复杂度 |
|---|---|---|
| **CLI 命令行** | 一次性任务、shell 脚本、人工调试 | ⭐ |
| **Python SDK** | 集成到 Python 项目、批量处理 | ⭐⭐ |
| **REST API + 启动时注入** | 集成到 web 服务、自动化部署 | ⭐⭐⭐ |
| **AI Skill (LLM 调用)** | 让 Claude 等 LLM 直接调用 | ⭐⭐⭐⭐ |

## 方式 1：CLI 命令行

### 安装

```bash
# 开发模式（推荐，修改代码立即生效）
pip install -e .

# 全局安装
pip install .
```

安装后 `ucrawl` 命令全局可用。

### 快速开始

```bash
# 通用命令
ucrawl search --source douyin --keyword "测试" --max-items 10

# 平台别名（更短）
ucrawl douyin search "测试" --max-items 10

# 漂亮输出
ucrawl search --source missav --keyword "ABC-123" --pretty

# JSON 输出（适合管道）
ucrawl search --source bilibili --keyword "测试" --json | jq '.items[].title'
```

### 完整参数

```bash
ucrawl search --help
```

关键参数：

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--source` / `-s` | ✅ | - | 平台：`douyin` / `bilibili` / `kuaishou` / `missav` |
| `keyword` | ✅ | - | 搜索关键词 / 视频链接 / 用户 ID |
| `--save-dir` / `-d` | ❌ | `downloads` | 保存目录 |
| `--max-items` | ❌ | 平台默认 | 最大视频数 |
| `--max-pages` | ❌ | 1 | 翻页数（仅 B站） |
| `--individual-only` | ❌ | False | 只看单体（仅 MissAV） |
| `--priority` | ❌ | 中文字幕优先 | 筛选优先级（仅 MissAV） |
| `--proxy` | ❌ | `http://127.0.0.1:7890` | 代理 URL（仅 MissAV） |
| `--run-timeout` | ❌ | 无 | 整体超时秒 |

### 二次选择参数

二次选择是爬虫扫描出候选后让用户选择要下载哪些的流程。CLI 提供 3 种选择模式：

#### 模式 A：规则（默认）

```bash
# 全选（默认）
ucrawl search --source bilibili --keyword "测试"

# 只选第一个
ucrawl search --source bilibili --keyword "测试" --first

# 只选最后一个
ucrawl search --source bilibili --keyword "测试" --last

# 指定索引（支持范围）
ucrawl search --source bilibili --keyword "测试" --select "0,2,5"
ucrawl search --source bilibili --keyword "测试" --select "0,2-5"

# 排除索引
ucrawl search --source bilibili --keyword "测试" --all --exclude "1,3"
```

#### 模式 B：TTY 交互

```bash
# 强制 TTY 交互（即使 stdin 是管道也用交互）
ucrawl search --source bilibili --keyword "测试" --interactive
```

运行后显示：
```
============================================================
🔔 二次选择 #1: 5 个候选
📋 共 5 个候选项：
  [0] 视频标题1
  [1] 视频标题2
  [2] 视频标题3
  [3] 视频标题4
  [4] 视频标题5
============================================================
请输入要下载的索引 (逗号分隔, 如 0,2,5) [a=全选/n=不选/q=取消]: 
```

输入 `0,2,5` 回车，下载 0/2/5 号视频。输入 `a` 全选，输入 `n` 不选，输入 `q` 取消。

#### 模式 C：stdin 管道

```bash
# 强制管道（适合脚本控制）
ucrawl search --source bilibili --keyword "测试" --pipe
```

stdin 接受 JSON 格式：

```bash
# 简单格式
echo '[0,2,5]' | ucrawl search --source bilibili --keyword "测试" --pipe

# 详细格式
echo '{"indices": [0,2,5]}' | ucrawl search --source bilibili --keyword "测试" --pipe

# 完整格式
echo '{"items": [{"index": 0, "selected": true}, {"index": 1, "selected": false}]}' | ucrawl search --source bilibili --keyword "测试" --pipe
```

#### 模式 D：预加载（合集场景多次选择）

爬虫可能在一次运行中多次调用 `ask_user_selection`（如 B 站合集展开）。预加载模式一次性指定所有轮次的选择：

```bash
# 第 1 轮选 0，第 2 轮选 1,2，第 3 轮选 3,4
ucrawl search --source bilibili --keyword "BV1xxx合集" --preload-choices "0|1,2|3,4"
```

### 返回结构

CLI 输出 JSON 到 stdout：

```json
{
  "status": "ok",
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
      "meta": {}
    }
  ],
  "logs": ["📡 开始搜索...", "✅ 已加载 10 个项目"],
  "selection_count": 1,
  "elapsed": 12.34,
  "error": null
}
```

退出码：
- `0` 成功
- `1` 错误 / 超时
- `2` 参数错误

## 方式 2：Python SDK

### 安装

无需额外安装，CLI 安装后即可 `import`：

```bash
pip install -e .
```

### 快速开始

```python
from ucrawl import UcrawlSDK, search, list_platforms, scan_directory

# 1. 函数式 API（最简）
result = search("douyin", "测试", max_items=10)
for item in result["items"]:
    print(item["title"])

# 2. SDK 类（推荐，配置复用）
sdk = UcrawlSDK(save_dir="downloads", verbose=True)
result = sdk.search("douyin", "测试", max_items=10)

# 3. 上下文管理器
with UcrawlSDK(save_dir="downloads") as sdk:
    r1 = sdk.search("douyin", "测试1")
    r2 = sdk.search("bilibili", "测试2")
```

### 二次选择

```python
from ucrawl import UcrawlSDK, RuleSelection, PipeSelection, InteractiveSelection, AutoSelection

sdk = UcrawlSDK()

# 规则：指定索引
sel = RuleSelection(select="0,2,5")
result = sdk.search("bilibili", "测试", selection=sel)

# 规则：排除某些
sel = RuleSelection(all_items=True, exclude="1,3")
result = sdk.search("bilibili", "测试", selection=sel)

# 预加载（合集场景）
sel = PipeSelection(preloaded_choices=[[0], [1, 2], [3, 4, 5]])
result = sdk.search("bilibili", "BV1xxx合集", selection=sel)

# 交互
sel = InteractiveSelection()
result = sdk.search("bilibili", "测试", selection=sel)

# 自动（推荐）：有 TTY 用交互，无 TTY 用管道，否则用全选
sel = AutoSelection()
result = sdk.search("bilibili", "测试", selection=sel)
```

简化字符串：

```python
# 字符串简写
result = sdk.search("douyin", "测试", selection="all")     # 全选
result = sdk.search("douyin", "测试", selection="first")   # 只选第一个
result = sdk.search("douyin", "测试", selection="last")    # 只选最后一个
result = sdk.search("douyin", "测试", selection="0,2,5")   # 指定索引
result = sdk.search("douyin", "测试", selection=[0,2,5])   # 列表也行
```

### 平台工具

```python
from ucrawl import UcrawlSDK

sdk = UcrawlSDK()

# 列出所有平台
for p in sdk.list_platforms():
    print(p["id"], p["name"], p["description"])

# 扫描本地目录
result = sdk.scan_directory("D:/downloads", scan_limit=500)
print(f"共 {result['total_count']} 个文件")
```

## 方式 3：REST API + 启动时注入

让 web 服务在启动后自动执行 Python 脚本，调用 SDK 完成自动化任务。

### 启动命令

```bash
python web_main.py \
    --script my_automation.py \
    --script-arg target=douyin \
    --script-arg keyword="测试" \
    --script-arg max=20
```

参数说明：
- `--script`：脚本路径（必填）
- `--script-arg key=value`：传给脚本的参数（可多次）
- `--script-strict`：脚本失败时退出 web 服务
- `--script-delay`：执行前延迟秒数

### 脚本模板

```python
# my_automation.py
def main(controller, **kwargs):
    """web 服务启动后自动调用。

    Args:
        controller: WebController 实例（提供 videos / start_crawl / etc）
        **kwargs: --script-arg 传入的参数

    Returns:
        int: 退出码 (0=成功, 非0=失败)
    """
    from cli import UcrawlSDK

    target = kwargs.get("target", "douyin")
    keyword = kwargs.get("keyword", "")
    max_items = int(kwargs.get("max", 10))

    sdk = UcrawlSDK(save_dir=controller.current_save_dir)
    result = sdk.search(target, keyword, max_items=max_items)

    print(f"✅ 找到 {len(result['items'])} 个项目")
    for item in result["items"]:
        print(f"  - {item['title']}: {item['url']}")

    return 0
```

### 高级用法：直接操作 controller

```python
def main(controller, **kwargs):
    """直接使用 WebController，跳过 SDK 抽象。"""
    # 启动爬虫
    controller.start_crawl(
        source="douyin",
        keyword="测试",
        config={"max_items": 10}
    )

    # 等待完成
    import time
    while controller.current_spider and controller.current_spider.isRunning():
        time.sleep(1)

    # 访问结果
    for vid, video in controller.videos.items():
        print(f"{vid}: {video.title}")

    return 0
```

## 方式 4：AI Skill（LLM 调用）

UCrawl 提供了符合 Claude / LLM skill 规范的封装，让 LLM 可以直接调用爬虫：

- **Skill 位置**：`cli/skill/SKILL.md` 和 `.trae/skills/ucrawl/SKILL.md`
- **Skill 入口**：`cli/skill/ucrawl_skill.py`
- **激活方式**：在 LLM 提示中提到 "ucrawl" 即可激活 skill

LLM 调用示例：

```
User: 帮我搜索抖音上"测试"关键词的 10 个视频
LLM: 激活 ucrawl skill
LLM: 执行 `ucrawl search --source douyin --keyword "测试" --max-items 10`
LLM: 找到以下视频：[返回结果]
```

## 二次选择：合集场景深度解析

### 什么是二次选择

爬虫在搜索过程中，遇到以下情况会进入"二次选择"：

1. **找到多个用户**（抖音 / B站）：爬虫先搜索关键词拿到一批视频，对应多个 UP 主/账号，让用户选择要下载哪个账号的
2. **扫描完成多个结果**（所有平台）：爬虫搜到一批结果后，让用户选择下载哪些
3. **B 站合集展开**：一个合集 BV 号对应多个视频（季/集），让用户选要下哪些
4. **MissAV 多作品页面**：一个搜索结果页有多个作品，让用户选要下哪些

### 为什么这是挑战

爬虫在 `run()` 方法中会**多次**调用 `ask_user_selection(items)`。GUI 端通过 Qt 信号弹窗阻塞等用户选；CLI/SDK 必须**按调用顺序**同步给出答案。

### UCrawl 的解决方案

UCrawl 把二次选择抽象为 `SelectionStrategy` 接口，提供 4 种实现：

| 策略 | 用途 | 典型场景 |
|---|---|---|
| `RuleSelection` | 按规则（select/exclude/first/last） | 自动化脚本 |
| `InteractiveSelection` | TTY 终端交互 | 人工调试 |
| `PipeSelection` | stdin 管道读 JSON | 其他程序控制 |
| `AutoSelection` | 自动选择（有 TTY→交互，无 TTY→管道） | 默认 |

**合集场景的预加载模式**特别关键：

```python
# B 站合集 BV1xxx 含 3 个分季
sel = PipeSelection(preloaded_choices=[
    [0, 1, 2],  # 第 1 季：全选
    [],         # 第 2 季：跳过
    [5],        # 第 3 季：只下第 6 个
])
result = sdk.search("bilibili", "BV1xxx合集", selection=sel)
```

CLI 版本：

```bash
ucrawl search --source bilibili --keyword "BV1xxx合集" --preload-choices "0,1,2||5"
```

## 性能与限制

- **CLI 启动开销**：约 1-2 秒（Qt 初始化 + 模块加载）
- **爬虫本身速度**：取决于目标平台，单次搜索 5-60 秒
- **内存占用**：约 100-300 MB（含 Qt + Playwright）
- **并发**：单实例运行，不支持并发搜索

## 故障排查

| 错误 | 原因 | 解决 |
|---|---|---|
| `PyQt6 未安装` | 缺少依赖 | `pip install PyQt6` |
| `No QApplication` | 未初始化 Qt | SDK 会自动处理 |
| `proxy error` | 代理不可用 | 改用 `--proxy` 或关闭代理 |
| `timeout` | 网络慢或平台限流 | 重试或加大 `--run-timeout` |
| `二次选择策略异常` | 选择器逻辑错误 | 用 `--all` 兜底 |

## 与 GUI / Web UI 的关系

UCrawl CLI **不**会启动 GUI 或 Web 服务。它是**完全独立的执行路径**：

- **GUI**：PyQt6 主窗口 + Qt 信号槽
- **Web UI**：FastAPI + WebSocket（基于 QApplication + WebController）
- **CLI/SDK**：独立 QApplication + CLIRunner（不依赖 GUI/Web）

三者**共享**：
- 爬虫代码（`app/spiders/`）
- 平台插件（`app/core/plugins/`）
- 配置文件（`~/.ucrawl/config.ini`）

三者**独立**：
- 启动方式
- 资源占用
- 进程隔离

## 完整示例

### 示例 1：批量下载某用户全部视频

```python
from ucrawl import UcrawlSDK, PipeSelection

sdk = UcrawlSDK(save_dir="downloads")

# 预加载：第 1 轮选用户 0，第 2 轮（搜索结果）全选
sel = PipeSelection(preloaded_choices=[
    [0],  # 选第一个用户
    list(range(100)),  # 选全部结果
])

result = sdk.search("douyin", "抖音号 ID", selection=sel)
print(f"下载 {len(result['items'])} 个视频")
```

### 示例 2：B 站合集自动下载

```bash
ucrawl search \
    --source bilibili \
    --keyword "BV1xxx合集标题" \
    --max-pages 1 \
    --preload-choices "0,1,2,3|0,1" \
    --save-dir "downloads/合集"
```

### 示例 3：MissAV 单体批量

```bash
ucrawl search \
    --source missav \
    --keyword "ABC" \
    --individual-only \
    --priority "中文字幕优先" \
    --proxy http://127.0.0.1:7890 \
    --all
```

### 示例 4：定时任务（cron）

```bash
# crontab -e
0 2 * * * cd /path/to/ucrawl && ucrawl search --source douyin --keyword "每日更新" --max-items 50 --save-dir "/data/crawl/$(date +\%Y\%m\%d)" >> /var/log/ucrawl.log 2>&1
```

## 进阶：自定义 Selection 策略

```python
from ucrawl import UcrawlSDK, SelectionStrategy

class MyCustomSelection:
    """自定义策略：只选标题包含特定关键词的。"""

    def __init__(self, must_contain: str):
        self.must_contain = must_contain

    def select(self, items, prompt=""):
        indices = []
        for i, item in enumerate(items):
            if isinstance(item, dict):
                title = item.get("title", "")
            else:
                title = str(item)
            if self.must_contain in title:
                indices.append(i)
        return indices

sel = MyCustomSelection(must_contain="测试")
sdk = UcrawlSDK()
result = sdk.search("douyin", "测试", selection=sel)
```
