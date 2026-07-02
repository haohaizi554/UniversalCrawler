# Windows 自绘标题栏与原生窗口行为

本文是 Universal Crawler Pro 在 Windows 下处理自绘标题栏、窗口缩放、最大化、Snap Layout 和任务栏交互的权威说明。若其它旧文档与本文冲突，以本文为准。

## 目标

项目需要的是：

```text
标题栏由 Qt 自绘
窗口管理仍交给 Windows
```

也就是说，视觉层可以定制，但拖动、贴边吸附、边框双箭头缩放、最大化、Win11 Snap Layout、任务栏避让和系统动画都应尽量保留 Win32 原生语义。

## 正确方案

Windows 下采用混合方案：

```text
Qt.Window | Qt.FramelessWindowHint
    用来阻止 Windows 原生标题栏绘制

Win32 window style
    用来保留正常窗口管理能力

nativeEvent / QAbstractNativeEventFilter
    用来处理 WM_NCCALCSIZE、WM_NCHITTEST、WM_GETMINMAXINFO 等消息
```

这不是纯 Qt 无边框窗口，也不是纯 Windows 原生标题栏窗口。核心是：**Qt 隐藏系统标题栏绘制，Win32 保留窗口管理语义。**

## 当前实现位置

- 主窗口：`app/ui/main_window.py`
- 自绘标题栏：`app/ui/layout/window_title_bar.py`
- 回归测试：`tests/test_main_window.py`

相关对象和方法：

- `MainWindow._apply_windows_frameless_window_style()`
- `MainWindow._handle_frameless_native_event()`
- `MainWindow._handle_nc_calc_size()`
- `MainWindow._win32_hit_test()`
- `MainWindow._handle_get_min_max_info()`
- `WindowTitleBar`
- `WindowChromeButton`

## Win32 样式规则

窗口创建后只执行一次 Win32 style 修复：

- 清除 `WS_POPUP`
- 保留或补回 `WS_CAPTION`
- 保留或补回 `WS_THICKFRAME`
- 保留或补回 `WS_SYSMENU`
- 保留或补回 `WS_MINIMIZEBOX`
- 保留或补回 `WS_MAXIMIZEBOX`
- 调用 `SetWindowPos(..., SWP_FRAMECHANGED)`

注意：

- `SetWindowLongPtr` 和 `SetWindowPos(...SWP_FRAMECHANGED...)` 不要在最大化或还原过程中反复执行。
- 反复改 window style 容易造成黑边闪烁、窗口重建、任务栏状态异常和原生按钮重绘。

## 非客户区消息规则

### WM_NCCALCSIZE

`WM_NCCALCSIZE` 在 `wParam` 为真时稳定返回 `0`。

它的职责是告诉 Windows：原生标题栏和非客户区不要绘制，整个窗口区域交给 Qt 内容绘制。

不要在这里做复杂的最大化工作区计算。最大化边界交给 `WM_GETMINMAXINFO`。

### WM_GETMINMAXINFO

`WM_GETMINMAXINFO` 用来约束最大化尺寸和最小追踪尺寸：

- 最大化不要盖住任务栏工作区。
- 自动隐藏任务栏需要保留可唤出边缘。
- 最小窗口尺寸不能小到让顶部栏、侧栏和状态栏互相挤压。

### WM_NCHITTEST

`WM_NCHITTEST` 必须使用 `msg.lParam` 里的屏幕坐标，再通过 `ScreenToClient` 转换为客户区坐标。

不要用 `QCursor.pos()` 判断命中区域。高 DPI、多屏幕、缩放比例和窗口动画期间，Qt 鼠标坐标容易和 Win32 消息坐标不一致。

命中顺序固定为：

1. 最大化按钮
2. 最小化按钮和关闭按钮
3. 四边和四角缩放区
4. 标题栏空白区
5. 普通客户区

返回值约定：

| 区域 | 返回值 | 原因 |
| --- | --- | --- |
| 最大化按钮 | `HTMAXBUTTON` | 触发 Windows 11 Snap Layout |
| 最小化按钮 | `HTCLIENT` | 继续由 Qt `clicked` 处理，避免系统绘制原生按钮态 |
| 关闭按钮 | `HTCLIENT` | 继续由 Qt `clicked` 处理，避免系统绘制原生按钮态 |
| 左右上下边缘 | `HTLEFT` / `HTRIGHT` / `HTTOP` / `HTBOTTOM` | 显示系统双箭头并执行原生缩放 |
| 四角 | `HTTOPLEFT` / `HTTOPRIGHT` / `HTBOTTOMLEFT` / `HTBOTTOMRIGHT` | 显示系统斜向双箭头 |
| 标题栏空白区 | `HTCAPTION` | 拖动、贴边吸附、双击最大化交给 Windows |
| 内容区 | `HTCLIENT` | 普通 Qt 内容交互 |

### WM_NCLBUTTONDOWN / WM_NCLBUTTONUP

最大化按钮区域返回 `HTMAXBUTTON` 后，Windows 有机会显示 Snap Layout。点击时需要兜底处理：

- `WM_NCLBUTTONDOWN + HTMAXBUTTON`：直接吞掉，避免 Windows 绘制原生按下态。
- `WM_NCLBUTTONUP + HTMAXBUTTON`：调用 `showMaximized()` / `showNormal()`。

最小化和关闭不暴露 `HTMINBUTTON` / `HTCLOSE`，仍由 Qt 信号处理。

## 最大化与全屏边界

最大化不是全屏。

主窗口最大化只能使用：

```python
showMaximized()
showNormal()
```

不要使用：

```python
showFullScreen()
setGeometry(screen.availableGeometry())
```

`showFullScreen()` 会绕开任务栏、Snap Layout、工作区和部分窗口动画语义，容易引发黑边、任务栏无法唤出、状态错乱等问题。真正全屏只属于媒体预览窗口。

## 不要做的事

- 不要让 Windows 原生标题栏和 Qt 自绘标题栏同时绘制。
- 不要把主窗口最大化做成 `showFullScreen()`。
- 不要用 `setGeometry()` 模拟最大化。
- 不要在窗口已显示后反复 `setWindowFlags()`。
- 不要在最大化和还原过程中反复 `SetWindowLongPtr()` / `SetWindowPos(SWP_FRAMECHANGED)`。
- 不要依赖 `QCursor.pos()` 做 Win32 hit-test。
- 不要给最小化和关闭按钮返回 `HTMINBUTTON` / `HTCLOSE`。
- 不要在主窗口使用 `WA_TranslucentBackground`、阴影容器或最大化状态下仍保留外层 margin / 圆角。

## 常见现象与根因

| 现象 | 优先排查 |
| --- | --- |
| 最大化按钮悬停不出现 Snap Layout | 最大化按钮是否返回 `HTMAXBUTTON` |
| 边缘没有双箭头缩放 | 是否返回 `HTLEFT` 等边缘命中；style 是否有 `WS_THICKFRAME` |
| 最大化后出现第二套系统按钮 | 是否漏用 `FramelessWindowHint`；`WM_NCCALCSIZE` 是否稳定返回 `0` |
| 最大化或还原黑边闪烁 | 是否反复改 Win32 style；是否存在透明背景、阴影或外层 margin |
| 自动隐藏任务栏无法唤出 | `WM_GETMINMAXINFO` 是否保留任务栏唤出边缘 |
| 点击最大化变成真正全屏 | 是否误用了 `showFullScreen()` |

## 验收清单

1. 鼠标悬停最大化按钮，Windows 11 Snap Layout 正常出现。
2. 鼠标悬停窗口四边和四角，出现系统双箭头缩放光标。
3. 拖动标题栏空白区域，窗口可移动并支持系统贴边吸附。
4. 双击标题栏空白区域，窗口最大化或还原。
5. 最大化不会盖住任务栏。
6. 自动隐藏任务栏仍能从屏幕边缘唤出。
7. 最大化和还原时不出现黑边闪烁。
8. 最大化后不会冒出第二套 Windows 原生按钮。
9. 媒体预览全屏不影响主窗口最大化语义。

## 推荐测试

```powershell
python -m py_compile app\ui\main_window.py app\ui\layout\window_title_bar.py
python -m pytest tests/test_main_window.py -q
python -m pytest tests/test_unified_frontend_contract.py -q
```

手工验收必须在真实 Windows 桌面环境执行，因为 Snap Layout、任务栏自动隐藏和 DWM 动画都不是普通单元测试能完整模拟的。
