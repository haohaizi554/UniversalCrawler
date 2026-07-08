# 配置说明

## 配置入口

项目配置统一由 `app/config/settings.py` 管理，运行时通常读取根目录或用户目录中的 `config.json`。桌面 GUI 与 WebUI 不直接拼装各自的设置模型，而是通过 `FrontendStateService.settings_snapshot()` 读取同一份快照。

## 热加载链路

- GUI：`SettingsPage.setting_changed(section, key, value)` → `MainWindow._update_basic_setting()` → `FrontendStateService.handle_action()`。
- WebUI：`updateSetting(section, key, value)` → `frontendAction("update_setting", payload)`。
- 服务层：`ConfigManager.set()` 负责类型收敛、枚举校验与落盘；成功后清空静态快照缓存并记录 `settings.update` 事件。
- 配置落盘：`ConfigManager.save()` 使用同目录临时文件加原子替换；Windows 上若 `config.json` 被 GUI/Web 进程或安全扫描短暂占用，会进行短重试并清理 `.tmp`，避免设置热加载过程中偶发保存失败。
- 刷新范围：`settings.update` 会刷新 `settings_snapshot`、`download_options` 与 `app_status`，避免设置页、下载控件和状态栏出现不同步。

## 前端设置约束

- 除下载目录和 MissAV 自定义代理端点外，GUI / WebUI 设置项必须使用下拉选项、开关或分段按钮，不允许使用可手输数字框。
- 下载、日志、平台数量、主题、语言、主题色、字号和缩放选项必须来自 `FrontendStateService.settings_snapshot()` 中的 `_options` / `count_options` / `proxy_options`。
- 平台默认数量必须在选项标签中带单位。短视频类平台显示“20 个视频（推荐）”，Bilibili 等分页平台显示“1 页（推荐）”，避免只显示孤立数字或混淆页数/视频数。
- 顶部爬取数量框必须与配置中心平台设置共用同一组 `count_options`，并在当前平台的 `settings_snapshot` 变化后热加载当前值；不能在顶部维护另一套硬编码数量预设。
- `download.speed_limit_kb=0` 是不限速哨兵值；界面必须展示为“无限制”，不要暴露 `0 KB/s`。
- 认证状态必须读取 `auth` 分组配置的 Cookie 文件，并按平台关键 Cookie 判断，不允许写死平台认证状态。
- MissAV 代理预设必须同时维护 `proxy_app` 与实际运行用的 `proxy_url`。GUI/WebUI 右侧保持预设下拉；只有选择“自定义”后才显示单独端点输入框，端点写入 `proxy_url`，下拉状态保持 `proxy_app=自定义`，其它代理预设不允许任意键入。预设下拉只显示应用名，不在 label 中重复端口，避免和右侧端口/端点输入框冲突。
- 主题色必须覆盖控件高亮、下拉框 focus/open 状态和数据行选中背景；GUI 与 WebUI 都不能把选中行固定成单一蓝色。顶部主题按钮必须同步外观页 Light/Dark 控件，不能只改图标或全局样式。
- GUI 下拉框弹层不能保留 Qt 原生黑色 focus rectangle；打开 popup 前必须同步 view 当前行，保证输入框当前值和弹层选中行一致。
- GUI 下拉框短列表必须完整展开；12 项以内不显示水平或垂直滚动条，内部 `verticalScrollBar().maximum()` 必须为 `0`，不允许通过隐藏滚动条或偏小 `maximumHeight` 制造可滚动空白。自定义 delegate 必须设置在 `QComboBox` 本体和内部 view 上，并保留 Python 引用，防止 Qt 恢复默认 delegate 后重新出现黑框。调用方传入的 popup 行高和可见行数必须保存到 combo 属性，避免 `showPopup()` 重新 polish 时回退到默认尺寸。
- GUI 深浅主题热切换必须先关闭临时 popup，但不能在热路径里触发完整前端 snapshot 或整页重绘。主题按钮先更新预览图标，实际样式按 latest-state-wins 合并到最后一次用户意图；设置页只同步必要的 Light/Dark 分段控件和局部主题色。
- GUI 主题切换必须在 UI 构建完成后执行，不能在 `MainWindow._build_ui()` 前应用全局 stylesheet。不得冻结 `window_root`；如确需短暂冻结，只允许冻结已可见的 `app_shell`，并必须在 `finally` 中恢复 `updatesEnabled`。
- 主题切换后必须检查并修复 shell chrome：`window_root`、标题栏、`app_shell`、`control_island`、TopBar、Sidebar、PageStack、`status_island` 和 StatusBar 都要可见且可重绘。只检查子控件会漏掉父级 island 或 stack 被隐藏的黑屏事故。
- GUI 全局 QSS 必须能被 Qt 原生解析，不能使用 Qt 不支持的 `outline`、`line-height`、`opacity`、小数像素或 `data:image/svg+xml`。主题热加载前后不允许出现 `Could not parse application stylesheet`，否则会造成下拉框、输入框或深浅主题状态局部失效。
- 语言和字号属于全局外观配置。语言切换需要覆盖 GUI/WebUI 顶栏、侧栏、状态栏和配置中心；字号切换需要影响配置中心局部 QSS，不能只改变系统默认字体。
- 设置页使用渲染签名缓存时，必须同时检查当前视图是否仍有有效子控件；如果堆叠页被清空或隐藏恢复后为空，必须强制重建，不能只因为快照签名一致就跳过渲染。
- GUI 与 WebUI 的配置中心都采用左侧分类导航、右侧当前分组详情的 master-detail 布局；WebUI 不允许退回“所有设置卡片平铺”的旧结构。
- 平台设置表格必须保证“20 个视频（推荐）”和“1 页（推荐）”完整可读；MissAV 自定义代理端点在空间不足时换行展示，不允许横向溢出。
- `app.web.server.create_app()` 是用户真实访问 WebUI 的入口，首页和 `/static/app.css`、`/static/app.js` 必须返回禁缓存头，避免浏览器继续使用旧前端资源。

## 常见配置分组

### `common`

- `save_directory`：默认下载目录。
- `last_source`：上次选择的平台。
- `filename_template`：文件命名模板，必须来自 `filename_template_options()`。
- `open_after_download`：下载完成后是否自动打开。
- `default_open_mode`：默认打开方式，必须来自 `open_mode_options()`。
- `theme`：界面主题，支持 `light` / `dark`。

### `download`

- `max_concurrent`：最大并发下载数，运行中可热更新。
- `local_scan_limit`：本地媒体扫描上限。
- `max_retries`：下载重试次数，允许为 `0` 表示不重试。
- `request_timeout`：请求超时时间。
- `chunk_size`：流式下载块大小。
- `resume_enabled`：是否启用断点续传。
- `speed_limit_kb`：下载限速，`0` 表示不限速。
- `video_only`：是否仅下载视频资源。

### `playback`

- `default_player`：默认播放器，必须来自 `playback_player_options()`。
- `builtin_player_enabled`：是否启用内置播放器。
- `remember_position`：是否记住播放位置。
- `hardware_acceleration`：旧配置兼容项；当前 PyQt6 运行时没有可靠的跨平台硬件解码开关，配置中心不展示该项。
- `autoplay_next`：是否自动播放下一个。
- `manual_image_switch`：图片预览是否手动切换。

### `logging`

- `retention_days`：日志保留天数，必须为 `1`、`3`、`5`、`7`；默认 `1` 天。应用初始化和保留策略变更时会清理过期日志。
- `level`：内部文件日志写入阈值，必须来自 `log_level_options()`；配置中心不再展示该项，日志中心请使用页面筛选器。
- `ui_log_max_display_count`：日志中心最大展示条数。
- `auto_copy_trace_on_error`：错误时是否自动保留 Trace ID。
- `cleanup_old_logs_on_start`：兼容旧配置项；旧日志清理由 `retention_days` 策略统一驱动。

### `appearance`

- `follow_system`：是否跟随系统主题。
- `accent`：主题色，必须来自 `accent_options()`。
- `scale`：界面缩放，必须来自 `scale_options()`。
- `font_size`：字体大小，必须来自 `font_size_options()`。
- `language`：界面语言，必须来自 `language_options()`；当前支持 `zh-CN`、`en-US`、`zh-TW`。
- GUI 组合框的显示 label 必须经过设置页语言映射翻译，不能只翻译字段标题；WebUI 使用同一语义的 `optionLabel()`，保证 Red/Large/Recommended 等选项在两端一致。

### 平台分组

- `bilibili` / `douyin` / `xiaohongshu` / `kuaishou` / `missav` 等平台配置只存放各自运行参数。
- 平台数量字段由 `settings_snapshot()` 明确输出 `count_config_key` 与 `count_unit`：Bilibili 使用 `max_pages/pages`，MissAV 与短视频平台使用 `max_items/videos`，其它分页平台可使用 `max_pages` 或 `search_max_pages`。
- 平台代理字段由 `settings_snapshot()` 明确输出 `proxy_config_key`、`proxy_custom_value` 与 `proxy_custom_active`。非 MissAV 平台默认不可编辑；MissAV 下拉写 `proxy_app`，自定义输入写 `proxy_url`。

### `auth`

- 各平台 Cookie 文件路径。
- 用于浏览器登录后恢复会话。

## 维护建议

- 新字段必须提供 dataclass 默认值、normalize 逻辑和必要的枚举选项。
- 会暴露到 GUI/WebUI 的字段必须进入 `settings_snapshot()`，并同时覆盖 GUI 控件、WebUI 控件与测试。
- 允许 `0` 的数值字段不能使用 `value or default` 写法，必须显式区分缺省和零值。
- 不同平台特有字段尽量收口到各自分组，不混入 `common`。
- 如果字段会直接影响爬虫流程、下载路径、播放行为或打包资源，请同步补测试和文档。
- 在 Windows 上修改保存逻辑时必须覆盖“临时文件替换被短暂拒绝”的场景，避免配置中心热加载成功但落盘失败。

## GUI 主题与弹窗生命周期约束

- GUI 目录选择必须使用非原生、非模态 `QFileDialog`，并由页面或窗口持有引用；禁止在主线程直接调用 `QFileDialog.getExistingDirectory()` 这类阻塞静态入口。
- 主题热加载只允许给真实顶层窗口（`QMainWindow` / `QDialog`）应用根样式。动态页面清理旧控件时不能先 `setParent(None)` 再 `deleteLater()`，否则旧按钮、卡片会在删除事件处理前变成隐藏 top-level，导致主题切换越来越慢，甚至留下空白小窗。
- `ConfigManager.set_many()` 用于同一配置分组的成组写入，例如 `common.theme` + `common.dark_theme`。GUI 与 WebUI 切换主题时应批量保存，避免连续 `config.changed` 事件触发误判 storm 或重复热加载。
- 主题按钮 busy 状态不能禁用按钮；连续点击应排队合并，不允许出现“图标已变、页面仍旧主题”或“按钮空变但主界面不重绘”的状态。
- `_apply_theme_stylesheet()` 默认不应刷新完整前端快照；前端状态刷新应交给 `FrontendSnapshotWorker` 或明确的局部 section，避免主题、配置落盘和列表刷新互相抢 UI 线程。
- 媒体预览全屏状态必须与主窗口主题状态分开判断；退出全屏或 stale fullscreen 清理后再执行 shell 可见性修复，避免黑色预览区域遮住主界面。
- 主题切换性能回归必须覆盖“连续切换主题 + 设置分组 + 页面 + 媒体预览”的混合压力路径，验收指标至少包括：只有主窗口可见、隐藏 Settings 顶层控件为 0、TopBar/Sidebar/PageStack/StatusBar 不消失、主题按钮仍可点击、无 QSS parse warning、无异常退出。事故细节见 [GUI 主题切换黑屏事故复盘](../fixes/2026-07-gui-theme-black-shell.md)。
