# 打包说明

## 目标

`packaging/` 目录用于生成桌面端分发产物，当前支持：

- 便携版目录打包
- 安装包生成
- 一键发布脚本

## 主要脚本

- `build_portable.py`
  - 生成便携版目录，适合本地验证与手动分发。
- `build_installer.py`
  - 基于 Inno Setup 生成安装包。
- `build_release.py`
  - 串联便携版与安装包流程。
- `generate_installer_assets.py`
  - 生成安装器资源图。

## 便携版构建

```bash
python packaging/build_portable.py
```

典型产物：

- `dist/UniversalCrawlerPro/UniversalCrawlerPro.exe`
- 随包携带的 `ffmpeg.exe`
- 随包携带的 `N_m3u8DL-RE.exe`
- Playwright Chromium 运行时

## 安装包构建

前置条件：

- 已安装 Inno Setup 6
- 系统可访问 `ISCC.exe`

执行：

```bash
python packaging/build_installer.py
```

安装器脚本位于：

- `packaging/installer.iss`

## 一键构建

```bash
python packaging/build_release.py
```

## 打包注意事项

- 用户数据不应被打进安装包。
- `config.json` 与平台 Cookie 文件应保持为运行期产物。
- 构建前请先执行完整测试，至少运行 `python -m unittest discover -s tests`。
- 如果修改了外部工具路径发现逻辑，请同步验证打包后的运行时路径。

## 建议发布前检查

- 主程序可启动。
- Chromium 运行时可用。
- `ffmpeg.exe` 与 `N_m3u8DL-RE.exe` 可被发现。
- 下载目录与日志目录可正常创建。
- UI 顶部调试入口可打开日志与错误摘要。
