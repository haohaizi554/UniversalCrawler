# 2026-06-30 Qt 前端工程审查

## 参考结论

本次审查覆盖 Qt Model/View、Qt 线程与 QObject、`QWindow.startSystemMove()` / `startSystemResize()`、Windows 非客户区消息、DWM 自定义窗口框架以及成熟无边框 Qt 项目的实现经验。

Windows 自绘标题栏和原生窗口行为的最新权威说明见：

- [Windows 自绘标题栏与原生窗口行为](../engineering/windows-native-chrome-hit-test.md)

## 当前经验

1. Windows 自绘标题栏属于平台适配层，不是普通页面样式问题；需要同时处理 Qt frameless、Win32 style、`WM_NCCALCSIZE`、`WM_NCHITTEST` 和 `WM_GETMINMAXINFO`。
2. 主窗口最大化只能使用 `showMaximized()` / `showNormal()`，真正全屏只属于媒体预览窗口。
3. 高频页面只渲染用户可见部分，隐藏页面不应在日志或下载事件下反复翻译、过滤和重绘。
4. 日志中心需要追加和环形缓冲路径，不能每次渲染都全量过滤。
5. 后台线程调用 Qt 必须有显式 GUI 线程桥，优先使用 QObject 信号和 queued connection。
6. 无边框缩放在 Windows 下优先走原生 `WM_NCHITTEST`，非 Windows 或异常环境再用 `startSystemResize()` 兜底。
7. 翻译、日志过滤和分类计数都属于渲染预算，必须合并计算并减少重复重建。
8. 悬浮光标也要跟随缩放边缘，否则用户按下前看不到正确反馈。
9. 窗口几何属于外壳职责，不应由页面内容决定；恢复旧几何时必须夹回当前屏幕工作区。
10. 侧边栏计数是徽标，不是按钮，应使用紧凑尺寸。
11. 最小窗口尺寸是布局契约，不能小到让顶部栏、侧栏和内容卡片互相重叠。
12. 自绘标题栏的点击区域和图标大小要分开控制，保留可点区域的同时压缩视觉体积。

## 已完成项

- 主窗口建立了 Windows 原生命中测试路径。
- 主窗口最大化从模拟几何切换为原生最大化。
- 恢复几何会夹回屏幕工作区，并限制 Win32 最大跟踪尺寸。
- 侧边栏计数徽标改为紧凑尺寸。
- 隐藏页面翻译延迟处理，当前页立即更新。
- 日志中心跳过未变化渲染，并单次计算分类计数。
- 运行时 GUI 设置通过 Qt queued invoker 分发。
- EventBus 记录慢同步 handler，方便观察 fan-out 卡顿。

## 仍需跟踪

- EventBus 仍是同步分发；若某个 handler 被证明慢，应迁移到异步或排队适配层。
- `SnapshotTableModel` 对大数据量仍可能有全行签名扫描成本，后续可按 id 接收 section delta。
- Windows 自绘标题栏改动必须同时跑窗口单测和真实桌面手工验收，Snap Layout 与任务栏自动隐藏不能只靠单元测试判断。

## 未来 UI 改动规则

如果改动涉及平台特定 Qt 行为、高频渲染、线程边界、Model/View 性能或可测试的用户体验坏点，应在本目录或 `docs/engineering/` 补充记录。
