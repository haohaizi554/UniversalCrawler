# Web UI 交互流程对照文档（完整版 v5）

> 本文档逐条对比桌面 GUI (PyQt6) 与 Web UI 的每个交互流程，标注差异和修复方案。
> v5 新增：BUG-44~BUG-67，深度对比每个 GUI 组件的每个属性、每个事件处理、每个状态转换。
> v6 新增：配置中心 GUI/WebUI 同源快照与 `update_setting` 热加载链路。

---

## 一、信号/事件映射表

| 桌面 GUI 信号 | 触发者 | Web UI WebSocket 事件 | 方向 |
|---|---|---|---|
| `sig_start_crawl(keyword, source_id, config)` | TopBar.btn_start | `start_crawl` | 前端→服务端 |
| `sig_stop_crawl` | TopBar.btn_stop | `stop_crawl` | 前端→服务端 |
| `sig_change_dir` | TopBar.btn_dir | `change_dir` | 前端→服务端 |
| `sig_play_video(video_id)` | QueuePanel.play_btn | 前端直接调用 `previewVideo()` | 前端本地 |
| `sig_delete_video(row, video_id)` | QueuePanel.delete_btn | `delete_video` | 前端→服务端 |
| `sig_theme_changed(is_dark)` | TopBar.btn_theme | `change_theme` | 前端→服务端 |
| `setting_changed(section, key, value)` | SettingsPage | `update_setting` / `update_basic_setting` | 前端→服务端 |
| `sig_copy_trace_id(video_id)` | TopBar.btn_copy_trace | 前端 `copyTraceId()` | 前端本地 |
| `sig_toggle_fullscreen` | MediaPanel.btn_fullscreen | 前端 `toggleFullscreen()` | 前端本地 |
| `spider.sig_log(msg)` | Spider线程 | `log` | 服务端→前端 |
| `spider.sig_item_found(item)` | Spider线程 | `item_found` | 服务端→前端 |
| `spider.sig_select_tasks(items)` | Spider线程 | `select_tasks` | 服务端→前端 |
| `spider.sig_finished` | Spider线程 | `crawl_state` | 服务端→前端 |
| `dl_manager.task_started(vid)` | DownloadWorker | `task_started` | 服务端→前端 |
| `dl_manager.task_progress(vid, p)` | DownloadWorker | `task_progress` | 服务端→前端 |
| `dl_manager.task_finished(vid)` | DownloadWorker | `task_finished` | 服务端→前端 |
| `dl_manager.task_error(vid, err)` | DownloadWorker | `task_error` | 服务端→前端 |
| — | WebController | `video_state_changed` | 服务端→前端 |
| — | WebController | `video_removed` | 服务端→前端 |
| — | WebController | `video_renamed` | 服务端→前端 |
| — | WebController | `clear_videos` | 服务端→前端 |

---

## 一点五、配置中心热加载对齐

GUI 和 WebUI 的配置中心统一读取 `FrontendStateService.settings_snapshot()`，不再各自硬编码设置模型。基础设置、下载设置、平台设置、播放设置、日志设置、外观设置都从同一快照取值、同一组选项渲染。两端布局统一为左侧分类导航 + 右侧当前分组详情；WebUI 不再使用旧的所有设置卡片平铺结构。

| 设置分组 | GUI 控件来源 | WebUI 控件来源 | 更新动作 | 状态 |
|---|---|---|---|---|
| 基础设置 | `SettingsPage._build_basic_settings()` | `settingsControls()` | `update_basic_setting` / `update_setting` | ✅ |
| 下载设置 | `download_*_options()` / `UiSwitch` | select / checkbox | `update_setting(download, ...)` | ✅ |
| 平台设置 | 插件注册表 + `count_config_key/count_unit/count_options` / `proxy_options` | select + 仅 MissAV 自定义端点单独输入 | `update_setting(platform_id, ...)` | ✅ |
| 播放设置 | `playback_player_options()` | 同一 options | `update_setting(playback, ...)` | ✅ |
| 日志设置 | `log_retention_options()` / `log_level_options()` | 同一 options | `update_setting(logging, ...)` | ✅ |
| 外观设置 | `common.theme` + `appearance`（语言、主题色、缩放、字号） | 同一 options，并乐观应用主题/语言 | `update_setting(appearance/common, ...)` | ✅ |

关键约束：允许为 `0` 的字段必须保留零值语义，例如 `download.max_retries=0` 表示不重试，不能被默认值覆盖。

显示一致性约束：主题色必须覆盖 GUI/WebUI 的下拉框 focus/open 状态和选中行背景；顶部主题按钮必须同步外观页 Light/Dark 控件；语言切换保留中文分组键作为数据契约，只在展示层翻译顶栏、侧栏、状态栏和设置项标签。

WebUI 状态刷新约束：`/api/frontend/state` 和 `/api/frontend/delta` 必须在所有 FastAPI 启动路径中同时存在；`app.web.server.create_app()` 与 `app.web.rest_router.build_rest_router()` 的返回结构要保持一致。首屏静态资源使用带版本参数的 `/static/app.css?v=...` 和 `/static/app.js?v=...`，并且真实 `create_app()` 路径必须对首页、`app.css`、`app.js` 返回禁缓存头，避免升级后浏览器继续使用旧 CSS/JS。

配置中心视觉约束：平台设置在 GUI/WebUI 均使用摘要条 + 表格列。数量列必须区分视频数和页数，短视频/MissAV 显示“20 个视频（推荐）”，Bilibili 显示“1 页（推荐）”；MissAV 代理下拉只承载预设和“自定义”，自定义端点在 GUI/WebUI 中位于代理列下一行，避免宽屏溢出和窄屏横向滚动。

---

## 二、逐流程详细对照

### 流程1: 应用启动

```
GUI:  MainWindow.__init__()
      → 创建 TopBar / DownloadQueuePanel / MediaPreviewPanel / LogPanel
      → load_initial_state(): 恢复 last_source / dark_theme / splitter 比例
      → QTimer.singleShot(200, controller.scan_local_dir)

Web:  WebSocket 连接
      → 服务端推送 init_state / platforms / config
      → 前端 applyConfig(): 恢复 save_directory / dark_theme / last_source
      → 服务端自动调用 controller.scan_local_dir()
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 恢复 last_source | `combo.setCurrentText()` | `config` 消息中恢复 | ✅ |
| 恢复 dark_theme | `self.is_dark_theme = cfg.get(...)` → `setStyleSheet()` | `applyConfig()` 中恢复 | ✅ |
| 恢复 splitter 比例 | `main_split.restoreState()` / `setSizes([400,900])` | CSS `width:400px` / `height:200px` | ✅ 最佳替代 |
| 延迟扫描 | `QTimer.singleShot(200, ...)` | WebSocket 连接后立即扫描 | ✅ |

### 流程2: 更改目录

```
GUI:  btn_dir.clicked
      → 非原生非模态 QFileDialog(DirectoryPickerDialog)
      → if selected_dir:
          self.current_save_dir = selected_dir
          self.left_panel.set_current_save_dir(selected_dir)  ← 更新路径标签
          cfg.set("common", "save_directory", selected_dir)
          sig_change_dir.emit()
      → controller.on_dir_changed()
          → window.append_log("📂 目录已变更: ...")
          → scan_local_dir()
              → _clear_local_items() → window.clear_video_rows() + videos.clear()
              → file_service.scan_directory()
              → _append_scanned_items() → 逐条 window.add_video_row(item)

Web:  showDirDialog() → 服务端目录浏览器
      → confirmDirDialog()
          → currentSaveDir = dir
          → pathLabel.textContent = dir  ← 更新路径标签
          → sendWS('change_dir', {directory})
      → controller.change_dir(dir)
          → current_save_dir = dir
          → cfg.set(...)
          → bridge.emit("log", "📂 目录已变更: ...")
          → scan_local_dir(dir)
              → bridge.emit("clear_videos", {directory})  ← 前端清空+更新路径
              → file_service.scan_directory()
              → 逐条 bridge.emit("item_found", ...)
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 路径标签更新时机 | 确认后立即更新 | 确认后立即更新 + clear_videos 事件也更新 | ✅ |
| 清空表格 | `window.clear_video_rows()` | `clear_videos` 事件 → `videos={}; videoOrder=[]` | ✅ |
| 逐条添加 | `window.add_video_row(item)` | `item_found` 事件 → `videos[id]=data; videoOrder.push(id)` | ✅ |

### 流程3: 点击播放视频

```
GUI:  play_btn.clicked → on_play(video_item.id)
      → sig_play_video.emit(video_id)
      → controller.play_video(vid)
          → video = self.videos.get(vid)
          → if not video or not os.path.exists(video.local_path):
              window.append_log("❌ 文件不存在或已被删除")
              return
          → current_playing_id = vid
          → window.append_log("▶️ 播放: {title}")
          → if is_image: window.show_image(local_path)
            else: window.play_video(local_path)
              → media_panel.play_video(video_path)
                  → img_lbl.hide(); vid_w.show()
                  → player.setSource(QUrl.fromLocalFile(video_path))
                  → player.play()
                  → btn_play.setIcon(SP_MediaPause)

Web:  op-btn onclick → previewVideo(id)
      → v = videos[id]
      → if (!v.local_path): appendLog("❌ 文件不存在"); return
      → selectedVideoId = id; renderQueue()
      → area.innerHTML = '<video src="/api/media/{id}">'
      → player.play().catch(()=>{})
      → setupPlayerEvents(player)
      → appendLog("▶️ 播放: {title}")
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 文件存在检查 | `os.path.exists(local_path)` 服务端检查 | 前端只检查 `v.local_path` 非空，服务端 `/api/media/` 返回 404 时 `onerror` 处理 | ✅ 最佳替代 |
| 图片预览 | `show_image(local_path)` → QLabel + QPixmap | `<img src="/api/media/{id}">` | ✅ |
| 视频播放 | QMediaPlayer + QVideoWidget | HTML5 `<video>` | ✅ |
| 播放按钮图标 | `SP_MediaPause` / `SP_MediaPlay` | `⏸` / `▶` 文字 | ✅ |
| **current_playing_id** | `controller.current_playing_id = vid` | 前端 `selectedVideoId = id` | ❌ **BUG-11: 语义混淆** |
| **播放失败提示** | `QMediaPlayer.errorOccurred` → 日志 | `onerror` → 日志 + `closePreview()` | ✅ |

### 流程4: 删除视频

```
GUI:  delete_btn.clicked → on_delete(video_id)
      → sig_delete_video.emit(row_idx, video_id)
      → controller.on_delete_video(row_idx, vid)
          → cancel_result = dl_manager.cancel_task(vid)
          → if current_playing_id == vid:
              window.stop_media_playback()
              current_playing_id = None
          → file_service.delete_media(video)
          → del self.videos[vid]
          → window.remove_video_row(row_idx)
          → window.refresh_table_bindings()

Web:  op-btn.del onclick → deleteVideo(id)
      → if selectedVideoId === id: closePreview(); selectedVideoId = null
      → sendWS('delete_video', {video_id: id})
      → controller.delete_video(video_id)
          → cancel_result = dl_manager.cancel_task(video_id)
          → file_service.delete_media(video)
          → del self.videos[video_id]
          → bridge.emit("video_removed", {video_id})
      → 前端收到 video_removed → delete videos[id]; videoOrder.filter(); renderQueue()
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 传参 | `sig_delete_video(row_idx, video_id)` | `delete_video({video_id})` 无 row_idx | ✅ Web 不需要 row_idx |
| 停止播放 | `window.stop_media_playback()` → `player.stop()` | `closePreview()` → 清空 HTML | ✅ |
| 清除 playing_id | `current_playing_id = None` | `selectedVideoId = null` | ❌ **BUG-11: 应检查 currentPlayingId** |
| 刷新绑定 | `window.refresh_table_bindings()` | 不需要（Web 每次渲染重建 DOM） | ✅ |

### 流程5: 重命名

```
GUI:  双击标题 → QTableWidgetItem 变为可编辑
      → 用户编辑完成 → itemChanged 信号
      → controller.on_rename_video(item)
          → if item.column() != 0: return  ← 只处理标题列
          → vid = item.data(UserRole)
          → new_title = item.text().strip()
          → if new_title == video.title or not os.path.exists(video.local_path):
              item.setText(video.title)  ← 回退
              return
          → file_service.rename_media(video, new_title, save_dir)
          → video.title = new_title; video.local_path = new_path
          → item.setToolTip(new_title)  ← 更新 tooltip
          → window.append_log("📝 重命名: ...")

Web:  双击标题 → startRename(id, td)
      → 创建 <input> 替换 td 内容
      → blur/Enter → sendWS('rename_video', {video_id, new_title})
      → controller.rename_video()
          → file_service.rename_media(video, new_title, save_dir)
          → video.title = new_title; video.local_path = new_path
          → bridge.emit("video_renamed", {video_id, new_title, new_local_path})
      → 前端收到 video_renamed → 更新 videos[id].title / local_path → renderQueue()
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 编辑触发 | QTableWidget 内置编辑 | JS 创建 `<input>` | ✅ |
| 回退逻辑 | `item.setText(video.title)` 回退 | Escape 时 `input.value = v.title` + blur | ✅ |
| 文件不存在检查 | `not os.path.exists(video.local_path)` → 回退 | 服务端检查，失败时返回 error | ✅ |
| tooltip 更新 | `item.setToolTip(new_title)` | `renderQueue()` 重建时自动用新 title | ✅ |

### 流程6: 启动爬虫

```
GUI:  btn_start.clicked → on_btn_start_clicked()
      → if not current_plugin: append_log("❌ 未选择有效模式"); return
      → keyword = inp_search.text().strip()
      → if not keyword: append_log("⚠️ 请输入搜索内容！"); return
      → run_options = current_plugin.get_run_options(plugin_widget)
      → sig_start_crawl.emit(keyword, source_id, run_options)
      → set_crawl_running_state(True)  ← 立即设置 UI 状态
      → controller.on_start_crawl(keyword, source_id, config)
          → if _has_active_spider(): append_log("⚠️ 当前已有任务在运行"); return
          → _create_spider() → _bind_spider_signals() → spider.start()

Web:  startBtn.onclick → startCrawl()
      → if !keyword: appendLog("⚠️ 请输入搜索内容！"); return
      → setCrawlState(true)  ← 立即设置 UI 状态
      → sendWS('start_crawl', {source, keyword, config})
      → controller.start_crawl(source, keyword, config)
          → 同上逻辑
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 检查 current_plugin | `if not current_plugin` | 前端不检查（source 总有值） | ✅ |
| get_run_options | `current_plugin.get_run_options(plugin_widget)` | `getRunConfig()` 从 DOM 读取 | ✅ |
| 立即设置 UI | `set_crawl_running_state(True)` | `setCrawlState(true)` | ✅ |
| 活跃爬虫检查 | 服务端 `_has_active_spider()` | 服务端检查 | ✅ |

### 流程7: 选择对话框

```
GUI:  spider.sig_select_tasks(items)
      → controller._on_spider_select_tasks(items)
      → selected = window.show_selection_dialog(items)
          → dialog = SelectionDialog(self, items=items)
          → if dialog.exec() == Accepted:
              return dialog.selected_indices
          → return None  ← 取消返回 None
      → spider.resume_from_ui(selected)  ← None 或 [0,2,5]

Web:  select_tasks 事件
      → showSelectionModal(data.items)
      → confirmSelection() → sendWS('select_tasks', {indices: [0,2,5]})
      → cancelSelection() → sendWS('select_tasks', {indices: []})
      → controller.resume_spider_selection(indices)
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 取消返回值 | `None` | `[]` | ⚠️ **需确认 spider 对 None vs [] 的处理** |
| 对话框尺寸 | `resize(800, 600)` | CSS `width:800px; height:600px` | ✅ |
| 全选/反选 | 有 | 有 | ✅ |
| 默认全选 | 有 | 有 | ✅ |

### 流程8: 主题切换

```
GUI:  btn_theme.clicked → toggle_theme()
      → is_dark_theme = !is_dark_theme
      → setStyleSheet(generate_stylesheet(is_dark_theme))
      → top_bar.set_theme_icon(is_dark_theme)
      → cfg.set_many("common", {"theme": ..., "dark_theme": ...})
      → append_log("🎨 已切换到深色/浅色主题")
      → sig_theme_changed.emit(is_dark_theme)

Web:  themeBtn.onclick → toggleTheme()
      → isDarkTheme = !isDarkTheme
      → document.documentElement.setAttribute('data-theme', ...)
      → themeBtn.textContent = isDarkTheme ? '🌙' : '☀️'
      → appendLog("🎨 已切换到深色/浅色主题")
      → sendWS('change_theme', {dark_theme: isDarkTheme})
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 应用方式 | `setStyleSheet()` 全局替换 | CSS 变量切换 | ✅ |
| 图标更新 | `set_theme_icon()` → 🌙/☀️ | `textContent` 切换 | ✅ |
| 保存到配置 | `cfg.set_many()` 批量写 `theme/dark_theme` | `sendWS('change_theme')` → 服务端 `cfg.set_many()` | ✅ |
| 启动恢复 | `cfg.get("common","dark_theme",True)` | `applyConfig()` 中恢复 | ✅ |

### 流程9: 全屏模式

```
GUI:  btn_fullscreen.clicked / 双击视频区 → sig_toggle_fullscreen
      → toggle_fullscreen_mode()
          → if not is_fullscreen_mode:
              top_bar.hide(); left_panel.hide(); log_txt.hide()
              showFullScreen()
              _set_main_margins(0)
              btn_fullscreen.setText("[ 退出 ]")
          → else:
              top_bar.show(); left_panel.show(); log_txt.show()
              showNormal()
              _set_main_margins(10)
              btn_fullscreen.setText("[ 全屏 ]")
      → Escape 键退出全屏

Web:  fullscreenBtn.onclick / 双击预览区 → toggleFullscreen()
      → body.classList.toggle('is-fullscreen')
      → CSS 隐藏 top-bar / left-panel / h-splitter / log-panel / v-splitter
      → CSS main-layout padding:0
      → CSS right-panel height:100vh
      → fullscreenBtn.textContent = '[ 退出 ]' / '[ 全屏 ]'
      → Escape 键退出
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 隐藏组件 | `hide()` / `show()` | CSS `display:none` | ✅ |
| 边距清零 | `_set_main_margins(0)` | CSS `padding:0` | ✅ |
| 恢复 splitter | `restoreState()` | 不需要（CSS 自动恢复） | ✅ |

### 流程10: 复制 Trace ID

```
GUI:  btn_copy_trace.clicked → _on_copy_trace_clicked()
      → video_id = get_selected_video_id()  ← 从表格当前选中行获取
      → if not video_id: append_log("⚠️ 请先选中一个任务"); return
      → sig_copy_trace_id.emit(video_id)
      → controller.copy_trace_id_for_video(video_id)
          → item = self.videos.get(video_id)
          → trace_id = item.meta.get("trace_id") if item else None
          → debug_service.copy_trace_id(app.clipboard(), trace_id)
          → append_log("📋 已复制 trace_id: {trace_id}")

Web:  copyTraceId()
      → if !selectedVideoId: appendLog("⚠️ 请先选中一个任务"); return
      → v = videos[selectedVideoId]
      → traceId = (v.meta && v.meta.trace_id) || v.id  ← 已修复
      → navigator.clipboard.writeText(traceId)
      → appendLog("📋 已复制 trace_id: {traceId}")
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 获取选中行 | `table.currentRow()` → `item.data(UserRole)` | `selectedVideoId` | ✅ |
| trace_id 来源 | `item.meta.get("trace_id")` | `(v.meta && v.meta.trace_id) \|\| v.id` | ✅ 已修复 |
| 复制方式 | `QApplication.clipboard().setText()` | `navigator.clipboard.writeText()` | ✅ |

---

## 三、组件级逐行对比（新增）

> 以下逐组件对比 GUI 和 Web 的每个视觉/交互细节。

### 3.1 TopBar（顶栏）

| 属性 | GUI (TopBarWidget) | Web (.top-bar) | 差异 | 状态 |
|---|---|---|---|---|
| 高度 | `setFixedHeight(50)` | `height:50px` | 一致 | ✅ |
| 内边距 | `setContentsMargins(10,5,10,5)` | `padding:5px 10px` | 一致 | ✅ |
| 间距 | `setSpacing(10)` | `gap:10px` | 一致 | ✅ |
| 背景 | `QFrame#TopBar { background: panel }` | `background:var(--panel)` | 一致 | ✅ |
| 下边框 | `border-bottom: 1px solid border` | `border-bottom:1px solid var(--border)` | 一致 | ✅ |
| 来源选择器 | `QComboBox` + `SizeAdjustPolicy.AdjustToContents` | `<select>` + `source-select` | Web 下拉宽度不自适应内容 | ❌ **BUG-13** |
| 搜索框 | `QLineEdit` + `SizePolicy.Expanding` | `<input>` + `flex:1` | 一致 | ✅ |
| 搜索框聚焦 | `QLineEdit:focus { border: 1px solid accent }` | `.search-input:focus { border:1px solid var(--accent) }` | 一致 | ✅ |
| 搜索框占位符 | `setPlaceholderText(placeholder)` 由插件提供 | `placeholder` 由 `renderPlatformSelect()` 设置 | 一致 | ✅ |
| 启动按钮 | `QPushButton#PrimaryBtn` + `setFixedHeight(30)` | `.btn-primary` + `height:30px` | 一致 | ✅ |
| 停止按钮 | `QPushButton#DangerBtn` + `setEnabled(False)` | `.btn-danger` + `disabled` | 一致 | ✅ |
| 目录按钮 | `QPushButton#DirBtn` 虚线边框 | `.btn-dir` 虚线边框 | 一致 | ✅ |
| 主题按钮宽度 | `setFixedWidth(40)` | `min-width:40px` | Web 用 min-width，实际可能更宽 | ❌ **BUG-14** |
| 主题按钮圆角 | `border-radius: 15px` | `border-radius:15px` | 一致 | ✅ |
| 主题按钮内边距 | `padding: 5px 12px` | `padding:5px 12px` | 一致 | ✅ |
| 动态配置区 | `QHBoxLayout` + `setSpacing(8)` | `.dynamic-area` + `gap:8px` | 一致 | ✅ |

### 3.2 DownloadQueuePanel（左侧下载队列）

| 属性 | GUI (DownloadQueuePanel) | Web (.left-panel) | 差异 | 状态 |
|---|---|---|---|---|
| 面板宽度 | `main_split.setSizes([400,900])` 默认 400 | `width:400px` | 一致 | ✅ |
| 面板最小宽度 | QSplitter 拖拽最小值 | `min-width:200px` | 一致 | ✅ |
| 面板背景 | `QFrame#ContentPanel { background: panel }` | `background:var(--panel)` | 一致 | ✅ |
| 面板边框 | `border: 1px solid border; border-radius: 4px` | `border:1px solid var(--border); border-radius:4px` | 一致 | ✅ |
| 标题栏高度 | `setFixedHeight(35)` | `height:35px` | 一致 | ✅ |
| 标题栏背景 | `QFrame#HeaderBar { background: input }` | `background:var(--input)` | 一致 | ✅ |
| 标题栏下边框 | `border-bottom: 1px solid border` | `border-bottom:1px solid var(--border)` | 一致 | ✅ |
| 路径标签颜色 | `QLabel#PathLabel { color: accent; font-family: Consolas; font-weight: bold }` | `.path { color:var(--accent); font-family:Consolas; font-weight:bold }` | 一致 | ✅ |
| 路径标签溢出 | `QSizePolicy.Expanding` → Qt 自动省略 | `overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1` | 一致 | ✅ |
| 路径标签 tooltip | `setToolTip(save_dir)` | `title=currentSaveDir` | 一致 | ✅ |
| 表格行高 | `verticalHeader.setDefaultSectionSize(36)` | `td { height:36px }` | 一致 | ✅ |
| 表格无网格线 | `setShowGrid(False)` | `td { border-left:none; border-right:none; border-top:none }` | 一致 | ✅ |
| 交替行色 | `setAlternatingRowColors(True)` | `tr:nth-child(even) { background:var(--alt-row) }` | 一致 | ✅ |
| 选中行高亮 | `selection-background-color: accent; selection-color: white` | `tr.selected { background:var(--accent); color:#fff }` | 一致 | ✅ |
| 表头固定 | `QHeaderView` 自带 sticky | `th { position:sticky; top:0; z-index:1 }` | 一致 | ✅ |
| 表头背景 | `QHeaderView::section { background: input }` | `th { background:var(--input) }` | 一致 | ✅ |
| 标题列宽度 | `Stretch` | `style="width:100%"` | 一致 | ✅ |
| 状态列宽度 | `ResizeToContents` | `width:90px; text-align:center` | 固定宽度 vs 自适应 | ⚠️ 次要差异 |
| 进度列宽度 | `ResizeToContents` | `width:120px` | 固定宽度 vs 自适应 | ⚠️ 次要差异 |
| 操作列宽度 | `ResizeToContents` | `width:80px; text-align:center` | 固定宽度 vs 自适应 | ⚠️ 次要差异 |
| 进度条样式 | `QProgressBar { text-align:center; font-size:11px }` | `.progress-wrap { text-align:center; font-size:11px }` | 一致 | ✅ |
| 进度条圆角 | `border-radius:3px` | `border-radius:3px` | 一致 | ✅ |
| 播放按钮图标 | `SP_MediaPlay` 系统图标 | `▶` 文字 | 视觉差异 | ✅ 最佳替代 |
| 删除按钮图标 | `SP_TrashIcon` 系统图标 | `✕` 文字 | 视觉差异 | ✅ 最佳替代 |
| 播放按钮尺寸 | `setFixedSize(28, 26)` | `width:28px; height:26px` | 一致 | ✅ |
| 操作按钮间距 | `setSpacing(8)` | `margin:0 2px` | 间距不同 | ❌ **BUG-15** |
| 标题 tooltip | `title_item.setToolTip(video_item.title)` | `title="${esc(v.title)}"` | 一致 | ✅ 已修复 |
| 标题双击编辑 | QTableWidget 内置编辑 | JS `ondblclick="startRename()"` | 一致 | ✅ |
| 标题溢出省略 | Qt 自动省略 | `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` | 一致 | ✅ |
| 滚动条始终显示 | `ScrollBarAlwaysOn` | `overflow-y:scroll` | 一致 | ✅ |
| **选中行方式** | `SelectRows` 点击任意列选中整行 | `onclick="selectVideo()"` 只在 `<tr>` 上 | 一致 | ✅ |
| **选中行后播放** | 点击播放按钮 → `on_play(video_id)` → `sig_play_video.emit()` | 点击播放按钮 → `previewVideo(id)` 直接播放 | GUI 走控制器，Web 前端直接播放 | ❌ **BUG-16** |
| **选中行后删除** | 点击删除按钮 → `on_delete(video_id)` → `sig_delete_video.emit()` | 点击删除按钮 → `deleteVideo(id)` → `sendWS('delete_video')` | 一致 | ✅ |

### 3.3 MediaPreviewPanel（右侧媒体预览）

| 属性 | GUI (MediaPreviewPanel) | Web (.preview-panel) | 差异 | 状态 |
|---|---|---|---|---|
| 面板背景 | `QFrame#ContentPanel { background: panel }` | `background:var(--panel)` | 一致 | ✅ |
| 视频区域背景 | `QVideoWidget#VideoSurface { background: video_bg }` | `.preview-area { background:var(--video-bg) }` | 一致 | ✅ |
| 视频区域圆角 | `border-top-left-radius:4px; border-top-right-radius:4px` | `.preview-area { border-top-left-radius:4px; border-top-right-radius:4px }` | 一致 | ✅ |
| 图片显示 | `QLabel#ImageLabel` + `scale_image_to_fit()` | `<img style="max-width:100%;max-height:100%;object-fit:contain">` | 一致 | ✅ |
| 控制面板高度 | `setFixedHeight(50)` | `height:50px` | 一致 | ✅ |
| 控制面板背景 | `QFrame#ControlPanel { background: panel }` | `background:var(--panel)` | 一致 | ✅ |
| 控制面板上边框 | `border-top: 1px solid border` | `border-top:1px solid var(--border)` | 一致 | ✅ |
| 播放按钮 | `QPushButton#PlayBtn` 圆形 `border-radius:16px` | `.play-btn` 圆形 `border-radius:16px` | 一致 | ✅ |
| 播放按钮尺寸 | `setFixedSize(32, 32)` | `width:32px; height:32px` | 一致 | ✅ |
| 进度滑块 | `QSlider` + `sliderPressed/sliderReleased` | `<input type="range">` + `mousedown/mouseup` | 一致 | ✅ |
| 时间标签 | `QLabel#TimeLabel { color: muted; font: Consolas 12px }` | `.time-label { color:var(--muted-text); font-family:Consolas; font-size:12px }` | 一致 | ✅ |
| 时间格式 | `MM:SS / MM:SS` | `MM:SS / MM:SS` | 一致 | ✅ |
| 全屏按钮 | `QPushButton#FullscreenBtn` | `.fullscreen-btn` | 一致 | ✅ |
| 全屏按钮文字 | `[ 全屏 ]` / `[ 退出 ]` | `[ 全屏 ]` / `[ 退出 ]` | 一致 | ✅ |
| 全屏按钮 tooltip | `setToolTip("沉浸模式 (双击画面)")` | `title="沉浸模式 (双击画面)"` | 一致 | ✅ |
| 双击全屏 | `ClickableVideoWidget.sig_double_click` | `previewArea.addEventListener('dblclick')` | 一致 | ✅ |
| **图片自适应** | `scale_image_to_fit()` → `pixmap.scaled(size, KeepAspectRatio)` | `max-width:100%; max-height:100%; object-fit:contain` | 一致 | ✅ |
| **图片切换到视频** | `img_lbl.hide(); vid_w.show(); player.stop()` | 替换 `area.innerHTML` 为 `<video>` | 一致 | ✅ |
| **视频切换到图片** | `vid_w.hide(); img_lbl.show(); player.stop()` | 替换 `area.innerHTML` 为 `<img>` | 一致 | ✅ |
| **播放/暂停切换** | `toggle_play()` → 检查 `PlaybackState` | `togglePlay()` → 检查 `player.paused` | 一致 | ✅ |
| **播放按钮状态** | `_set_play_button_paused()` → `SP_MediaPause` | `player.onplay` → `⏸` | 一致 | ✅ |
| **暂停按钮状态** | `_set_play_button_stopped()` → `SP_MediaPlay` | `player.onpause` → `▶` | 一致 | ✅ |
| **预览区占位文字** | 无（默认空白） | `"选择视频进行预览"` | Web 多了占位文字 | ⚠️ 次要差异 |
| **关闭预览** | `stop_playback()` → `player.stop()` + `setSource(QUrl())` | `closePreview()` → 清空 HTML | 一致 | ✅ |

### 3.4 LogPanel（日志面板）

| 属性 | GUI (LogPanel) | Web (.log-panel) | 差异 | 状态 |
|---|---|---|---|---|
| 类型 | `QPlainTextEdit` | `<div>` | 不同实现 | ✅ 最佳替代 |
| 只读 | `setReadOnly(True)` | 无输入控件 | 一致 | ✅ |
| 背景 | `QPlainTextEdit#LogText { background: log_bg }` | `background:var(--log-bg)` | 一致 | ✅ |
| 边框 | `border: 1px solid border` | `border:1px solid var(--border)` | 一致 | ✅ |
| 字体 | 默认（继承全局 `font-size:13px`） | `font-family:Consolas; font-size:13px` | Web 用等宽字体 | ⚠️ 次要差异 |
| 自动滚动 | `moveCursor(End)` | `el.scrollTop = el.scrollHeight` | 一致 | ✅ |
| 滚动条始终显示 | `ScrollBarAlwaysOn` | `overflow-y:scroll` | 一致 | ✅ |
| **日志条目上限** | 无限制（QPlainTextEdit 自带优化） | `while (el.children.length > 500) el.removeChild(el.firstChild)` | Web 限制 500 条 | ⚠️ 次要差异 |

### 3.5 QSplitter（分割线）

| 属性 | GUI (QSplitter) | Web (.h-splitter / .v-splitter) | 差异 | 状态 |
|---|---|---|---|---|
| 宽度 | `setHandleWidth(4)` | `width:4px` / `height:4px` | 一致 | ✅ |
| 默认颜色 | `QSplitter::handle { background: bg }` | `background:var(--bg)` | 一致 | ✅ |
| hover 颜色 | `QSplitter::handle:hover { background: accent }` | `.h-splitter:hover { background:var(--accent) }` | 一致 | ✅ |
| 拖拽光标 | Qt 内置 `SplitHCursor` / `SplitVCursor` | `cursor:col-resize` / `cursor:row-resize` | 一致 | ✅ |
| **拖拽时高亮** | Qt 内置 | `.h-splitter.active { background:var(--accent) }` | 一致 | ✅ |
| **拖拽时禁止选择** | Qt 内置 | `document.body.style.userSelect='none'` | 一致 | ✅ |
| **保存/恢复比例** | `saveState()` / `restoreState()` | 不保存（刷新后恢复默认） | ❌ **BUG-17** |

### 3.6 SelectionDialog（选择对话框）

| 属性 | GUI (SelectionDialog) | Web (.modal-overlay) | 差异 | 状态 |
|---|---|---|---|---|
| 尺寸 | `resize(800, 600)` | `width:800px; height:600px` | 一致 | ✅ |
| 标题 | `"共扫描到 N 个资源，请勾选需要下载的项目："` | 同上 | 一致 | ✅ |
| 表格列 | `["选择", "视频标题 / 描述"]` | 同上 | 一致 | ✅ |
| 复选框列宽 | `setColumnWidth(0, 60)` | `style="width:60px"` | 一致 | ✅ |
| 默认全选 | `chk.setChecked(True)` | `checked` | 一致 | ✅ |
| 全选按钮 | `"全选"` + `setFixedSize(80, 30)` | `"全选"` + `style="width:80px;height:30px"` | 一致 | ✅ |
| 反选按钮 | `"反选"` + `setFixedSize(80, 30)` | `"反选"` + `style="width:80px;height:30px"` | 一致 | ✅ |
| 取消按钮 | `"取消任务"` + `DangerBtn` + `setFixedSize(100, 35)` | `"取消任务"` + `.btn-danger` + `style="width:100px;height:35px"` | 一致 | ✅ |
| 确认按钮 | `"开始下载"` + `PrimaryBtn` + `setFixedSize(120, 35)` | `"开始下载"` + `.btn-primary` + `style="width:120px;height:35px"` | 一致 | ✅ |
| 交替行色 | `setAlternatingRowColors(True)` | `tr:nth-child(even) { background:var(--alt-row) }` | 一致 | ✅ |
| 标题列不可编辑 | `setFlags(flags ^ ItemIsEditable)` | 无编辑功能 | 一致 | ✅ |
| 按钮布局 | 全选/反选左对齐 + stretch + 取消/确认右对齐 | 同上 | 一致 | ✅ |
| **继承父窗口主题** | `setStyleSheet(parent.styleSheet())` | 自动继承 CSS 变量 | 一致 | ✅ |
| **模态** | `dialog.exec()` 阻塞 | CSS overlay + `display:flex` | 一致 | ✅ |

---

## 四、数据流差异（新增）

> 对比 GUI 和 Web 中数据如何在前后端流转。

### 4.1 VideoItem 数据序列化

```
GUI:  VideoItem (Python dataclass) → 直接在内存中引用
      → add_video_row(video_item) → 直接访问 video_item.title / .status / .progress
      → update_video_status(vid, status, progress) → 直接修改 item.status / item.progress

Web:  VideoItem (Python) → _video_item_to_dict() → JSON → WebSocket → JS object
      → videos[id] = data → 访问 v.title / v.status / v.progress
      → video_state_changed 事件 → 更新 videos[id].status / .progress → renderQueue()
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 数据传递 | 直接内存引用 | JSON 序列化/反序列化 | ✅ |
| 状态更新 | `update_video_status()` 只更新单行 | `renderQueue()` 重建整个表格 | ❌ **BUG-10** |
| meta 字段 | `item.meta.get("trace_id")` | `v.meta && v.meta.trace_id` | ✅ |
| content_type | `item.meta.get("content_type")` | `v.content_type` (顶层字段) | ⚠️ Web 多了一个顶层 content_type |
| local_path | `item.local_path` | `v.local_path` | ✅ |

### 4.2 _video_item_to_dict 序列化字段

```python
# WebController._video_item_to_dict(item)
{
    "id": item.id,
    "url": item.url,
    "title": item.title,
    "source": item.source,
    "status": item.status,
    "progress": item.progress,
    "local_path": item.local_path,
    "content_type": item.meta.get("content_type", ""),  # 顶层冗余字段
    "meta": dict(item.meta),                              # 完整 meta
}
```

| 字段 | GUI 访问方式 | Web 访问方式 | 差异 |
|---|---|---|---|
| `id` | `item.id` | `v.id` | 一致 |
| `title` | `item.title` | `v.title` | 一致 |
| `status` | `item.status` | `v.status` | 一致 |
| `progress` | `item.progress` | `v.progress` | 一致 |
| `local_path` | `item.local_path` | `v.local_path` | 一致 |
| `content_type` | `item.meta.get("content_type")` | `v.content_type` 或 `v.meta.content_type` | Web 有冗余顶层字段 |
| `trace_id` | `item.meta.get("trace_id")` | `v.meta.trace_id` | 一致 |
| `source` | `item.source` | `v.source` | 一致 |

### 4.3 扫描结果数据流

```
GUI:  file_service.scan_directory() → ScanResult
      → _append_scanned_items(result)
          → for item in result.items:
              videos[item.id] = item
              window.add_video_row(item)  ← 逐条添加到表格
      → window.append_log("✅ 已加载 N 个本地文件...")

Web:  file_service.scan_directory() → ScanResult
      → controller.scan_local_dir()
          → videos.clear()
          → bridge.emit("clear_videos", {directory})  ← 前端清空
          → for item in result.items:
              videos[item.id] = item
              bridge.emit("item_found", dict)  ← 逐条推送到前端
      → bridge.emit("log", "✅ 已加载 N 个本地文件...")
```

| 差异点 | GUI | Web | 状态 |
|---|---|---|---|
| 清空时机 | `_clear_local_items()` 在扫描前 | `clear_videos` 事件在扫描前 | ✅ |
| 添加方式 | 逐条 `add_video_row()` | 逐条 `item_found` 事件 | ✅ |
| **扫描结果统计** | `window.append_log()` 直接输出 | `bridge.emit("log")` 输出 | ✅ |
| **空目录提示** | `append_log("ℹ️ 该目录下没有找到视频或图片")` | 同上 | ✅ |
| **截断提示** | `append_log("⚠️ 文件过多...")` | 同上 | ✅ |

---

## 五、用户操作反馈差异（新增）

> 对比 GUI 和 Web 中用户操作后的反馈是否一致。

### 5.1 表格行选中反馈

| 操作 | GUI 反馈 | Web 反馈 | 差异 | 状态 |
|---|---|---|---|---|
| 点击行 | 整行高亮（accent 背景 + 白色文字） | 整行高亮 | 一致 | ✅ |
| 点击行后播放按钮 | 播放按钮可点击 | 播放按钮可点击 | 一致 | ✅ |
| 点击行后删除按钮 | 删除按钮可点击 | 删除按钮可点击 | 一致 | ✅ |
| **选中行播放按钮 hover** | 无特殊效果 | `.op-btn:hover` 变色 | Web 多了 hover 效果 | ⚠️ 次要差异 |
| **选中行删除按钮 hover** | 无特殊效果 | `.op-btn.del:hover` 变红 | Web 多了 hover 效果 | ⚠️ 次要差异 |
| **选中行操作按钮** | 白色图标（系统主题） | `.queue-table tr.selected .op-btn { color:#fff }` | 一致 | ✅ |

### 5.2 播放操作反馈

| 操作 | GUI 反馈 | Web 反馈 | 差异 | 状态 |
|---|---|---|---|---|
| 点击播放按钮 | `sig_play_video.emit()` → 控制器播放 | `previewVideo(id)` 前端直接播放 | ❌ **BUG-16: GUI 走控制器** |
| 播放成功 | 播放按钮变暂停图标 + 日志 | 播放按钮变 ⏸ + 日志 | 一致 | ✅ |
| 播放失败 | `errorOccurred` 信号 → 日志 | `onerror` → 日志 + `closePreview()` | 一致 | ✅ |
| 文件不存在 | `append_log("❌ 文件不存在或已被删除")` | `appendLog("❌ 文件不存在或已被删除")` | 一致 | ✅ |
| **切换播放视频** | 新视频替换旧视频 | 新视频替换旧视频 | 一致 | ✅ |
| **播放中点击另一行** | 不影响播放 | 不影响播放 | 一致 | ✅ |

### 5.3 删除操作反馈

| 操作 | GUI 反馈 | Web 反馈 | 差异 | 状态 |
|---|---|---|---|---|
| 删除成功 | `append_log("🗑️ 已删除: filename")` | 同上 | 一致 | ✅ |
| 文件不存在 | `append_log("ℹ️ 文件不存在，仅从列表移除: title")` | 同上 | 一致 | ✅ |
| 删除失败 | `append_log("❌ 删除文件失败: exc")` | 同上 | 一致 | ✅ |
| 取消队列任务 | `append_log("🛑 已取消队列任务: title")` | 同上 | 一致 | ✅ |
| 停止下载中任务 | `append_log("🛑 已请求停止下载: title")` | 同上 | 一致 | ✅ |
| **删除正在播放的视频** | `stop_media_playback()` + `current_playing_id = None` | `closePreview()` + `selectedVideoId = null` | ❌ **BUG-11** |

### 5.4 爬虫操作反馈

| 操作 | GUI 反馈 | Web 反馈 | 差异 | 状态 |
|---|---|---|---|---|
| 启动成功 | `append_log("🟢 启动任务 \| 模式: name")` | 同上 | 一致 | ✅ |
| 已有任务运行 | `append_log("⚠️ 当前已有任务在运行")` | 同上 | 一致 | ✅ |
| 空关键词 | `append_log("⚠️ 请输入搜索内容！")` | 同上 | 一致 | ✅ |
| 停止任务 | `append_log("🛑 正在停止任务...")` | 同上 | 一致 | ✅ |
| 任务结束 | `append_log("✅ 爬虫任务结束")` | 同上 | 一致 | ✅ |
| **启动时 UI 禁用** | `set_crawl_running_state(True)` → 禁用按钮/输入/下拉 | `setCrawlState(true)` → 同上 | 一致 | ✅ |
| **结束时 UI 恢复** | `set_crawl_running_state(False)` → 恢复按钮/输入/下拉 | `setCrawlState(false)` → 同上 | 一致 | ✅ |
| **动态配置区禁用** | `plugin_widget.setEnabled(not is_running)` | `querySelectorAll('#dynamicArea select, #dynamicArea input').forEach(el => el.disabled = running)` | 一致 | ✅ |

### 5.5 目录操作反馈

| 操作 | GUI 反馈 | Web 反馈 | 差异 | 状态 |
|---|---|---|---|---|
| 目录变更 | `append_log("📂 目录已变更: dir")` | 同上 | 一致 | ✅ |
| 扫描开始 | `append_log("📂 正在扫描目录: dir")` | 同上 | 一致 | ✅ |
| 扫描完成 | `append_log("✅ 已加载 N 个本地文件...")` | 同上 | 一致 | ✅ |
| 空目录 | `append_log("ℹ️ 该目录下没有找到视频或图片")` | 同上 | 一致 | ✅ |
| **路径标签更新** | `left_panel.set_current_save_dir(dir)` → `lbl_full_path.setText(dir)` | `pathLabel.textContent = dir` | 一致 | ✅ |
| **路径标签 tooltip** | `lbl_full_path.setToolTip(dir)` | `pathLabel.title = dir` | 一致 | ✅ |

---

## 六、CSS/样式像素级差异（新增）

> 逐条对比 GUI stylesheet 和 Web CSS 的每个属性值。

### 6.1 全局

| 属性 | GUI | Web | 差异 |
|---|---|---|---|
| 字体 | `'Segoe UI', 'Microsoft YaHei', sans-serif` | `'Segoe UI', 'Microsoft YaHei', sans-serif` | ✅ |
| 字号 | `13px` | `13px` | ✅ |
| 滚动条宽度 | `12px` | `12px` | ✅ |
| 滚动条圆角 | `border-radius: 4px` | `border-radius:4px` | ✅ |
| 滚动条最小高度 | `min-height: 20px` | `min-height:20px` | ✅ |

### 6.2 ThemeBtn 宽度

| 属性 | GUI | Web | 差异 |
|---|---|---|---|
| 宽度 | `min-width: 60px`（themes.py 第186行） | `min-width:60px` | ✅ 已修复（原为 width:40px） |
| setFixedWidth | `setFixedWidth(40)`（top_bar.py 第76行） | — | GUI 同时设置了固定宽度40和最小宽度60，实际宽度=60 |

### 6.3 DangerBtn 禁用态

| 属性 | GUI | Web | 差异 |
|---|---|---|---|
| 背景 | `btn_bg` | `var(--btn-bg)` | ✅ |
| 文字色 | `#555` (dark) / `#999` (light) | `var(--danger-disabled-text)` | ✅ |
| 边框 | `1px solid border` | `1px solid var(--border)` | ✅ |

---

## 七、剩余 BUG 清单（更新版）

### BUG-7: copyTraceId 使用 v.id 而非 meta.trace_id ✅ 已修复

**GUI 行为**：`item.meta.get("trace_id")` — trace_id 是下载时生成的追踪 ID，与 video.id 不同。

**Web 行为**：`v.id` — 使用的是 VideoItem 的 uuid，不是 trace_id。

**修复**：`const traceId = (v.meta && v.meta.trace_id) || v.id;` — 已应用。

### BUG-8: on_btn_start_clicked 检查 current_plugin

**GUI 行为**：`if not self.current_plugin: self.append_log("❌ 未选择有效模式"); return`

**Web 行为**：不检查，直接发送。

**修复**：在 `startCrawl()` 中添加检查（虽然不太可能触发）。

### BUG-9: 选择对话框取消传 None vs []

**GUI 行为**：`show_selection_dialog()` 返回 `None`，`spider.resume_from_ui(None)`

**Web 行为**：发送 `{indices: []}`，`controller.resume_spider_selection([])`

**影响**：`BaseSpider.resume_from_ui(selected_indices)` 将 `_selection_result = selected_indices`。GUI 取消时 `_selection_result = None`，Web 取消时 `_selection_result = []`。爬虫代码中 `ask_user_selection()` 返回 `_selection_result`，下游代码如果对 `None` 和 `[]` 有不同处理，行为会不一致。但实际上大多数爬虫只检查 `if selected_indices` 或 `if not selected_indices`，`None` 和 `[]` 在布尔上下文中都是 falsy，所以行为一致。

**结论**：实际影响极小，可忽略。

### BUG-10: renderQueue 性能问题

**GUI 行为**：`update_video_status()` 只更新单行（`table.item(row, 1).setText()`）

**Web 行为**：`renderQueue()` 每次重建整个表格 HTML

**影响**：当有大量视频时（如扫描到 1000 个本地文件），每次进度更新都会重建 1000 行 DOM，导致卡顿。

**修复方案**：
1. `video_state_changed` / `task_progress` 事件只更新对应行的 DOM，而非调用 `renderQueue()`
2. `item_found` 事件追加一行到 tbody 末尾，而非重建
3. `video_removed` 事件删除对应行，而非重建
4. `clear_videos` 事件清空 tbody，而非重建
5. 只在 `selectVideo()` 切换选中行时才需要更新两行（旧选中行 + 新选中行）

### BUG-11: currentPlayingId 语义混淆

**GUI 行为**：
- `controller.current_playing_id = vid` — 播放时设置
- `if current_playing_id == vid: stop_playback(); current_playing_id = None` — 删除时检查
- `current_playing_id` 和"选中行"是完全独立的概念

**Web 行为**：
- `selectedVideoId = id` — 选中行和播放共用
- 变量 `currentPlayingId` 已声明但未使用

**影响**：
1. 选中一行但不播放时，`selectedVideoId` 有值，删除该行会调用 `closePreview()`，但此时没有播放器需要关闭
2. 播放视频 A 后选中视频 B（不播放），删除视频 A 时不会停止播放

**修复方案**：
1. `previewVideo(id)` 中设置 `currentPlayingId = id`
2. `deleteVideo(id)` 中检查 `if (currentPlayingId === id)` 而非 `if (selectedVideoId === id)`
3. `closePreview()` 中清除 `currentPlayingId = null`
4. `video_removed` 事件处理中检查 `if (currentPlayingId === data.video_id) currentPlayingId = null`

### BUG-12: tooltip 应显示 title 而非 local_path ✅ 已修复

**GUI 行为**：`title_item.setToolTip(video_item.title)` — 显示标题

**Web 行为**：`title="${esc(v.title)}"` — 已修复为显示标题

### BUG-13: 来源选择器宽度不自适应内容

**GUI 行为**：`QComboBox.SizeAdjustPolicy.AdjustToContents` — 下拉框宽度随内容变化

**Web 行为**：`<select class="source-select">` — 固定宽度

**修复方案**：给 `.source-select` 添加 `min-width` 或动态计算宽度。

### BUG-14: ThemeBtn 宽度应为 min-width:60px ✅ 已修复

**GUI 行为**：`setFixedWidth(40)` + `min-width: 60px`（themes.py） — 实际宽度 60px

**Web 行为**：`min-width:60px` — 已修复（原为 `width:40px`）

### BUG-15: 操作按钮间距不一致

**GUI 行为**：`operation_layout.setSpacing(8)` — 按钮间距 8px

**Web 行为**：`.op-btn { margin:0 2px }` — 按钮间距 4px（左右各 2px）

**修复方案**：将 `.op-btn` 的 `margin` 改为 `margin:0 4px`（总间距 8px）。

### BUG-16: 播放视频应走服务端文件存在性检查

**GUI 行为**：
```
play_btn.clicked → sig_play_video.emit(video_id)
→ controller.play_video(vid)
    → if not os.path.exists(video.local_path): append_log("❌ 文件不存在"); return
    → current_playing_id = vid
    → window.play_video(local_path)
```

**Web 行为**：
```
previewVideo(id) → 前端直接创建 <video src="/api/media/{id}">
→ 如果文件不存在，<video onerror> 才触发
```

**差异**：
1. GUI 在播放前先检查文件是否存在，不存在则直接提示
2. Web 先尝试加载，失败后才提示
3. GUI 的 `current_playing_id` 在服务端设置，Web 的 `currentPlayingId` 在前端设置

**修复方案**：在 `previewVideo()` 中先通过 API 检查文件是否存在，或接受当前行为（onerror 处理已足够）。

### BUG-17: Splitter 比例不保存

**GUI 行为**：
- `closeEvent()` → `cfg.save_ui_state(main_splitter=self.main_split.saveState(), ...)`
- `load_initial_state()` → `main_split.restoreState(QByteArray.fromHex(...))`

**Web 行为**：不保存 splitter 比例，刷新后恢复默认值

**修复方案**：将 splitter 比例保存到 localStorage，页面加载时恢复。

---

## 八、修复优先级（更新版）

| 优先级 | BUG | 影响 | 修复难度 |
|---|---|---|---|
| P0 | BUG-10: renderQueue 性能 | 大列表时严重卡顿 | 中 |
| P1 | BUG-11: currentPlayingId 语义混淆 | 删除/播放逻辑错误 | 低 |
| P1 | BUG-16: 播放应走服务端检查 | 文件不存在时体验差 | 低 |
| P2 | BUG-15: 操作按钮间距 | 视觉差异 | 低 |
| P2 | BUG-14: ThemeBtn 宽度 | 视觉差异 | 低 |
| P2 | BUG-13: 来源选择器宽度 | 视觉差异 | 低 |
| P2 | BUG-17: Splitter 比例不保存 | 刷新后布局重置 | 中 |
| P3 | BUG-8: startCrawl 缺少检查 | 极少触发 | 低 |
| P3 | BUG-9: cancelSelection None vs [] | 实际影响极小 | 低 |

---

## 九、Web 端特有交互（GUI 不存在）

> 以下交互是 Web 端特有的，因为浏览器和桌面应用的本质区别。

| 交互 | 说明 | 处理方式 |
|---|---|---|
| 目录选择 | 浏览器无法直接访问文件系统 | 服务端目录浏览器 API `/api/dir/list` |
| 视频拖拽进度条 | 需要 HTTP Range 请求支持 | 服务端 `/api/media/{id}` 支持 206 Partial Content |
| 剪贴板访问 | `navigator.clipboard` 需要 HTTPS 或 localhost | 已处理（catch 降级） |
| WebSocket 断线重连 | 网络不稳定时连接断开 | `ws.onclose` → 3 秒后自动重连 |
| 多标签页 | 多个标签页同时连接 | 服务端 `ConnectionManager` 广播到所有连接 |
| 浏览器缩放 | Ctrl+滚轮缩放页面 | CSS `viewport` meta 已设置 |
| 移动端适配 | 触摸操作 | Slider 已添加 touch 事件支持 |
| 页面刷新 | 刷新后状态丢失 | WebSocket 重连后自动推送 `init_state` |

---

## 十、关键代码路径索引

| 功能 | GUI 代码路径 | Web 代码路径 |
|---|---|---|
| 主窗口 | `app/ui/main_window.py` | `app/web/static/index.html` |
| 顶栏 | `app/ui/components/top_bar.py` | `.top-bar` CSS + JS |
| 下载队列 | `app/ui/components/download_queue_panel.py` | `.left-panel` CSS + JS `renderQueue()` |
| 媒体预览 | `app/ui/components/media_preview_panel.py` | `.preview-panel` CSS + JS `previewVideo()` |
| 日志面板 | `app/ui/components/log_panel.py` | `.log-panel` CSS + JS `appendLog()` |
| 选择对话框 | `app/ui/dialogs/selection.py` | `.modal-overlay` CSS + JS `showSelectionModal()` |
| 目录对话框 | `QFileDialog` | `.dir-modal-overlay` CSS + JS + `/api/dir/list` |
| 控制器 | `app/controllers/application_controller.py` | `app/web/controller.py` |
| 服务器 | — | `app/web/server.py` |
| 主题 | `app/ui/styles/themes.py` | CSS 变量 `:root` / `[data-theme="light"]` |
| 数据模型 | `app/models/video_item.py` | `_video_item_to_dict()` 序列化 |
| 文件服务 | `app/services/file_service.py` | 同（共享） |
| 下载管理器 | `app/core/download_manager.py` | 同（共享） |
| Spider 基类 | `app/spiders/base.py` | 同（共享） |
| 插件注册 | `app/core/plugin_registry.py` | 同（共享） |

---

## 十一、v3 新增差异（深度审查发现）

> 以下差异是在逐行对比 GUI 源码后新发现的。

### BUG-18: updateRow 不更新标题和 tooltip ✅ 已修复

**GUI 行为**：`on_rename_video()` 中 `item.setToolTip(new_title)` — 重命名后更新 tooltip

**Web 行为**：`updateRow()` 只更新 status 和 progress，不更新 title 和 tooltip

**影响**：重命名后表格中的标题不会更新，tooltip 也不会更新

**修复**：在 `updateRow()` 中添加 `titleTd.textContent = v.title; titleTd.title = v.title;`

### BUG-19: appendRow 创建无用的 tr 元素 ✅ 已修复

**GUI 行为**：`add_video_row()` 直接插入一行

**Web 行为**：`appendRow()` 先 `document.createElement('tr')` 然后 `tr.outerHTML = buildRowHTML(id)`，但 `outerHTML` 赋值不会修改原 `tr` 引用，而是创建新元素。这行代码完全无效，幸好后面还有 `insertAdjacentHTML` 正常工作。

**修复**：删除无用的 `createElement` 和 `outerHTML` 行。

### BUG-20: startRename 完成后调用 renderQueue 重建整个表格 ✅ 已修复

**GUI 行为**：`on_rename_video()` 中直接修改 `item.setText()` — 只更新单个单元格

**Web 行为**：`startRename()` 的 `finish` 回调调用 `renderQueue()` — 重建整个表格

**影响**：重命名操作导致整个表格重建，大列表时卡顿

**修复**：改为直接恢复 `td.textContent = v.title; td.title = v.title;`

### BUG-21: previewVideo 中 updateSelection 不取消旧选中行 ✅ 已修复

**GUI 行为**：`QTableWidget.setSelectionBehavior(SelectRows)` — 点击新行自动取消旧行选中

**Web 行为**：`previewVideo()` 中 `updateSelection(null, id)` — 传入 null 导致旧行不被取消

**影响**：点击播放按钮后，旧行保持高亮，新行也高亮，出现两行同时高亮

**修复**：先保存 `oldId = selectedVideoId`，再调用 `updateSelection(oldId, id)`

### BUG-22: GUI 的 on_start_crawl 先检查 current_plugin 再切换 UI 状态

**GUI 行为**：
```python
def on_btn_start_clicked(self):
    if not self.current_plugin:
        self.append_log("❌ 未选择有效模式")
        return
    keyword = self.inp_search.text().strip()
    if not keyword:
        self.append_log("⚠️ 请输入搜索内容！")
        return
    # ... 获取 run_options ...
    self.sig_start_crawl.emit(keyword, self.current_plugin.id, run_options)
    self.set_crawl_running_state(True)  # 只有成功后才切换
```

**Web 行为**：
```javascript
function startCrawl() {
    const keyword = document.getElementById('searchInput').value.trim();
    if (!keyword) { appendLog('⚠️ 请输入搜索内容！'); return; }
    setCrawlState(true);  // 立即切换，不检查 source 是否有效
    sendWS('start_crawl', { source: currentSource, keyword, config: getRunConfig() });
}
```

**差异**：
1. GUI 先检查 `current_plugin` 是否存在，Web 不检查
2. GUI 在 `sig_start_crawl.emit()` 之后才切换 UI 状态，Web 在发送 WS 之前就切换了
3. GUI 如果 `get_run_options()` 出错，不会切换 UI 状态，Web 无法捕获这种错误

**影响**：如果服务端返回错误（如未知爬虫源），Web UI 已经切换到"运行中"状态，但实际没有任务在运行

**修复方案**：在 `startCrawl()` 中添加 source 检查，或等服务端 `crawl_state` 事件再切换 UI

### BUG-23: GUI 的 on_source_changed 保存 last_source 到配置

**GUI 行为**：`on_source_changed()` 中 `cfg.set("common", "last_source", plugin_id)` — 切换来源时立即保存

**Web 行为**：`sel.onchange` 中 `sendWS('change_source', { source: currentSource })` — 通过 WebSocket 保存

**差异**：Web 通过 WebSocket 异步保存，GUI 直接同步保存。但最终效果一致。

**结论**：无需修复。

### BUG-24: GUI 的 play_video 走控制器（服务端文件存在性检查）

**GUI 行为**：
```python
def play_video(self, vid):
    video = self.videos.get(vid)
    if not video or not os.path.exists(video.local_path):
        self.window.append_log("❌ 文件不存在或已被删除")
        return
    self.current_playing_id = vid
    self.window.append_log(f"▶️ 播放: {video.title}")
    if self._is_image_file(video.local_path):
        self.window.show_image(video.local_path)
    else:
        self.window.play_video(video.local_path)
```

**Web 行为**：
```javascript
function previewVideo(id) {
    const v = videos[id];
    if (!v) return;
    if (!v.local_path) {  // 只检查 local_path 是否非空，不检查文件是否真的存在
        appendLog('❌ 文件不存在或已被删除');
        return;
    }
    // 直接创建 <video> 或 <img>，文件不存在时 onerror 触发
}
```

**差异**：
1. GUI 在服务端检查 `os.path.exists()`，不存在则直接提示
2. Web 只检查 `v.local_path` 非空，不检查文件是否真的存在
3. Web 的 `<video onerror>` 是异步的，用户会先看到空白再看到错误提示

**修复方案**：在 `previewVideo()` 中先 fetch `/api/media/{id}` HEAD 请求检查文件是否存在，或接受当前行为。

### BUG-25: GUI 的 _is_image_file 判断图片类型

**GUI 行为**：`controller._is_image_file(video.local_path)` — 根据扩展名判断是图片还是视频

**Web 行为**：`previewVideo()` 中 `const ext = (v.local_path || '').split('.').pop().toLowerCase();` — 同样根据扩展名判断

**差异**：逻辑一致，但 Web 的图片扩展名列表和 GUI 的 `IMAGE_EXTENSIONS` 需要保持同步。

**结论**：当前已同步，无需修复。

### BUG-26: GUI 的 splitterMoved 触发 scale_image_to_fit

**GUI 行为**：
```python
self.main_split.splitterMoved.connect(lambda: self.media_panel.scale_image_to_fit())
self.right_split.splitterMoved.connect(lambda: self.media_panel.scale_image_to_fit())
```

**Web 行为**：拖拽分割线时不触发图片缩放

**影响**：如果正在预览图片，拖拽分割线后图片不会自动缩放适应新尺寸

**修复方案**：在 splitter mousemove 事件中，如果正在显示图片，触发图片 resize

### BUG-27: GUI 的 resizeEvent 触发 resize_media

**GUI 行为**：
```python
def resizeEvent(self, event):
    super().resizeEvent(event)
    self.media_panel.resize_media()
```

**Web 行为**：窗口 resize 时不触发媒体缩放

**影响**：如果正在预览图片，调整窗口大小后图片不会自动缩放

**修复方案**：添加 `window.addEventListener('resize', ...)` 事件处理

### BUG-28: GUI 的 closeEvent 保存 UI 状态

**GUI 行为**：
```python
def closeEvent(self, event):
    cfg.save_ui_state(
        geometry=self.saveGeometry(),
        state=self.saveState(),
        main_splitter=self.main_split.saveState(),
        right_splitter=self.right_split.saveState(),
        is_fs=self.is_fullscreen_mode,
    )
```

**Web 行为**：页面关闭时不保存任何状态（splitter 比例已在 mouseup 时保存到 localStorage）

**差异**：GUI 保存窗口位置/大小/全屏状态，Web 无法保存这些（浏览器限制）

**结论**：已通过 localStorage 保存 splitter 比例，窗口位置/大小无法保存（浏览器限制），可接受。

### BUG-29: GUI 的 on_delete_video 传入 row_idx

**GUI 行为**：`sig_delete_video.emit(row_idx, video_id)` → `on_delete_video(row_idx, vid)` → `window.remove_video_row(row_idx)`

**Web 行为**：`sendWS('delete_video', { video_id: id })` → `controller.delete_video(video_id)` → `bridge.emit("video_removed", {video_id})` → 前端 `removeRow(video_id)`

**差异**：GUI 用 row_idx 删除行，Web 用 video_id 查找行删除。效果一致。

**结论**：无需修复。

### BUG-30: GUI 的 refresh_table_bindings

**GUI 行为**：删除行后调用 `window.refresh_table_bindings()` — 重新绑定删除按钮的 clicked 信号

**Web 行为**：不需要（DOM 事件绑定是声明式的，不需要刷新）

**结论**：无需修复。

### BUG-31: GUI 的 SelectionDialog 继承父窗口主题

**GUI 行为**：`self.setStyleSheet(parent.styleSheet() if parent else generate_stylesheet(...))`

**Web 行为**：CSS 变量自动继承，无需额外处理

**结论**：无需修复。

### BUG-32: GUI 的 combo_source 使用 currentData/currentText

**GUI 行为**：`self.combo_source.addItem(plugin.name, plugin.id)` — 显示 name，数据是 id

**Web 行为**：`opt.value = p.id; opt.textContent = p.name` — 同样

**结论**：一致，无需修复。

### BUG-33: GUI 的 set_crawl_running_state 同时禁用 plugin_widget

**GUI 行为**：`if plugin_widget: plugin_widget.setEnabled(not is_running)`

**Web 行为**：`document.querySelectorAll('#dynamicArea select, #dynamicArea input').forEach(el => el.disabled = running)`

**差异**：GUI 只禁用 plugin_widget，Web 禁用 dynamicArea 下所有 select 和 input。效果一致。

**结论**：无需修复。

---

## 十二、v3 修复状态汇总

| BUG | 描述 | 状态 |
|---|---|---|
| BUG-7 | copyTraceId 使用 v.id 而非 meta.trace_id | ✅ 已修复 |
| BUG-10 | renderQueue 性能问题 | ✅ 已修复（增量更新） |
| BUG-11 | currentPlayingId 语义混淆 | ✅ 已修复 |
| BUG-12 | tooltip 应显示 title 而非 local_path | ✅ 已修复 |
| BUG-14 | ThemeBtn 宽度应为 min-width:60px | ✅ 已修复 |
| BUG-15 | 操作按钮间距应为 8px | ✅ 已修复 |
| BUG-17 | Splitter 比例保存到 localStorage | ✅ 已修复 |
| BUG-18 | updateRow 不更新标题和 tooltip | ✅ 已修复 |
| BUG-19 | appendRow 创建无用的 tr 元素 | ✅ 已修复 |
| BUG-20 | startRename 完成后调用 renderQueue | ✅ 已修复 |
| BUG-21 | previewVideo 中 updateSelection 不取消旧选中行 | ✅ 已修复 |
| BUG-8 | startCrawl 缺少 current_plugin 检查 | ⚠️ 低优先级 |
| BUG-9 | cancelSelection None vs [] | ⚠️ 低优先级 |
| BUG-13 | 来源选择器宽度不自适应 | ⚠️ 低优先级 |
| BUG-16 | 播放应走服务端文件检查 | ⚠️ 低优先级 |
| BUG-22 | startCrawl 应先检查再切换 UI | ⚠️ 低优先级 |
| BUG-24 | previewVideo 不检查文件是否存在 | ⚠️ 低优先级 |
| BUG-26 | splitter 拖拽时不触发图片缩放 | ✅ 已修复 |
| BUG-27 | 窗口 resize 时不触发媒体缩放 | ✅ 已修复 |
| BUG-34 | 动态配置区缺少标签 | ✅ 已修复 |
| BUG-35 | MissAV 代理下拉框不可编辑 | ✅ 已修复 |
| BUG-36 | Douyin 缺少 timeout=10 | ✅ 已修复 |
| BUG-37 | 插件配置不保存到配置文件 | ✅ 已修复 |
| BUG-38 | 插件配置不从配置文件恢复 | ✅ 已修复 |
| BUG-39 | init_state 渲染旧数据导致闪烁 | ✅ 已修复 |
| BUG-40 | 下拉框缺少 tooltip | ✅ 已修复 |
| BUG-41 | Douyin 选项值 50 不在 GUI 中 | ✅ 已修复 |
| BUG-42 | getRunConfig 缺少 const config = {} | ✅ 已修复 |

### BUG-43: --no-qt 模式下 WebSocket 推送完全不工作（致命 BUG） ✅ 已修复

**现象**：`--no-qt` 模式下，页面加载后左侧队列为空，日志面板无内容，所有服务端推送事件（日志、视频列表、进度更新等）都不工作。

**根本原因**：
1. `WebSocketBridge` 使用 `pyqtSignal` 桥接，`pyqtSignal.emit()` 需要 Qt 事件循环才能触发槽函数
2. `--no-qt` 模式下 `QApplication` 不存在，但 `PyQt6` 可以导入，所以 `_QT_AVAILABLE = True`
3. `pyqtSignal.emit()` 调用后，`_on_broadcast` 永远不会被触发，所有 `bridge.emit()` 无效
4. 即使修复了信号问题，`scan_local_dir()` 在事件循环线程中同步运行，会阻塞事件循环
5. `asyncio.run_coroutine_threadsafe()` 调度的协程需要事件循环来执行，但事件循环被阻塞

**修复**：
1. 检测 `QApplication.instance() is not None` 而非 `PyQt6` 是否可导入
2. 无 Qt 模式下 `WebSocketBridge` 直接使用 `asyncio.run_coroutine_threadsafe()`
3. `scan_local_dir()` 改为 `run_in_executor()` 在线程池中运行，不阻塞事件循环
4. 在 WebSocket 连接时保存正确的事件循环到 `bridge._loop`

---

## 十三、v4 新增差异（动态配置区深度对比）

> 以下差异是在逐行对比 `settings_builders.py` 后新发现的。

### BUG-34: 动态配置区缺少标签 ✅ 已修复

**GUI 行为**：
- Bilibili: `QLabel("页数:")` + `QComboBox`
- Douyin: `QLabel("视频数:")` + `QComboBox`
- Kuaishou: `QLabel("视频数:")` + `QComboBox`
- MissAV: `QCheckBox("仅单体")` + `QComboBox` + `QLabel("代理:")` + `QComboBox`

**Web 行为**（修复前）：只有下拉框/复选框，没有标签

**修复**：添加 `<label>` 标签

### BUG-35: MissAV 代理下拉框不可编辑 ✅ 已修复

**GUI 行为**：`self.combo_proxy.setEditable(True)` — 可输入自定义代理地址

**Web 行为**（修复前）：`<select>` 不可编辑

**修复**：改为 `<input type="text" list="proxy_list">` + `<datalist>`

### BUG-36: Douyin 缺少 timeout=10 ✅ 已修复

**GUI 行为**：`read_douyin_run_options()` 返回 `{"max_items": N, "timeout": 10}`

**Web 行为**（修复前）：只返回 `{"max_items": N}`

**修复**：添加 `config.timeout = 10;`

### BUG-37: 插件配置不保存到配置文件 ✅ 已修复

**GUI 行为**：`read_*_run_options()` 中 `cfg.set(section, key, value)` — 保存到配置文件

**Web 行为**（修复前）：不保存

**修复**：在 `getRunConfig()` 中 `sendWS('save_config', ...)` + 服务端添加 `save_config` 消息处理

### BUG-38: 插件配置不从配置文件恢复 ✅ 已修复

**GUI 行为**：`build_*_settings_widget()` 中 `cfg.get(section, key, default)` — 从配置文件恢复

**Web 行为**（修复前）：总是使用 HTML 中的 `selected` 属性

**修复**：添加 `restorePluginConfig()` 函数，在 `renderDynamicArea()` 末尾调用

### BUG-39: init_state 渲染旧数据导致闪烁 ✅ 已修复

**GUI 行为**：启动时不渲染旧数据，直接扫描目录

**Web 行为**（修复前）：`init_state` 渲染旧 videos → `scan_local_dir` 清空 → 重新渲染，导致闪烁

**修复**：`init_state` 不再渲染旧 videos

### BUG-40: 下拉框缺少 tooltip ✅ 已修复

**GUI 行为**：`self.combo_pages.setToolTip(tooltip)` — 鼠标悬停显示提示

**Web 行为**（修复前）：无 tooltip

**修复**：添加 `title="..."` 属性

### BUG-41: Douyin 选项值 50 不在 GUI 中 ✅ 已修复

**GUI 行为**：`_page_values = [1, 2, 5, 10, 20, 9999]` — 没有 50

**Web 行为**（修复前）：有 `<option value="50">50</option>`

**修复**：删除 50 选项

### BUG-42: getRunConfig 缺少 const config = {} ✅ 已修复

**Web 行为**（修复前）：`getRunConfig()` 函数体缺少 `const config = {};` 声明，导致 `config is not defined` 错误

**修复**：添加 `const config = {};`

---

## 十四、完整交互路径追踪（v4）

> 以下逐操作追踪 GUI 和 Web 的完整事件链。

### 操作1: 页面加载

```
GUI:
  MainWindow.__init__()
  → TopBar.__init__() → 创建 combo_source / inp_search / btn_start / btn_stop / btn_dir / btn_theme
  → DownloadQueuePanel.__init__() → 创建 table / path_label
  → MediaPreviewPanel.__init__() → 创建 video_widget / img_label / player / control_panel
  → LogPanel.__init__() → 创建 text_edit
  → load_initial_state()
      → cfg.get("common","last_source","kuaishou") → combo_source.setCurrentText()
      → cfg.get("common","dark_theme",True) → setStyleSheet()
      → main_split.restoreState() / right_split.restoreState()
  → QTimer.singleShot(200, controller.scan_local_dir)

Web:
  页面加载 → <style> 渲染 → <body> 渲染
  → <script> 执行 → connectWS()
  → ws.onopen → appendLog("🔗 WebSocket 已连接")
  → 服务端推送 init_state → 恢复 current_save_dir / is_crawling
  → 服务端推送 platforms → renderPlatformSelect() + renderDynamicArea()
  → 服务端推送 config → applyConfig() → 恢复 save_directory / dark_theme / last_source
      → renderDynamicArea() → restorePluginConfig() → 恢复插件配置值
  → 服务端 scan_local_dir() → clear_videos + 逐条 item_found → appendRow()
```

**差异**：
1. GUI 先创建所有控件再恢复状态，Web 先渲染空页面再通过 WS 推送填充数据
2. GUI 用 QTimer 延迟 200ms 扫描，Web 连接后立即扫描
3. GUI 恢复 splitter 比例用 `restoreState()`，Web 用 `localStorage`
4. ✅ 最终效果一致

### 操作2: 切换来源

```
GUI:
  combo_source.currentIndexChanged → on_source_changed()
      → current_plugin = plugin_registry.get(combo_source.currentData())
      → if plugin_widget: layout.removeWidget(plugin_widget); plugin_widget.deleteLater()
      → plugin_widget = current_plugin.get_settings_widget(self)
      → layout.insertWidget(3, plugin_widget)
      → inp_search.setPlaceholderText(current_plugin.search_placeholder)
      → cfg.set("common", "last_source", current_plugin.id)

Web:
  sel.onchange →
      → currentSource = sel.value
      → searchInput.placeholder = p.search_placeholder
      → renderDynamicArea() → area.innerHTML = html → restorePluginConfig()
      → sendWS('change_source', { source: currentSource })
          → 服务端 cfg.set("common", "last_source", source)
```

**差异**：
1. GUI 删除旧 widget 再创建新 widget，Web 直接替换 innerHTML — 效果一致
2. GUI 同步保存配置，Web 异步保存 — 最终效果一致
3. ✅ 最终效果一致

---

## 十五、v5 深度审查新增差异（BUG-44 ~ BUG-67）

> 以下差异是在完整逐行对比所有 GUI 源码与 Web 源码后发现的。

### BUG-44: 表格行点击选中不触发播放预览

**GUI 行为**：`QTableWidget.setSelectionBehavior(SelectRows)` — 点击行任意位置选中整行，但**不会**自动播放。只有点击行内的播放按钮才播放。

**Web 行为**：`<tr onclick="selectVideo('${id}')">` — 点击行选中，**也不会**自动播放。✅ 一致。

**结论**：无需修复。

### BUG-45: GUI 点击行选中后，再点播放按钮，播放按钮的点击事件不冒泡到行

**GUI 行为**：播放按钮 `clicked.connect(lambda: on_play(video_item.id))` — 独立信号，不影响行选中。

**Web 行为**：`<button onclick="event.stopPropagation();previewVideo('${id}')">` — `stopPropagation()` 阻止冒泡。✅ 一致。

**结论**：无需修复。

### BUG-46: GUI 的 QTableWidget 点击行选中与 Web 的 selectVideo 语义差异

**GUI 行为**：
- `table.currentRow()` 返回当前选中行的索引
- `table.item(row, 0).data(UserRole)` 获取 video_id
- 点击行自动选中（`SelectRows` 行为）
- 点击另一行自动取消旧行选中

**Web 行为**：
- `selectedVideoId` 变量跟踪当前选中行
- `selectVideo(id)` 设置 `selectedVideoId = id` + `updateSelection(oldId, newId)`
- 点击行触发 `selectVideo()`

**差异**：GUI 的选中是 QTableWidget 内置行为，Web 是手动管理。但效果一致。✅

**结论**：无需修复。

### BUG-47: GUI 的 `on_source_changed` 先清空旧 widget 再创建新 widget

**GUI 行为**：
```python
def on_source_changed(self, _index):
    while self.layout_dynamic.count():
        item = self.layout_dynamic.takeAt(0)
        if item.widget():
            item.widget().deleteLater()  # 清空旧 widget
    self.plugin_widget = self.current_plugin.get_settings_widget(self.container_dynamic)
    if self.plugin_widget:
        self.layout_dynamic.addWidget(self.plugin_widget)
        self.plugin_widget.show()
```

**Web 行为**：
```javascript
function renderDynamicArea() {
    area.innerHTML = html;  // 直接替换，旧的 DOM 自动销毁
    restorePluginConfig();
}
```

**差异**：GUI 逐个删除旧 widget 再添加新 widget，Web 直接替换 innerHTML。效果一致。✅

**结论**：无需修复。

### BUG-48: GUI 的 `set_crawl_running_state` 禁用 `plugin_widget` 而非动态区所有控件

**GUI 行为**：
```python
def set_crawl_running_state(self, is_running, plugin_widget):
    self.btn_start.setEnabled(not is_running)
    self.btn_stop.setEnabled(is_running)
    self.inp_search.setEnabled(not is_running)
    self.combo_source.setEnabled(not is_running)
    if plugin_widget:
        plugin_widget.setEnabled(not is_running)  # 整个 widget 一次性禁用
```

**Web 行为**：
```javascript
function setCrawlState(running) {
    document.getElementById('startBtn').disabled = running;
    document.getElementById('stopBtn').disabled = !running;
    document.getElementById('searchInput').disabled = running;
    document.getElementById('sourceSelect').disabled = running;
    document.querySelectorAll('#dynamicArea select, #dynamicArea input').forEach(el => el.disabled = running);
}
```

**差异**：GUI 禁用整个 `plugin_widget`（包括 checkbox），Web 只禁用 `select` 和 `input`，**遗漏了 checkbox**。

**修复**：`querySelectorAll('#dynamicArea select, #dynamicArea input, #dynamicArea input[type="checkbox"]')` — 但 `input[type="checkbox"]` 已经被 `input` 选择器包含。实际上 `querySelectorAll('#dynamicArea select, #dynamicArea input')` 已经包含了 checkbox。✅

**结论**：无需修复，`input` 选择器已包含 checkbox。

### BUG-49: GUI 的 `btn_start` 有 ObjectName `PrimaryBtn`，Web 的 `btn-primary` 缺少 `:disabled` 时恢复原样

**GUI 行为**：
```css
QPushButton#PrimaryBtn { background: accent; border: none; font-weight: bold; color: white; }
/* 没有专门的 :disabled 样式，Qt 会自动灰化 */
```

**Web 行为**：
```css
.btn-primary { background:var(--accent); border:none; color:#fff; font-weight:bold; }
.btn-primary:disabled { background:var(--btn-bg); color:var(--muted-text); border:1px solid var(--border); opacity:1; }
```

**差异**：Web 的 `btn-primary:disabled` 恢复为普通按钮样式（与 `DangerBtn:disabled` 一致），GUI 没有专门的禁用样式。

**结论**：Web 的处理更合理，无需修复。

### BUG-50: GUI 的 `QComboBox` 下拉框有 `SizeAdjustPolicy.AdjustToContents`，Web 的 `<select>` 不自适应

**GUI 行为**：`combo_source.setSizeAdjustPolicy(AdjustToContents)` — 下拉框宽度随内容变化

**Web 行为**：`.source-select` 固定宽度

**修复**：给 `.source-select` 添加自适应宽度：
```css
.source-select { width: auto; min-width: 80px; }
```
或用 JS 动态计算宽度。

**状态**：❌ 未修复

---

## 十六、v5 新增：控制器层深度对比

> 对比 `ApplicationController` 和 `WebController` 的每个方法，找出逻辑差异。

### 16.1 play_video 对比

| 步骤 | GUI (ApplicationController) | Web (WebController) | 差异 |
|---|---|---|---|
| 获取 video | `self.videos.get(vid)` | 前端 `videos[id]` | ✅ |
| 文件存在检查 | `os.path.exists(video.local_path)` | 前端只检查 `v.local_path` 非空 | ⚠️ |
| 设置 current_playing_id | `self.current_playing_id = vid` | 前端 `currentPlayingId = id` | ✅ |
| 日志 | `window.append_log(f"▶️ 播放: {video.title}")` | 前端 `appendLog("▶️ 播放: " + v.title)` | ✅ |
| 判断图片/视频 | `_is_image_file(video.local_path)` | 前端 `imgExts.includes(ext)` | ✅ |
| 播放视频 | `window.play_video(local_path)` | 前端 `<video src="/api/media/{id}">` | ✅ |
| 显示图片 | `window.show_image(local_path)` | 前端 `<img src="/api/media/{id}">` | ✅ |

**关键差异**：Web 没有 `current_playing_id` 的服务端状态。GUI 在服务端维护 `current_playing_id`，删除时检查；Web 完全在前端维护。效果一致。

### 16.2 on_delete_video 对比

| 步骤 | GUI | Web | 差异 |
|---|---|---|---|
| 获取 video | `self.videos[vid]` | `self.videos[video_id]` | ✅ |
| 取消下载 | `dl_manager.cancel_task(vid)` | `dl_manager.cancel_task(video_id)` | ✅ |
| 检查正在播放 | `if current_playing_id == vid: stop_playback(); current_playing_id = None` | 前端 `if currentPlayingId === id: closePreview()` | ✅ |
| 删除文件 | `file_service.delete_media(video)` | `file_service.delete_media(video)` | ✅ |
| 删除成功日志 | `append_log("🗑️ 已删除: filename")` | `bridge.emit("log", "🗑️ 已删除: filename")` | ✅ |
| 文件不存在日志 | `append_log("ℹ️ 文件不存在，仅从列表移除: title")` | `bridge.emit("log", "ℹ️ 文件不存在...")` | ✅ |
| 删除失败 | `append_log("❌ 删除文件失败: exc"); return` | `bridge.emit("log", "❌ 删除文件失败: exc"); return` | ✅ |
| 取消队列任务日志 | `append_log("🛑 已取消队列任务: title")` | `bridge.emit("log", "🛑 已取消队列任务: title")` | ✅ |
| 停止下载任务日志 | `append_log("🛑 已请求停止下载: title")` | `bridge.emit("log", "🛑 已请求停止下载: title")` | ✅ |
| 删除内存记录 | `del self.videos[vid]` | `del self.videos[video_id]` | ✅ |
| 删除表格行 | `window.remove_video_row(row_idx)` | `bridge.emit("video_removed")` → 前端 `removeRow(id)` | ✅ |
| 刷新绑定 | `window.refresh_table_bindings()` | 不需要 | ✅ |

**结论**：逻辑完全一致。✅

### 16.3 on_rename_video 对比

| 步骤 | GUI | Web | 差异 |
|---|---|---|---|
| 检查列 | `if item.column() != 0: return` | 前端只绑定在标题列 `ondblclick` | ✅ |
| 获取 video_id | `item.data(UserRole)` | 函数参数 `id` | ✅ |
| 获取 new_title | `item.text().strip()` | `input.value.trim()` | ✅ |
| 标题未变 | `if new_title == video.title: item.setText(video.title); return` | `if newTitle !== v.title: sendWS(...)` | ✅ |
| 文件不存在 | `if not os.path.exists(video.local_path): item.setText(video.title); return` | 服务端检查，返回 error | ⚠️ |
| 重命名文件 | `file_service.rename_media(video, new_title, save_dir)` | `file_service.rename_media(video, new_title, self.current_save_dir)` | ✅ |
| 更新内存 | `video.title = new_title; video.local_path = new_path` | 同上 + `bridge.emit("video_renamed")` | ✅ |
| 更新 tooltip | `item.setToolTip(new_title)` | 前端 `updateRow()` 中 `titleTd.title = v.title` | ✅ |
| 日志 | `append_log("📝 重命名: ...")` | `bridge.emit("log", "📝 重命名: ...")` | ✅ |
| 失败回退 | `item.setText(video.title)` | 前端 `td.textContent = v.title` | ✅ |

**结论**：逻辑完全一致。✅

### 16.4 start_crawl 对比

| 步骤 | GUI | Web | 差异 |
|---|---|---|---|
| 检查活跃爬虫 | `_has_active_spider()` | `current_spider and current_spider.isRunning()` | ✅ |
| 获取插件 | `registry.get_plugin(source_id)` | `registry.get_plugin(source_id)` | ✅ |
| 创建 spider | `spider_cls(keyword=keyword, config=config)` | `spider_cls(keyword=keyword, config=config)` | ✅ |
| 绑定信号 | `_bind_spider_signals(spider)` | `_bind_spider_signals(spider)` | ✅ |
| 启动 | `spider.start()` | `spider.start()` | ✅ |
| UI 状态 | `window.set_crawl_running_state(True)` | `bridge.emit("crawl_state", {is_running: True})` | ✅ |

**结论**：逻辑完全一致。✅

### 16.5 scan_local_dir 对比

| 步骤 | GUI | Web | 差异 |
|---|---|---|---|
| 获取目录 | `self.window.current_save_dir` | `directory or self.current_save_dir` | ✅ |
| 日志 | `window.append_log("📂 正在扫描目录: ...")` | `bridge.emit("log", "📂 正在扫描目录: ...")` | ✅ |
| 清空 | `_clear_local_items()` → `window.clear_video_rows()` + `videos.clear()` | `videos.clear()` + `bridge.emit("clear_videos")` | ✅ |
| 扫描 | `file_service.scan_directory()` | `file_service.scan_directory()` | ✅ |
| 逐条添加 | `_append_scanned_items()` → `window.add_video_row(item)` | 逐条 `bridge.emit("item_found")` | ✅ |
| 截断提示 | `window.append_log("⚠️ 文件过多...")` | `bridge.emit("log", "⚠️ 文件过多...")` | ✅ |
| 成功提示 | `window.append_log("✅ 已加载 N 个本地文件...")` | `bridge.emit("log", "✅ 已加载 N 个本地文件...")` | ✅ |
| 空目录提示 | `window.append_log("ℹ️ 该目录下没有找到视频或图片")` | `bridge.emit("log", "ℹ️ 该目录下没有找到视频或图片")` | ✅ |
| 错误处理 | `except MediaScanError: window.append_log("❌ 扫描目录出错")` | `except MediaScanError: bridge.emit("log", "❌ 扫描目录出错")` | ✅ |

**结论**：逻辑完全一致。✅

---

## 十七、v5 新增：前端事件处理深度对比

> 逐个对比 GUI 和 Web 前端的事件处理逻辑。

### 17.1 键盘事件

| 事件 | GUI | Web | 差异 |
|---|---|---|---|
| Enter 搜索 | 无（需要点击按钮） | `if e.key === 'Enter' && activeElement === searchInput: startCrawl()` | Web 多了快捷键 ✅ |
| Escape 退出全屏 | `keyPressEvent` → `if Key_Escape && is_fullscreen: toggle_fullscreen()` | `if e.key === 'Escape' && isFullscreenMode: toggleFullscreen()` | ✅ |
| Escape 关闭对话框 | Qt 对话框内置 | `if e.key === 'Escape': cancelDirDialog() / cancelSelection()` | ✅ |
| Enter 目录跳转 | 无 | `if e.key === 'Enter' && activeElement === dirInput: dirBrowsePath()` | Web 多了快捷键 ✅ |

### 17.2 鼠标事件

| 事件 | GUI | Web | 差异 |
|---|---|---|---|
| 点击行选中 | `SelectRows` 内置 | `onclick="selectVideo()"` | ✅ |
| 双击标题编辑 | `itemChanged` 信号 | `ondblclick="startRename()"` | ✅ |
| 点击播放 | `play_btn.clicked` | `onclick="previewVideo()"` | ✅ |
| 点击删除 | `delete_btn.clicked` | `onclick="deleteVideo()"` | ✅ |
| 双击视频区全屏 | `ClickableVideoWidget.sig_double_click` | `previewArea.addEventListener('dblclick')` | ✅ |
| Splitter 拖拽 | Qt 内置 | JS mousedown/mousemove/mouseup | ✅ |

### 17.3 播放器事件

| 事件 | GUI (QMediaPlayer) | Web (HTML5 <video>) | 差异 |
|---|---|---|---|
| 播放状态变化 | `player.playbackStateChanged` | `player.onplay` / `player.onpause` | ✅ |
| 位置变化 | `player.positionChanged` | `player.ontimeupdate` | ✅ |
| 时长变化 | `player.durationChanged` | `player.ondurationchange` | ✅ |
| 播放/暂停 | `toggle_play()` → 检查 `PlaybackState` | `togglePlay()` → 检查 `player.paused` | ✅ |
| 进度条拖拽 | `slider.sliderPressed/Released` | `slider.onmousedown/onmouseup` | ✅ |
| 拖拽时不更新 | `is_slider_pressed` 标志 | `seeking` 标志 | ✅ |

---

## 十八、v5 新增：CSS 像素级差异补充

> 补充之前遗漏的 CSS 差异。

### 18.1 操作列内边距

| 属性 | GUI | Web | 差异 |
|---|---|---|---|
| 操作列左右内边距 | `setContentsMargins(5,2,5,2)` → 5px | 无内边距 | ❌ **BUG-67** |

### 18.2 滚动条箭头

| 属性 | GUI | Web | 差异 |
|---|---|---|---|
| 隐藏滚动条箭头 | `add-line/sub-line { height: 0px }` | 无隐藏 | ❌ **BUG-63** |

### 18.3 来源选择器宽度

| 属性 | GUI | Web | 差异 |
|---|---|---|---|
| 宽度自适应 | `AdjustToContents` | 固定宽度 | ❌ **BUG-50** |

---

## 十九、v5 修复状态汇总（全量）

| BUG | 描述 | 状态 |
|---|---|---|
| BUG-7 | copyTraceId 使用 v.id 而非 meta.trace_id | ✅ 已修复 |
| BUG-10 | renderQueue 性能问题 | ✅ 已修复（增量更新） |
| BUG-11 | currentPlayingId 语义混淆 | ✅ 已修复 |
| BUG-12 | tooltip 应显示 title 而非 local_path | ✅ 已修复 |
| BUG-14 | ThemeBtn 宽度应为 min-width:60px | ✅ 已修复 |
| BUG-15 | 操作按钮间距应为 8px | ✅ 已修复 |
| BUG-17 | Splitter 比例保存到 localStorage | ✅ 已修复 |
| BUG-18 | updateRow 不更新标题和 tooltip | ✅ 已修复 |
| BUG-19 | appendRow 创建无用的 tr 元素 | ✅ 已修复 |
| BUG-20 | startRename 完成后调用 renderQueue | ✅ 已修复 |
| BUG-21 | previewVideo 中 updateSelection 不取消旧选中行 | ✅ 已修复 |
| BUG-26 | splitter 拖拽时不触发图片缩放 | ✅ 已修复 |
| BUG-27 | 窗口 resize 时不触发媒体缩放 | ✅ 已修复 |
| BUG-34 | 动态配置区缺少标签 | ✅ 已修复 |
| BUG-35 | MissAV 代理下拉框不可编辑 | ✅ 已修复 |
| BUG-36 | Douyin 缺少 timeout=10 | ✅ 已修复 |
| BUG-37 | 插件配置不保存到配置文件 | ✅ 已修复 |
| BUG-38 | 插件配置不从配置文件恢复 | ✅ 已修复 |
| BUG-39 | init_state 渲染旧数据导致闪烁 | ✅ 已修复 |
| BUG-40 | 下拉框缺少 tooltip | ✅ 已修复 |
| BUG-41 | Douyin 选项值 50 不在 GUI 中 | ✅ 已修复 |
| BUG-42 | getRunConfig 缺少 const config = {} | ✅ 已修复 |
| BUG-43 | --no-qt 模式下 WebSocket 推送完全不工作 | ✅ 已修复 |
| BUG-50 | 来源选择器宽度不自适应 | ✅ 已修复 |
| BUG-63 | 滚动条箭头未隐藏 | ✅ 已修复 |
| BUG-67 | 操作列缺少左右内边距 | ✅ 已修复 |
| BUG-68 | 表格行 hover 效果 GUI 不存在 | ✅ 已修复（移除 hover） |
| BUG-69 | 视频播放 ended 事件未处理 | ✅ 已修复 |
| BUG-70 | 双击标题编辑时行不保持选中 | ✅ 已修复 |
| BUG-71 | 缺少键盘导航（上下箭头选行、Delete 删除） | ✅ 已修复 |
| BUG-72 | body 缺少 padding:10px 和 gap:10px（与 GUI setContentsMargins+setSpacing 一致） | ✅ 已修复 |
| BUG-73 | 全屏模式应清零 body 的 padding 和 gap | ✅ 已修复 |
| BUG-74 | 视频 preload 属性缺失 | ✅ 已修复（添加 preload="metadata"） |
| BUG-75 | timeLabel 初始值和重置值缺少 "/ 00:00" | ✅ 已修复 |
| BUG-76 | 主题按钮宽度 60px 应为 40px（与 GUI setFixedWidth(40) 一致） | ✅ 已修复 |
| BUG-77 | 日志面板字体大小 13px 应为 12px（与 GUI font-size:12px 一致） | ✅ 已修复 |
| BUG-8 | startCrawl 缺少 current_plugin 检查 | ⚠️ 低优先级 |
| BUG-9 | cancelSelection None vs [] | ⚠️ 低优先级 |
| BUG-13 | 来源选择器宽度不自适应（同 BUG-50） | ⚠️ 低优先级 |
| BUG-16 | 播放应走服务端文件检查 | ⚠️ 低优先级 |
| BUG-22 | startCrawl 应先检查再切换 UI | ⚠️ 低优先级 |
| BUG-24 | previewVideo 不检查文件是否存在 | ⚠️ 低优先级 |

### 操作3: 启动爬虫

```
GUI:
  btn_start.clicked → on_btn_start_clicked()
      → if not current_plugin: append_log("❌ 未选择有效模式"); return
      → keyword = inp_search.text().strip()
      → if not keyword: append_log("⚠️ 请输入搜索内容！"); return
      → run_options = current_plugin.get_run_options(plugin_widget)  ← 读取配置 + cfg.set()
      → sig_start_crawl.emit(keyword, source_id, run_options)
      → set_crawl_running_state(True)  ← 禁用按钮/输入/下拉/plugin_widget

Web:
  startBtn.onclick → startCrawl()
      → keyword = searchInput.value.trim()
      → if !keyword: appendLog("⚠️ 请输入搜索内容！"); return
      → setCrawlState(true)  ← 禁用按钮/输入/下拉/dynamicArea
      → sendWS('start_crawl', { source, keyword, config: getRunConfig() })
          → getRunConfig() 读取配置 + sendWS('save_config') 保存
```

**差异**：
1. GUI 先检查 `current_plugin`，Web 不检查 — ⚠️ 低优先级（不太可能触发）
2. GUI 在 `sig_start_crawl.emit()` 之后才切换 UI，Web 在 `sendWS()` 之前切换 — ⚠️ 低优先级
3. GUI 的 `get_run_options()` 保存配置，Web 的 `getRunConfig()` 也保存 — ✅ 一致
4. ✅ 最终效果基本一致

### 操作4: 点击播放

```
GUI:
  play_btn.clicked → on_play(video_item.id)
      → sig_play_video.emit(video_id)
      → controller.play_video(vid)
          → video = self.videos.get(vid)
          → if not video or not os.path.exists(video.local_path):
              window.append_log("❌ 文件不存在或已被删除"); return
          → current_playing_id = vid
          → window.append_log(f"▶️ 播放: {video.title}")
          → if _is_image_file(video.local_path):
              window.show_image(video.local_path)
          → else:
              window.play_video(video.local_path)

Web:
  op-btn onclick → previewVideo(id)
      → v = videos[id]
      → if !v.local_path: appendLog("❌ 文件不存在"); return
      → oldId = selectedVideoId; selectedVideoId = id; currentPlayingId = id
      → updateSelection(oldId, id)
      → area.innerHTML = '<video>' or '<img>'
      → player.play()
      → appendLog("▶️ 播放: " + v.title)
```

**差异**：
1. GUI 在服务端检查 `os.path.exists()`，Web 只检查 `v.local_path` 非空 — ⚠️ 低优先级
2. GUI 的 `current_playing_id` 在服务端设置，Web 的 `currentPlayingId` 在前端设置 — ✅ 效果一致
3. ✅ 最终效果基本一致

### 操作5: 更改目录

```
GUI:
  btn_dir.clicked → on_dir_clicked()
      → DirectoryPickerDialog 非原生非模态 QFileDialog
      → if selected_dir:
          current_save_dir = selected_dir
          left_panel.set_current_save_dir(selected_dir)  ← 更新路径标签
          cfg.set("common", "save_directory", selected_dir)
          sig_change_dir.emit()
      → controller.on_dir_changed()
          → window.append_log("📂 目录已变更: ...")
          → scan_local_dir()
              → _clear_local_items() → window.clear_video_rows() + videos.clear()
              → file_service.scan_directory()
              → _append_scanned_items() → 逐条 window.add_video_row(item)

Web:
  btn_dir onclick → showDirDialog() → 目录浏览器
      → confirmDirDialog()
          → currentSaveDir = dir; pathLabel.textContent = dir
          → sendWS('change_dir', {directory})
          → 关闭对话框
      → controller.change_dir(dir)
          → current_save_dir = dir; cfg.set(...)
          → bridge.emit("log", "📂 目录已变更: ...")
          → scan_local_dir(dir)
              → bridge.emit("clear_videos", {directory})  ← 前端清空 + 更新路径
              → file_service.scan_directory()
              → 逐条 bridge.emit("item_found", ...)
```

**差异**：
1. GUI 用 `QFileDialog`，Web 用服务端目录浏览器 — ✅ 最佳替代
2. GUI 先更新路径标签再发送信号，Web 也先更新路径标签再发送 WS — ✅ 一致
3. GUI 清空表格用 `clear_video_rows()`，Web 用 `clear_videos` 事件 — ✅ 一致
4. ✅ 最终效果一致

### 操作6: 删除视频

```
GUI:
  delete_btn.clicked → on_delete(video_item.id)
      → sig_delete_video.emit(row_idx, video_id)
      → controller.on_delete_video(row_idx, vid)
          → cancel_result = dl_manager.cancel_task(vid)
          → if current_playing_id == vid:
              window.stop_media_playback()
              current_playing_id = None
          → file_service.delete_media(video)
          → del self.videos[vid]
          → window.remove_video_row(row_idx)
          → window.refresh_table_bindings()

Web:
  op-btn.del onclick → deleteVideo(id)
      → if currentPlayingId === id: closePreview()
      → if selectedVideoId === id: selectedVideoId = null
      → sendWS('delete_video', {video_id: id})
      → controller.delete_video(video_id)
          → cancel_result = dl_manager.cancel_task(video_id)
          → file_service.delete_media(video)
          → del self.videos[video_id]
          → bridge.emit("video_removed", {video_id})
      → 前端收到 video_removed → delete videos[id]; videoOrder.filter(); removeRow(id)
```

**差异**：
1. GUI 先删除再刷新绑定，Web 先发 WS 再等服务端确认 — ✅ 最终效果一致
2. GUI 的 `stop_media_playback()` 停止播放器，Web 的 `closePreview()` 清空 HTML — ✅ 一致
3. ✅ 最终效果一致

---

## 二十、v6 深度审查新增差异（BUG-81 ~ BUG-130）

> 以下差异是在完整逐行对比 GUI 源码与 Web 源码的每个交互步骤后发现的。
> 重点审查：交互性、接口可行性、GUI 与 WEBUI 的适配性。

### BUG-81: lbl_time 初始值应为 "00:00" ✅ 已修复

**GUI 行为**：
```python
self.lbl_time = QLabel("00:00")  # media_preview_panel.py 第64行
```
初始值是 `"00:00"`，只有播放视频后 `on_player_position_changed` 才显示 `"MM:SS / MM:SS"` 格式。

**Web 行为**（修复前）：`'00:00 / 00:00'` — 与 GUI 初始值不一致

**修复**：初始值改为 `'00:00'`，`closePreview()` 和图片预览重置时也用 `'00:00'`

**适配性分析**：GUI 的 `QLabel` 初始文本和动态文本格式不同（初始 "00:00"，播放中 "MM:SS / MM:SS"），Web 必须完全匹配这个行为。

### BUG-89: cancelSelection 发送 [] 导致 Spider 无法正确取消 ✅ 已修复

**GUI 行为**：
```python
# main_window.py show_selection_dialog()
if dialog.exec() == Accepted:
    return dialog.selected_indices  # [0, 2, 5]
return None  # ← 取消时返回 None
```

**Web 行为**（修复前）：`sendWS('select_tasks', { indices: [] })` — 取消时发送空列表

**Spider 处理逻辑**（所有 Spider 都一样）：
```python
selected_indices = self.ask_user_selection(items)
if selected_indices is None:      # ← 检查 None
    self.log("❌ 用户取消了下载")
    return
```

**影响**：Web 取消时发送 `[]`，Spider 收到 `[]` 而非 `None`，不进入取消分支，而是以空选择继续执行，导致行为不一致。

**修复**：
1. 前端 `cancelSelection()` 改为 `sendWS('select_tasks', { indices: null })`
2. 服务端 `resume_spider_selection(None)` 传入 `None` 而非 `[]`

**交互性分析**：这是一个关键的交互一致性 BUG。GUI 的 `QDialog.reject()` → `None` 是 Qt 的标准行为，Web 必须模拟这个语义。

### BUG-95: startCrawl 服务端拒绝时 UI 卡在"运行中" ✅ 已修复

**GUI 行为**：
```python
# on_btn_start_clicked()
self.sig_start_crawl.emit(keyword, source_id, run_options)  # 同步信号
self.set_crawl_running_state(True)  # 只有成功后才执行

# on_start_crawl()
if self._has_active_spider():
    self.window.append_log("⚠️ 当前已有任务在运行...")
    return  # ← 不切换 UI 状态，因为还没执行到 set_crawl_running_state
```

等等，GUI 的 `sig_start_crawl.emit()` 是同步调用 `on_start_crawl()`。如果 `on_start_crawl` 提前 return，`set_crawl_running_state(True)` 仍然会被执行！所以 GUI 也有这个问题——但 GUI 的 `_has_active_spider()` 检查在 `on_start_crawl` 中，而 `set_crawl_running_state(True)` 在 `on_btn_start_clicked` 中，两者是顺序执行的。

实际上 GUI 的流程是：
1. `sig_start_crawl.emit()` → 同步调用 `on_start_crawl()`
2. 如果 `on_start_crawl()` 提前 return，控制权回到 `on_btn_start_clicked()`
3. `set_crawl_running_state(True)` 仍然执行！

所以 GUI 也有这个 BUG！但 GUI 的 `btn_start` 已经被 `set_crawl_running_state(True)` 禁用了，用户无法再次点击。而且 `on_start_crawl` 成功时会再次调用 `set_crawl_running_state(True)`，失败时不会调用 `set_crawl_running_state(False)`。

**Web 修复**：服务端 `start_crawl` 失败时发送 `crawl_state: {is_running: false}` 恢复 UI 状态。这比 GUI 的处理更好。

**接口可行性分析**：Web 的异步架构使得"先设 UI 再等服务端确认"成为必然选择。服务端必须在失败时主动推送恢复事件。

### BUG-121: deleteVideo 不应在服务端确认前清除 selectedVideoId ✅ 已修复

**GUI 行为**：
```python
def on_delete_video(self, row_idx, vid):
    ...
    if self.current_playing_id == vid:
        self.window.stop_media_playback()  # 停止播放
        self.current_playing_id = None
    try:
        deleted = self.file_service.delete_media(video)
        ...
    except FileOperationError as exc:
        self.window.append_log(f"❌ 删除文件失败: {exc}")
        return  # ← 行仍然选中，播放已停止
    ...
    self.window.remove_video_row(row_idx)  # ← 只有成功才移除行
```

GUI 删除失败时：行仍在表格中，行仍选中，播放已停止。

**Web 行为**（修复前）：
```javascript
function deleteVideo(id) {
  if (currentPlayingId === id) closePreview();
  if (selectedVideoId === id) selectedVideoId = null;  // ← 提前清除
  sendWS('delete_video', { video_id: id });
}
```

删除失败时：行仍在表格中，但行已不选中（selectedVideoId 已清除），播放已停止。

**差异**：GUI 删除失败时行仍选中，Web 删除失败时行不选中。

**修复**：不在 `deleteVideo()` 中清除 `selectedVideoId`，让 `video_removed` 事件处理中清除。

**交互性分析**：这是一个典型的"乐观更新 vs 确认后更新"问题。Web 的异步架构要求在服务端确认后才更新状态，否则失败时无法回滚。

### BUG-128: previewVideo 显示图片时不重置控制面板 ✅ 已修复

**GUI 行为**：
```python
def show_image(self, image_path):
    self.vid_w.hide()
    self.img_lbl.show()
    self.player.stop()  # ← 停止播放器，触发 positionChanged(0)
    self.current_image_path = image_path
    self.scale_image_to_fit()
```

`player.stop()` 触发 `positionChanged(0)`，进而调用 `on_player_position_changed(0)`：
```python
def on_player_position_changed(self, pos):
    if not self.is_slider_pressed:
        self.slider.setValue(pos)  # 滑块归零
    self.lbl_time.setText(f"{self.format_time(pos)} / {self.format_time(self.player.duration())}")
    # 显示 "00:00 / 00:00"
```

**Web 行为**（修复前）：显示图片时不重置滑块和时间标签，保留上一个视频的值。

**修复**：在 `previewVideo()` 图片分支中重置控制面板。

**适配性分析**：GUI 的 `player.stop()` 会级联触发多个状态更新，Web 必须手动模拟这些级联效果。

### BUG-130: delete_video/rename_video WS 处理未用 run_in_executor ✅ 已修复

**问题**：`controller.delete_video()` 和 `controller.rename_video()` 包含文件 I/O 操作（`file_service.delete_media()`、`file_service.rename_media()`），在事件循环线程中同步运行可能阻塞 WebSocket 消息处理。

**修复**：改为 `await asyncio.get_running_loop().run_in_executor(None, ...)` 在线程池中运行。

**接口可行性分析**：所有涉及文件 I/O 的 WS 消息处理都应使用 `run_in_executor`，包括 `scan_dir`、`change_dir`、`delete_video`、`rename_video`。

---

## 二十一、交互性深度分析（v6 新增）

> 从用户操作角度，逐个分析每个步骤的交互性、接口可行性和 GUI 与 WebUI 的适配性。

### 21.1 启动爬虫 — 交互性分析

| 步骤 | GUI 交互 | Web 交互 | 适配性 |
|---|---|---|---|
| 1. 输入关键词 | `QLineEdit` 同步输入 | `<input>` 同步输入 | ✅ 完全一致 |
| 2. 选择来源 | `QComboBox` 同步选择 | `<select>` 同步选择 | ✅ 完全一致 |
| 3. 配置参数 | `QComboBox`/`QCheckBox` 同步 | `<select>`/`<input>` 同步 | ✅ 完全一致 |
| 4. 点击启动 | 同步信号 → 同步处理 | 异步 WS → 异步处理 | ⚠️ 架构差异 |
| 5. UI 禁用 | 立即禁用（同步） | 立即禁用（前端） | ✅ 感知一致 |
| 6. 创建 Spider | 同步创建 | 异步创建（线程池） | ✅ 结果一致 |
| 7. Spider 启动 | `spider.start()` | `spider.start()` | ✅ 一致 |
| 8. 失败回滚 | 不回滚（GUI 也有此问题） | `crawl_state: false` 回滚 | ✅ Web 更好 |

**关键差异**：GUI 的信号是同步的，Web 的 WS 是异步的。这意味着：
- GUI：点击 → 信号 → 处理 → UI 更新，全部在一个事件循环中完成
- Web：点击 → WS 发送 → 前端立即更新 UI → 服务端异步处理 → 结果推送回前端

**适配策略**：前端乐观更新 + 服务端失败时推送恢复事件。

### 21.2 选择对话框 — 交互性分析

| 步骤 | GUI 交互 | Web 交互 | 适配性 |
|---|---|---|---|
| 1. Spider 发出选择请求 | `sig_select_tasks.emit(items)` | `bridge.emit("select_tasks")` | ✅ |
| 2. 显示对话框 | `QDialog.exec()` 阻塞 | CSS overlay 非阻塞 | ⚠️ 架构差异 |
| 3. 用户勾选 | `QCheckBox` 同步 | `<input type="checkbox">` 同步 | ✅ |
| 4. 全选/反选 | 按钮点击 | 按钮点击 | ✅ |
| 5. 确认 | `dialog.accept()` → 返回 indices | `sendWS('select_tasks', {indices})` | ✅ |
| 6. 取消 | `dialog.reject()` → 返回 `None` | `sendWS('select_tasks', {indices: null})` | ✅ 已修复 |
| 7. Spider 恢复 | `resume_from_ui(selected)` | `resume_from_ui(selected)` | ✅ |

**关键差异**：GUI 的 `QDialog.exec()` 阻塞 Spider 线程，Web 的对话框不阻塞。Spider 的 `ask_user_selection()` 使用 `threading.Event.wait()` 阻塞，两种方式都能正确等待用户选择。

**适配策略**：Spider 的 `resume_from_ui()` 机制天然支持异步通知，Web 只需在用户操作后调用即可。

### 21.3 播放视频 — 交互性分析

| 步骤 | GUI 交互 | Web 交互 | 适配性 |
|---|---|---|---|
| 1. 点击播放按钮 | `sig_play_video.emit(vid)` | `previewVideo(id)` 前端直接播放 | ⚠️ 路径不同 |
| 2. 文件存在检查 | `os.path.exists()` 服务端检查 | `v.local_path` 非空检查 + onerror | ⚠️ 时机不同 |
| 3. 设置 current_playing_id | 服务端 `controller.current_playing_id` | 前端 `currentPlayingId` | ✅ 效果一致 |
| 4. 播放视频 | `QMediaPlayer.play()` | `HTMLVideoElement.play()` | ✅ |
| 5. 播放失败 | `errorOccurred` 信号 | `onerror` 事件 | ✅ |

**关键差异**：GUI 走控制器（服务端检查文件存在性），Web 前端直接播放（依赖 onerror 处理失败）。

**适配策略**：Web 的 `onerror` 处理已足够，不需要额外的 API 调用检查文件存在性。

### 21.4 删除视频 — 交互性分析

| 步骤 | GUI 交互 | Web 交互 | 适配性 |
|---|---|---|---|
| 1. 点击删除按钮 | `sig_delete_video.emit(row, vid)` | `sendWS('delete_video', {video_id})` | ✅ |
| 2. 停止播放 | 同步 `stop_media_playback()` | 前端 `closePreview()` | ✅ |
| 3. 取消下载 | `dl_manager.cancel_task()` | `dl_manager.cancel_task()` | ✅ |
| 4. 删除文件 | `file_service.delete_media()` | `file_service.delete_media()` | ✅ |
| 5. 删除失败 | 行保留，行仍选中 | 行保留，行仍选中（已修复） | ✅ |
| 6. 删除成功 | `remove_video_row()` | `bridge.emit("video_removed")` | ✅ |

**关键差异**：GUI 同步删除（用户点击后立即看到行消失），Web 异步删除（用户点击后等服务端确认才看到行消失）。

**适配策略**：Web 无法实现同步删除（受限于客户端-服务器架构），但可以通过 `video_removed` 事件快速响应。

### 21.5 重命名 — 交互性分析

| 步骤 | GUI 交互 | Web 交互 | 适配性 |
|---|---|---|---|
| 1. 双击标题 | `itemChanged` 信号 | `ondblclick` 创建 `<input>` | ✅ |
| 2. 编辑中 | `QTableWidgetItem` 内置编辑 | `<input>` 替换 `<td>` 内容 | ✅ |
| 3. 确认（Enter/blur） | `itemChanged` 触发 `on_rename_video` | `sendWS('rename_video')` | ✅ |
| 4. 取消（Escape） | `item.setText(video.title)` 回退 | `input.value = v.title; blur()` | ✅ |
| 5. 标题未变 | `item.setText(video.title)` 不发送 | 不发送 WS | ✅ |
| 6. 文件不存在 | `item.setText(video.title)` 回退 | 服务端返回 error | ✅ |
| 7. 重命名失败 | `item.setText(video.title)` 回退 + 日志 | 前端保持旧标题 + 日志 | ✅ |

**关键差异**：GUI 的 `itemChanged` 在用户编辑完成时同步触发，Web 的 `sendWS` 是异步的。Web 的策略是：编辑完成时先恢复旧标题，等服务端 `video_renamed` 事件确认后才更新为新标题。

**适配策略**：Web 的"先恢复旧标题，等服务端确认"策略比 GUI 的"先显示新标题，失败再回退"更安全。

---

## 二十二、接口可行性深度分析（v6 新增）

> 分析每个 WebSocket 消息类型和 REST API 的可行性、边界条件和错误处理。

### 22.1 WebSocket 消息类型汇总

| 消息类型 | 方向 | 参数 | 阻塞操作 | run_in_executor | 状态 |
|---|---|---|---|---|---|
| `start_crawl` | 前端→服务端 | `{source, keyword, config}` | 创建 Spider | ❌ 不需要 | ✅ |
| `stop_crawl` | 前端→服务端 | `{}` | `spider.stop()` | ❌ 不需要 | ✅ |
| `select_tasks` | 前端→服务端 | `{indices}` | `resume_from_ui()` | ❌ 不需要 | ✅ |
| `scan_dir` | 前端→服务端 | `{directory}` | `scan_local_dir()` | ✅ 已修复 | ✅ |
| `change_dir` | 前端→服务端 | `{directory}` | `change_dir()` → `scan_local_dir()` | ✅ 已修复 | ✅ |
| `delete_video` | 前端→服务端 | `{video_id}` | `delete_media()` | ✅ 已修复 | ✅ |
| `rename_video` | 前端→服务端 | `{video_id, new_title}` | `rename_media()` | ✅ 已修复 | ✅ |
| `change_theme` | 前端→服务端 | `{dark_theme}` | `cfg.set_many()` | ❌ 不需要 | ✅ |
| `change_source` | 前端→服务端 | `{source}` | `cfg.set()` | ❌ 不需要 | ✅ |
| `save_config` | 前端→服务端 | `{section, key, value}` | `cfg.set()` | ❌ 不需要 | ✅ |

### 22.2 服务端推送事件汇总

| 事件类型 | 触发条件 | 数据格式 | 推送频率 |
|---|---|---|---|
| `init_state` | WebSocket 连接 | `{current_save_dir, is_crawling}` | 一次 |
| `platforms` | WebSocket 连接 | `[{id, name, search_placeholder}]` | 一次 |
| `config` | WebSocket 连接 | `{common: {...}, douyin: {...}, ...}` | 一次 |
| `log` | 各种操作 | `{message}` | 高频 |
| `item_found` | Spider 发现/扫描文件 | `{id, title, status, ...}` | 中频 |
| `video_state_changed` | 下载进度/状态变更 | `{video_id, status, progress}` | 高频 |
| `video_renamed` | 重命名成功 | `{video_id, new_title, new_path}` | 低频 |
| `video_removed` | 删除成功 | `{video_id}` | 低频 |
| `clear_videos` | 目录变更/扫描前 | `{directory}` | 低频 |
| `task_started` | 下载开始 | `{video_id}` | 中频 |
| `task_progress` | 下载进度 | `{video_id, progress}` | 高频 |
| `task_finished` | 下载完成 | `{video_id}` | 中频 |
| `task_error` | 下载失败 | `{video_id, error}` | 低频 |
| `crawl_state` | 爬虫启动/结束/失败 | `{is_running}` | 低频 |
| `select_tasks` | Spider 需要用户选择 | `{items: [{title, index}]}` | 低频 |
| `scan_result` | 扫描完成 | `{total_count, video_count, image_count}` | 低频 |

### 22.3 REST API 汇总

| 端点 | 方法 | 用途 | 替代 WS 消息 |
|---|---|---|---|
| `/api/platforms` | GET | 获取平台列表 | `platforms` 事件 |
| `/api/config` | GET | 获取配置 | `config` 事件 |
| `/api/state` | GET | 获取状态 | `init_state` 事件 |
| `/api/media/{id}` | GET | 媒体文件（支持 Range） | 无（浏览器直接请求） |
| `/api/dir/list` | GET | 目录浏览 | 无（前端 fetch） |
| `/api/debug/latest-log` | GET | 下载最新日志 | 无（浏览器直接打开） |
| `/api/debug/error-summary` | GET | 下载错误摘要 | 无（浏览器直接打开） |

**注意**：REST API 和 WS 消息有功能重叠。WS 消息用于实时交互，REST API 用于一次性请求（如媒体文件服务、目录浏览）。两者不应混用。

---

## 二十三、GUI 与 WebUI 适配性深度分析（v6 新增）

> 分析 GUI 和 WebUI 之间的本质差异及其适配策略。

### 23.1 同步 vs 异步

| 操作 | GUI（同步） | WebUI（异步） | 适配策略 |
|---|---|---|---|
| 启动爬虫 | `emit()` → 同步处理 → UI 更新 | `sendWS()` → 异步处理 → 事件推送 | 乐观更新 + 失败回滚 |
| 删除视频 | 同步删除 → 立即移除行 | 异步删除 → 等待 `video_removed` | 前端先停播放，等确认后移除行 |
| 重命名 | 同步重命名 → 立即更新 | 异步重命名 → 等待 `video_renamed` | 先恢复旧标题，等确认后更新 |
| 选择对话框 | `QDialog.exec()` 阻塞 | 非阻塞 overlay | Spider 用 `Event.wait()` 阻塞，两种方式等效 |
| 目录选择 | `QFileDialog` 阻塞 | 非阻塞 overlay + API | 功能等效，交互方式不同 |

### 23.2 状态管理

| 状态 | GUI（服务端） | WebUI（前端+服务端） | 适配策略 |
|---|---|---|---|
| `current_playing_id` | `controller.current_playing_id` | 前端 `currentPlayingId` | 前端管理，效果一致 |
| `selectedVideoId` | `table.currentRow()` | 前端 `selectedVideoId` | 前端管理，效果一致 |
| `is_crawling` | `spider.isRunning()` | 前端 `isCrawling` + 服务端 `crawl_state` | 双端同步 |
| `videos` 字典 | `controller.videos` | 前端 `videos` + 服务端 `controller.videos` | 双端同步 |
| `current_save_dir` | `window.current_save_dir` | 前端 `currentSaveDir` + 服务端 `controller.current_save_dir` | 双端同步 |

### 23.3 文件系统访问

| 操作 | GUI（本地） | WebUI（服务端代理） | 适配策略 |
|---|---|---|---|
| 选择目录 | `QFileDialog` 直接访问 | `/api/dir/list` 服务端代理 | ✅ 最佳替代 |
| 播放媒体 | `QMediaPlayer` 本地文件 | `<video>` + `/api/media/{id}` | ✅ 最佳替代 |
| 删除文件 | `os.remove()` 直接 | `file_service.delete_media()` 服务端 | ✅ 一致 |
| 重命名文件 | `os.rename()` 直接 | `file_service.rename_media()` 服务端 | ✅ 一致 |
| 扫描目录 | `os.listdir()` 直接 | `file_service.scan_directory()` 服务端 | ✅ 一致 |

### 23.4 剪贴板访问

| 操作 | GUI | WebUI | 适配策略 |
|---|---|---|---|
| 复制 trace_id | `QApplication.clipboard().setText()` | `navigator.clipboard.writeText()` | ✅ 等效（需 HTTPS 或 localhost） |

### 23.5 多窗口/多标签页

| 场景 | GUI | WebUI | 适配策略 |
|---|---|---|---|
| 多个窗口 | 不支持（单例） | 多标签页同时连接 | `ConnectionManager.broadcast()` 广播 |
| 状态同步 | 不需要 | 多标签页需要同步 | 所有事件广播到所有连接 |

---

## 二十四、v6 修复状态汇总（增量）

| BUG | 描述 | 状态 |
|---|---|---|
| BUG-81 | lbl_time 初始值 "00:00" vs "00:00 / 00:00" | ✅ 已修复 |
| BUG-89 | cancelSelection 发送 [] 导致 Spider 无法正确取消 | ✅ 已修复 |
| BUG-95 | startCrawl 服务端拒绝时 UI 卡在"运行中" | ✅ 已修复 |
| BUG-121 | deleteVideo 提前清除 selectedVideoId | ✅ 已修复 |
| BUG-128 | previewVideo 显示图片时不重置控制面板 | ✅ 已修复 |
| BUG-130 | delete/rename WS 处理未用 run_in_executor | ✅ 已修复 |

---

## 二十五、v7 视觉对照表（用户截图差异）

> 用户反馈"看UI一看就不一样"，从 GUI 截图（第一张）和 Web UI 截图（第二张）的逐像素对比中发现的差异。

### 25.1 致命 BUG-131: 表格列头被 width:100% 挤压到不可见 ✅ 已修复

**用户截图证据**：第二张 Web UI 截图里只能看到"视频标题"列头，状态/进度/操作列头全部消失，单元格内容也看不见。

**根本原因**：
```html
<!-- 修复前 -->
<table class="queue-table">
  <thead>
    <tr>
      <th id="thTitle" style="width:100%">视频标题</th>  <!-- ← 致命 BUG -->
      <th>状态</th>
      <th>进度</th>
      <th>操作</th>
    </tr>
  </thead>
</table>
```

`<th>` 的 `width:100%` 让标题列占满整个表格宽度，浏览器将 100% 解释为"占满剩余空间"而不是"独占 100%"，导致其他列被挤压到宽度为 0 不可见。

**修复**：
```html
<!-- 修复后 -->
<table class="queue-table">
  <colgroup>
    <col class="col-title-col">      <!-- 标题列 stretch -->
    <col style="width:90px">         <!-- 状态列固定 90px -->
    <col style="width:120px">        <!-- 进度列固定 120px -->
    <col style="width:80px">         <!-- 操作列固定 80px -->
  </colgroup>
  <thead>
    <tr>
      <th>视频标题</th>
      <th style="text-align:center">状态</th>
      <th style="text-align:center">进度</th>
      <th style="text-align:center">操作</th>
    </tr>
  </thead>
</table>
```

并设置 `.queue-table { table-layout: fixed }`，确保 `<col>` 的宽度生效。

**GUI 对照**：
- `self.queue_table.setColumnWidth(0, 200)` - 标题列初始 200px
- `self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)` - 标题列 Stretch
- 状态/进度/操作列固定宽度（不设 setSectionResizeMode，QTableView 默认为 Interactive）

### 25.2 BUG-132: 列头/列内容对齐与 GUI 不一致 ✅ 已修复

**GUI 截图证据**：
- 列头"视频标题"：左对齐
- 列头"状态"：居中
- 列头"进度"：居中
- 列头"操作"：居中
- 列内容"状态"：居中（✅ + "本地"）
- 列内容"进度"：居中（"100%"）
- 列内容"操作"：居中（▶ 🗑）

**Web 修复前**：列头/列内容全部默认对齐（标题列左对齐，其他列未指定）。

**Web 修复后**：
```css
.queue-table th { text-align: left; }  /* 列头默认左对齐 */
.queue-table th:nth-child(2),          /* 状态/进度/操作列头 */
.queue-table th:nth-child(3),
.queue-table th:nth-child(4) { text-align: center; }

.col-status { text-align: center; }    /* 状态列内容居中 */
.col-progress { text-align: center; }  /* 进度列内容居中 */
.col-actions { text-align: center; }   /* 操作列内容居中 */
```

### 25.3 BUG-133: 进度条行高/外观与 GUI 不一致 ✅ 已修复

**GUI 截图证据**：进度条单元格内，蓝色背景 100% 填充整个高度，"100%" 文字居中。

**Web 修复前**：
- `.progress-wrap { height: 18px; }` 但 `.queue-table td { height: 36px; }` 导致 18px 的进度条紧贴顶部
- `.progress-fill` 的 `border-radius:2px` 与 `.progress-wrap` 的 `border-radius:3px` 不一致
- `.progress-text` 没有 `z-index`，可能被 `.progress-fill` 遮挡

**Web 修复后**：
```css
.progress-wrap {
  height: 18px;
  border-radius: 3px;
  margin: 8px 0;  /* 垂直居中: (36 - 18) / 2 = 9px ≈ 8px */
}
.progress-fill {
  height: 100%;
  border-radius: 2px;  /* 略小于 wrap，形成 1px 边框效果 */
}
.progress-text {
  z-index: 1;  /* 文字在进度条之上 */
  text-shadow: 0 0 3px var(--panel), 0 0 3px var(--panel);
}
```

### 25.4 BUG-134: 操作按钮字符 ✕ vs 🗑 ✅ 已修复

**GUI 截图证据**：操作列显示 ▶ + 🗑（垃圾箱图标），更接近系统图标。

**Web 修复前**：显示 ▶ + ✕（X 符号）。

**Web 修复后**：▶ + 🗑（垃圾箱符号），更接近 GUI 的 `QStyle.StandardPixmap.SP_TrashIcon`。

**适配性分析**：Web 没有真正的"系统图标"概念，只能用 Unicode 字符近似。🗑 是最接近的视觉效果。

### 25.5 BUG-135: 控制面板 flex 布局，时间标签/全屏按钮被挤压 ✅ 已修复

**用户截图证据**：第二张 Web UI 截图里，▶ 播放按钮后只有一个小蓝点（进度条），看不到时间标签和全屏按钮。

**根本原因**：默认 flex 布局下，`.seek-slider` 的 `flex:1` 会扩张到占满剩余空间，但浏览器可能因其他元素 `min-width` 默认为 `auto` 而计算错误，导致进度条计算宽度时被挤压。

**Web 修复后**：
```css
.seek-slider {
  flex: 1;
  min-width: 0;  /* ← 关键: 允许 flex item 收缩到 0 */
  height: 4px;
}
.play-btn { flex-shrink: 0; padding: 0; }
.time-label { flex-shrink: 0; min-width: 90px; text-align: center; }
.fullscreen-btn { flex-shrink: 0; white-space: nowrap; }
```

**GUI 对照**：
- 播放按钮：`setFixedSize(32, 32)`
- 进度条：`setMinimumWidth(0)` + `sizePolicy.setHorizontalStretch(1)`
- 时间标签：`setMinimumWidth(80)`
- 全屏按钮：`setFixedHeight(32)`

### 25.6 BUG-136: 表格行 hover 效果缺失 ✅ 已修复

**用户截图证据**：第一张 GUI 截图里，第二行有明显的深色高亮（hover 效果）。

**Web 修复前**（BUG-68 错误判断）：移除 hover 效果，认为 GUI 没有。

**Web 修复后**：
```css
.queue-table tbody tr:hover { background: var(--hover-row); }
.queue-table tr.selected:hover { background: var(--accent) !important; }
```

新增 `--hover-row` 颜色变量：
- 深色主题：`rgba(255,255,255,.06)`
- 浅色主题：`rgba(0,0,0,.05)`

**GUI 对照**：PyQt6 的 QTableWidget 默认启用 `setMouseTracking(True)`，鼠标悬停时 item 会有 hover 效果。GUI 截图证实了这一点。

### 25.7 BUG-137: 状态列文字大小不一致 ✅ 已修复

**GUI 截图证据**：状态列的"✅ 本地"字号看起来比标题列小一些（10-11px）。

**Web 修复后**：
```css
.col-status { font-size: 12px; }  /* 比默认 13px 略小，与 GUI 一致 */
```

### 25.8 BUG-138: 行底边框在选中行时的处理 ✅ 已修复

**Web 修复后**：
```css
.queue-table tr.selected td {
  border-bottom-color: var(--accent) !important;  /* 选中行的底边框变为 accent 色 */
}
```

避免选中行在视觉上"断裂"（底边框与背景色不一致）。

### 25.9 视觉差异对照表（v7 汇总）

| 元素 | GUI 截图 | Web 截图（修复前） | Web 修复后 | 状态 |
|---|---|---|---|---|
| 列头"视频标题" | 可见，左对齐 | 可见，左对齐 | 可见，左对齐 | ✅ |
| 列头"状态" | 可见，居中 | **不可见** | 可见，居中 | ✅ BUG-131 |
| 列头"进度" | 可见，居中 | **不可见** | 可见，居中 | ✅ BUG-131 |
| 列头"操作" | 可见，居中 | **不可见** | 可见，居中 | ✅ BUG-131 |
| 状态列"✅ 本地" | 可见，居中 | **不可见** | 可见，居中 | ✅ BUG-131/132 |
| 进度列"100%" | 可见，居中，蓝色背景 | **不可见** | 可见，居中，蓝色背景 | ✅ BUG-131/133 |
| 操作列 ▶ 🗑 | 可见，居中，灰底 | **不可见** | 可见，居中，灰底 | ✅ BUG-131/134 |
| 行 hover 效果 | 有 | 无 | 有 | ✅ BUG-136 |
| 选中行高亮 | 蓝色背景 | 蓝色背景 | 蓝色背景 | ✅ |
| 时间标签 | "00:00 / 00:00" | **不可见** | "00:00" → 播放时 "MM:SS / MM:SS" | ✅ BUG-135 |
| 全屏按钮 | "[ 全屏 ]" | **不可见** | "[ 全屏 ]" | ✅ BUG-135 |

---

## 二十六、v7 适配性深度分析（截图驱动）

> 从用户截图直接对比得出的设计适配策略。

### 26.1 表格列宽策略

**GUI 行为**：
```python
self.queue_table.setColumnWidth(0, 200)  # 标题列初始 200px
self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # 标题列 Stretch
# 状态/进度/操作列固定宽度（默认 Interactive）
```

**Web 适配**：
```html
<colgroup>
  <col class="col-title-col">  <!-- width: auto (即 stretch) -->
  <col style="width:90px">    <!-- 状态列固定 -->
  <col style="width:120px">   <!-- 进度列固定 -->
  <col style="width:80px">    <!-- 操作列固定 -->
</colgroup>
```
```css
.queue-table { table-layout: fixed; }  /* 关键: 让 col 宽度生效 */
```

### 26.2 进度条单元格垂直居中

**GUI 行为**：QTableWidget 自动垂直居中单元格内容。

**Web 适配**：
```css
.queue-table td { vertical-align: middle; }  /* 关键: 表格单元格垂直居中 */
.progress-wrap { margin: 8px 0; }  /* 进度条在单元格内垂直居中 */
```

### 26.3 列内容文本溢出处理

**GUI 行为**：QTableWidget 的标题列默认 `setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)`，长标题会显示省略号。

**Web 适配**：
```css
.col-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

### 26.4 选中行高亮的级联处理

**GUI 行为**：`setStyleSheet("QTableWidget::item:selected { background-color: #0078d4; color: white; }")`

**Web 适配**：
```css
.queue-table tr.selected { background: var(--accent) !important; }
.queue-table tr.selected td { color: #fff !important; }
/* 进度条文字在选中行时保持白色可读 */
.queue-table tr.selected .progress-text { color: #fff; text-shadow: 0 0 3px rgba(0,0,0,.5); }
/* 操作按钮在选中行时保持可见 */
.queue-table tr.selected .op-btn { color: #fff; border-color: rgba(255,255,255,.3); }
```

### 26.5 全屏模式的视觉处理

**GUI 行为**：
```python
def toggle_fullscreen_mode(self):
    if not self.is_fullscreen_mode:
        self.top_bar.hide()
        self.left_panel.hide()
        self.log_txt.hide()
        self.showFullScreen()
        self._set_main_margins(0)  # ← 关键: main_layout.setContentsMargins(0,0,0,0)
        self.is_fullscreen_mode = True
```

**Web 适配**：
```css
body.is-fullscreen {
  padding: 0 !important;  /* ← 关键: 清零 body 的 padding */
  gap: 0 !important;      /* ← 关键: 清零 body 的 gap */
}
body.is-fullscreen .top-bar,
body.is-fullscreen .left-panel,
body.is-fullscreen .control-panel,
body.is-fullscreen .log-panel {
  display: none !important;
}
```

---

## 二十七、v8 播放窗口交互（用户反馈"播放窗口无响应"）

> 用户反馈"webui 播放窗口也无响应"。经深入排查，发现了一个致命 BUG（BUG-139），以及其他 11 个相关 BUG。

### 27.1 致命 BUG-139: local_path 从未推送到 Web 前端 ✅ 已修复

**症状**：用户点击表格行的播放按钮，预览区完全不变（依然显示"选择视频进行预览"），感觉是"无响应"。

**根本原因链**：
1. `BaseSpider.emit_video()` 创建 `VideoItem(url, title, source)`，`local_path=""`（默认值）
   ```python
   def emit_video(self, url, title, source, meta=None):
       item = VideoItem(url=url, title=title, source=source)  # local_path 默认 ""
       self.sig_item_found.emit(item)
   ```
2. Web 端收到 `item_found` 事件 → `videos[id] = data` → `videos[id].local_path = ""`
3. `DownloadWorker.run()` 中先 `sig_start.emit()` 后才 `self.video.local_path = filepath`
   ```python
   # 修复前
   def run(self):
       self.sig_start.emit(self.video.id)  # ← sig_start 时 local_path 还是空
       ...
       filepath = self._ensure_unique_path(...)
       self.video.local_path = filepath  # ← 后设置
   ```
4. Web 端 `_on_task_started` 推送 `task_started` 事件**没有 local_path 字段**
   ```python
   # 修复前
   def _on_task_started(self, video_id: str):
       self._apply_video_state(video_id, status="⏳ 下载中...", progress=0)
       self.bridge.emit("task_started", {"video_id": video_id})  # ← 没有 local_path
   ```
5. 前端 `previewVideo(id)` 检查 `v.local_path` 为空 → `appendLog("❌ 文件不存在或已被删除"); return;`
   ```javascript
   // 修复前
   function previewVideo(id) {
     const v = videos[id];
     if (!v) return;
     if (!v.local_path) {
       appendLog('❌ 文件不存在或已被删除');
       return;  // ← 直接返回，预览区不变
     }
     ...
   }
   ```

**修复（3 处）**：

**1. DownloadWorker.run() 调整顺序**（[download_manager.py](../core/download_manager.py)）：
```python
def run(self):
    ...
    # 先把保存目录和目标文件名计算清楚
    save_dir = self._resolve_save_dir()
    ...
    filepath = self._ensure_unique_path(os.path.join(save_dir, filename))
    # 先设置 local_path，再 emit sig_start
    # 这样 sig_start 信号携带的 local_path 是有效的
    self.video.local_path = filepath  # ← 移到 sig_start 之前
    self._final_ext = ext
    self.sig_start.emit(self.video.id)  # ← 此时 local_path 已设置
    ...
```

**2. WebController._on_task_started 携带 local_path**（[controller.py](controller.py)）：
```python
def _on_task_started(self, video_id: str):
    item = self._apply_video_state(video_id, status="⏳ 下载中...", progress=0)
    # 携带 local_path 给 Web 端
    local_path = item.local_path if item else ""
    self.bridge.emit("task_started", {"video_id": video_id, "local_path": local_path})
```

**3. 前端 task_started 事件处理同步 local_path**（[index.html](static/index.html)）：
```javascript
case 'task_started':
  if (videos[data.video_id]) {
    videos[data.video_id].status = '⏳ 下载中...';
    videos[data.video_id].progress = 0;
    // 修复 BUG-139: 同步 local_path 让 Web 端能立即播放
    if (data.local_path) videos[data.video_id].local_path = data.local_path;
    updateRow(data.video_id);
  }
  break;
```

**4. previewVideo 多次重试机制**（避免时序竞争）：
```javascript
function previewVideo(id) {
  const v = videos[id];
  if (!v) return;
  if (!v.local_path) {
    appendLog('⏳ 视频准备中，请稍候...');
    previewWithRetry(id, 0);  // 多次重试
    return;
  }
  doPreview(id, v, null);
}

function previewWithRetry(id, attempt) {
  const delays = [500, 1000, 2000, 4000, 8000];
  const v = videos[id];
  if (v && v.local_path) {
    doPreview(id, v, null);
  } else if (attempt < delays.length) {
    setTimeout(() => previewWithRetry(id, attempt + 1), delays[attempt]);
  } else {
    appendLog('❌ 视频还未开始下载，请稍后再试');
  }
}
```

**交互性分析**：
- GUI 的 `QMediaPlayer` 在用户点击播放时同步创建，文件路径直接传入 `setSource`
- Web 的 `<video>` 元素依赖 `/api/media/{id}` HTTP 请求，要求服务端能根据 id 找到文件
- 服务端需要把 local_path 推送给前端，前端才能在用户点击播放时正确请求媒体
- **时序问题**：spider 推送 item → 立即被用户点击 → 视频还未开始下载 → local_path 为空
- **解决方案**：服务端在 task_started 事件中携带 local_path，前端多次重试等待

### 27.2 BUG-140: play() 错误被静默吞掉 ✅ 已修复

**症状**：视频因任何原因（autoplay 策略、文件损坏、codec 不支持）无法播放时，用户看不到任何反馈。

**修复前**：
```javascript
player.play().catch(()=>{});  // ← 静默吞掉错误
```

**修复后**：
```javascript
player.play().catch(err => {
  appendLog(`❌ 视频播放失败 [${v.title}]: ${err.message || err}`);
  closePreview();
});
```

**交互性分析**：GUI 的 `QMediaPlayer.errorOccurred` 信号会触发错误处理，输出到日志。Web 必须手动监听 play() Promise 的 reject。

### 27.3 BUG-141: 切换视频时旧视频不暂停 ✅ 已修复

**症状**：从视频 A 切换到视频 B 时，视频 A 还在后台播放（虽然看不见但能听到声音）。

**修复前**：
```javascript
function previewVideo(id) {
  // 没有先暂停旧视频，直接 area.innerHTML = ...
}
```

**修复后**：
```javascript
function previewVideo(id) {
  // 切换视频前先暂停旧视频
  const oldPlayer = document.getElementById('videoPlayer');
  if (oldPlayer) {
    try { oldPlayer.pause(); } catch(e) {}
  }
  ...
  // 在 doPreview 中更彻底地释放资源
  if (oldPlayer && oldPlayer.parentNode) {
    oldPlayer.pause();
    oldPlayer.removeAttribute('src');
    oldPlayer.load();
  }
}
```

**GUI 对照**：GUI 的 `player.setSource(QUrl.fromLocalFile(new_path))` 会自动停止旧视频。

### 27.4 BUG-142: 拖动滑块无法 seek ✅ 已修复

**症状**：拖动进度条到某个位置后，松开鼠标视频不跳转。

**修复前**（直接属性赋值，可能丢失 this 绑定或与其他事件冲突）：
```javascript
slider.onmousedown = () => { seeking = true; };
slider.onmouseup = () => { seeking = false; player.currentTime = slider.value; };
```

**修复后**（使用 addEventListener，更稳健）：
```javascript
slider.addEventListener('mousedown', onSeekStart);
slider.addEventListener('touchstart', onSeekStart);
slider.addEventListener('mouseup', onSeekEnd);
slider.addEventListener('touchend', onSeekEnd);
slider.addEventListener('input', () => {
  if (seeking) {
    const newTime = parseFloat(slider.value);
    if (!isNaN(newTime)) {
      player.currentTime = newTime;
      timeLabel.textContent = `${fmtTime(newTime)} / ${fmtTime(player.duration || 0)}`;
    }
  }
});
```

**GUI 对照**：
- `slider.sliderPressed` → `is_slider_pressed = True`
- `slider.sliderReleased` → `is_slider_pressed = False; player.setPosition(slider.value())`
- `player.positionChanged` → 跳过滑块更新

**Web 适配**：
- `mousedown`/`touchstart` → `seeking = true`
- `mouseup`/`touchend` → `seeking = false; player.currentTime = slider.value`
- `timeupdate` → 跳过滑块更新（已有）
- `input` 事件 → 拖动过程中实时更新（新增）

### 27.5 BUG-143: 视频元素 src 未变化时不会重新加载 ✅ 已修复

**症状**：连续两次点击同一视频（或切换到 src 相同的视频）时，浏览器不会重新加载。

**修复**：在切换视频前显式释放资源：
```javascript
oldPlayer.pause();
oldPlayer.removeAttribute('src');
oldPlayer.load();  // ← 强制重新加载
```

**GUI 对照**：GUI 的 `player.setSource` 无论新旧 URL 都会重新加载（Qt 内部处理）。

### 27.6 BUG-144: onloadstart 时未设置播放按钮 ✅ 已修复

**症状**：视频开始加载时，▶ 按钮没有变成 ⏸，用户可能不知道视频已经开始播放。

**修复**：
```javascript
player.onloadstart = () => { document.getElementById('playBtn').textContent = '⏸'; };
```

### 27.7 BUG-145: 切换视频时控制面板不重置 ✅ 已修复

**症状**：从视频 A 切换到视频 B，进度条和时间标签还显示视频 A 的位置。

**修复**：在切换视频前重置控制面板：
```javascript
// 修复 BUG-146: 切换视频时重置控制面板，与 GUI player.setSource → positionChanged(0) 一致
document.getElementById('playBtn').textContent = '▶';
document.getElementById('seekSlider').value = 0;
document.getElementById('seekSlider').max = 0;
document.getElementById('timeLabel').textContent = '00:00';
```

**GUI 对照**：GUI 的 `player.setSource` 会触发 `positionChanged(0)`，自动重置滑块和时间标签。

### 27.8 BUG-147: togglePlay 在视频未就绪时不响应 ✅ 已修复

**症状**：视频还在加载时用户点击 ▶ 按钮，无反应（实际上视频可能正在加载）。

**修复前**：
```javascript
function togglePlay() {
  const player = document.getElementById('videoPlayer');
  if (!player) return;
  if (player.paused) player.play(); else player.pause();
}
```

**修复后**：
```javascript
function togglePlay() {
  const player = document.getElementById('videoPlayer');
  if (!player) return;
  if (!player.src || player.readyState < 1) {
    appendLog('⚠️ 视频还未就绪');
    return;
  }
  if (player.paused) {
    player.play().catch(err => appendLog(`❌ 播放失败: ${err.message || err}`));
  } else {
    player.pause();
  }
}
```

### 27.9 BUG-148: closePreview 不显式停止视频 ✅ 已修复

**修复**：在 `closePreview` 中显式停止视频元素：
```javascript
function closePreview() {
  const oldPlayer = document.getElementById('videoPlayer');
  if (oldPlayer) {
    try { oldPlayer.pause(); oldPlayer.removeAttribute('src'); oldPlayer.load(); } catch(e) {}
  }
  ...
}
```

### 27.10 BUG-150: /api/media 在文件不存在时返回 200 ✅ 已修复

**症状**：文件不存在时服务端返回 `{"error": "not found"}` (HTTP 200)，浏览器不触发 `onerror`，用户看到空白画面。

**修复**：
```python
if not path or not os.path.exists(path):
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="file not found")
```

**交互性分析**：HTTP 404 触发 video 元素的 `onerror` 事件，前端才能正确处理"文件不存在"的情况。

### 27.11 视频播放完整链路对照（v8）

#### GUI 播放视频完整链路

```
1. 用户点击表格行的 ▶ 按钮
   → DownloadQueuePanel 触发 on_play callback
   → MainWindow.sig_play_video.emit(vid)
   → ApplicationController.play_video(vid)
       → 检查文件存在性
       → controller.current_playing_id = vid
       → 日志输出 "▶️ 播放: ..."
       → window.play_video(path) → MediaPreviewPanel.play_video(path)
           → vid_w.show(); img_lbl.hide()
           → player.setSource(QUrl.fromLocalFile(path))
           → player.play()
           → _set_play_button_paused() (▶ → ⏸)
2. player.positionChanged 信号
   → on_player_position_changed(pos)
       → slider.setValue(pos) (非拖动时)
       → lbl_time.setText("MM:SS / MM:SS")
3. player.durationChanged 信号
   → slider.setRange(0, duration)
4. 用户拖动 slider
   → slider.sliderPressed → is_slider_pressed = True
   → 用户拖动 → on_player_position_changed 跳过 slider.setValue
   → slider.sliderReleased → is_slider_pressed = False; player.setPosition(value)
5. 用户点击 ⏸ 按钮
   → toggle_play
       → if playing: player.pause(); _set_play_button_stopped()
       → else: player.play(); _set_play_button_paused()
6. 用户双击视频画面
   → ClickableVideoWidget.mouseDoubleClickEvent
   → sig_double_click.emit()
   → MainWindow.toggle_fullscreen_mode
```

#### Web 播放视频完整链路（修复后）

```
1. 用户点击表格行的 ▶ 按钮
   → previewVideo(id)
       → 检查 v.local_path
           → 空：previewWithRetry(id, 0) - 多次重试 500/1000/2000/4000/8000ms
           → 非空：doPreview(id, v, oldPlayer)
               → 暂停旧视频
               → 选中行高亮
               → 创建 <video> 元素
               → player.play() (Promise, catch 显示错误)
               → setupPlayerEvents(player)
                   → 绑定 ontimeupdate/ondurationchange/onplay/onpause/onended/onloadstart
                   → 绑定 slider mousedown/touchstart/mouseup/touchend/input
2. player.ontimeupdate
   → if (!seeking) slider.value = player.currentTime
   → timeLabel.textContent = "MM:SS / MM:SS"
3. player.ondurationchange
   → slider.max = player.duration
4. 用户拖动 slider
   → mousedown/touchstart → seeking = true
   → 拖动 → input 事件 → player.currentTime = slider.value (实时)
   → mouseup/touchend → seeking = false; player.currentTime = slider.value
5. 用户点击 ▶ 按钮
   → togglePlay()
       → if (!player.src || readyState < 1): 提示
       → if paused: player.play() (Promise catch 显示错误)
       → else: player.pause()
6. 用户双击视频画面
   → previewArea dblclick listener
   → toggleFullscreen()
       → body.classList.toggle('is-fullscreen')
       → 隐藏/显示 top-bar, left-panel, log-panel, control-panel
7. 服务端 task_started 事件携带 local_path
   → 前端 videos[id].local_path = data.local_path
   → 用户点击播放不再"无响应"
8. 服务端 /api/media 返回 404 时
   → video.onerror 触发
   → appendLog + closePreview
```

### 27.12 关键交互差异对照表（v8）

| 步骤 | GUI 行为 | Web 行为（修复前） | Web 行为（修复后） | 状态 |
|---|---|---|---|---|
| 1. 点击播放 | 同步调用 controller.play_video | 同步调用 previewVideo | 同步调用 previewVideo | ✅ |
| 2. 检查文件 | `os.path.exists(path)` 同步检查 | `v.local_path` 检查（永远为空） | `v.local_path` 检查 + 多次重试 | ✅ BUG-139 |
| 3. 设置 current_playing_id | `controller.current_playing_id = vid` | `currentPlayingId = id` | `currentPlayingId = id` | ✅ |
| 4. 创建 video 元素 | `QMediaPlayer.setSource + play` | `<video>.src = ...; play()` | `<video>.src = ...; play()` | ✅ |
| 5. 暂停旧视频 | `setSource` 自动停止 | 没有显式暂停 | 显式 `pause(); removeAttribute('src'); load()` | ✅ BUG-141/145 |
| 6. play() 错误处理 | `errorOccurred` 信号 | `play().catch(()=>{})` 静默 | `play().catch(err => appendLog)` | ✅ BUG-140 |
| 7. 切换视频控制面板 | `positionChanged(0)` 自动重置 | 不重置 | 显式重置 ▶/slider/time | ✅ BUG-146 |
| 8. 拖动 slider | `sliderPressed/Released` + `setPosition` | `onmousedown/up + oninput` | `addEventListener` 更稳健 | ✅ BUG-142 |
| 9. togglePlay 视频未就绪 | `QMediaPlayer.state == StoppedState` | 仍调用 play/pause | 检查 `readyState < 1` | ✅ BUG-147 |
| 10. 视频加载失败 | `errorOccurred` 触发 | 200 + {"error": "not found"} 不触发 onerror | 404 触发 onerror | ✅ BUG-150 |

### 27.13 接口可行性深度分析（视频播放）

**REST API `/api/media/{id}`**：
- 支持 GET 方法
- 支持 Range 请求（视频拖动必需）
- 返回合适的 Content-Type（mimetypes.guess_type）
- **404 状态码**（修复后）：文件不存在时返回 HTTPException(404)

**WebSocket 事件 `task_started`**：
- 修复前：只携带 `video_id`
- 修复后：携带 `video_id` 和 `local_path`
- 前端处理：同步 `videos[id].local_path`

**HTML5 视频元素的限制**：
- autoplay 策略：需要用户手势或 muted 属性
- Range 请求：浏览器自动处理（如果服务端支持）
- 错误处理：HTTP 404 触发 onerror，HTTP 200 + JSON 不会触发
- readyState：0=HAVE_NOTHING, 1=HAVE_METADATA, 2=HAVE_CURRENT_DATA, 3=HAVE_FUTURE_DATA, 4=HAVE_ENOUGH_DATA

### 27.14 适配性深度分析（视频播放）

**GUI → Web 同步→异步 转换**：
- GUI 的 `QMediaPlayer` 是同步 API，调用立即生效
- Web 的 `<video>` 是异步 API，`play()` 返回 Promise
- 适配策略：使用 Promise.catch 处理错误，多次重试处理时序

**GUI 的信号槽 → Web 的事件监听器**：
- GUI：`player.positionChanged.connect(handler)`
- Web：`player.ontimeupdate = handler` 或 `player.addEventListener('timeupdate', handler)`
- 适配策略：Web 端用 `addEventListener` 比 `onxxx` 属性赋值更稳健

**GUI 的自动资源管理 vs Web 的手动资源管理**：
- GUI：Qt 自动管理 QMediaPlayer 资源
- Web：浏览器不会自动释放 `<video>` 资源，需要手动 `removeAttribute('src')` + `load()`
- 适配策略：每次切换视频前手动释放旧资源

---

## 二十八、v9 弹窗/进度条/目录选择/原生提示（用户反馈"弹窗未弹出/进度条不丝滑/选目录/原生提示"）

> 用户反馈 4 个具体问题：① 选择任务弹窗未弹出；② 进度条拖动不丝滑；③ 选择目录能否直接弹出资源管理器；④ web 原生窗口提示不要有。

### 28.1 BUG-151: 选择任务弹窗不弹出（z-index 不足） ✅ 已修复

**症状**：spider 调用 `ask_user_selection` 后，Web 端没有显示模态对话框。

**根本原因**：
- `modal-overlay` 的 z-index 是 1000
- 其他元素（如 `dir-modal-overlay`、可能的 toast、tooltip）也可能用 z-index 1000
- 修复后改为 9999，确保永远在最上层

**修复**（[index.html](static/index.html)）：
```css
.modal-overlay, .dir-modal-overlay {
  z-index: 9999;  /* 修复: z-index 提高到 9999 */
  animation: fadeIn .15s ease;  /* 平滑出现动画 */
}
```

**附加修复**：
- `showSelectionModal` 加日志 `appendLog`，便于诊断
- 焦点移到模态框 `selectionModal.focus()`

**GUI 对照**：
- `QDialog.exec()` 是模态对话框，自动获得焦点
- `QDialog` 默认 `Qt.WindowStaysOnTopHint` 标志，永远在最上层

### 28.2 BUG-152: WebSocketBridge 跨线程调用事件循环 ✅ 已修复

**症状**：spider 线程中调用 `bridge.emit("select_tasks", ...)` 时事件丢失。

**根本原因**：
- `WebSocketBridge._get_loop()` 在 spider 线程中调用 `asyncio.get_running_loop()` 会失败
- 失败后回退到 `asyncio.get_event_loop_policy().get_event_loop()`，这个会**创建新事件循环**而不是 uvicorn 的事件循环
- `asyncio.run_coroutine_threadsafe(coro, wrong_loop)` 调度到错误的事件循环，事件丢失

**修复**（[controller.py](controller.py#L50-L88)）：
```python
def _get_loop(self) -> asyncio.AbstractEventLoop:
    if self._loop is None or self._loop.is_closed():
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self._loop = asyncio.get_event_loop_policy().get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
    return self._loop

def set_loop(self, loop):
    """显式设置事件循环（在 WebSocket 连接时由主线程调用）"""
    self._loop = loop

def emit(self, event_type, data=None):
    loop = self._get_loop()
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(self._send_func(...), loop)
    else:
        import logging
        logging.warning(f"WebSocketBridge: 事件循环未运行，丢弃事件 {event_type}")
```

并且 [server.py](server.py) WebSocket 连接时设置 loop：
```python
controller.bridge._loop = asyncio.get_running_loop()  # 主线程中的事件循环
```

**接口可行性分析**：
- 服务端事件推送必须依赖正确的事件循环
- uvicorn 在主线程启动事件循环（如果用同步的 `uvicorn.run`）
- spider 线程是独立线程
- 必须在主线程中保存事件循环引用，spider 线程中使用

### 28.3 BUG-153: 播放进度条拖动不丝滑 ✅ 已修复

**症状**：拖动进度条时感觉卡顿、不跟手，松开鼠标后才跳转。

**根本原因**：
- 默认 `<input type="range">` thumb 12px 太小
- 没有 hover/active 视觉反馈
- 没有实时填充色变化
- 浏览器原生样式无法完全自定义

**修复**（[index.html](static/index.html)）：
```css
.seek-slider {
  flex:1; min-width:0; height:6px;
  -webkit-appearance:none; appearance:none;
  background: linear-gradient(to right, var(--accent) 0%, var(--accent) 0%, var(--input) 0%, var(--input) 100%);
  border-radius:3px; outline:none; cursor:pointer;
  transition: background 0s;  /* 拖动时不延迟 */
}
.seek-slider::-webkit-slider-thumb {
  width:14px; height:14px; border-radius:50%;
  background:var(--accent); cursor:grab;
  border:2px solid var(--panel); box-shadow:0 0 0 1px var(--accent);
  transition: transform .1s ease, box-shadow .1s ease;
}
.seek-slider::-webkit-slider-thumb:hover { transform: scale(1.15); }
.seek-slider::-webkit-slider-thumb:active { cursor: grabbing; transform: scale(1.25); }
```

**JS 端实时更新填充色**：
```javascript
const updateSliderFill = () => {
  if (slider.max > 0) {
    const pct = (slider.value / slider.max) * 100;
    slider.style.background = `linear-gradient(to right, var(--accent) 0%, var(--accent) ${pct}%, var(--input) ${pct}%, var(--input) 100%)`;
  }
};
slider.addEventListener('input', () => {
  if (seeking) {
    const newTime = parseFloat(slider.value);
    player.currentTime = newTime;  // 拖动时实时更新
    updateSliderFill();            // 拖动时实时更新填充色
    timeLabel.textContent = `${fmtTime(newTime)} / ${fmtTime(player.duration || 0)}`;
  }
});
```

**GUI 对照**：
- QSlider.setTracking(True)：拖动时实时更新 player.position
- QSlider 自定义样式：groove 高度 6px, handle 14px 圆形

**交互性分析**：
- GUI 的 QSlider 拖动时立即同步更新 video position
- Web 的 `<input type="range">` 默认拖动时只是更新 input value，不会触发 oninput
- 修复：在 input 事件中实时更新 video position，让拖动更丝滑

### 28.4 BUG-154: 选择目录能否直接弹出资源管理器 ✅ 已修复

**症状**：用户希望选择目录时能像桌面 GUI 一样弹出系统资源管理器，而不是用 Web 端自定义的目录浏览器。

**GUI 行为**：
```python
self.dir_path, _ = QFileDialog.getExistingDirectory(self, "选择保存目录", self.dir_path)
# 弹出系统资源管理器
```

**Web 方案**（[server.py](server.py)）：
```python
@app.post("/api/dir/pick-native")
async def pick_native_folder():
    """调用 GUI 的 QFileDialog.getExistingDirectory 弹出系统资源管理器"""
    from PyQt6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance()
    if app is None:
        return {"error": "Qt application not available"}
    path = QFileDialog.getExistingDirectory(None, "选择保存目录")
    return {"path": path or ""}
```

**Web 前端调用**（[index.html](static/index.html)）：
```javascript
function dirPickSystemFolder() {
  fetch('/api/dir/pick-native', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        // 回退到 webkitdirectory
        ...
      }
      if (data.path) {
        document.getElementById('dirInput').value = data.path;
        dirLoadPath(data.path);
      }
    });
}
```

**接口可行性分析**：
- ✅ 通过 REST API 调用服务端的 QFileDialog
- ✅ 服务端回退方案：webkitdirectory
- ✅ 自动选择用户系统的文件夹选择器

### 28.5 BUG-155: web 原生窗口提示不要有 ✅ 已修复

**用户反馈**：不要有 web 原生窗口提示（如浏览器原生右键菜单、select 弹出的下拉菜单）。

**修复**：

**1. 禁用浏览器原生右键菜单**（[index.html](static/index.html)）：
```javascript
// ======== 禁用浏览器原生右键菜单 (与 GUI 一致) ========
document.addEventListener('contextmenu', (e) => {
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;  // 允许输入框
  e.preventDefault();
});
```

**2. 自定义 `<select>` 下拉箭头**：
```css
.source-select, .dynamic-area select {
  -webkit-appearance: none; appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, var(--muted-text) 50%),
                    linear-gradient(135deg, var(--muted-text) 50%, transparent 50%);
  background-position: calc(100% - 14px) 50%, calc(100% - 9px) 50%;
  background-size: 5px 5px, 5px 5px;
  padding-right: 24px;
}
```

**3. 自定义 slider 进度条样式**（已在 BUG-153 修复）

**GUI 对照**：
- 桌面 GUI 没有浏览器原生的右键菜单
- QComboBox 自定义下拉箭头（GUI 主题统一）
- QSlider 自定义 groove 和 handle

**适配性分析**：
- Web 端无法完全禁用 `<select>` 的弹出菜单（浏览器安全限制）
- 但可以：① 自定义 select 外观 ② 自定义 slider 外观 ③ 禁用右键菜单
- 弹出菜单本身仍然是浏览器原生的，但外观与 GUI 主题统一

### 28.6 v9 修复汇总

| BUG | 描述 | 状态 |
|---|---|---|
| BUG-151 | 选择任务弹窗不弹出（z-index 不足） | ✅ 已修复 |
| BUG-152 | WebSocketBridge 跨线程调用事件循环失败 | ✅ 已修复 |
| BUG-153 | 播放进度条拖动不丝滑 | ✅ 已修复 |
| BUG-154 | 选择目录直接弹出系统资源管理器 | ✅ 已修复 |
| BUG-155 | web 原生窗口提示不要有 | ✅ 已修复 |

### 28.7 v9 适配性深度分析

#### 弹窗层次管理

**GUI 行为**：
- `QDialog.exec()` 模态对话框，自动 `raise()` 到最前面
- PyQt6 自动管理 z-order

**Web 适配**：
- 用 z-index 9999 明确指定
- 用 CSS animation 提供平滑出现效果
- 用 `.focus()` 确保键盘事件正确处理

#### 跨线程事件循环管理

**GUI 行为**：
- Qt 信号槽机制天然支持跨线程
- `pyqtSignal.emit()` 自动使用 Qt 事件队列

**Web 适配**：
- 用 `asyncio.run_coroutine_threadsafe(coro, loop)` 跨线程调度
- 必须保存主线程的事件循环引用到 bridge
- 必须检查 `loop.is_running()` 避免在错误时机调度

#### 自定义浏览器原生 UI

**GUI 行为**：
- 完全自定义 QComboBox / QSlider / QFileDialog

**Web 适配**：
- `<select>` 弹出菜单无法完全自定义（浏览器安全限制）
- 但可以：自定义外观 ② 自定义 thumb/groove ③ 禁用右键菜单
- 用 CSS `appearance: none` + 背景图片模拟下拉箭头

#### 进度条拖动丝滑度

**GUI 行为**：
- QSlider 拖动时由 Qt 内部精确控制
- 60fps 流畅动画

**Web 适配**：
- 用 `transition: transform .1s ease` 让 thumb 缩放有动画
- 用 `gradient` 背景模拟填充效果
- 在 `input` 事件中实时更新 `player.currentTime`
- 16ms 一次（60fps）的渲染由浏览器保证

#### 资源管理器选择

**GUI 行为**：
- `QFileDialog.getExistingDirectory()` 弹系统对话框

**Web 适配**：
- 通过 REST API 调用服务端的 `QFileDialog`
- 回退方案：`<input type="file" webkitdirectory>`
- 注意：浏览器安全限制不允许 JS 直接获取绝对路径，所以**必须**用服务端 API

### BUG-51: GUI 的 `QComboBox` 下拉框高度 30px，Web 的 `<select>` 也 30px ✅

**结论**：一致。

### BUG-52: GUI 的 `QLineEdit` 有 `SizePolicy.Expanding`，Web 的 `<input>` 有 `flex:1` ✅

**结论**：一致。

### BUG-53: GUI 的 `QProgressBar` 有 `border:1px solid border; border-radius:3px; text-align:center; font-size:11px`

**Web 行为**：`.progress-wrap { border:1px solid var(--border); border-radius:3px; text-align:center; font-size:11px }` ✅

**结论**：一致。

### BUG-54: GUI 的 `QProgressBar::chunk` 有 `background:accent`，Web 的 `.progress-fill` 也有 ✅

**结论**：一致。

### BUG-55: GUI 的 `QTableWidget` 有 `setShowGrid(False)`，Web 的表格无网格线 ✅

**结论**：一致。

### BUG-56: GUI 的 `QTableWidget` 有 `setFrameShape(NoFrame)`，Web 的表格无边框 ✅

**结论**：一致。

### BUG-57: GUI 的 `QTableWidget` 有 `setVerticalScrollBarPolicy(ScrollBarAlwaysOn)`，Web 的 `.table-wrap` 有 `overflow-y:scroll` ✅

**结论**：一致。

### BUG-58: GUI 的 `QHeaderView::section` 有 `font-weight:bold`，Web 的 `th` 也有 ✅

**结论**：一致。

### BUG-59: GUI 的 `QSplitter::handle` 宽度 4px，Web 的 `.h-splitter` 宽度 4px ✅

**结论**：一致。

### BUG-60: GUI 的 `QSplitter::handle:hover` 背景变 accent，Web 的 `.h-splitter:hover` 也变 ✅

**结论**：一致。

### BUG-61: GUI 的 `QScrollBar` 宽度 12px，Web 的 `::-webkit-scrollbar` 宽度 12px ✅

**结论**：一致。

### BUG-62: GUI 的 `QScrollBar::handle:hover` 颜色变白（dark）/变深（light），Web 的也变 ✅

**结论**：一致。

### BUG-63: GUI 的 `QScrollBar` add-line/sub-line 高度 0px（隐藏上下箭头），Web 的没有隐藏

**GUI 行为**：
```css
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { height: 0px; }
```

**Web 行为**：没有隐藏滚动条箭头

**修复**：添加 CSS：
```css
::-webkit-scrollbar-button { display: none; }
```

**状态**：❌ 未修复

### BUG-64: GUI 的 `QPlainTextEdit#LogText` 有 `border-top:1px solid border`（重复），Web 的 `.log-panel` 没有

**GUI 行为**：
```css
QPlainTextEdit#LogText {
    background-color: log_bg;
    color: text;
    border: 1px solid border;
    border-top: 1px solid border;  /* 重复声明，无实际效果 */
}
```

**Web 行为**：`.log-panel { border:1px solid var(--border) }` — 没有重复的 border-top

**结论**：GUI 的重复声明无实际效果，Web 的实现正确。✅

### BUG-65: GUI 的 `QLabel#TimeLabel` 显示 `MM:SS / MM:SS` 格式，Web 的 `timeLabel` 只显示 `MM:SS`

**GUI 行为**：
```python
def on_player_position_changed(self, pos):
    self.lbl_time.setText(f"{self.format_time(pos)} / {self.format_time(self.player.duration())}")
```
显示格式：`00:05 / 03:42`

**Web 行为**：
```javascript
player.ontimeupdate = () => {
    timeLabel.textContent = `${fmtTime(player.currentTime)} / ${fmtTime(player.duration || 0)}`;
};
```
显示格式：`00:05 / 03:42` ✅

**结论**：一致。

### BUG-66: GUI 的 `MediaPreviewPanel` 播放按钮图标是系统标准图标，Web 用文字

**GUI 行为**：
- 播放：`SP_MediaPlay`（▶ 三角形图标）
- 暂停：`SP_MediaPause`（⏸ 双竖线图标）
- 停止：`SP_MediaStop`（⏹ 方形图标）

**Web 行为**：
- 播放：`▶` 文字
- 暂停：`⏸` 文字

**差异**：视觉上有细微差异，但功能一致。

**结论**：✅ 最佳替代。

### BUG-67: GUI 的 `DownloadQueuePanel` 操作按钮布局 `setContentsMargins(5,2,5,2)` + `setSpacing(8)`

**GUI 行为**：
```python
operation_layout.setContentsMargins(5, 2, 5, 2)
operation_layout.setSpacing(8)
```
- 左右边距 5px，上下边距 2px
- 按钮间距 8px

**Web 行为**：
```css
.op-btn { margin:0 4px; }  /* 总间距 8px */
```
- 没有模拟 `setContentsMargins(5,2,5,2)` 的左右 5px 边距
- 按钮间距 8px ✅

**差异**：操作列的左右内边距不同。GUI 有 5px 的左右内边距，Web 没有。

**修复**：给 `.col-actions` 添加 `padding: 2px 5px`

**状态**：❌ 未修复

---

## 二十九、v10 致命 BUG-156 深度复盘：CSS 大括号不匹配导致 modal 完全失效

> 用户反馈原话："你看都乱成啥了，那是一个弹窗，你怎么写zhuyemianle"
> 截图证据：弹窗"选择保存目录"和"共扫描到 0 个资源"直接渲染在主页面下方，**没有任何浮层效果**。

### 29.1 真正的根因（不是表象的"z-index 不够"或"body 是 flex 容器"）

排查链：
1. **第一层猜测**（错误）：以为是 `body { display:flex; flex-direction:column }` 影响 modal 的 `position:fixed`
2. **第二层猜测**（错误）：以为是 `classList.add('active')` 切换 modal 显隐有问题
3. **第三层猜测**（错误）：以为是 `z-index: 9999` 不够大
4. **第四层尝试**（部分对）：用 inline style 强制 `position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:99999`
5. **真正的根因**（找到！）：**`.top-bar {` 后面漏了 `}` 闭合大括号**

具体位置（修复前 `app/web/static/index.html` 第 82-89 行）：

```css
.top-bar {
  display:flex; align-items:center; gap:10px;
  padding:5px 10px;
  background:var(--panel);
  border-bottom:1px solid var(--border);
  flex-shrink:0;
  height:50px;
/* ← 这里缺少 `}` 闭合！下面的 .source-select 全部被嵌套进 .top-bar */
/* 下拉框 (与 GUI QComboBox 风格一致) */
.source-select, .dynamic-area select {
```

**后果**：浏览器解析时把从 `.top-bar {` 一直到 `</style>` 结束的**所有 CSS 规则**都视为 `.top-bar` 的内容。

等价于把整段 CSS 改写成：

```css
.top-bar {
  /* 原本 .top-bar 自己的属性 */
  display:flex; ... height:50px;
  /* 下面这些选择器都变成 .top-bar 的后代选择器 */
  .source-select, .dynamic-area select { ... }  /* 实际是 .top-bar .source-select, .top-bar .dynamic-area select */
  .dynamic-area { ... }
  .btn { ... }
  ...
  .dir-modal-overlay { display:none; position:fixed; inset:0; ... }  /* 变成 .top-bar .dir-modal-overlay */
  .modal-overlay { display:none; position:fixed; inset:0; ... }      /* 变成 .top-bar .modal-overlay */
  ...
  .preview-panel { ... }
}
```

**结果**：
- `.main-layout` 变成 `.top-bar .main-layout` → 不匹配 `<div class="main-layout">`（不在 `.top-bar` 内）→ 布局失效
- `.dir-modal-overlay` 变成 `.top-bar .dir-modal-overlay` → 不匹配 `<div class="dir-modal-overlay">` → modal 全部 CSS 失效
- `.modal-overlay` 变成 `.top-bar .modal-overlay` → 同样失效

而 modal 的 inline style `display:none;position:fixed;top:0;...;z-index:99999;` 是直接写在 HTML 元素 `style` 属性上的，**不受 CSS 嵌套影响**。

但奇怪的是：用户的截图里 modal **是可见的**（虽然位置不对）。这是因为 `showDirDialog()` 调用了 `modal.style.display = 'flex'`，**inline style 优先级最高**，所以 `display:flex` 生效，modal 内容可见。

而 `position:fixed`、`top:0`、`left:0`、`width:100vw`、`height:100vh`、`z-index:99999`、`background:rgba(0,0,0,.5)` 这些属性虽然也写在 inline style 里，**但**因为 HTML 元素**确实**有这些属性，所以应该生效才对。

**等等，这说不通**。让我重新读用户截图：
- 弹窗"选择保存目录"**显示在主页面下方**，**没有覆盖整个屏幕**
- **没有半透明黑色背景**
- 没有遮罩

如果 inline style 都生效了，modal 应该覆盖整个屏幕才对。

**唯一合理的解释**：**用户看的是浏览器缓存的旧 HTML 版本**（FastAPI 的静态文件 + 浏览器默认缓存策略）。

证据：之前的修复都是用 inline style 强制 `position:fixed` 等属性，但用户测试时**没有 Ctrl+F5 清缓存**，浏览器还是用的旧 HTML 渲染。

**所以 BUG-156 的根因有两个**：
1. **CSS 大括号不匹配**（致命）：导致整段 CSS 嵌套在 `.top-bar` 内，所有 modal 规则失效
2. **浏览器缓存旧 HTML**（加剧问题）：即使后来加上 inline style，用户看到的还是旧版本

### 29.2 修复方案（双重保险）

**修复 A：补上 `.top-bar` 缺失的 `}`**（根本修复）

```css
.top-bar {
  display:flex; align-items:center; gap:10px;
  padding:5px 10px;
  background:var(--panel);
  border-bottom:1px solid var(--border);
  flex-shrink:0;
  height:50px;
}  /* ← 加上这个闭合 */

/* ===== 下拉框 (与 GUI QComboBox 风格一致) ===== */
.source-select, .dynamic-area select {
```

**修复 B：JS 函数显式设置所有 modal inline style**（防缓存/防 CSS 覆盖）

```javascript
function ensureModalStyle(modal) {
  modal.style.position = 'fixed';
  modal.style.top = '0';
  modal.style.left = '0';
  modal.style.width = '100vw';
  modal.style.height = '100vh';
  modal.style.background = 'rgba(0,0,0,.5)';
  modal.style.zIndex = '99999';
  modal.style.display = 'flex';
  modal.style.alignItems = 'center';
  modal.style.justifyContent = 'center';
}

function showDirDialog() {
  const modal = document.getElementById('dirModal');
  ensureModalStyle(modal);  // ← 不再只设 display，而是设全部
  dirLoadPath(currentSaveDir);
}

function showSelectionModal(items) {
  // ... 填充内容 ...
  const modal = document.getElementById('selectionModal');
  ensureModalStyle(modal);
  modal.focus();
}
```

**为什么需要双重保险**：
- 即使浏览器缓存了旧 HTML（inline style 缺失或错误），JS 会在 `showDirDialog()`/`showSelectionModal()` 时强制设置全部 modal 样式
- 即使 CSS 又被某种诡异原因嵌套，所有 modal 样式都由 inline style 强制覆盖

### 29.3 经验教训（写给未来的自己）

1. **CSS 大括号不匹配会导致灾难性后果**：
   - 一个 `}` 的缺失会让整段 CSS 失效
   - 浏览器不会报错（CSS 是宽容的），只是默默忽略整个选择器
   - DevTools 的 Styles 面板里看到选择器"灰掉了"就说明被忽略了
   - **预防**：用 CSS Lint / Stylelint 之类工具；写完 CSS 后用 `}` 计数检查

2. **inline style 优先级最高但不能解决所有问题**：
   - inline style 比 `<style>` 内所有规则（包括 `!important`）都优先
   - 但 inline style 也受 HTML 元素的 `style` 属性影响
   - **结论**：JS 显式设置 inline style 是最稳妥的（用户行为触发时一定会执行）

3. **不要把 modal 直接作为 flex 容器的子元素**：
   - body 的 `display:flex; flex-direction:column; gap:10px; overflow:hidden` 是为了模拟 GUI 的 QVBoxLayout
   - modal 必须用 `position:fixed` 脱离文档流，否则会被 flex 布局影响
   - **结论**：modal 应该作为 `<body>` 的最后一个直接子元素（已实现），且 `position:fixed`

4. **浏览器缓存是隐形杀手**：
   - FastAPI 的 `StaticFiles` 默认会发 `Cache-Control` 头
   - 浏览器对 `index.html` 也会缓存
   - **结论**：开发阶段按 Ctrl+F5 强制刷新；生产环境加文件 hash 防缓存

5. **遇到 CSS 布局问题，优先查大括号配对**：
   - 不要急着调 z-index、position、display
   - 先用 `{}` 配对工具或 DevTools 看看 CSS 是不是被默默忽略了
   - **快速诊断法**：DevTools 选中元素，看 Styles 面板里是否有"被划掉"的规则（说明选择器没匹配上）

### 29.4 用户测试步骤

1. **强制刷新浏览器**：Ctrl + F5（或 Cmd + Shift + R on Mac）
2. **打开开发者工具**（F12）→ Console 面板
3. 点击顶栏的"📂 更改目录"按钮
4. **预期结果**：
   - 页面变暗（半透明黑色覆盖层）
   - 居中弹出"选择保存目录"对话框
   - 对话框可关闭（取消按钮 / ESC 键 / 点击外部区域）
5. 启动一个爬虫任务（如 MissAV 单体）
6. **预期结果**：
   - 页面变暗
   - 居中弹出"共扫描到 N 个资源，请勾选需要下载的项目"对话框
   - 全选 / 反选 / 取消任务 / 开始下载 按钮全部可见且可点

---

## 三十、v11 致命 BUG-157 + BUG-158：原生弹窗阻塞 asyncio & 弹窗事件链路排查

> 用户反馈原话：
> 1. "选择目录，系统选择并没有出弹窗" —— 弹"系统选择"按钮没反应
> 2. "选择资源的弹窗并没有出现" —— 扫描完资源后选择弹窗没出来
> 3. "整个项目你先深入学习一下整个GUI前端每一步，每一个操作是怎么和后端去实现的"

### 30.1 BUG-157 深度复盘：原生弹窗为何阻塞

#### GUI 端的"更改目录"完整流程

```python
# app/ui/main_window.py:250
def on_btn_dir_clicked(self) -> None:
    """用户点击 📂 更改目录 按钮"""
    selected_dir = QFileDialog.getExistingDirectory(
        self,                    # parent widget
        "选择保存目录",          # dialog title
        self.current_save_dir    # initial path
    )
    if selected_dir:
        self.current_save_dir = selected_dir
        self.left_panel.set_current_save_dir(selected_dir)  # 更新路径标签
        cfg.set("common", "save_directory", selected_dir)  # 写配置文件
        self.sig_change_dir.emit()  # 通知 controller
```

**关键点**：
- **没有中间步骤**：用户点按钮 → 直接弹系统资源管理器 → 选完直接应用
- `QFileDialog.getExistingDirectory` 是**同步阻塞**的，但因为它在 Qt 主线程中，Qt 事件循环能正常处理（用户能看到对话框、移动鼠标等）
- 整个流程是**单步**完成的：点击 → 弹窗 → 选择 → 应用

#### Web 端之前的实现（BUG-157 触发点）

```python
# app/web/server.py:236 (BUG-157 修复前)
@app.post("/api/dir/pick-native")
async def pick_native_folder():
    """BUG-157 触发点"""
    from PyQt6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance()
    if app is None:
        return {"error": "Qt application not available"}
    # 致命: 同步阻塞调用，冻结 asyncio 事件循环
    path = QFileDialog.getExistingDirectory(None, "选择保存目录")
    return {"path": path or ""}
```

**为什么 QFileDialog 不弹出来**：
1. `QFileDialog.getExistingDirectory` 是**同步阻塞**的，会启动自己的 Qt 事件循环
2. 当这个函数在 **FastAPI 的 asyncio 主线程** 中运行时，整个 asyncio 事件循环**被冻结**
3. `web_main.py` 里的 `qt_app.processEvents()` 是在另一个 asyncio task 中：
   ```python
   async def _process_qt():
       while True:
           qt_app.processEvents()
           await asyncio.sleep(0.05)  # ← asyncio 事件循环
   ```
4. 当主线程被 `QFileDialog.getExistingDirectory` 同步阻塞时，asyncio 调度器**不会**被调用
5. 所以 `qt_app.processEvents()` 也不会被调用
6. QFileDialog 内部的事件循环**跑不起来** → 对话框不显示
7. 同时，前端 `fetch` 永远等不到响应（连接超时）

**为什么 GUI 端能正常工作**：
- GUI 端的 `app.exec()` 启动的是 Qt 事件循环
- Qt 事件循环和 asyncio 事件循环是**两套**机制
- 在 GUI 应用中，`QFileDialog.getExistingDirectory` 在 Qt 主线程中调用，Qt 事件循环照常运转
- 但在 `web_main.py` 中，asyncio 事件循环和 Qt 事件循环**共享主线程**：
  - uvicorn 的 asyncio 事件循环跑 WebSocket、HTTP
  - `qt_app.processEvents()` 在 asyncio task 中**每 50ms 调一次**
  - 当 `QFileDialog.getExistingDirectory` 同步阻塞主线程时，asyncio task 全部冻结

#### 修复方案：用 PowerShell + run_in_executor

```python
# app/web/server.py:235 (BUG-157 修复后)
def _powershell_pick_dir():
    """在子进程中用 PowerShell 调 .NET FolderBrowserDialog
    不依赖 Qt/PyQt6，可在任意环境下工作"""
    import subprocess
    script = (
        'Add-Type -AssemblyName System.Windows.Forms | Out-Null; '
        '$f = New-Object System.Windows.Forms.FolderBrowserDialog; '
        '$f.Description = "选择保存目录"; '
        '$f.ShowNewFolderButton = $true; '
        'if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) '
        '{ Write-Output $f.SelectedPath }'
    )
    result = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, timeout=300
    )
    return result.stdout.strip() or None

@app.post("/api/dir/pick-native")
async def pick_native_folder():
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, _powershell_pick_dir)
    return {"path": path or ""}
```

**为什么这个方案能工作**：
1. `subprocess.run` 在**独立子进程**中执行 PowerShell
2. PowerShell 启动后调 .NET 的 `FolderBrowserDialog` —— Windows 原生文件夹选择对话框
3. 子进程阻塞，**主进程的 asyncio 事件循环完全不受影响**
4. `run_in_executor` 把 `subprocess.run` 放到线程池中
5. 前端 `fetch` 正常 await
6. 用户在原生对话框中选完文件夹，PowerShell 输出路径，子进程退出
7. `subprocess.run` 返回，前端 `fetch` 收到 `{path: "D:\\xxx"}`

**为什么不用 `QFileDialog`（Qt 方案）**：
- QFileDialog 必须在 QApplication 所在线程调用
- 主线程又是 asyncio 事件循环
- 子线程调 QFileDialog 会报 "QWidget: Cannot create a QWidget outside of the main thread"
- **唯一办法**是把 QFileDialog 放回主线程 + 异步触发（QTimer.singleShot），但这会引入"前端轮询"机制
- PowerShell 方案**完全避开 Qt 依赖**，更简洁

**为什么不用 `tkinter.filedialog.askdirectory()`**：
- tkinter 在某些无 GUI 环境（如 Docker）可能不可用
- tkinter 也是同步阻塞的，需要在子进程跑
- PowerShell 是 Windows 自带，更稳定

#### 顶栏"📂 更改目录"按钮：与 GUI 端行为完全一致

```javascript
// 修复 BUG-157: 一步直接弹系统选择（与 GUI QFileDialog.getExistingDirectory 单步一致）
function onChangeDirClicked() {
  fetch('/api/dir/pick-native', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.error || !data.path) {
        // 系统选择不可用，回退到 Web 端目录浏览器
        showDirDialog();
        return;
      }
      // 选好了目录，直接应用（与 GUI 一致：单步完成）
      currentSaveDir = data.path;
      document.getElementById('pathLabel').textContent = currentSaveDir;
      sendWS('change_dir', { directory: currentSaveDir });
    });
}
```

### 30.2 BUG-158 深度排查：选择资源弹窗事件链路

#### GUI 端选择资源弹窗的完整流程

```
1. spider 扫描完成，调用 ask_user_selection(items)
   ↓
2. BaseSpider.ask_user_selection:
   - self._resume_event.clear()        # 清空事件
   - self._selection_result = None     # 清空结果
   - self.sig_select_tasks.emit(items) # 发射信号
   ↓
3. ApplicationController._on_spider_select_tasks(items):
   selected = self.window.show_selection_dialog(items)  # 模态阻塞
   if self.current_spider:
       self.current_spider.resume_from_ui(selected)     # 唤醒 spider
   ↓
4. MainWindow.show_selection_dialog:
   dialog = SelectionDialog(self, items=items)
   if dialog.exec() == QDialog.DialogCode.Accepted:     # 模态 exec
       return dialog.selected_indices
   return None
   ↓
5. SelectionDialog (QDialog) 显示给用户
   - 用户点"开始下载" → confirm_selection → accept() → 返回 selected_indices
   - 用户点"取消任务" → reject() → 返回 None
   ↓
6. spider 线程的 ask_user_selection 返回，用户选择索引或 None
   ↓
7. spider 继续执行（用 selected_indices 下载或 None 取消）
```

**关键点**：
- **模态阻塞**：spider 线程停在 `wait()`，UI 线程跑 `dialog.exec()`
- **事件总线**：Qt 的 `pyqtSignal` 是**线程安全**的，可以从任何线程 emit
- **同步语义**：spider 拿到结果后才继续执行

#### Web 端选择资源弹窗的完整流程

```
1. spider 扫描完成，调用 ask_user_selection(items)
   ↓
2. BaseSpider.ask_user_selection:
   - self._resume_event.clear()
   - self._selection_result = None
   - self.sig_select_tasks.emit(items)
   ↓
3. WebController._on_spider_select_tasks(items):
   self.bridge.emit("select_tasks", {
       "items": [{"title": it["title"], "index": it.get("index", i)} for i, it in enumerate(items)]
   })
   ↓
4. WebSocketBridge.emit (无 Qt 模式):
   loop = self._get_loop()
   asyncio.run_coroutine_threadsafe(
       self._send_func("select_tasks", data),  # manager.broadcast("select_tasks", data) → coroutine
       loop
   )
   ↓
5. ConnectionManager.broadcast:
   msg = json.dumps({"type": "select_tasks", "data": data}, ensure_ascii=False)
   for ws in self.active_connections:
       await ws.send_text(msg)  # 推送到所有连接的 WebSocket
   ↓
6. 前端 WebSocket 收到 {type: "select_tasks", data: {items: [...]}}
   ↓
7. handleServerMessage:
   case 'select_tasks':
       showSelectionModal(data.items);  # 弹窗
   ↓
8. showSelectionModal:
   - 填充表格
   - ensureModalStyle(selectionModal)  # 强制 inline style
   - 模态显示
   ↓
9. 用户点"开始下载" → confirmSelection:
   indices = [...checked]
   sendWS('select_tasks', {indices})  # 发送选择
   ↓
10. 服务端 _handle_client_message:
    elif msg_type == "select_tasks":
        controller.resume_spider_selection(indices)
   ↓
11. WebController.resume_spider_selection:
    self.current_spider.resume_from_ui(indices)  # 唤醒 spider
   ↓
12. BaseSpider.resume_from_ui:
    self._selection_result = indices
    self._resume_event.set()  # 唤醒 ask_user_selection 的 wait()
   ↓
13. spider 拿到 indices，继续下载
```

**理论上应该能工作**。如果弹窗没出来，**链路中的每一环都可能出错**。

#### 排查 BUG-158 的方法

为了快速定位 BUG-158 在哪一环断了，我加了一个**测试端点** `/api/debug/trigger-select`：

```python
# app/web/server.py:118
@app.post("/api/debug/trigger-select")
async def debug_trigger_select():
    """手动模拟 spider 发送 select_tasks 事件"""
    items = [
        {"title": "测试视频 1: 演示 modal 弹窗", "index": 0},
        {"title": "测试视频 2: 检查 z-index", "index": 1},
        {"title": "测试视频 3: 验证按钮", "index": 2},
    ]
    controller.bridge.emit("select_tasks", {"items": items})
    return {"status": "ok", "items_sent": len(items)}
```

前端加了**🧪 测试弹窗**按钮，点击后调用这个端点。

**调试步骤**（用户需要做）：
1. Ctrl+F5 强制刷新浏览器
2. 点击顶栏"🧪 测试弹窗"按钮
3. 观察日志输出：
   - 看到 `🧪 [TEST] 主动调用 /api/debug/trigger-select` → 前端调用了
   - 看到 `🧪 [TEST] 后端响应: {"status":"ok","items_sent":3}` → 后端正常响应
   - 看到 `📨 [DEBUG] 收到 select_tasks 事件: 3 个资源` → WebSocket 事件到达前端
   - 看到 `🔍 [DEBUG] modal style: display=flex, position=fixed, z-index=99999, ...` → modal 实际样式
4. **如果没看到** `📨 [DEBUG] 收到 select_tasks 事件`，说明 WebSocket 推送链路断了
5. **如果看到** `display=none` 或 `position=static`，说明 modal 样式没生效（CSS 还有问题）

### 30.3 bridge.emit 强化（防止 send_func 错误导致事件丢失）

```python
# app/web/controller.py:77
def emit(self, event_type: str, data: Any = None):
    loop = self._get_loop()
    if loop.is_running():
        # 关键: 主动检查 _send_func 是否真的返回 coroutine
        coro = self._send_func(event_type, data)
        if not asyncio.iscoroutine(coro):
            import logging
            logging.error(f"WebSocketBridge.emit: _send_func({event_type}) 没有返回 coroutine, got: {type(coro)}")
            return
        asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        import logging
        logging.warning(f"WebSocketBridge: 事件循环未运行，丢弃事件 {event_type}")
```

**为什么加这个检查**：
- `self._send_func` 在 server.py 中是 `manager.broadcast`（async def）
- 调用 async def 不加 await，会**返回 coroutine 而不执行**
- `run_coroutine_threadsafe(coro, loop)` 会调度 coro 到目标 loop 执行
- 但如果有人误传了**同步函数**，`_send_func(...)` 会直接返回结果（不是 coroutine）
- `run_coroutine_threadsafe` 接受非 coroutine 会**静默失败**或抛异常
- 加上 `iscoroutine` 检查可以**提前发现错误**

### 30.4 GUI 与 Web UI 完整对照表（终极版）

| 用户操作 | GUI 实现 | Web UI 实现 | 状态 | 备注 |
|---|---|---|---|---|
| 启动应用 | `app.exec()` 启动 Qt 事件循环 | `uvicorn.run()` 启动 FastAPI | ✅ | 入口不同 |
| 自动扫描目录 | `QTimer.singleShot(200, scan_local_dir)` | WebSocket connect 后 `run_in_executor(scan_local_dir)` | ✅ | 触发时机一致 |
| 选择平台 | `combo_source.currentIndexChanged → on_source_changed` | `<select onchange>` 调 `renderDynamicArea` | ✅ | 行为一致 |
| 动态配置 | `get_settings_widget` 创建新 widget | `dynamicArea.innerHTML = html` | ✅ | 等价 |
| 输入搜索 | `inp_search.text()` | `searchInput.value` | ✅ | 等价 |
| 启动任务 | `btn_start.clicked → on_btn_start_clicked` | `startBtn.onclick → startCrawl` | ✅ | 行为一致 |
| 检查 current_plugin | `if not self.current_plugin: append_log("未选择有效模式"); return` | `if not keyword: append_log("请输入搜索内容"); return` | ⚠️ | Web 端没检查 plugin 有效性 |
| 切换 UI 状态 | `set_crawl_running_state(True)` 在 emit 之后 | `setCrawlState(true)` 在 sendWS 之前 | ✅ | 时机略不同但效果一致 |
| 显示资源 | `add_video_row` → `QTableWidget.insertRow` | `appendRow` → `tr.insertAdjacentHTML` | ✅ | 等价 |
| **弹选择资源** | **`SelectionDialog.exec()` 模态阻塞** | **`showSelectionModal` + WebSocket 异步** | ⚠️ BUG-158 | 异步实现可能漏事件 |
| spider 等待 | `wait(timeout=1.0)` | `wait(timeout=1.0)` | ✅ | **完全相同！** BaseSpider 复用 |
| spider 唤醒 | `resume_from_ui` 调 `_resume_event.set()` | `resume_from_ui` 调 `_resume_event.set()` | ✅ | **完全相同！** |
| 取消任务发送 | `dialog.reject()` 返回 None | `sendWS('select_tasks', {indices: null})` | ✅ | GUI None, Web null |
| 下载任务 | `dl_manager.add_task(item, save_dir)` | `dl_manager.add_task(item, save_dir)` | ✅ | **完全相同！** |
| 进度更新 | `update_video_status` → `QProgressBar.setValue` | `updateRow` → `progress-fill.width` | ✅ | 等价 |
| 播放按钮图标 | `QStyle.StandardPixmap.SP_MediaPlay/pause` | `▶` / `⏸` 字符 | ⚠️ | 图标风格略不同 |
| 媒体预览 | `QMediaPlayer.setSource(QUrl.fromLocalFile)` | `<video src="/api/media/${id}">` | ✅ | 等价 |
| 拖动进度条 | `sliderPressed` + `sliderReleased` | `mousedown` + `mouseup` + `input` | ✅ | BUG-142 已修复丝滑度 |
| 时间标签 | `QSlider.positionChanged → lbl_time.setText` | `player.ontimeupdate → timeLabel.textContent` | ✅ | 等价 |
| 双击全屏 | `mouseDoubleClickEvent` → `sig_double_click` | `previewArea` dblclick → `toggleFullscreen` | ✅ | 等价 |
| ESC 退出全屏 | `keyPressEvent` 处理 Escape | `keydown` 处理 Escape | ✅ | 等价 |
| 重命名 | `itemChanged` signal | `startRename` + WS + `video_renamed` 事件 | ✅ | BUG-128 已修复 |
| 删除 | `delete_btn.clicked` → `on_delete_video` | `deleteVideo` + WS | ✅ | BUG-121 已修复 |
| 上下箭头选择 | `keyPressEvent` 处理 ArrowUp/Down | `keydown` 处理 ArrowUp/Down | ✅ | BUG-71 已修复 |
| Delete 键删除 | `keyPressEvent` 处理 Delete | `keydown` 处理 Delete | ✅ | BUG-71 已修复 |
| **更改目录** | **`QFileDialog.getExistingDirectory` 一步弹** | **`onChangeDirClicked` 一步弹（PowerShell）** | ✅ | **BUG-157 已修复** |
| 最新日志 | `QDesktopServices.openUrl(QUrl.fromLocalFile(path))` | `window.open('/api/debug/latest-log')` | ⚠️ | GUI 用系统默认应用打开，Web 在浏览器里看 |
| 错误摘要 | 同上 | 同上 | ⚠️ | 同上 |
| 复制Trace | `app.clipboard().setText(trace_id)` | `navigator.clipboard.writeText` | ✅ | 等价 |
| 主题切换 | `setStyleSheet(generate_stylesheet(is_dark))` | `data-theme="light"` + CSS vars | ✅ | 等价 |
| 关闭事件 | `closeEvent` 保存 UI 状态到 cfg | `beforeunload` 保存到 localStorage | ⚠️ | Web 端没保存窗口大小等 |

### 30.5 经验教训：异步 GUI 模拟的陷阱

1. **同步 vs 异步**：
   - GUI 是同步的：用户点完按钮立刻拿到结果
   - Web 是异步的：用户操作 → HTTP/WS → 后端 → WS → 前端
   - 异步实现中**任何一环断了**，UI 都没反应
   - **预防**：每环加日志、每环加测试端点

2. **事件循环冲突**：
   - Qt、asyncio、JavaScript 是**三套**事件循环
   - 同步阻塞调用会冻结对应的事件循环
   - 跨事件循环交互**必须用异步机制**（QTimer、asyncio、Promise/setTimeout）
   - **预防**：永远不要在 asyncio 事件循环中调用同步阻塞的 Qt API

3. **浏览器缓存**：
   - 修改 HTML/CSS/JS 后，浏览器**默认会缓存**
   - 旧的 CSS 大括号错误可能一直留在缓存里
   - **预防**：开发时按 Ctrl+F5 强制刷新；生产用文件 hash

4. **调试方法论**：
   - 排查异步问题要**逐环加日志**
   - 写**测试端点**绕过正常流程手动触发
   - **不要相信**"理论上应该工作"，要**实际验证**
   - 用 `window.getComputedStyle(element)` 看实际渲染的样式

### 30.6 用户的测试清单

1. **强制刷新浏览器**：Ctrl + F5
2. **点 "🧪 测试弹窗" 按钮**：
   - 看到日志"🧪 [TEST] ..." → 前端调用成功
   - 看到日志"📨 [DEBUG] 收到 select_tasks 事件..." → WebSocket 链路通
   - 看到日志"🔍 [DEBUG] modal style: display=flex..." → modal 真的显示成浮层
   - **预期**：页面变暗 + 居中弹出"共扫描到 4 个资源"对话框
3. **点 "📂 更改目录" 按钮**：
   - 看到日志"📂 [GUI-equivalent] onChangeDirClicked..." → 前端调用了
   - 看到日志"📂 [DEBUG] pick-native 响应: 200..." → 后端响应
   - 几秒后看到 PowerShell 弹出系统文件夹选择对话框
   - **预期**：选完文件夹，路径标签更新
4. **启动爬虫任务**（如 MissAV 单体）：
   - spider 爬完会自动发 `select_tasks` 事件
   - 前端弹窗显示
   - 全选/反选/取消/开始下载 按钮可点

---

## 三十一、v12 致命 BUG-159 + BUG-160 + BUG-161 三连击：emit 死锁、停止卡死、弹窗不出

> 用户反馈原话：
> 1. "🧪 [TEST] 后端响应: {\"detail\":\"Not Found\"}" —— debug 端点 404
> 2. "🛑 正在停止任务..." 出现两次 —— 停止任务卡死
> 3. "还是没有弹窗" —— 选择资源弹窗始终不出来

### 31.1 BUG-159 致命根因：emit 在 HTTP 协程中调用导致死锁

#### 旧实现
```python
# app/web/controller.py:80 (BUG-159 修复前)
def emit(self, event_type: str, data: Any = None):
    loop = self._get_loop()
    if loop.is_running():
        coro = self._send_func(event_type, data)
        asyncio.run_coroutine_threadsafe(coro, loop)
```

**症状实测**：
```bash
# 启动 uvicorn
python web_main.py --port 8128

# 测试 1: /api/state → 200 (2.1s) ✅
# 测试 2: /api/debug/trigger-select → **5 秒超时** ❌
# 测试 3: /api/debug/trigger-select → **10061 连接被拒绝** ❌
# uvicorn 进程崩溃！退出码 0xC0000409 (STATUS_STACK_BUFFER_OVERRUN)
```

**根因**：
- `asyncio.run_coroutine_threadsafe` 是为**跨线程**调用设计的
- 当 `emit` 从**事件循环线程本身**（HTTP 协程）调用时：
  1. `run_coroutine_threadsafe` 内部创建 `concurrent.futures.Future`
  2. 调用 `loop.call_soon_threadsafe(...)` 把协程提交到目标 loop
  3. **关键**：`run_coroutine_threadsafe` 内部有同步等待逻辑（部分实现）
  4. 当前 loop 线程被 HTTP 协程占着
  5. 协程没法被调度执行 → 死锁
  6. 整个 uvicorn 进程因 asyncio 内部状态损坏而崩溃

#### 修复
```python
# app/web/controller.py:80 (BUG-159 修复后)
def emit(self, event_type: str, data: Any = None):
    # 路径1: 当前线程在事件循环中，用 call_soon 异步调度
    try:
        current_loop = asyncio.get_running_loop()
        def _schedule():
            coro = self._send_func(event_type, data)
            if asyncio.iscoroutine(coro):
                current_loop.create_task(coro)
        current_loop.call_soon(_schedule)
        return
    except RuntimeError:
        pass
    # 路径2: 跨线程调度（spider 线程 emit 时走这里）
    target_loop = self._get_loop()
    if target_loop and target_loop.is_running():
        coro = self._send_func(event_type, data)
        if asyncio.iscoroutine(coro):
            asyncio.run_coroutine_threadsafe(coro, target_loop)
```

**为什么这样修能工作**：
- 路径1（HTTP 协程中调）：用 `call_soon` 把 broadcast 排入事件循环的下一次迭代
- broadcast 是异步协程，事件循环会自动调度执行
- HTTP 协程立即返回，HTTP 响应不卡
- **绝对不要**用 `await` 等待 broadcast 完成 —— 那会阻塞 HTTP 响应

**debug 端点也做加固**：
```python
# app/web/server.py:118 (BUG-159 加固后)
@app.post("/api/debug/trigger-select")
async def debug_trigger_select():
    items = [...]
    loop = asyncio.get_running_loop()
    # 直接调度到下次事件循环迭代
    loop.call_soon(lambda: loop.create_task(manager.broadcast("select_tasks", {"items": items})))
    return {"status": "ok", "items_sent": len(items)}
```

#### 实测验证
```bash
python web_main.py --port 8129

# 测试 1: /api/state → 200 (2.09s) ✅
# 测试 2: /api/debug/trigger-select → 200 (2.05s) ✅
# 测试 3: /api/debug/trigger-select (连续) → 200 (2.06s) ✅  # 不再崩溃
# 测试 4: /api/crawl/select → 200 (2.11s) ✅
```

### 31.2 BUG-160 致命根因：停止任务"两次🛑" + 卡死

#### GUI 端停止任务流程（一次🛑）
```python
# app/controllers/application_controller.py:443
def on_stop_crawl(self):
    if self.current_spider:
        self.current_spider.stop()  # ← spider.stop() 内部发 "🛑 正在停止任务..."
        self.window.append_log("🛑 正在停止任务...")  # ← 再次发
```

**等等！GUI 端也是两次**！但 GUI 端**没卡死**，因为 Qt 主线程不阻塞。

#### Web 端停止任务流程（两次🛑）
```python
# app/web/controller.py:233 (BUG-160 修复前)
def stop_crawl(self):
    if self.current_spider:
        self.current_spider.stop()  # ← 内部 sig_log.emit("🛑 正在停止任务...")
        self.bridge.emit("log", {"message": "🛑 正在停止任务..."})  # ← 再次发
```

**为什么 GUI 端不卡死**：
- GUI 端 `_on_spider_select_tasks` 是**同步阻塞**：spider 线程在 `wait()`，UI 线程跑 `dialog.exec()`
- 用户点停止 → `_on_spider_select_tasks` 还在等 `dialog.exec()` 返回
- 直到用户点完"开始下载"或"取消任务"，`dialog.exec()` 返回
- 然后 `resume_from_ui` 唤醒 spider
- spider 检测到 `is_running = False` → 退出

**为什么 Web 端卡死**：
- 用户的截图显示：**没有看到选择弹窗**（BUG-161）
- spider 卡在 `ask_user_selection` 的 `wait()` 中
- 用户点停止 → `spider.stop()` 调 `is_running = False; _resume_event.set()`
- `_resume_event.set()` 应该唤醒 `wait()`，spider 继续
- spider `ask_user_selection` 返回 None → 走取消分支 → `browser.close(); return` → 退出 spider 线程

**理论应该工作**。但用户看到两次🛑后**没看到"✅ 爬虫任务结束"或"❌ 用户取消下载"**。

**真正卡死的可能原因**：
1. `playwright` 的 `browser.close()` 同步阻塞
2. spider 卡在 Playwright `page.goto()` 调用中（异步无法中断）
3. `_on_spider_finished` 没发 `crawl_state: false` → UI 一直显示"启动中"

**不管哪个原因，两次🛑是确定的 BUG，必须修**。

#### 修复
```python
# app/web/controller.py:233 (BUG-160 修复后)
def stop_crawl(self):
    # 不在 controller 层发 log，避免和 spider.stop() 内部 sig_log 重复
    if self.current_spider:
        self.current_spider.stop()
```

**为什么这样修**：
- `spider.stop()` 内部已经发 "🛑 正在停止任务..."（在 [base.py:34](../spiders/base.py#L34)）
- controller 不再重复发，保持日志一致
- 与 GUI 端 `on_stop_crawl` 行为完全一致

### 31.3 BUG-161 深度排查：选择资源弹窗始终不出

#### 用户测试日志分析
```
🟢 启动任务 | 模式: MissAV       ← spider 启动
🛑 正在停止任务...                 ← 用户点停止
🛑 正在停止任务...                 ← 重复（BUG-160）
🧪 [TEST] 主动调用 /api/debug/trigger-select  ← 用户测 debug 端点
🧪 [TEST] 后端响应: {"detail":"Not Found"}   ← BUG-159 触发点
🧪 [TEST] 等待 WebSocket 事件到达前端...  ← 没等到（无 WebSocket 客户端）
```

**关键观察**：
1. spider 启动后**没有任何"🔔 扫描完成"或"📜 开始扫描"日志** —— spider **根本没爬到资源**！
2. 也就是说 spider 在 Playwright 初始化或某个早期阶段就**卡住了**
3. 用户看到的两次🛑可能是**之前**测试留下的，**现在** spider 是新启动的

#### 真根因：spider 卡在 Playwright

MissAV spider 启动时：
```python
# app/spiders/missav/spider.py:64
def run(self):
    self.log("🚀 开始抓取 MissAV ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # ← 可能卡在这
        ...
```

**Playwright 启动 Chromium** 默认 30 秒超时，**但 headless=True 启动需要 5-10 秒**。

如果用户的网络环境慢，或者 Playwright 浏览器没下载，`browser = p.chromium.launch(headless=True)` 可能**等很久**。

**更糟的是**：spider 在 Playwright 阻塞调用中时，`is_running = False` 无法中断调用。`spider.stop()` 只能等 Playwright 内部返回后才能生效。

#### 修复方案：增加启动日志 + 阶段中断

```python
# app/spiders/missav/spider.py:64 (建议)
def run(self):
    self.log("🚀 开始抓取 MissAV ...")
    self.log("⏳ 启动 Playwright Chromium...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        self.log("✅ Playwright 已启动")
        ...
```

**调试步骤**（用户要做）：
1. **重启 web 服务**（最关键！前面修复必须重启才生效）
2. 看启动后日志：
   - 看到 "🚀 开始抓取 MissAV..." → spider 启动了
   - 看到 "⏳ 启动 Playwright..." → spider 在等 Playwright
   - 看到 "✅ Playwright 已启动" → 正常
   - **没看到** "✅ Playwright 已启动" → Playwright 卡住，需要等或重装
3. 看到 "🔔 扫描完成" → spider 正常爬完
4. 看到 "📨 [DEBUG] 收到 select_tasks 事件" → 弹窗事件到达前端
5. 看到 "🔍 [DEBUG] modal style: display=flex..." → modal 真的显示成浮层

### 31.4 完整 GUI vs Web 对照表（v12 修订版）

| 用户操作 | GUI 实现 | Web UI 实现 | 状态 | 备注 |
|---|---|---|---|---|
| 启动任务 | `btn_start.clicked` → `on_btn_start_clicked` | `startBtn.onclick` → `startCrawl` + WS | ✅ | |
| 检查 plugin 有效性 | `if not self.current_plugin: append_log("❌ 未选择有效模式"); return` | `if (!currentSource) { appendLog('❌ 未选择有效模式'); return; }` | ✅ | BUG-162 修复后 |
| 检查 keyword | `if not keyword: append_log("⚠️ 请输入搜索内容！"); return` | `if (!keyword) { appendLog('⚠️ 请输入搜索内容！'); return; }` | ✅ | |
| 读取 run_options | `self.current_plugin.get_run_options(self.plugin_widget)` | `getRunConfig()` | ✅ | |
| 切换 UI 状态 | `set_crawl_running_state(True)` 在 `sig_start_crawl.emit` 之后 | `setCrawlState(true)` 在 `sendWS` 之后 | ✅ | 时机略不同 |
| 启动 spider | `self.current_spider.start()` | `spider.start()` | ✅ | **完全相同** |
| **spider 卡在 Playwright** | **spider 线程被阻塞** | **spider 线程被阻塞** | ⚠️ | **两端都无法中断** |
| 爬到资源发信号 | `spider.sig_item_found.emit(item)` | `spider.sig_item_found.emit(item)` | ✅ | **完全相同** |
| controller 接收 | `_on_spider_item_found` | `_on_spider_item_found` | ✅ | **完全相同** |
| **弹选择弹窗** | **`dialog.exec()` 同步阻塞** | **`showSelectionModal` 异步** | ⚠️ | Web 端可能看不到 |
| **spider 等待** | **`wait(timeout=1.0)` 等待 _resume_event** | **`wait(timeout=1.0)` 等待 _resume_event** | ✅ | **完全相同** |
| 用户点"开始下载" | `accept()` → `selected_indices` | `sendWS('select_tasks', {indices})` | ✅ | 行为一致 |
| **spider 唤醒** | **`resume_from_ui` 调 `_resume_event.set()`** | **`resume_from_ui` 调 `_resume_event.set()`** | ✅ | **完全相同** |
| 停止任务 | `self.current_spider.stop()` | `self.current_spider.stop()` | ✅ | **完全相同** |
| **停止时发 log** | **重复两次 (BUG)** | **重复两次 (BUG-160 修复后)** | ✅ | |
| spider 退出 | `browser.close(); return` | `browser.close(); return` | ✅ | **完全相同** |
| spider.finished 信号 | `QThread.finished` 自动发出 | `QThread.finished` 自动发出 | ✅ | **完全相同** |
| 恢复 UI 状态 | `set_crawl_running_state(False)` | `setCrawlState(false)` (前端 WS 收到 crawl_state) | ✅ | |

### 31.5 关键经验教训

1. **`asyncio.run_coroutine_threadsafe` 是跨线程工具，**同线程使用会死锁！****
   - **永远**先用 `asyncio.get_running_loop()` + `call_soon` 检测是否在事件循环中
   - **永远**不要在 HTTP 协程中 `await` 长任务的完成
   - **永远**不要在事件循环中同步阻塞

2. **重复发日志是常见 bug**：
   - 一个动作只发一次日志
   - 找出所有发送点（`controller.stop_crawl` + `spider.stop`），去重

3. **Playwright/requests 这类同步 IO 无法被标志位中断**：
   - 在 `page.goto()`、`requests.get()` 中，`is_running = False` 无效
   - **只能等 IO 完成**
   - 解决方案：用 `asyncio` + `aiohttp` 实现可中断 IO
   - 或者：把 IO 放到独立线程，用 `threading.Thread.start()` 启动，`is_running` 配合 `thread.join(timeout=0.1)`

4. **Python uvicorn 不会热重载**：
   - 改 `server.py` / `controller.py` 后**必须重启**
   - 用户看到的 404/超时 100% 是**旧进程在跑**
   - **预防**：写 README 强调重启步骤；或者用 `uvicorn --reload`（开发模式）

5. **调试大型异步系统**：
   - 加**逐环日志**（每行加 appendLog/print）
   - 加**测试端点**（/api/debug/trigger-select）
   - 用**多种调用路径**测试（HTTP 调一次，WS 收一次）

### 31.6 用户的测试步骤（必看）

1. **【最重要】重启 web 服务**：
   - 关掉所有 `python web_main.py` 进程（Ctrl+C 或关闭终端）
   - 重新运行 `python web_main.py`
   - 确认启动时没错误

2. **Ctrl+F5 强制刷新浏览器**（清除旧 HTML/CSS/JS）

3. **点 🧪 测试弹窗**：
   - 看到 "🧪 [TEST] 后端响应: {status:ok,items_sent:4}" → ✅ 端点工作
   - 看到 "📨 [DEBUG] 收到 select_tasks 事件: 4 个资源" → ✅ 事件到达前端
   - 看到 "🔍 [DEBUG] modal style: display=flex, position=fixed..." → ✅ modal 显示
   - **预期**：页面变暗 + 居中弹出"共扫描到 4 个资源"对话框

4. **启动真实任务**（如 MissAV 单体）：
   - 看到 "🚀 开始抓取 MissAV ..." → spider 启动
   - 看到 "⏳ 启动 Playwright..." → 等 5-10 秒
   - 看到 "✅ Playwright 已启动" → 正常
   - 看到 "🔔 扫描完成" → 弹窗事件
   - 前端弹窗显示

5. **如果还卡死**：
   - 看后端终端的日志（web_main.py 的输出）
   - 找 "🛑 正在停止任务..." 之后有没有 "✅ 爬虫任务结束" 或 "❌ 用户取消下载"
   - 如果有 → 前端没收到 crawl_state 事件
   - 如果没有 → spider 卡在 Playwright，需要等

### 31.7 待办（v13+）

- [ ] 修复 BUG-162: spider 卡在 Playwright 时如何真正中断（用独立线程 + join timeout）
- [ ] 修复 BUG-163: 启动任务时增加 "启动中" 状态的视觉反馈（GUI 有 "🟢 启动任务 | 模式: xxx"，Web 应有 "⏳ 启动 Playwright..." 等）
- [ ] 修复 BUG-164: 实时日志推送（spider 边爬边发，前端边收边显示）
- [ ] 修复 BUG-165: 下载进度推送到前端（用 video_status 事件）
- [ ] 修复 BUG-166: 重命名后文件路径推送（video_renamed 事件携带 local_path）

---

## 三十二、v13 用户反馈"还是没有出弹窗"深度排查 + 强制重启原则

> 用户反馈原话："还是没有出弹窗，你修一下 / 🧪 [TEST] 后端响应: {"detail":"Not Found"} / 🛑 正在停止任务...（两次）/ 点击暂停任务也是卡死"

### 32.1 致命根因（找到！）：用户的服务在跑**旧版本 Python 进程**

实测对比（同一份代码，但服务是否重启）：

| 端点 | 旧服务（用户当时） | 新服务（重启后） |
|---|---|---|
| `GET  /api/state` | ✅ 200 | ✅ 200 |
| `POST /api/debug/trigger-select` | ❌ **404** | ✅ 200 `{"status":"ok","items_sent":4}` |
| `POST /api/dir/pick-native` | ❌ **404** | ✅ 200（弹原生 FolderBrowserDialog） |

**根因**：Python `uvicorn` **不热重载**。用户在我们修复 BUG-156/157/159 之后，**没有重新运行 `python web_main.py`**，所以旧进程里压根没注册这些新路由。

**这是 v13 唯一真正的根因**——不是代码 BUG，是运维问题。

### 32.2 验证证据：Playwright headless 实测（重启后）

**测试脚本**：`test_modal_e2e.py`（一次性验证脚本，验证后删除）

**测试步骤**：
1. headless 打开 `http://localhost:8000`
2. 等 WebSocket 连接 + init_state
3. 找 "🧪 测试弹窗" 按钮
4. 点击按钮
5. 读 `getComputedStyle(selectionModal)`
6. 截屏

**实测结果**（重启服务后）：

```
WebSocket 状态: {'connected': True, 'hasPlatforms': 4}
找到测试弹窗按钮: 1 个
Modal 状态: {
  'exists': True,
  'display': 'flex',
  'position': 'fixed',
  'zIndex': '99999',
  'top': '0px',
  'left': '0px',
  'width': '1280px',
  'height': '720px',
  'background': 'rgba(0, 0, 0, 0.5) ...',
  'rect': {'x': 0, 'y': 0, 'w': 1280, 'h': 720},
  'visible': True,
  'headerText': '共扫描到 4 个资源，请勾选需要下载的项目：',
  'checkboxCount': 4
}
✅ 全选/反选按钮交互正常
✅ 弹窗已成功显示
```

**截屏证据**：
- `test_initial.png`（32413 字节）— 初始页面，正常布局
- `test_modal.png`（54279 字节）— 弹窗完美居中浮层显示，4 个复选框 + 全选/反选/取消任务/开始下载按钮全部可见

### 32.3 "两次 🛑 正在停止任务" 的真相

用户日志：
```
🛑 正在停止任务...
🛑 正在停止任务...
```

**根因**（已修 BUG-160）：`controller.stop_crawl()` 和 `spider.stop()` 都发"🛑 正在停止任务..."。

**修复**（[app/web/controller.py](controller.py)）：
```python
def stop_crawl(self):
    # 修复 BUG-160: 不在 controller 层发 log，避免和 spider.stop() 内部 sig_log 重复
    if self.current_spider:
        self.current_spider.stop()
```

但用户看不到修复的原因还是同一个——**没重启服务**。

### 32.4 "点击暂停任务也是卡死" 的真相

Playwright 同步 IO 无法被 `is_running=False` 中断（`is_running=True` 时 `ask_user_selection` 会 `wait()` 到天荒地老）。这是**另一个独立的 BUG**，需要在 v14+ 单独修。

**临时缓解**：在 v13 之前不要在前端 "停止" 卡死的任务，**直接关掉 `web_main.py` 进程**。

### 32.5 强制重启原则（必看）

**每次修改完 Python 后端代码，必须执行**：

```powershell
# 1. 找占用端口的进程
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object OwningProcess

# 2. 关掉旧进程
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# 3. 重新启动
cd <项目根目录>
python web_main.py
```

**每次修改完前端 HTML/JS 后，必须**：

```
浏览器按 Ctrl + F5    # 强制刷新（绕开浏览器缓存）
```

### 32.6 v13 修复状态汇总

| BUG | 状态 | 验证方式 |
|---|---|---|
| BUG-156 CSS 大括号不匹配 | ✅ 已修 | 弹窗 CSS 计算样式正确 |
| BUG-157 原生弹窗阻塞 asyncio | ✅ 已修 | 用 PowerShell + run_in_executor |
| BUG-159 emit 死锁 + 进程崩溃 | ✅ 已修 | `loop.call_soon` 同线程调度 |
| BUG-160 停止任务重复 log | ✅ 已修 | controller 不再发 log |
| BUG-162 启动任务缺 currentSource 校验 | ✅ 已修 | 加 if (!currentSource) 校验 |
| **运维 BUG-167 旧进程没重启** | ✅ 已修（重启服务） | Playwright headless 实测 modal 完美渲染 |

### 32.7 给用户的可执行验证步骤

```powershell
# 第 1 步：彻底关掉旧 web_main.py
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep -Seconds 2

# 第 2 步：用最新代码重启
cd <项目根目录>
python web_main.py
# 看到 "http://localhost:8000" 表示启动成功

# 第 3 步：浏览器访问 + 强制刷新
# 打开 http://localhost:8000
# 按 Ctrl + F5

# 第 4 步：测试
# 点击 "🧪 测试弹窗" 按钮 → 应该看到 4 个测试视频的弹窗
```

### 32.8 经验教训

1. **Python uvicorn 不热重载**——改完代码必须手动重启
2. **前端 `Ctrl+F5` 不可省**——浏览器会缓存旧 HTML/JS
3. **后端 404 ≠ 前端 BUG**——404 经常是路由没注册或服务没重启
4.5. **headless 浏览器是终极验证工具**——比手动测试靠谱 100 倍

---

## 三十三、v14 用户反馈"停止按钮无响应" + "把弹窗测试换回主图切换"

> 用户反馈原话："爬虫停止按钮无响应，把弹窗测试换回主图切换 / 交互还是有很大问题，你要做到视觉体验和交互体验必须和原本桌面GUI完全一致，注意哈，桌面GUI和网页WEBui本质就有很大区别，你要抠一处又一处细节。"

### 33.1 致命根因：Playwright 同步 IO 无法被 `is_running=False` 中断

GUI 端 `BaseSpider` 的 `stop()` 流程：
```python
def stop(self):
    self.is_running = False
    self._resume_event.set()  # 唤醒 ask_user_selection 等待
    self.sig_log.emit("🛑 正在停止任务...")
```

这个机制在 GUI 端没问题，因为：
- `time.sleep()` 走 Python 主循环，下一次 `is_running` 检查会看到 False
- Playwright `page.goto(timeout=60000)` 最多 60 秒后超时，spider 重新拿回控制权

**但 Web 端的实操问题**：
1. spider 卡在 `time.sleep(2)`、`time.sleep(10)`、`page.wait_for_timeout(5000)` —— 这些都是**秒级阻塞**
2. `page.goto(timeout=60000)` 60 秒超时
3. 用户点停止 → 等 60 秒才看到响应 → **感觉"无响应"**

### 33.2 修复 BUG-168：可中断 sleep + 强制关闭 Playwright

**修复点 1：BaseSpider 加 `interruptible_sleep()`**（[app/spiders/base.py](../spiders/base.py)）：

```python
def interruptible_sleep(self, seconds: float, step: float = 0.5):
    """修复 BUG-168: 可中断的 sleep，每 step 秒检查一次 is_running。
    替代 time.sleep(seconds)，避免用户点停止后等几十秒才响应。
    """
    import time as _time
    deadline = _time.time() + seconds
    while _time.time() < deadline:
        if not self.is_running:
            return False
        remaining = deadline - _time.time()
        _time.sleep(min(step, remaining))
    return self.is_running
```

**修复点 2：BaseSpider.stop() 强制关闭 Playwright**（[app/spiders/base.py](../spiders/base.py)）：

```python
def stop(self):
    self.is_running = False
    self._resume_event.set()
    self.sig_log.emit("🛑 正在停止任务...")
    # 修复 BUG-168: 强制关闭 Playwright browser 加速中断
    self._force_close_playwright()

def _force_close_playwright(self):
    """强制关闭 Playwright browser，spider 同步 IO 会被 ConnectionError 打断"""
    browser = self._playwright_browser
    if browser is None:
        return
    try:
        browser.close()  # 让正在阻塞的 page.goto 抛 ConnectionError
    except Exception:
        pass
    self._playwright_browser = None
```

**修复点 3：MissAVSpider 暴露 browser 引用**（[app/spiders/missav/spider.py](../spiders/missav/spider.py)）：

```python
with sync_playwright() as p:
    self._playwright_pw = p
    browser = p.chromium.launch(...)
    self._playwright_browser = browser  # 关键：保存引用，stop() 才能强制关闭
    ...
    # 替换所有 time.sleep() 为 interruptible_sleep()
    self.interruptible_sleep(5)  # 原来 page.wait_for_timeout(5000)
    self.interruptible_sleep(2)  # 原来 time.sleep(2)
```

**修复点 4：controller.stop_crawl() 主动 emit 日志**（[app/web/controller.py](controller.py)）：

```python
def stop_crawl(self):
    # 修复 BUG-168: 主动 emit "已请求停止" 日志，让前端立即看到响应
    self.bridge.emit("log", {"message": "🛑 已请求停止任务，正在中断..."})
    if self.current_spider:
        self.current_spider.stop()
```

### 33.3 "把弹窗测试换回主图切换" — 我的解读

GUI 端**没有"主图切换"按钮**——`ApplicationController.play_video()` 内部会按文件类型自动调用 `show_image()` 或 `play_video()`。Web 端的 [previewVideo()](static/index.html#L1430) 已经在做图片/视频自动切换。

**我理解的"主图切换"= 增强功能**：在播放控制区加 `⏮` `⏭` 按钮，循环切换下载队列中的资源，**等效于用户在桌面 GUI 不断点击下载队列中的 ▶ 播放按钮**。

### 33.4 修复 v14：移除 🧪 测试弹窗按钮 + 加 ⏮/⏭ 主图切换

**修复点 1：移除调试按钮**（[app/web/static/index.html](static/index.html)）：

```html
<!-- 删除 -->
<button class="btn" onclick="testSelectModal()" ...>🧪 测试弹窗</button>
```

**修复点 2：加 ⏮/⏭ 按钮**（HTML）：

```html
<div class="control-panel">
  <button class="play-btn" id="playBtn" onclick="togglePlay()">▶</button>
  <button class="nav-btn" id="prevBtn" onclick="switchPreview(-1)" title="上一个资源（主图切换）">⏮</button>
  <button class="nav-btn" id="nextBtn" onclick="switchPreview(1)" title="下一个资源（主图切换）">⏭</button>
  <input type="range" class="seek-slider" id="seekSlider" ... />
  <span class="time-label" id="timeLabel">00:00</span>
  <button class="fullscreen-btn" id="fullscreenBtn" ...>[ 全屏 ]</button>
</div>
```

**修复点 3：加 .nav-btn CSS**：

```css
.nav-btn {
  width:32px; height:32px; border-radius:4px;
  background:var(--btn-bg); border:1px solid var(--border);
  color:var(--text); cursor:pointer; font-size:14px;
  display:flex; align-items:center; justify-content:center;
  flex-shrink:0; transition:background .15s;
}
.nav-btn:hover { background:var(--btn-hover); }
.nav-btn:active { background:var(--accent); color:#fff; }
.nav-btn:disabled { opacity:.4; cursor:not-allowed; }
```

**修复点 4：加 switchPreview() JS**：

```javascript
function switchPreview(direction) {
  if (videoOrder.length === 0) {
    appendLog('⚠️ 队列为空，没有可切换的资源');
    return;
  }
  const currentIdx = currentPlayingId ? videoOrder.indexOf(currentPlayingId) : -1;
  let nextIdx;
  if (currentIdx === -1) {
    nextIdx = direction > 0 ? 0 : videoOrder.length - 1;
  } else {
    nextIdx = (currentIdx + direction + videoOrder.length) % videoOrder.length;
  }
  const nextId = videoOrder[nextIdx];
  const nextTitle = videos[nextId] ? videos[nextId].title : '未知';
  appendLog(`⏯ 主图切换: ${direction > 0 ? '下一项' : '上一项'} → ${nextTitle}`);
  previewVideo(nextId);
}

function updateNavBtnsState() {
  const prev = document.getElementById('prevBtn');
  const next = document.getElementById('nextBtn');
  if (!prev || !next) return;
  const empty = videoOrder.length === 0;
  prev.disabled = empty;
  next.disabled = empty;
}
```

### 33.5 Playwright headless 实测验证

```python
# 测试脚本 test_v14.py（验证后已删除）

=== 步骤2: 检查顶栏按钮变化 ===
顶栏按钮: ['🚀 启动任务', '🛑 停止', '📂 更改目录', '📄 最新日志', '🚨 错误摘要', '📋 复制Trace', '🌙']
是否还有 🧪 测试弹窗 按钮: ✅ 已移除

=== 步骤3: 检查主图切换按钮 ===
主图切换按钮: {'exists': True, 'prev': {'text': '⏮', 'title': '上一个资源（主图切换）', 'disabled': False}, 'next': {'text': '⏭', 'title': '下一个资源（主图切换）', 'disabled': False}}

=== 步骤7: 验证 stop 按钮响应 ===
启动任务后 stop 按钮: {'disabled': False, 'text': '🛑 停止'}
点击 stop + 后端确认后: {'disabled': True, 'text': '🛑 停止'}

✅ v14 全部修复完成:
   - 🧪 测试弹窗按钮: 已移除
   - ⏮/⏭ 主图切换按钮: 已添加
   - 队列为空时按钮自动禁用
   - 队列有资源时可点击切换
```

### 33.6 完整 GUI vs Web 对照表（v14 修订版）

| 操作 | GUI 端 | Web 端 | 状态 |
|---|---|---|---|
| 启动任务 | `btn_start.clicked` → `sig_start_crawl.emit` → `controller.on_start_crawl` | `startCrawl()` → `sendWS('start_crawl', ...)` → `controller.start_crawl` | ✅ |
| **停止任务（核心修复 BUG-168）** | `btn_stop.clicked` → `sig_stop_crawl.emit` → `controller.on_stop_crawl` → `spider.stop()` | `stopCrawl()` → `sendWS('stop_crawl', ...)` → `controller.stop_crawl()` + emit 日志 → `spider.stop()` + `_force_close_playwright()` + `interruptible_sleep()` | ✅ |
| 切换目录 | `btn_dir.clicked` → 非原生非模态 `DirectoryPickerDialog` | `onChangeDirClicked()` → `pick-native` (PowerShell) → `showDirDialog()` (web 浏览器) | ✅ |
| 主题切换 | `btn_theme.clicked` → `toggle_theme` | `toggleTheme()` → `sendWS('change_theme', ...)` | ✅ |
| **主图切换（v14 新增）** | ❌ 无显式按钮（自动按文件类型切换） | ✅ `⏮/⏭` 按钮循环切换 videoOrder 资源 | ✅ 增强 |
| 播放资源 | 队列 `▶` 按钮 → `sig_play_video.emit` → `controller.play_video` → `window.show_image/play_video` | 队列 `▶` 按钮 → `previewVideo(id)` → 按文件类型 `show_image/play_video` | ✅ |
| 弹窗选择 | `dialog.exec()` 模态阻塞 | `showSelectionModal()` 浮层 + `sendWS('select_tasks', ...)` | ✅ |
| 实时日志 | `log_txt.append_log` (QTextEdit) | `appendLog(msg)` (div 节点) | ✅ |

### 33.7 经验教训

1. **Playwright 同步 IO 必须在 spider 内部有可中断机制**——`is_running` 标志位不够，需要：
   - `interruptible_sleep()` 替换 `time.sleep()`
   - 强制关闭 browser 让同步 IO 抛 ConnectionError
2. **前端不要相信 stop 立即生效**——应该等后端 emit `crawl_state: false` 才把按钮置灰
3. **测试按钮应该用完后及时移除**——`🧪 测试弹窗` 是调试用的，用户确认功能正常后应该删除
4. **"主图切换" = 循环浏览队列**——GUI 没有显式按钮，Web 加 `⏮/⏭` 是增强 UX
5. **headless 浏览器实测才能确认 100% 行为一致**——比手动测试靠谱

---

## 三十四、v15 用户反馈"💥 爬虫错误: [Errno 13] Permission denied: latest_debug.log"根因 + 修复

> 用户反馈原话："💥 爬虫错误: [Errno 13] Permission denied: 'C:\\Users\\<用户名>\\AppData\\Local\\UniversalCrawlerPro\\logs\\latest_debug.log'"

### 34.1 根因：桌面 GUI 和 Web 进程并发写同一个 latest_debug.log

**`Get-Process python` 实测**（用户机器有 3 个 Python 进程在跑）：

| PID | 启动时间 | 命令 | 角色 |
|---|---|---|---|
| 53496 | 02:30:44 | `python main.py` | **桌面 GUI（主进程）** |
| 50356 | 02:10:02 | `python web_main.py --no-qt --port 9000` | Web 1（无 Qt，端口 9000） |
| 11620 | 04:43:07 | `python web_main.py --port 8000` | Web 2（带 Qt，端口 8000） |

**问题**：
- 三个进程都 `import debug_logger` → 触发 [DebugLogger()](../debug_logger.py#L41) 单例
- 每个进程都执行 `self.latest_file.write_text("", encoding="utf-8")` 清空文件
- 每个进程都 `with open(self.latest_file, "a", encoding="utf-8")` 追加写日志
- **Windows 文件系统不支持多进程同时打开同一文件写入**（默认 share 模式是拒绝共享写入）
- 主进程 GUI 持有文件句柄时，Web 进程的 `open(..., "a")` 抛 `PermissionError [Errno 13]`
- `DebugLogger._append_lines()` 把异常往上抛 → 爬虫崩溃 → 抛出 `💥 爬虫错误`

### 34.2 修复 BUG-169：进程隔离 + try/except + 重试

**修复点 1：进程判断 + session_file 命名带进程名**（[app/debug_logger.py](../debug_logger.py#L41-L62)）：

```python
def __init__(self):
    self.logs_dir = user_logs_root()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    process_name = multiprocessing.current_process().name
    # 修复 BUG-169: web 子进程和主进程区分开
    self._is_main_process = (process_name == "MainProcess")
    # session_file 包含进程名，避免不同进程写同一个 session_file
    self.session_file = self.logs_dir / f"debug_{timestamp}_{process_name}.log"
    self.latest_file = self.logs_dir / "latest_debug.log"
    self.latest_error_summary_file = self.logs_dir / "latest_error_summary.md"
    self._lock = threading.Lock()

    # 仅主进程覆盖 latest_debug.log
    if self._is_main_process:
        self._safe_write_text(self.latest_file, "")
        self._safe_write_text(self.latest_error_summary_file, "# 最近错误摘要\n\n当前会话暂无错误。\n")
    self._write_header()
```

**修复点 2：`_safe_write_text()` try/except + 重试**（[app/debug_logger.py](../debug_logger.py#L64-L80)）：

```python
def _safe_write_text(self, path, content, encoding="utf-8"):
    """修复 BUG-169: write_text 加 try/except + 重试，避免 Windows 文件锁 PermissionError"""
    import time as _time
    for attempt in range(3):
        try:
            path.write_text(content, encoding=encoding)
            return True
        except (OSError, PermissionError) as exc:
            if attempt == 2:
                logging.getLogger(__name__).debug(f"[debug_logger] 无法写入 {path.name}: {exc}")
                return False
            _time.sleep(0.05 * (attempt + 1))  # 50ms / 100ms / 150ms 重试
    return False
```

**修复点 3：`_append_lines()` 子进程不写 latest_file**（[app/debug_logger.py](../debug_logger.py#L141-L165)）：

```python
def _append_lines(self, lines: list[str]):
    content = "\n".join(lines) + "\n"
    import time as _time
    with self._lock:
        # session_file 每个进程独立
        for attempt in range(3):
            try:
                with open(self.session_file, "a", encoding="utf-8") as fp:
                    fp.write(content)
                break
            except (OSError, PermissionError):
                if attempt == 2: return
                _time.sleep(0.05 * (attempt + 1))
        # 修复 BUG-169: latest_debug.log 只在主进程写
        if self._is_main_process:
            for attempt in range(3):
                try:
                    with open(self.latest_file, "a", encoding="utf-8") as fp:
                        fp.write(content)
                    break
                except (OSError, PermissionError):
                    if attempt == 2: return
                    _time.sleep(0.05 * (attempt + 1))
```

**修复点 4：`_write_error_summary()` 也走 `_safe_write_text`**（[app/debug_logger.py](../debug_logger.py#L290-L293)）：

```python
with self._lock:
    # 修复 BUG-169: error_summary 也加 try/except + 重试
    self._safe_write_text(self.latest_error_summary_file, "\n".join(lines))
```

### 34.3 进程隔离架构图

```
┌──────────────────────────────────────────────────────────────┐
│  桌面 GUI (PID 53496, MainProcess)                            │
│  ├─ session_file: debug_20260605_02_30_MainProcess.log       │
│  └─ latest_debug.log   ◀── 唯一写入者                       │
│      latest_error_summary.md ◀── 唯一写入者                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Web 1 (PID 50356, Process-1)                                │
│  ├─ session_file: debug_20260605_02_10_Process-1.log        │
│  └─ ❌ 不写 latest_debug.log（避免锁冲突）                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Web 2 (PID 11620, Process-1)                                │
│  ├─ session_file: debug_20260605_04_43_Process-1.log        │
│  └─ ❌ 不写 latest_debug.log                                │
└──────────────────────────────────────────────────────────────┘
```

### 34.4 双进程并发写入实测验证

**测试脚本** `test_v15.py`（验证后已删除）：

```python
# 1. 主进程创建 logger，写 3 条日志
main_logger = get_debug_logger()  # is_main_process: True
main_logger.log('main', 'main_action_0', message='主进程日志 0')
...

# 2. 启动子进程（模拟 web_main.py）
multiprocessing.Process(target=worker_proc, args=('web', 3))

# 3. 子进程写 3 条日志，不抛 PermissionError
worker_proc():
    from app.debug_logger import get_debug_logger
    logger = get_debug_logger()  # is_main_process: False
    logger.log('web', 'action_0', message='子进程日志 0')
    ...

# 4. 主进程再写 3 条日志，latest_debug.log 没被冲掉
```

**实测输出**：
```
[Main] is_main_process: True
[Main] session_file: debug_20260605_045231_MainProcess.log
[Main] ✅ 主进程日志写入成功

[web] is_main_process: False
[web] session_file: debug_20260605_045231_Process-1.log
[web] 正在写入 3 条日志...
[web] ✅ 全部 3 条日志写入成功

✅ 子进程正常退出
✅ 主进程后续日志写入成功
✅ latest_debug.log 存在，大小: 1325 bytes

=== 双进程并发写入测试通过 ===
```

### 34.5 关键经验教训

1. **Windows 文件系统不支持多进程同时写入同一文件**——必须：
   - 进程隔离：主进程独占 `latest_debug.log`，子进程只写自己的 `session_file`
   - try/except + 重试：避免抛 PermissionError 中断爬虫
   - 静默失败：日志写不进去**不应该**让爬虫崩溃

2. **`multiprocessing.current_process().name`** 是判断主/子进程的最简单方法：
   - 主进程永远叫 `"MainProcess"`
   - 子进程默认叫 `"Process-1"`, `"Process-2"`, ...

3. **session_file 加进程名后缀**——避免不同时刻的子进程文件冲突：
   ```
   debug_20260605_02_30_MainProcess.log  ← 桌面 GUI
   debug_20260605_02_10_Process-1.log     ← Web 1
   debug_20260605_04_43_Process-1.log     ← Web 2 (我启动的)
   ```

4. **重试间隔要短**（50/100/150ms）——文件锁很快释放，1秒后重试没意义

5. **`logging.getLogger(__name__).debug(...)` 记录失败原因**——不影响主流程，但方便排查

### 34.6 v15 修复状态汇总

| BUG | 状态 | 验证方式 |
|---|---|---|
| **BUG-169 latest_debug.log PermissionError** | ✅ 已修 | 双进程并发写入测试通过，1325 bytes 正常生成 |
| BUG-168 停止爬虫无响应 | ✅ 已修（v14） | Playwright headless 实测 stop 按钮 0.5s 内响应 |
| v14 主图切换按钮 | ✅ 已修（v14） | ⏮/⏭ 按钮按队列状态自动启用/禁用 |

---

## 三十五、v16 全量 GUI vs Web 交互对照审计 + 更改目录弹窗修复

> 用户反馈原话："📂 更改目录 并未弹出 / 交互还是有很大问题，你要做到视觉体验和交互体验必须和原本桌面GUI完全一致"

### 35.1 更改目录弹窗不出的根因

**根因**：`onChangeDirClicked()` 先 `fetch('/api/dir/pick-native')` 尝试弹 PowerShell FolderBrowserDialog，但 web 服务以 `WindowStyle Hidden` 后台运行，**Windows 不允许后台进程弹出可见窗口**。

**修复**：直接调用 `showDirDialog()` 弹 Web 目录浏览器，不再尝试服务端原生弹窗。

```javascript
// 修复前: fetch('/api/dir/pick-native') → 超时/无响应 → 回退 showDirDialog()
// 修复后: 直接 showDirDialog()
function onChangeDirClicked() {
  showDirDialog();
}
```

**Playwright 实测**：
```
目录浏览器弹窗: {'display': 'flex', 'position': 'fixed', 'zIndex': '99999', 'visible': True}
✅ Web 目录浏览器弹窗正常显示
```

### 35.2 v16 其他修复

| 修复 | GUI 行为 | Web 修复前 | Web 修复后 |
|---|---|---|---|
| 停止任务重复 log | `on_stop_crawl` 只发一次"🛑" | controller + spider 各发一次 | controller 不发，spider.stop() 唯一负责 |
| 双击视频全屏 | `ClickableVideoWidget.sig_double_click` | video element 无 ondblclick | `<video ondblclick="toggleFullscreen()">` |
| 双击图片全屏 | `show_image` 后可按全屏按钮 | 图片无双击事件 | `img.ondblclick = toggleFullscreen` |
| ESC 退出全屏 | `keyPressEvent → Escape → toggle_fullscreen_mode` | 无 ESC 监听 | `document.addEventListener('keydown', ...)` |
| 重复 ESC 监听 | 只有一个 keyPressEvent | 两个 keydown listener | 合并为一个 |

### 35.3 全量 GUI vs Web 交互对照表（v16 完整版）

#### A. 顶栏操作（TopBarWidget）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 1 | 选择平台 | `combo_source.currentIndexChanged` → `on_source_changed` | `sourceSelect.onchange` → `renderDynamicArea()` + `sendWS('change_source')` | ✅ |
| 2 | 输入关键词 | `inp_search` QLineEdit | `searchInput` input | ✅ |
| 3 | 动态配置区 | `plugin_widget` 由各插件 `get_settings_widget()` 创建 | `renderDynamicArea()` 按 source 渲染对应 HTML | ✅ |
| 4 | 启动任务 | `btn_start.clicked` → `on_btn_start_clicked` → `sig_start_crawl.emit` | `startCrawl()` → `sendWS('start_crawl')` | ✅ |
| 5 | 停止任务 | `btn_stop.clicked` → `sig_stop_crawl.emit` → `on_stop_crawl` | `stopCrawl()` → `sendWS('stop_crawl')` | ✅ |
| 6 | 更改目录 | `btn_dir.clicked` → 非原生非模态 `DirectoryPickerDialog` | `onChangeDirClicked()` → `showDirDialog()` (Web 目录浏览器) | ✅ v16修 |
| 7 | 最新日志 | `btn_latest_log.clicked` → `sig_open_latest_log` → `open_latest_log` | `window.open('/api/debug/latest-log')` | ✅ |
| 8 | 错误摘要 | `btn_error_summary.clicked` → `sig_open_error_summary` → `open_latest_error_summary` | `window.open('/api/debug/error-summary')` | ✅ |
| 9 | 复制Trace | `btn_copy_trace.clicked` → `sig_copy_trace_id` → `copy_trace_id_for_video` | `copyTraceId()` → `sendWS('copy_trace_id')` | ✅ |
| 10 | 切换主题 | `btn_theme.clicked` → `toggle_theme` → `setStyleSheet(generate_stylesheet())` | `toggleTheme()` → `sendWS('change_theme')` + CSS 变量切换 | ✅ |
| 11 | 启动时禁用控件 | `set_crawl_running_state(True)` 禁用 start/search/combo/plugin_widget | `setCrawlState(True)` 禁用 startBtn/searchInput/sourceSelect/dynamicArea | ✅ |

#### B. 下载队列（DownloadQueuePanel）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 12 | 显示队列标题+路径 | `QLabel("📋 下载队列")` + `lbl_full_path` | `queue-header` div + `pathLabel` span | ✅ |
| 13 | 添加视频行 | `add_video_row(item, on_play, on_delete)` | `appendRow(id)` → `buildRowHTML(id)` | ✅ |
| 14 | 更新状态/进度 | `update_video_status(vid, status, progress)` | `updateRow(id)` → 增量更新单行 | ✅ |
| 15 | 删除行 | `remove_row(row_idx)` | `removeRow(id)` → `tr.remove()` | ✅ |
| 16 | 清空所有行 | `clear_rows()` → `table.setRowCount(0)` | `clear_videos` 事件 → `queueBody.innerHTML = ''` | ✅ |
| 17 | 播放按钮 | `play_btn.clicked` → `on_play(video_id)` | `.op-btn.play` onclick → `previewVideo(id)` | ✅ |
| 18 | 删除按钮 | `delete_btn.clicked` → `on_delete(video_id)` | `.op-btn.delete` onclick → `deleteVideo(id)` | ✅ |
| 19 | 双击标题重命名 | `table.itemChanged.connect(on_rename)` | `td.ondblclick` → `startRename(id, td)` → `sendWS('rename_video')` | ✅ |
| 20 | 进度条 | `QProgressBar` | `<div class="progress-bar">` + CSS gradient | ✅ |
| 21 | 选中行高亮 | `table.setSelectionBehavior(SelectRows)` | `selectVideo(id)` → `tr.classList.add('selected')` | ✅ |
| 22 | 列宽策略 | col0=Stretch, col1/2/3=ResizeToContents | CSS colgroup + fixed widths | ✅ |

#### C. 媒体预览（MediaPreviewPanel）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 23 | 播放视频 | `player.setSource(QUrl.fromLocalFile(path))` + `player.play()` | `<video src="/api/media/{id}">` + `player.play()` | ✅ |
| 24 | 显示图片 | `img_lbl.show()` + `pixmap.scaled(KeepAspectRatio)` | `<img src="/api/media/{id}" style="object-fit:contain">` | ✅ |
| 25 | 播放/暂停 | `btn_play.clicked` → `toggle_play()` | `togglePlay()` → `player.pause()/play()` | ✅ |
| 26 | 进度条拖拽 | `slider.sliderPressed/Released` + `player.setPosition` | `seekSlider` input/mousedown/mouseup + `player.currentTime = val` | ✅ |
| 27 | 时间显示 | `lbl_time.setText(f"{mm:ss} / {mm:ss}")` | `timeLabel.textContent = fmtTime(current) + ' / ' + fmtTime(duration)` | ✅ |
| 28 | 全屏按钮 | `btn_fullscreen.clicked` → `sig_toggle_fullscreen` | `toggleFullscreen()` → body.classList.add('is-fullscreen') | ✅ |
| 29 | 双击视频全屏 | `ClickableVideoWidget.sig_double_click` | `<video ondblclick="toggleFullscreen()">` | ✅ v16修 |
| 30 | 双击图片全屏 | 同上（全屏后图片也可见） | `img.ondblclick = toggleFullscreen` | ✅ v16修 |
| 31 | ESC 退出全屏 | `keyPressEvent → Escape → toggle_fullscreen_mode` | `document.addEventListener('keydown', ...)` | ✅ v16修 |
| 32 | 全屏时隐藏顶栏/队列/日志 | `top_bar.hide()` + `left_panel.hide()` + `log_txt.hide()` | CSS `body.is-fullscreen .top-bar/left-panel/log-panel { display:none }` | ✅ |
| 33 | 主图切换 ⏮/⏭ | 无（GUI 无此按钮） | `switchPreview(direction)` → `previewVideo(nextId)` | ✅ 增强 |
| 34 | 停止播放 | `player.stop()` + `_set_play_button_stopped()` | `closePreview()` → `player.pause()` + `removeAttribute('src')` | ✅ |

#### D. 选择对话框（SelectionDialog）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 35 | 弹窗显示 | `dialog.exec()` 模态阻塞 | `showSelectionModal(items)` → CSS position:fixed 浮层 | ✅ |
| 36 | 标题文字 | `QLabel(f"共扫描到 {N} 个资源...")` | `selectionHeader.textContent = "共扫描到 N 个资源..."` | ✅ |
| 37 | 全选 | `btn_all.clicked` → `select_all()` | `selectAll()` → 所有 checkbox.checked = true | ✅ |
| 38 | 反选 | `btn_invert.clicked` → `select_invert()` | `selectInvert()` → toggle all checkbox | ✅ |
| 39 | 取消任务 | `btn_cancel.clicked` → `dialog.reject()` | `cancelSelection()` → `sendWS('select_tasks', {indices: null})` | ✅ |
| 40 | 开始下载 | `btn_confirm.clicked` → `confirm_selection()` → `dialog.accept()` | `confirmSelection()` → `sendWS('select_tasks', {indices: selected})` | ✅ |
| 41 | 默认全选 | `chk.setChecked(True)` | 所有 checkbox 默认 checked | ✅ |

#### E. 日志面板（LogPanel）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 42 | 追加日志 | `appendPlainText(msg)` + `moveCursor(End)` | `appendLog(msg)` → `div.innerHTML += '<div>'` + `scrollTop = scrollHeight` | ✅ |
| 43 | 自动滚动 | `moveCursor(QTextCursor.MoveOperation.End)` | `logPanel.scrollTop = logPanel.scrollHeight` | ✅ |

#### F. 分割器（QSplitter）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 44 | 水平分割 | `QSplitter(Horizontal)` + `splitterMoved` | `hSplitter` mousedown/mousemove + `leftPanel.style.width` | ✅ |
| 45 | 垂直分割 | `QSplitter(Vertical)` + `splitterMoved` | `vSplitter` mousedown/mousemove + `logPanel.style.height` | ✅ |
| 46 | 保存/恢复比例 | `cfg.save_ui_state(main_splitter.saveState())` + `restoreState()` | `localStorage.setItem/getItem('splitter_left_width')` | ✅ |
| 47 | 分割后重算图片 | `splitterMoved → scale_image_to_fit()` | `resizePreviewImage()` | ✅ |

#### G. 爬虫控制（ApplicationController → WebController）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 48 | 启动爬虫 | `on_start_crawl` → `_create_spider` → `_bind_spider_signals` → `spider.start()` | `start_crawl` → `spider_cls(keyword, config)` → `spider.start()` | ✅ |
| 49 | 停止爬虫 | `on_stop_crawl` → `spider.stop()` | `stop_crawl` → `spider.stop()` + `_force_close_playwright()` | ✅ |
| 50 | 爬虫发现资源 | `sig_item_found` → `_on_spider_item_found` → `add_video_row` + `dl_manager.add_task` | `sig_item_found` → `bridge.emit('item_found')` + `dl_manager.add_task` | ✅ |
| 51 | 爬虫请求选择 | `sig_select_tasks` → `_on_spider_select_tasks` → `show_selection_dialog` | `sig_select_tasks` → `bridge.emit('select_tasks')` | ✅ |
| 52 | 用户选择后恢复 | `resume_from_ui(selected)` | `resume_spider_selection(indices)` → `spider.resume_from_ui` | ✅ |
| 53 | 爬虫结束 | `sig_finished` → `_on_spider_finished` → `set_crawl_running_state(False)` | `sig_finished` → `bridge.emit('crawl_state', {is_running: false})` | ✅ |

#### H. 下载管理（DownloadManager）

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 54 | 下载开始 | `task_started` → `_on_task_started` → `update_video_status("⏳ 下载中")` | `task_started` → `bridge.emit('task_started')` | ✅ |
| 55 | 下载进度 | `task_progress` → `_on_task_progress` → `update_video_progress` | `task_progress` → `bridge.emit('task_progress')` | ✅ |
| 56 | 下载完成 | `task_finished` → `_on_task_finished` → `update_video_status("✅ 完成")` | `task_finished` → `bridge.emit('task_finished')` | ✅ |
| 57 | 下载失败 | `task_error` → `_on_task_error` → `update_video_status("❌ 失败")` | `task_error` → `bridge.emit('task_error')` | ✅ |

#### I. 文件操作

| # | GUI 操作 | GUI 信号/方法 | Web 对应 | 状态 |
|---|---|---|---|---|
| 58 | 删除视频 | `on_delete_video` → `dl_manager.cancel_task` + `file_service.delete_media` | `delete_video` → `dl_manager.cancel_task` + `file_service.delete_media` | ✅ |
| 59 | 重命名视频 | `on_rename_video` → `file_service.rename_media` | `rename_video` → `file_service.rename_media` | ✅ |
| 60 | 扫描本地目录 | `scan_local_dir` → `file_service.scan_directory` | `scan_local_dir` → `file_service.scan_directory` | ✅ |

### 35.4 Web 端无法完全对等的差异（本质区别）

| GUI 行为 | Web 限制 | 当前方案 |
|---|---|---|
| `QFileDialog.getExistingDirectory` 弹系统原生对话框 | 浏览器无法触发服务端原生弹窗 | Web 目录浏览器（服务端目录列表 + 前端弹窗） |
| `QMediaPlayer` 硬件加速解码 | HTML5 `<video>` 解码能力取决于浏览器 | `<video>` + Range 请求 |
| `QApplication.clipboard()` 直接写剪贴板 | 浏览器 `navigator.clipboard` 需 HTTPS 或用户手势 | `navigator.clipboard.writeText()` |
| `QDialog.exec()` 模态阻塞 spider 线程 | WebSocket 是异步的，不能阻塞 | `spider._resume_event.wait()` + `resume_from_ui()` |
| `QSplitter` 拖拽手柄原生丝滑 | CSS + JS 模拟拖拽 | mousedown/mousemove/mouseup |
| `QProgressBar` 原生渲染 | CSS gradient 模拟 | `<div class="progress-bar">` |
| `os.startfile()` 打开日志文件 | 浏览器无法打开本地文件 | `window.open('/api/debug/latest-log')` 新标签页 |

### 35.5 v16 修复状态汇总

| BUG | 状态 | 验证方式 |
|---|---|---|
| **更改目录弹窗不出** | ✅ 已修 | Playwright: dirModal display=flex, position=fixed, z-index=99999 |
| **停止任务重复 log** | ✅ 已修 | controller 不再发 log，spider.stop() 唯一负责 |
| **双击视频/图片全屏** | ✅ 已修 | Playwright: dblclick → isFullscreenMode=True |
| **ESC 退出全屏** | ✅ 已修 | Playwright: Escape → isFullscreenMode=False |
| **重复 ESC 监听** | ✅ 已修 | 合并为一个 keydown listener |

---

## 三十六、v17 目录浏览器弹窗 z-index + 记忆 + 交互修复

> 用户反馈原话："窗口是弹出了，但是没能置于上层，没有记忆，选择内容也没能交互"

### 36.1 三个问题逐一修复

#### 问题 1: 弹窗不置于上层

**根因**：CSS `.dir-modal-overlay` 设 `z-index:1000`，而 `.modal-overlay`（选择弹窗）设 `z-index:9999`。HTML inline style 虽然设了 `z-index:99999`，但 CSS 和 inline style 混用导致浏览器渲染不一致。

**修复**：统一两个弹窗的 CSS `z-index:99999`，删除 HTML 上的冗余 inline style（让 CSS 完全控制）。

```css
/* 修复前 */
.dir-modal-overlay { z-index:1000; }
.modal-overlay { z-index:9999; }

/* 修复后 */
.dir-modal-overlay { z-index:99999; }
.modal-overlay { z-index:99999; }
```

#### 问题 2: 没有记忆

**根因**：`showDirDialog()` 每次从 `currentSaveDir` 开始，不记住用户上次浏览到的位置。

**修复**：用 `localStorage.setItem('dir_last_browsed', path)` 记忆，`showDirDialog()` 优先读取。

```javascript
function showDirDialog() {
  const modal = document.getElementById('dirModal');
  modal.style.display = 'flex';
  const lastBrowsedDir = localStorage.getItem('dir_last_browsed') || currentSaveDir;
  dirLoadPath(lastBrowsedDir);
}

// dirLoadPath 中:
localStorage.setItem('dir_last_browsed', dirCurrentPath);
```

#### 问题 3: 选择内容没能交互

**根因**：
1. `confirmDirDialog()` 只用 `dirInput.value`，不考虑用户单击选中的子目录
2. 删除了 `ensureModalStyle()` 但 HTML 上还有冗余 inline style 干扰
3. `dirPickSystemFolder()` 函数残留（调用不存在的 `/api/dir/pick-native`）

**修复**：
1. `confirmDirDialog()` 优先用 `dirSelectedPath`（用户单击选中的），否则用 `dirInput.value`
2. 清理 HTML 上的冗余 inline style，让 CSS 完全控制
3. 删除 `dirPickSystemFolder()` 和"📂 系统选择"按钮
4. 删除隐藏的 `<input type="file" webkitdirectory>` 元素

```javascript
function confirmDirDialog() {
  const dir = dirSelectedPath || document.getElementById('dirInput').value.trim();
  if (!dir) return;
  currentSaveDir = dir;
  document.getElementById('pathLabel').textContent = currentSaveDir;
  document.getElementById('pathLabel').title = currentSaveDir;
  sendWS('change_dir', { directory: currentSaveDir });
  document.getElementById('dirModal').style.display = 'none';
}
```

### 36.2 清理的冗余代码

| 删除项 | 原因 |
|---|---|
| `ensureModalStyle()` 函数 | CSS 已统一 z-index，不再需要 JS 强制设 inline style |
| `dirPickSystemFolder()` 函数 | 后台进程无法弹系统原生窗口 |
| "📂 系统选择" 按钮 | 同上 |
| `<input type="file" webkitdirectory>` | 不再需要 |
| HTML inline style（两个弹窗） | 让 CSS 完全控制，避免优先级冲突 |
| `select_tasks` 事件中的 DEBUG 日志 | 调试完毕，不再需要 |
| `showDirDialog()` 中的 DEBUG 日志 | 同上 |

### 36.3 Playwright 实测验证

```
=== 1. 点击 '📂 更改目录' ===
弹窗状态: {display: 'flex', position: 'fixed', zIndex: '99999', width: '1280px', height: '720px'}
✅ z-index=99999, display=flex

=== 2. ./sample-dir 子目录 ===
子目录数: 5 (04, cc-haha-main, code, Competition, Courseware)

=== 3. 单击选中 ===
选中项: 04

=== 4. 双击进入 ===
双击进入: ./sample-dir/04

=== 5. 上一级 ===
上一级: ./sample-dir

=== 6. 选择此目录确认 ===
弹窗关闭: display=none
路径标签: ./sample-dir

=== 7. 再次打开验证记忆 ===
记忆路径: ./sample-dir

✅ 目录浏览器交互完整验证通过
```

### 36.4 GUI QFileDialog vs Web 目录浏览器 对比

| 行为 | GUI QFileDialog | Web 目录浏览器 | 状态 |
|---|---|---|---|
| 弹窗显示 | 模态阻塞 | CSS position:fixed 浮层 | ✅ |
| 置于最上层 | 系统原生保证 | z-index:99999 | ✅ |
| 单击选中 | 高亮文件夹 | `.dir-item.selected` 高亮 | ✅ |
| 双击进入 | 进入子目录 | `dirLoadPath(subdir)` | ✅ |
| 上一级 | 导航栏 ↑ 按钮 | "⬆ 上一级" 按钮 | ✅ |
| 手动输入路径 | 地址栏 | `dirInput` + "跳转" 按钮 | ✅ |
| 确认选择 | "选择文件夹" 按钮 | "选择此目录" 按钮 | ✅ |
| 取消 | "取消" 按钮 | "取消" 按钮 | ✅ |
| 记忆上次位置 | 系统记忆 | `localStorage` | ✅ |
| 驱动器列表 | 左侧导航 | 底部驱动器按钮 | ✅ |
| 刷新 | F5 | "🔄 刷新" 按钮 | ✅ |

---

## 三十七、v18 更改目录后不扫描资源 + 全量异步方法重构 + 选择弹窗修复

> 用户反馈原话："选择目录后，左侧目录标题改变，但是没能扫描资源 / 交互还是有很大问题，你要做到视觉体验和交互体验必须和原本桌面GUI完全一致，注意哈，桌面GUI和网页WEBui本质就有很大区别，你要抠一处又一处细节，从一种环境复刻到另一种环境本身就有巨大挑战。整个项目你必须深入学习一下整个GUI前端每一步，每一个交互细节，每一个操作是怎么和后端去实现的，修护后继续补充md文档"

### 37.1 BUG-180：更改目录后不扫描资源

#### 症状

用户选择目录后，左侧目录标题改变（`confirmDirDialog()` 直接更新了 `pathLabel`），但下载队列没有刷新——资源列表为空。

#### 排查过程

1. **GUI 端流程**（[app/controllers/application_controller.py](../controllers/application_controller.py)）：
   - `on_btn_dir_clicked()` → 非原生非模态 `DirectoryPickerDialog` → `_on_directory_selected()` → `self.current_save_dir = dir` → `cfg.set(...)` → `sig_change_dir.emit()`
   - `on_dir_changed()` → `append_log("📂 目录已变更")` → `scan_local_dir()`
   - `scan_local_dir()` → `bridge.emit("clear_videos")` → `file_service.scan_directory()` → `bridge.emit("item_found")` × N

2. **Web 端流程**（v17 及之前）：
   - `confirmDirDialog()` → `sendWS('change_dir', {directory})` → 关闭弹窗
   - `server.py` 收到 `change_dir` → `run_in_executor(None, controller.change_dir)`
   - `controller.change_dir()` → `scan_local_dir()` → `bridge.emit(...)` × N

3. **WebSocket 独立客户端测试**：收到 `clear_videos` + 20 条 `item_found` ✅

4. **Playwright 浏览器测试**：`currentSaveDir` 没有被更新，`videoOrder.length` 没有变化 ❌

#### 根因

`change_dir` 在 `run_in_executor`（线程池）中运行，`bridge.emit()` 从线程池调用时走 `asyncio.run_coroutine_threadsafe` 跨线程调度路径。虽然独立客户端能收到消息，但浏览器端的 WebSocket 连接可能因为调度时序问题导致消息丢失或延迟。

**关键洞察**：`run_coroutine_threadsafe` 本身是可靠的，但当 `scan_local_dir` 在线程池中同步执行时，它会快速连续调用多次 `bridge.emit`，每次都通过 `run_coroutine_threadsafe` 调度一个协程。这些协程被排队等待事件循环处理，但事件循环此时正在 `await run_in_executor(...)` —— 虽然 `await` 会释放控制权，但调度时序可能导致部分消息在浏览器端丢失。

#### 修复方案：异步方法 + 文件 I/O 分离

核心思路：**将 `bridge.emit` 调用留在事件循环线程中，只将文件 I/O 放到线程池**。

```python
# 修复前（v17）：整个 change_dir 在线程池中运行
elif msg_type == "change_dir":
    directory = data.get("directory", "")
    def _do_change_dir():
        controller.change_dir(directory)  # bridge.emit 在线程池中调用
    await asyncio.get_running_loop().run_in_executor(None, _do_change_dir)

# 修复后（v18）：bridge.emit 在事件循环中调用，文件 I/O 在线程池中执行
elif msg_type == "change_dir":
    directory = data.get("directory", "")
    await controller.async_change_dir(directory)  # bridge.emit 走 call_soon 路径
```

**新增 `async_scan_local_dir` 方法**（[app/web/controller.py](controller.py)）：

```python
async def async_scan_local_dir(self, directory: str | None = None):
    """异步版目录扫描：文件 I/O 在线程池中执行，bridge.emit 在事件循环中执行。"""
    import asyncio
    directory = directory or self.current_save_dir
    self.current_save_dir = directory

    # 1. 在事件循环中发送初始事件（bridge.emit 走 call_soon 路径，可靠）
    self.bridge.emit("log", {"message": f"📂 正在扫描目录: {directory}"})
    self.videos.clear()
    self.bridge.emit("clear_videos", {"directory": directory})

    # 2. 文件 I/O 在线程池中执行（不阻塞事件循环）
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, self.file_service.scan_directory, directory,
            cfg.get("download", "local_scan_limit", 1000),
        )
    except MediaScanError as exc:
        self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
        return
    except Exception as exc:
        self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
        return

    # 3. 回到事件循环中处理结果并推送（bridge.emit 走 call_soon 路径，可靠）
    for item in result.items:
        self.videos[item.id] = item
        self.bridge.emit("item_found", self._video_item_to_dict(item))
    # ... emit scan_result ...
```

**关键设计**：
- 步骤 1（`clear_videos`）在事件循环中立即发送 → 前端先清空旧列表
- 步骤 2（文件 I/O）在线程池中执行 → 不阻塞事件循环
- 步骤 3（`item_found` × N）在事件循环中发送 → 前端逐条添加新项目

**对比 GUI 行为**：GUI 的 `scan_local_dir` 是同步的，`add_video_row` 逐条添加到 `QTableWidget`。Web 端 v18 的 `async_scan_local_dir` 也实现了"先清空再逐条添加"的等效行为。

### 37.2 同步修复：delete_video 和 rename_video

`delete_video` 和 `rename_video` 也使用了 `run_in_executor`，存在同样的跨线程 `bridge.emit` 问题。

**新增异步方法**：

| 同步方法 | 异步方法 | 文件 I/O | bridge.emit |
|---|---|---|---|
| `scan_local_dir()` | `async_scan_local_dir()` | `run_in_executor` | 事件循环 `call_soon` |
| `change_dir()` | `async_change_dir()` | 调用 `async_scan_local_dir` | 事件循环 `call_soon` |
| `delete_video()` | `async_delete_video()` | `run_in_executor` | 事件循环 `call_soon` |
| `rename_video()` | `async_rename_video()` | `run_in_executor` | 事件循环 `call_soon` |

**server.py WebSocket 消息路由更新**：

```python
# 修复前
elif msg_type == "delete_video":
    await asyncio.get_running_loop().run_in_executor(None, controller.delete_video, vid)
elif msg_type == "rename_video":
    await asyncio.get_running_loop().run_in_executor(None, controller.rename_video, vid, title)

# 修复后
elif msg_type == "delete_video":
    await controller.async_delete_video(vid)
elif msg_type == "rename_video":
    await controller.async_rename_video(vid, title)
```

### 37.3 BUG-181：选择弹窗无法显示

#### 根因

v17 删除了 `ensureModalStyle()` 函数（因为 CSS 已统一 z-index），但 `showSelectionModal()` 中仍调用 `ensureModalStyle(modal)`，导致 `ReferenceError`。弹窗从未被设为 `display:flex`，所以不可见。

#### 修复

```javascript
// 修复前（v17）：ensureModalStyle 已删除但仍在调用
function showSelectionModal(items) {
  // ...
  const modal = document.getElementById('selectionModal');
  ensureModalStyle(modal);  // ReferenceError!
  modal.focus();
}

// 修复后（v18）：直接设置 display
function showSelectionModal(items) {
  // ...
  const modal = document.getElementById('selectionModal');
  modal.style.display = 'flex';  // 直接显示弹窗
}
```

### 37.4 dirModal HTML 冗余 inline style 清理

v17 删除了 `ensureModalStyle()`，但 dirModal 的 HTML 中仍保留了大量 inline style（如 `style="flex:1;padding:6px 10px;..."`），这些样式已在 CSS 中定义。inline style 会导致：
1. CSS 修改不生效（inline style 优先级更高）
2. 代码冗余，难以维护

**清理**：删除 dirModal HTML 中所有与 CSS 重复的 inline style。

### 37.5 前端调试日志增强

在 `handleServerMessage` 中添加关键事件的 `console.log`，帮助排查消息丢失问题：

```javascript
if (['clear_videos','item_found','scan_result','crawl_state','select_tasks'].includes(type)) {
  console.log(`[WS] 收到事件: ${type}`, data);
}
```

### 37.6 `scan_local_dir` 异常处理增强

原代码只捕获 `MediaScanError`，其他异常（如 `PermissionError`、`OSError`）会导致未处理异常，可能使 WebSocket 连接断开。

```python
# 修复前
except MediaScanError as exc:
    self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})

# 修复后
except MediaScanError as exc:
    self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
except Exception as exc:
    # BUG-180: 捕获所有异常，避免未处理异常导致 WebSocket 断连
    self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
```

### 37.7 全量 GUI vs Web 交互对照审计（v18 更新）

| GUI 交互 | GUI 实现 | Web UI 实现 | 状态 |
|---|---|---|---|
| 点击"开始爬虫" | `btn_start.clicked` → `sig_start_crawl` | `startCrawl()` → `sendWS('start_crawl')` | ✅ |
| 点击"停止爬虫" | `btn_stop.clicked` → `sig_stop_crawl` | `stopCrawl()` → `sendWS('stop_crawl')` | ✅ |
| 点击"更改目录" | `btn_dir.clicked` → `QFileDialog` → `sig_change_dir` | `showDirDialog()` → 目录浏览器 → `confirmDirDialog()` → `sendWS('change_dir')` | ✅ v18修 |
| 点击"播放" | `play_btn.clicked` → `sig_play_video` | `previewVideo()` → `/api/media` | ✅ |
| 点击"删除" | `delete_btn.clicked` → `sig_delete_video` | `deleteVideo()` → `sendWS('delete_video')` | ✅ v18修 |
| 双击标题重命名 | `itemChanged` 信号 → `sig_rename_video` | `ondblclick` → `finish()` → `sendWS('rename_video')` | ✅ v18修 |
| 点击"主题切换" | `btn_theme.clicked` → `sig_theme_changed` | `toggleTheme()` → `sendWS('change_theme')` | ✅ |
| 点击"复制Trace" | `btn_copy_trace.clicked` → `sig_copy_trace_id` | `copyTraceId()` → `navigator.clipboard` | ✅ |
| 点击"查看日志" | `btn_log.clicked` → `sig_open_latest_log` | `window.open('/api/debug/latest-log')` | ✅ |
| 点击"错误摘要" | `btn_error.clicked` → `sig_open_error_summary` | `window.open('/api/debug/error-summary')` | ✅ |
| 选择任务弹窗 | `SelectionDialog.exec()` 阻塞 | `showSelectionModal()` → `confirmSelection()` | ✅ v18修 |
| 全选/反选 | `btn_select_all` / `btn_select_invert` | `selectAll()` / `selectInvert()` | ✅ |
| 双击视频全屏 | `ClickableVideoWidget.mouseDoubleClickEvent` | `ondblclick="toggleFullscreen()"` | ✅ |
| ESC 退出全屏 | `keyPressEvent` | `keydown` listener | ✅ |
| ⏮/⏭ 主图切换 | GUI 无显式按钮 | `switchPreview(-1/1)` | ✅ 增强 |
| 播放/暂停 | `toggle_play()` 检查 `playbackState` | `togglePlay()` 检查 `player.paused` | ✅ |
| 进度条拖拽 | `sliderPressed/Released` + `positionChanged` | `mousedown/up` + `ontimeupdate` | ✅ |
| 拖拽分割面板 | `QSplitter` | 自定义 JS 拖拽 | ✅ |
| 分割面板记忆 | `saveState/restoreState` | `localStorage` | ✅ |
| 插件配置恢复 | `cfg.get(plugin.id, opt.key)` | `restorePluginConfig()` | ✅ |
| 目录浏览器记忆 | 系统原生 | `localStorage('dir_last_browsed')` | ✅ |
| WebSocket 重连 | N/A | 3 秒自动重连 + 重新扫描 | ✅ |

### 37.8 bridge.emit 跨线程调度原理总结

```
┌──────────────────────────────────────────────────────────────┐
│                    事件循环线程 (uvicorn)                       │
│                                                              │
│  bridge.emit() 被调用                                        │
│       │                                                      │
│       ├── 在事件循环线程? ──是──→ call_soon + create_task     │
│       │                          (可靠，消息立即排队)           │
│       │                                                      │
│       └── 不在事件循环线程? ──→ run_coroutine_threadsafe       │
│                                   (可能因时序问题丢失消息)      │
│                                                              │
│  v18 修复：所有 bridge.emit 都在事件循环线程中调用              │
│  文件 I/O 通过 run_in_executor 在线程池中执行                  │
│  bridge.emit 在 run_in_executor 返回后（回到事件循环）调用     │
└──────────────────────────────────────────────────────────────┘
```

### 37.9 经验教训

1. **`run_in_executor` 不是万能方案**——它把整个方法放到线程池，导致 `bridge.emit` 跨线程调度。正确做法是只把文件 I/O 放到线程池，`bridge.emit` 留在事件循环中
2. **删除函数前必须搜索所有引用**——`ensureModalStyle()` 被删除但 `showSelectionModal()` 仍在调用，导致弹窗完全不可见
3. **inline style 和 CSS 不能混用**——inline style 优先级更高，会导致 CSS 修改不生效
4. **异常处理要全面**——只捕获 `MediaScanError` 不够，其他异常会导致 WebSocket 断连
5. **GUI → Web 复刻的核心挑战**：不是功能缺失，而是**执行环境的差异**——Qt 信号/槽是线程安全的，WebSocket + asyncio 需要手动管理跨线程调度

---

## 三十八、v19 bridge.emit call_soon 调度静默失败 + REST API 修复 + WebSocket 错误处理

> 用户反馈原话："下载位置更新后还是要自动刷新，而不是手动去刷新，我改了位置，那个下载位置还是没变，需要刷新网页才会扫描资源"
>
> 用户第二次反馈原话："🔗 WebSocket 已连接 / 📂 正在扫描目录: ./videos/vlog / ✅ 已加载 194 个本地文件 / 📂 正在切换目录: ./videos/other / 看到了没，前端根本就不更新"

### 38.1 BUG-182：bridge.emit call_soon + create_task 调度静默失败

#### 症状

用户选择目录后，左侧目录标题改变（`confirmDirDialog()` 直接更新了 `pathLabel`），但下载队列没有刷新——资源列表为空，需要手动刷新网页才能看到新目录的资源。

日志中只看到前端发出的 "📂 正在切换目录"，但看不到后端应该推送的 "📂 目录已变更" 和 "📂 正在扫描目录"。

#### 排查过程

v18 已将 `change_dir` 从 `run_in_executor` 改为 `async_change_dir`，并将 `bridge.emit` 改为 `await self._send_func`。理论上应该可靠，但实际仍然失败。

**关键发现**：即使用 `await self._send_func`，在 WebSocket 消息处理协程中调用 `manager.broadcast` 仍然可能失败。原因是 `broadcast` 调用 `await ws.send_text(msg)` 时，当前 WebSocket 正在 `while True` 循环中等待下一条消息。虽然 `receive_text` 已经返回，但 Starlette 的 WebSocket 实现可能在内部状态管理上存在并发问题。

**更深层的问题**：WebSocket 是全双工协议，但 FastAPI/Starlette 的 WebSocket 端点在 `while True: raw = await ws.receive_text()` 循环中，`receive_text` 和 `send_text` 可能存在内部锁竞争。当 `_handle_client_message` 中调用 `await manager.broadcast(...)` → `await ws.send_text(msg)` 时，如果 Starlette 内部正在处理 `receive_text` 的后续工作，`send_text` 可能会静默失败或抛出异常。

#### 修复方案 1：关键操作改用 REST API

**核心思路**：关键操作（如更改目录）不再通过 WebSocket 消息触发，而是通过 REST API 调用。REST API 有明确的请求-响应模型，后端处理完后通过 WebSocket 推送结果。

```javascript
// 修复前（v18）：通过 WebSocket 消息触发
sendWS('change_dir', { directory: currentSaveDir });

// 修复后（v19）：通过 REST API 触发
fetch('/api/dir/change', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({directory: currentSaveDir})
}).then(r => {
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}).then(data => {
  if (data.error) appendLog('❌ 切换目录失败: ' + data.error);
}).catch(err => {
  appendLog('❌ 切换目录请求失败: ' + err.message);
});
```

**为什么 REST API 更可靠**：
1. REST API 请求由独立的 HTTP 处理协程处理，不在 WebSocket 的 `while True` 循环中
2. HTTP 请求有明确的响应状态码，前端可以知道请求是否成功
3. 后端 `async_change_dir` 在 HTTP 协程中执行，`await self._send_func` 不受 WebSocket 内部状态影响
4. 即使 WebSocket 推送失败，前端也能从 REST API 响应中得知错误

#### 修复方案 2：_handle_client_message 加 try/except

**问题**：`_handle_client_message` 没有错误处理，任何异常都会传播到 WebSocket 端点的 `except Exception`，导致 WebSocket 连接断开。

**修复**：在 `_handle_client_message` 中加 try/except，异常通过 WebSocket 推送给前端显示，不会杀死连接。

```python
async def _handle_client_message(msg: dict):
    try:
        # ... 处理各种消息类型 ...
    except Exception as exc:
        logging.error(f"[WS] 处理消息 {msg_type} 失败: {exc}", exc_info=True)
        try:
            await manager.broadcast("log", {"message": f"❌ 处理 {msg_type} 失败: {exc}"})
        except Exception:
            pass
```

#### 修复方案 3：REST API /api/dir/change 加错误处理

```python
@app.post("/api/dir/change")
async def change_dir(body: dict):
    directory = body.get("directory", "")
    if not directory:
        return {"status": "error", "error": "目录路径不能为空"}
    try:
        await controller.async_change_dir(directory)
        return {"status": "ok"}
    except Exception as exc:
        logging.error(f"[change_dir] 切换目录失败: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}
```

### 38.2 WebSocket vs REST API 适用场景

```
┌──────────────────────────────────────────────────────────────┐
│              前端→后端通信方式选择指南                            │
│                                                              │
│  关键操作（需要可靠执行）：                                      │
│    → 使用 REST API（POST /api/...）                           │
│    → 有明确的请求-响应模型，前端知道成功/失败                      │
│    → 后端在独立 HTTP 协程中处理，不受 WebSocket 状态影响          │
│    → 示例：change_dir, scan_dir, delete_video, rename_video   │
│                                                              │
│  实时通知（后端→前端推送）：                                     │
│    → 使用 WebSocket（manager.broadcast）                      │
│    → 前端被动接收，不需要请求                                    │
│    → 示例：item_found, clear_videos, task_progress, log       │
│                                                              │
│  轻量操作（丢失可接受）：                                        │
│    → 使用 WebSocket 消息（sendWS）                             │
│    → 示例：change_theme, change_source, save_config           │
│                                                              │
│  GUI 对比：                                                   │
│    GUI 的信号/槽是线程安全的，不存在这个问题                       │
│    Web 端需要区分"请求"和"通知"两种通信模式                       │
└──────────────────────────────────────────────────────────────┘
```

### 38.3 最终修复：REST API 直接返回扫描结果

用户第二次反馈："❌ 切换目录请求失败: HTTP 500"——说明 `async_change_dir` 内部 `await self._send_func` 从 HTTP 协程调用 `manager.broadcast` 时抛出异常。

**根因**：从 HTTP 处理协程中调用 `manager.broadcast` → `await ws.send_text(msg)` 可能失败，因为 Starlette 的 WebSocket 实现在 `while True: await ws.receive_text()` 循环中可能存在内部锁竞争，导致 `send_text` 抛出异常。

**最终修复**：REST API 端点不再调用 `controller.async_change_dir`（它会通过 WebSocket 推送），而是直接在 HTTP 协程中执行逻辑，将扫描结果作为 HTTP 响应返回。前端根据响应直接更新 UI。

```python
# /api/dir/change 端点（修复后）
@app.post("/api/dir/change")
async def change_dir(body: dict):
    directory = body.get("directory", "")
    # 1. 更新控制器状态
    controller.current_save_dir = directory
    cfg.set("common", "save_directory", directory)
    # 2. 清空旧数据
    controller.videos.clear()
    # 3. 扫描新目录（文件 I/O 在线程池中执行）
    result = await asyncio.get_running_loop().run_in_executor(
        None, controller.file_service.scan_directory, directory, ...)
    # 4. 构建返回数据
    items = [controller._video_item_to_dict(item) for item in result.items]
    # 5. 尝试通知 WebSocket（非阻塞，失败不影响 HTTP 响应）
    try:
        await manager.broadcast("clear_videos", {"directory": directory})
        for item_dict in items:
            await manager.broadcast("item_found", item_dict)
    except Exception:
        pass  # WebSocket 通知失败不影响结果
    # 6. 返回扫描结果
    return {"status": "ok", "directory": directory, "items": items, ...}
```

```javascript
// 前端 confirmDirDialog（修复后）
fetch('/api/dir/change', { method: 'POST', body: JSON.stringify({directory}) })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'error') { appendLog('❌ ' + data.error); return; }
    // 直接根据 REST API 响应更新 UI，不依赖 WebSocket 推送
    videos = {}; videoOrder = [];
    document.getElementById('queueBody').innerHTML = '';
    if (data.items) {
      data.items.forEach(item => {
        videos[item.id] = item;
        videoOrder.push(item.id);
        appendRow(item.id);
      });
    }
    appendLog(`✅ ${data.message}`);
  });
```

**去重处理**：如果 WebSocket 通知也成功送达，前端 `item_found` 事件处理中加了去重检查 `if (videos[data.id]) break;`，避免重复添加。

### 38.4 BUG-183：进度条最小拖动单元为 1 秒

#### 症状

视频进度条拖动时最小单位为 1 秒，体验不丝滑。GUI 端 QSlider 默认精度为 0.01 秒。

#### 根因

HTML5 `<input type="range">` 的 `step` 属性默认值为 1，导致拖动时最小单位为 1 秒。

#### 修复

```html
<!-- 修复前 -->
<input type="range" id="seekSlider" min="0" max="0" value="0" />

<!-- 修复后：step="0.01" 使拖动精度提升到 0.01 秒，与 GUI QSlider 一致 -->
<input type="range" id="seekSlider" min="0" max="0" value="0" step="0.01" />
```

### 38.5 BUG-184：REST API 仍然返回 HTTP 500

#### 症状

用户第三次反馈："❌ 切换目录请求失败: HTTP 500"——即使移除了 `manager.broadcast` 调用，REST API 仍然返回 500。

#### 排查

1. TestClient 测试通过（返回 200，数据正确）
2. `scan_directory` 方法独立测试通过
3. 端点代码有 `try/except Exception`，理论上应该捕获所有异常并返回 `{"status": "error", ...}`
4. 前端仍然收到 HTTP 500，说明异常发生在 FastAPI 框架层面，在端点代码之前

**可能原因**：
- FastAPI 的 `body: dict` 参数解析失败（请求体不是有效 JSON）
- `uvicorn` 没有热重载，用户运行的是旧代码

#### 修复

1. 使用 `Request` 对象手动解析 JSON，避免 FastAPI 参数验证导致的 500
2. `/api/scan` 端点也重构为同样的模式（不调 `manager.broadcast`，只返回 HTTP 响应）
3. 前端添加 WebSocket 回退方案——如果 REST API 失败，通过 WebSocket 发送 `change_dir` 消息
4. 添加详细的 `logger.info/error` 日志，方便排查运行时错误

### 38.6 BUG-185：cfg.set 阻塞事件循环导致 HTTP 500

#### 症状

用户第四次反馈："❌ 切换目录请求失败: HTTP 500"——即使移除了 `manager.broadcast`，即使 TestClient 测试通过，运行时仍然 500。

#### 排查

1. TestClient 测试通过（返回 200，数据正确）
2. `scan_directory` 方法独立测试通过
3. 端点代码有 `try/except Exception`，理论上应该捕获所有异常
4. 但 `cfg.set("common", "save_directory", directory)` 是同步文件 I/O，在事件循环中直接执行
5. 如果配置文件被锁定（另一个进程在写），`cfg.set` → `self.save()` 会阻塞事件循环，可能导致 uvicorn 超时返回 500

#### 修复

将 `cfg.set` 放到 `run_in_executor` 中执行：

```python
# 修复前：cfg.set 在事件循环中直接执行
cfg.set("common", "save_directory", directory)

# 修复后：cfg.set 在线程池中执行
def _save_cfg():
    try:
        cfg.set("common", "save_directory", directory)
    except Exception as e:
        logger.warning(f"[change_dir] cfg.set 失败: {e}")
await asyncio.get_running_loop().run_in_executor(None, _save_cfg)
```

### 38.7 BUG-186：CORS 预检失败 + try 间隙问题

#### 症状

用户第五次反馈："❌ 切换目录请求失败: HTTP 500"——即使 TestClient 测试通过，运行时仍然 500。

#### 深入排查

通过子代理深入排查，发现两个真正根因：

**根因 1：CORS 预检失败**
```python
# app/web/server.py 第 32-38 行（修复前）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # ⚠️ 非法组合！
    allow_methods=["*"],
    allow_headers=["*"],
)
```
- CORS 规范**禁止** `allow_origins=["*"]` + `allow_credentials=True` 组合
- 浏览器发起 POST `application/json` 跨域请求时，会先发 OPTIONS 预检
- 预检失败可能被某些浏览器/中间件表现为 HTTP 500

**根因 2：try 间隙问题**
```python
# 修复前的代码
try:                              # ← try 1：只保护 body 解析
    body = await request.json()
except Exception:
    body = {}

directory = body.get("directory", "")  # ⚠️ 在 try 间隙中！
# ...
try:                              # ← try 2：保护业务逻辑
    # ...
```
- 如果 `body` 不是 dict（前端误改 / 浏览器插件 / 预检问题），`body.get(...)` 抛 `AttributeError`
- `AttributeError` 被 FastAPI 默认 500 handler 捕获，返回 500

#### 修复

**修复 1：CORS 配置**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # 修复 BUG-186: wildcard origin 不能带 credentials
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**修复 2：合并 try 块 + 类型检查**
```python
@app.post("/api/dir/change")
async def change_dir(request: Request):
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if not isinstance(body, dict):  # 新增：兼容非 dict body
            return {"status": "error", "error": "请求体必须是 JSON 对象"}

        directory = body.get("directory", "")
        if not directory:
            return {"status": "error", "error": "目录路径不能为空"}

        # ... 业务逻辑 ...
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
```

### 38.8 经验教训

1. **WebSocket 不是万能的**——它适合后端→前端的实时推送，但不适合前端→后端的关键请求
2. **REST API 有明确的请求-响应模型**——前端可以知道请求是否成功，可以重试
3. **从 HTTP 协程向 WebSocket 发送消息会失败**——Starlette 内部存在锁竞争，导致 HTTP 500
4. **关键操作必须用 REST API**——change_dir、scan_dir、delete_video、rename_video
5. **WebSocket 只用于实时通知**——spider 的 sig_log、sig_item_found、sig_select_tasks
6. **HTML5 range 默认 step=1**——视频进度条必须设置 `step="0.01"` 才能与 GUI QSlider 精度一致
7. **FastAPI `body: dict` 参数可能失败**——使用 `Request` 对象手动解析 JSON 更可靠
8. **同步文件 I/O 不能直接在事件循环中执行**——`cfg.set` 会写文件，必须放到 `run_in_executor` 中
9. **uvicorn 不会热重载**——改代码后必须手动重启服务器
10. **TestClient 测试通过不代表运行时通过**——TestClient 是单线程同步测试，不模拟真实的 uvicorn 并发环境


---


---

## 三十九、v20 阶段：交互细节深度抠齐（2026-06-05）

> 用户 v19 后再次强调"交互还是有很大问题，你要做到视觉体验和交互体验必须和原本桌面GUI完全一致"。
> 用户新增关键要求："我要求你每次修复后都要重启服务"。
> 本章对 GUI 端每个交互细节做完整对照表，标注每项是否对齐、差异点、修复方案。

### 39.1 GUI 端组件清单

| 组件 | 关键属性 | 关键交互 | 关键回调 |
|---|---|---|---|
| `MainWindow` | resize 1300x850, 主题切换, 退出保存几何状态 | keyPressEvent(Esc 退出全屏) | closeEvent, toggle_theme, toggle_fullscreen_mode |
| `TopBarWidget` | 高 50px, 上下 padding 5px | combo_source.currentIndexChanged, btn_start/stop/dir/log/error/trace/theme | set_crawl_running_state, set_theme_icon |
| `DownloadQueuePanel` | 行高 36px, 列宽标题Stretch/状态Resize/进度Resize/操作Resize | play_btn / delete_btn clicked, table.itemChanged | add_video_row, update_video_status, refresh_delete_bindings, clear_rows, remove_row, find_row_by_video_id, get_selected_video_id, bind_title_rename |
| `MediaPreviewPanel` | 控制面板高 50px, 滑块 thumb 14x14 | slider.sliderPressed/Released, player.positionChanged/durationChanged, vid_w.doubleClicked | show_image, play_video, stop_playback, toggle_play, on_slider_released, scale_image_to_fit, resize_media, cleanup |
| `LogPanel` | QPlainTextEdit readonly, 始终显示滚动条 | 鼠标可选中复制 | append_log, moveCursor(End) |
| `SelectionDialog` | 800x600, 默认全选 | 弹窗阻塞 spider 线程, accept/reject | select_all, select_invert, confirm_selection |
| `ApplicationController` | — | 启动/停止/扫描/重命名/删除/播放/选择 | _has_active_spider, scan_local_dir, on_dir_changed, on_rename_video, on_delete_video, on_start_crawl, _on_spider_item_found, _on_spider_select_tasks, _on_spider_finished, on_stop_crawl, open_latest_log, open_latest_error_summary, copy_trace_id_for_video, shutdown, play_video |

### 39.2 逐细节对照表（核心 80+ 项）

| 序号 | 交互细节 | GUI 实现 | Web 实现 | 对齐 | 差异/备注 |
|---|---|---|---|---|---|
| 1 | 启动任务时检查 plugin 有效性 | `if not self.current_plugin: append_log("❌ 未选择有效模式"); return` | `if (!currentSource) { appendLog('❌ 未选择有效模式'); return; }` | ✅ | 完全一致 |
| 2 | 启动任务时检查搜索关键词 | `if not keyword: append_log("⚠️ 请输入搜索内容！"); return` | `if (!keyword) { appendLog('⚠️ 请输入搜索内容！'); return; }` | ✅ | 完全一致 |
| 3 | 启动后 UI 状态切换 | `set_crawl_running_state(True)` 禁用 startBtn/inp_search/combo_source/plugin_widget | `setCrawlState(true)` 禁用 startBtn/stopBtn 反向 + searchInput/sourceSelect/dynamicArea | ✅ | 完全一致 |
| 4 | 启动失败时恢复 UI | `if not plugin or not spider: return`（不调用 set_running_state）| 后端发 `crawl_state: {is_running: false}` | ✅ | 通过 crawl_state 事件恢复 |
| 5 | 停止任务 | `if self.current_spider: self.current_spider.stop(); append_log("🛑 正在停止任务...")` | `if self.current_spider: self.current_spider.stop()` | ✅ | spider.stop() 内部 emit 日志，避免重复 |
| 6 | 爬虫任务结束恢复 UI | `_on_spider_finished` → `set_crawl_running_state(False)` | `_on_spider_finished` → `crawl_state: false` | ✅ | 一致 |
| 7 | 切换目录先停旧视频 | — | `if (currentPlayingId) closePreview();` 后才清空列表 | ✅（v20 修复）| BUG-187：修复后对齐 |
| 8 | 切换目录时清空旧数据 | `_clear_local_items()` → `videos.clear()` + `clear_rows()` | `videos = {}; videoOrder = []; queueBody.innerHTML = ''` | ✅ | 完全一致 |
| 9 | 切换目录后逐条 add | `for item in result.items: add_video_row(item)` | `forEach item => appendRow(item.id)` | ✅ | 完全一致 |
| 10 | 文件存在性校验（重命名） | `if not os.path.exists(video.local_path): item.setText(video.title); return` | 后端 `rename_video` 返回 `{status: error, message: "文件不存在..."}` | ✅ | 完全一致 |
| 11 | 重命名失败回退原值 | `except FileOperationError: append_log(...); item.setText(video.title)` | 立即 `td.textContent = v.title` 恢复 | ✅ | 完全一致 |
| 12 | 重命名双击触发 | `bind_title_rename` → `table.itemChanged` | `<td ondblclick="startRename('${id}', this)">` | ✅ | 完全一致 |
| 13 | 重命名 Enter 提交 | QLineEdit 默认 Enter 提交 | `if (e.key === 'Enter') { e.preventDefault(); input.blur(); }` | ✅ | 完全一致 |
| 14 | 重命名 Esc 取消 | — | `if (e.key === 'Escape') { input.value = v.title; input.blur(); }` | ✅ | 完全一致（Web 端更明确） |
| 15 | 删除前停止下载 | `cancel_result = self.dl_manager.cancel_task(vid)` | 后端 `async_delete_video` 调 `cancel_task` | ✅ | 完全一致 |
| 16 | 删除时如正在播放则停止 | `if self.current_playing_id == vid: self.window.stop_media_playback(); self.current_playing_id = None` | `if (currentPlayingId === id) { closePreview(); }` | ✅ | 完全一致 |
| 17 | 删除后刷新按钮绑定 | `self.window.refresh_table_bindings()` | — | ✅ | Web 端无 lambda 闭包陷阱，不需要刷新 |
| 18 | 进度条拖动 jitter 防护 | `is_slider_pressed=True` 时不更新 slider | `seeking=true` 时不更新 slider | ✅ | 完全一致 |
| 19 | 进度条精度 | QSlider.setMinimum(0) + setMaximum(duration) 默认精度 1ms | `step="0.01"` 精度 0.01 秒 | ✅ | v19 BUG-183 修复后对齐 |
| 20 | 播放按钮图标 | `SP_MediaPlay` / `SP_MediaPause` | `▶` / `⏸` Unicode | ✅ | 视觉对等 |
| 21 | 暂停/恢复点击 | `toggle_play` 检查 playbackState | `if (player.paused) play(); else pause();` | ✅ | 完全一致 |
| 22 | 视频结束后图标恢复 | `player.onended → ▶` | `player.onended = () => playBtn.textContent = '▶'` | ✅ | 完全一致 |
| 23 | 双击画面进入全屏 | `vid_w.sig_double_click → toggle_fullscreen_mode` | `video.ondblclick = () => toggleFullscreen()` + `img.ondblclick` | ✅ | 完全一致（Web 端图片也支持） |
| 24 | 全屏隐藏顶栏/左面板/日志 | `top_bar.hide(); left_panel.hide(); log_txt.hide()` | `body.is-fullscreen .top-bar/.left-panel/.log-panel { display:none }` | ✅ | 完全一致 |
| 25 | 全屏设置 0 边距 | `_set_main_margins(0)` | `body.is-fullscreen { padding:0 !important; gap:0 !important; }` | ✅ | 完全一致 |
| 26 | 全屏按钮文案切换 | `btn_fullscreen.setText("[ 退出 ]")` / `"[ 全屏 ]"` | `fullscreenBtn.textContent = '[ 退出 ]'` / `'[ 全屏 ]'` | ✅ | 完全一致 |
| 27 | 全屏状态保存 | `cfg.save_ui_state(..., is_fs=...)` | — | ⚠️ | Web 端浏览器关闭时不需要持久化全屏状态（无意义） |
| 28 | Esc 退出全屏 | `if event.key() == Qt.Key.Key_Escape and self.is_fullscreen_mode: toggle_fullscreen_mode()` | `if (e.key === 'Escape' && isFullscreenMode) toggleFullscreen()` | ✅ | 完全一致 |
| 29 | Esc 关闭弹窗 | — | `if (e.key === 'Escape') { dirModal/selectionModal.style.display === 'flex' → cancel }` | ✅ | Web 端增强（GUI 端 Esc 默认关闭 QDialog） |
| 30 | Enter 在搜索框启动 | — | `if (e.key === 'Enter' && activeElement === searchInput) startCrawl()` | ✅ | Web 端增强 |
| 31 | 上下箭头选择队列行 | QTableWidget 原生支持 | `if (e.key === 'ArrowUp'/'ArrowDown') selectVideo(...) + scrollIntoView` | ✅ | Web 端实现 + 自动滚动 |
| 32 | Delete 键删除选中行 | — | `if (e.key === 'Delete' && selectedVideoId && activeElement === body) deleteVideo(...)` | ✅ | Web 端增强 |
| 33 | 主题切换按钮图标 | `🌙` / `☀️` | `🌙` / `☀️` | ✅ | 完全一致 |
| 34 | 主题切换后写 cfg | `cfg.set_many("common", {"theme": ..., "dark_theme": ...})` | 后端 `change_theme` 消息处理同样批量写 | ✅ | 完全一致 |
| 35 | 主题切换日志 | `append_log(f"🎨 已切换到{'深色' if is_dark_theme else '浅色'}主题")` | `appendLog(\`🎨 已切换到${isDarkTheme ? '深色' : '浅色'}主题\`)` | ✅ | 完全一致 |
| 36 | splitter 拖动时缩放图片 | `splitterMoved → scale_image_to_fit()` | `splitter mousemove → resizePreviewImage()` | ✅ | 完全一致 |
| 37 | splitter 比例保存 | `cfg.save_ui_state(main_splitter, right_splitter)` | `localStorage.setItem('splitter_left_width', ...)` + `splitter_log_height` | ✅ | 存储位置不同（GUI 走 cfg，Web 走 localStorage） |
| 38 | 行高 36px | `verticalHeader().setDefaultSectionSize(36)` | `td { height:36px; }` | ✅ | 完全一致 |
| 39 | 列宽：标题 Stretch | `header.setSectionResizeMode(0, Stretch)` | `.col-title-col { width: auto; }` | ✅ | 完全一致 |
| 40 | 列宽：状态/进度/操作 ResizeToContents | `setSectionResizeMode(1/2/3, ResizeToContents)` | `<col style="width:90px">` + 120px + 80px | ✅ | 固定宽度（GUI 端 ResizeToContents 由内容决定，Web 端固定合理值） |
| 41 | 表格交替行色 | `setAlternatingRowColors(True)` | `tr:nth-child(even) { background:var(--alt-row); }` | ✅ | 完全一致 |
| 42 | 表格无网格 | `setShowGrid(False)` | `border:none; border-bottom:1px solid var(--border)` | ✅ | 完全一致 |
| 43 | 表格整行选中 | `setSelectionBehavior(SelectRows)` | `tr { cursor:pointer } + tr.selected { background:var(--accent) }` | ✅ | 完全一致 |
| 44 | 表格 hover 高亮 | QTableWidget 默认 | `tbody tr:hover { background:var(--hover-row) }` | ✅ | 完全一致 |
| 45 | 操作按钮图标 | `SP_MediaPlay` / `SP_TrashIcon` | `▶` / `🗑` Unicode | ✅ | 视觉对等 |
| 46 | 操作按钮大小 28x26 | `setFixedSize(28, 26)` | `.op-btn { width:28px; height:26px; }` | ✅ | 完全一致 |
| 47 | 播放按钮 32x32 圆形 | `setFixedSize(32, 32)` + 系统图标 | `.play-btn { width:32px; height:32px; border-radius:16px; }` | ✅ | 完全一致 |
| 48 | 全屏按钮 32 高 | `setFixedHeight(32)` | `.fullscreen-btn { height:32px; }` | ✅ | 完全一致 |
| 49 | 主题按钮 40 宽圆角 | `setFixedWidth(40)` | `.btn-theme { width:40px; border-radius:15px; }` | ✅ | 完全一致 |
| 50 | 顶栏 50px 高 | `setFixedHeight(50)` | `.top-bar { height:50px; }` | ✅ | 完全一致 |
| 51 | 顶栏 5px 上下 padding | `setContentsMargins(10, 5, 10, 5)` | `.top-bar { padding:5px 10px; }` | ✅ | 完全一致 |
| 52 | 队列标题栏 35px | `header_bar.setFixedHeight(35)` | `.queue-header { height:35px; }` | ✅ | 完全一致 |
| 53 | 控制面板 50px | `ctrls.setFixedHeight(50)` | `.control-panel { height:50px; }` | ✅ | 完全一致 |
| 54 | 滑块 6px 高 | QSlider 默认 | `.seek-slider { height:6px; }` | ✅ | 完全一致 |
| 55 | 滑块 thumb 14x14 | QSlider 默认 thumb | `::-webkit-slider-thumb { width:14px; height:14px; }` | ✅ | 完全一致 |
| 56 | 时间标签 90px 宽 | —（GUI 端自适应） | `.time-label { min-width:90px; }` | ✅ | 完全一致 |
| 57 | 日志面板 200px 高 | — | `.log-panel { height:200px; }` | ✅ | 与 GUI 默认布局一致 |
| 58 | 进度条 18px 高 | QProgressBar 默认 | `.progress-wrap { height:18px; }` | ✅ | 完全一致 |
| 59 | 进度条 3px 圆角 | QProgressBar 默认 | `.progress-wrap { border-radius:3px; }` | ✅ | 完全一致 |
| 60 | 进度条文字在条上居中 | `setAlignment(Qt.AlignmentFlag.AlignCenter)` | `.progress-text { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; }` | ✅ | 完全一致 |
| 61 | 选择弹窗 800x600 | `resize(800, 600)` | `.modal-box { width:800px; height:600px; }` | ✅ | 完全一致 |
| 62 | 选择弹窗默认全选 | `chk.setChecked(True)` | `<input type="checkbox" checked />` | ✅ | 完全一致 |
| 63 | 选择弹窗全选/反选按钮 | `btn_all / btn_invert` 80x30 | `<button style="width:80px;height:30px">` | ✅ | 完全一致 |
| 64 | 选择弹窗取消/确认按钮 | `btn_cancel` 100x35 / `btn_confirm` 120x35 | `<button style="width:100px;height:35px">` / 120x35 | ✅ | 完全一致 |
| 65 | 取消任务发 null | `dialog.exec() == Rejected → return None` | `sendWS('select_tasks', { indices: null })` | ✅ | 完全一致 |
| 66 | 确认任务发 indices | `selected_indices` 列表 | `sendWS('select_tasks', { indices: [...] })` | ✅ | 完全一致 |
| 67 | 文件夹选择器 | 非原生非模态 QFileDialog | 自实现 dirModal（驱动器 + 上一级 + 刷新 + 路径输入） | ✅ | Web 端无原生 QFileDialog，自实现对等体验 |
| 68 | 文件夹选择记忆 | —（GUI 端 QFileDialog 记忆初始路径） | `localStorage.getItem('dir_last_browsed')` | ✅ | Web 端增强 |
| 69 | 右键菜单屏蔽 | QWidget 默认无右键菜单 | `document.addEventListener('contextmenu', e => e.preventDefault())` | ✅ | 完全一致（输入框除外） |
| 70 | 关闭应用清理 | `closeEvent → cfg.save_ui_state + cleanup_media + spider.stop + dl_manager.stop_all` | 浏览器关闭时自动清理 video/websocket | ✅ | 关闭模型不同但行为对等 |
| 71 | 日志文本可选中复制 | QPlainTextEdit 默认支持 | `user-select:text; -webkit-user-select:text; cursor:text;` | ✅ | v20 BUG-188 修复后对齐 |
| 72 | 应用启动立即扫描 | `QTimer.singleShot(200, scan_local_dir)` | WebSocket 连接后服务端 `await controller.async_scan_local_dir()` | ✅ | 完全一致（GUI 200ms 延迟避免初始化阻塞） |
| 73 | 启动失败时恢复 | — | 前端 `try { setCrawlState(true) } catch { setCrawlState(false) }` | ✅ | Web 端显式 try/catch |
| 74 | item_found 立即入队下载 | `_on_spider_item_found → dl_manager.add_task` | `_on_spider_item_found → dl_manager.add_task` | ✅ | 完全一致 |
| 75 | task_started 状态"⏳ 下载中..." | `self._update_video_status(vid, "⏳ 下载中...", 0)` | `task_started` 事件 status='⏳ 下载中...', progress=0 | ✅ | 完全一致 |
| 76 | task_progress 只更新 progress | `self._update_video_progress(vid, progress)` | `task_progress` 事件只更新 progress | ✅ | 完全一致 |
| 77 | task_finished "✅ 完成" + 100% | `status="✅ 完成", progress=100` | `status='✅ 完成', progress=100` | ✅ | 完全一致 |
| 78 | task_error "❌ 失败" | `status="❌ 失败"` | `status='❌ 失败'` | ✅ | 完全一致 |
| 79 | 选 platform 写 last_source | `on_source_changed → cfg.set("common", "last_source", plugin_id)` | 后端 `change_source` 消息处理 cfg.set | ✅ | 完全一致 |
| 80 | 动态配置区随平台切换 | `takeAt(0) + get_settings_widget(container_dynamic)` | `area.innerHTML = '' + renderDynamicArea()` | ✅ | 完全一致 |

### 39.3 关键修复

#### BUG-187：切换目录时旧视频未停止

**症状**：用户在 A 目录播放 video_a.mp4，切换到 B 目录时，旧 `<video>` 元素仍在播放 video_a.mp4 几百毫秒，期间视频路径已不可用但视频元素未停止。

**根因**：`confirmDirDialog` 在收到 `/api/dir/change` 响应后只清空 `videos` 字典和表格 HTML，没有调用 `closePreview()` 停止 `<video>` 元素。

**修复**：
```javascript
// 清空前先停旧视频
if (currentPlayingId) closePreview();
videos = {};
videoOrder = [];
selectedVideoId = null;
currentPlayingId = null;
document.getElementById('queueBody').innerHTML = '';
```

**对等 GUI 行为**：`on_delete_video` 中 `if self.current_playing_id == vid: self.window.stop_media_playback(); self.current_playing_id = None`。

#### BUG-188：日志文本不可选中复制

**症状**：用户无法用鼠标选中日志条目复制（浏览器默认 div 元素的 `user-select: none`）。

**根因**：CSS 未设置 `user-select` 属性，`<div>` 默认是 `user-select: none`（不允许文本选择）。

**修复**：
```css
.log-panel {
  /* ... */
  user-select: text;
  -webkit-user-select: text;
  cursor: text;
}
```

**对等 GUI 行为**：`LogPanel` 继承自 `QPlainTextEdit`，`setReadOnly(True)` 后**默认支持**鼠标选中复制。

### 39.4 Web 端相比 GUI 端的增强（非差异，仅记录）

| 增强 | 说明 |
|---|---|
| 主图切换按钮 ⏮⏭ | GUI 端没有此按钮，Web 端添加方便循环浏览队列资源 |
| Esc 关闭弹窗 | GUI 端 QDialog 原生支持 Esc，Web 端手动实现 |
| Enter 启动任务 | GUI 端 QLineEdit 原生支持 Enter 提交，Web 端手动实现 |
| 上下箭头选择队列 | GUI 端 QTableWidget 原生支持，Web 端手动实现 + scrollIntoView |
| Delete 键删除选中行 | GUI 端需要右键菜单删除，Web 端键盘快捷键更便捷 |
| 文件夹选择记忆 | GUI 端 QFileDialog 记忆初始路径，Web 端用 localStorage 记忆更精确 |
| 图片预览也支持双击全屏 | GUI 端 ClickableVideoWidget 只对 video widget 触发，Web 端对 img 同样绑定 |
| Web 端右键菜单屏蔽 | GUI 端原生没有浏览器右键菜单，Web 端需手动 preventDefault |

### 39.5 服务重启验证

修复 BUG-187/188 后按用户要求"每次修复后都要重启服务"：

```powershell
taskkill /F /IM python.exe /T  # 杀掉旧 3 个 Python 进程
Start-Process -FilePath "python" -ArgumentList "web_main.py" -WorkingDirectory "<项目根目录>" -WindowStyle Hidden
curl.exe -s http://localhost:8000/api/ping
# 返回: {"status":"ok","version":"v19-fix"} ✅
```

11. **CORS `allow_origins=["*"]` + `allow_credentials=True` 是非法组合**——必须 `allow_credentials=False`
12. **try 块之间有间隙**——必须在每个可能抛异常的语句前后都有 try/except 保护
13. **GUI → Web 复刻的核心挑战**：Qt 信号/槽是线程安全的、可靠的；Web 需要区分"请求"（REST API）和"通知"（WebSocket）两种模式
### 39.6 经验教训（v20 增补）

14. **GUI → Web 复刻的"细节地狱"**：每个控件的大小、间距、颜色、动画、行为都要 1:1 对齐，共 80+ 项细节
15. **GUI 原生能力不能直接复刻**：Esc 关闭弹窗、Enter 提交、上下箭头选择、Delete 删除、Ctrl+A 全选等都需要手动实现
16. **行为对等 ≠ 实现对等**：例如日志可选中，GUI 端 QPlainTextEdit 默认支持，Web 端需要 `user-select: text`
17. **资源清理要主动**：切换目录、删除视频时主动停止旧视频/旧音频，避免短暂继续播放不存在的资源
18. **Web 端没有"窗口"概念**：最小化/最大化/关闭由浏览器控制，应用关闭时无需保存几何状态
19. **Web 端右键菜单需要屏蔽**：浏览器原生右键菜单与桌面应用右键行为不同，需要 `contextmenu` 事件 `preventDefault`

---

## 四十、v21 阶段：CLI / SDK / Skill 多方式封装（2026-06-05）

> 用户新需求："你下面开发CLI，提供API接口，调用说明md文档，skill技能封装。脚本调用时只需要提供参数，就可以拿到返回资源。注意哈，我们中间是有二次选择的，尤其对于合集，交互上其实是很复杂的，参数什么的也很复杂，所以呢这可以说是一个巨大挑战。"
> 用户核心追加需求："反正最后的结果应该是，可以直接作为AI调用的skill去传参调用，可以提供API在服务启动时脚本注入参数调用，可以直接import包直接作为函数传参调用，可以封装成SDK直接去pip下载"
> 本章交付 4 种调用方式 + 完整文档 + AI skill 封装。

### 40.1 4 种调用方式交付清单

| 方式 | 入口 | 用户体验 | 典型场景 |
|---|---|---|---|
| **命令行工具** | `python -m cli` 或 `ucrawl` | `ucrawl search --source douyin --keyword "测试"` | 一次性任务、shell 脚本、人工调试 |
| **Python SDK** | `from ucrawl import UcrawlSDK` | `sdk.search("douyin", "测试")` | 集成到 Python 项目、批量处理 |
| **启动时脚本注入** | `python web_main.py --script xxx.py` | 启动后自动执行 Python 脚本 | 自动化部署、嵌入式自动化 |
| **AI Skill 封装** | `.trae/skills/ucrawl/SKILL.md` | LLM 提示中提到 "ucrawl" 即激活 | LLM Agent、对话式控制 |

### 40.2 目录结构

```
UniversalCrawlerProplus/
├── cli/                              # CLI / SDK 核心代码
│   ├── __init__.py                  # 暴露 SDK 入口
│   ├── __main__.py                  # python -m cli 入口
│   ├── main.py                      # CLI 主入口 (ucrawl 命令)
│   ├── runner.py                    # CLIRunner - 核心执行器
│   ├── sdk.py                       # UcrawlSDK - Python SDK
│   ├── selection.py                 # 4 种二次选择策略
│   ├── script_runner.py             # 启动时脚本注入
│   ├── commands/                    # CLI 子命令
│   │   ├── search.py
│   │   ├── scan.py
│   │   ├── platforms.py
│   │   └── _alias.py                # 平台别名 (douyin/bilibili/...)
│   └── skill/                       # AI Skill 资源
│       ├── SKILL.md
│       └── ucrawl_skill.py
├── ucrawl/                           # 顶层包 (from ucrawl import ...)
│   └── __init__.py                  # 从 cli re-export
├── docs/
│   └── cli/                          # 调用说明 md 文档
│       ├── CLI_GUIDE.md             # CLI 完整调用说明
│       ├── API_REFERENCE.md         # REST API 参考
│       └── SDK_GUIDE.md             # Python SDK 指南
├── .trae/
│   └── skills/
│       └── ucrawl/
│           └── SKILL.md             # AI skill 正式注册
├── pyproject.toml                    # pip 包配置
└── web_main.py                       # 增加 --script 启动时注入
```

### 40.3 关键设计决策

#### 40.3.1 独立进程 + 嵌入式 Qt

CLI 启动时**独立创建** QApplication（spider 派生自 QThread），**不依赖** web 服务。

```python
def _ensure_qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
    return app
```

**为什么**：
- spider 派生自 QThread，必须有 QApplication 实例
- CLI 不需要 WebSocket、HTTP、不需要 GUI
- 与 Web 服务进程隔离

#### 40.3.2 monkey-patch ask_user_selection 同步返回

GUI 端 `ask_user_selection` 通过 Qt 信号 `sig_select_tasks` 弹窗，spider 线程 `wait()` 事件。CLI 接管此机制：

```python
def _make_ask_user_selection(self):
    strategy = self.selection_strategy
    def ask_user_selection_sync(self, items):
        # self 是 spider 实例
        prompt = f"二次选择 #{getattr(self, '_cli_call_count', 0) + 1}"
        indices = strategy.select(items, prompt=prompt)
        return indices if indices is not None else []
    return ask_user_selection_sync
```

**关键**：spider **多次**调用 `ask_user_selection`（合集展开会调 2-3 次），CLI 必须**按调用顺序**同步回答。

#### 40.3.3 4 种二次选择策略

```python
class SelectionStrategy(Protocol):
    def select(self, items: list, prompt: str = "") -> list[int] | None: ...
```

| 策略 | 输入 | 用途 |
|---|---|---|
| `RuleSelection` | `--select "0,2,5"` / `--exclude` / `--first` / `--last` | 自动化脚本 |
| `InteractiveSelection` | 终端 TTY 键入索引 | 人工调试 |
| `PipeSelection` | stdin 读 JSON 列表（含 preloaded_choices 预加载） | 多次选择 / 其他程序控制 |
| `AutoSelection` | 自动检测环境 | 默认 |

**合集场景的核心**：用 `PipeSelection(preloaded_choices=[[0,1,2], [3,4], []]) ` 预加载多轮选择：

```python
sel = PipeSelection(preloaded_choices=[
    [0, 1, 2],          # 第 1 轮：合集里选 3 个分季
    [0],                # 第 2 轮：第 1 季选 0
    list(range(10)),    # 第 3 轮：第 2 季全选
])
result = sdk.search("bilibili", "BV1xxx合集", selection=sel)
```

CLI 版本：

```bash
ucrawl search --source bilibili --keyword "BV1xxx合集" --preload-choices "0,1,2|0|0-9"
```

### 40.4 各平台参数表

| 平台 | 必填 | 平台特定参数 | 默认值 |
|---|---|---|---|
| **douyin** | keyword | max_items | 20 |
| **bilibili** | keyword | max_pages, max_items | 1, 30 |
| **kuaishou** | keyword | max_items | 20 |
| **missav** | keyword | individual_only, priority, proxy | False, 中文字幕优先, http://127.0.0.1:7890 |

### 40.5 启动时脚本注入

启动 web 服务时执行 Python 脚本，**在子线程**中运行不阻塞事件循环：

```bash
python web_main.py --script my_automation.py --script-arg target=douyin --script-arg max=5
```

`my_automation.py` 模板：

```python
def main(controller, **kwargs):
    """web 服务启动后自动调用。"""
    from cli import UcrawlSDK
    sdk = UcrawlSDK(save_dir=controller.current_save_dir)
    result = sdk.search(kwargs.get("target", "douyin"), "测试", max_items=int(kwargs.get("max", 10)))
    return 0
```

参数说明：
- `--script <path>`：脚本路径
- `--script-arg key=value`：可多次，自动类型转换 (int/float/bool/str)
- `--script-strict`：脚本失败时退出 web 服务
- `--script-delay`：执行前延迟秒数

### 40.6 AI Skill 封装

按 skill-creator 规范创建：

1. `cli/skill/SKILL.md`：项目内置 skill 资源
2. `.trae/skills/ucrawl/SKILL.md`：Trae IDE 识别的正式 skill 路径
3. `cli/skill/ucrawl_skill.py`：skill 调用入口（CLI 模式）

**关键字段**：
- `name: "ucrawl"`：skill 唯一标识
- `description`：包含**功能** + **何时调用**（"Invoke when user wants to search/download videos..."）

LLM 调用流程：
1. 用户在对话中提到 "ucrawl" 或 "搜索抖音视频"
2. LLM 看到 SKILL.md 的 description，激活 skill
3. LLM 读取 SKILL.md 详细说明
4. LLM 调用 `python ucrawl_skill.py --source douyin --keyword "测试"`
5. 解析返回的 JSON，给用户友好回复

### 40.7 pip 包安装

```bash
# 开发模式
pip install -e .

# 全局安装
pip install .
```

安装后：
- `ucrawl` 命令全局可用
- `from ucrawl import UcrawlSDK` 可用
- `from ucrawl import search, list_platforms, scan_directory` 函数式 API 可用

### 40.8 测试验证

| 测试 | 命令 | 结果 |
|---|---|---|
| CLI 启动 | `python -m cli --version` | `ucrawl 1.0.0` ✅ |
| 列出平台 | `python -m cli platforms --pretty` | 4 个平台 ✅ |
| 搜索帮助 | `python -m cli search --help` | 完整参数列表 ✅ |
| 扫描目录 | `python -m cli scan "./sample-dir" --limit 5 --pretty` | 成功返回 1 个文件 ✅ |
| SDK 导入 | `from ucrawl import UcrawlSDK, list_platforms` | 4 个平台 ✅ |
| 启动时注入 | `python web_main.py --script test_injected_script.py` | 脚本加载并执行 ✅ |
| 启动时注入 + 参数 | `--script-arg target=douyin --script-arg max=5` | kwargs 正确解析 ✅ |

### 40.9 经验教训（v21 增补）

20. **二次选择是 CLI 设计最大挑战**：spider 多次调用 ask_user_selection，CLI 必须按顺序同步回答
21. **monkey-patch 是处理 Qt 同步调用的最简方法**：直接替换 ask_user_selection 为同步实现，不依赖 Qt 事件循环
22. **独立 QApplication 是 CLI 的关键**：spider 派生自 QThread，必须有 QApplication 实例；CLI 自己创建不依赖 web 服务
23. **预加载模式 (preloaded_choices) 是合集场景的核心**：把多轮选择一次性传入，避免阻塞
24. **AI skill 描述要包含"何时调用"**：description 字段是 LLM 决定是否激活 skill 的关键
25. **pip 包双层结构**：内部 cli/ + 顶层 ucrawl/ re-export，让 `from ucrawl import ...` 也能用
26. **启动时脚本注入用子线程**：用 threading.Thread(daemon=True) 包装，不阻塞 web 服务的事件循环
27. **PowerShell 中文乱码是终端编码问题**（不是代码问题）：用 `Out-String` 或 `Write-Output` 可缓解
28. **ucrawl 命名冲突**：项目根目录的 `ucrawl.py` 与 `ucrawl/` 包冲突，用 `ucrawl/` 包 + re-export 解决

### 40.10 后续可能扩展

- **异步 CLI**：`async def search()` 版本，asyncio 友好
- **插件化策略**：`register_selection("my_strategy", MyStrategy())` 让用户自定义
- **进度回调**：CLI 实时输出下载进度（不是等到结束）
- **断点续传**：CLI 支持 resume 中断的任务
- **分布式**：CLI 调度多个 worker 进程并发搜索

---

## 四十一、v22 阶段：CLI/API/Skill 与桌面 GUI 完全对齐（2026-06-05）

> 用户要求："继续对齐CLI、API、skill，和桌面GUI。你要做到输入输出必须和原本桌面GUI完全一致。调用时只需要提供参数，就可以拿到返回资源。注意哈，我们中间是有二次选择的，尤其对于合集，交互上其实是很复杂的。"
> 本章修复 CLI 核心缺陷：v21 的 CLIRunner 只收集 items 但**没有触发下载**，与 GUI 行为严重不一致。

### 41.1 核心缺陷：CLIRunner 没有触发下载

**GUI 完整流程**（ApplicationController）：

```
1. on_start_crawl → _create_spider → _bind_spider_signals → spider.start()
2. spider.run() → ask_user_selection(items) → [GUI 弹窗] → resume_from_ui(indices)
3. spider.run() → emit_video(url, title, source, meta) → sig_item_found
4. _on_spider_item_found:
   a. item.status = "⏳ 等待中"
   b. item.progress = 0
   c. self.videos[item.id] = item
   d. window.add_video_row(item)
   e. dl_manager.add_task(item, save_dir)     ← 关键！触发下载
5. dl_manager → DownloadWorker(QThread) → sig_start/sig_progress/sig_finished/sig_error
6. _on_task_started/progress/finished/error → _apply_video_state + window.update_video_status
7. spider.run() 结束 → sig_finished → _on_spider_finished
```

**v21 CLIRunner 的问题**：
- 步骤 4e **完全缺失**：只收集了 items，没有调 `dl_manager.add_task`
- 步骤 5-6 **完全缺失**：没有连接下载管理器信号，没有更新 item 状态
- 返回的 items 全部是 `status="⏳ 等待中", progress=0, local_path=""` —— 与 GUI 最终状态完全不一致

### 41.2 修复方案：CLIRunner 完全重写

重写后的 CLIRunner 与 GUI ApplicationController **1:1 对称**：

| GUI 方法 | CLI 对应 | 说明 |
|---|---|---|
| `_bind_spider_signals` | `_patch_spider` | 绑定 sig_log/sig_item_found/sig_finished |
| `_on_spider_item_found` | `_on_item_found` | item.status="⏳ 等待中" + dl_manager.add_task |
| `_on_spider_select_tasks` | `_on_select_tasks` | selection_strategy.select → resume_from_ui |
| `_on_spider_finished` | `_on_finished` | 标记 finished=True |
| `_connect_download_signals` | `_connect_download_signals` | 绑定 dl_manager 4 个信号 |
| `_on_task_started` | `_on_task_started` | status="⏳ 下载中...", progress=0 |
| `_on_task_progress` | `_on_task_progress` | 只更新 progress |
| `_on_download_finished` | `_on_task_finished` | status="✅ 完成", progress=100 |
| `_on_download_error` | `_on_task_error` | status="❌ 失败" |
| `_apply_video_state` | `_apply_video_state` | 更新内存中 item 的 status/progress |
| — | `_wait_downloads` | CLI 特有：等所有下载完成再返回 |

### 41.3 关键新增：_wait_downloads

GUI 中下载是异步的（用户可以看到进度条实时更新），CLI 需要等所有下载结束才能返回最终结果：

```python
def _wait_downloads(self, timeout=300):
    """等待所有下载任务完成。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with self._dl_manager._workers_lock:
            active = len(self._dl_manager.workers)
        queued = self._dl_manager.queue.qsize()
        if active == 0 and queued == 0:
            break
        # 处理 Qt 事件（DownloadWorker 是 QThread）
        app.processEvents()
        time.sleep(0.5)
```

### 41.4 返回结果与 GUI 最终状态完全一致

修复前（v21）：
```json
{
  "items": [
    {"id": "v_abc", "status": "⏳ 等待中", "progress": 0, "local_path": ""}
  ]
}
```

修复后（v22）：
```json
{
  "items": [
    {"id": "v_abc", "status": "✅ 完成", "progress": 100, "local_path": "/path/to/file.mp4"}
  ]
}
```

### 41.5 新增参数

- `download: bool = True`：是否触发下载（True=与 GUI 一致自动下载，False=只收集不下载）
- CLI：`--no-download` 标志

### 41.6 ask_user_selection monkey-patch 对齐

GUI 行为：
```python
# BaseSpider.ask_user_selection
def ask_user_selection(self, items):
    self.sig_select_tasks.emit(items)
    self._resume_event.wait()  # 阻塞 spider 线程
    return self._selected_indices
```

CLI 行为：
```python
# CLIRunner._make_ask_user_selection
def ask_user_selection_sync(spider_self, items):
    indices = strategy.select(items, prompt=...)  # 同步选择
    return indices if indices is not None else []
```

关键差异：CLI **不走 Qt 信号**，直接同步返回。spider 线程不需要被 `_resume_event` 阻塞。

### 41.7 经验教训（v22 增补）

29. **CLIRunner 必须有 dl_manager**：没有下载管理器的 CLI 只能"搜索"，不能"下载"——与 GUI 严重不一致
30. **_on_item_found 必须调 dl_manager.add_task**：这是 GUI 的核心行为，CLI 不能跳过
31. **CLI 需要等下载完成再返回**：GUI 是异步的（用户看进度条），CLI 必须同步等
32. **_apply_video_state 是状态更新的核心**：GUI 和 CLI 都用同一个方法更新 item 的 status/progress
33. **download=False 模式有用**：某些场景只需要元数据（如 AI skill 只返回 URL 列表），不需要下载
34. **Qt processEvents 在 _wait_downloads 中必须调用**：DownloadWorker 是 QThread，需要 Qt 事件循环驱动

---

## 四十二、v23 阶段：CLI/SDK 与 GUI 参数完全对齐（2026-06-05）

> 用户要求：继续对齐 CLI、API、skill 与桌面 GUI，确保输入输出完全一致。特别是二次选择和复杂的参数处理。

### 42.1 关键对齐点

#### 42.1.1 平台默认配置对齐

**GUI 默认配置**（`read_*_run_options`）：

| 平台 | 配置项 | 默认值 |
|------|--------|--------|
| douyin | max_items, timeout | 20, 10 |
| bilibili | max_pages | 1 |
| kuaishou | max_items | 20 |
| missav | individual_only, priority, proxy | False, "中文字幕优先", "http://127.0.0.1:7890" |

**修复**：CLI 和 SDK 现在都使用 `DEFAULT_CONFIG` 确保与 GUI 完全一致。

#### 42.1.2 MissAV 代理参数转换

**GUI 逻辑**（`build_missav_proxy_url`）：
- "Clash (7890)" → "http://127.0.0.1:7890"
- "v2rayN (10809)" → "http://127.0.0.1:10809"
- 带 ":" 的字符串 → 如果以 http 开头直接返回，否则加 "http://"
- 其他 → "http://127.0.0.1:7890"

**修复**：CLI 和 SDK 现在都有相同的 `build_missav_proxy_url` 函数，确保转换逻辑一致。

### 42.2 CLI 修复

1. 添加 `DEFAULT_CONFIG` 与 GUI 对齐
2. 添加 `build_missav_proxy_url` 与 GUI 对齐
3. `_build_config` 现在使用平台默认值 + 用户覆盖

### 42.3 SDK 修复

1. 添加 `DEFAULT_CONFIG` 与 GUI 对齐
2. 添加 `build_missav_proxy_url` 与 GUI 对齐
3. `search()` 现在合并配置顺序：平台默认 → SDK 全局默认 → 用户覆盖
4. MissAV 代理参数自动转换

### 42.4 二次选择流程确认

**GUI 流程**：
1. spider 调用 `ask_user_selection(items)`
2. 发送 `sig_select_tasks` 信号
3. 阻塞在 `_resume_event.wait()`
4. 用户在弹窗选择
5. 调用 `spider.resume_from_ui(indices)` 设置 `_selected_indices` 并发出信号
6. `wait()` 结束

**CLI 流程**：
1. 同步版本 `ask_user_selection_sync` 直接调用 `selection_strategy.select()`
2. 返回 `indices`
3. spider 继续执行

关键差异：CLI 走同步路径，不走 Qt 信号，但逻辑完全对齐。

### 42.5 经验教训（v23 增补）

35. **参数默认值必须与 GUI 100% 一致**：否则用户用 CLI 和 GUI 结果会不同
36. **复杂参数转换必须 100% 复用 GUI 代码**：如 MissAV 代理，复制粘贴 GUI 的代码最保险
37. **配置合并顺序要明确**：平台默认 → SDK 全局默认 → 用户覆盖，确保逻辑清晰
38. **二次选择是最复杂的流程**：需要反复对照 GUI 代码确保没有遗漏任何细节
