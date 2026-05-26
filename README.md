# Universal Crawler Pro 🚀

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

**Universal Crawler Pro** 是一个功能强大的桌面端视频爬虫与下载管理工具。基于 **Python** + **PyQt6** 构建现代化界面，采用插件化架构，支持多平台视频的高速下载与管理。

---

## ✨ 核心功能

### 🎵 抖音 (Douyin)

- **多格式输入**：支持用户主页链接、视频链接、合集链接、分享短链、用户昵称搜索
- **无水印下载**：自动提取 `~noop` 无水印图片源，1080P 高清视频
- **图集/实况照片**：图集自动批量保存无水印图片，实况照片自动提取视频流
- **合集下载**：支持合集链接解析，自动创建合集名称文件夹
- **断点续传**：下载中断后自动从断点继续，最多重试 5 次
- **扫码登录**：Playwright 环境隔离扫码，自动管理 Cookie

**支持的输入格式**：
| 输入格式 | 示例 | 说明 |
|---------|------|------|
| 用户主页链接 | `https://www.douyin.com/user/MS4wLjABAAAA...` | 批量获取用户作品 |
| 视频链接 | `https://www.douyin.com/video/7123456789` | 单个视频下载 |
| 合集链接 | `https://www.douyin.com/collection/7123456789` | 合集批量下载 |
| 分享链接 | `https://v.douyin.com/xxxxx/` | 自动解析重定向 |
| Modal ID 链接 | `https://www.douyin.com/...?modal_id=7123456789` | 搜索页/发现页链接 |

### 📺 Bilibili (B站)

- **多模式支持**：BV 号、UP 主主页（UID）、搜索关键词、合集/列表 URL
- **高清画质**：自动解析 Dash 流，支持 8K/4K/1080P60 高帧率下载
- **音画合并**：自动调用 FFmpeg 将音频与视频流无损合并
- **登录支持**：内置扫码登录功能，支持获取会员高画质权限
- **批量下载**：支持多P视频、剧集、合集的批量选择与下载

### 🎥 Kuaishou (快手)

- **智能嗅探**：模拟真人操作滚动"瀑布流"页面，自动拦截网络数据包
- **去水印**：自动提取无水印高清视频源
- **批量采集**：支持按作者主页或搜索关键词批量扫描

### 🔞 MissAV

- **智能筛选**：支持"中文字幕优先"、"无码优先"等智能排序算法
- **HLS 下载**：集成 `N_m3u8DL-RE`，支持多线程并发下载 M3U8 流媒体
- **代理支持**：内置代理设置（Clash/v2ray），解决网络访问问题

### 🛠️ 通用功能

- **现代化 UI**：基于 PyQt6 的深色/浅色主题切换，自适应布局
- **内置播放器**：支持本地视频/图片播放，视频保持原始比例居中显示
- **交互式选择**：爬虫扫描完成后弹出清单，用户可自由勾选需要下载的项目
- **实时进度**：下载进度条实时更新，支持断点续传
- **本地管理**：支持本地文件的重命名、播放和删除
- **配置持久化**：自动保存应用配置（窗口位置、主题、保存目录等）

---

## ⚙️ 环境依赖

1. **Python 3.8+**
2. **外部工具**（放入项目根目录）：
   - [FFmpeg](https://ffmpeg.org/download.html) (`ffmpeg.exe`)：B站音视频合并
   - [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases) (`N_m3u8DL-RE.exe`)：M3U8 流媒体下载

---

## 📥 安装与运行

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 安装浏览器内核（Playwright）
playwright install chromium

# 3. 将 ffmpeg.exe 和 N_m3u8DL-RE.exe 放到 main.py 同级目录

# 4. 启动程序
python main.py
```

---

## 📂 项目结构

```text
Universal-Crawler-Pro/
├── app/
│   ├── core/
│   │   ├── downloaders.py      # 下载器（Python/ffmpeg/N_m3u8DL-RE）
│   │   ├── download_manager.py # 下载管理器（任务队列）
│   │   ├── plugin_registry.py  # 插件注册中心
│   │   └── lib/douyin/         # 抖音核心库
│   │       ├── interface/      # API 接口层
│   │       │   ├── detail.py   # 作品详情
│   │       │   ├── user.py     # 用户主页
│   │       │   ├── mix.py      # 合集
│   │       │   ├── search.py   # 搜索
│   │       │   ├── live.py     # 直播
│   │       │   ├── collection.py # 收藏夹
│   │       │   ├── comment.py  # 评论
│   │       │   ├── hot.py      # 热榜
│   │       │   ├── hashtag.py  # 话题
│   │       │   └── account.py  # 账号信息
│   │       ├── extract/        # 数据提取层
│   │       └── link/           # 链接解析层
│   ├── spiders/
│   │   ├── douyin_spider.py    # 抖音爬虫
│   │   ├── bilibili_spider.py  # B站爬虫
│   │   ├── kuaishou_spider.py  # 快手爬虫
│   │   ├── missav_spider.py    # MissAV 爬虫
│   │   └── tiktok_spider.py    # TikTok 爬虫（待实现）
│   ├── ui/
│   │   ├── main_window.py      # 主窗口
│   │   ├── styles.py           # 主题样式
│   │   └── dialogs.py          # 弹窗组件
│   ├── models.py               # 数据模型
│   └── utils.py                # 配置管理
├── main.py                     # 程序入口
├── config.json                 # 配置文件（自动生成）
├── requirements.txt            # 依赖列表
├── ffmpeg.exe                  # [需自行下载]
└── N_m3u8DL-RE.exe             # [需自行下载]
```

---

## 🖥️ 使用指南

1. **选择平台**：顶部下拉框选择目标平台
2. **输入目标**：搜索框输入链接/昵称/关键词
3. **启动任务**：点击"🚀 启动任务"
4. **选择内容**：扫描完成后弹出选择框，勾选需要的项目
5. **自动下载**：视频自动加入队列下载，进度实时显示
6. **播放管理**：下载完成后可直接播放、全屏、删除

---

## 📋 下载策略

| 场景 | 下载方式 | 进度同步 | 说明 |
|------|---------|---------|------|
| 图集/实况 | Python 逐文件 | ✅ 实时 | 无水印图片/视频 |
| M3U8/HLS 流 | N_m3u8DL-RE | 外部窗口 | 16线程加速 |
| 所有 MP4 | Python 单线程 | ✅ 实时 | 断点续传，5次重试 |
| B站音视频 | Python + FFmpeg | ✅ 实时 | Dash 流无损合并 |

---

## 📌 待实现功能

- [ ] TikTok 爬虫（空文件已预留）
- [ ] 抖音直播下载
- [ ] 抖音收藏夹下载
- [ ] 抖音评论下载
- [ ] 抖音热榜/话题浏览
- [ ] 纯数字 UID 搜索（需浏览器渲染）
- [ ] 下载速度限制
- [ ] 代理设置（全局）

---

## ⚠️ 免责声明

1. 本项目仅供 **Python 爬虫技术交流与学习** 使用，不得用于任何商业用途。
2. 使用者请遵守各目标网站的 `robots.txt` 协议及服务条款。
3. 对于使用本项目下载的任何内容，使用者需自行承担版权风险和法律责任。
