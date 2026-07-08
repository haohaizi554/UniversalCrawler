# GUI 主题切换黑屏事故复盘（2026-07）

## 现象

主 GUI 频繁切换深浅主题后，窗口标题栏仍然存在，但主界面的 TopBar、左侧导航、页面栈和底部状态栏消失，只剩深色背景以及中间一块黑色媒体预览区域。主题按钮图标切换很快，页面实际重绘明显滞后，继续快速点击会扩大状态错位，最终看起来像主界面被清空。

## 直接影响

- 用户无法继续从主界面启动、停止、切换页面或查看状态。
- 视觉上像应用卡死，但 Qt 事件循环和标题栏仍在。
- 反复修按钮图标、局部 stylesheet 或单个控件样式无法解决根因，容易制造“图标正确但页面仍黑”的假修复。

## 根因

这次事故不是单个主题按钮问题，而是主题切换链路同时踩到了几个 Shell 状态边界：

1. `MainWindow.__init__` 在 `_build_ui()` 之前就应用主题，导致部分根容器和 shell 组件还不存在时先走了一轮样式和 palette 更新。
2. 主题切换为了减少闪烁冻结了过大的容器范围，`window_root` / shell 父级一旦在异常、排队或延迟刷新中没有及时恢复 `updatesEnabled`，后续控件实际存在但不再重绘。
3. 快速连续点击时，按钮图标先变、页面主题后变，前端 snapshot 刷新、settings 同步和 Qt stylesheet 重绘互相穿插，形成“按钮状态”和“页面完成状态”不一致。
4. 只恢复 TopBar、Sidebar、StatusBar 本体还不够；它们外层的 `control_island`、`status_island`、`PageStack` 或 `window_root` 被隐藏/冻结时，子控件仍然不可见。
5. 媒体预览全屏残留状态会让 shell 恢复逻辑误判当前仍在全屏/预览模式，造成中间黑色预览区域盖住主要界面的错觉。

## 修复原则

- 主题应用必须发生在 UI 构建完成之后；初始化早期只允许记录配置值，不允许触碰未构建的 shell。
- 主题切换默认不冻结 `window_root`。如果确实需要临时冻结，只能冻结已可见的 `app_shell`，并且必须在 `finally` 中恢复。
- 主题按钮 busy 状态不能禁用按钮；快速点击应按 latest-state-wins 合并到最后一次用户意图。
- `_apply_theme_stylesheet()` 默认不触发完整前端 snapshot 刷新，只做 Qt 样式和必要设置页同步；前端刷新必须按明确 section 进入 worker。
- 每次主题应用、主题过渡完成、窗口 show、前端 snapshot 完成后，都要检查并恢复 shell chrome 可见性。
- shell 可见性检查不能只看子控件；必须覆盖 `window_root`、标题栏、`app_shell`、`control_island`、TopBar、Sidebar、PageStack、`status_island` 和 StatusBar。
- 媒体预览全屏状态必须单独识别和清理 stale fullscreen，不允许和主窗口主题状态混在一起判断。

## 当前落地

- `app/ui/main_window.py` 增加 `_debug_shell_visibility(reason)`，用于记录 shell 关键容器的 exists / visible / hidden / updatesEnabled / geometry。
- `app/ui/main_window.py` 增加 `_ensure_shell_chrome_visible(reason=...)` 和 `_repair_black_shell_if_needed(reason)`，在主题应用、主题完成、showEvent 和前端 snapshot 完成后兜底修复。
- `_apply_theme_stylesheet(..., freeze_updates=False)` 默认不冻结更新；即使手动开启，也不再冻结 `window_root`。
- `_commit_theme_toggle()` 使用 `refresh_frontend_snapshot=False`、`update_theme_icon=False`、`freeze_updates=False`，避免按钮、页面和前端快照三条链路互相打架。
- `_finish_theme_transition()` 先处理排队主题，再释放 busy 状态；如果还有下一次切换，保持 busy 并延迟一帧执行下一次。
- `TopBarWidget.set_theme_button_busy()` 保持主题按钮可点击，只用属性和 tooltip 表示忙碌。
- 增加回归测试，覆盖主题切换不冻结 `window_root`、黑屏 shell 修复、主题 busy 按钮仍可点击和快速点击合并。

## 以后禁止

- 禁止在 UI 构建前调用主题应用或全局 stylesheet 热加载。
- 禁止为了“少闪一下”冻结 `window_root` 或不可见父容器。
- 禁止把主题按钮图标变化当作主题切换完成信号。
- 禁止只修可见子控件，不检查承载它们的 island / stack / root 容器。
- 禁止在主题切换热路径里直接做完整前端 snapshot 或同步配置落盘。

## 必测清单

1. 普通点击深浅主题切换，TopBar、左侧导航、页面栈、底部状态栏不消失。
2. 1 秒内连续点击主题按钮十几次，最终主题等于最后一次用户意图，按钮仍可点，主界面不黑屏。
3. 在下载队列、日志中心、设置页、已完成页和媒体预览页分别切换主题。
4. 媒体预览进入/退出全屏后再切换主题，不留下黑色预览区域盖住 shell。
5. 系统跟随主题触发 palette change 时，也走同样的 shell 恢复链路。
6. 运行 `tests/test_main_window.py` 和 `tests/test_unified_frontend_contract.py -k "theme or top_bar"`。
