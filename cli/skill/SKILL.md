---
name: "ucrawl"
description: "通用视频爬虫工具 (CLI / SDK / REST API / AI Skill)。支持抖音/B站/快手/MissAV 四平台，可通过 CLI 命令、Python SDK、REST API 三种方式调用，并能处理合集/多用户的二次选择场景。Invoke when user wants to search/download videos from these platforms, batch crawl, integrate crawler into existing service, or call crawler from LLM/script."
version: 3.6.14
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

# 平台别名（支持短别名：dy/bili/bl/ks/miss）
ucrawl douyin search "测试" --max-items 10
ucrawl dy search "测试" --max-items 10          # dy = douyin
ucrawl bilibili search "BV1xxx" --select "0,2,5"
ucrawl bili search "BV1xxx" --select "0,2,5"    # bili/bl = bilibili
ucrawl kuaishou search "测试"
ucrawl ks search "测试"                          # ks = kuaishou
ucrawl missav search "ABC-123" --individual-only
ucrawl miss search "ABC-123" --individual-only   # miss = missav

# 平台别名也支持 --config（与通用 search --config 对齐）
ucrawl douyin search "测试" --config '{"max_items":50}'
ucrawl missav search "ABC-123" --config '{"proxy":"http://127.0.0.1:7890"}'

# 二次选择：指定索引
ucrawl search --source bilibili --keyword "BV1xxx" --select "0,2,5"

# 二次选择：预加载（合集场景多次选择）
ucrawl search --source bilibili --keyword "BV1xxx" --preload-choices "0|1,2|3"

# 强制 stdin 管道（适合被其他脚本调用）
echo '[0,2,5]' | ucrawl search --source douyin --keyword "测试" --pipe

# 输出 JSON 给 jq 处理
ucrawl search --source missav --keyword "ABC-123" | jq '.items[].url'

# 扫描本地目录
ucrawl scan "./downloads" --limit 500

# 静默扫描（不输出 SDK 内部日志，与 search --quiet 对齐）
ucrawl scan "./downloads" --quiet

# 只搜索不下载（获取元数据，不触发下载）
ucrawl search --source douyin --keyword "测试" --no-download

# 搜索时传入平台特定配置（与 CLI download --config 和 SDK config 对齐）
ucrawl search --source douyin --keyword "测试" --config '{"max_items":50}'
ucrawl search --source missav --keyword "ABC-123" --config '{"proxy":"http://127.0.0.1:7890"}'

# 搜索时使用便捷参数（与 GUI spider build_download_meta 对齐，避免手写 JSON）
ucrawl search --source douyin --keyword "测试" --cookie "sessionid=xxx"
ucrawl search --source bilibili --keyword "BV1xxx" --referer "https://www.bilibili.com"
ucrawl search --source kuaishou --keyword "测试" --download-strategy m3u8
ucrawl search --source douyin --keyword "测试" --ua "Mozilla/5.0 ..."

# 下载指定视频（需先搜索获取 URL）
ucrawl download "视频标题" --url "https://..." --source douyin

# 下载指定视频并设置超时（与 SDK timeout 和 REST API timeout 对齐）
ucrawl download "视频标题" --url "https://..." --source douyin --timeout 600

# 下载 MissAV 视频并设置代理（与 SDK config 和 REST API config 对齐）
ucrawl download "ABC-123" --url "https://missav.ws/..." --source missav --config '{"proxy":"http://127.0.0.1:7890"}'

# 下载时使用便捷参数（与 GUI spider build_download_meta 对齐，避免手写 JSON）
ucrawl download "视频标题" --url "https://..." --source douyin --cookie "sessionid=xxx"
ucrawl download "视频标题" --url "https://..." --source bilibili --referer "https://www.bilibili.com"
ucrawl download "视频标题" --url "https://..." --source kuaishou --download-strategy m3u8
ucrawl download "视频标题" --url "https://..." --source douyin --ua "Mozilla/5.0 ..."
ucrawl download "合集视频" --url "https://..." --source bilibili --folder-name "合集名" --use-subdir
ucrawl download "图集视频" --url "https://..." --source douyin --content-type gallery
ucrawl download "ABC-123" --url "https://missav.ws/..." --source missav --proxy "http://127.0.0.1:7890" --individual-only --priority "中文字幕优先"

# 静默下载（不输出进度，适合脚本调用，与 search --quiet 对齐）
ucrawl download "视频标题" --url "https://..." --source douyin --quiet

# 人类可读格式输出（与 search --pretty 对齐）
ucrawl download "视频标题" --url "https://..." --source douyin --pretty

# 列出所有平台（--pretty 显示搜索提示和描述，与 SDK list_platforms() 对齐）
ucrawl platforms --pretty

# 查看指定平台详细参数
ucrawl platforms --describe douyin

# 交互式引导模式（逐步选择平台和参数，适合不熟悉命令行的用户）
ucrawl interactive
ucrawl i --run-timeout 60

# 交互式模式 + 额外配置（交互式输入的参数优先级高于 --config）
ucrawl interactive --config '{"max_items":50}'
ucrawl i --config '{"proxy":"http://127.0.0.1:7890"}'

# 交互式 MissAV 模式 + 便捷参数（与 CLI search/download --individual-only/--priority 对齐）
ucrawl interactive --individual-only --priority "中文字幕优先"

# 交互式静默模式（不输出 spider 日志，与 search --quiet 对齐）
ucrawl interactive --quiet

# 交互式模式 + 二次选择策略（与 search 命令对齐：默认 AutoSelection，可覆盖）
ucrawl interactive --all
ucrawl interactive --first
ucrawl interactive --select "0,2,5"
ucrawl i --pipe
ucrawl i --preload-choices "0|1,2|3"
```

### 方式 2：Python SDK（最灵活）

```python
from ucrawl import UcrawlSDK, RuleSelection, PipeSelection

# 简单搜索
sdk = UcrawlSDK(save_dir="downloads")
result = sdk.search("douyin", "测试", max_items=10)
for item in result["items"]:
    print(item["title"], item["url"])

# 设置整体超时（与 CLI --run-timeout 对齐）
result = sdk.search("douyin", "测试", run_timeout=60)

# 同时设置整体超时和 spider HTTP 超时
result = sdk.search("douyin", "测试", run_timeout=60, **{"timeout": 15})

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
result = sdk.scan_directory("./downloads", scan_limit=500)

# 直接下载指定 URL 的视频（与 CLI download 命令对齐）
result = sdk.download_video("https://...", "douyin", title="测试视频")
if result["status"] == "ok":
    print(f"下载完成: {result['local_path']}")

# 静默下载（不输出进度到 stderr，与 CLI download --quiet 对齐）
result = sdk.download_video("https://...", "douyin", title="测试视频", verbose=False)

# 带进度回调（与 GUI DownloadManager task_progress 信号对齐，适合 WebUI/REST API 实时进度广播）
def on_progress(pct):
    print(f"进度: {pct}%")
result = sdk.download_video("https://...", "douyin", title="测试视频", progress_callback=on_progress)

# 下载 MissAV 视频并设置代理（与 CLI --config 和 REST API config 对齐）
result = sdk.download_video("https://missav.ws/...", "missav", title="ABC-123", config={"proxy": "http://127.0.0.1:7890"})

# 也可以使用函数式 API（无需手动管理 SDK 实例）
from ucrawl import search, download_video
result = search("douyin", "测试", max_items=10)
result = search("douyin", "测试", run_timeout=60)  # 与 CLI --run-timeout 对齐
result = download_video("https://...", "douyin", title="测试视频")
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
| `source` | string | 是 | 平台：`douyin` / `bilibili` / `kuaishou` / `missav`（**必须是字符串，无效平台会返回错误**，与 GUI 下拉框对齐） |
| `keyword` | string | 是 | 搜索关键词 / 视频链接 / 用户 ID（**必须是字符串，自动去除前后空白**，与 GUI QLineEdit `.strip()` 对齐） |
| `save_dir` | string | 否 | 保存目录（默认使用服务端配置，**必须是字符串或 null**，与 GUI QFileDialog 对齐） |
| `config` | object | 否 | 平台特定参数（**必须是 JSON 对象**，与 GUI Qt 控件类型安全对齐） |
| `selection` | object \| null | 否 | 二次选择策略（**必须是 JSON 对象或 null**，无效策略会返回错误，见下方） |
| `timeout` | float | 否 | 整体超时秒数（默认无限，**必须是数字**，与 GUI/WebUI 的选项化设置契约对齐。也可使用 `run_timeout` 参数，与 SDK `run_timeout` 对齐，优先级高于 `timeout`） |
| `download` | bool \| null | 否 | 是否下载（默认 true，与 GUI 一致。**注意**：传字符串 `"false"` 会被自动转为 `false`；传 `null` 视为未提供，使用默认值 true） |
| `max_items` | int | 否 | 便捷参数：最大视频数（与 CLI `--max-items` 对齐，优先级高于 `config.max_items`） |
| `max_pages` | int | 否 | 便捷参数：翻页数（与 CLI `--max-pages` 对齐，优先级高于 `config.max_pages`） |
| `cookie` | string | 否 | 便捷参数：Cookie 字符串（与 CLI `--cookie` 对齐，优先级高于 `config.cookie`） |
| `download_strategy` | string | 否 | 便捷参数：下载策略 m3u8/http（与 CLI `--download-strategy` 对齐，优先级高于 `config.download_strategy`） |
| `referer` | string | 否 | 便捷参数：Referer 请求头（与 CLI `--referer` 对齐，优先级高于 `config.referer`） |
| `ua` | string | 否 | 便捷参数：User-Agent 请求头（与 CLI `--ua` 对齐，优先级高于 `config.ua`） |
| `folder_name` | string | 否 | 便捷参数：子目录名（与 CLI `--folder-name` 对齐，优先级高于 `config.folder_name`） |
| `use_subdir` | bool | 否 | 便捷参数：使用子目录保存（与 CLI `--use-subdir` 对齐，优先级高于 `config.use_subdir`） |
| `file_name` | string | 否 | 便捷参数：输出文件名（与 CLI `--file-name` 对齐，优先级高于 `config.file_name`） |
| `content_type` | string | 否 | 便捷参数：内容类型 video/image/gallery（与 CLI `--content-type` 对齐，优先级高于 `config.content_type`） |
| `proxy` | string | 否 | 便捷参数：代理 URL（与 CLI `--proxy` 对齐，优先级高于 `config.proxy`。MissAV 平台会自动调用 `build_missav_proxy_url` 转换） |
| `individual_only` | bool | 否 | 便捷参数：只看单体作品（MissAV 专属，与 CLI `--individual-only` 对齐，优先级高于 `config.individual_only`） |
| `priority` | string | 否 | 便捷参数：优先级（MissAV 专属，与 CLI `--priority` 对齐，优先级高于 `config.priority`） |

#### `/api/search` selection 参数格式

| strategy | 格式 | 说明 |
|---|---|---|
| `all` | `{"strategy": "all"}` | 全选（默认） |
| `first` | `{"strategy": "first"}` | 只选第一个 |
| `last` | `{"strategy": "last"}` | 只选最后一个 |
| `rule` | `{"strategy": "rule", "select": "0,2,5", "exclude": "1,3"}` | 规则选择 |
| `preload` | `{"strategy": "preload", "choices": [[0], [1,2]]}` | 预加载多轮选择 |
| `interactive` | `{"strategy": "interactive"}` | TTY 交互式选择（与 CLI `--interactive` 对齐） |
| `pipe` | `{"strategy": "pipe"}` | stdin 管道选择（与 CLI `--pipe` 对齐） |

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

# 启动爬虫（指定保存目录，与 /api/search 的 save_dir 对齐）
curl -X POST http://localhost:8000/api/crawl/start \
  -H "Content-Type: application/json" \
  -d '{"source": "douyin", "keyword": "测试", "save_dir": "/path/to/downloads"}'
```

#### `/api/crawl/start` 请求参数

**注意：** 此端点始终触发下载（与 GUI 行为一致），不支持 `download` 参数。如需只搜索不下载，请使用 `/api/search` 并传 `download: false`。**如果请求体中包含 `download` 参数，将返回错误**，避免用户误以为 `download: false` 可以跳过下载。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source` | string | 是 | 平台：`douyin` / `bilibili` / `kuaishou` / `missav`（**必须是字符串，无效平台会返回错误**，与 GUI 下拉框对齐） |
| `keyword` | string | 是 | 搜索关键词 / 视频链接 / 用户 ID（**必须是字符串，自动去除前后空白**，同 `/api/search` 的 keyword） |
| `config` | object | 否 | 平台特定参数（**必须是 JSON 对象**，同 `/api/search` 的 config） |
| `selection` | object \| null | 否 | 二次选择策略（**必须是 JSON 对象或 null**，无效策略会返回错误，同 `/api/search` 的 selection） |
| `save_dir` | string | 否 | 保存目录（默认使用服务端配置，**必须是字符串或 null**，与 GUI QFileDialog 对齐） |
| `max_items` | int | 否 | 便捷参数：最大视频数（与 CLI `--max-items` 对齐，优先级高于 `config.max_items`） |
| `max_pages` | int | 否 | 便捷参数：翻页数（与 CLI `--max-pages` 对齐，优先级高于 `config.max_pages`） |
| `cookie` | string | 否 | 便捷参数：Cookie 字符串（与 CLI `--cookie` 对齐，优先级高于 `config.cookie`） |
| `download_strategy` | string | 否 | 便捷参数：下载策略 m3u8/http（与 CLI `--download-strategy` 对齐，优先级高于 `config.download_strategy`） |
| `referer` | string | 否 | 便捷参数：Referer 请求头（与 CLI `--referer` 对齐，优先级高于 `config.referer`） |
| `ua` | string | 否 | 便捷参数：User-Agent 请求头（与 CLI `--ua` 对齐，优先级高于 `config.ua`） |
| `folder_name` | string | 否 | 便捷参数：子目录名（与 CLI `--folder-name` 对齐，优先级高于 `config.folder_name`） |
| `use_subdir` | bool | 否 | 便捷参数：使用子目录保存（与 CLI `--use-subdir` 对齐，优先级高于 `config.use_subdir`） |
| `file_name` | string | 否 | 便捷参数：输出文件名（与 CLI `--file-name` 对齐，优先级高于 `config.file_name`） |
| `content_type` | string | 否 | 便捷参数：内容类型 video/image/gallery（与 CLI `--content-type` 对齐，优先级高于 `config.content_type`） |
| `proxy` | string | 否 | 便捷参数：代理 URL（与 CLI `--proxy` 对齐，优先级高于 `config.proxy`。MissAV 平台会自动调用 `build_missav_proxy_url` 转换） |
| `individual_only` | bool | 否 | 便捷参数：只看单体作品（MissAV 专属，与 CLI `--individual-only` 对齐，优先级高于 `config.individual_only`） |
| `priority` | string | 否 | 便捷参数：优先级（MissAV 专属，与 CLI `--priority` 对齐，优先级高于 `config.priority`） |

WebSocket 交互流程（不带 selection 时）：
1. 服务端推送 `select_tasks` 事件，包含候选项列表
2. 前端展示选择界面，用户勾选
3. 前端发送 `select_tasks` 消息，包含 `indices` 数组
4. 重复直到爬虫完成

WebSocket `start_crawl` 消息也支持 `selection`、`config`、`save_dir` 参数（与 REST API `/api/crawl/start` 对齐），以及便捷参数（与 CLI search 命令对齐，优先级高于 `config` 字典。REST API `/api/crawl/start` 同样支持这些便捷参数）：
```json
{"type": "start_crawl", "data": {"source": "douyin", "keyword": "测试", "selection": {"strategy": "all"}, "config": {"max_items": 10}, "save_dir": "/path/to/downloads", "cookie": "sessionid=xxx", "download_strategy": "m3u8", "referer": "https://www.douyin.com/", "ua": "Mozilla/5.0 ...", "folder_name": "合集名", "use_subdir": true, "content_type": "video", "proxy": "http://127.0.0.1:7890", "max_items": 10, "individual_only": false, "priority": "中文字幕优先"}}
```

#### WebSocket 其他消息参数

| 消息类型 | 参数 | 说明 |
|---|---|---|
| `stop_crawl` | 无 | 停止正在运行的爬虫（与 REST API `POST /api/crawl/stop` 对齐，与 GUI 停止按钮对齐） |
| `scan_dir` | `directory` (string, 可选) | 要扫描的目录（默认使用服务端配置） |
| `scan_dir` | `scan_limit` (int, 可选) | 最多扫描文件数（默认从配置读取） |
| `delete_video` | `video_id` (string) | 要删除的视频 ID（**必须是字符串**） |
| `rename_video` | `video_id` (string), `new_title` (string) | 重命名参数（**都必须是字符串**） |
| `select_tasks` | `indices` (int[]) | 选中的索引数组（**必须是整数数组**，**当前必须有正在运行的爬虫**，否则返回错误日志） |
| `change_dir` | `directory` (string) | 新的保存目录（**必须是字符串，不能为空**） |
| `download` | `url` (string), `source` (string), `title` (string, 可选), `save_dir` (string, 可选), `timeout` (float, 可选, 默认 300), `config` (object, 可选, 平台特定配置如 missav proxy), `cookie` (string, 可选), `download_strategy` (string, 可选), `referer` (string, 可选), `ua` (string, 可选), `folder_name` (string, 可选), `use_subdir` (bool, 可选), `file_name` (string, 可选), `content_type` (string, 可选), `proxy` (string, 可选), `individual_only` (bool, 可选), `priority` (string, 可选) | 直接下载指定 URL 的视频（与 REST API `/api/download` 对齐，**url 和 source 必填**。便捷参数与 CLI 对齐，优先级高于 `config` 字典） |
| `change_theme` | `dark_theme` (bool, 可选, 默认 true) | 切换主题（**dark_theme 必须是布尔值**，与 GUI 主题切换对齐） |
| `change_source` | `source` (string) | 切换当前平台（**必须是字符串，必须是有效平台 ID**，与 GUI QComboBox 对齐） |
| `save_config` | `section` (string), `key` (string), `value` (any) | 保存单个配置项（**section 和 key 必须是字符串**，与 GUI 设置对话框对齐） |

#### WebSocket 事件类型

**连接初始化事件**（客户端连接后服务端自动推送）：

| 事件类型 | 数据字段 | 说明 |
|---|---|---|
| `init_state` | `current_save_dir`, `is_crawling`, `video_count` | 当前状态快照（与 `GET /api/state` 一致） |
| `platforms` | 平台列表 | 可用平台列表（与 `GET /api/platforms` 一致） |
| `config` | 配置字典 | 当前配置（与 `GET /api/config` 一致） |

**运行时事件**（爬虫/下载过程中推送）：

| 事件类型 | 数据字段 | 说明 |
|---|---|---|
| `item_found` | VideoItem dict | 发现新视频 |
| `scan_result` | `total_count`, `video_count`, `image_count`, `truncated`, `original_count` | 扫描结果汇总 |
| `select_tasks` | `items` (VideoItem[]) | 需要用户选择的候选项 |
| `task_started` | `video_id`, `local_path`, `title`, `content_type` | 下载开始（title 和 content_type 让客户端在下载开始时即可显示完整信息，与 task_finished 对齐。REST API/WebSocket download 的 content_type 从 URL 预推断，与 GUI spider 在 emit_video 时设置 content_type 对齐） |
| `task_progress` | `video_id`, `progress` | 下载进度（REST API/WebSocket download 通过 SDK progress_callback 实时广播，与 GUI DownloadManager 信号对齐） |
| `task_finished` | `video_id`, `local_path`, `content_type`, `title` | 下载完成（content_type 和 title 让客户端无需额外请求即可获取完整下载结果） |
| `task_error` | `video_id`, `error`, `local_path`, `content_type`, `title` | 下载失败（local_path/content_type/title 与 task_finished 对齐，让客户端无需额外请求即可获取完整错误信息） |
| `crawl_state` | `is_running`, `source` | 爬虫状态变化 |
| `log` | `message` | 日志消息 |
| `video_removed` | `video_id` | 视频已删除（与 REST API DELETE /api/video/{id} 对齐） |
| `video_renamed` | `video_id`, `new_title`, `new_path` | 视频已重命名（与 REST API POST /api/video/rename 对齐） |
| `clear_videos` | `directory` | 清空视频列表（扫描前触发） |
| `video_state_changed` | `video_id`, `status`, `progress`, `local_path`*, `content_type`* | 视频状态变化（下载开始/进度/完成/失败时触发。*完成/失败状态时额外包含 local_path 和 content_type，与 REST API/WebSocket download 对齐） |

### 方式 5：REST API 目录扫描

```bash
# 扫描本地目录（返回已有媒体文件列表）
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"directory": "./downloads"}'

# 指定 scan_limit（与 CLI --limit 和 SDK scan_limit 对齐）
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"directory": "./downloads", "scan_limit": 500}'
```

#### `/api/scan` 请求参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `directory` | string | 否 | 要扫描的目录（默认使用服务端配置的保存目录，**必须是字符串或 null**，与 GUI QFileDialog 对齐） |
| `scan_limit` | int | 否 | 最多扫描文件数（默认从配置读取，通常 1000，**必须是整数且大于 0**，与 SDK scan_directory 对齐） |

### 方式 6：REST API 直接下载

**与 CLI `ucrawl download` 和 SDK `download_video()` 输入输出完全一致。**

```bash
# 直接下载指定 URL 的视频
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://...", "source": "douyin", "title": "视频标题"}'

# 指定保存目录
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://...", "source": "missav", "title": "ABC-123", "save_dir": "/path/to/downloads"}'

# MissAV 下载带代理（与 CLI --config 和 SDK config 对齐）
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://missav.ws/...", "source": "missav", "title": "ABC-123", "config": {"proxy": "http://127.0.0.1:7890"}}'
```

#### `/api/download` 请求参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 是 | 视频 URL |
| `source` | string | 是 | 平台：`douyin` / `bilibili` / `kuaishou` / `missav`（**必须是字符串，无效平台会返回错误**） |
| `title` | string | 否 | 视频标题（默认使用 URL） |
| `save_dir` | string \| null | 否 | 保存目录（默认使用服务端配置，**必须是字符串或 null**） |
| `timeout` | float | 否 | 下载超时秒数（默认 300，**必须是数字**，与 CLI 和 SDK 对齐） |
| `config` | object | 否 | 平台特定参数（**必须是 JSON 对象**，同 `/api/search` 的 config，如 missav 的 `{"proxy": "http://127.0.0.1:7890"}`） |
| `cookie` | string | 否 | 便捷参数：Cookie 字符串（与 CLI `--cookie` 对齐，优先级高于 `config.cookie`） |
| `download_strategy` | string | 否 | 便捷参数：下载策略 m3u8/http（与 CLI `--download-strategy` 对齐，优先级高于 `config.download_strategy`） |
| `referer` | string | 否 | 便捷参数：Referer 请求头（与 CLI `--referer` 对齐，优先级高于 `config.referer`） |
| `ua` | string | 否 | 便捷参数：User-Agent 请求头（与 CLI `--ua` 对齐，优先级高于 `config.ua`） |
| `folder_name` | string | 否 | 便捷参数：子目录名（与 CLI `--folder-name` 对齐，优先级高于 `config.folder_name`） |
| `use_subdir` | bool | 否 | 便捷参数：使用子目录保存（与 CLI `--use-subdir` 对齐，优先级高于 `config.use_subdir`） |
| `file_name` | string | 否 | 便捷参数：输出文件名（与 CLI `--file-name` 对齐，优先级高于 `config.file_name`） |
| `content_type` | string | 否 | 便捷参数：内容类型 video/image/gallery（与 CLI `--content-type` 对齐，优先级高于 `config.content_type`） |
| `proxy` | string | 否 | 便捷参数：代理 URL（与 CLI `--proxy` 对齐，优先级高于 `config.proxy`。MissAV 平台会自动调用 `build_missav_proxy_url` 转换） |
| `individual_only` | bool | 否 | 便捷参数：只看单体作品（MissAV 专属，与 CLI `--individual-only` 对齐，优先级高于 `config.individual_only`） |
| `priority` | string | 否 | 便捷参数：优先级（MissAV 专属，与 CLI `--priority` 对齐，优先级高于 `config.priority`） |

### `/api/media/{video_id}` 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `video_id` | string | 是 | 视频 ID（路径参数，与 items 中的 id 字段一致） |
| `Range` | string | 否 | HTTP Range 请求头（如 `bytes=0-1048575`，视频 seek 必需） |

返回：媒体文件流（支持 206 Partial Content），文件不存在返回 404。

### 方式 7：REST API 辅助端点

```bash
# 健康检查（验证服务是否运行）
curl http://localhost:8000/api/ping

# 列出所有可用平台（与 CLI `ucrawl platforms` 和 SDK `sdk.list_platforms()` 对齐）
curl http://localhost:8000/api/platforms

# 停止正在运行的爬虫
curl -X POST http://localhost:8000/api/crawl/stop

# 异步爬取时通过 REST API 进行二次选择（与 WebSocket select_tasks 对齐）
curl -X POST http://localhost:8000/api/crawl/select \
  -H "Content-Type: application/json" \
  -d '{"indices": [0, 2, 5]}'

#### `/api/crawl/select` 请求参数与响应

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `indices` | int[] | 否 | 选中的索引数组（**必须是整数数组**，与 GUI SelectionDialog 对齐） |

成功响应：`{"status": "ok"}`

错误条件：
- 当前没有正在运行的爬虫：`{"status": "error", "error": "当前没有正在运行的爬虫，无法进行二次选择"}`
- indices 不是整数数组：`{"status": "error", "error": "indices 必须是整数数组"}`

#### `/api/dir/change` 请求参数与响应

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `directory` | string | 是 | 新的保存目录（**必须是字符串，不能为空**，与 GUI QFileDialog 对齐） |

成功响应（与 `/api/scan` 返回结构一致）：

```json
{
  "status": "ok",
  "directory": "./new-downloads",
  "items": [...],
  "total_count": 10,
  "video_count": 8,
  "image_count": 2,
  "truncated": false,
  "original_count": 10,
  "message": "已加载 10 个本地文件 (视频: 8, 图片: 2)"
}
```

# 浏览文件系统目录（供前端文件夹选择器使用）
curl "http://localhost:8000/api/dir/list?path=./downloads"

# 更改保存目录（同时扫描新目录，与 GUI 切换目录对齐）
curl -X POST http://localhost:8000/api/dir/change \
  -H "Content-Type: application/json" \
  -d '{"directory": "./new-downloads"}'

# 弹出系统原生文件夹选择对话框（Windows 专用，与 GUI QFileDialog 对齐）
curl -X POST http://localhost:8000/api/dir/pick-native

# 获取当前状态（保存目录、是否正在爬取、视频数量）
curl http://localhost:8000/api/state

# 获取/更新配置
curl http://localhost:8000/api/config
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"download": {"max_concurrent": 5}}'

# 删除视频
curl -X DELETE http://localhost:8000/api/video/{video_id}

# 重命名视频
curl -X POST http://localhost:8000/api/video/rename \
  -H "Content-Type: application/json" \
  -d '{"video_id": "xxx", "new_title": "新标题"}'

# 流式播放/下载媒体文件（支持 Range 请求，视频拖拽进度条必需）
curl http://localhost:8000/api/media/{video_id}
# Range 请求示例（视频 seek）
curl -H "Range: bytes=0-1048575" http://localhost:8000/api/media/{video_id}

# 获取最新调试日志（返回文本文件）
curl http://localhost:8000/api/debug/latest-log

# 获取最新错误摘要（返回 Markdown 文件）
curl http://localhost:8000/api/debug/error-summary

# 调试用：模拟二次选择弹窗（发送测试 select_tasks 事件到 WebSocket）
curl -X POST http://localhost:8000/api/debug/trigger-select
```

## 参数参考

### 通用参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `source` / `-s` | 是 | 平台：`douyin` / `bilibili` / `kuaishou` / `missav`（CLI 平台别名也支持短名：`dy` / `bili` / `bl` / `ks` / `miss`） |
| `keyword` | 是 | 搜索关键词 / 视频链接 / 用户 ID |
| `save-dir` / `-d` | 否 | 保存目录（默认：从配置读取） |
| `--config` | 否 | 平台特定配置（JSON 字符串，如 `'{"max_items":50}'`，与 CLI download --config 和 SDK config 对齐） |
| `--cookie` | 否 | Cookie 字符串（与 `--config '{"cookie":"..."}'` 等价，与 GUI spider cookie 对齐） |
| `--download-strategy` | 否 | 下载策略（m3u8/http，与 GUI spider `build_download_meta` 对齐） |
| `--referer` | 否 | Referer 请求头（与 `--config '{"referer":"..."}'` 等价，与 GUI spider `build_download_meta` 对齐） |
| `--ua` | 否 | User-Agent 请求头（与 `--config '{"ua":"..."}'` 等价，与 GUI spider `build_download_meta` 对齐） |
| `--content-type` | 否 | 内容类型（与 `--config '{"content_type":"gallery"}'` 等价，video/image/gallery，影响文件扩展名和保存路径，与 GUI spider `build_download_meta` 对齐） |
| `--folder-name` | 否 | 子目录名（与 `--config '{"folder_name":"..."}'` 等价，传入时自动启用 `--use-subdir`，与 GUI BilibiliSpider `"use_subdir": bool(folder_name)` 行为对齐） |
| `--use-subdir` | 否 | 使用子目录保存（与 `--config '{"use_subdir":true}'` 等价，传入 `--folder-name` 时自动启用，无需显式设置） |
| `--file-name` | 否 | 输出文件名（与 `--config '{"file_name":"..."}'` 等价，不含扩展名，与 GUI spider `build_download_meta` 对齐） |
| `--timeout` | 否 | spider HTTP 超时秒（默认 10，传入 config，仅 CLI 有此参数；SDK/REST API 通过 `config={"timeout": N}` 设置） |
| `--run-timeout` | 否 | 整体超时秒（对应 SDK `run_timeout` 参数和 REST API `timeout` 参数，默认无限。SDK 的 `timeout` 参数已弃用，建议使用 `run_timeout`） |
| `--proxy` | 否 | 代理 URL（与 `--config '{"proxy":"http://127.0.0.1:7890"}'` 等价，MissAV 平台会自动调用 `build_missav_proxy_url` 转换） |
| `--individual-only` | 否 | 只看单体作品（MissAV 专属，与 `--config '{"individual_only":true}'` 等价） |
| `--priority` | 否 | 优先级（MissAV 专属，与 `--config '{"priority":"中文字幕优先"}'` 等价） |
| `no-download` | 否 | 只搜索不下载（默认会自动下载，与 GUI 一致） |

### 下载命令参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `video_id` | 是 | 视频 ID / 标题 |
| `--url` | 条件必填 | 视频 URL（实际下载时必填，需配合 --source 使用） |
| `--source` / `-s` | 条件 | 平台 ID（使用 --url 时必填，**必须是有效平台 ID，无效平台会返回错误**，与 SDK/REST API 对齐） |
| `--save-dir` / `-d` | 否 | 保存目录（默认：从配置读取） |
| `--timeout` | 否 | 下载超时秒数（默认 300，与 SDK/REST API 一致） |
| `--config` | 否 | 平台特定配置（JSON 字符串，如 `'{"proxy":"http://127.0.0.1:7890"}'`，与 SDK config 和 REST API config 对齐） |
| `--cookie` | 否 | Cookie 字符串（与 `--config '{"cookie":"..."}'` 等价，与 GUI spider cookie 对齐） |
| `--download-strategy` | 否 | 下载策略（m3u8/http，与 GUI spider `build_download_meta` 对齐） |
| `--referer` | 否 | Referer 请求头（与 `--config '{"referer":"..."}'` 等价，与 GUI spider `build_download_meta` 对齐） |
| `--ua` | 否 | User-Agent 请求头（与 `--config '{"ua":"..."}'` 等价，与 GUI spider `build_download_meta` 对齐） |
| `--folder-name` | 否 | 子目录名（与 `--config '{"folder_name":"..."}'` 等价，传入时自动启用 `--use-subdir`，与 GUI BilibiliSpider `"use_subdir": bool(folder_name)` 行为对齐） |
| `--use-subdir` | 否 | 使用子目录保存（与 `--config '{"use_subdir":true}'` 等价，传入 `--folder-name` 时自动启用，无需显式设置） |
| `--file-name` | 否 | 输出文件名（与 `--config '{"file_name":"..."}'` 等价，不含扩展名） |
| `--content-type` | 否 | 内容类型（与 `--config '{"content_type":"gallery"}'` 等价，video/image/gallery，影响文件扩展名和保存路径，与 GUI spider `build_download_meta` 对齐） |
| `--proxy` | 否 | 代理 URL（与 `--config '{"proxy":"http://127.0.0.1:7890"}'` 等价，MissAV 平台会自动调用 `build_missav_proxy_url` 转换，与 CLI search `--proxy` 对齐） |
| `--individual-only` | 否 | 只看单体作品（MissAV 专属，与 `--config '{"individual_only":true}'` 等价，与 CLI search `--individual-only` 对齐） |
| `--priority` | 否 | 优先级（MissAV 专属，与 `--config '{"priority":"中文字幕优先"}'` 等价，与 CLI search `--priority` 对齐） |
| `--quiet` / `-q` | 否 | 不输出下载进度到 stderr（与 search --quiet 对齐） |
| `--pretty` | 否 | 人类可读格式输出（默认 JSON，与 search --pretty 对齐） |

### 扫描命令参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `directory` | 是 | 要扫描的目录 |
| `--limit` | 否 | 最多扫描文件数（默认：从配置读取，通常 1000） |
| `--quiet` / `-q` | 否 | 不输出扫描进度到 stderr（与 search/download --quiet 对齐） |
| `--pretty` | 否 | 人类可读格式输出（默认 JSON，与 search/download --pretty 对齐） |

### SDK `search()` 参数

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `source` | 是 | str | 平台 ID（douyin/bilibili/kuaishou/missav） |
| `keyword` | 是 | str | 搜索关键词 / 链接 / 用户 ID |
| `save_dir` | 否 | str \| None | 保存目录（None=从配置读取，与 GUI 对齐） |
| `selection` | 否 | SelectionStrategy \| str \| list[int] \| dict \| None | 二次选择策略（None=AutoSelection，"all"/"first"/"last"=快捷策略，list[int]=指定索引，dict=与 REST API 对齐） |
| `timeout` | 否 | float \| None | 整体超时秒数（已弃用，建议使用 `run_timeout`。若需设置 spider HTTP 超时，通过 `**config` 传入 `timeout` 关键字） |
| `download` | 否 | bool | 是否触发下载（True=与 GUI 一致自动下载，默认 True） |
| `run_timeout` | 否 | float \| None | 整体超时秒数（None=无限，优先级高于 `timeout`，与 CLI --run-timeout 对齐） |
| `**config` | 否 | — | 平台特定参数（如 `max_items=20`、`proxy="http://..."` 等，与 CLI --config 和 REST API config 对齐） |

### SDK `download_video()` 参数

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `url` | 是 | str | 视频 URL |
| `source` | 是 | str | 平台 ID（douyin/bilibili/kuaishou/missav） |
| `title` | 否 | str | 视频标题（默认使用 URL，与 CLI download 对齐） |
| `save_dir` | 否 | str \| None | 保存目录（None=从配置读取，与 GUI 对齐） |
| `timeout` | 否 | float | 下载超时秒数（默认 300，与 CLI download --timeout 和 REST API /api/download timeout 对齐） |
| `verbose` | 否 | bool | 是否输出下载进度到 stderr（默认 False，与 CLI download --quiet 对齐：CLI 默认 verbose=True，加 --quiet 时 verbose=False） |
| `config` | 否 | dict \| None | 平台特定配置（None=使用平台默认值，与 REST API /api/download 的 config 对齐） |
| `progress_callback` | 否 | Callable[[int], None] \| None | 下载进度回调（None=不回调，进度范围 0-100，与 GUI DownloadManager task_progress 信号对齐） |

### SDK `scan_directory()` 参数

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `directory` | 是 | str | 要扫描的目录 |
| `scan_limit` | 否 | int \| None | 最多扫描文件数（None=从配置读取，与 GUI/Web 一致，默认 1000） |

### 平台列表命令参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--describe` | 否 | 显示指定平台的详细参数（如 `--describe douyin`） |
| `--quiet` / `-q` | 否 | 不输出额外信息到 stderr（与 scan/search/download --quiet 对齐） |
| `--pretty` | 否 | 人类可读格式输出（默认 JSON，显示搜索提示和描述，与 SDK list_platforms() 对齐） |

### 交互式命令参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--save-dir` / `-d` | 否 | 保存目录（默认：从配置读取，与 search 对齐） |
| `--run-timeout` | 否 | 整体超时秒（与 search --run-timeout 对齐，默认无限等待） |
| `--no-download` | 否 | 只搜索不下载（与 search --no-download 对齐） |
| `--quiet` / `-q` | 否 | 不输出 spider 日志（与 search --quiet 对齐） |
| `--pretty` | 否 | 人类可读格式输出（与 search --pretty 对齐） |
| `--config` | 否 | 平台特定配置（JSON 字符串，与 search/download --config 对齐。交互式输入的参数优先级高于 --config） |
| `--cookie` | 否 | Cookie 字符串（与 `--config '{"cookie":"..."}'` 等价，与 GUI spider cookie 对齐） |
| `--download-strategy` | 否 | 下载策略（m3u8/http，与 GUI spider `build_download_meta` 对齐） |
| `--referer` | 否 | Referer 请求头（与 `--config '{"referer":"..."}'` 等价，与 GUI spider `build_download_meta` 对齐） |
| `--ua` | 否 | User-Agent 请求头（与 `--config '{"ua":"..."}'` 等价，与 GUI spider `build_download_meta` 对齐） |
| `--content-type` | 否 | 内容类型（与 `--config '{"content_type":"gallery"}'` 等价，video/image/gallery，影响文件扩展名和保存路径，与 GUI spider `build_download_meta` 对齐） |
| `--folder-name` | 否 | 子目录名（与 `--config '{"folder_name":"..."}'` 等价，传入时自动启用 `--use-subdir`，与 GUI BilibiliSpider `"use_subdir": bool(folder_name)` 行为对齐） |
| `--use-subdir` | 否 | 使用子目录保存（与 `--config '{"use_subdir":true}'` 等价，传入 `--folder-name` 时自动启用，无需显式设置） |
| `--file-name` | 否 | 输出文件名（与 `--config '{"file_name":"..."}'` 等价，不含扩展名，与 GUI spider `build_download_meta` 对齐） |
| `--proxy` | 否 | 代理 URL（与 `--config '{"proxy":"http://127.0.0.1:7890"}'` 等价，MissAV 平台会自动调用 `build_missav_proxy_url` 转换，与 CLI search/download `--proxy` 对齐） |
| `--individual-only` | 否 | 只看单体作品（MissAV 专属，与 `--config '{"individual_only":true}'` 等价，与 CLI search/download `--individual-only` 对齐） |
| `--priority` | 否 | 优先级（MissAV 专属，与 `--config '{"priority":"中文字幕优先"}'` 等价，与 CLI search/download `--priority` 对齐） |
| `--all` | 否 | 全选（与 search --all 对齐，默认使用 AutoSelection） |
| `--first` | 否 | 只选第一个（与 search --first 对齐） |
| `--last` | 否 | 只选最后一个（与 search --last 对齐） |
| `--select "0,2,5"` | 否 | 指定索引（与 search --select 对齐，支持范围如 0,2-5 或 0,2:5） |
| `--exclude "1,3"` | 否 | 排除索引（与 search --exclude 对齐，支持范围如 1,3-5 或 1,3:5） |
| `--pipe` | 否 | 强制 stdin 管道选择（与 search --pipe 对齐） |
| `--preload-choices "0\|1,2\|3"` | 否 | 预加载多次选择（与 search --preload-choices 对齐，`\|` 分轮，`逗号` 分索引） |

### 平台特定参数

#### 抖音 (douyin)
- `max_items` (int): 最大视频数（默认从配置读取，兜底 20）
- `timeout` (int/float): HTTP 超时秒（默认从配置读取，兜底 10，仅影响 spider 网络请求，与 REST API `/api/search` 的 `timeout` 整体超时不同）
- `aweme_id` (str): 抖音视频 ID（与 GUI spider `build_download_meta` 对齐，通常由 spider 自动设置）
- `is_gallery` (bool): 是否为图集（与 GUI spider `build_download_meta` 对齐，通常由 spider 自动设置）
- `is_mix` (bool): 是否为合集（与 GUI spider `build_download_meta` 对齐，通常由 spider 自动设置）
- `images_data` (list): 图集图片数据（与 GUI spider `DouyinTaskBuilder.build_items` 对齐，通常由 spider 自动设置，DouyinDownloader 读取此字段下载图集）
- `size_mb` (int/float): 文件大小 MB（与 GUI spider 设置对齐，BaseDownloader 读取此字段决定是否使用分块下载策略）
- `media_label` (str): 媒体类型标签（与 GUI spider `build_download_meta` 对齐，如"视频"/"图集"/"实况"，用于日志显示）

#### B站 (bilibili)
- `max_pages` (int): 翻页数（默认从配置读取，兜底 1）
- `max_items` (int): 最大视频数（兜底 30）
- `audio_url` (str): DASH 格式音频流 URL（与 GUI spider `build_download_meta` 对齐，通常由 spider 自动设置）
- `bvid` (str): B站视频 BV 号（与 GUI spider `build_download_meta` 对齐，通常由 spider 自动设置）
- `cid` (str): B站视频 CID（与 GUI spider `build_download_meta` 对齐，通常由 spider 自动设置）
- `file_name` (str): 输出文件名（不含扩展名，与 GUI spider `build_download_meta` 对齐）
- `preferred_filename` (str): 首选文件名（不含扩展名，与 GUI spider `build_download_meta` 对齐）

#### 快手 (kuaishou)
- `max_items` (int): 最大视频数（默认从配置读取，兜底 20）
- `download_strategy` (str): 下载策略（m3u8/http，与 GUI spider `KuaishouTaskBuilder.build_download_meta` 对齐，通常由 spider 自动设置）

#### MissAV (missav)
- `individual_only` (bool): 只看单体作品（False=默认）
- `priority` (str): "中文字幕优先"（默认） / "无码流出优先"
- `proxy` (str): 代理 URL（默认从配置读取，兜底 `http://127.0.0.1:7890`）

#### 通用下载参数（所有平台）
- `folder_name` (str): 子目录名（与 GUI spider `build_download_meta` 对齐，B站合集场景。传入 folder_name 时自动启用 use_subdir，与 GUI BilibiliSpider `"use_subdir": bool(folder_name)` 行为对齐）
- `use_subdir` (bool): 使用子目录保存（与 GUI spider `build_download_meta` 对齐。传入 folder_name 时自动启用，无需显式设置）
- `download_strategy` (str): 下载策略（m3u8/http，与 GUI spider `build_download_meta` 对齐）
- `referer` (str): Referer 请求头（与 GUI spider `build_download_meta` 对齐）
- `ua` (str): User-Agent 请求头（与 GUI spider `build_download_meta` 对齐）
- `cookie` (str): Cookie 字符串（与 GUI spider cookie 对齐）
- `cookies` (dict): Cookie 字典（与 GUI spider cookies 对齐）
- `content_type` (str): 内容类型（video/image/gallery，与 GUI spider `build_download_meta` 对齐）
- `images_data` (list): 图集图片数据（与 GUI spider `DouyinTaskBuilder.build_items` 对齐，DouyinDownloader 读取）
- `size_mb` (int/float): 文件大小 MB（与 GUI spider 设置对齐，BaseDownloader 分块下载策略）
- `media_label` (str): 媒体类型标签（与 GUI spider `build_download_meta` 对齐，如"视频"/"图集"/"实况"）
- `duration` (int/float): 视频时长秒数（与 GUI spider DouyinParser 对齐，ChunkedDownloader/FFmpegDownloader 读取，影响下载策略选择）
- `file_name` (str): 输出文件名（不含扩展名，与 GUI spider `build_download_meta` 对齐，DownloadWorker._generate_filename 读取）
- `preferred_filename` (str): 首选文件名（不含扩展名，与 GUI spider `build_download_meta` 对齐，DownloadWorker._generate_filename 读取，优先级高于 file_name）
- `mix_title` (str): 合集标题（与 GUI spider DouyinSpider._process_mix 对齐，通常由 spider 自动设置）
- `create_time` (int): 创建时间戳（与 GUI spider DouyinParser 对齐，通常由 spider 自动设置）
- `author` (str): 作者名（与 GUI spider DouyinParser 对齐，通常由 spider 自动设置，用作 folder_name。**SDK `download_video()` 自动逻辑**：传入 `author` 但未传 `folder_name` 时，自动将 `author` 设为 `folder_name`，与 GUI DouyinParser 行为一致）
- `has_live_photo` (bool): 是否包含实况照片（与 GUI spider DouyinParser 对齐，通常由 spider 自动设置）

### 二次选择参数

#### CLI 参数

| 参数 | 说明 |
|---|---|
| `--all` | 全选（默认） |
| `--first` | 只选第一个 |
| `--last` | 只选最后一个 |
| `--select "0,2,5"` | 指定索引（支持范围如 `0,2-5` 或 `0,2:5`） |
| `--exclude "1,3"` | 排除索引（支持范围如 `1,3-5` 或 `1,3:5`） |
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

# dict 格式（与 REST API selection 参数对齐）
sdk.search("douyin", "测试", selection={"strategy": "all"})
sdk.search("douyin", "测试", selection={"strategy": "rule", "select": "0,2,5"})
sdk.search("bilibili", "合集", selection={"strategy": "preload", "choices": [[0], [1,2]]})
```

#### REST API 参数

```json
{"strategy": "all"}
{"strategy": "first"}
{"strategy": "last"}
{"strategy": "rule", "select": "0,2,5", "exclude": "1,3"}
{"strategy": "preload", "choices": [[0], [1,2], [3,4,5]]}
{"strategy": "interactive"}
{"strategy": "pipe"}
```

## 返回结构

**CLI / SDK / REST API `/api/search` 返回结构完全一致：**

`status` 字段取值：`"ok"`（成功）、`"error"`（爬虫异常）、`"timeout"`（超时）、`"cancelled"`（用户取消）。

items 中每个 item 的 `status` 字段取值：
- `"✅ 完成"` — 下载成功
- `"❌ 失败"` — 下载失败（错误原因在 `meta.download_error`）
- `"⏳ 等待中"` — 等待下载（download=true 时）
- `"⏳ 下载中..."` — 正在下载
- `"📋 已收集"` — 仅搜索未下载（download=false 时，与 GUI 的"⏳ 等待中"区分）
- `"❌ 超时"` — 下载超时

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

### 下载返回结构

**CLI `ucrawl download` / SDK `download_video()` / REST API `/api/download` 返回结构完全一致：**

**REST API/WebSocket download 的 video_id 一致性**：下载请求发出后立即创建 `pending_item`（video_id=A），广播 `item_found`/`task_started`/`video_state_changed` 事件。下载完成后就地更新 `pending_item` 属性（status/progress/local_path/title/meta），**video_id 始终为 A**，不会因 SDK 内部创建新 VideoItem 而改变。前端可通过同一 video_id 追踪整个下载生命周期（task_started → task_finished/task_error）。

成功时：

```json
{
  "status": "ok",
  "video_id": "...",
  "url": "https://...",
  "source": "douyin",
  "local_path": "/path/to/file.mp4",
  "title": "视频标题",
  "save_dir": "downloads",
  "content_type": "video",
  "meta": {...},
  "elapsed": 12.34
}
```

失败时：

```json
{
  "status": "error",
  "video_id": "...",
  "url": "https://...",
  "source": "douyin",
  "title": "视频标题",
  "error": "下载失败原因",
  "save_dir": "downloads",
  "local_path": "",
  "content_type": "",
  "meta": {"download_error": "下载失败原因"},
  "elapsed": 5.67
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | `"ok"`（成功）、`"error"`（下载失败）、`"timeout"`（下载超时） |
| `video_id` | string | 唯一标识（UUID） |
| `url` | string | 视频 URL（与输入一致） |
| `source` | string | 平台 ID |
| `title` | string | 视频标题 |
| `local_path` | string | 本地文件路径（成功时为实际路径，失败时为空字符串 `""`） |
| `error` | string | 错误原因（仅失败时） |
| `save_dir` | string | 保存目录 |
| `content_type` | string | 内容类型（video/image/gallery，与 search 返回的 items 对齐。**注意**：直接下载 `download_video()` 不经过 spider，content_type 由文件扩展名推断：视频文件→"video"，图片文件→"image"，无法推断→空字符串 `""`；通过 `search(download=True)` 下载时 content_type 由 spider 设置） |
| `meta` | object | 平台特定元数据（失败时包含 `download_error`，与 search 返回的 items 对齐） |
| `elapsed` | float | 下载耗时（秒，与 search 返回的 elapsed 字段对齐） |

**REST API/WebSocket download 异常处理**：当 SDK 抛出 TypeError/ValueError（参数校验失败）或其他异常时，`pending_item` 保留在 `controller.videos` 中，状态设为 `"❌ 失败"`，`meta.download_error` 记录错误原因（与 SDK 返回 `{"status": "error"}` 结果路径完全一致，与 GUI `_on_download_error` 行为对齐：失败条目保留在列表中可见，用户可查看失败原因或删除条目）。当 SDK 返回 `{"status": "timeout"}` 时，`pending_item` 状态设为 `"❌ 超时"`（与 GUI/CLI CLIRunner 对齐），`video_state_changed` 事件的 `status` 字段也为 `"❌ 超时"`，WebSocket 客户端可据此区分超时与其他错误。

### 扫描返回结构

**CLI `ucrawl scan` / SDK `scan_directory()` / REST API `/api/scan` 返回结构完全一致：**

```json
{
  "status": "ok",
  "directory": "./downloads",
  "items": [
    {
      "id": "...",
      "url": "",
      "title": "文件名",
      "source": "",
      "status": "✅ 本地",
      "progress": 100,
      "local_path": "./downloads/文件名.mp4",
      "content_type": "video",
      "meta": {}
    }
  ],
  "total_count": 10,
  "video_count": 8,
  "image_count": 2,
  "truncated": false,
  "original_count": 10,
  "message": "已加载 10 个本地文件 (视频: 8, 图片: 2)"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `directory` | string | 扫描的目录路径 |
| `items` | array | 文件列表（每个 item 与 search 返回的 items 字段一致） |
| `total_count` | int | 文件总数 |
| `video_count` | int | 视频文件数 |
| `image_count` | int | 图片文件数 |
| `truncated` | bool | 是否因文件过多而截断 |
| `original_count` | int | 截断前的原始文件数（未截断时等于 total_count） |
| `message` | string | 人类可读的扫描结果摘要 |

### 错误响应格式

REST API 在参数校验失败或执行异常时返回：

```json
{"status": "error", "error": "source 和 keyword 必须是字符串"}
{"status": "error", "error": "source 和 keyword 为必填参数"}
{"status": "error", "error": "无效平台: youtube。支持: ['douyin', 'bilibili', 'kuaishou', 'missav']"}
{"status": "error", "error": "config 必须是 JSON 对象"}
{"status": "error", "error": "selection 必须是 JSON 对象或 null"}
{"status": "error", "error": "无效选择策略。支持: ['all', 'first', 'last', 'rule', 'preload', 'interactive', 'pipe']"}
{"status": "error", "error": "timeout 必须是数字"}
{"status": "error", "error": "timeout 必须大于 0"}
{"status": "error", "error": "indices 必须是整数数组"}
{"status": "error", "error": "当前已有任务在运行，请先停止或等待结束"}
{"status": "error", "error": "当前没有正在运行的爬虫，无法进行二次选择"}
{"status": "error", "error": "无法启动爬虫，请检查平台 xxx 是否正确"}
{"status": "error", "error": "directory 必须是字符串"}
{"status": "error", "error": "video_id 和 new_title 必须是字符串"}
{"status": "error", "error": "video_id 必须是字符串"}
{"status": "error", "error": "save_dir 必须是字符串或 null"}
{"status": "error", "error": "目录路径不能为空"}
{"status": "error", "error": "请求体必须是 JSON 对象"}
{"status": "error", "error": "url 和 source 必须是字符串"}
{"status": "error", "error": "url 和 source 为必填参数"}
{"status": "error", "error": "title 必须是字符串"}
{"status": "error", "error": "save_dir 必须是字符串或 null"}
{"status": "error", "error": "dark_theme 必须是布尔值"}
{"status": "error", "error": "source 必须是字符串"}
{"status": "error", "error": "section 和 key 必须是字符串"}
{"status": "error", "error": "保存配置失败: ..."}
{"status": "error", "error": "config.max_items 必须是整数，收到 str"}
{"status": "error", "error": "config.individual_only 必须是布尔值，收到 str"}
{"status": "error", "error": "config.priority 必须是字符串，收到 int"}
{"status": "error", "error": "download 必须是布尔值"}
{"status": "error", "error": "无效平台: xxx。支持: ['douyin', 'bilibili', 'kuaishou', 'missav']"}
{"status": "error", "error": "启动爬虫异常: ..."}
{"status": "error", "error": "scan_limit 必须大于 0"}
{"status": "error", "error": "scan_limit 必须是整数"}
{"status": "error", "error": "此端点始终触发下载，不支持 download 参数。如需只搜索不下载，请使用 POST /api/search 并传 download: false"}
```

CLI search `--config` 校验错误（与 CLI download `--config` 对齐）：
```
❌ --config 必须是 JSON 对象
❌ --config JSON 解析失败: ...
```

CLI/SDK 在参数错误时返回非零退出码 + stderr 错误信息。SDK 在参数类型错误时抛出 `TypeError`，在参数值错误时抛出 `ValueError`（注意：SDK `_validate_config` 抛出的 TypeError/ValueError 会去掉 "config." 前缀，例如 `max_items 必须是整数` 而非 `config.max_items 必须是整数`，与 REST API 返回的 `config.xxx` 前缀格式不同，这是因为 SDK 作为 Python 库，参数名本身就是 `max_items` 而非 `config.max_items`）。SDK 额外校验：`__init__` 的 `save_dir` 必须是字符串或 None、`config` 必须是字典或 None；`search()` 的 `save_dir` 必须是字符串或 None、`run_timeout`/`timeout` 必须大于 0（`run_timeout` 优先，`timeout` 已弃用但仍向后兼容；若需设置 spider HTTP 超时，请通过 `**config` 传入 `timeout` 关键字，如 `sdk.search(..., run_timeout=60, **{"timeout": 10})`）；`download_video()` 的 `title` 必须是字符串、`save_dir` 必须是字符串或 None、`timeout` 必须是数字且大于 0、`verbose` 必须是布尔值（默认 False，与 CLI `download --quiet` 对齐：CLI 默认 verbose=True，加 --quiet 时 verbose=False）；`scan_directory()` 的 `directory` 必须是非空字符串、`scan_limit` 必须是整数或 None（与 `search()`/`download_video()` 对齐，参数校验抛出 TypeError/ValueError 而非返回 error dict）；selection 的 `preload` 策略 `choices` 必须是二维数组、`rule` 策略的 `select`/`exclude` 必须是字符串或 null；**config 已知参数类型校验**（与 CLI argparse type 对齐）：`max_items`/`max_pages`/`timeout` 必须是整数、`individual_only` 必须是布尔值、`priority`/`proxy` 必须是字符串，未知参数透传给 spider 不做校验。REST API 同样校验 config 已知参数类型，返回 `{"status": "error", "error": "config.xxx 必须是xxx，收到 xxx"}`。**config 合并行为**：SDK/REST API/CLI search 会过滤用户 config 中的 None 值再与平台默认值合并（与 CLI `_build_config` 对齐，避免 null 覆盖默认值）。**CLI search --config 合并顺序**：平台默认值 → `--config` JSON → 独立参数（`--max-items`/`--timeout` 等优先级最高，与 SDK `search(**config)` 覆盖 `default_config` 的语义对齐）。**download 参数校验**：REST API `/api/search` 的 `download` 参数不接受 list/dict 类型（会返回错误），避免 `bool([])` 误判；传 `null` 视为未提供，使用默认值 true。**REST API/WebSocket download title 校验**：先校验 title 类型（必须是字符串或 null），再应用默认值（null/空字符串 → URL），避免非字符串 falsy 值（如 `0`、`false`）被静默替换为 URL。**save_dir 回退行为**：REST API `/api/download` 和 WebSocket `download` 在 `save_dir` 未提供时使用 `controller.current_save_dir`（与 `/api/search` 对齐，而非从 cfg 重新读取）。**CLI download 输出控制**：`--quiet`/`-q` 不输出下载进度到 stderr（与 search --quiet 对齐），`--pretty` 人类可读格式输出（与 search --pretty 对齐，显示状态/平台/标题/URL/保存目录/本地路径/类型）。**CLI interactive 二次选择策略**：interactive 命令现在支持 `--all`/`--first`/`--last`/`--select`/`--exclude`/`--pipe`/`--preload-choices` 参数（与 search 命令对齐），默认仍使用 AutoSelection（有 TTY 交互，无 TTY 管道，否则全选）。
- **CLI/SDK/REST API config 参数**：CLI search 和 download 的 `--config` 都接受 JSON 字符串，SDK `search(**config)` 和 `download_video(config=)` 接受字典，REST API `/api/search` 和 `/api/download` 的 `config` 接受 JSON 对象，四者对齐。config 中的 missav proxy 会自动转换（与 GUI `build_missav_proxy_url` 一致）。config 参数同样经过 `_validate_config_types` 校验。

### items 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一标识（UUID） |
| `url` | string | 资源 URL |
| `title` | string | 标题 |
| `source` | string | 平台 ID |
| `status` | string | 状态：`⏳ 等待中` / `⏳ 下载中...` / `✅ 完成` / `❌ 失败` / `❌ 超时` / `✅ 本地` / `📋 已收集` |
| `progress` | int | 进度 0-100 |
| `local_path` | string | 本地文件路径 |
| `content_type` | string | 内容类型（video/image/gallery） |
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
| CLI | `ucrawl search` / `ucrawl download` | `--select`/`--preload-choices`/交互 | JSON dict（同下） |
| SDK | `UcrawlSDK.search()` / `UcrawlSDK.download_video()` | `selection` 参数 | dict（同下） |
| REST API | `POST /api/search` / `POST /api/download` | `selection` JSON | dict（同下） |

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
- **REST API 异步爬取**：`POST /api/crawl/start` + WebSocket 交互，适合前端实时更新。**此端点始终触发下载（与 GUI 一致），如果请求体包含 `download` 参数会返回错误**，请使用 `POST /api/search` + `download: false` 实现只搜索不下载
- **WebSocket stop_crawl**：发送 `{"type": "stop_crawl"}` 可停止正在运行的爬虫（与 REST API `POST /api/crawl/stop` 和 GUI 停止按钮对齐）
- **启动时注入脚本**：用 `python web_main.py --script xxx.py`，脚本在子线程中运行，不阻塞 web 服务
- **CLI 结构化日志**：CLIRunner 与 GUI/WebController 对齐，使用 debug_logger 记录关键事件（爬虫启动/完成、item 发现、下载完成/失败），便于 CLI 问题排查
- **下载失败 progress=0**：所有层（GUI/CLI/SDK/Web）在下载失败时统一将 progress 重置为 0，与 REST API `/api/download` 错误路径对齐
- **REST API/WebSocket download 异常广播**：当 `POST /api/download` 或 WebSocket `download` 消息触发 SDK 异常（TypeError/ValueError/Exception）时，会广播 `task_error` + `video_state_changed` + `log` 事件，与正常下载失败流程对齐，确保前端能正确更新 UI
- **索引范围语法**：`--select`/`--exclude` 和交互式输入均支持 `-` 和 `:` 作为范围分隔符（如 `0,2-5` 或 `0,2:5`）
- **直接下载 content_type 推断**：SDK `download_video()` 和 REST API/WebSocket `download` 在直接下载时不经过 spider，`content_type` 由文件扩展名推断（视频文件→"video"，图片文件→"image"，无法推断→空字符串），与 GUI spider 设置的 content_type 对齐。推断逻辑由 `cli.defaults.infer_content_type()` 统一实现
- **CLI scan/platforms --quiet**：`ucrawl scan` 和 `ucrawl platforms` 命令支持 `--quiet`/`-q` 标志（与 search/download 命令对齐），静默模式下不输出 SDK 内部日志到 stderr
- **SDK progress_callback**：`UcrawlSDK.download_video()` 和函数式 `download_video()` 支持 `progress_callback` 参数（签名 `callback(progress: int) -> None`，进度范围 0-100），与 GUI DownloadManager 的 `task_progress` 信号对齐。REST API `/api/download` 和 WebSocket `download` 通过此回调实时广播 `task_progress` 和 `video_state_changed` 事件，让 WebSocket 客户端能显示下载进度（与 GUI 实时进度条对齐）
- **WebSocket 事件增强**：`task_finished` 事件新增 `content_type` 和 `title` 字段；`video_state_changed` 事件在完成/失败状态时新增 `local_path` 和 `content_type` 字段；`task_started` 事件新增 `title` 和 `content_type` 字段（与 `task_finished` 对齐）；`task_error` 事件新增 `local_path`、`content_type` 和 `title` 字段（与 `task_finished` 对齐）。这些增强让 WebSocket 客户端无需额外请求即可获取完整下载结果和错误信息，与 GUI 直接读取 VideoItem 对象的行为对齐
- **SDK download_video trace_id 对齐**：SDK `download_video()` 和 REST API/WebSocket `download` 在直接下载时自动生成 `trace_id`（格式 `{source_prefix}-dl-{uuid8}`，如 `dy-dl-a1b2c3d4`），与 GUI spider 通过 `build_download_meta` 设置的 `trace_id` 对齐。`DownloadWorker._trace_id()` 依赖此字段做日志关联，确保 CLI/SDK/API 的下载日志也能通过 trace_id 追踪
- **SDK download_video cookie 自动加载**：SDK `download_video()` 通过 `get_platform_download_defaults()` 自动加载本地 cookie 文件（与 GUI spider 启动时通过 AuthService 自动加载对齐），确保需要登录的平台（douyin/bilibili/kuaishou）在 CLI/SDK/API 环境下也能正常下载。用户通过 `config` 显式传入的 cookie 优先级高于自动加载的 cookie
- **SDK download_video meta 字段扩展**：SDK `download_video()` 的 meta 复制列表新增 `folder_name` 和 `use_subdir` 字段（与 GUI Bilibili spider 通过 `build_download_meta` 设置的 `folder_name`/`use_subdir` 对齐），支持通过 `config` 传入子目录结构控制
- **SDK download_video meta 字段全面对齐**：SDK `download_video()` 的 meta 复制列表进一步扩展，新增 `audio_url`（B站 DASH 音频流）、`aweme_id`（抖音视频 ID）、`bvid`/`cid`（B站视频 ID）、`file_name`/`preferred_filename`（文件名控制）、`is_gallery`/`is_mix`（图集/合集标记），与 GUI spider `build_download_meta` 和 `DownloadWorker` 读取的 meta 字段完全对齐。`validate_config_types` 同步新增这些字段的类型校验。interactive 命令的 `download_config` 提取列表同步扩展。CLI download 命令新增 `--file-name` 便捷参数
- **ucrawl 包导出补全**：`ucrawl` 包新增导出 `GUISelection` 和 `is_selection_strategy`（从 `cli.selection` 透传），确保 SDK 用户可通过 `from ucrawl import GUISelection, is_selection_strategy` 使用
- **SDK download_video meta 字段补全 images_data/size_mb/media_label**：SDK `download_video()` 的 meta 复制列表新增 `images_data`（抖音图集数据，DouyinDownloader 读取）、`size_mb`（文件大小 MB，BaseDownloader 分块下载策略）、`media_label`（媒体类型标签，GUI spider 日志使用），与 GUI spider 和下载器读取的 meta 字段完全对齐。`validate_config_types` 同步新增这些字段的类型校验（`images_data`: list, `size_mb`: int/float, `media_label`: str）。interactive 命令的 `download_config` 提取列表同步扩展
- **SDK download_video meta 字段补全 duration/mix_title/create_time/author/has_live_photo**：SDK `download_video()` 的 meta 复制列表新增 `duration`（视频时长秒数，ChunkedDownloader/FFmpegDownloader 读取，与 GUI spider DouyinParser 对齐）、`mix_title`（合集标题，与 GUI spider DouyinSpider._process_mix 对齐）、`create_time`（创建时间戳，与 GUI spider DouyinParser 对齐）、`author`（作者名，与 GUI spider DouyinParser 对齐，用作 folder_name）、`has_live_photo`（是否包含实况照片，与 GUI spider DouyinParser 对齐）。`validate_config_types` 同步新增这些字段的类型校验（`duration`: int/float, `mix_title`: str, `create_time`: int, `author`: str, `has_live_photo`: bool）。interactive 命令的 `download_config` 提取列表同步扩展。SKILL.md 通用下载参数同步补全 `duration`/`file_name`/`preferred_filename`/`mix_title`/`create_time`/`author`/`has_live_photo`
- **REST API/WebSocket 便捷参数对齐**：REST API `/api/search`、`/api/crawl/start`、`/api/download`、WebSocket `start_crawl`、`download` 消息新增便捷参数支持（与 CLI `--cookie`/`--download-strategy`/`--referer`/`--ua`/`--folder-name`/`--use-subdir`/`--file-name`/`--content-type`/`--max-items`/`--max-pages`/`--proxy`/`--individual-only`/`--priority` 对齐）。便捷参数作为请求体的顶层字段传入，优先级高于 `config` 字典中的同名参数（与 CLI 独立参数优先级高于 `--config` 的语义一致）。合并逻辑由 `cli.defaults.merge_convenience_params()` 统一实现，确保 CLI/REST API/WebSocket 三层行为一致
- **MissAVTaskBuilder download_strategy 对齐**：MissAVTaskBuilder 的 `build_download_meta` 新增 `download_strategy="m3u8"` 字段（与 KuaishouTaskBuilder 对齐，MissAV 视频始终使用 m3u8 下载策略）
- **REST API `/api/crawl/start` 便捷参数对齐**：REST API `/api/crawl/start` 新增便捷参数支持（与 `/api/search` 和 WebSocket `start_crawl` 对齐），支持 `cookie`/`download_strategy`/`referer`/`ua`/`folder_name`/`use_subdir`/`file_name`/`content_type`/`max_items`/`max_pages`/`proxy`/`individual_only`/`priority` 作为请求体顶层字段传入，优先级高于 `config` 字典。合并逻辑由 `cli.defaults.merge_convenience_params()` 统一实现，确保 REST API `/api/crawl/start` 与 `/api/search` 和 WebSocket `start_crawl` 三层行为完全一致
