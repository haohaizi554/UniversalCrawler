# 打包说明

## 目标

`packaging/` 目录用于产出当前项目的 Windows 分发物，覆盖两种交付形态：

- 便携版目录：解压即用，适合本地验证、灰度分发、免安装交付
- 安装包：基于 Inno Setup 的标准 Windows 安装器，适合正式发布

如果你更关心“发布流程”和“人工验收清单”，请优先阅读 [docs/guides/packaging.md](../docs/guides/packaging.md)。

当前打包链路已经适配本项目的真实入口结构：

- 源码自适应入口：`main.py` / `ucrawl-auto` → `entry/dispatcher.py`
- 打包后双 EXE 直启（绕过 dispatcher）：
  - `UniversalCrawlerPro.exe`：桌面 GUI（`entry.gui_entry`）
  - `CrawlerWebPortal.exe`：Web UI（`entry.web_entry`）
- 跨入口共享层：`shared/` 已显式纳入 `portable.spec` 的 `datas` 与 `hiddenimports`

## 目录职责

- `build_portable.py`
  - 构建便携版目录
  - 校验关键入口、图标、外部工具、Playwright Chromium
  - 生成 `BUILD_INFO.txt`
- `build_installer.py`
  - 调用 Inno Setup 生成安装包
  - 从 `pyproject.toml` 同步项目版本并注入 `installer.iss`
- `build_release.py`
  - 串联便携版和安装包构建
- `portable.spec`
  - PyInstaller 打包规格
- `installer.iss`
  - Inno Setup 安装脚本
- `runtime_hook.py`
  - 运行时环境修正，如 `PLAYWRIGHT_BROWSERS_PATH`、标准输出兜底、任务栏 AppUserModelID
- `project_meta.py`
  - 打包链路共享元数据，收口项目版本、发布名称、EXE 名称、图标名称、安装目录名和 Windows 标识

## 打包模块联动规则

`packaging/` 目录不是孤立存在的，下面这些文件与它构成一个同步单元：

- 版本源：
  - `pyproject.toml`
  - `packaging/project_meta.py`
- 路径规则：
  - `app/utils/runtime_paths.py`
- 维护文档：
  - `README.md`
  - `README_EN.md`
  - `docs/guides/packaging.md`
  - `docs/guides/testing.md`
  - `docs/changelog.md`
- 静态验证：
  - `tests/test_packaging.py`

只修改 `portable.spec` 或 `installer.iss` 而不更新这些联动文件，后续最容易出现版本漂移、文档漂移和用户数据路径漂移。

## 版本与元数据

打包链路的版本源统一来自根目录 `pyproject.toml`：

- Python 包版本：`[project].version`
- 安装器显示版本：由 `build_installer.py` 注入 `installer.iss`
- 安装包文件名：自动带当前版本号
- 便携版 `BUILD_INFO.txt`：自动写入当前版本号

这样可以避免：

- 安装器版本和源码版本漂移
- 手工改 `installer.iss` 忘记同步
- 发布包版本不可追溯

## 便携版构建

### 前置条件

- Windows 环境
- 已安装构建依赖
- 已执行 `playwright install chromium`
- 根目录可找到：
  - `ffmpeg.exe`
  - `ffprobe.exe`
  - `N_m3u8DL-RE.exe`

### 命令

```bash
python packaging/build_portable.py
```

### 典型产物

- `dist/UniversalCrawlerPro/UniversalCrawlerPro.exe`
- `dist/UniversalCrawlerPro/CrawlerWebPortal.exe`
- `dist/UniversalCrawlerPro/_internal/`
- `dist/UniversalCrawlerPro/BUILD_INFO.txt`
- `dist/UniversalCrawlerPro/README.md`
- `dist/UniversalCrawlerPro/README_EN.md`
- 随包携带的 `ffmpeg.exe`
- 随包携带的 `ffprobe.exe`
- 随包携带的 `N_m3u8DL-RE.exe`
- 随包携带的 Playwright Chromium 运行时

## 安装包构建

### 前置条件

- 已先完成便携版构建
- 已安装 Inno Setup 6
- 系统可访问 `ISCC.exe`
- `packaging/wizard_image.bmp` 与 `packaging/wizard_small_image.bmp` 已就绪

### 命令

```bash
python packaging/build_installer.py
```

### 说明

- 安装器脚本位于 `packaging/installer.iss`
- `build_installer.py` 会把项目版本、发布者、展示名、EXE 名称、图标名称、安装目录、输出文件名和 AppUserModelID 注入安装器
- 安装包文件名默认形如：

```text
dist/installer/UniversalCrawlerPro_Setup_<version>.exe
```

## 一键构建

```bash
python packaging/build_release.py
```

执行顺序：

1. 构建便携版
2. 校验输出完整性
3. 基于便携版生成安装包

## 当前产物约定

### 主程序

- `UniversalCrawlerPro.exe`
- 入口：桌面 GUI
- AppUserModelID：`ucrawl.universalcrawlerpro.main`

### Web 门户

- `CrawlerWebPortal.exe`
- 入口：Web UI
- AppUserModelID：`ucrawl.universalcrawlerpro.web`

### 用户数据

不允许把以下用户态文件打入产物：

- `config.json`
- `bili_auth.json`
- `ks_auth.json`
- `dy_auth.json`
- `xhs_auth.json`

运行时用户数据路径应走项目现有规则：

- 开发态：优先项目根目录 `user_data`
- 打包态：优先 `%LOCALAPPDATA%` / `AppData`

这里不要自行复制路径判断逻辑，统一以 `app/utils/runtime_paths.py` 为准。

## 安装源完整性

安装包构建前会校验 `dist/UniversalCrawlerPro/` 是否同时包含双入口 EXE、`BUILD_INFO.txt`、中英文说明文档、WebUI 静态入口和 GUI/WebUI 共享图标：

- `UniversalCrawlerPro.exe`
- `CrawlerWebPortal.exe`
- `README.md`
- `README_EN.md`
- `_internal/app/web/static/index.html`
- `_internal/app/web/static/app.css`
- `_internal/app/web/static/log_i18n.js`
- `_internal/app/web/static/frontend_runtime.js`
- `_internal/app/web/static/list_pages.js`
- `_internal/app/web/static/log_center.js`
- `_internal/app/web/static/settings_controller.js`
- `_internal/app/web/static/dialog_controller.js`
- `_internal/app/web/static/playback_controller.js`
- `_internal/app/web/static/app.js`
- `_internal/UI/icon/nav_settings.png`
- `favicon.ico`
- `Web.ico`

缺少任一项都应重新构建便携版，而不是直接运行 Inno Setup。

## 发布前检查

至少执行以下检查：

1. `python -m pytest tests/test_packaging.py`
2. `python tests/test_launcher.py --list`
3. 启动 `UniversalCrawlerPro.exe`
4. 启动 `CrawlerWebPortal.exe`
5. 验证 Chromium 运行时可用
6. 验证 `ffmpeg.exe`、`ffprobe.exe` 与 `N_m3u8DL-RE.exe` 能被找到
7. 验证下载目录、日志目录和配置目录可正常创建
8. 确认安装源包含 `README.md`、`README_EN.md`、`app/web/static/index.html`、`app/web/static/app.css`、七个职责模块 `log_i18n.js`、`frontend_runtime.js`、`list_pages.js`、`log_center.js`、`settings_controller.js`、`dialog_controller.js`、`playback_controller.js`，以及 `app.js`、`UI/icon/nav_settings.png`、`favicon.ico` 与 `Web.ico`
9. 确认产物中未混入用户态配置和 Cookie

`portable.spec` 必须继续递归收录整个 `app/web/static` 树；安装器构建脚本还会逐项校验上述七个职责模块，避免静态树存在于源码但安装源缺文件。项目运行、PyInstaller 打包和安装包运行均不依赖 Node，也不引入前端构建器。`node --check` 仅是发布机已安装 Node 时可选的开发/发布语法检查；没有 Node 不影响打包或运行，仍需执行 focused WebUI/packaging pytest 套件与完整 pytest 套件。

## 常见问题

### 未找到 `ms-playwright`

先执行：

```bash
playwright install chromium
```

### 未找到 `ISCC.exe`

请安装 Inno Setup 6，或确保 `ISCC.exe` 在系统 `PATH` 中可见。

### 安装器版本不对

不要手改 `installer.iss` 里的版本号。
当前正确做法是修改根目录 `pyproject.toml` 中的 `[project].version`，再重新运行构建脚本。
