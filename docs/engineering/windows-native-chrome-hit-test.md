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
- 共享弹窗基类：`app/ui/dialogs/chromed_dialog.py`
- 共享窗口框架：`app/ui/layout/window_chrome.py`
- 共享窗口控制器：`app/ui/layout/window_chrome_controller.py`
- 启动模式选择器：`entry/mode_selection_ui.py`
- Web 端口冲突弹窗：`entry/web_port_dialog.py`
- 发布构建器：`packaging/release_tool/panel.py`
- 回归测试：`tests/unit/app/ui/test_main_window.py`
- 架构守卫：`tests/architecture/test_window_chrome_contract.py`

相关对象和方法：

- `MainWindow._apply_windows_frameless_window_style()`
- `MainWindow._handle_frameless_native_event()`
- `MainWindow._handle_nc_calc_size()`
- `MainWindow._win32_hit_test()`
- `MainWindow._handle_get_min_max_info()`
- `WindowTitleBar`
- `WindowChromeButton`
- `ChromedDialog`
- `WindowChromeFrame`
- `FramelessWindowChromeController`

## 所有顶层窗口的统一接入契约

本节不是只针对主 GUI 或发布构建器。所有现有和未来由应用拥有的顶层窗口都必须遵守同一套
窗口 chrome 契约：

- 普通弹窗继承 `ChromedDialog`，不得直接构造裸 `QDialog()`。
- 独立 `QMainWindow` / 顶层 `QWidget` 使用 `WindowChromeFrame` 时，必须同时创建
  `FramelessWindowChromeController`。
- 标题栏最小化、最大化/还原和关闭信号只能由
  `FramelessWindowChromeController.bind_title_bar_controls()` 绑定；宿主窗口不得直接
  `.connect()` 这些信号。
- 特殊窗口可以把关闭动作传为 `reject`，或把主 GUI 的“媒体全屏退出”逻辑作为
  `toggle_maximized` 回调注入控制器，但标题栏仍只能连接到控制器，不能绕过控制器直连回调。
- `showEvent` 调用 `install()` 和 `on_show_event()`；关闭/销毁路径调用 `uninstall()`；
  `nativeEvent`、`mousePressEvent` 和 `eventFilter` 分别转发给控制器。
- 真正无标题栏的媒体全屏画布和操作系统原生文件选择器不属于窗口 chrome 宿主，不伪造
  最大化/还原按钮。

独立窗口的标准接入形态如下：

```python
self.chrome_frame = WindowChromeFrame(...)
self.window_title_bar = self.chrome_frame.title_bar
self._window_chrome_controller = FramelessWindowChromeController(
    self,
    title_bar_getter=lambda: self.window_title_bar,
    resizable=True,
    minimizable=True,
    maximizable=True,
)
self._window_chrome_controller.set_window_flags()
self._window_chrome_controller.bind_title_bar_controls()
```

禁止以下写法：

```python
self.window_title_bar.maximize_restore_requested.connect(self._toggle_maximized)

def _toggle_maximized(self):
    if self.isMaximized():
        self.showNormal()
    else:
        self.showMaximized()
```

禁止原因是：无边框窗口在 Windows 最大化、Snap、还原动画和打包运行环境中，Qt 的
`WindowMaximized` / `isMaximized()` 可能晚于真实 HWND 状态。直接连接会绕过控制器的
`IsZoomed(hwnd)` 真值和 `ShowWindow(SW_MAXIMIZE/SW_RESTORE)` 动作，导致功能看似正常，
但最大化/还原图标显示相反。

`tests/architecture/test_window_chrome_contract.py` 会扫描生产窗口：遗漏完整控制器生命周期、
手工连接标题栏信号或直接构造裸 `QDialog()` 都会使 CI 失败。该守卫是未来新增窗口的强制
门禁，不得为新窗口添加路径白名单来规避。

## 启动阶段与独立弹窗的标题栏契约

启动模式选择器虽然出现在主窗口创建之前，但它仍然是应用的顶层 GUI 窗口，必须遵守与主窗口一致的标题栏和主题契约。当前调用链为：

```text
entry.dispatcher._prompt_mode_with_qt()
    -> entry.mode_selection_ui._prompt_mode_with_qt()
    -> ChromedDialog
    -> WindowChromeFrame + FramelessWindowChromeController
```

`entry.dispatcher` 只保留延迟导入和薄委托，实际界面只有 `entry.mode_selection_ui` 一份实现。这样既不会让 CLI 和无 Qt 启动路径提前加载 GUI 依赖，也不会出现 dispatcher 与组件各维护一套弹窗的漂移。

### 2026-07-14 启动模式弹窗主题事故

现象：Windows 处于深色系统主题、应用内容使用浅色主题时，启动模式弹窗出现黑色原生标题栏和白色内容区，标题栏也不受应用主题切换控制。

根因不是 Windows 主题 API 本身，而是实际启动路径直接创建了原始 `QDialog`，内容区又使用硬编码浅色 QSS。Windows 原生标题栏跟随操作系统主题，Qt 内容区跟随另一套固定样式，两套真值天然可能冲突。同时，已经拆出的 `entry/mode_selection_ui.py` 当时没有接入 dispatcher 的真实调用链，因此只修改组件文件不会影响用户实际看到的窗口。

修复后，启动模式弹窗统一继承 `ChromedDialog`，由 `resolve_is_dark_theme()` 获取主题真值、由 `theme_colors()` 提供颜色，并同时设置窗口图标和 `WindowChromeFrame` 图标。禁止再为同一入口复制原始 `QDialog` 实现。

必须遵守以下规则：

1. 主窗口之外的顶层弹窗，包括主窗口创建前的启动弹窗，默认使用 `ChromedDialog`；确实需要系统原生标题栏时，必须在代码和本文中说明原因。
2. 不得把 Windows 原生标题栏与硬编码的 Qt 内容主题组合使用。
3. 主题真值统一来自 `resolve_is_dark_theme()`，颜色统一来自 `theme_colors()` 或项目设计令牌，不得在弹窗中另建明暗主题判断。
4. 自绘标题栏弹窗设置图标时，必须同时更新 `QWidget.windowIcon()` 和共享 `WindowChromeFrame` 的图标。
5. 启动入口继续使用延迟导入，确保 CLI、测试和缺少 PyQt6 的环境不会因导入 GUI 模块而失败。
6. dispatcher 只负责选择和调度，弹窗结构、样式和交互只能在独立 UI 组件中维护一份。

该问题的回归检查包括：

- 浅色和深色模式下，标题栏、内容区、边框、按钮文字均来自同一主题，不能出现黑白割裂。
- 关闭按钮、标题栏拖动、窗口缩放、数字快捷键、取消和模式选择均可正常使用。
- 自动测试应验证 dispatcher 委托到独立组件，并验证组件使用 `ChromedDialog` 和主题令牌，而不是直接构造原始 `QDialog`。
- 真实 Windows 桌面环境至少各验证一次浅色和深色主题；离屏渲染截图只能作为布局和配色的补充检查。

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
- `WM_NCLBUTTONUP + HTMAXBUTTON`：进入控制器统一切换入口；Windows 下调用
  `ShowWindow(hwnd, SW_MAXIMIZE/SW_RESTORE)`。

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

## 最大化状态真值

自绘标题栏的最大化/还原按钮状态必须来自真实窗口状态，不能来自“刚刚请求过最大化”的缓存标记。

规则：

- `_native_maximize_requested` 只能作为 UI 辅助字段，不能作为 `_is_effectively_maximized()` 的持久真值。
- 不要把点击后的 pending 目标态放进 `_is_effectively_maximized()`。这个函数同时被标题栏按钮、最大化/还原动作判断、resize hit-test 使用，混入临时态会污染窗口缩放。
- Windows 下真实最大化状态只信 Win32 `IsZoomed(hwnd)`。如果 `IsZoomed(hwnd)` 是 `False`，即使 Qt 仍残留 `WindowMaximized`，也必须按非最大化处理。
- Windows 下最大化/还原动作优先使用 Win32 `ShowWindow(hwnd, SW_MAXIMIZE/SW_RESTORE)`，不要依赖 Qt 在陈旧 `WindowMaximized` 标记下重新执行 `showMaximized()` / `showNormal()`。
- 点击按钮后可以临时把按钮画成目标图标，但这个临时反馈不能反写到 `_is_effectively_maximized()`；后续同步只能用真实窗口状态覆盖。
- 非 Windows 或取不到 HWND 时，才退回 Qt 的 `windowState()` / `isMaximized()`。

经验教训：不要把“请求过最大化”“Win32 当前回报”“Qt 当前回报”“几何贴合工作区”混成同一种状态。临时按钮反馈只负责视觉反馈；真实状态和 resize/hit-test 必须只看真实窗口状态。

## 不要做的事

- 不要让 Windows 原生标题栏和 Qt 自绘标题栏同时绘制。
- 不要让任何宿主窗口直接连接共享标题栏的最小化、最大化/还原或关闭信号。
- 不要在应用代码中直接构造裸 `QDialog()`；普通弹窗统一继承 `ChromedDialog`。
- 不要让启动弹窗或独立工具窗口绕过 `ChromedDialog` 后再用硬编码 QSS 模拟应用主题。
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
python -m pytest tests/architecture/test_window_chrome_contract.py -q
python -m pytest tests/unit/app/ui/test_main_window.py -q
python -m pytest tests/release/packaging/test_release_builder_panel.py -q
python -m pytest tests/contract/frontend/test_unified_frontend.py -q
```

测试不得只修改按钮内部 `_maximized` 布尔值后断言图标。至少要验证
“标题栏信号 -> 共享控制器 -> Win32 动作 -> `IsZoomed` 真值 -> 图标”的完整链路。
手工验收必须在真实 Windows 桌面环境执行，因为 Snap Layout、任务栏自动隐藏和 DWM 动画
都不是普通单元测试能完整模拟的。
