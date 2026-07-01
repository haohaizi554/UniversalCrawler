# 重构提取记录（2026-06-30）

## 已完成提取

- 平台设置表格列宽策略从 `SettingsPage` 提取到 `app/ui/viewmodels/settings_platform_layout.py`。
- `SettingsPage._platform_col_widths()` 保留薄兼容包装，避免旧调用和测试同时失效。
- 设置快照组装提取到 `app/services/frontend_settings_adapter.py`，让 `FrontendStateService` 专注状态、事件和动作。
- 视频行格式化和分类提取到 `app/services/frontend_video_adapter.py`，覆盖队列、正在下载、已完成、失败分类和失败建议。
- 日志过滤、时间解析、搜索文本、平台匹配、分类计数和排序提取到 `app/ui/viewmodels/log_filtering.py`。
- 调试日志解析、级别归一、平台推断、摘录索引和失败任务诊断提取到 `app/services/frontend_log_adapter.py`。

## 为什么值得保留

- 列宽是纯布局策略，不需要 QWidget，可直接单测。
- 设置快照是配置到前端的稳定契约，离开 GUI 测试更便宜、更安全。
- 视频行适配是 `VideoItem -> frontend row` 的边界，不能让状态服务继续吞掉格式化规则。
- 日志分类和过滤是产品规则，不是控件行为，应作为纯函数测试。
- `FrontendStateService` 保留副作用：元数据探测、事件发布、配置写入、运行时应用和下载管理器交互。

## 工程规则

- 超过 1000 行的文件，优先提取纯策略、格式化器、分类器、分页和数据适配器。
- 页面类只做编排：接收快照、处理用户事件、组合控件。
- 服务类负责副作用：读写配置、发布事件、调用 manager、调度后台工作。
- 每次提取保留薄兼容包装，等测试和调用迁移后再清理。
- 自动化写文件后必须验证 UTF-8，终端乱码不能污染源码或文档。

## 边界经验

- 好的提取不是把大文件所有行都搬走，而是找到稳定输入和稳定输出之间的纯函数边界。
- 元数据探测、文件系统 stat、活动事件补全和日志摘录定位属于服务编排。
- 行构造、分类、标签和前端字典结构属于适配器。
- 不要用 `LogCenterPage.__new__()` 测页面方法，它绕过 Qt 初始化，会把普通规则测试变成脆弱的 QWidget 生命周期测试。


## 2026-07-01 HLS Proxy Extraction

- ? `app/core/downloaders/m3u8.py` ???? HLS ????????? `app/core/downloaders/hls_proxy.py`?
- `m3u8.py` ???? `from .hls_proxy import _LocalHlsProxy`?????????????????????
- ??????? `_ThreadingHlsProxyServer`?`_HlsProxyHandler`?`_LocalHlsProxy`?????????????????? MissAV fallback ?????????

## HLS Proxy Boundary Lesson

- ?????????????????????????? HTTP ????? URL token??????????????????
- ???????????????????????????? N_m3u8DL-RE????? fallback ??????
- ????????????????????????????? import ??????


## 2026-07-01 N_m3u8DL-RE Progress Parser Extraction

- ? `_Nm3u8OutputProgress` ? `app/core/downloaders/m3u8.py` ??? `app/core/downloaders/nm3u8_progress.py`?
- `m3u8.py` ?????????????????? `_Nm3u8OutputProgress`?
- ?????? monkeypatch ??????????????????????? import ???

## Progress Parser Boundary Lesson

- ???????????????????????????????????
- ???????? `feed()` ? `snapshot()`????????????????????????????
- ????????????? ffmpeg?yt-dlp ??? CLI ???????????????????


## 2026-07-01 Log Center Stylesheet Extraction

- ??????? QSS ? `app/ui/styles/themes.py` ??? `app/ui/styles/log_center_styles.py`?
- ????????????????? QSS???? Qt?????????? import `themes.py`?
- `themes.py` ?? `generate_log_center_stylesheet(is_dark=False)` ????????? `generate_stylesheet()` ??????????

## Stylesheet Boundary Lesson

- ????????????????palette???????????? QSS ?????????????
- ?????????????????? import ?????????????????????
- ??????????????????????????????????????????


## 2026-07-01 HLS Pure Helper Consolidation

- ? playlist ???playlist URL ????? bytes ????????????????? URI ???? HLS ???? `app/core/downloaders/hls_proxy.py`?
- `N_m3u8DL_RE_Downloader` ?????? wrapper?????????????????
- `_LocalHlsProxy` ???? downloader ???????????? downloader ??????????

## Helper Migration Lesson

- ?????????????????????????????????????????
- ????????? wrapper ??????????????????????????
- ??????????????????? `py_compile` ??????????????????


## 2026-07-01 Settings Catalog Extraction

`app/ui/pages/settings_page.py` previously mixed page layout with static settings catalog data: group icons, option lists, descriptions, hints, and fallback labels. Those values now live in `app/ui/viewmodels/settings_catalog.py`, while `SettingsPage` imports the existing names for compatibility.

### Lesson

Static UI catalog data is a better viewmodel boundary than page code. It keeps the page focused on rendering and interactions, and gives GUI/WebUI adapters a stable place to share labels and option contracts without scraping widget code.

## 2026-07-01 Settings Path Picker Extraction

The download directory row has been extracted into `app/ui/components/settings_path_picker.py`. The component owns the editable path field, focus state, folder icon button, and left-aligned path display. `SettingsPage` keeps the directory dialog and setting emission as thin compatibility wrappers.

### Lesson

Reusable widgets should own local UI behavior, but not business actions. Keeping the file dialog and setting mutation in the page preserves testability, avoids hidden service dependencies in the component, and still removes repeated widget construction code from the long page file.


## 2026-07-01 Log Detail Payload Extraction

`app/ui/pages/log_center_page.py` no longer owns Trace ID extraction, detail payload normalization, or exported log-detail payload construction. Those pure functions now live in `app/ui/viewmodels/log_detail_payloads.py`, with page methods kept as small compatibility wrappers for selection, clipboard, and file-dialog behavior.

### Lesson

A log page should not decide how diagnostic payloads are normalized. Keeping payload shaping in a viewmodel makes copy/export behavior reusable by GUI inspectors, failed-task panels, and WebUI without pulling Qt widgets or dialogs into data logic. To avoid circular imports with log classification, the page passes the already-derived status code into the payload helpers.

## 2026-07-01 Metadata Probe Queue Extraction

`FrontendStateService` no longer owns the timer, generation, pending-map, and batch-drain mechanics for completed media metadata probes. That scheduling responsibility now lives in `app/services/metadata_probe_queue.py`, while `FrontendStateService` keeps only the domain callback that retries a probe and writes metadata back to completed items.

### Lesson

Background probe fanout is infrastructure, not frontend state shaping. Extracting it gives the project a reusable debounced batch queue for other slow background enrichments, and keeps the facade focused on snapshot/delta semantics. The old private service methods remain as compatibility wrappers so the migration is incremental instead of a large disruptive rewrite.

## 2026-07-01 Completed Metadata Rules Extraction

Completed-media metadata rules now live in `app/services/completed_metadata_rules.py`: payload normalization, missing-value backfill policy, real-resolution checks, duration validity, and local-path equivalence. `FrontendStateService` keeps compatibility wrappers, but no longer owns the pure rules.

### Lesson

Metadata enrichment has two separate concerns: orchestration and rules. The state facade should decide when to probe and emit deltas; a rule module should decide what values are trustworthy and when they can overwrite existing metadata. This makes the same behavior reusable by GUI playback callbacks, WebUI loadedmetadata events, background probes, and future toolbox metadata inspection.

## 2026-07-01 Bilibili Input Router Extraction

Bilibili input classification now lives in `app/spiders/bilibili/input_router.py`: BV, av, UID labels, UP homepages, search URLs, collection-style links, short-link text extraction, and collection BV fallback URL construction. `BilibiliSpider` keeps the old private method names as thin wrappers because tests and existing crawler orchestration still call them directly.

### Lesson

Crawler spiders should orchestrate browser/API/download pipelines, not own every pure route rule. Moving route classification into a small module makes the repeated Bilibili edge cases testable without spinning up the spider, while wrapper methods keep the migration reversible and low-risk.

## 2026-07-01 Frontend Settings Adapter Wiring

`FrontendStateService.settings_snapshot()` now delegates to `app/services/frontend_settings_adapter.py`. The old private service methods for platform counts, proxy mode, timeout, auth snapshot, and count labels remain as compatibility wrappers, but the actual configuration contract is maintained in one adapter module.

### Lesson

Extraction is incomplete until the caller uses the extracted module. Keeping duplicate settings-contract builders in both the service and adapter invites drift: one side can preserve `max`, default units, proxy custom values, or log limits while the other silently regresses. A facade should ask for a settings snapshot, not rebuild the settings catalog itself.

## 2026-07-01 Frontend Log Cache Extraction

The UI log file cache now lives in `app/services/frontend_log_cache.py`. `FrontendStateService` still exposes the old private cache methods, but cache fill, resize, invalidation, and tail merging are owned by `FrontendLogCache`.

### Lesson

Log display limits are a performance policy, not generic frontend state. Small-to-large limit changes should expand the in-memory allowance without immediately backfilling from disk; large-to-small changes should drop cached rows immediately. Keeping this policy in a focused cache object makes it testable and avoids accidental UI freezes when log counts exceed thousands.

## 2026-07-01 Toolbox Catalog Extraction

The toolbox catalog now lives in `app/services/frontend_toolbox_adapter.py`. The state service re-exports `TOOLBOX_DEFINITIONS` for compatibility and delegates item snapshots, recent items, and tool-id validation to the adapter.

### Lesson

Static product catalog data is not state-service behavior. Tool titles, examples, summaries, icons, and valid IDs should have one owner so GUI pages, WebUI, and actions do not drift. Re-exporting the old constant keeps this kind of extraction incremental.

## 2026-07-01 Metadata Retry Tracker Extraction

Empty completed-media metadata probe retries now live in `app/services/metadata_retry_tracker.py`. The tracker owns retry timers, duplicate suppression, empty-result attempt counts, failure-key clearing, and retry-result events. `FrontendStateService` still decides when a completed item needs metadata and keeps compatibility wrappers for existing private methods.

### Lesson

Retry timers are lifecycle infrastructure, not snapshot-building logic. Keeping timer maps and failure counters inside the frontend facade made metadata probing harder to reason about and harder to reuse. A focused tracker gives the project one place to test bounded retry behavior while keeping the state service centered on item lookup, metadata writeback, and frontend delta emission.

## 2026-07-01 Web Custom Select Component Extraction

The WebUI custom select implementation now lives in `app/web/static/custom_select.js`. `app.js` keeps thin compatibility wrappers such as `enhanceSelects()` and `syncCustomSelectForSelect()`, but the real component owns select enhancement, menu rendering, keyboard handling, outside-click close behavior, disabled state, and helper configuration for translation and escaping.

### Lesson

Global application scripts should not own reusable widgets. The custom select is used by top-bar controls, settings rows, platform tables, and pagination controls, so it deserves its own component boundary. Loading it before `app.js` keeps the current non-module browser model intact, while wrapper functions allow incremental migration without rewriting every call site at once.

## 2026-07-01 Web I18n Component Extraction

The WebUI fallback translation catalog and translation helpers now live in `app/web/static/i18n.js`. `app.js` keeps compatibility wrappers for `t()`, `translateUiText()`, `optionLabel()`, and `applyStaticLanguage()`, while the component owns catalog loading, language lookup, visible-text translation, and static label updates.

### Lesson

Large translation catalogs are shared UI infrastructure, not page orchestration. They should load before widgets and the main application script, then expose a narrow helper API. When moving JavaScript files that contain Chinese text, use UTF-8 aware tooling end to end; a shell that decodes UTF-8 as the system code page can turn valid source into mojibake and even break string literals.

## 2026-07-01 Active Download Event Adapter Extraction

Current-download event enrichment now lives in `app/services/frontend_video_adapter.py`. The state service still exposes private compatibility methods, but the rules for cleaning existing events, filling missing timestamps, deriving progress/speed/write/merge messages, and capping the timeline at six rows are owned by the video adapter.

### Lesson

Frontend state services should assemble sections and emit deltas; they should not own every display rule for each row type. Active-download event derivation is part of the active row contract and belongs next to `active_item()`, where it can be tested without app state, controllers, Qt, WebSocket, or the download manager.

## 2026-07-01 Frontend Status Adapter Extraction

Status-bar speed parsing, transfer-speed formatting, active-download speed aggregation, and app-status payload assembly now live in `app/services/frontend_status_adapter.py`. `FrontendStateService` still decides whether the crawler/download manager is running and supplies bucket counts, but the payload rules are shared adapter logic.

### Lesson

Bottom status bars are cross-frontend contracts. Formatting `2.0 MB/s`, deriving idle/error/running indicators, and aggregating active download speeds should not be embedded in a state facade. Keeping those rules in a small adapter lets GUI, WebUI, and tests agree on the same status contract without pulling in controller or download-manager dependencies.

## 2026-07-01 Frontend File Action Extraction

Local file actions now live in `app/services/frontend_file_actions.py`: truncating the latest debug log, exporting the debug log, opening a file or directory with the system, and resolving the current executable path. `FrontendStateService` keeps compatibility wrappers so existing callers and tests can still patch the old private methods.

### Lesson

Opening files and copying logs are operating-system boundary actions, not frontend snapshot state. Keeping them behind a small adapter makes the state service easier to read and gives tests a direct place to verify path handling without invoking GUI pages, controllers, or platform-specific shell commands.

## 2026-07-01 Web Media Display Component Extraction

The WebUI media display helpers now live in `app/web/static/media_display.js`. `app.js` keeps thin wrappers for active speed trends, active event timelines, metadata placeholder text, and path basename/dirname splitting. The installer source checks now include all split Web static scripts so packaged builds cannot accidentally ship `app.js` without its companion components.

### Lesson

Charts, timeline snippets, and path display helpers are reusable presentation components, not application orchestration. Extracting them keeps the main WebUI script focused on state flow and page routing. Whenever a browser script is split out, update HTML loading order and packaging validation in the same change; otherwise development may pass while packaged installs miss the new asset.

## 2026-07-01 Web Log Display Component Extraction

The WebUI log display rules now live in `app/web/static/log_display.js`: stable log row IDs, category detection, search text construction, time-range filtering, filter matching, and visible-row budgeting. `app.js` still owns DOM rendering, selected row state, and log actions.

### Lesson

Log center performance depends on a clean split between data policy and rendering. Filtering thousands of rows, enforcing a visible-row budget, and deriving categories are reusable rules that should be testable without touching DOM nodes or WebSocket state. Keeping those rules in a component also makes future virtual scrolling or worker-backed filtering easier to add without rewriting page orchestration.

## 2026-07-01 Web Settings Render Component Extraction

The WebUI settings-center HTML generation now lives in `app/web/static/settings_render.js`. `app.js` keeps compatibility wrappers and continues to own behavior actions such as updating settings, custom proxy commits, and frontend action dispatch, while the component renders basic, download, platform, playback, log, and appearance setting rows.

### Lesson

Settings pages mix a lot of repeated presentation rules with a small number of real actions. Splitting pure render helpers from action dispatch keeps the main WebUI script focused on state flow, while the extracted renderer can be loaded and tested as a static component. Browser-script extraction should always update HTML load order, installer source checks, and static contract tests in the same step.
## 2026-07-01 Web Task Render Component Extraction
The WebUI queue, active, completed, and failed task row/detail HTML helpers now live in `app/web/static/task_render.js`. The main `app.js` keeps page orchestration, pagination, selection, and state updates, then delegates repeated task presentation primitives to the shared renderer.

### Lesson
Task pages share the same concepts: platform badges, progress bars, operation buttons, path wrapping, key-value rows, and failure diagnostics. Centralizing those primitives avoids four pages quietly drifting apart and reduces the size of the WebUI controller without forcing unrelated page state into the renderer.
## 2026-07-01 Web Playback State Extraction
The WebUI playback settings, playback-position key generation, stale-position cleanup, image detection, duration formatting, and metadata display checks now live in `app/web/static/playback_state.js`. `app.js` keeps the DOM-facing playback controls and delegates reusable policy decisions to this pure helper module.

### Lesson
Playback behavior mixes persistent policy and live DOM control. Splitting the pure state/policy layer first gives the project a stable seam for tests and future reuse without risking a large player-controller move in one step.
## 2026-07-01 Web Platform Limit Strategy Extraction
The WebUI platform count unit rules now live in `app/web/static/platform_limits.js`: videos, notes, pages, default values, max, and recommended option labels are generated from one small policy module. The top bar and settings rendering can both delegate to the same vocabulary instead of repeating unit-specific label rules.

### Lesson
Small display policies become correctness bugs when they are duplicated across top-level controls and settings pages. Extracting the unit strategy keeps platform limits consistent while leaving page rendering and backend persistence in their own layers.

## Download Options Adapter Extraction

- Keep frontend download option semantics in one adapter layer: snapshot building, payload normalization, manager concurrency reconciliation, and persistence now live in `frontend_settings_adapter`.
- Leave `FrontendStateService` responsible for orchestration only: manager lookup, runtime setting application, cache invalidation, and frontend event publication.
- Direct adapter tests are valuable here because GUI, WebUI, settings center, and active-page queue controls all depend on the same normalized download options contract.
## Log Filter Input Component Extraction

- Keep theme-aware focus styling with the input component instead of embedding it in `log_center_page.py`.
- The log center page should compose filter controls and delegate focus-border refresh to `log_filter_input`, which makes the same behavior reusable for future log/search filter surfaces.
- Contract coverage should instantiate the page and verify the actual focused widget style, not only static stylesheet text.
## Frontend Mock Snapshot Extraction

- Keep large demo/mock state out of `FrontendStateService`; the real service should own transport and state orchestration, not fixture construction.
- Preserve `FrontendStateService.mock_snapshot()` as a compatibility wrapper while moving fixture data into `frontend_mock_snapshot`.
- Put shared page definitions in `frontend_page_definitions` so production snapshots and mock snapshots cannot drift.
## Settings Platform Controls Extraction

- Keep the settings page responsible for page flow and group rendering; move reusable platform count, timeout, and proxy control construction into `settings_platform_controls`.
- Preserve thin `SettingsPage` wrapper methods when existing tests or callers rely on private helper names, then migrate internals behind the wrapper.
- Extract the control cluster first instead of the entire platform table: this reduces risk while moving the most stateful UI logic out of the long page class.

## Log Inspector Sections Extraction

- Keep `LogCenterPage` responsible for filter state, pagination, selected log state, and copy/export actions; move only the right-side inspector widget construction into `log_inspector_sections`.
- Return explicit `LogInspectorRefs` from the component so the page can keep its existing render/update methods without hidden mutation or brittle child lookup.
- Style hooks such as message wrapping and theme refresh stay in the page for now because they depend on the live page theme and existing resize behavior; extracting construction first lowers risk and leaves a clear next boundary.

### Lesson

A reusable Qt component should not silently reach back into its owner. For incremental refactors, have the component build widgets and return typed references, then let the page decide how those widgets connect to state and actions. This keeps the extraction reversible and avoids mixing UI construction with log-center behavior.

## Log Center Controls Extraction

- Move the log action bar and table footer construction into `log_center_controls`, while keeping filtering, action dispatch, pagination state, and selected-log behavior inside `LogCenterPage`.
- Return explicit refs for `copy_trace_button`, footer stats, page indicator, page-size combo, and page buttons so existing page methods keep a stable update surface without searching the widget tree.
- Keep combo sizing and popup polish with the component because those are control-construction details, not log-center business state.

### Lesson

Repeated Qt control clusters should be extracted at the construction boundary first. The page should own behavior and state transitions, while the component owns object names, sizes, labels, and signal wiring into supplied callbacks. This keeps large-page refactors incremental and avoids turning a UI helper into a second controller.
