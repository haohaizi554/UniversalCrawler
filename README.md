# Universal Crawler Pro 🚀

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://riverbankcomputing.com/software/pyqt/)
[![Playwright](https://img.shields.io/badge/Browser-Playwright-orange.svg)](https://playwright.dev/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

**Universal Crawler Pro** 是一个功能强大的桌面端视频爬虫与下载管理工具。它基于 **Python** + **PyQt6** 构建现代化暗黑风格界面，利用 **Playwright** 实现智能网页交互与嗅探，支持多平台视频的高速下载与管理。

---

## ✨ 核心功能 (Features)

该项目采用插件化架构，支持以下平台的视频抓取：

### 📺 Bilibili (B站)
- **多模式支持**：支持 BV 号、UP 主主页（UID）、搜索关键词、合集/列表 URL。
- **高清画质**：自动解析 Dash 流，支持 8K/4K/1080P60 高帧率下载。
- **音画合并**：自动调用 FFmpeg 将音频与视频流无损合并。
- **登录支持**：内置扫码登录功能，支持获取会员高画质权限。
- **批量下载**：支持多P视频、剧集、合集的批量选择与下载。

### 🎥 Kuaishou (快手)
- **智能嗅探**：模拟真人操作滚动“瀑布流”页面，自动拦截网络数据包。
- **去水印**：自动提取无水印高清视频源。
- **批量采集**：支持按作者主页或搜索关键词批量扫描。

### 🔞 MissAV
- **智能筛选**：支持“中文字幕优先”、“无码优先”等智能排序算法。
- **HLS 下载**：集成 `N_m3u8DL-RE`，支持多线程并发下载 M3U8 流媒体。
- **代理支持**：内置代理设置（Clash/v2ray），解决网络访问问题。

### 🛠️ 通用功能
- **现代化 UI**：基于 PyQt6 的深色主题（Dark Mode），包含任务队列、进度条、内置播放器。
- **交互式选择**：爬虫扫描完成后弹出清单，用户可自由勾选需要下载的项目。
- **本地管理**：内置简易播放器，支持本地文件的重命名、播放和删除。
- **断点恢复**：自动保存应用配置（窗口位置、上次源、代理设置等）。

---

## ⚙️ 环境依赖 (Prerequisites)

在运行本项目之前，您需要准备以下环境和工具：

1.  **Python 3.8+**
2.  **外部工具 (必须放入项目根目录)**:
    *   [FFmpeg](https://ffmpeg.org/download.html): 用于 Bilibili 音视频合并 (`ffmpeg.exe`)。
    *   [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases): 用于 m3u8 视频下载 (`N_m3u8DL-RE.exe`)。

---

## 📥 安装与运行 (Installation)

### 1. 克隆项目
```bash
git clone https://github.com/yourusername/Universal-Crawler-Pro.git
cd Universal-Crawler-Pro
```

### 2. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 3. 安装浏览器内核
本项目依赖 Playwright 进行网页渲染：
```bash
playwright install chromium
```

### 4. 配置外部工具
**非常重要**：请确保下载 `ffmpeg.exe` 和 `N_m3u8DL-RE.exe` 并将它们直接放置在 `main.py` 同级目录下。

### 5. 启动程序
```bash
python main.py
```

---

## 📂 项目结构 (Structure)

```text
Universal-Crawler-Pro/
├── app/
│   ├── core/           # 核心逻辑 (下载器、插件注册)
│   ├── spiders/        # 爬虫逻辑 (B站、快手、MissAV)
│   ├── ui/             # 界面代码 (主窗口、弹窗、样式)
│   ├── models.py       # 数据模型
│   └── utils.py        # 配置管理工具
├── main.py             # 程序入口
├── config.json         # 配置文件 (自动生成)
├── requirements.txt    # 依赖列表
├── ffmpeg.exe          # [需自行下载]
└── N_m3u8DL-RE.exe     # [需自行下载]
```

---

## 🖥️ 使用指南 (Usage)

1.  **选择模式**：在顶部下拉框选择目标平台（Bilibili / 快手 / MissAV）。
2.  **配置参数**：
    *   **Bilibili**：设置爬取页数，首次使用若需会员画质会自动弹窗扫码登录。
    *   **MissAV**：可设置代理端口（默认 7890）及筛选偏好。
3.  **输入目标**：在搜索框输入 关键词、URL、BV号或番号。
4.  **启动任务**：点击“🚀 启动任务”。
5.  **选择视频**：等待扫描完成后，会弹出选择对话框，勾选你想要下载的视频。
6.  **下载管理**：视频将自动加入左侧下载队列，下载完成后可直接在右侧播放或双击全屏。

---

## ⚠️ 免责声明 (Disclaimer)

1.  本项目仅供 **Python 爬虫技术交流与学习** 使用，不得用于任何商业用途。
2.  使用者请遵守各目标网站的 `robots.txt` 协议及服务条款。
3.  对于使用本项目下载的任何内容，使用者需自行承担版权风险和法律责任。
4.  本项目集成的 MissAV 模块仅作为技术研究（如 M3U8 解析、HLS 下载技术），请勿在禁止该类内容的地区使用。

---