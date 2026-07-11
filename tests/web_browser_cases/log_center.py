"""WebUI browser cases owned by the log center responsibility."""

from __future__ import annotations

class LogCenterCases:
    def test_09c_language_switch_keeps_log_filter_values_and_labels(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = "en-US";
              window.__setLogFiltersForTest({ level: "全部", time: "近 24 小时", platform: "全部" });
              applyStaticLanguage();
              switchPage("logs");
              renderLogs();
              const ids = ["logLevelFilter", "logTimeFilter", "logPlatformFilter"];
              return Object.fromEntries(ids.map(id => {
                const select = document.getElementById(id);
                const wrapper = select.closest(".custom-select");
                return [id, {
                  value: select.value,
                  label: wrapper.querySelector(".custom-select-label").textContent.trim()
                }];
              }));
            }
            """
        )

        self.assertEqual(result["logLevelFilter"], {"value": "all", "label": "All"})
        self.assertEqual(result["logTimeFilter"], {"value": "24h", "label": "Last 24 hours"})
        self.assertEqual(result["logPlatformFilter"], {"value": "all", "label": "All"})

    def test_09d_log_tabs_keep_gui_counts_after_language_refresh(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.log_items = [
                {
                  id: 'log-crawl',
                  time: new Date().toISOString(),
                  level: 'INFO',
                  source: 'Crawler',
                  trace_id: 'trace-crawl',
                  message_summary: '采集主页解析完成',
                  message: '采集主页解析完成'
                },
                {
                  id: 'log-download',
                  time: new Date().toISOString(),
                  level: 'INFO',
                  source: 'BilibiliDownloader',
                  platform: 'Bilibili',
                  trace_id: 'trace-download',
                  message_summary: '下载分片完成',
                  message: '下载分片完成'
                },
                {
                  id: 'log-error',
                  time: new Date().toISOString(),
                  level: 'ERROR',
                  source: 'GUI',
                  trace_id: 'trace-error',
                  message_summary: '任务异常退出',
                  message: '任务异常退出'
                }
              ];
              window.__setLogFiltersForTest({
                category: 'all',
                level: '全部',
                time: '近 30 分钟',
                platform: '全部',
                trace: '',
                keyword: ''
              });
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "zh-CN"
              };
              document.documentElement.dataset.language = 'zh-CN';
              switchPage('logs');
              renderLogs();
              await window.__waitForLogRender({ rows: 3, total: 3, matched: 3, visible: 3, text: '全部日志 3' });
              const zh = Array.from(document.querySelectorAll('#logTabs [data-log-tab]')).map(button => button.textContent.trim());
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = 'en-US';
              applyStaticLanguage();
              const en = Array.from(document.querySelectorAll('#logTabs [data-log-tab]')).map(button => button.textContent.trim());
              return {
                timeValue: document.getElementById('logTimeFilter').value,
                zh,
                en
              };
            }
            """
        )

        self.assertEqual(result["timeValue"], "30m")
        self.assertIn("全部日志 3", result["zh"])
        self.assertIn("错误日志 1", result["zh"])
        self.assertIn("All logs 3", result["en"])
        self.assertIn("Crawl logs 1", result["en"])
        self.assertIn("Download logs 1", result["en"])
        self.assertIn("System logs 0", result["en"])
        self.assertIn("Performance logs 0", result["en"])
        self.assertIn("Error logs 1", result["en"])

    def test_09da_log_query_uses_worker_even_for_small_batches(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest({ captureLogWorkers: true });
              frontendState.log_items = Array.from({ length: 12 }, (_, index) => ({
                id: `worker-log-${index}`,
                time: '2026-07-06 03:30:' + String(index % 60).padStart(2, '0'),
                level: index % 10 === 0 ? 'ERROR' : 'INFO',
                source: index % 2 === 0 ? 'BilibiliDownloader' : 'GUI',
                platform: index % 2 === 0 ? 'Bilibili' : '系统',
                trace_id: `trace-${index}`,
                message_summary: index % 2 === 0 ? '下载任务完成' : '系统状态刷新',
                message: index % 2 === 0 ? '下载任务完成' : '系统状态刷新'
              }));
              window.__setLogFiltersForTest({
                category: 'all',
                level: 'all',
                time: 'all',
                platform: 'all',
                trace: '',
                keyword: ''
              });
              switchPage('logs');
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 12, total: 12, matched: 12, visible: 12, timeoutMs: 6000 });
              window.__restoreLogWorkerForTest();
              const counts = (document.getElementById('logTotal').textContent.match(/\d+/g) || []).map(Number);
              return {
                workerCreated: window.__logWorkerUrls.includes('/static/log_query_worker.js?v=20260707-log-worker'),
                pending: false,
                rows: document.querySelectorAll('#logBody tr').length,
                total: counts[0] || 0,
                matched: counts[1] || 0,
                visible: counts[2] || 0,
                allTab: document.querySelector('#logTabs [data-log-tab="all"]')?.textContent.trim() || ''
              };
            }
            """
        )

        self.assertTrue(result["workerCreated"])
        self.assertFalse(result["pending"])
        self.assertEqual(result["rows"], 12)
        self.assertEqual(result["total"], 12)
        self.assertEqual(result["matched"], 12)
        self.assertEqual(result["visible"], 12)
        self.assertIn("12", result["allTab"])

    def test_09e_language_switch_translates_log_values_and_completed_detail_labels(self):
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
              frontendState.log_items = [{
                id: "log-i18n-a",
                time: "2026-07-05 09:04:22",
                level: "INFO",
                raw_level: "INFO",
                result_type: "info",
                category: "system",
                log_scope: "system",
                event_stage: "step",
                event_stage_display: "步骤",
                event_code: "GUI_日志缓存已刷新",
                source: "GUI",
                source_display: "系统 · GUI",
                source_display_icon_file: "nav_settings.png",
                platform: "系统",
                trace_id: "",
                message_summary: "日志缓存已刷新",
                message: "日志缓存已刷新",
                detail: { description: "日志缓存已刷新", platform: "系统", source: "GUI" },
                stack: ""
              }];
              frontendState.completed_items = [{
                id: "completed-i18n-a",
                title: "demo",
                filename: "demo.mp4",
                save_dir: "D:\\\\Downloads",
                completed_at: "2026-07-05 09:14:13",
                duration: "00:01:00",
                resolution: "1280 x 720",
                size: "1.3 GB",
                format: "MP4"
              }];
              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              switchPage("logs");
              applyStaticLanguage();
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: 'System \\u00b7 GUI' });
              const logText = document.getElementById("page-logs").textContent;
              currentPage = "completed";
              selected.completed = "completed-i18n-a";
              renderCompleted();
              const waitForCompletedText = expectedText => new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const text = document.getElementById("completedDetail").textContent;
                  if (text.includes(expectedText)) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error(`completed detail did not render: ${expectedText}`));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });
              await waitForCompletedText("Filename");
              const completedText = document.getElementById("completedDetail").textContent;
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "zh-TW"
              };
              document.documentElement.dataset.language = "zh-TW";
              switchPage("logs");
              applyStaticLanguage();
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: '系統 \\u00b7 圖形介面' });
              const twLogText = document.getElementById("page-logs").textContent;
              currentPage = "completed";
              renderCompleted();
              await waitForCompletedText("檔案名稱");
              const twCompletedText = document.getElementById("completedDetail").textContent;
              return { logText, completedText, twLogText, twCompletedText };
            }
            """
        )

        self.assertIn("System · GUI", result["logText"])
        self.assertIn("Log cache refreshed", result["logText"])
        self.assertIn("GUI_LOG_CACHE_REFRESHED", result["logText"])
        self.assertIn("Process", result["logText"])
        self.assertIn("Step", result["logText"])
        self.assertNotIn("日志缓存已刷新", result["logText"])
        for label in ("Filename", "Save path", "Completed at", "Duration", "Resolution", "Size", "Format"):
            self.assertIn(label, result["completedText"])
        self.assertNotIn("文件名", result["completedText"])
        self.assertIn("系統 · 圖形介面", result["twLogText"])
        self.assertIn("日誌快取已刷新", result["twLogText"])
        self.assertIn("圖形介面_日誌快取已刷新", result["twLogText"])
        self.assertNotIn("日志缓存已刷新", result["twLogText"])
        for label in ("檔案名稱", "儲存路徑", "完成時間", "時長", "解析度", "大小", "格式"):
            self.assertIn(label, result["twCompletedText"])

    def test_09i_runtime_log_translation_handles_raw_english_sources(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              document.documentElement.dataset.language = "zh-CN";
              const cn = [
                window.UcpLogI18n.translateRuntimeLogText("fetch video detail"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili route: direct BV video"),
                window.UcpLogI18n.translateRuntimeLogText("Download task has been queued"),
                window.UcpLogI18n.translateRuntimeLogText("Released download concurrency slot"),
                window.UcpLogI18n.translateRuntimeLogText("Frontend render exceeded the interactive budget; refresh cadence was relaxed"),
                window.UcpLogI18n.translateRuntimeLogText("Download completed: 小伙拉货挣到钱了"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili stream request established"),
                window.UcpLogI18n.translateRuntimeLogText("Preparing to merge Bilibili audio/video stream"),
                window.UcpLogI18n.translateRuntimeLogText("Douyin download task submitted to the queue"),
                window.UcpLogI18n.translateRuntimeLogText("Kuaishou video stream captured and submitted to the queue"),
                window.UcpLogI18n.translateRuntimeLogText("MissAV detail page sniff timed out; playlist.m3u8 was not found"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu crawl task finished"),
                window.UcpLogI18n.translateRuntimeLogText("Switched to light theme"),
                window.UcpLogI18n.translateRuntimeLogText("ℹ️ No videos or images found in this directory"),
                window.UcpLogI18n.translateRuntimeLogText("Found 3 matching users"),
                window.UcpLogI18n.translateRuntimeLogText("System · BaseDownloader"),
                window.UcpLogI18n.translateRuntimeLogText("System · WebSocketRuntime"),
                window.UcpLogI18n.translateRuntimeLogText("System · WebSocketBridge"),
                window.UcpLogI18n.translateRuntimeLogText("System · FrontendLogCache"),
                window.UcpLogI18n.translateRuntimeLogText("System · FailedRecordStore"),
                window.UcpLogI18n.translateRuntimeLogText("System · BiliAPI"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaohongshuDownloader"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaohongshuSpider"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaoHongShuSpider"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaohongshuClient"),
                window.UcpLogI18n.translateRuntimeLogText("ui callback failed"),
                window.UcpLogI18n.translateRuntimeLogText("callback failed"),
                window.UcpLogI18n.translateRuntimeLogText("_on_spider_finished 被调用"),
                window.UcpLogI18n.translateRuntimeLogText("Web event loop is unavailable; deferred frontend delta until a later async flush."),
                window.UcpLogI18n.translateRuntimeLogText("Skipped frontend delta flush because no running event loop is available."),
                window.UcpLogI18n.translateRuntimeLogText("Douyin参数初始化完成"),
                window.UcpLogI18n.translateRuntimeLogText("Douyin parameters updated!"),
                window.UcpLogI18n.translateRuntimeLogText("Config cookie_tiktok is not set; TikTok features may not work properly"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] Updating Douyin parameters, please wait..."),
                window.UcpLogI18n.translateRuntimeLogText("Download task completed"),
                window.UcpLogI18n.translateRuntimeLogText("\U0001f50d Resolving link redirect")
              ];
              document.documentElement.dataset.language = "zh-TW";
              const tw = [
                window.UcpLogI18n.translateRuntimeLogText("fetch video detail"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili route: browser scan search"),
                window.UcpLogI18n.translateRuntimeLogText("Dispatched queued task to a download worker"),
                window.UcpLogI18n.translateRuntimeLogText("Download completed: demo.mp4"),
                window.UcpLogI18n.translateRuntimeLogText("Started Douyin task | target: demo"),
                window.UcpLogI18n.translateRuntimeLogText("Preparing Kuaishou video stream download"),
                window.UcpLogI18n.translateRuntimeLogText("Switched to dark theme"),
                window.UcpLogI18n.translateRuntimeLogText("ℹ️ No videos or images found in this directory"),
                window.UcpLogI18n.translateRuntimeLogText("Found 2 matching users")
              ];
              document.documentElement.dataset.language = "en-US";
              const en = [
                window.UcpLogI18n.translateRuntimeLogText("用户确认了 45 个任务"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili 流请求建立成功"),
                window.UcpLogI18n.translateRuntimeLogText("准备下载 Bilibili 音视频流"),
                window.UcpLogI18n.translateRuntimeLogText("准备合并 Bilibili 音视频流"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili 下载任务已提交到下载队列"),
                window.UcpLogI18n.translateRuntimeLogText("🎉 全部完成: 成功 45/45 | 失败 0"),
                window.UcpLogI18n.translateRuntimeLogText("启动抖音任务 | 目标: demo"),
                window.UcpLogI18n.translateRuntimeLogText("快手分享链接已解析并提交到下载队列"),
                window.UcpLogI18n.translateRuntimeLogText("MissAV m3u8 嗅探成功并提交下载"),
                window.UcpLogI18n.translateRuntimeLogText("小红书爬虫任务结束"),
                window.UcpLogI18n.translateRuntimeLogText("已切换到浅色主题"),
                window.UcpLogI18n.translateRuntimeLogText("已切换到深色主题"),
                window.UcpLogI18n.translateRuntimeLogText("ℹ️ 该目录下没有找到视频或图片"),
                window.UcpLogI18n.translateRuntimeLogText("找到 3 个匹配用户"),
                window.UcpLogI18n.translateRuntimeLogText("爬虫完成回调已调用"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] 正在更新抖音参数，请稍等..."),
                window.UcpLogI18n.translateRuntimeLogText("配置文件 cookie 参数未登录，数据获取已提前结束"),
                window.UcpLogI18n.translateRuntimeLogText("配置文件 cookie 参数未设置，抖音平台功能可能无法正常使用"),
                window.UcpLogI18n.translateRuntimeLogText("⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] Douyin参数初始化完成"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] Douyin参数更新完毕!"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] 抖音参数更新完毕！"),
                window.UcpLogI18n.translateRuntimeLogText("TikTok 参数更新完毕！"),
                window.UcpLogI18n.translateRuntimeLogText("✅️ 下载完成: emoji.mp4"),
                window.UcpLogI18n.translateRuntimeLogText("下载完成: demo.mp4")
              ];
              return { cn, tw, en };
            }
            """
        )

        self.assertEqual(
            result["cn"],
            [
                "获取视频详情",
                "Bilibili 路由：直接 BV 视频",
                "下载任务已入队",
                "已释放下载并发槽位",
                "前端渲染超过交互预算，已降低刷新频率",
                "下载完成：小伙拉货挣到钱了",
                "Bilibili 流请求建立成功",
                "准备合并 Bilibili 音视频流",
                "抖音下载任务已提交到下载队列",
                "快手视频流已捕获并提交到下载队列",
                "MissAV 详情页嗅探超时，未发现 playlist.m3u8",
                "小红书爬虫任务结束",
                "已切换到浅色主题",
                "ℹ️ 该目录下没有找到视频或图片",
                "找到 3 个匹配用户",
                "系统 · 基础下载器",
                "系统 · WebSocket 运行时",
                "系统 · WebSocket 桥接器",
                "系统 · 前端日志缓存",
                "系统 · 失败记录存储",
                "系统 · Bilibili 接口",
                "小红书 · 小红书下载器",
                "小红书 · 小红书爬虫",
                "小红书 · 小红书爬虫",
                "小红书 · 小红书客户端",
                "UI 回调失败",
                "回调失败",
                "爬虫完成回调已调用",
                "Web 事件循环不可用，已延后前端增量刷新",
                "没有可用事件循环，已跳过前端增量刷新",
                "Douyin 参数初始化完成",
                "抖音参数更新完毕！",
                "配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                "[INFO] 正在更新抖音参数，请稍等...",
                "下载任务完成",
                "\U0001f50d 正在解析链接重定向",
            ],
        )
        self.assertEqual(
            result["tw"],
            [
                "取得影片詳情",
                "Bilibili 路由：瀏覽器掃描 search",
                "已將排隊任務分發給下載執行緒",
                "下載完成：demo.mp4",
                "啟動抖音任務 | 目標：demo",
                "準備下載快手影片串流",
                "已切換到深色主題",
                "ℹ️ 該目錄下沒有找到影片或圖片",
                "找到 2 個匹配使用者",
            ],
        )
        self.assertEqual(
            result["en"],
            [
                "User confirmed 45 tasks",
                "Bilibili stream request established",
                "Preparing Bilibili audio/video stream download",
                "Preparing to merge Bilibili audio/video stream",
                "Bilibili download task submitted to the queue",
                "🎉 All completed: success 45/45 | failed 0",
                "Started Douyin task | target: demo",
                "Kuaishou share link parsed and submitted to the queue",
                "MissAV m3u8 sniffed successfully and submitted for download",
                "Xiaohongshu crawl task finished",
                "Switched to light theme",
                "Switched to dark theme",
                "ℹ️ No videos or images found in this directory",
                "Found 3 matching users",
                "_on_spider_finished was called",
                "[INFO] Updating Douyin parameters, please wait...",
                "Config cookie is not logged in; data fetching ended early",
                "Config cookie is not set; Douyin features may not work properly",
                "⚠️ Config cookie_tiktok is not set; TikTok features may not work properly",
                "[INFO] Douyin parameters initialized",
                "[INFO] Douyin parameters updated!",
                "[INFO] Douyin parameters updated!",
                "TikTok parameters updated!",
                "✅️ Download completed: emoji.mp4",
                "Download completed: demo.mp4",
            ],
        )

    def test_09ia_log_table_localizes_mixed_runtime_summaries_after_language_switch(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.log_items = [
                {
                  id: "web-log-douyin-init",
                  time: "2026-07-08 13:28:01",
                  level: "INFO",
                  source: "GUI",
                  platform: "系统",
                  trace_id: "dy_i18n_1",
                  message_summary: "[INFO] Douyin参数初始化完成",
                  message: "[INFO] Douyin参数初始化完成"
                },
                {
                  id: "web-log-cookie",
                  time: "2026-07-08 13:28:02",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_2",
                  message_summary: "配置文件 cookie 参数未登录，数据获取已提前结束",
                  message: "配置文件 cookie 参数未登录，数据获取已提前结束"
                },
                {
                  id: "web-log-cookie-tiktok",
                  time: "2026-07-08 13:28:03",
                  level: "WARN",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_3",
                  message_summary: "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                  message: "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                  detail: { description: "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用" }
                },
                {
                  id: "web-log-completed-cn",
                  time: "2026-07-08 13:28:04",
                  level: "INFO",
                  source: "BaseDownloader",
                  platform: "Douyin",
                  trace_id: "dy_i18n_4",
                  message_summary: "下载完成: demo.mp4",
                  message: "下载完成: demo.mp4"
                },
                {
                  id: "web-log-completed-emoji-cn",
                  time: "2026-07-08 13:28:05",
                  level: "INFO",
                  source: "BaseDownloader",
                  platform: "Douyin",
                  trace_id: "dy_i18n_5",
                  message_summary: "✅️ 下载完成: emoji.mp4",
                  message: "✅️ 下载完成: emoji.mp4",
                  detail: { description: "✅️ 下载完成: emoji.mp4" }
                },
                {
                  id: "web-log-douyin-updated",
                  time: "2026-07-08 13:28:06",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_6",
                  message_summary: "[INFO] Douyin参数更新完毕!",
                  message: "[INFO] Douyin参数更新完毕!"
                },
                {
                  id: "web-log-updating-en",
                  time: "2026-07-08 13:28:07",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_7",
                  message_summary: "[INFO] Updating Douyin parameters, please wait...",
                  message: "[INFO] Updating Douyin parameters, please wait..."
                },
                {
                  id: "web-log-task-en",
                  time: "2026-07-08 13:28:08",
                  level: "INFO",
                  source: "BaseDownloader",
                  platform: "Douyin",
                  trace_id: "dy_i18n_8",
                  message_summary: "Download task completed",
                  message: "Download task completed"
                },
                {
                  id: "web-log-redirect-en",
                  time: "2026-07-08 13:28:09",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_9",
                  message_summary: "\U0001f50d Resolving link redirect",
                  message: "\U0001f50d Resolving link redirect"
                }
              ];
              window.__setLogFiltersForTest({ category: "all", level: "all", time: "all", platform: "all", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));

              document.documentElement.dataset.language = "en-US";
              renderLogs();
              await window.__waitForLogRender({ rows: 9, total: 9, matched: 9, visible: 9, text: "[INFO] Douyin parameters initialized" });
              const enText = document.getElementById("page-logs").textContent;
              selectLog("web-log-cookie-tiktok");
              await window.__waitForLogRender({ rows: 9, total: 9, matched: 9, visible: 9, selectedId: "web-log-cookie-tiktok", text: "Config cookie_tiktok is not set; TikTok features may not work properly" });
              const enDetailText = document.getElementById("logDetail").textContent;
              const enDetailJson = document.querySelector("#logDetail .log-detail-readable")?.dataset?.json || "";

              document.documentElement.dataset.language = "zh-CN";
              renderLogs();
              await window.__waitForLogRender({ rows: 9, total: 9, matched: 9, visible: 9, text: "\U0001f50d 正在解析链接重定向" });
              const zhText = document.getElementById("page-logs").textContent;
              return { enText, enDetailText, enDetailJson, zhText };
            }
            """
        )

        self.assertIn("[INFO] Douyin parameters initialized", result["enText"])
        self.assertIn("Config cookie is not logged in; data fetching ended early", result["enText"])
        self.assertIn("⚠️ Config cookie_tiktok is not set; TikTok features may not work properly", result["enText"])
        self.assertIn("Download completed: demo.mp4", result["enText"])
        self.assertIn("✅️ Download completed: emoji.mp4", result["enText"])
        self.assertIn("[INFO] Douyin parameters updated!", result["enText"])
        self.assertNotIn("Douyin参数初始化完成", result["enText"])
        self.assertNotIn("Douyin参数更新完毕", result["enText"])
        self.assertNotIn("配置文件 cookie 参数未登录", result["enText"])
        self.assertNotIn("配置文件 cookie_tiktok 参数未设置", result["enText"])
        self.assertIn("⚠️ Config cookie_tiktok is not set; TikTok features may not work properly", result["enDetailText"])
        self.assertIn("Config cookie_tiktok is not set; TikTok features may not work properly", result["enDetailJson"])
        self.assertNotIn("配置文件 cookie_tiktok 参数未设置", result["enDetailJson"])
        self.assertIn("[INFO] 正在更新抖音参数，请稍等...", result["zhText"])
        self.assertIn("下载任务完成", result["zhText"])
        self.assertIn("\U0001f50d 正在解析链接重定向", result["zhText"])
        self.assertNotIn("Updating Douyin parameters", result["zhText"])
        self.assertNotIn("Download task completed", result["zhText"])

    def test_13_log_panel_writes(self):
        """appendLog 应在 logPanel 写入内容。"""
        self._goto_ready()
        timestamp = self._page.evaluate("formatLocalDateTime(new Date(2026, 6, 4, 6, 24, 9))")
        self.assertEqual(timestamp, "2026-07-04 06:24:09")
        self._page.evaluate("appendLog('test marker 12345')")
        content = self._page.locator("#logPanel").text_content()
        self.assertIn("test marker 12345", content)

    def test_13b_log_center_footer_paginates_like_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              switchPage('logs');
              currentPage = 'logs';
              window.__setLogFiltersForTest({ time: '全部' });
              frontendState.log_items = Array.from({ length: 25 }, (_, index) => ({
                id: `log-${index + 1}`,
                time: `2026-07-04 06:${String(index).padStart(2, '0')}:00`,
                level: 'INFO',
                source: 'GUI',
                trace_id: `trace-${index + 1}`,
                message_summary: `message-${index + 1}`,
                message: `message-${index + 1}`,
                detail: '',
                stack: ''
              }));
              renderLogs();
              await window.__waitForLogRender({ rows: 20, total: 25, matched: 25, visible: 20 });
              const firstPageRows = document.querySelectorAll('#logBody tr').length;
              const firstStats = document.getElementById('logTotal').textContent;
              const firstIndicator = document.getElementById('logPageIndicator').textContent;
              const firstPrevDisabled = document.getElementById('logPrevPage').disabled;
              const firstNextDisabled = document.getElementById('logNextPage').disabled;
              setLogPage(1);
              await window.__waitForLogRender({ rows: 5, total: 25, matched: 25, visible: 5 });
              return {
                firstPageRows,
                firstStats,
                firstIndicator,
                firstPrevDisabled,
                firstNextDisabled,
                secondPageRows: document.querySelectorAll('#logBody tr').length,
                secondStats: document.getElementById('logTotal').textContent,
                secondIndicator: document.getElementById('logPageIndicator').textContent,
                secondPrevDisabled: document.getElementById('logPrevPage').disabled,
                secondNextDisabled: document.getElementById('logNextPage').disabled
              };
            }
            """
        )

        self.assertEqual(result["firstPageRows"], 20)
        self.assertEqual(result["firstStats"], "共 25 条 / 匹配 25 条 / 当前显示 20 条")
        self.assertEqual(result["firstIndicator"], "第 1 / 2 页")
        self.assertTrue(result["firstPrevDisabled"])
        self.assertFalse(result["firstNextDisabled"])
        self.assertEqual(result["secondPageRows"], 5)
        self.assertEqual(result["secondStats"], "共 25 条 / 匹配 25 条 / 当前显示 5 条")
        self.assertEqual(result["secondIndicator"], "第 2 / 2 页")
        self.assertFalse(result["secondPrevDisabled"])
        self.assertTrue(result["secondNextDisabled"])

    def test_13c_log_center_empty_state_matches_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              switchPage('logs');
              currentPage = 'logs';
              window.__setLogFiltersForTest({ category: 'all', level: '全部', time: '全部', platform: '全部', trace: '', keyword: '不会命中的关键字' });
              frontendState.log_items = [{
                id: 'log-empty-a',
                time: '2026-07-04 06:30:00',
                level: 'INFO',
                source: 'GUI',
                trace_id: 'trace-log-empty-a',
                message_summary: '可见日志',
                message: '可见日志',
                detail: '',
                stack: ''
              }];
              renderLogs();
              await window.__waitForLogRender({ rows: 0, total: 1, matched: 0, visible: 0 });
              const empty = document.getElementById('logEmptyState');
              const subtitle = empty.querySelector('.log-empty-subtitle');
              const primaryNode = empty.querySelector('[data-log-empty-primary]');
              const secondaryNode = empty.querySelector('[data-log-empty-secondary]');
              return {
                rowCount: document.querySelectorAll('#logBody tr').length,
                hidden: empty.hidden,
                text: empty.textContent.replace(/\\s+/g, ' ').trim(),
                ariaLabel: subtitle?.getAttribute('aria-label') || '',
                primary: primaryNode?.textContent || '',
                secondary: secondaryNode?.textContent || '',
                primaryTop: primaryNode?.getBoundingClientRect().top || 0,
                secondaryTop: secondaryNode?.getBoundingClientRect().top || 0,
                subtitleDisplay: getComputedStyle(subtitle).display,
                subtitleDirection: getComputedStyle(subtitle).flexDirection,
                stats: document.getElementById('logTotal').textContent
              };
            }
            """
        )

        self.assertEqual(result["rowCount"], 0)
        self.assertFalse(result["hidden"])
        self.assertIn("暂无匹配日志", result["text"])
        self.assertEqual(result["ariaLabel"], "调整筛选条件 或点击「刷新缓冲」重新加载日志")
        self.assertNotIn("调整筛选条件，", result["text"])
        self.assertEqual(result["primary"], "调整筛选条件")
        self.assertEqual(result["secondary"], "或点击「刷新缓冲」重新加载日志")
        self.assertGreater(result["secondaryTop"], result["primaryTop"])
        self.assertEqual(result["subtitleDisplay"], "flex")
        self.assertEqual(result["subtitleDirection"], "column")
        self.assertEqual(result["stats"], "共 1 条 / 匹配 0 条 / 当前显示 0 条")

    def test_13c_log_table_summary_column_stays_visible_at_gui_width(self):
        self._page.set_viewport_size({"width": 1270, "height": 1024})
        try:
            self._goto_ready()

            result = self._page.evaluate(
                """
                async () => {
                  window.__isolateFrontendStateForTest();
                  currentPage = 'logs';
                  window.__setLogFiltersForTest({ category: 'all', level: '全部', time: '全部', platform: '全部', trace: '', keyword: '' });
                  frontendState.log_items = [{
                    id: 'log-layout-a',
                    time: '2026-07-04 22:45:00',
                    level: 'INFO',
                    source: 'GUI',
                    source_display: '系统 · WebUI',
                    source_display_icon_file: 'nav_settings.png',
                    trace_id: 'web_scan_start_trace_20260704',
                    message_summary: 'Web 端开始扫描本地媒体目录（异步）',
                    message: 'Web 端开始扫描本地媒体目录（异步）',
                    detail: '',
                    stack: ''
                  }];
                  switchPage('logs');
                  renderLogs();
                  await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: 'Web 端开始扫描本地媒体目录' });
                  const shell = document.querySelector('#page-logs .logs-table-card .table-shell');
                  const shellRect = shell.getBoundingClientRect();
                  const headers = Array.from(document.querySelectorAll('#page-logs thead th')).map(node => node.getBoundingClientRect());
                  const rowCells = Array.from(document.querySelectorAll('#logBody tr:first-child td')).map(node => node.getBoundingClientRect());
                  const grid = document.querySelector('#page-logs .logs-grid');
                  const detail = document.querySelector('#page-logs .logs-right-column');
                  return {
                    shellRight: shellRect.right,
                    headerRight: headers[4].right,
                    cellRight: rowCells[4].right,
                    summaryHeaderWidth: headers[4].width,
                    summaryCellWidth: rowCells[4].width,
                    scrollOverflow: shell.scrollWidth - shell.clientWidth,
                    gridColumns: getComputedStyle(grid).gridTemplateColumns,
                    detailWidth: detail.getBoundingClientRect().width
                  };
                }
                """
            )
        finally:
            self._page.set_viewport_size({"width": 1280, "height": 720})

        self.assertLessEqual(result["headerRight"], result["shellRight"] + 1)
        self.assertLessEqual(result["cellRight"], result["shellRight"] + 1)
        self.assertLessEqual(result["scrollOverflow"], 1)
        self.assertGreaterEqual(result["summaryHeaderWidth"], 82)
        self.assertGreaterEqual(result["summaryCellWidth"], 82)
        self.assertLessEqual(result["detailWidth"], 360)

    def test_13c_log_detail_copy_export_actions_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              const originalClick = HTMLAnchorElement.prototype.click;
              const originalCreateObjectUrl = URL.createObjectURL;
              const originalRevokeObjectUrl = URL.revokeObjectURL;
              window.__copiedLogTexts = [];
              window.__downloadedLogDetail = null;
              Object.defineProperty(navigator, 'clipboard', {
                value: {
                  writeText: text => {
                    window.__copiedLogTexts.push(text);
                    return Promise.resolve();
                  }
                },
                configurable: true
              });
              HTMLAnchorElement.prototype.click = function () {
                window.__downloadedLogDetail = { href: this.href, download: this.download };
              };
              URL.createObjectURL = () => 'blob:log-detail';
              URL.revokeObjectURL = () => {};
              try {
                switchPage('logs');
                window.__setLogFiltersForTest({ time: '全部' });
                frontendState.log_items = [{
                  id: 'log-detail-a',
                  time: '2026-07-04 06:30:00',
                  level: 'INFO',
                  raw_level: 'INFO',
                  source: 'ApplicationController',
                  platform: '系统',
                  trace_id: 'trace-log-detail-a',
                  message_summary: '应用开始初始化',
                  message: '应用开始初始化',
                  detail: { description: '应用开始初始化', status_code: 'APP_INIT' },
                  stack: ''
                }];
                window.UcpLogCenter.render();
                await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, selectedId: 'log-detail-a' });
                window.UcpLogCenter.copyDetail();
                window.UcpLogCenter.copyJson();
                window.UcpLogCenter.exportDetail();
                await new Promise(resolve => setTimeout(resolve, 0));
                return {
                  selectedLog: document.querySelector('#logBody tr.selected')?.dataset.key || '',
                  detailText: document.getElementById('logDetail').textContent,
                  copied: window.__copiedLogTexts,
                  download: window.__downloadedLogDetail
                };
              } finally {
                HTMLAnchorElement.prototype.click = originalClick;
                URL.createObjectURL = originalCreateObjectUrl;
                URL.revokeObjectURL = originalRevokeObjectUrl;
              }
            }
            """
        )

        self.assertEqual(result["selectedLog"], "log-detail-a")
        self.assertIn("日志详情", result["detailText"])
        self.assertIn("详细信息", result["detailText"])
        self.assertEqual(len(result["copied"]), 2)
        self.assertIn("trace-log-detail-a", result["copied"][0])
        self.assertIn("APP_INIT", result["copied"][0])
        self.assertIn("description", result["copied"][1])
        self.assertIn("APP_INIT", result["copied"][1])
        self.assertEqual(result["download"]["href"], "blob:log-detail")
        self.assertEqual(result["download"]["download"], "log_detail_trace-log-detail-a.json")

    def test_13d_log_center_ignores_stale_worker_errors_and_retries_current_detail(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const nativeWorker = window.Worker;
              const workers = [];
              const state = {
                log_items: [{
                  id: "worker-log",
                  time: "2026-07-10 09:00:00",
                  level: "INFO",
                  source: "GUI",
                  trace_id: "worker-trace",
                  message_summary: "initial message",
                  message: "initial message",
                  detail: { description: "same", nested: { alpha: 1, beta: 1 } },
                  stack: ""
                }],
                settings_snapshot: {}
              };

              class ControlledWorker {
                constructor(url) {
                  this.url = String(url);
                  this.requests = [];
                  this.terminateCalls = 0;
                  workers.push(this);
                }
                postMessage(request) { this.requests.push(request); }
                terminate() { this.terminateCalls += 1; }
                emit(payload) { this.onmessage?.({ data: payload }); }
                fail() { this.onerror?.(new Event("error")); }
              }

              const workerFor = name => workers.find(worker => worker.url.includes(name));
              const detailWorkers = () => workers.filter(worker => worker.url.includes("log_detail_worker"));
              const queryResult = request => window.UcpLogDisplay.queryLogItems(request);
              const detailResult = request => {
                const detailJson = JSON.stringify(request.item.detail, null, 2);
                return {
                  sequence: request.sequence,
                  itemId: request.itemId,
                  item: request.item,
                  detailJson,
                  detailDisplayText: detailJson,
                  fullJson: JSON.stringify({ detail: request.item.detail }, null, 2),
                  stack: "",
                  filename: "worker-log.json"
                };
              };

              window.Worker = ControlledWorker;
              window.UcpLogCenter.dispose();
              try {
                window.UcpLogCenter.configure({
                  getState: () => state,
                  getLanguage: () => "zh-CN",
                  t: value => String(value),
                  esc,
                  escAttr,
                  byId,
                  writeClipboard: () => Promise.resolve(true),
                  runOperation: () => {},
                  onFiltersChange: () => {}
                });
                byId("logTimeFilter").value = "all";
                window.UcpLogCenter.syncFiltersFromDom();
                switchPage("logs");

                const queryWorker = workerFor("log_query_worker");
                const firstQuery = queryWorker.requests.at(-1);
                state.log_items[0].message_summary = "query current";
                state.log_items[0].message = "query current";
                window.UcpLogCenter.render();
                const secondQuery = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "error", sequence: firstQuery.sequence, message: "stale query error" });
                const staleQueryIgnored = queryWorker.terminateCalls === 0;
                if (!staleQueryIgnored) {
                  return {
                    staleQueryIgnored,
                    detailMutationRequested: false,
                    staleDetailIgnored: false,
                    stableOrderCacheHit: false,
                    genericErrorRetried: false,
                    renderedJson: ""
                  };
                }
                queryWorker.emit({ type: "result", result: queryResult(secondQuery) });

                const detailWorker = detailWorkers()[0];
                const firstDetail = detailWorker.requests[0];
                state.log_items[0].message_summary = "detail current";
                state.log_items[0].message = "detail current";
                state.log_items[0].detail = { description: "same", nested: { alpha: 1, beta: 2 } };
                window.UcpLogCenter.render();
                const thirdQuery = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "result", result: queryResult(thirdQuery) });
                const secondDetail = detailWorker.requests[1];
                const detailMutationRequested = Boolean(secondDetail);
                detailWorker.emit({ type: "error", sequence: firstDetail.sequence, message: "stale detail error" });
                const staleDetailIgnored = detailWorker.terminateCalls === 0
                  && document.getElementById("logDetail").textContent.includes("detail current");
                if (secondDetail) detailWorker.emit({ type: "result", result: detailResult(secondDetail) });

                state.log_items[0].detail = { nested: { beta: 2, alpha: 1 }, description: "same" };
                window.UcpLogCenter.render();
                const fourthQuery = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "result", result: queryResult(fourthQuery) });
                const stableOrderCacheHit = detailWorker.requests.length === 2;

                detailWorker.fail();
                const retryWorker = detailWorkers()[1];
                const genericErrorRetried = Boolean(retryWorker && retryWorker.requests.length === 1);
                if (retryWorker) retryWorker.emit({ type: "result", result: detailResult(retryWorker.requests[0]) });
                const renderedJson = document.querySelector("#logDetail .log-detail-readable")?.dataset.json || "";
                return {
                  staleQueryIgnored,
                  detailMutationRequested,
                  staleDetailIgnored,
                  stableOrderCacheHit,
                  genericErrorRetried,
                  renderedJson
                };
              } finally {
                window.UcpLogCenter.dispose();
                window.Worker = nativeWorker;
              }
            }
            """
        )

        self.assertTrue(result["staleQueryIgnored"])
        self.assertTrue(result["detailMutationRequested"])
        self.assertTrue(result["staleDetailIgnored"])
        self.assertTrue(result["stableOrderCacheHit"])
        self.assertTrue(result["genericErrorRetried"])
        self.assertIn('"beta": 2', result["renderedJson"])

    def test_13e_log_center_dispose_is_idempotent_and_cancels_pending_fallback(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.__isolateFrontendStateForTest();
              const nativeWorker = window.Worker;
              const nativeSetTimeout = window.setTimeout;
              const nativeClearTimeout = window.clearTimeout;
              const workers = [];
              const timers = [];
              const clearedTimers = [];
              const state = {
                log_items: [{
                  id: "dispose-log",
                  time: "2026-07-10 10:00:00",
                  level: "INFO",
                  source: "GUI",
                  trace_id: "dispose-trace",
                  message_summary: "dispose message",
                  message: "dispose message",
                  detail: { description: "dispose message" },
                  stack: ""
                }],
                settings_snapshot: {}
              };

              class ControlledWorker {
                constructor(url) {
                  this.url = String(url);
                  this.requests = [];
                  this.terminateCalls = 0;
                  workers.push(this);
                }
                postMessage(request) { this.requests.push(request); }
                terminate() { this.terminateCalls += 1; }
                emit(payload) { this.onmessage?.({ data: payload }); }
              }

              const configure = () => {
                window.UcpLogCenter.configure({
                  getState: () => state,
                  getLanguage: () => "zh-CN",
                  t: value => String(value),
                  esc,
                  escAttr,
                  byId,
                  writeClipboard: () => Promise.resolve(true),
                  runOperation: () => {},
                  onFiltersChange: () => {}
                });
                byId("logTimeFilter").value = "all";
                window.UcpLogCenter.syncFiltersFromDom();
              };

              window.Worker = ControlledWorker;
              window.UcpLogCenter.dispose();
              try {
                configure();
                switchPage("logs");
                const queryWorker = workers.find(worker => worker.url.includes("log_query_worker"));
                const queryRequest = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "result", result: window.UcpLogDisplay.queryLogItems(queryRequest) });
                const detailWorker = workers.find(worker => worker.url.includes("log_detail_worker"));
                window.UcpLogCenter.dispose();
                window.UcpLogCenter.dispose();

                document.getElementById("logBody").innerHTML = "";
                document.getElementById("logDetail").innerHTML = "";
                state.log_items[0].message_summary = "fallback must not render";
                state.log_items[0].message = "fallback must not render";
                window.Worker = undefined;
                let nextTimerId = 1;
                window.setTimeout = callback => {
                  const timer = { id: nextTimerId++, callback };
                  timers.push(timer);
                  return timer.id;
                };
                window.clearTimeout = timerId => { clearedTimers.push(timerId); };
                configure();
                window.UcpLogCenter.render();
                const pendingTimer = timers.at(-1);
                window.UcpLogCenter.dispose();
                window.UcpLogCenter.dispose();
                pendingTimer.callback();
                return {
                  queryTerminatedOnce: queryWorker.terminateCalls === 1,
                  detailTerminatedOnce: detailWorker.terminateCalls === 1,
                  fallbackCancelled: clearedTimers.includes(pendingTimer.id),
                  fallbackRendered: document.getElementById("page-logs").textContent.includes("fallback must not render")
                };
              } finally {
                window.UcpLogCenter.dispose();
                window.Worker = nativeWorker;
                window.setTimeout = nativeSetTimeout;
                window.clearTimeout = nativeClearTimeout;
              }
            }
            """
        )

        self.assertTrue(result["queryTerminatedOnce"])
        self.assertTrue(result["detailTerminatedOnce"])
        self.assertTrue(result["fallbackCancelled"])
        self.assertFalse(result["fallbackRendered"])
