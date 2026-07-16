# 热更新签名清单缺失与安装包超限复盘

## 现象

使用已安装的 `v3.6.17` 检查 `v3.6.21` 时，问题分两层暴露：

1. 客户端能够发现 GitHub Release 的新版本，但提示缺少 `latest.json` 与 `latest.json.sig`，拒绝自动更新。
2. 补齐签名清单后，更新进入下载准备阶段，随后以 `asset size exceeds configured maximum` 失败。
3. GUI 更新失败对话框中的“查看日志”没有动作，WebUI 更新弹窗也没有对应入口。

这些现象不是版本跨度或配置迁移导致的。旧包与新包即使只有版本号差异，只要 Release 元数据不完整，或者安装包超过客户端安全上限，更新链仍会按设计失败关闭。

## 根因

### Release 资产不完整

发布流程只上传了安装包，没有把签名清单作为同一 Release 的必备资产。版本发现读取 GitHub Release 标签，因此能看到 `v3.6.21`；自动安装必须经过 Ed25519 清单、平台资产、文件大小和 SHA-256 校验，所以不能用未签名的 Release 数据降级授权安装。

### 打包结果依赖发布机历史缓存

旧 `portable.spec` 直接复制整个 `%LOCALAPPDATA%\ms-playwright`。该目录是机器级共享缓存，会长期累积多代 Chromium、Firefox、WebKit、headless shell 和 FFmpeg revision。一次实测中：

- 便携目录总计 `3.073 GiB`；
- `ms-playwright` 占 `2.102 GiB`；
- 其中包含三代 Chromium、两代 Firefox、两代 WebKit；
- Inno Setup 安装包达到 `987.61 MiB`。

这使发布物体积取决于“发布机用过哪些 Playwright 版本”，而不是取决于项目当前依赖，是不可复现构建。

### 下载上限与实际发布物脱节

客户端默认上限原为 `512 MiB`，而 Release 安装包已经超过该值。清单中的大小不能伪造，因为下载完成后还会校验实际字节数和 SHA-256。正确做法是同时控制发布物体积并为合理的生产包预留安全空间，而不是移除上限。

### 日志入口在异步重构后断链

日志文件打开已经迁移到 `FrontendStateService` action worker，更新对话框仍向不再接入控制器的旧信号发射，形成孤立信号。WebUI 的日志中心具备 `/api/debug/latest-log`，但更新弹窗没有暴露该入口。

## 修复

### 可复现的 Playwright 收集

`packaging/playwright_bundle.py` 从当前 Python 环境内 Playwright 自带的 `browsers.json` 读取 revision，只选择当前 Chromium 运行时：

- `chromium-<revision>`；
- `chromium_headless_shell-<revision>`（当前版本声明时）；
- `ffmpeg-<revision>`；
- `winldd-<revision>`（当前版本声明时）。

Firefox、WebKit 和历史 revision 不再进入发布物。缺少当前 revision 时构建立即失败，并提示执行 `python -m playwright install chromium`。

本次目录级静态核验预计把便携包从 `3.073 GiB` 降至约 `1.599 GiB`，移除约 `1.474 GiB` 历史缓存。最终安装包大小必须在真实构建后重新记录。

### 保留有界下载

默认更新资产上限提升为 `2 GiB`。`packaging/update_manifest.py` 复用同一常量，生成清单前先校验本地安装包；超过客户端上限时发布端直接失败，避免生成客户端必然拒绝的签名元数据。

资产描述文件同时兼容 PowerShell 5 常见的 UTF-8 BOM，避免 Windows 发布机在签名前因编码失败。

### 双端日志入口

- GUI 更新弹窗调用 `_handle_log_action("open_latest")`，继续经 action worker 执行文件操作，不在 UI 线程直接读写文件。
- WebUI 更新弹窗通过 `/api/debug/latest-log` 在新标签页打开日志，不尝试访问浏览器不可见的本地路径。

### 失败关闭的一键发布资产

`python packaging/build_release.py` 现在默认要求干净工作树、同名 tag 指向 `HEAD`、版本与
安装包一致，并要求 manifest 私钥位于仓库外。构建完成后，它会在临时目录生成安装包、
`latest.json` 与 `latest.json.sig`，重新核对源提交、最终文件 SHA-256、URL、平台字段和
Ed25519 签名，全部通过后才原子切换到 `dist/release-assets/v<version>/`。

只构建便携版/安装器必须显式传入 `--build-only`；该模式会明确提示没有生成签名清单，
不得直接作为支持热更新的 Release。这样把“三项资产缺一不可”从人工守则升级为可执行门禁。

## 发布守则

1. 运行 `python -m playwright install chromium`，确认当前 revision 完整。
2. 构建后记录便携目录和安装包实际大小，不能沿用上一次数据。
3. 运行默认 `build_release.py` 原子生成安装包、`latest.json` 与 `latest.json.sig`；生成器必须校验安装包上限、大小、SHA-256、源提交和签名。
4. GitHub Release 必须同时具备安装包、`latest.json`、`latest.json.sig` 三项资产后才能宣布支持热更新。
5. 从 GitHub 重新下载两个元数据文件，用客户端内置公钥验签；不能只验证本地产物。
6. 使用旧版本号执行一次真实在线检查，确认状态为 `available`、平台资产匹配且下载准备能够启动。

## 验证

- 新增下载上限、Playwright revision 选择、BOM 兼容、发布上限门禁、GUI/WebUI 日志入口测试。
- 更新器、更新检查、GUI、打包、Web 静态契约与 FastAPI 定向回归：`451 passed`。
- 手动构建后的安装包体积、启动和完整热更新仍属于发布验收步骤，不能由静态测试替代。
