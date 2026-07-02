# 配置中心主题闪屏与入口崩溃修复

## 背景

2026-06-28 的 GUI 验收中，配置中心暴露出一组相关问题：下拉框与背景区分度不足，部分输入框没有跟随主题色，设置页切换深浅主题时偶发黑屏，语言切换只影响设置页局部，直接运行 `main.py` 还可能以 `-805306369 (0xCFFFFFFF)` 异常退出。

## 现象

- 平台和数量下拉框选中态仍偏蓝，未跟随用户配置的主题色。
- Qt 原生下拉弹层会额外绘制黑色 focus rectangle，导致选中行看起来像套了一个黑框。
- 顶部爬取数量和配置中心平台页数量选项来自两套常量，导致同一平台当前值和选项列表不一致。
- 深浅主题切换后，顶部按钮和设置页 Light/Dark 控件偶发不同步。
- 设置页有时保持空白，因为快照签名没有变化，渲染缓存跳过了重建。
- WebUI 修改语言后，顶栏、侧栏和状态栏仍可能保留旧语言。
- 无参数入口仍保持原设计：展示 TUI 菜单或 Qt 模式选择后备；不能为了规避某个宿主的 EOF 行为而自动改派 GUI。
- `app/core/downloaders/m3u8.py` 中可选依赖导入被放进另一个 import tuple，触发启动期 `SyntaxError`。

## 根因

1. Qt stylesheet 不完整支持浏览器 CSS。`outline`、`line-height`、`opacity`、小数像素和 `data:image/svg+xml` 都可能让 Qt 报 `Could not parse application stylesheet`，进而造成部分控件主题样式失效。
2. 设置页的渲染缓存只比较 snapshot signature，没有检测当前 view 是否还包含有效控件。页面隐藏、主题切换或懒加载恢复后，空 view 会被误判为“无需渲染”。
3. 主题切换时同步刷新配置快照和重绘发生在同一轮调用里，容易放大 repaint 空窗，表现为偶发黑屏或闪屏。
4. WebUI 的语言状态没有作为全局 shell 渲染签名的一部分，导致设置外的区域不会被强制重绘。
5. 入口调度只看命令行参数，未区分“看起来有 tty”但 stdin/stdout 不适合交互的宿主。
6. 顶部数量框维护了独立预设 `(10, 20, 50, max)`，配置中心平台页使用后端 `count_options`，两边天然会漂移。

## 修复

- GUI 全局样式改用 `theme_colors()`，让主题色覆盖 QComboBox、QLineEdit、QSpinBox、弹层选中行和顶部/侧栏关键输入控件。
- 移除 Qt 不支持的 QSS 属性，checkbox indicator 改用文件 URL 资源，保证 Qt 原生应用 stylesheet 时不再报解析错误。
- 下拉框 popup 使用无 focus rectangle 的 delegate，打开前同步 view 当前行，避免黑框和选中行偏移。
- 顶部数量框改为读取 `platform_count_options()` / `platform_page_count_options()`；`AppShell.render()` 在 `settings_snapshot` 变化后按当前平台行热加载顶部数量值和选项。
- `SettingsPage.render()` 增加空视图修复；`showEvent()` 和重复进入当前分组时都会检查 view 是否需要重建。
- 主题切换不再冻结整个窗口，也不再同步强刷所有前端状态；样式先即时应用，快照刷新用 `QTimer.singleShot(0, ...)` 延后到下一轮事件循环。切换前会主动关闭 QComboBox popup 和临时 top-level popup，避免留下空白小浮窗。
- `AppShell.apply_language()` 覆盖所有已构建页面；WebUI 语言更新会清空 render signature 并重绘顶栏、侧栏、状态栏和配置中心。
- 按用户要求恢复 `entry.dispatcher` 无参数入口行为：继续通过 `prompt_mode_menu()` 选择模式，不自动把 EOF 或非 TTY 场景改派到 GUI。
- `m3u8.py` 的 Playwright 可选导入移出 import tuple，避免启动期语法错误。

## 验证

- 精准回归：`python -m pytest tests/test_main_entry.py tests/test_ui_dialogs.py tests/test_unified_frontend_contract.py tests/test_main_window.py tests/test_frontend_state_service.py -q`，结果 `196 passed`。
- 全量回归：`python -m pytest -q --timeout=90 --timeout-method=thread --session-timeout=900`，结果 `1448 passed, 1 skipped`。
- 入口恢复验证：无参数 `main.py` 在 stdin EOF 场景恢复为菜单取消并正常退出，不再自动进入 GUI。
- GUI 启动验证：`"D:\APP\python 3.13.2\python.exe" D:\desktop\project\UniversalCrawlerProplus\main.py --mode gui` 运行 8 秒后仍保持运行，仅输出 Qt multimedia FFmpeg 信息，无 QSS 解析告警和启动期异常退出。
- 视觉验证：浅色/深色配置中心截图均能稳定显示设置页内容；下拉框与输入框边框、focus 和选中行使用配置主题色；顶部爬取数量与平台页当前平台值一致；代理入口显示“自定义 HTTP/SOCKS5 端点”且保留完整预设选项。

## 全量测试补充发现

全量测试期间还暴露了一个隐藏挂起点：`DownloadManagerCore._rebuild_slot_semaphore()` 旧实现通过 `while semaphore.acquire(blocking=False)` 回收旧信号量剩余 token。真实 `threading.BoundedSemaphore` 会在 token 为空时返回 `False`，但测试替身或异常包装对象可能持续返回 truthy 值，导致无限循环。

修复方式是最多只按旧并发容量 `old_value` 尝试回收 token：

```python
for _ in range(max(0, old_value)):
    if not self.slot_semaphore.acquire(blocking=False):
        break
    available_tokens += 1
```

对应测试也改为使用真实 `BoundedSemaphore` 验证“扩容后保留已占用槽位、只增加可用容量”，不再用无边界 Mock 统计 release 次数。

## 经验

- Qt QSS 不是浏览器 CSS，设计系统要以 Qt 实际解析结果为准；对生产 GUI，最好把 stylesheet parse warning 纳入回归测试。
- Qt popup 是独立临时窗口，主题切换前要先关闭弹层；否则旧 popup 可能在换肤后残留为空白小窗。
- 渲染缓存不能只缓存数据签名，还要验证当前 view 的结构完整性。
- 主题热加载应拆成“立即换肤”和“下一轮刷新数据”，避免在同一调用栈里重排、重绘和重建页面。
- 多入口程序的无参数策略属于产品入口契约，不能为了解决 GUI 崩溃而擅自改派；GUI 稳定性应在 GUI 生命周期、主题和弹层管理里修。
- 所有“drain until false”的并发基础设施代码都需要有硬上限；生产代码不能假设替身对象或未来封装永远完全符合标准库语义。

## 2026-06-28 追加：主题切换后一帧空白

后续复验发现，配置中心主题切换时控件树没有丢失，`detail_layout` 和导航按钮都仍然完整，但窗口截图会短暂呈现为空白面板。这不是数据热加载失败，而是 Qt 样式切换、popup 关闭和页面刷新之间存在一帧 repaint 空窗。

修复方式是把主题切换后的前端刷新从延后到下一轮事件改为同步收口，并在刷新后调用 `_finalize_theme_repaint()`：先修复可能为空的 settings view，再对 settings 页、侧栏分组面板、详情面板和 app shell 做一次轻量 `update()/repaint()`。复验脚本连续切换 6 次深浅主题且在每次切换后立刻截图，结果为 `visible_popup_count=0`，设置页内容保持完整。

## 2026-06-28 追加：下拉框滚动条与黑框回归

新一轮截图显示，短列表下拉框被压成带滚动条的弹层，当前项还出现系统黑框或灰框。根因有两个：第一，popup 高度使用 Qt/QSS 放大的 `sizeHintForRow()`，导致内容高度估算偏大或偏小；第二，`QComboBox` 会把自己的 delegate 覆盖到内部 view 上，如果只调用 `view.setItemDelegate()` 且不保留 Python delegate 引用，去焦点框逻辑会被默认 delegate 悄悄替换。

修复方式是把 `polish_combo_popup()` 改成短列表全量展开：12 项以内强制 `ScrollBarAlwaysOff`，按固定主题行高计算弹层高度；同时在 combo 本体和 view 上都设置 `NoFocusItemDelegate`，并把 delegate 引用挂到对象属性上。选中行由 delegate 整行绘制，QSS 的 `item:selected` 背景改为透明，避免 Qt 再绘制一层文本区域色块。

## 2026-06-28 追加：隐藏 top-level 控件导致主题切换越来越慢

后续压力测试发现，空白小窗消失后仍有 3 秒级事件间隔。分段计时显示页面切换只需几十到一百多毫秒，真正的卡顿集中在主题切换；继续检查 `QApplication.topLevelWidgets()` 后发现，设置页多次重建分组时留下了大量隐藏的 `SettingsNavButton`、`SettingsFormCard`、`SettingsDetailHeader` 顶层控件。

根因是清理旧布局时执行了 `widget.setParent(None)` 再 `deleteLater()`。在 Qt 处理 deferred delete 之前，这些控件会短暂成为无父 top-level。主题切换又会遍历 top-level 套根样式，结果越切越慢，也提高了空白小窗风险。

修复方式：

- 设置页清理旧导航和详情控件时只 `hide()` + `deleteLater()`，不再 `setParent(None)`。
- `apply_application_theme()` 只给真实 `QMainWindow` / `QDialog` 顶层窗口应用根样式，忽略孤儿控件。
- 字体探测和 `QApplication.setFont()` 增加缓存，字体/缩放没有变化时不触发全局 FontChange。
- GUI / WebUI 主题写入改用 `ConfigManager.set_many()`，把 `theme` 与 `dark_theme` 合成一次保存和一次 `config.changed`，避免快速切换时误触发 storm warning。
- 主窗口和设置页目录选择器统一为非原生、非模态 `QFileDialog`，不再调用阻塞静态 `getExistingDirectory()`。

复验结果：32 次混合操作（主题切换、队列页、设置页不同分组）最大总耗时约 416-438ms；可见 top-level 只剩 `MainWindow`；隐藏 `Settings*` 顶层控件数量为 0；相关回归测试覆盖目录选择器、设置页清理、主题根过滤和批量配置事件。

## 2026-06-29 追加：组合框内联样式在主题切换后滞留

用户截图显示日志中心在深色主题下仍出现白底下拉框。根因不是全局 palette 没切换，而是 `ThemedComboBox` 在构造时写入了一份基于当时主题的内联 QSS；如果控件先在浅色主题下创建，再热切到深色主题，全局 stylesheet 与 palette 已经更新，但这些 combo 本体仍保留浅色 `background`。

修复方式是让 `apply_themed_combo_box()` 标记托管 combo，并记录该控件是否由共享样式接管本体外观。`AppShell.apply_theme()` 和日志页视觉刷新会调用 `refresh_themed_combo_boxes()`，对托管 combo 重新生成当前主题下的本体 QSS 与 popup 样式；设置页 `SettingsComboBox` 显式标记为只共享 popup，不覆盖配置中心自己的本体样式。

同时将侧栏平台选择框固定为更紧凑的 176px，并给常态边框使用主题色；popup 最大宽度随控件锁定，避免短平台名下拉出现过宽空白。回归测试新增“浅色构造后热切深色”的日志 combo 检查，以及平台下拉宽度和主题边框断言。
