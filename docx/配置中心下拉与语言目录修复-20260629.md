# 配置中心下拉与语言目录修复

日期：2026-06-29

## 现象

- GUI 下拉框弹层偶发保留原生边框、滚动条或白色背景。
- 设置页更新字体、主题、语言时会触发不必要的全局页面翻译和顶部数量框重配，体感卡顿并可能出现短暂白屏。
- 日志页筛选下拉未完全进入主题化控件路径。
- GUI 与 WebUI 语言文本存在双份维护风险。

## 根因

- `QComboBox` 弹层样式分散在多个页面中，部分控件只在弹层打开后修正 view，控件本体仍可能走原生或全局默认样式。
- `AppShell.apply_language(force=True)` 在语言未变化时仍遍历所有页面翻译，扩大了设置热加载的重绘范围。
- WebUI 只有内置 fallback 字典，没有从共享语言目录加载。
- 全局 QSS / palette 切换时没有批量冻结顶层窗口更新，容易把中间空白帧绘制出来。

## 修复

- 抽出 `ThemedComboBox` 和统一 `polish_combo_popup()` 契约，补齐 popup 无边框、无滚动条、主题色和 delegate 行为。
- 设置页保留自身控件外观，但复用统一 popup 行为。
- 日志页筛选和分页下拉改用 `ThemedComboBox`。
- 同语言 settings snapshot 更新直接短路，不再触发 shell/page 全量翻译，也不重配顶部数量框。
- `apply_application_theme()` 在样式表切换期间冻结并恢复顶层窗口更新。
- GUI 使用 `app/ui/i18n/*.json`，WebUI 通过 `/api/i18n/{language}` 复用同一份目录。

## 回归覆盖

- `tests/test_unified_frontend_contract.py`
  - 下拉弹层无滚动条、无原生边框、共享主题契约。
  - 同语言设置刷新不重绘顶部控件、不触发全量翻译。
  - 语言切换覆盖日志页、下载页 model/view 表头。
  - MissAV 自定义代理显示端口并提交完整 endpoint。
  - WebUI 从共享 i18n API 加载语言目录。
- `tests/test_fastapi_endpoints.py`
  - `/api/i18n/en-US` 返回共享语言目录。
  - `/api/i18n/zh-CN` 返回空目录，保持源语言直出。

## 教训

设置热加载不能只看“数据是否更新”，还要控制刷新半径。语言、主题、字体这类全局设置尤其需要区分“真实语义变化”和“同语言/同主题的设置快照刷新”，否则很容易把小改动放大成全窗口重绘。

## 2026-06-29 追加：截图复验中的弹层几何回归

复验截图里还暴露出一类更隐蔽的问题：短列表下拉表面上隐藏了滚动条，但内部 view 仍可能保留可滚动范围，滚轮后会把底部空白拖出来；部分调用方传入了更适合当前控件的 popup 行高，但 `PolishedComboBox.showPopup()` 重新 polish 时没有保留这些参数，弹层几何可能回退到默认值。

本轮修复把 `comboPopupRowHeight` 和 `comboPopupVisibleRows` 保存到 `QComboBox` 属性，并在每次 `showPopup()` 前后继续沿用。全展开短列表会把 `verticalScrollBar().maximum()` 锁为 `0`，事件过滤器拦截 wheel 后重置滚动值，避免“看不见滚动条但还能滚”的空白弹层。回归测试同步补充了平台下拉与代理下拉的 `comboPopupFullExpand` 和滚动范围断言。

同一轮还修复了截图中的平台代理显示问题：代理预设 label 不再附带端口，`V2Ray / Qv2ray`、`Clash Verge` 等保持为应用名；只有“自定义”走右侧端口/端点输入框。这样配置语义保持为“左侧选择预设，右侧输入自定义值”，不会把预设名、端口和 URL 混成一个可编辑字符串。

验证命令：

```bash
python -m pytest tests/test_unified_frontend_contract.py -q
python -m pytest -q
```
