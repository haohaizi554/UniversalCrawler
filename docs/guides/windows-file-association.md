# Windows 默认打开方式接入经验

## 背景

本项目支持通过打包后的 `UniversalCrawlerPro.exe` 直接打开本地视频和图片资源。用户在 Windows 中把 `.mp4`、`.mkv`、`.jpg` 等扩展名设为本软件打开后，期望双击文件时：

1. 启动 `UniversalCrawlerPro.exe`。
2. 自动切到文件所在目录。
3. 选中对应资源。
4. 直接播放视频或预览图片。

这里真正容易踩坑的是第 1 步：Windows 10/11 的“默认打开方式”并不是只看 `HKCU\Software\Classes` 或 Inno Setup 的 `ChangesAssociations=yes`。

## 这次踩到的问题

安装器最初只做了这些事：

- 注册 `RegisteredApplications`。
- 写入 `Capabilities\FileAssociations`。
- 写入 `Applications\<exe>\shell\open\command`。
- 写入扩展名到自定义 `ProgID` 的映射。
- 安装结束后跳转 Windows 默认应用设置页，让用户验证。

结果是 Windows 设置页能看到 `Universal Crawler Pro` 这个候选应用，但 `.avi`、`.mkv`、`.mp4` 等扩展名仍然显示为系统自带“媒体播放器”。双击文件只会启动默认播放器，或者只启动 exe 而没有进入目标文件。

根因是：现代 Windows 会优先读取当前用户下的 `UserChoice`：

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.ext\UserChoice
```

这个键里必须有匹配的：

- `ProgId`
- `Hash`

只写普通扩展名关联，最多让应用出现在候选列表里，不等于成为默认打开方式。

## 正确实现

当前实现分两层：

### 1. 注册候选应用

代码位置：

- `app/services/windows_file_association_service.py`
- `packaging/installer.iss`

需要写入：

- `Software\RegisteredApplications`
- `Software\UniversalCrawlerPro\Capabilities`
- `Software\Classes\Applications\UniversalCrawlerPro.exe\shell\open\command`
- `Software\Classes\UniversalCrawlerPro.Video`
- `Software\Classes\UniversalCrawlerPro.Image`
- 各扩展名的 `OpenWithProgids`
- `SupportedTypes`

这一步负责让 Windows 知道本软件支持哪些文件类型。

### 2. 设置当前用户默认值

代码位置：

- `WindowsFileAssociationService.set_current_user_defaults()`

核心动作：

1. 获取当前用户 SID。
2. 删除旧的扩展名 `UserChoice`。
3. 创建新的 `UserChoice` 键。
4. 读取新键的最后写入时间，并按分钟截断为 FileTime hex。
5. 计算 Windows 认可的 `Hash`。
6. 写入 `ProgId` 和 `Hash`。
7. 调用 `SHChangeNotify(SHCNE_ASSOCCHANGED)` 刷新 Shell 关联缓存。

安装器通过 exe helper 调用：

```text
--register-file-associations video --set-default-file-associations
```

不要在 Inno Setup 脚本里直接声明 `shell32.dll` 外部函数；之前出现过 `<utf8>shell32.dll` 运行时导入错误。Shell 刷新统一放到 Python/ctypes 里做，安装版和免安装版可以复用同一套逻辑。

## 用户授权边界

这类功能容易滑向“默认程序劫持”。本项目的约束是：

- 只在安装器明确勾选“视频文件默认使用本软件打开”或“图片文件默认使用本软件打开”时写入默认值。
- 视频默认勾选，图片默认不勾选。
- 免安装版只能由用户在应用内点击“默认打开”后触发。
- 不做后台反复抢占，不做静默恢复，不做卸载后残留抢占。

也就是说，我们学习的是 Windows 默认打开方式的技术机制，不学习流氓软件的隐蔽行为。

## 安装后不再跳设置页

当 `UserChoice` 已成功写入并诊断确认没有 `pending_extensions` 时，不需要再跳转 Windows 设置页。

当前策略：

- 安装器：不再传 `--open-default-apps-settings`。
- 应用内按钮：如果仍有扩展名 pending，才打开 Windows 设置页作为兜底。
- 诊断命令仍保留，方便手工确认：

```powershell
.\UniversalCrawlerPro.exe --check-file-associations video
```

期望输出：

```text
registered_app=True
defaulted=.mp4,.avi,.mkv,.mov,.flv,.wmv,.m4v,.webm,.m3u8,.ts
pending=
```

## 回归测试要点

相关测试：

- `tests/unit/app/services/test_windows_file_association.py`
- `tests/contract/entry/test_gui_entry.py`
- `tests/unit/app/controllers/test_application_controller.py`
- `tests/release/packaging/test_assets.py`

重点覆盖：

- Hash 计算有已知向量保护。
- 安装器传入 `--set-default-file-associations`。
- 安装器不再传入 `--open-default-apps-settings`。
- 当前用户默认值写入 `UserChoice`。
- 成功绑定后应用内不跳设置页。
- 仍有 pending 扩展名时才打开设置页兜底。

## 经验总结

- `ChangesAssociations=yes` 不是默认打开方式的充分条件。
- `Capabilities` 只解决“出现在候选列表”，不解决“成为默认值”。
- Windows 10/11 默认应用的关键状态在 `UserChoice`。
- `UserChoice` 的 `Hash` 和用户 SID、ProgID、扩展名、UserExperience 字符串、键最后写入时间有关。
- 写入后必须刷新 Shell 关联缓存，否则图标和双击行为可能短时间不一致。
- 成功绑定后跳设置页会制造“好像还要用户确认”的错觉，应当收掉。
