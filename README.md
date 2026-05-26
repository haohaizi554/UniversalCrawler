# Universal Crawler Pro

一个面向 Windows 桌面的多平台媒体采集与下载工具，使用 `Python + PyQt6` 构建图形界面，围绕扫描 -> 选择 -> 下载 -> 本地管理 / 播放的完整流程设计。

当前真正接入并可在界面中使用的平台有：

- `抖音`
- `Bilibili`
- `快手`
- `MissAV`

项目同时包含一套较完整的 `app/core/lib/douyin` 内置能力库，用于抖音参数生成、签名处理、链接解析、接口访问与数据提取。仓库中仍保留部分 TikTok 相关底层模块，但桌面程序当前没有把 TikTok 作为 UI 可选平台接入。

## 目录

- [项目预览](#项目预览)
- [项目特点](#项目特点)
- [支持平台与能力矩阵](#支持平台与能力矩阵)
- [界面与使用流程](#界面与使用流程)
- [运行环境](#运行环境)
- [安装与启动](#安装与启动)
- [配置文件说明](#配置文件说明)
- [日志与调试](#日志与调试)
- [项目结构](#项目结构)
- [核心架构说明](#核心架构说明)
- [测试与质量保障](#测试与质量保障)
- [二次开发指南](#二次开发指南)
- [FAQ](#faq)
- [常见问题排查](#常见问题排查)
- [更新记录模板](#更新记录模板)
- [当前边界与限制](#当前边界与限制)
- [相关文档](#相关文档)
- [免责声明](#免责声明)

## 项目预览

> 当前仓库暂未放入正式截图，下面保留 GitHub 风格展示占位，后续可直接替换为真实图片或 GIF。

### 主界面截图占位

```text
[Screenshot Placeholder]
- 顶部平台切换与动态配置区
- 左侧下载队列
- 右上媒体预览
- 右下日志面板
```

### 下载流程截图占位

```text
[Screenshot Placeholder]
- Spider 扫描结果弹窗
- 任务进入队列
- 进度条更新
- 完成后本地预览
```

### 调试能力截图占位

```text
[Screenshot Placeholder]
- 最新日志
- 错误摘要
- 复制 Trace
- latest_error_summary.md 示例
```

## 项目特点

### 面向桌面实际使用

- 不是 Web 服务，而是本地 GUI 程序。
- 使用 `PyQt6` 提供图形界面，支持下载队列、本地媒体管理、日志查看与播放器联动。
- 默认围绕 Windows 环境打磨，仓库根目录直接支持放置 `ffmpeg.exe` 与 `N_m3u8DL-RE.exe`。

### 多平台统一下载链路

- 各平台 Spider 统一下沉到 `app/spiders/<platform>/spider.py`。
- 解析逻辑与任务装配逻辑拆分到 `parser.py` 与 `task_builder.py`。
- 下载统一接入 `DownloadManager`，按任务元数据自动选择合适的下载器或外部工具。

### 调试能力内建

- 运行日志会落到 `logs/`。
- 生成 `latest_debug.log` 和 `latest_error_summary.md`。
- 支持全链路 `trace_id` 串联。
- UI 顶部提供 `最新日志`、`错误摘要`、`复制Trace` 三个调试入口。
- 外部命令如 `ffmpeg`、`N_m3u8DL-RE` 会记录实际注入参数。

### 配置、异常、测试持续收口

- 配置由 `app/config/settings.py` 统一管理，带默认值、字段归一化与基础校验。
- 常见错误已拆分到 `config / spider / downloader / service` 多层异常。
- 仓库已补有覆盖配置、下载器、控制器、主窗口、Spider helper、认证服务等方向的单元测试。

## 支持平台与能力矩阵

| 平台 | UI 可选 | 登录方式 | 主要输入 | 扫描方式 | 下载方式 |
| --- | --- | --- | --- | --- | --- |
| 抖音 | 是 | 扫码登录 | 作品链接 / 主页链接 / 合集链接 / 关键词 / 分享短链 | 内置 Douyin 库 + 参数更新 + 链接解析 | `requests` / 断点续传 / 图集拆分 / 必要时 `m3u8` |
| Bilibili | 是 | 扫码登录 | `BV` / 视频 URL / UP 主页 URL / UID / 搜索关键词 | 浏览器扫描 + API 详情解析 | 视频音频分流下载 + `ffmpeg` 合并 |
| 快手 | 是 | 浏览器登录 | 主页链接 / 关键词 | Playwright 页面滚动与媒体请求嗅探 | 根据 `http / m3u8` 策略下载 |
| MissAV | 是 | 无站内登录流程 | 番号 / 演员 / 分类 URL / 列表 URL / 详情页 URL | Playwright 访问页面并嗅探 `playlist.m3u8` | `N_m3u8DL-RE.exe` |
| TikTok | 否 | 未接入 UI | 无 | 仅保留底层模块 | 当前不可直接在桌面程序中使用 |

## 各平台已实现能力

### 抖音

- 支持用户主页链接、作品链接、分享短链、合集链接、带 `modal_id` 的页面链接。
- 支持用户昵称 / 抖音号风格输入分流。
- 自动扫码登录，登录信息保存到 `dy_auth.json`。
- 使用内置 Douyin 核心库完成参数更新、重定向解析、详情抓取、主页抓取、合集抓取、关键词搜索。
- 支持普通视频下载。
- 支持图集与实况照片拆分下载。
- 图集图片优先尝试无水印地址。
- MP4 下载支持重试、临时文件写入和断点续传。
- 合集作品会自动按合集名创建子目录。

### Bilibili

- 支持 `BV`、视频 URL、UP 主空间 URL、纯数字 UID、搜索关键词。
- 首次使用可扫码登录，Cookie 保存到 `bili_auth.json`。
- 浏览器负责扫描页面与提取 BV，接口线程池负责详情解析。
- 支持单视频、多 P、合集二次选择。
- 解析 DASH 音视频流后使用 `ffmpeg` 合并输出。
- 下载任务会自动保留 `bvid / cid / referer / trace_id` 等关键元信息，便于排障。

### 快手

- 支持主页链接或关键词搜索作者。
- 首次使用可登录并保存 `ks_auth.json`。
- 通过 Playwright 打开页面、滚动加载列表并截获媒体请求。
- 扫描完成后弹出选择对话框，再按选中目标实时捕获媒体地址。
- 成功捕获后进入统一下载队列。
- 下载时根据任务元数据自动选择普通 HTTP 或 `m3u8` 方案。

### MissAV

- 支持番号、女优名、单体页 URL、列表页 URL、分类页 URL。
- 支持“仅单体”“中文字幕优先”“无码流出优先”等筛选思路。
- 支持代理配置，默认兼容 `Clash (7890)`、`v2rayN (10809)` 或手动输入。
- 列表模式下会进行两轮扫描，第二轮用于校验中文字幕资源。
- 最终通过页面请求嗅探 `playlist.m3u8`。
- 使用 `N_m3u8DL-RE.exe` 下载 HLS 流并封装为 `mp4`。

### 通用桌面功能

- 深色 / 浅色主题切换。
- 顶部平台配置组件动态切换。
- 下载队列表格展示状态与进度。
- 默认最多 `3` 个任务并发下载，可通过配置调整。
- 启动后自动扫描下载目录中的本地视频和图片。
- 本地文件支持重命名、删除。
- 内置播放器支持视频播放与图片预览。
- 支持双击进入沉浸式全屏播放。
- 自动保存配置到 `config.json`。
- 自动保存窗口几何信息、分栏状态、主题、最近平台和保存目录。

## 界面与使用流程

### 基本使用步骤

1. 启动程序，选择平台。
2. 输入关键词、作品链接、主页链接、合集链接或平台支持的标识符。
3. 根据平台显示的配置项补充参数。
4. 点击 `启动任务`。
5. 等待 Spider 扫描页面或接口。
6. 在选择对话框中勾选要下载的内容。
7. 任务进入下载队列，右侧日志面板显示执行过程。
8. 下载完成后，可直接在程序内播放、预览、重命名或删除本地文件。

### 顶部调试入口

主界面顶部提供 3 个调试按钮：

- `最新日志`
  - 直接打开 `latest_debug.log`
- `错误摘要`
  - 直接打开 `latest_error_summary.md`
- `复制Trace`
  - 先选中下载队列中的任务，再复制对应 `trace_id`

### 典型运行链路

```text
UI 输入
  -> ApplicationController
  -> 平台 Spider
  -> parser 解析
  -> task_builder 装配下载任务
  -> DownloadManager 入队与调度
  -> 平台 Downloader / 外部工具
  -> 本地文件落盘
  -> UI 状态更新 / 本地媒体预览
```

## 运行环境

建议环境：

- `Windows 10 / 11`
- `Python 3.10+`
- 已安装 `Playwright Chromium`

主要 Python 依赖见 `requirements.txt`，核心包括：

- `PyQt6`
- `requests`
- `httpx`
- `playwright`
- `rich`
- `emoji`
- `gmssl`

外部工具：

- `ffmpeg.exe`
  - 用于 Bilibili 音视频流合并
  - 若系统环境变量里已有 `ffmpeg`，代码也会尝试直接调用系统命令
- `N_m3u8DL-RE.exe`
  - 用于 MissAV 的 HLS 下载
  - 抖音或快手若落到 `m3u8` 策略时也会复用该工具链

## 安装与启动

### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd <your-project-dir>
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 准备外部工具

若仓库中未直接包含可执行文件，请把以下文件放到项目根目录：

- `ffmpeg.exe`
- `N_m3u8DL-RE.exe`

### 4. 启动程序

```bash
python main.py
```

## 配置文件说明

程序启动后会自动生成 `config.json`。当前配置模型由 `app/config/settings.py` 统一管理，主要分为以下 section：

- `common`
  - 保存目录、最近平台、主题
- `missav`
  - 代理应用、代理地址、优先级、是否仅单体
- `bilibili`
  - 登录文件、UA、最大页数、API worker 数
- `douyin`
  - UA、搜索最大页数
- `kuaishou`
  - UA
- `auth`
  - 各平台认证文件路径
- `download`
  - 并发数、启动本地扫描上限、重试次数、超时、分块大小
- `ui`
  - 窗口几何信息、分栏状态、全屏状态

### 当前默认配置示例

```json
{
  "common": {
    "save_directory": "downloads",
    "last_source": "kuaishou",
    "theme": "dark",
    "dark_theme": true
  },
  "missav": {
    "proxy_app": "Clash (7890)",
    "proxy_url": "http://127.0.0.1:7890",
    "priority": "中文字幕优先",
    "individual_only": false
  },
  "bilibili": {
    "auth_file": "bili_auth.json",
    "user_agent": "Mozilla/5.0 ... Chrome/139.0.0.0 Safari/537.36",
    "max_pages": 1,
    "api_workers": 8
  },
  "douyin": {
    "user_agent": "Mozilla/5.0 ... Chrome/139.0.0.0 Safari/537.36",
    "search_max_pages": 1
  },
  "kuaishou": {
    "user_agent": "Mozilla/5.0 ... Chrome/139.0.0.0 Safari/537.36"
  },
  "auth": {
    "bilibili_cookie_file": "bili_auth.json",
    "kuaishou_cookie_file": "ks_auth.json",
    "douyin_cookie_file": "dy_auth.json"
  },
  "download": {
    "max_concurrent": 3,
    "local_scan_limit": 1000,
    "max_retries": 3,
    "request_timeout": 60,
    "chunk_size": 65536
  }
}
```

说明：

- 实际首次生成的 `save_directory` 会基于代码中的默认下载目录。
- 配置加载时会做类型归一化和范围约束。
- 读取失败或结构损坏时，会自动备份原配置并回退默认值。

## 日志与调试

### 调试文件

程序运行后会在根目录附近生成或更新以下文件：

- `config.json`
- `dy_auth.json`
- `bili_auth.json`
- `ks_auth.json`
- `logs/`
  - 运行时日志目录
- `Logs/README.md`
  - 当前日志体系的详细使用说明

日志目录中的关键文件：

- `latest_debug.log`
  - 最新一次运行的完整调试日志
- `latest_error_summary.md`
  - 最近一次错误的摘要诊断报告
- `debug_YYYYMMDD_HHMMSS.log`
  - 历史完整日志

### 这套日志能回答什么问题

- 当前问题发生在 `爬虫 / 入队 / 下载 / 合并 / UI` 的哪一层
- 某个任务从发现到下载是否属于同一条链路
- `ffmpeg` 与 `N_m3u8DL-RE` 实际拿到了哪些参数
- 某次失败更像是登录态、接口取流、调度还是外部工具问题

### 建议排查顺序

1. 先看 `latest_error_summary.md`
2. 记下里面的 `trace_id`
3. 去 `latest_debug.log` 里全文搜索这个 `trace_id`
4. 按时间顺序查看 `Spider -> Queue -> Downloader -> External Tool` 的链路

### 日志特点

- 会记录 `trace_id`
- 只保留有价值的响应摘要，不会默认把整包原始 JSON 全量落盘
- 会记录外部工具命令参数
- 已加入敏感信息脱敏，避免 `cookie / token / authorization / session` 明文写入

更详细的排障说明见 [Logs/README.md](Logs/README.md)。

## 项目结构

```text
.
├── .github/
│   └── workflows/
│       └── python-tests.yml         # GitHub Actions: compileall + unittest
├── Logs/
│   └── README.md                    # 日志体系说明
├── docs/
│   ├── api.md                       # 内部接口说明
│   ├── architecture.md              # 架构说明
│   └── development.md               # 开发指南
├── tests/                           # 单元测试
├── app/
│   ├── config/                      # 统一配置模型与默认值
│   ├── controllers/                 # 控制器层
│   ├── core/
│   │   ├── downloaders/             # 各平台下载器与 external 封装
│   │   ├── lib/
│   │   │   └── douyin/              # 抖音底层接口、签名、提取逻辑
│   │   ├── plugins/                 # 插件定义、设置构建、注册表实现
│   │   ├── download_manager.py      # 队列、并发控制、worker 调度
│   │   └── plugin_registry.py       # 插件统一导出入口
│   ├── exceptions/                  # 自定义异常
│   ├── models/                      # 数据模型
│   ├── services/                    # 认证、文件、调试辅助服务
│   ├── spiders/
│   │   ├── base.py                  # Spider 线程基类
│   │   ├── base_task_builder.py     # 统一下载 meta 装配
│   │   ├── bilibili/
│   │   ├── douyin/
│   │   ├── kuaishou/
│   │   └── missav/
│   ├── ui/
│   │   ├── components/              # 主界面复用组件
│   │   ├── dialogs/                 # 对话框
│   │   ├── styles/                  # 深浅色主题样式
│   │   └── widgets/                 # 自定义控件
│   ├── utils/                       # 文件名清理、格式化等工具
│   └── debug_logger.py              # 调试日志与错误摘要生成
├── ffmpeg.exe
├── N_m3u8DL-RE.exe
├── favicon.ico
├── main.py
├── requirements.txt
└── README.md
```

## 核心架构说明

### 1. 配置层

- 统一入口：`app.config.cfg`
- 真实实现：`ConfigManager`
- 负责配置读取、默认值补齐、类型归一化、范围校验、UI 状态保存

### 2. 插件层

- 统一入口：`app.core.plugin_registry`
- 实际实现：`app/core/plugins`
- 负责平台定义、平台配置组件构建与插件注册

### 3. Spider 层

每个平台尽量统一拆为三层：

- `spider`
  - 页面访问、浏览器控制、流程编排、信号发射
- `parser`
  - 页面数据或接口结果解析
- `task_builder`
  - 把解析结果转换成统一下载任务或 `VideoItem`

### 4. 下载层

- `DownloadManager`
  - 管理任务队列、并发调度、Worker 生命周期
- `BaseDownloader`
  - 收口公共 HTTP 下载流程、重试、临时文件与停止检查
- 平台下载器
  - `DouyinDownloader`
  - `BilibiliDownloader`
  - `KuaishouDownloader`
  - `MissAVDownloader`
- `external.py`
  - 统一封装 `ffmpeg` 与 `N_m3u8DL-RE` 的工具发现、命令构建和调用

### 5. UI 层

- `main_window.py`
  - 主窗口入口
- `components/`
  - 顶栏、下载队列、日志面板、媒体预览面板
- `dialogs/`
  - 任务选择对话框
- `styles/`
  - 深浅色主题样式
- `widgets/`
  - 自定义视频控件

### 6. 服务层

- `AuthService`
  - 认证文件读写、Cookie 提取、Playwright Cookie 恢复、登录态持久化
- `MediaLibraryService`
  - 本地媒体扫描、删除、重命名
- `DebugArtifactsService`
  - 打开最新日志、打开错误摘要、复制 `trace_id`

## 下载实现说明

### 下载调度

- `DownloadManager` 负责统一队列分发。
- `DownloadWorker` 负责单个任务生命周期。
- 默认并发数为 `3`，来自 `download.max_concurrent`。

### 按来源选择下载器

- `DouyinDownloader`
  - 图集 / 实况按文件逐个下载
  - 视频优先走普通 HTTP 下载
  - 支持断点续传
- `BilibiliDownloader`
  - 视频流与音频流分开下载
  - 使用 `ffmpeg` 合并
- `KuaishouDownloader`
  - 普通媒体资源走 HTTP
  - `m3u8` 资源可转入 HLS 策略
- `MissAVDownloader`
  - 直接委托 `N_m3u8DL-RE.exe`

### 文件名与目录策略

- 文件名会统一清理非法字符。
- 抖音合集会按合集名创建目录。
- 本地文件扫描按修改时间倒序展示。
- 为防止界面卡顿，启动时最多加载最近 `1000` 个本地媒体文件，来自 `download.local_scan_limit`。

## 测试与质量保障

### 当前已有保障

- `tests/` 已覆盖配置、下载器、控制器、主窗口、认证服务、日志、文件服务、插件注册、Spider helper 等方向。
- 根目录提供 GitHub Actions 工作流 [python-tests.yml](.github/workflows/python-tests.yml)。
- CI 当前会自动执行：
  - `python -m compileall app tests main.py`
  - `python -m unittest discover -s tests`

### 本地验证命令

```bash
python -m compileall app tests main.py
python -m unittest discover -s tests
```

## 二次开发指南

### 新平台接入最少需要哪些模块

建议至少新增：

- `app/spiders/<platform>/spider.py`
- `app/spiders/<platform>/parser.py`
- `app/spiders/<platform>/task_builder.py`
- `app/core/downloaders/<platform>.py`

如果需要平台专属设置 UI，还建议同步补：

- `app/core/plugins/definitions.py`
- `app/core/plugins/settings_builders.py`

### 推荐新增逻辑的落点

- 配置相关
  - 放 `app/config`
- 下载器相关
  - 放 `app/core/downloaders`
- 插件注册与平台设置构建
  - 入口走 `app/core/plugin_registry.py`
  - 实现放 `app/core/plugins`
- 与 UI 无关的业务逻辑
  - 放 `app/services`
- 数据模型
  - 放 `app/models`
- 错误类型
  - 放 `app/exceptions`

### 兼容层策略

- 旧模块只在仍有真实引用时保留兼容入口。
- 一旦引用全部切换完成，旧 shim 应直接删除。
- 新功能不再继续向历史大文件追加。

## 当前边界与限制

以下内容是根据当前代码状态整理出的真实边界，而不是规划目标：

- 仓库明显偏向 Windows 使用场景，其他系统下需要自行处理 `.exe` 依赖与路径兼容问题。
- `TikTok` 相关底层接口和加密模块仍保留在 `app/core/lib/douyin`，但桌面程序当前没有对应插件和 Spider 接入。
- 抖音底层库中包含 `live`、`comment`、`collects`、`hot`、`hashtag` 等接口模块，但桌面 UI 当前没有把这些能力接进可操作流程。
- 抖音输入纯数字 UID 时，当前逻辑会明确提示暂不支持直接搜索。
- 当前测试体系仍以单元测试和导入 / 编译验证为主，浏览器真实联动覆盖还不算高。

## 相关文档

- [架构说明](docs/architecture.md)
- [开发指南](docs/development.md)
- [内部接口说明](docs/api.md)
- [日志使用说明](Logs/README.md)

## 免责声明

本项目仅供学习桌面自动化、网络请求处理、媒体下载流程和 PyQt 界面组织方式使用。

- 请勿将其用于侵犯版权、隐私或违反目标平台服务条款的行为。
- 请在你所在地区法律允许的前提下使用。
- 使用者应自行承担由内容下载、转载、分发带来的全部风险与责任。
