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

打包后的 Windows 产物提供模式启动中心、独立命令行入口，同时保留两个既有直达入口：

- `UCrawlLauncher.exe` → `main.py` / `entry.dispatcher`（Qt 模式选择与代码量统计）
- `UCrawlCLI.exe` → `main.py` / `entry.dispatcher`（带真实标准输入/输出的 CLI 与交互式引导）
- `UniversalCrawlerPro.exe` → `entry.gui_entry`
- `CrawlerWebPortal.exe` → `entry.web_entry`

`UCrawlLauncher.exe` 是无控制台窗口程序；选择 CLI 或交互式引导时，它会把模式和剩余参数委托给同目录的 `UCrawlCLI.exe`，避免在窗口子系统进程中运行依赖 stdin/stdout 的流程。CLI 卡片在没有附带命令时会先显示用法并保留独立命令行窗口，交互式引导则直接进入逐步选择。GUI/Web 两个 EXE 继续绕过 dispatcher，原有双击启动语义不变；安装器在开始菜单同时暴露启动中心与命令行入口。

## 关键原则

- 版本号只认 `pyproject.toml`
- 安装器版本不得手工硬编码
- 打包态用户数据不得回写进仓库
- 开发态与打包态路径必须继续遵守 `runtime_paths.py` 规范
- 外部工具必须显式随包交付，不依赖用户手工补环境
- Playwright 只打包当前依赖声明的 Chromium revision，禁止复制整份机器级浏览器缓存
- 热更新 Release 必须同时发布安装包、`latest.json` 与 `latest.json.sig`

## 元数据与路径收口

打包链路必须复用应用本身的运行时元数据入口，避免发布脚本、PyInstaller spec 和安装器各自维护一套规则。

- 运行时路径统一由 `app/utils/runtime_paths.py` 维护。
- 项目版本、发布名称、EXE 名称、图标名称、安装目录名和 Windows 标识统一由 `packaging/project_meta.py` 收口。
- 不要在 `portable.spec`、`installer.iss` 或发布脚本中重复硬编码路径、版本或应用标识。
- `packaging/README.md` 记录构建脚本职责；本文档记录发布流程和人工验收清单。
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
  - `../changelog.md`

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
python -m pytest tests/release/packaging/test_assets.py
python -m pytest tests/integration/app/core/downloaders/test_runtime.py
python tests/launcher.py --list
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

- `UCrawlLauncher.exe`
- `UCrawlCLI.exe`
- `UniversalCrawlerPro.exe`
- `CrawlerWebPortal.exe`
- `_internal/`
- `BUILD_INFO.txt`
- `ffmpeg.exe`
- `ffprobe.exe`
- `N_m3u8DL-RE.exe`
- `ms-playwright/`

`ms-playwright/` 由 `packaging/playwright_bundle.py` 按当前 Playwright 的
`browsers.json` 精确选择 Chromium、headless shell、FFmpeg 与平台辅助程序。
构建脚本不得直接复制 `%LOCALAPPDATA%\ms-playwright` 整目录，否则旧 Chromium、
Firefox 和 WebKit revision 会让发布物随发布机历史持续膨胀。

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

### 发布构建器

```bash
python packaging/build_release.py
```

无参数运行打开主题化发布构建面板；CI 和脚本可使用 `--headless`。面板的版本模式、
签名材料、代理、取消与远端验收规则见
[发布构建器维护指南](release-builder.md)。

面板中选择正式发布后，会执行失败关闭的完整热更新准备流程，而不是只构建 EXE：

1. 查询远端版本并锁定本次本地调试、同版本修复或新版本发布模式。
2. 在版本提交和构建快照之前解析仓库外 Ed25519 材料；显式轮换时先原子写入并提交公开信任锚。
3. 要求 Git 工作树干净，版本提交已推送，且 `v<version>` tag 精确指向该提交。
4. 从该提交导出临时 `git archive` 快照，物化并按 OID/大小校验 Git LFS 对象；三个 Windows 工具还必须通过 PE 头与最小体积检查。
5. 便携版、安装包、manifest 生成器与客户端验证器全部从同一快照运行，快照源码树在全过程中不得修改、新增或删除。
6. 启用 Windows 签名时，必须预先提交生产发布者/指纹且强制操作系统签名校验，再将最终安装包签名人与已冻结信任匹配。
7. 在临时目录生成并回验安装包、`latest.json`、`latest.json.sig`，重新核对最终安装包 SHA-256、下载 URL、平台字段、源提交和 Ed25519 签名后，
   一次性发布到 `dist/release-assets/v<version>/`。

热更新三项资产必须同时上传。公开 PEM 可作为独立的审计资产上传，但不会复制进
portable 或 installer。清单生成器会拒绝超过客户端 `DEFAULT_MAX_DOWNLOAD_BYTES`
（当前 `2 GiB`）的安装包。

发布入口和两个叶子构建脚本共用跨进程锁。父流程仅通过一次性令牌授权本次子构建；直接启动叶子脚本也会申请同一把锁，不会形成无保护的并发写入。普通构建禁止改写信任配置；显式信任锚轮换被建模为版本提交前的事务，在验证版本提交形成前失败会回滚，提交形成后保留已提交源身份，并必须从包含新公钥的同一提交快照重建安装包。

Windows 发布快照默认写入仓库同级的 `.ucrawl-release-tmp` 短目录。该边界用于控制 Playwright、Qt 等深层随包资源的绝对路径长度，防止 Inno Setup 压缩接近结束时才因传统 Win32 路径上限失败。需要切换构建盘时可设置 `UCRAWL_RELEASE_TEMP_ROOT`，但必须使用短、可写的本地路径；不要指向仓库目录或网络共享。

冻结分析会执行少量模块导入，因此构建编排必须将 `UCRAWL_USER_DATA_ROOT` 指向快照内已隔离的 `build/runtime-user-data`。三个冻结入口脚本作为受 Git 管理的 canonical 源文件，由 `portable.spec` 只读消费；构建期不得删除后重建。发布门禁仍对其余快照文件逐项计算 SHA-256；构建副作用应被隔离，不能靠白名单跳过源码完整性验证。

只做本地构建或生产信任 bootstrap 时必须显式使用：

```bash
python packaging/build_release.py --build-only
```

该模式不会生成签名清单，输出不得直接宣称支持热更新。密钥初始化和手工清单命令见
[更新安全文档](../update.md)。

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
- `xhs_auth.json`

原因：

- 这些都是运行期状态，不应进入发布物
- 否则会污染用户环境，且容易把开发机状态带入正式包

## 安装源完整性校验

`packaging/build_installer.py` 在调用 Inno Setup 前会检查便携版安装源，避免把不完整的 `dist/UniversalCrawlerPro/` 目录打成安装包。当前必须存在：

- `UCrawlLauncher.exe`
- `UCrawlCLI.exe`
- `UniversalCrawlerPro.exe`
- `CrawlerWebPortal.exe`
- `BUILD_INFO.txt`
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
- `_internal/app/web/static/app.js`
- `_internal/UI/icon/nav_settings.png`
- `favicon.ico`
- `Web.ico`

如果这些文件缺失，应先重新运行 `python packaging/build_portable.py`，不要直接复用旧 dist 目录生成安装包。

## 安装器原子发布与资源锁竞态

`build_installer.py` 不得直接在
`dist/installer/UniversalCrawlerPro_Setup_<version>.exe` 上原地编译。每次 Inno
尝试必须使用独立的 `dist/installer/.inno-build-*` 目录；仅当暂存安装包存在、
时间戳属于本次构建且 Inno 成功退出后，才能同卷原子替换正式产物。构建失败时，
上一份有效安装包必须继续保留。

Windows 的安全扫描或文件索引可能在 Inno 输出
`Updating icons (Setup.exe)` 时短暂持有新 PE，随后报
`Resource update error: EndUpdateResource failed (110)`。这是可识别的资源写入
竞态：允许在新工作区做有限退避重试。其他编译错误不得套用该重试，也不得建议
用户长期关闭安全软件作为默认构建流程。相关回归测试位于
`tests/release/packaging/test_assets.py`。

## 发布后人工验收

建议至少人工验证以下项目：

1. 双击 `UCrawlLauncher.exe` 能打开模式选择器，并能进入代码量统计
2. 在启动中心选择 CLI / 交互式引导会打开独立终端，且 `UCrawlCLI.exe --mode cli --help` 能非交互退出并返回成功
3. 双击 `UniversalCrawlerPro.exe` 仍能直接启动 GUI
4. 双击 `CrawlerWebPortal.exe` 仍能直接启动 Web UI
5. Web UI 能正常打开浏览器
6. GUI / Web 都能创建下载目录
7. `ffmpeg.exe`、`ffprobe.exe` 与 `N_m3u8DL-RE.exe` 可被发现
8. Playwright Chromium 可用
9. 用户数据写入位置符合当前路径规范
10. 安装源完整性校验通过，启动中心、命令行入口、中英文说明文档、Web 静态入口、CSS/JS、GUI/Web 图标和 UI 图标随包存在
11. 安装包的启动中心、命令行、GUI、Web 开始菜单快捷方式以及既有桌面快捷方式可用
12. 卸载流程正常
13. 开发态落盘仍在项目根 `user_data/`，打包态落盘切到 `%LOCALAPPDATA%`
14. 把保存目录临时指向一个包含大量无关文件的宽目录，启动 GUI 后窗口仍可拖动、切换和关闭，不出现 Windows“未响应”
15. 启动日志出现 `DL_STARTUP_MAINTENANCE_START` 和 `DL_STARTUP_MAINTENANCE_DONE`；旧目录迁移未完成时只记录 `legacy_scan_pending=true`，不能阻塞 GUI
16. 正常关闭 GUI 后进程退出码为 `0`，日志不得出现 `DL_DISPATCHER_STOP_TIMEOUT`；线程超时只能在 `join(timeout)` 后以 `is_alive()` 判定
17. 下载任务创建前存在恢复账本记录；成功后立即销账，失败目录在下次启动尝试清理后销账

冻结态读取 `%LOCALAPPDATA%` 中的真实配置，不能只在源码态默认 `user_data/` 下验证启动性能。保存根属于用户可控输入，打包验收必须按“大目录、慢磁盘、目录已被删除”三种情况测试。相关复盘见 [打包态启动未响应与递归清理](../postmortems/packaged-startup-recursive-sweep-freeze.md)。

## 相关文件

- [packaging/README.md](../../packaging/README.md)
- [packaging/build_portable.py](../../packaging/build_portable.py)
- [packaging/build_installer.py](../../packaging/build_installer.py)
- [packaging/portable.spec](../../packaging/portable.spec)
- [packaging/installer.iss](../../packaging/installer.iss)
- [packaging/project_meta.py](../../packaging/project_meta.py)
- [app/utils/runtime_paths.py](../../app/utils/runtime_paths.py)
- [tests/release/packaging/test_assets.py](../../tests/release/packaging/test_assets.py)
- [docs/guides/windows-file-association.md](windows-file-association.md)
