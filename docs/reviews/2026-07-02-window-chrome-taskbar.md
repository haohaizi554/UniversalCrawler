# 2026-07-02 自绘标题栏与 Windows 窗口体验复盘

## 当前结论

本次复盘已合并到工程实践文档：

- [Windows 自绘标题栏与原生窗口行为](../engineering/windows-native-chrome-hit-test.md)

后续维护自绘标题栏、最大化、边框缩放、Snap Layout、任务栏避让和黑边问题时，以该工程文档为准。

## 问题现象

当时出现的问题包括：

- 鼠标悬停最大化按钮不出现 Windows 11 Snap Layout。
- 窗口边缘不出现系统双箭头缩放。
- 最大化或还原时出现黑边闪烁。
- 最大化后偶发冒出第二套 Windows 原生按钮。
- 自动隐藏任务栏在某些状态下不易从屏幕边缘唤出。

这些现象说明问题不只是“自绘标题栏画得不像”，而是 Windows 原生非客户区和 Qt 自绘标题栏之间的职责边界没有彻底理顺。

## 修正后的方向

最终采用的方向是：

```text
Qt FramelessWindowHint 隐藏系统标题栏绘制
Win32 style 保留窗口管理能力
WM_NCCALCSIZE 隐藏原生非客户区
WM_NCHITTEST 返回正确命中语义
WM_GETMINMAXINFO 约束最大化工作区
```

这条路线同时满足：

- 自绘标题栏视觉可控。
- Windows 仍能识别最大化按钮、标题栏拖动区和缩放边框。
- Snap Layout、系统双箭头缩放、贴边吸附和任务栏避让保持原生体验。

## 已废弃的旧判断

以下旧判断不要再沿用：

- “Windows 下不使用 `FramelessWindowHint`”。
- “最小化和关闭按钮也返回 `HTMINBUTTON` / `HTCLOSE`”。
- “用 `WM_NCCALCSIZE` 同时承担标题栏隐藏和最大化工作区调整”。
- “用 `showFullScreen()` 或 `setGeometry()` 模拟主窗口最大化”。

正确规则见 [Windows 自绘标题栏与原生窗口行为](../engineering/windows-native-chrome-hit-test.md)。

## 维护提示

后续如果又出现黑边、第二套系统按钮、边缘不可缩放或 Snap Layout 消失，先不要改页面布局和按钮样式，应该先检查：

- `FramelessWindowHint` 是否仍在 Windows 主窗口上启用。
- Win32 style 是否有 `WS_THICKFRAME`、`WS_MAXIMIZEBOX`，且没有 `WS_POPUP`。
- 最大化按钮区域是否返回 `HTMAXBUTTON`。
- 最小化和关闭按钮是否仍返回 `HTCLIENT`。
- `WM_NCCALCSIZE` 是否稳定隐藏原生非客户区。
- 最大化和还原路径是否仍是 `showMaximized()` / `showNormal()`。
