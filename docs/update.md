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
