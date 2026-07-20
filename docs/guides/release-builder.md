# 发布构建面板维护指南

本文档说明 Universal Crawler Pro 的唯一发布入口、版本模式、签名材料、
信任锚轮换和远端发布约束。面向维护者，不替代用户安装说明。

## 入口

在项目根目录执行：

```powershell
python packaging/build_release.py
```

无参数运行会打开使用项目标题栏、主题令牌和专用图标的 Qt 构建面板。面板通过
`QProcess` 启动同一脚本的无界面子进程，进度来自结构化 JSONL 事件，不根据日志文本
猜测。

自动化、CI 或兼容旧脚本时使用无界面入口：

```powershell
python packaging/build_release.py --headless --build-only --version 3.6.21
```

只验证计划、不写版本、不构建、不签名、不操作 Git/GitHub：

```powershell
python packaging/build_release.py --headless --dry-run --version 3.6.21 --build-only
```

`--build-only` 只适合本地构建，产物不具备热更新发布资格。

## 版本模式

面板先读取 `shared/version.py` 的本地版本并查询远端最新 Release，再按下表确定模式：

| 目标版本与远端版本 | 模式 | 允许的行为 |
| --- | --- | --- |
| 低于远端 | 本地调试 | 构建本地程序；禁止签名、tag、Release 和上传 |
| 等于远端 | 本地重构建 | 默认只在本地重构建；禁止远端写入 |
| 等于远端且显式允许修复 | 同版本修复 | 可修复既有 Release；必须人工确认覆盖语义 |
| 高于远端 | 新版本发布 | 可启用版本提交、tag、签名、上传和远端回读 |
| 远端不可用且显式离线调试 | 离线调试 | 只允许本地非发布构建 |

目标版本低于远端并不代表降级发布。它始终被当作本地调试，防止误覆盖已发布版本。

## 本地调试边界

本地调试和本地重构建：

- 继承源码中已经提交的生产公钥；
- 不生成本地 manifest 密钥；
- 不写入 `app/config/update_trust.py`；
- 不生成或上传 `latest.json`、`latest.json.sig`；
- 不创建 tag、Release，也不推送分支；
- 不把测试公钥或临时公钥打进 portable/installer。

这些限制由模式验证器和 runner 双重执行，不能只靠面板控件禁用。

## 新版本发布依赖

创建新 Release 时，以下选项构成完整链路：

1. 应用版本变更；
2. 提交版本与公开信任配置；
3. 推送 `main`；
4. 创建或复用 `v<version>` tag；
5. 构建 portable 与 installer；
6. 使用仓库外私钥签署更新清单；
7. 执行 smoke tests；
8. 创建或更新 GitHub Release；
9. 上传 installer、`latest.json`、`latest.json.sig`；
10. 从远端回读并校验资产。

缺少任一强制依赖时，预检会失败关闭。安装包、清单和签名必须来自同一个已验证
`sourceCommit` 快照。

## 同版本修复

同版本修复只在目标版本等于远端版本且维护者显式勾选时可用。该模式可能调用 GitHub
Release 的覆盖能力，其语义等价于明确同意 `--clobber`：

- 不会自动提升版本号；
- 不会隐式替换 tag 指向；
- 上传前仍要求完整签名和远端回读；
- 面板在远端写入开始前显示版本、tag、仓库、代理与资产摘要；
- 必须核对当前 Release 的源提交和资产身份后再确认。

## 密钥与信任锚

默认签名材料目录：

```text
~/.ucrawl/release-secrets
```

可通过 `UCRAWL_RELEASE_SECRETS_DIR` 指向其他仓库外目录。私钥路径也可以由受控环境变量
引用，但私钥内容不得进入参数、请求 JSON、事件、日志、构建目录或 Git。

普通正式发布复用已有私钥，不修改生产信任锚。若对应 public PEM 缺失或与私钥不匹配，
工具会从私钥重新导出并原子修复仓库外 public PEM。

轮换信任锚必须显式勾选，并且只能用于高于远端版本的新版本发布。轮换强制要求：

- 生成新的 manifest key；
- 应用并提交版本变更；
- 把新公钥注入 `app/config/update_trust.py`；
- 推送 `main` 并创建或复用新 tag；
- 从包含新信任锚的同一提交快照重建 installer。

私钥、公钥和信任配置作为一个事务写入。在验证版本提交形成之前，版本应用、提交、
取消或中断失败都会恢复轮换前内容；验证提交形成后，后续推送或构建失败保留已经提交
的源身份，避免把工作树反向改脏。日志只显示文件名和公钥 SHA-256 fingerprint，不显示
私钥目录或内容。

公开 PEM 仅可作为独立、可选的 GitHub Release 审计资产上传，不能复制进 portable 或
installer。运行时信任来源始终是构建快照中的 `UPDATE_PUBLIC_KEY_PEM`。

## 代理

代理选项复用项目配置中心的代理契约：

- 系统代理：保留当前进程环境；
- 直连：从子进程环境移除大小写两套 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`；
- Clash、Clash Verge、v2rayN 等项目预设：把规范化端点写入上述三组变量；
- 自定义：接受明确的 HTTP/HTTPS/SOCKS 端点；
- `env:NAME`：只在子进程内解析受控环境变量，避免把认证信息写入请求文件。

面板只显示代理标签。带认证的 URL、Cookie、Authorization 和 token 会在事件流与持久
日志进入 UI 前脱敏。

## 日志、取消与恢复

面板日志位于：

```text
dist/release-logs/
```

每次执行使用时间戳和随机后缀生成独立审计日志。日志区域支持复制、导出、清空视图和
打开目录；清空视图不会删除持久日志。

取消先请求子进程协作退出，超时后终止进程；Windows 上会使用 `taskkill /T /F` 清理进程
树并等待确认。关闭仍在运行的面板会先进入取消流程，只有子进程、远端查询线程和日志
写入生命周期收束后才关闭窗口。

日志写入失败不会把已经取得的发布结果改写成失败，但 UI 会明确提示审计日志可能不完整。
协议事件缺失、畸形或终态与进程退出码不一致时，发布按失败处理。

## 版本唯一事实源

项目版本唯一事实源是：

```text
shared/version.py
```

`pyproject.toml` 通过动态元数据读取该值。版本事务只允许同步以下当前版本投影：

- `README.md`
- `README_EN.md`
- `docs/README.md`
- `cli/skill/SKILL.md`

历史 Release 文档不在投影列表中，不会因新版本构建被批量改写。版本更新先生成完整计划，
再使用临时文件和 `os.replace` 原子提交；中途失败会回滚已经替换的文件。

## 远端资产验收

正式发布至少要求并回读校验：

- `UniversalCrawlerPro_Setup_<version>.exe`
- `latest.json`
- `latest.json.sig`

可选上传：

- `update_manifest_ed25519_public.pem`

回读会复核资产名称、大小、SHA-256、下载 URL、平台、版本、`sourceCommit` 和 Ed25519
签名。公钥资产只用于独立审计，不替代客户端内置信任锚。

## 发布前检查

```powershell
python -m pytest tests/release/packaging tests/release/updater -q
python -m ruff check packaging/build_release.py packaging/release_tool scripts/update_bootstrap.py
python -m compileall packaging/release_tool packaging/build_release.py
python -m scripts.update_bootstrap scan-secrets
```

最后确认工作树只包含预期公开文件，且私钥、token、代理密码、请求临时文件均未被 Git
跟踪。

### 2026-07-19 验收记录

- Release 打包与更新器分区：`764 passed in 97.04s`。
- Headless 规划烟测：
  `python packaging/build_release.py --headless --dry-run --version 3.6.21 --build-only`，
  返回码为 `0`，且不会修改统一版本源。
- 私钥扫描区分文档/测试中的短合成占位文本与真实 PEM 载荷；真实私钥即使落入测试目录也会
  阻断发布。
- 正式发布仍必须完成 installer、`latest.json`、`latest.json.sig` 三项远端回读，不能用
  dry-run 或本地构建结果替代。
