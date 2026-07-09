# Secure Update Flow

UCrawl 的自动更新流程使用 signed manifest，而不是直接信任 GitHub Release
asset。客户端不会内置 GitHub token、PAT、client secret 或长期凭证。

## Release Assets

每个 Release 至少包含：

- `latest.json`
- `latest.json.sig`
- 当前平台安装包，例如：
  - `UniversalCrawlerPro_Setup_3.7.0_x64.exe`
  - `UniversalCrawlerPro_Setup_3.7.0_arm64.exe`
  - `UniversalCrawlerPro_3.7.0_x64.msi`
  - `UniversalCrawlerPro_3.7.0_macos_arm64.pkg`
  - `UniversalCrawlerPro_3.7.0_linux_x64.AppImage`

GUI 只会选择 manifest 中精确匹配当前 `os + arch + installerType` 的 asset。
不会按文件名猜测“看起来像”的安装包。

## Multiple Version Candidates

手动检查更新时，客户端会读取最近的 GitHub Releases，并只把同时包含
`latest.json` 与 `latest.json.sig` 的 Release 作为候选。每个候选都必须先完成
Ed25519 manifest 签名校验、`appId/channel/schema/expiresAt` 校验和当前平台 asset
匹配，才会出现在 GUI 的版本选择面板里。

这意味着版本选择面板不是直接信任 GitHub tag 列表；用户看到的每个版本都来自已验签
manifest。默认选择最高可用版本，但当本地版本落后多个 Release 时，用户可以选择任一
高于当前版本且满足 `minClientVersion` 的候选版本安装。

## latest.json Schema

`latest.json` 必须是 UTF-8 JSON object，字段示例：

```json
{
  "schema": 1,
  "appId": "ucrawl.universalcrawlerpro",
  "channel": "stable",
  "version": "3.7.0",
  "tag": "v3.7.0",
  "publishedAt": "2026-07-09T00:00:00Z",
  "expiresAt": "2026-08-09T00:00:00Z",
  "minClientVersion": "3.0.0",
  "mandatory": false,
  "notes": "Release notes",
  "assets": {
    "windows-x64": {
      "name": "UniversalCrawlerPro_Setup_3.7.0_x64.exe",
      "url": "https://github.com/OWNER/REPO/releases/download/v3.7.0/UniversalCrawlerPro_Setup_3.7.0_x64.exe",
      "sha256": "<64 hex chars>",
      "size": 12345678,
      "installerType": "inno",
      "os": "windows",
      "arch": "x64"
    }
  }
}
```

Allowed hosts default to `github.com`, `objects.githubusercontent.com`, and
`release-assets.githubusercontent.com`. Use `trustedHosts` only for controlled
release infrastructure.

## Signing

The manifest is signed with Ed25519. The public key must be shipped in the
read-only updater trust config (`app/config/update_trust.py` /
`UPDATE_PUBLIC_KEY_PEM`) before enabling production auto-update.

Windows/macOS installer verification also requires a production allowlist:
configure `UPDATE_TRUSTED_PUBLISHERS` and/or `UPDATE_TRUSTED_THUMBPRINTS` in
`app/config/update_trust.py` to match the release signing certificate. Leaving
them empty makes verification fail closed.

Generate `latest.json` and `latest.json.sig` with the release helper. Keep the
private key outside the repository:

```powershell
python packaging/update_manifest.py `
  --output-dir dist/release-assets `
  --private-key C:\secure\update-private-ed25519.pem `
  --version 3.7.0 `
  --tag v3.7.0 `
  --asset-spec C:\secure\release-assets.json `
  --notes "Release notes"
```

`release-assets.json` is a JSON array:

```json
[
  {
    "key": "windows-x64",
    "path": "dist/installer/UniversalCrawlerPro_Setup_3.7.0.exe",
    "url": "https://github.com/OWNER/REPO/releases/download/v3.7.0/UniversalCrawlerPro_Setup_3.7.0.exe",
    "os": "windows",
    "arch": "x64",
    "installerType": "inno"
  }
]
```

Never publish the private key. Do not fetch public keys from the network.

## Production Bootstrap With Local Scripts

生产启用由 `scripts/update_bootstrap.py` 串起来，目标是让 release 机器或 CI
自动完成公开 trust anchor 注入，同时把签名材料留在仓库外。

最短路径：

```powershell
python packaging/build_release.py
python scripts/update_bootstrap.py production-bootstrap --installer dist/installer/UniversalCrawlerPro_Setup_<version>.exe
python packaging/update_manifest.py `
  --output-dir dist/release-assets `
  --version <version> `
  --tag v<version> `
  --asset-spec <asset-spec>
```

然后上传这些公开 release 资产：

- `UniversalCrawlerPro_Setup_<version>.exe`
- `latest.json`
- `latest.json.sig`

`production-bootstrap` 会按顺序执行：

- 确认 release secret 目录不在当前 git working tree 内。
- 缺少 manifest keypair 时，在本机 release secret 目录生成 Ed25519 keypair。
- 只把 public key 注入 `UPDATE_PUBLIC_KEY_PEM`。
- 发现真实 Windows Code Signing 证书，签名并验证 installer。
- 从已签 installer 提取 signer subject、SHA1 thumbprint 和 SHA256 fingerprint。
- 注入 `UPDATE_TRUSTED_PUBLISHERS` 与 `UPDATE_TRUSTED_THUMBPRINTS`。
- 运行 `scan-secrets` 和 updater 相关测试。

默认 release secret 目录：

- Windows: `%USERPROFILE%\.ucrawl\release-secrets`
- macOS/Linux: `~/.ucrawl/release-secrets`

可以用 `UCRAWL_RELEASE_SECRETS_DIR` 覆盖，但该路径如果落在仓库内，脚本会拒绝执行。

会提交到仓库的是公开 trust anchor 和自动化代码：

- `UPDATE_PUBLIC_KEY_PEM`
- `UPDATE_TRUSTED_PUBLISHERS`
- `UPDATE_TRUSTED_THUMBPRINTS`
- bootstrap scripts
- docs/tests

绝对不要提交的是签名材料或发布凭据：

- `update_manifest_ed25519_private.pem`
- `*.pfx`
- `*.p12`
- certificate passphrase
- timestamp credentials
- Azure/Microsoft signing credentials
- 含本地私有路径的 release asset spec，除非已经脱敏

如果当前机器没有真实 Code Signing certificate，生产 bootstrap 必须失败；不要把
self-signed development certificate 写进生产 `update_trust.py`，也不要把生产校验改成
fail-open。开发测试可以使用：

```powershell
python scripts/update_bootstrap.py generate-dev-windows-cert --write-dev-trust
```

该命令只写 `app/config/update_trust_dev.py`，生产 updater 不会导入它。

`packaging/build_installer.py` 默认不签名。需要生产签名时显式设置
`UCRAWL_SIGN_WINDOWS=1`，并配置真实证书选择、timestamp URL 和 signtool 路径：

- `UCRAWL_SIGN_CERT_SHA1` 或 `UCRAWL_SIGN_CERT_SUBJECT`
- `UCRAWL_TIMESTAMP_URL`
- 可选 `UCRAWL_SIGNTOOL_PATH`
- 可选 `UCRAWL_SIGN_PFX_PATH` 与对应 passphrase 环境变量

签完后 `packaging/update_manifest.py` 会用 `app/config/update_trust.py` 中的
`UPDATE_PUBLIC_KEY_PEM` 重新验证 `latest.json.sig`。如果公钥未注入或签名不匹配，
脚本会删除 `.sig` 并失败。

## Local Test

Run the updater unit tests:

```powershell
python -m pytest tests/test_secure_updater.py tests/test_update_check_service.py -q
```

For a local signed-manifest check, inject a test public key into
`check_secure_update(..., public_key_pem=...)` and pass local `manifest_path`
and `signature_path`.

## Platform Install Behavior

- Windows MSI: helper runs
  `msiexec.exe /i <installer.msi> /passive /norestart /L*v <logPath>`.
- Windows Inno: helper runs only explicit Inno silent arguments.
- Windows NSIS: helper runs only explicit NSIS silent arguments.
- macOS PKG: helper delegates to `/usr/sbin/installer`.
- Linux AppImage/deb/rpm: hash verification is enforced; privileged package
  manager flows should be added only with explicit helper support.

The GUI must spawn `entry.updater_helper` after download verification. Portable
and installer builds include a dedicated `updater_helper.exe`; frozen GUI builds
prefer that helper instead of trying to install from the main process. The helper
repeats hash and OS signature verification before executing any installer. All
process calls use argv arrays with `shell=False`.

## Failure Recovery

The updater records structured logs such as:

- `update.check.started`
- `update.check.available`
- `update.download.started`
- `update.download.progress`
- `update.download.completed`
- `update.verify.failed`
- `update.install.started`
- `update.install.exit`
- `update.install.succeeded`
- `update.install.failed`

Pending installs track attempt counts and are cleared only when the next app
startup reports the expected version. Failed versions are not retried forever.

Check `user_data/logs/latest_debug.log` and installer logs for troubleshooting.
