  # 🚀 Universal Crawler Pro

  ![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
  ![Framework](https://img.shields.io/badge/Framework-PyQt6-green?logo=qt&logoColor=white)
  ![Platform](https://img.shields.io/badge/Platform-Windows_10%20%7C%2011-lightgray?logo=windows)
  ![Playwright](https://img.shields.io/badge/Playwright-Chromium-orange?logo=playwright)
  ![License](https://img.shields.io/badge/License-Disclaimer-red)

  **Universal Crawler Pro** 是一款专为 Windows 桌面环境打造的**多平台高性能媒体采集与下载工具**。本项目基于 `Python` 与 `PyQt6` 构建，彻底告别繁琐的命令行操作，提供从 **「数据嗅探/解析」** -> **「精准勾选」** -> **「高速下载」** -> **「本地资产管理与播放」** 的一站式沉浸体验。

  > 💡 **设计初衷**：打造一个“开箱即用”且“对开发者友好”的媒体采集工作站。无论是普通用户的高频下载需求，还是开发者二次开发的底层框架，都能在这里找到完美的契合点。

---

  ## 📑 目录导航

  - [✨ 核心特性](#-核心特性)
  - [🌐 支持平台与能力矩阵](#-支持平台与能力矩阵)
  - [📦 安装与快速启动](#-安装与快速启动)
  - [⚙️ 配置体系说明](#-配置体系说明)
  - [🏗️ 核心架构与工程化](#-核心架构与工程化)
  - [🛠️ 全链路日志与调试](#-全链路日志与调试)
  - [👨‍💻 二次开发与贡献指南](#-二次开发与贡献指南)
  - [⚠️ 边界、限制与免责声明](#-边界限制与免责声明)

---

  ## ✨ 核心特性

  ### 🎨 面向桌面的极致体验 (GUI-First)
  - **非 Web 架构**：纯本地原生桌面程序，响应迅速，拒绝繁琐的 Web 服务部署。
  - **现代化 UI**：基于 PyQt6 深度定制，内置**深色/浅色**主题无缝切换，提供下载队列、实时进度条及任务状态概览。
  - **内建媒体管理**：下载完成后，支持在程序内直接**管理、重命名、删除**，更内置播放器支持双击沉浸式全屏播放及图集预览。

  ### ⚡ 强大的统一下载引擎
  - **智能策略分发**：下载统一接入 `DownloadManager`，根据任务元数据（视频、图集、音频分流、m3u8）自动选择最合适的下载器或外部封装工具。
  - **并发与断点续传**：支持多任务高并发（可配置），MP4 文件下载支持断点续传与防崩溃的临时文件写入机制。
  - **外部工具集成**：无缝驱动 `ffmpeg`（音视频混流）与 `N_m3u8DL-RE`（HLS 流媒体拉取），自动构建注入参数。

  ### 🔧 工业级的调试与排障能力
  - **Trace ID 全链路追踪**：每个任务从输入生成专属 `trace_id`，贯穿爬虫、解析、入队到下载全流程。
  - **智能错误报告**：遇到异常自动生成 `latest_error_summary.md`（错误摘要诊断报告），极大幅度降低排障门槛。
  - **一键调试入口**：UI 顶部集成 `最新日志`、`错误摘要`、`复制Trace` 快捷操作，让 Bug 无处遁形。

---

  ## 🌐 支持平台与能力矩阵

  系统采用高度模块化的 Spider 架构，目前已原生接入并支持以下平台：

  | 平台         |  状态  | 身份认证       | 核心输入支持                                  | 嗅探 / 下载策略                                              |
  | :----------- | :----: | :------------- | :-------------------------------------------- | :----------------------------------------------------------- |
  | **抖音**     | 🟢 稳定 | 扫码自动登录   | 作品 / 主页 / 合集 / 关键词 / 短链 / modal_id | 内置签名与参数生成 + 接口解析。支持断点续传、无水印图集拆分下载、实况照片。 |
  | **Bilibili** | 🟢 稳定 | 扫码自动登录   | BV / URL / 空间 URL / UID / 搜索              | 浏览器无头扫描 + API 详情解析。DASH 音视频分流拉取 + `ffmpeg` 本地无损合并。 |
  | **快手**     | 🟡 测试 | 浏览器辅助登录 | 主页链接 / 关键词搜索                         | Playwright 动态滚动加载 + 媒体请求拦截。根据资源类型自动切换 HTTP / HLS 策略。 |
  | **MissAV**   | 🟢 稳定 | 无需站内登录   | 番号 / 演员 / 分类 / 列表 / 单体 URL          | 双轮扫描机制 + 代理穿透。支持“中文字幕/无码优先”策略，捕获 `playlist.m3u8` 后交由 `N_m3u8DL-RE` 极速下载。 |
  | **TikTok**   | ⚪ 潜藏 | 未接入 UI      | -                                             | 仓库保留完整底层协议与加密模块，供开发者自行调用，当前未在 GUI 侧透出。 |

---

  ## 📦 安装与快速启动

  ### 1. 环境依赖要求
  - **操作系统**：Windows 10 / 11（推荐）
  - **环境运行库**：Python 3.10 及以上版本

  ### 2. 克隆与安装依赖

  ```bash
  # 获取源码
  git clone https://github.com/your-repo/universal-crawler-pro.git
  cd universal-crawler-pro
  
  # 安装 Python 依赖
  pip install -r requirements.txt
  
  # 安装 Playwright 浏览器内核 (Chromium)
  playwright install chromium
  ```

  ### 3. 配置外部核心组件
  为了保证完整功能（尤其是 B站合并与 MissAV 下载），请将以下两个可执行文件放置在项目**根目录**：
  - 🎬 `ffmpeg.exe` (如系统环境变量已配置，程序也会自动识别)
  - 📥 `N_m3u8DL-RE.exe`

  **最终根目录结构示例：**
  ```text
  universal-crawler-pro/
   ├── app/                  # 核心源码
   ├── ffmpeg.exe            # <--- 必须存在
   ├── N_m3u8DL-RE.exe       # <--- 必须存在
   ├── main.py
   └── requirements.txt
  ```

  ### 4. 启动应用

  ```bash
  python main.py
  ```
  > 首次启动会自动生成 `config.json` 与默认下载目录 `downloads/`。

---

  ## ⚙️ 配置体系说明

  应用的所有配置收口于 `app/config/settings.py`，具有**默认值补齐、字段归一化与基础边界校验**能力。修改后或在 UI 中调整状态后，会自动序列化到根目录的 `config.json` 中。

  <details>
  <summary><b>点击查看 config.json 核心字段说明</b></summary>

  ```json
  {
    "common": {
      "save_directory": "downloads",   // 全局保存路径
      "last_source": "kuaishou",       // 记忆上次使用的平台
      "theme": "dark"                  // 主题模式 (dark/light)
    },
    "missav": {
      "proxy_url": "http://127.0.0.1:7890", // 代理配置 (支持 Clash/v2rayN 等)
      "priority": "中文字幕优先",             // 筛选策略
      "individual_only": false              // 是否仅获取单体视频
    },
    "bilibili": {
      "api_workers": 8,                // API 解析并发数
      "max_pages": 1                   // 搜索/主页抓取最大页数
    },
    "download": {
      "max_concurrent": 3,             // 核心下载并发线程数
      "local_scan_limit": 1000,        // 启动时本地文件扫描上限 (防卡顿)
      "max_retries": 3,                // 失败重试次数
      "chunk_size": 65536              // 流式写入分块大小 (64KB)
    }
  }
  ```
  </details>

---

  ## 🏗️ 核心架构与工程化

  本项目严格遵循高内聚、低耦合的工程化设计原则：

  ```mermaid
  graph TD
      UI["UI 层 (PyQt6 Main Window)"] --> Ctrl["Controllers 控制器"]
      Ctrl --> Spider["Spiders 爬虫层"]
      Spider --> Parser[Parser 解析层]
      Parser --> Builder[Task Builder 任务装配]
      Builder --> DLMgr[Download Manager 队列调度]
      DLMgr --> DL[Downloaders 具体下载器]
      DL --> IO[本地 I/O 落盘]
  ```

  - **🧩 插件化注入** (`app/core/plugins`)：新增平台只需注册插件，即可自动生成 UI 面板。
  - **🕷️ 爬虫三段式** (`app/spiders`)：`Spider` 负责发包与编排，`Parser` 负责清洗 JSON/HTML，`TaskBuilder` 负责将其映射为标准的 `VideoItem` 实体。
  - **🚀 并发调度** (`app/core/download_manager.py`)：管理 Worker 生命周期，确保多平台任务混合投递时依然井然有序。

---

  ## 🛠️ 全链路日志与调试

  为了解决桌面爬虫工具常见的“黑盒问题”，本项目内置了一套完备的**日志服务体系**。

  - **`Logs/README.md`**：专属的日志系统说明文档。
  - **`latest_debug.log`**：实时记录当前最新运行的完整脱敏日志（含网络请求、外部工具调用参数）。
  - **`latest_error_summary.md`**：当出现解析失败或下载异常时，自动生成的 Markdown 格式诊断书。
  - **安全脱敏**：底层日志器会自动对 `cookie`, `token`, `authorization`, `session` 等敏感信息进行掩码处理，保证日志分享安全。

  **排障三步曲**：
  1. 点击顶部「错误摘要」，查看初步报错。
  2. 提取摘要中的 `trace_id`。
  3. 点击「最新日志」，全文搜索该 `trace_id`，完整还原从 `Spider -> Queue -> Downloader -> External Tool` 的执行路径。

---

  ## 👨‍💻 二次开发与贡献指南

  我们非常欢迎开发者对本项目进行扩展！仓库内已配置健全的 `unittest` 测试体系与 GitHub Actions 持续集成。

  ### 接入新平台的最短路径
  1. **Spider 层**：在 `app/spiders/<new_platform>/` 下实现 `spider.py` (请求), `parser.py` (解析) 和 `task_builder.py` (装配)。
  2. **下载器层**：在 `app/core/downloaders/` 新增专属下载策略类。
  3. **插件注册**：在 `app/core/plugins/` 下配置平台 Definition 与 UI 组件构建器，通过 `plugin_registry.py` 暴露。

  ### 本地测试与质量保证
  提交代码前，请确保通过所有检查：
  ```bash
  # 验证代码编译是否正常
  python -m compileall app tests main.py
  
  # 运行所有单元测试
  python -m unittest discover -s tests
  ```

---

  ## ⚠️ 边界、限制与免责声明

  ### 🛠️ 当前边界与限制
  1. **OS 倾向性**：当前逻辑主要针对 Windows 文件系统与进程管理打磨，macOS/Linux 理论上可通过修改依赖路径运行，但未经严格测试。
  2. **UID 搜索**：当前针对部分平台（如抖音纯数字 UID）不支持直接检索，需转换为分享链接。
  3. **TikTok 模块**：仅存在于底层 API 中，当前未与桌面 GUI 桥接。

  ### ⚖️ 免责声明
  > 1. **仅供学习交流**：本项目属于个人业余项目，初衷为探索桌面端 GUI 编程（PyQt）、并发网络请求与本地文件流处理的技术实践。
  > 2. **责任自负**：使用者应当遵守相关法律法规及目标平台的服务条款（ToS）。**请勿将本工具用于任何商业盈利、侵犯版权、隐私窃取及其他非法用途。**
  > 3. **无担保**：作者不对因使用本软件产生的任何直接或间接后果承担法律责任。下载的数据及产生的影响由使用者完全负责。

---
  *If you find this project helpful, please consider giving it a ⭐️!*
