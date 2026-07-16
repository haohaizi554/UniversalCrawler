"""WebUI browser cases owned by the localization and logs responsibility."""

from __future__ import annotations

class LocalizationCases:
    def test_09aa_runtime_log_pipeline_continues_after_structured_source_localization(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const samples = [
                ["zh-CN", "MainWindow · fetch video detail"],
                ["zh-TW", "BiliAPI · fetch video detail"],
                ["en-US", "WebController · Web 端用户请求停止爬虫任务"],
                ["zh-CN", "WebController · Web 端Crawl task finished"],
                ["zh-CN", "Download worker did not stop before file deletion timeout"],
                ["zh-CN", "select_tasks relay lag=12.5ms items=42"],
                ["en-US", "select_tasks 轉發延遲=12.5 毫秒，項目數=42"]
              ];
              return samples.map(([language, value]) => {
                document.documentElement.dataset.language = language;
                return window.UcpLogI18n.translateRuntimeLogText(value);
              });
            }
            """
        )

        self.assertEqual(
            result,
            [
                "主窗口 · 获取视频详情",
                "Bilibili 介面 · 取得影片詳情",
                "WebController · Web user requested to stop the crawl task",
                "Web 控制器 · Web 端爬虫任务结束",
                "文件删除等待超时前下载线程未停止",
                "select_tasks 转发延迟=12.5 毫秒，项目数=42",
                "select_tasks relay lag=12.5ms items=42",
            ],
        )

    def test_09b_language_switch_translates_runtime_ui_messages(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = "en-US";
              applyStaticLanguage();
              document.getElementById("searchInput").value = "";
              startCrawl();
              const originalFetch = window.fetch;
              window.fetch = () => Promise.reject(new Error("boom"));
              await window.UcpDialogController.loadDirectory("C:/missing");
              window.fetch = originalFetch;
              const lastLog = frontendState.log_items[frontendState.log_items.length - 1] || {};
              return {
                startLabel: document.getElementById("startBtn").textContent.trim(),
                logMessage: lastLog.message,
                dirStatus: document.getElementById("dirStatus").textContent
              };
            }
            """
        )

        self.assertEqual(result["startLabel"], "Start")
        self.assertEqual(result["logMessage"], "Enter a profile, shared, or collection link")
        self.assertEqual(result["dirStatus"], "Failed to load folder: boom")

    def test_09f_language_switch_translates_settings_logs_active_and_platforms(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.settings_snapshot = {
                "基础设置": {
                  download_directory: "D:\\\\Downloads",
                  filename_template: "默认",
                  open_after_download: false,
                  default_open_mode: "内置播放器",
                  _options: {
                    filename_template: [{ value: "默认", label: "默认" }],
                    default_open_mode: [{ value: "内置播放器", label: "内置播放器" }, { value: "打开所在目录", label: "打开所在目录" }]
                  }
                },
                "下载设置": {
                  max_concurrent: 3,
                  image_respects_concurrency: true,
                  request_timeout: 60,
                  max_retries: 3,
                  resume_enabled: true,
                  speed_limit_kb: 0,
                  video_only: false,
                  _options: {
                    max_concurrent: [{ value: "3", label: "3（推荐）" }],
                    request_timeout: [{ value: "60", label: "60 秒（推荐）" }],
                    max_retries: [{ value: "3", label: "3（推荐）" }],
                    speed_limit_kb: [{ value: "0", label: "无限制" }]
                  }
                },
                "平台设置": [
                  { id: "douyin", name: "抖音", auth_status: "已认证", default_count: 50, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "50", label: "50 个视频" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理", "直连"], proxy_editable: false },
                  { id: "missav", name: "MissAV", auth_status: "未认证", default_count: 20, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "20", label: "20 个视频（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "自定义", proxy_config_key: "proxy", proxy_editable: true, proxy_custom_allowed: true, proxy_custom_active: true, proxy_custom_value: "http://127.0.0.1:7890", proxy_options: ["系统代理", "直连", "自定义"] },
                  { id: "xiaohongshu", name: "小红书", auth_status: "已认证", default_count: 20, count_unit: "notes", count_config_key: "max_notes", count_editable: true, count_options: [{ value: "20", label: "20 篇笔记（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false }
                ],
                "播放设置": {
                  default_player: "内置播放器",
                  remember_position: true,
                  autoplay_next: true,
                  manual_image_switch: true,
                  _options: { default_player: [{ value: "内置播放器", label: "内置播放器" }] }
                },
                "日志设置": {
                  retention_days: 1,
                  ui_log_max_display_count: 300,
                  auto_copy_trace_on_error: true,
                  _options: {
                    retention_days: [{ value: "1", label: "1 天（推荐）" }, { value: "3", label: "3 天" }, { value: "5", label: "5 天" }, { value: "7", label: "7 天" }],
                    ui_log_max_display_count: [{ value: "300", label: "300 条（推荐）" }]
                  }
                },
                "外观设置": { language: "en-US", theme: "light", accent: "red", scale: "100%", font_size: "medium" }
              };
              frontendState.settings_contract = {
                group_order: ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"],
                group_descriptions: {
                  "基础设置": "下载目录、文件命名和打开行为",
                  "下载设置": "并发、超时、重试和下载策略",
                  "平台设置": "认证状态、爬取数量和代理入口",
                  "播放设置": "播放器、断点续播和预览行为",
                  "日志设置": "保留策略、显示上限和错误追踪",
                  "外观设置": "语言、主题、界面缩放和字体"
                },
                group_hints: {
                  "基础设置": "路径支持粘贴和选择，命名规则使用预设模板，避免非法文件名。",
                  "下载设置": "并发越高不一定越快，建议根据网络和磁盘性能调整。",
                  "日志设置": "UI 显示数量只影响日志中心显示，不影响日志文件本身。"
                }
              };
              frontendState.download_options = { auto_retry: true, max_retries: 3, max_concurrent: 3 };
              frontendState.active_downloads = [];
              frontendState.log_items = [{
                id: "log-i18n-surface",
                time: "2026-07-05 09:55:36",
                level: "WARN",
                raw_level: "WARN",
                result_type: "warn",
                category: "performance",
                log_scope: "performance",
                event_stage: "performance",
                event_code: "FRONTEND_RENDER_SLOW",
                source: "MainWindow",
                source_display: "系统 · MainWindow",
                source_display_icon_file: "nav_settings.png",
                platform: "系统",
                trace_id: "",
                message_summary: "📂 正在扫描目录: D:\\\\Downloads",
                message: "📂 正在扫描目录: D:\\\\Downloads",
                detail: { description: "说明：应用开始初始化", type: "预警", scope: "性能", stage: "性能", platform: "系统", source: "MainWindow" },
                stack: ""
              }];
              platforms = [
                { id: "missav", name: "MissAV" },
                { id: "douyin", name: "抖音" },
                { id: "xiaohongshu", name: "小红书" },
                { id: "kuaishou", name: "快手" },
                { id: "bilibili", name: "Bilibili" }
              ];
              document.documentElement.dataset.language = "en-US";
              renderSignatures = {};
              applyStaticLanguage();
              renderPlatforms();
              const sourceOptions = Array.from(document.querySelectorAll("#sourceSelect option")).map(option => option.textContent.trim());

              currentPage = "settings";
              document.querySelectorAll(".page").forEach(page => page.classList.remove("active"));
              const settingsTexts = {};
              for (const group of ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置"]) {
                window.UcpSettingsController.switchGroup(group);
                window.UcpSettingsController.render(true);
                settingsTexts[group] = document.getElementById("page-settings").textContent;
              }

              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));
              renderLogs();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: "All logs 1" });
              const logsText = document.getElementById("page-logs").textContent;
              const logPlatformLabel = document.querySelector("#logPlatformFilter").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();

              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              const activeText = document.getElementById("page-active").textContent;
              const retryLabel = document.querySelector("#activeMaxRetries").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();

              frontendState.settings_snapshot["外观设置"].language = "zh-CN";
              frontendState.settings_contract.group_descriptions["平台设置"] = "Auth status, crawl quantity, and proxy entry";
              frontendState.settings_snapshot["平台设置"][0].count_options = [{ value: "50", label: "50 videos" }];
              frontendState.settings_snapshot["平台设置"][0].timeout_options = [{ value: "60", label: "60 sec (Recommended)" }];
              frontendState.settings_snapshot["平台设置"][0].proxy_options = [{ value: "系统代理", label: "System proxy" }];
              frontendState.settings_snapshot["日志设置"]._options.retention_days = [{ value: "1", label: "1 day (Recommended)" }];
              frontendState.log_items[0].source_display = "System · MainWindow";
              frontendState.log_items[0].platform = "System";
              frontendState.log_items[0].message_summary = "📂 Scanning folder: D:\\\\Downloads";
              frontendState.log_items[0].message = "Frontend render exceeded the interactive budget; refresh cadence was relaxed";
              frontendState.log_items[0].detail = { description: "Frontend render exceeded the interactive budget; refresh cadence was relaxed", type: "Warning", scope: "Performance", stage: "Performance", platform: "System", source: "MainWindow" };
              document.documentElement.dataset.language = "zh-CN";
              applyStaticLanguage();
              renderPlatforms();
              const zhSourceOptions = Array.from(document.querySelectorAll("#sourceSelect option")).map(option => option.textContent.trim());

              currentPage = "settings";
              document.querySelectorAll(".page").forEach(page => page.classList.remove("active"));
              window.UcpSettingsController.switchGroup("平台设置");
              window.UcpSettingsController.render(true);
              const zhSettingsText = document.getElementById("page-settings").textContent;

              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: "前端渲染超过交互预算" });
              const zhLogsText = document.getElementById("page-logs").textContent;

              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              const zhActiveText = document.getElementById("page-active").textContent;
              const zhRetryLabel = document.querySelector("#activeMaxRetries").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();
              return { sourceOptions, settingsTexts, logsText, logPlatformLabel, activeText, retryLabel, zhSourceOptions, zhSettingsText, zhLogsText, zhActiveText, zhRetryLabel };
            }
            """
        )

        joined_settings = "\n".join(result["settingsTexts"].values())
        for expected in (
            "Download folder, filename rules, and open behavior",
            "Concurrency, timeout, retry, and download policy",
            "Player, resume playback, and preview behavior",
            "Retention policy, display limits, and error tracing",
            "Maximum simultaneous downloads",
            "Control the image fast lane",
            "1 day (Recommended)",
            "Custom",
            "Timeout",
            "Douyin",
            "Xiaohongshu",
        ):
            self.assertIn(expected, joined_settings)
        for unexpected in ("下载目录、文件命名", "播放器、断点续播", "保留策略、显示上限", "最大同时下载数", "自定义", "超时"):
            self.assertNotIn(unexpected, joined_settings)

        self.assertIn("Douyin", result["sourceOptions"])
        self.assertIn("Xiaohongshu", result["sourceOptions"])
        self.assertIn("Kuaishou", result["sourceOptions"])
        self.assertEqual(result["logPlatformLabel"], "All")
        self.assertIn("All logs 1", result["logsText"])
        self.assertIn("System · Main window", result["logsText"])
        self.assertIn("Scanning folder: D:\\Downloads", result["logsText"])
        self.assertIn("Warning", result["logsText"])
        self.assertIn("Performance", result["logsText"])
        self.assertIn("Total 1 / matched 1 / showing 1", result["logsText"])
        for unexpected in ("全部日志", "系统 · MainWindow", "正在扫描目录", "预警", "性能", "共 1 条"):
            self.assertNotIn(unexpected, result["logsText"])
        self.assertIn("Queue controls", result["activeText"])
        self.assertIn("Auto retry failures", result["activeText"])
        self.assertIn("Current task events", result["activeText"])
        self.assertIn("No events", result["activeText"])
        self.assertIn("Running: 0 tasks", result["activeText"])
        self.assertEqual(result["retryLabel"], "3 times")
        self.assertIn("抖音", result["zhSourceOptions"])
        self.assertIn("小红书", result["zhSourceOptions"])
        self.assertIn("认证状态、爬取数量和代理入口", result["zhSettingsText"])
        self.assertIn("50 个视频", result["zhSettingsText"])
        self.assertIn("60 秒（推荐）", result["zhSettingsText"])
        self.assertIn("系统代理", result["zhSettingsText"])
        self.assertIn("全部日志 1", result["zhLogsText"])
        self.assertIn("系统 · 主窗口", result["zhLogsText"])
        self.assertIn("正在扫描目录：D:\\Downloads", result["zhLogsText"])
        self.assertIn("前端渲染超过交互预算", result["zhLogsText"])
        self.assertIn("预警", result["zhLogsText"])
        self.assertIn("性能", result["zhLogsText"])
        self.assertIn("共 1 条 / 匹配 1 条 / 当前显示 1 条", result["zhLogsText"])
        self.assertIn("队列控制", result["zhActiveText"])
        self.assertIn("暂无事件", result["zhActiveText"])
        self.assertIn("当前运行：0 个任务", result["zhActiveText"])
        self.assertEqual(result["zhRetryLabel"], "3次")
        for unexpected in ("Douyin", "Xiaohongshu", "Auth status", "50 videos", "System proxy"):
            self.assertNotIn(unexpected, result["zhSettingsText"] + "\n".join(result["zhSourceOptions"]))
        for unexpected in ("All logs", "System · MainWindow", "Scanning folder", "Warning", "Performance", "Total 1 / matched 1 / showing 1"):
            self.assertNotIn(unexpected, result["zhLogsText"])
        for unexpected in ("Queue controls", "No events", "Running: 0 tasks"):
            self.assertNotIn(unexpected, result["zhActiveText"])

    def test_09g_current_page_language_controls_runtime_dialogs_and_dynamic_text(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "zh-CN",
                theme: "light",
                accent: "purple",
                scale: "100%",
                font_size: "medium"
              };
              document.documentElement.dataset.language = "en-US";
              frontendState.active_downloads = [];
              frontendState.download_options = { auto_retry: true, max_retries: 3, max_concurrent: 3 };
              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              showFileAssociationModal();
              const modalText = document.getElementById("fileAssociationModal").textContent;
              const activeText = document.getElementById("page-active").textContent;
              const languageBeforeApply = currentLanguage();
              const recLabel = optionLabel("20 videos (Rec.)");
              const runningLabel = translateUiText("当前运行：0 个任务");
              applyAppearance(frontendState.settings_snapshot["外观设置"]);
              const languageAfterApply = currentLanguage();
              cancelFileAssociationModal();
              return { languageBeforeApply, languageAfterApply, modalText, activeText, recLabel, runningLabel };
            }
            """
        )

        self.assertEqual(result["languageBeforeApply"], "en-US")
        self.assertEqual(result["languageAfterApply"], "zh-CN")
        self.assertIn("Current task events", result["activeText"])
        self.assertIn("No events", result["activeText"])
        self.assertIn("Running: 0 tasks", result["activeText"])
        self.assertIn("Bind default app", result["modalText"])
        self.assertIn("Video resources", result["modalText"])
        self.assertIn("Cancel", result["modalText"])
        self.assertIn("Bind", result["modalText"])
        self.assertEqual(result["recLabel"], "20 videos (Recommended)")
        self.assertEqual(result["runningLabel"], "Running: 0 tasks")
        for unexpected in ("当前任务事件", "暂无事件", "当前运行", "绑定默认打开方式", "取消"):
            self.assertNotIn(unexpected, result["activeText"] + result["modalText"])

    def test_09h_runtime_language_update_translates_dropdowns_logs_active_and_dialogs(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              window.__languageActions = [];
              window.frontendAction = (action, payload) => window.__languageActions.push({ action, payload });
              frontendAction = window.frontendAction;
              platforms = [
                { id: "douyin", name: "抖音" },
                { id: "xiaohongshu", name: "小红书" },
                { id: "kuaishou", name: "快手" },
                { id: "missav", name: "MissAV" },
                { id: "bilibili", name: "Bilibili" }
              ];
              frontendState.settings_snapshot = {
                "外观设置": {
                  language: "zh-CN",
                  theme: "light",
                  accent: "purple",
                  scale: "100%",
                  font_size: "medium",
                  _options: {
                    language: [
                      { value: "zh-CN", label: "简体中文（推荐）" },
                      { value: "en-US", label: "English" }
                    ],
                    accent: [{ value: "purple", label: "紫色" }],
                    scale: [{ value: "100%", label: "100%（推荐）" }],
                    font_size: [{ value: "medium", label: "中（推荐）" }],
                    theme: [{ value: "light", label: "浅色" }, { value: "dark", label: "深色" }]
                  }
                },
                "平台设置": [
                  { id: "douyin", name: "抖音", auth_status: "已认证", default_count: 50, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "50", label: "50 个视频" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false },
                  { id: "xiaohongshu", name: "小红书", auth_status: "已认证", default_count: 20, count_unit: "notes", count_config_key: "max_notes", count_editable: true, count_options: [{ value: "20", label: "20 篇笔记（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false },
                  { id: "kuaishou", name: "快手", auth_status: "已认证", default_count: 20, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "20", label: "20 个视频（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false },
                  { id: "missav", name: "MissAV", auth_status: "未认证", default_count: 20, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "20", label: "20 个视频（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "自定义", proxy_config_key: "proxy", proxy_editable: true, proxy_custom_allowed: true, proxy_custom_active: true, proxy_custom_value: "7890", proxy_options: ["系统代理", "直连", "自定义"] },
                  { id: "bilibili", name: "Bilibili", auth_status: "已认证", default_count: 1, count_unit: "pages", count_config_key: "max_pages", count_editable: true, count_options: [{ value: "1", label: "1 页（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false }
                ]
              };
              frontendState.log_items = [
                {
                  id: "log-runtime-language",
                  time: "2026-07-05 11:33:04",
                  level: "WARN",
                  type: "预警",
                  scope: "性能",
                  stage: "性能",
                  source: "系统 · MainWindow",
                  platform: "系统",
                  trace_id: "-",
                  message_summary: "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                  message: "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                  detail: {
                    description: "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                    type: "预警",
                    scope: "性能",
                    stage: "性能",
                    source: "MainWindow",
                    platform: "系统"
                  }
                },
                {
                  id: "log-bilibili-start",
                  time: "2026-07-05 11:33:03",
                  level: "INFO",
                  type: "过程",
                  scope: "采集",
                  stage: "启动",
                  source: "Bilibili · BilibiliSpider",
                  platform: "Bilibili",
                  trace_id: "bilibili_crawl_1",
                  message_summary: "启动 Bilibili 爬虫任务",
                  message: "启动 Bilibili 爬虫任务",
                  detail: { description: "启动 Bilibili 爬虫任务", source: "BilibiliSpider", platform: "Bilibili" }
                },
                {
                  id: "log-bilibili-confirm",
                  time: "2026-07-05 11:33:02",
                  level: "INFO",
                  type: "过程",
                  scope: "系统",
                  stage: "确认",
                  source: "系统 · GUI",
                  platform: "系统",
                  trace_id: "-",
                  message_summary: "用户确认了 45 个任务",
                  message: "用户确认了 45 个任务",
                  detail: { description: "用户确认了 45 个任务", source: "GUI", platform: "系统" }
                },
                {
                  id: "log-bilibili-finish",
                  time: "2026-07-05 11:33:01",
                  level: "INFO",
                  type: "成功",
                  scope: "下载",
                  stage: "完成",
                  source: "Bilibili · Downloader",
                  platform: "Bilibili",
                  trace_id: "bilibili_BV1",
                  message_summary: "下载任务完成",
                  message: "下载任务完成",
                  detail: { description: "下载任务完成", source: "Downloader", platform: "Bilibili" }
                }
              ];
              document.documentElement.dataset.language = "zh-CN";
              renderPlatforms();
              currentPage = "settings";
              window.UcpSettingsController.switchGroup("外观设置");
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "settings"));
              window.UcpSettingsController.render(true);
              updateSetting("appearance", "language", "en-US");

              const sourceOptions = Array.from(document.querySelectorAll("#sourceSelect option")).map(option => option.textContent.trim());
              window.UcpSettingsController.switchGroup("平台设置");
              window.UcpSettingsController.render(true);
              const settingsText = document.getElementById("page-settings").textContent;
              const customProxyPlaceholder = document.querySelector(".proxy-custom")?.getAttribute("placeholder") || "";

              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));
              renderLogs();
              await window.__waitForLogRender({
                rows: 4,
                total: 4,
                matched: 4,
                visible: 4,
                itemId: "log-bilibili-start",
                text: "Started Bilibili crawl task",
              });
              const logsText = document.getElementById("page-logs").textContent;
              const logPlatformButton = document.querySelector("#logPlatformFilter").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();
              const logPlatformOriginal = document.querySelector("#logPlatformFilter option[value='all']").dataset.originalLabel;

              frontendState.completed_items = [{
                id: "completed-pending",
                title: "pending metadata",
                filename: "pending.mp4",
                local_path: "D:/Downloads/pending.mp4",
                completed_at: "2026-07-05 11:32:00",
                completed_at_table: "11:32:00",
                duration: "检测中",
                resolution: "检测中",
                metadata_pending: true,
                size: "1 MB",
                format: "MP4"
              }];
              selected.completed = "completed-pending";
              currentPage = "completed";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "completed"));
              renderCompleted();
              await new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const text = document.getElementById("page-completed").textContent;
                  if (text.includes("Checking")) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error("completed page did not render localized pending metadata"));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });
              const completedText = document.getElementById("page-completed").textContent;

              frontendState.active_downloads = [{
                id: "active-language",
                title: "demo",
                platform: "Bilibili",
                platform_id: "bilibili",
                progress: 25,
                speed: "1.0 MB/s",
                remaining_time: "00:47",
                chunk_progress: { percent: 25, completed: 25, total: 100 },
                events: [
                  { time: "20:20:48", message: "任务进入 Bilibili 下载器" },
                  { time: "20:20:49", message: "音视频流下载中" },
                  { time: "20:20:50", message: "当前速度：1.0 MB/s，剩余：00:47" }
                ]
              }];
              frontendState.download_options = { auto_retry: true, max_retries: 3, max_concurrent: 3 };
              selected.active = "active-language";
              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              const activeText = document.getElementById("page-active").textContent;

              showFileAssociationModal();
              const modalText = document.getElementById("fileAssociationModal").textContent;
              cancelFileAssociationModal();

              return { sourceOptions, settingsText, customProxyPlaceholder, logsText, logPlatformButton, logPlatformOriginal, completedText, activeText, modalText };
            }
            """
        )

        for expected in ("Douyin", "Xiaohongshu", "Kuaishou"):
            self.assertIn(expected, result["sourceOptions"])
            self.assertIn(expected, result["settingsText"])
        self.assertIn("Custom", result["settingsText"])
        self.assertEqual(result["customProxyPlaceholder"], "Port")
        self.assertEqual(result["logPlatformButton"], "All")
        self.assertEqual(result["logPlatformOriginal"], "全部")
        self.assertIn("All logs", result["logsText"])
        self.assertIn("Warning", result["logsText"])
        self.assertIn("Performance", result["logsText"])
        self.assertIn("System", result["logsText"])
        self.assertIn("Started Bilibili crawl task", result["logsText"])
        self.assertIn("User confirmed 45 tasks", result["logsText"])
        self.assertIn("Download task completed", result["logsText"])
        self.assertIn("Checking", result["completedText"])
        self.assertIn("Current task events", result["activeText"])
        self.assertIn("Task entered Bilibili downloader", result["activeText"])
        self.assertIn("Audio/video stream downloading", result["activeText"])
        self.assertIn("Current speed: 1.0 MB/s, remaining: 00:47", result["activeText"])
        self.assertIn("Running: 1 tasks", result["activeText"])
        self.assertIn("Bind default app", result["modalText"])
        self.assertIn("Video resources", result["modalText"])
        for unexpected in (
            "抖音",
            "小红书",
            "快手",
            "自定义",
            "全部日志",
            "全部",
            "预警",
            "性能",
            "系统",
            "启动 Bilibili 爬虫任务",
            "用户确认了 45 个任务",
            "下载任务完成",
            "检测中",
            "暂无事件",
            "当前运行",
            "音视频流下载中",
            "绑定默认打开方式",
        ):
            self.assertNotIn(unexpected, "\n".join(result["sourceOptions"]) + result["settingsText"] + result["logsText"] + result["completedText"] + result["activeText"] + result["modalText"])

    def test_09j_completed_pending_metadata_fallback_respects_language(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const pendingText = String.fromCharCode(0x68c0, 0x6d4b, 0x4e2d);
              const originalMediaDisplay = window.UcpMediaDisplay;
              const taskRenderScript = await fetch("/static/task_render.js").then(response => response.text());
              document.documentElement.dataset.language = "en-US";
              const frame = document.createElement("iframe");
              document.body.appendChild(frame);
              try {
                window.UcpMediaDisplay = null;
                frame.contentWindow.eval(taskRenderScript);
                frame.contentWindow.UcpTaskRender.configure({ t: translateUiText });
                return {
                  direct: displayMetadataValue(pendingText, true),
                  emptyPending: displayMetadataValue("", true),
                  rowHtml: frame.contentWindow.UcpTaskRender.completedRow({
                    id: "pending-row",
                    title: "demo",
                    completed_at_table: "07-05 22:44",
                    duration: pendingText,
                    metadata_pending: true,
                    format: "MP4"
                  }, "")
                };
              } finally {
                window.UcpMediaDisplay = originalMediaDisplay;
                frame.remove();
              }
            }
            """
        )

        self.assertEqual(result["direct"], "Checking")
        self.assertEqual(result["emptyPending"], "Checking")
        self.assertIn("Checking", result["rowHtml"])
        self.assertNotIn("检测中", result["rowHtml"])
