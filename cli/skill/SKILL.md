---
name: "ucrawl"
description: "通用视频爬虫工具 (CLI / SDK / REST API / AI Skill)。支持抖音/B站/快手/MissAV 四平台，可通过 CLI 命令、Python SDK、REST API 三种方式调用，并能处理合集/多用户的二次选择场景。Invoke when user wants to search/download videos from these platforms, batch crawl, integrate crawler into existing service, or call crawler from LLM/script."
version: 2.0.0
author: UCrawl Team
---

# UCrawl - 通用视频爬虫

从多个视频平台（抖音、B站、快手、MissAV）搜索、获取元数据、下载视频。支持**合集展开**和**二次选择**的复杂交互场景。

**CLI / SDK / REST API / 桌面 GUI 四层输入输出完全一致。**

## 何时使用

- 用户要批量搜索某个关键词在多个平台上的视频
- 用户要从某个 UP 主 / 用户主页批量获取视频
- 用户要下载某合集（如 B 站合集、抖音合集）并选择要下载的集数
- 用户要用脚本/程序批量调用爬虫功能
- 用户要把爬虫嵌入到现有 web 服务中
- LLM 需要在对话中调用爬虫获取资源

## 关键能力

1. **4 个平台统一接口**：抖音（douyin）、B站（bilibili）、快手（kuaishou）、MissAV（missav）
2. **4 种调用方式**：
   - CLI：`ucrawl search --source douyin --keyword "测试"`
   - Python SDK：`from ucrawl import UcrawlSDK; sdk.search(...)`
   - REST API 同步搜索：`POST /api/search`
   - REST API 异步爬取：`POST /api/crawl/start` + WebSocket 交互
3. **4 种二次选择策略**：
   - 规则（--select / --exclude / --all / --first / --last）
   - TTY 交互（在终端输入索引）
   - stdin 管道（接收 JSON 列表）
   - 预加载（`preload` 模式，按轮次提供选择，适合合集/多用户场景）
4. **合集/多用户自动展开**：爬虫自动识别合集/多用户，进入二次选择流程

## 调用方式

### 方式 1：CLI（最快）

```bash
# 通用命令
ucrawl search --source douyin --keyword "测试" --max-items 10

# 平台别名
ucrawl douyin search "测试" --max-items 10

# 二次选择：指定索引
ucrawl search --source bilibili --keyword "BV1xxx" --select "0,2,5"

# 二次选择：预加载（合集场景多次选择）
ucrawl search --source bilibili --keyword "BV1xxx" --preload-choices "0|1,2|3"

# 强制 stdin 管道（适合被其他脚本调用）
echo '[0,2,5]' | ucrawl search --source douyin --keyword "测试" --pipe

# 输出 JSON 给 jq 处理
ucrawl search --source missav --keyword "ABC-123" --json | jq '.items[].url'
```

### 方式 2：Python SDK（最灵活）

```python
from ucrawl import UcrawlSDK, RuleSelection, PipeSelection

# 简单搜索
sdk = UcrawlSDK(save_dir="downloads")
result = sdk.search("douyin", "测试", max_items=10)
for item in result["items"]:
    print(item["title"], item["url"])

# 规则选择
sel = RuleSelection(select="0,2,5")
result = sdk.search("missav", "ABC-123", selection=sel)

# 合集场景：预加载多次选择
sel = PipeSelection(preloaded_choices=[[0], [1, 2]])
result = sdk.search("bilibili", "BV1xxx合集", selection=sel)

# 列出所有平台
for p in sdk.list_platforms():
    print(p["id"], p["name"])

# 扫描本地目录
result = sdk.scan_directory("D:/downloads", scan_limit=500)
```

### 方式 3：REST API 同步搜索（最通用）

**与 CLI/SDK 输入输出完全一致，适合被任何 HTTP 客户端调用。**

```bash
# 基本搜索（全选）
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"source": "douyin", "keyword": "测试", "config": {"max_items": 10}}'

# 规则选择
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "source": "bilibili",
    "keyword": "BV1xxx",
    "selection": {"strategy": "rule", "select": "0,2,5"}
  }'

# 合集场景：预加载多轮选择
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "source": "bilibili",
    "keyword": "BV1xxx合集",
    "selection": {"strategy": "preload", "choices": [[0], [1,2]]}
  }'

# MissAV 搜索（带代理）
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "source": "missav",
    "keyword": "ABC-123",
    "config": {"proxy": "http://127.0.0.1:7890"},
    "selection": {"strategy": "all"}
  }'
```

#### `/api/search` 请求参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source` | string | 是 | 平台：`douyin` / `bilibili` / `kuaishou` / `missav` |
| `keyword` | string | 是 | 搜索关键词 / 视频链接 / 用户 ID |
| `save_dir` | string | 否 | 保存目录（默认使用服务端配置） |
| `config` | object | 否 | 平台特定参数（见下方） |
| `selection` | object | 否 | 二次选择策略（见下方） |
| `timeout` | float | 否 | 整体超时秒数（默认无限） |
| `download` | bool | 否 | 是否下载（默认 true，与 GUI 一致） |

#### `/api/search` selection 参数格式

| strategy | 格式 | 说明 |
|---|---|---|
| `all` | `{"strategy": "all"}` | 全选（默认） |
| `first` | `{"strategy": "first"}` | 只选第一个 |
| `last` | `{"strategy": "last"}` | 只选最后一个 |
| `rule` | `{"strategy": "rule", "select": "0,2,5", "exclude": "1,3"}` | 规则选择 |
| `preload` | `{"strategy": "preload", "choices": [[0], [1,2]]}` | 预加载多轮选择 |

**preload 的 choices 是二维数组**：每个内层数组对应一次 `ask_user_selection` 调用。
- B站合集：第1轮选合集，第2轮选集数 → `[[0], [0,1,2]]`
- 抖音多用户：第1轮选用户，第2轮选作品 → `[[0,1], [2,3,5]]`
- 如果预加载数量不够，超出部分默认全选

### 方式 4：REST API 异步爬取（WebSocket 交互）

适合需要实时进度更新的 Web 前端场景。

```bash
# 启动爬虫（不带 selection → 走 WebSocket 交互流程）
curl -X POST http://localhost:8000/api/crawl/start \
  -H "Content-Type: application/json" \
  -d '{"source": "douyin", "keyword": "测试", "config": {"max_items": 10}}'

# 启动爬虫（带 selection → 自动选择，不需要 WebSocket 交互）
curl -X POST http://localhost:8000/api/crawl/start \
  -H "Content-Type: application/json" \
  -d '{
    "source": "douyin",
    "keyword": "测试",
    "config": {"max_items": 10},
    "selection": {"strategy": "all"}
  }'
```

WebSocket 交互流程（不带 selection 时）：
1. 服务端推送 `select_tasks` 事件，包含候选项列表
2. 前端展示选择界面，用户勾选
3. 前端发送 `select_tasks` 消息，包含 `indices` 数组
4. 重复直到爬虫完成

## 参数参考

### 通用参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `source` / `-s` | 是 | 平台：`douyin` / `bilibili` / `kuaishou` / `missav` |
| `keyword` | 是 | 搜索关键词 / 视频链接 / 用户 ID |
| `save-dir` / `-d` | 否 | 保存目录（默认：`downloads`） |
| `timeout` | 否 | HTTP 超时秒（默认 10） |

### 平台特定参数

#### 抖音 (douyin)
- `max_items` (int): 最大视频数（默认 20）

#### B站 (bilibili)
- `max_pages` (int): 翻页数（默认 1）
- `max_items` (int): 最大视频数（默认 30）

#### 快手 (kuaishou)
- `max_items` (int): 最大视频数（默认 20）

#### MissAV (missav)
- `individual_only` (bool): 只看单体作品（False=默认）
- `priority` (str): "中文字幕优先"（默认） / "无码流出优先"
- `proxy` (str): 代理 URL（默认 `http://127.0.0.1:7890`）

### 二次选择参数

#### CLI 参数

| 参数 | 说明 |
|---|---|
| `--all` | 全选（默认） |
| `--first` | 只选第一个 |
| `--last` | 只选最后一个 |
| `--select "0,2,5"` | 指定索引（支持范围如 `0,2-5`） |
| `--exclude "1,3"` | 排除索引 |
| `--interactive` | 强制 TTY 交互 |
| `--pipe` | 强制 stdin 管道 |
| `--preload-choices "0\|1,2\|3,4"` | 预加载多次选择（`\|` 分轮，`逗号` 分索引） |

#### SDK 参数

```python
# 规则选择
RuleSelection(select="0,2,5", exclude="1,3", all_items=True, first=False, last=False)

# 预加载多轮选择
PipeSelection(preloaded_choices=[[0], [1,2], [3,4,5]])
# 每个内层列表对应一次 ask_user_selection 调用

# 交互选择
InteractiveTTYSelection()

# 自动选择（有TTY→交互，无TTY→管道，否则→全选）
AutoSelection()
```

#### REST API 参数

```json
{"strategy": "all"}
{"strategy": "first"}
{"strategy": "last"}
{"strategy": "rule", "select": "0,2,5", "exclude": "1,3"}
{"strategy": "preload", "choices": [[0], [1,2], [3,4,5]]}
```

## 返回结构

**CLI / SDK / REST API `/api/search` 返回结构完全一致：**

```json
{
  "status": "ok",
  "source": "douyin",
  "keyword": "测试",
  "save_dir": "downloads",
  "items": [
    {
      "id": "...",
      "url": "https://...",
      "title": "视频标题",
      "source": "douyin",
      "status": "✅ 完成",
      "progress": 100,
      "local_path": "/path/to/file.mp4",
      "content_type": "video",
      "meta": {...}
    }
  ],
  "logs": ["📡 开始搜索...", "✅ 已加载 10 个项目"],
  "selection_count": 2,
  "elapsed": 12.34,
  "error": null
}
```

### items 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一标识（UUID） |
| `url` | string | 资源 URL |
| `title` | string | 标题 |
| `source` | string | 平台 ID |
| `status` | string | 状态：`⏳ 等待中` / `⏳ 下载中...` / `✅ 完成` / `❌ 失败` |
| `progress` | int | 进度 0-100 |
| `local_path` | string | 本地文件路径 |
| `content_type` | string | 内容类型（video/image） |
| `meta` | object | 平台特定元数据 |

## 二次选择的关键场景

爬虫在以下场景会**自动**进入二次选择：

1. **找到多个用户时**（抖音 / B站）→ 第1轮选用户，第2轮选作品
2. **扫描完成有多个结果时**（快手 / MissAV）→ 1轮选择
3. **B 站合集展开**→ 第1轮选合集/视频，第2轮选集数（每个合集独立一轮）
4. **抖音合集**→ 1轮选择合集内容

**多轮选择的关键**：spider 可能多次调用 `ask_user_selection`，每次调用都需要一组选择结果。

| 平台 | 典型场景 | 选择轮数 | preload 示例 |
|---|---|---|---|
| douyin | 用户主页 | 1 | `[[0,1,2]]` |
| douyin | 多用户搜索 | 2+ | `[[0], [1,2], [0,1]]` |
| douyin | 合集 | 1 | `[[0,1,2]]` |
| bilibili | 单视频 | 0 | 不需要 |
| bilibili | 合集 | 2 | `[[0], [0,1,2]]` |
| bilibili | 搜索结果 | 1 | `[[0,2,5]]` |
| kuaishou | 用户主页 | 1 | `[[0,1,2]]` |
| missav | 搜索/演员 | 1 | `[[0,1,2]]` |

## 四层对齐关系

| 层 | 入口 | 选择方式 | 返回格式 |
|---|---|---|---|
| 桌面 GUI | `ApplicationController.on_start_crawl()` | SelectionDialog 弹窗 | VideoItem 对象 |
| CLI | `ucrawl search` | `--select`/`--preload-choices`/交互 | JSON dict（同下） |
| SDK | `UcrawlSDK.search()` | `selection` 参数 | dict（同下） |
| REST API | `POST /api/search` | `selection` JSON | dict（同下） |

**所有非 GUI 层的返回结构完全一致**，均为 `VideoItem.to_dict()` 序列化后的 dict。

## 安装

```bash
# 开发模式
pip install -e .

# 全局安装
pip install .
```

安装后 `ucrawl` 命令全局可用。

## 注意事项

- **必须安装 PyQt6**：爬虫基于 Qt 的 QThread 机制，需要 QApplication 实例
- **首次使用需要配置代理**：MissAV 等需要翻墙的平台，请设置 `--proxy` 参数
- **保存目录**：默认 `downloads/`，可在 `~/.ucrawl/config.ini` 中修改
- **REST API 同步搜索**：`POST /api/search` 在线程池中执行，不阻塞 Web 事件循环
- **REST API 异步爬取**：`POST /api/crawl/start` + WebSocket 交互，适合前端实时更新
- **启动时注入脚本**：用 `python web_main.py --script xxx.py`，脚本在子线程中运行，不阻塞 web 服务
