# 打包与发布指南

## 目标

本文档面向当前项目维护者，说明如何把 UniversalCrawlerProplus 打成可分发的 Windows 产物，并保证版本、入口、用户数据路径与当前工程实现一致。

## 当前发布形态

项目当前维护两种标准分发物：

- 便携版目录
  - 适合本地验证、灰度分发、无需安装的交付场景
- Inno Setup 安装包
  - 适合正式发布、桌面快捷方式、开始菜单、标准卸载

两种发布物都基于同一套源码入口：

- `main.py` / `ucrawl-auto`：统一自适应入口（`entry.dispatcher`）
- `entry.gui_entry`：桌面 GUI
- `entry.web_entry`：Web UI

打包后的 Windows EXE **不走 dispatcher**，而是双 EXE 直启：

- `UniversalCrawlerPro.exe` → `entry.gui_entry`
- `CrawlerWebPortal.exe` → `entry.web_entry`

## 关键原则

- 版本号只认 `pyproject.toml`
- 安装器版本不得手工硬编码
- 打包态用户数据不得回写进仓库
- 开发态与打包态路径必须继续遵守 `runtime_paths.py` 规范
- 外部工具必须显式随包交付，不依赖用户手工补环境

## 联动更新矩阵

打包链路一旦调整，下面这些文件必须一起看，避免“构建脚本变了，但 README / 安装器 / 路径规则没同步”：

- 版本与展示名：
  - `pyproject.toml`
  - `packaging/project_meta.py`
- 便携版构建：
  - `packaging/build_portable.py`
  - `packaging/portable.spec`
  - `packaging/runtime_hook.py`
- 安装包构建：
  - `packaging/build_installer.py`
  - `packaging/installer.iss`
- 文档：
  - `README.md`
  - `README_EN.md`
  - `packaging/README.md`
  - `testing.md`
  - `../CHANGELOG.md`

当前项目要求以 `project_meta.py` 作为打包元数据收口层，以 `runtime_paths.py` 作为开发态 / 打包态用户数据路径规则的唯一口径。

## 打包前准备

### 1. 基础依赖

```bash
pip install -e .
pip install -r packaging/requirements-build.txt
playwright install chromium
```

### 2. 根目录外部工具

以下文件必须位于项目根目录：

- `ffmpeg.exe`
- `ffprobe.exe`（标准 FFmpeg 发行包自带，供 `media_metadata_service` 使用）
- `N_m3u8DL-RE.exe`

安装包构建还需要 `packaging/wizard_image.bmp` 与 `packaging/wizard_small_image.bmp`。

### 3. 发布前回归

至少执行：

```bash
python -m pytest tests/test_packaging.py
python -m pytest tests/test_downloaders.py
python tests/test_launcher.py --list
```

如果近期改动过 Web、下载器、控制器或路径策略，建议补跑对应专题测试。

## 构建流程

### 便携版

```bash
python packaging/build_portable.py
```

产物目录：

```text
dist/UniversalCrawlerPro/
```

关键产物：

- `UniversalCrawlerPro.exe`
- `CrawlerWebPortal.exe`
- `_internal/`
- `BUILD_INFO.txt`
- `ffmpeg.exe`
- `ffprobe.exe`
- `N_m3u8DL-RE.exe`
- `ms-playwright/`

便携版 EXE 为冻结运行时，用户数据应写入 `%LOCALAPPDATA%\UniversalCrawlerPro`（见 `runtime_paths.py`）。仅源码开发态默认使用项目根目录 `user_data/`。

### 安装包

```bash
python packaging/build_installer.py
```

输出目录：

```text
dist/installer/
```

命名规则：

- 安装包文件名自动带当前项目版本
- 版本号来源于 `pyproject.toml`
- 安装后运行时用户数据应写入 `%LOCALAPPDATA%` / `AppData`

### 一键发布

```bash
python packaging/build_release.py
```

## 版本同步规则

当前版本同步关系如下：

- Python 包版本：`pyproject.toml`
- 打包元数据：`packaging/project_meta.py`
- 便携版说明：`packaging/build_portable.py` 写入 `BUILD_INFO.txt`
- 安装器版本：`packaging/build_installer.py` 注入 `installer.iss`
- 安装包输出名：同样由 `build_installer.py` 注入

如果你要发布新版本，优先修改：

```toml
[project]
version = "x.y.z"
```

不要再手改：

- `installer.iss` 的版本号
- 安装包文件名
- 便携版构建说明里的版本文本

## 任务栏与快捷方式标识

为了让主程序与 Web 门户在 Windows 任务栏正确分组，当前约定如下：

- 主程序：`ucrawl.universalcrawlerpro.main`
- Web 门户：`ucrawl.universalcrawlerpro.web`

这些标识必须在以下位置保持一致：

- `packaging/runtime_hook.py`
- `packaging/installer.iss`
- GUI / Web 启动入口

## 用户数据约束

打包时必须排除：

- `config.json`
- `bili_auth.json`
- `ks_auth.json`
- `dy_auth.json`

原因：

- 这些都是运行期状态，不应进入发布物
- 否则会污染用户环境，且容易把开发机状态带入正式包

## 安装源完整性校验

`packaging/build_installer.py` 在调用 Inno Setup 前会检查便携版安装源，避免把不完整的 `dist/UniversalCrawlerPro/` 目录打成安装包。当前必须存在：

- `UniversalCrawlerPro.exe`
- `CrawlerWebPortal.exe`
- `BUILD_INFO.txt`
- `_internal/app/web/static/index.html`
- `_internal/app/web/static/app.css`
- `_internal/app/web/static/app.js`
- `_internal/UI/icon/nav_settings.png`
- `favicon.ico`
- `Web.ico`

如果这些文件缺失，应先重新运行 `python packaging/build_portable.py`，不要直接复用旧 dist 目录生成安装包。

## 发布后人工验收

建议至少人工验证以下项目：

1. 双击 `UniversalCrawlerPro.exe` 能启动 GUI
2. 双击 `CrawlerWebPortal.exe` 能启动 Web UI
3. Web UI 能正常打开浏览器
4. GUI / Web 都能创建下载目录
5. `ffmpeg.exe`、`ffprobe.exe` 与 `N_m3u8DL-RE.exe` 可被发现
6. Playwright Chromium 可用
7. 用户数据写入位置符合当前路径规范
8. 安装源完整性校验通过，Web 静态入口、CSS/JS、GUI/Web 图标和 UI 图标随包存在
9. 安装包开始菜单和桌面快捷方式可用
10. 卸载流程正常
11. 开发态落盘仍在项目根 `user_data/`，打包态落盘切到 `%LOCALAPPDATA%`

## 相关文件

- [packaging/README.md](../../packaging/README.md)
- [packaging/build_portable.py](../../packaging/build_portable.py)
- [packaging/build_installer.py](../../packaging/build_installer.py)
- [packaging/portable.spec](../../packaging/portable.spec)
- [packaging/installer.iss](../../packaging/installer.iss)
- [packaging/project_meta.py](../../packaging/project_meta.py)
- [app/utils/runtime_paths.py](../../app/utils/runtime_paths.py)
- [tests/test_packaging.py](../../tests/test_packaging.py)
- [docs/windows-file-association.md](windows-file-association.md)
