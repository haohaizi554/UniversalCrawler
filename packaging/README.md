# 打包说明

## 目标

`packaging/` 目录用于产出当前项目的 Windows 分发物，覆盖两种交付形态：

- 便携版目录：解压即用，适合本地验证、灰度分发、免安装交付
- 安装包：基于 Inno Setup 的标准 Windows 安装器，适合正式发布

如果你更关心“发布流程”和“人工验收清单”，请优先阅读 [docs/guides/packaging.md](../docs/guides/packaging.md)。

当前打包链路已经适配本项目的真实入口结构：

- 源码自适应入口：`main.py` / `ucrawl-auto` → `entry/dispatcher.py`
- 打包后提供启动中心、独立命令行入口及两个既有直达入口：
  - `UCrawlLauncher.exe`：模式选择启动中心（`main.py` → `entry.dispatcher`），可进入代码量统计
  - `UCrawlCLI.exe`：带控制台的 CLI / 交互式引导入口（`main.py` → `entry.dispatcher`）
  - `UniversalCrawlerPro.exe`：桌面 GUI（`entry.gui_entry`）
  - `CrawlerWebPortal.exe`：Web UI（`entry.web_entry`）
- GUI/Web 两个直达入口继续绕过 dispatcher，保持原有双击语义
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
  - 默认串联便携版、安装包、签名清单和最终回验，原子准备三项 Release 资产
  - `--build-only` 仅供本地构建或生产信任 bootstrap
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
  - `tests/release/packaging/test_assets.py`

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

构建器通过 `playwright_bundle.py` 读取当前 Playwright 自带的 `browsers.json`，
只收集当前 Chromium revision。不要把 `%LOCALAPPDATA%\ms-playwright` 整目录加入
`portable.spec`；该缓存会保留历史 Chromium、Firefox 和 WebKit，导致构建结果依赖
发布机使用历史并持续膨胀。

### 典型产物

- `dist/UniversalCrawlerPro/UCrawlLauncher.exe`
- `dist/UniversalCrawlerPro/UCrawlCLI.exe`
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

## 一键发布

```bash
python packaging/build_release.py
```

执行顺序：

1. 校验工作树干净、版本一致且同名 tag 指向 `HEAD`
2. 从 `sourceCommit` 导出独立 `git archive` 快照；将 Git LFS 指针物化为真实对象，并按 LFS OID 和声明大小逐个校验
3. 要求随包的 `N_m3u8DL-RE.exe`、`ffmpeg.exe`、`ffprobe.exe` 已物化为有效 PE 文件，而不是 LFS 指针或异常小的占位文件
4. 校验 manifest 私钥位于仓库外；从同一快照运行构建、清单生成器与客户端验证器
5. 构建便携版与安装包，并校验快照源码树未被脚本修改、新增或删除
6. 开启 Windows 签名时，要求源码中已提交生产信任锚且 `UPDATE_REQUIRE_OS_SIGNATURE=True`；便携版只冻结一次，最终安装包签名人必须与冻结信任一致
7. 在临时目录生成并用快照中的客户端公钥重新验签 manifest，复核安装包 SHA-256、URL、平台和源提交
8. 原子生成 `dist/release-assets/v<version>/`，其中只能包含安装包、`latest.json`、`latest.json.sig`

`build_release.py`、`build_portable.py` 与 `build_installer.py` 共用同一个跨进程发布锁。顶层发布通过一次性父令牌授权子构建；直接运行任一叶子脚本也必须独立获取同一把锁，不能绕过并发发布门禁。构建脚本不会在发布过程中回写信任配置，需要更换签名证书时必须先审核并提交新的信任锚。

Windows 正式发布快照默认放在仓库同级的 `.ucrawl-release-tmp` 短目录中，并使用短工作区名称，避免 Playwright 深层资源在 Inno Setup 内部处理时触发传统 Win32 路径上限。发布机需要改用其他磁盘时可设置 `UCRAWL_RELEASE_TEMP_ROOT`；该值必须指向短、可写的本地目录，不应放在仓库内或网络共享中。

PyInstaller 的分析阶段会导入部分应用模块。正式发布会将 `UCRAWL_USER_DATA_ROOT` 强制隔离到快照的 `build/runtime-user-data`。三个 launcher 是受 Git 管理的 canonical 源文件，`portable.spec` 只能只读消费，不得在构建期删除、生成或改写。不要通过放宽源码指纹校验来容忍构建副作用；`sourceCommit` 快照除 `build/`、`dist/` 与字节码缓存外必须保持完全不变。

只需要便携版和安装器时使用：

```bash
python packaging/build_release.py --build-only
```

`--build-only` 产物不具备热更新发布资格。

## 当前产物约定

### 启动中心

- `UCrawlLauncher.exe`
- 入口：`main.py` / `entry.dispatcher`
- 安装器在开始菜单创建“Universal Crawler Pro 启动中心”快捷方式
- 无控制台双击时打开 Qt 模式选择器，可进入代码量统计；选择 CLI / 交互式引导时委托同目录的 `UCrawlCLI.exe` 打开独立终端，不替换下列 GUI/Web 直达入口
- CLI 卡片无附加参数时先显示用法并保留命令行窗口，可继续输入命令；交互式引导直接进入逐步选择

### 命令行入口

- `UCrawlCLI.exe`
- 入口：`main.py` / `entry.dispatcher`，PyInstaller `console=True`
- 安装器在开始菜单创建“Universal Crawler Pro 命令行”快捷方式，并以 `--mode interactive` 启动
- 可用 `UCrawlCLI.exe --mode cli --help` 做无需用户输入的发布 smoke test

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

安装包构建前会校验 `dist/UniversalCrawlerPro/` 是否同时包含启动中心、GUI/Web 直达 EXE、`BUILD_INFO.txt`、中英文说明文档、WebUI 静态入口和 GUI/WebUI 共享图标：

- `UCrawlLauncher.exe`
- `UCrawlCLI.exe`
- `UniversalCrawlerPro.exe`
- `CrawlerWebPortal.exe`
- `README.md`
- `README_EN.md`
- `_internal/app/web/static/index.html`
- `_internal/app/web/static/app.css`
- `_internal/app/web/static/log_layout.css`
- `_internal/app/web/static/task_pages.css`
- `_internal/app/web/static/task_runtime.css`
- `_internal/app/web/static/media_logs.css`
- `_internal/app/web/static/settings.css`
- `_internal/app/web/static/overlays_responsive.css`
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

1. `python -m pytest tests/release/packaging/test_assets.py`
2. `python tests/launcher.py --list`
3. 启动 `UCrawlLauncher.exe`，确认模式选择器可见并能进入代码量统计
4. 在启动中心选择 CLI / 交互式引导会打开独立终端，并确认 `UCrawlCLI.exe --mode cli --help` 返回成功
5. 启动 `UniversalCrawlerPro.exe`，确认仍直接进入 GUI
6. 启动 `CrawlerWebPortal.exe`，确认仍直接进入 Web UI
7. 验证 Chromium 运行时可用
8. 验证 `ffmpeg.exe`、`ffprobe.exe` 与 `N_m3u8DL-RE.exe` 能被找到
9. 验证下载目录、日志目录和配置目录可正常创建
10. 确认安装源包含 `UCrawlLauncher.exe`、`UCrawlCLI.exe`、`README.md`、`README_EN.md`、`app/web/static/index.html`、七个有序样式表 `app.css`、`log_layout.css`、`task_pages.css`、`task_runtime.css`、`media_logs.css`、`settings.css`、`overlays_responsive.css`、七个职责脚本 `log_i18n.js`、`frontend_runtime.js`、`list_pages.js`、`log_center.js`、`settings_controller.js`、`dialog_controller.js`、`playback_controller.js`，以及 `app.js`、`UI/icon/nav_settings.png`、`favicon.ico` 与 `Web.ico`
11. 确认产物中未混入用户态配置和 Cookie

`portable.spec` 必须继续递归收录整个 `app/web/static` 树；安装器构建脚本还会逐项校验上述七个有序样式表和七个职责脚本，避免静态树存在于源码但安装源缺文件。项目运行、PyInstaller 打包和安装包运行均不依赖 Node，也不引入前端构建器。`node --check` 仅是发布机已安装 Node 时可选的开发/发布语法检查；没有 Node 不影响打包或运行，仍需执行 focused WebUI/packaging pytest 套件与完整 pytest 套件。

## 常见问题

### 未找到 `ms-playwright`

先执行：

```bash
playwright install chromium
```

如果目录存在但仍报缺失，通常是当前 Playwright 所需 revision 未安装，而目录里只有
旧版本缓存。仍应执行上面的命令，不要通过恢复“复制整个缓存目录”绕过检查。

### 未找到 `ISCC.exe`

请安装 Inno Setup 6，或确保 `ISCC.exe` 在系统 `PATH` 中可见。

### 安装器版本不对

不要手改 `installer.iss` 里的版本号。
当前正确做法是修改根目录 `pyproject.toml` 中的 `[project].version`，再重新运行构建脚本。
