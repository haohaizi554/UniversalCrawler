from __future__ import annotations

import re
from typing import Any

from app.ui.localization import normalize_language, platform_display_name, tr


_LOCAL_FILE_LOADED_RE = re.compile(
    r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
    r"已加载\s*(?P<count>\d+)\s*个本地文件\s*"
    r"\(视频[:：]\s*(?P<videos>\d+)\s*,\s*图片[:：]\s*(?P<images>\d+)\)$"
)
_SCAN_DIR_RE = re.compile(
    r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
    r"正在扫描目录[:：]\s*(?P<path>.+)$"
)
_DOWNLOAD_DONE_RE = re.compile(r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?下载完成[:：]\s*(?P<title>.+)$")
_DOWNLOAD_FAILED_RE = re.compile(
    r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
    r"下载失败\s*\[(?P<title>.+?)\][：:]\s*(?P<error>.+)$"
)
_DYNAMIC_PREFIX = r"(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
_CRAWL_CONFIRM_RE = re.compile(rf"^{_DYNAMIC_PREFIX}用户确认了\s*(?P<count>\d+)\s*个任务$")
_CRAWL_FINAL_CONFIRM_RE = re.compile(rf"^{_DYNAMIC_PREFIX}最终确认\s*(?P<count>\d+)\s*个.*$")
_CRAWL_START_RE = re.compile(rf"^{_DYNAMIC_PREFIX}启动\s*(?P<platform>.*?)\s*爬虫任务$")
_TASK_START_TARGET_RE = re.compile(rf"^{_DYNAMIC_PREFIX}启动\s*(?P<platform>.*?)\s*任务\s*\|\s*目标[:：]\s*(?P<target>.*)$")
_TASK_START_MODE_KEYWORD_RE = re.compile(
    rf"^{_DYNAMIC_PREFIX}启动任务\s*\|\s*模式[:：]\s*(?P<mode>.*?)\s*\|\s*关键词[:：]\s*(?P<keyword>.*)$"
)
_TASK_START_MODE_RE = re.compile(rf"^{_DYNAMIC_PREFIX}启动任务\s*\|\s*模式[:：]\s*(?P<mode>.*)$")
_SCAN_FINISH_RE = re.compile(rf"^{_DYNAMIC_PREFIX}扫描结束[，,]\s*共\s*(?P<count>\d+)(?P<tail>.*)$")
_FETCH_OK_RE = re.compile(rf"^{_DYNAMIC_PREFIX}获取成功\s*(?P<detail>.*)$")
_PARSE_STREAM_RE = re.compile(rf"^{_DYNAMIC_PREFIX}解析流[:：]\s*(?P<detail>.*)$")
_EXPANDING_RE = re.compile(rf"^{_DYNAMIC_PREFIX}正在展开[:：]\s*(?P<detail>.*)$")
_PIPELINE_RE = re.compile(rf"^{_DYNAMIC_PREFIX}流水线已建立[:：]\s*(?P<detail>.*)$")
_ALL_COMPLETED_RE = re.compile(
    rf"^{_DYNAMIC_PREFIX}全部完成[:：]\s*成功\s*(?P<success>\d+)\s*/\s*(?P<total>\d+)\s*\|\s*失败\s*(?P<failed>\d+)$"
)

_RUNTIME_LOG_PHRASE_TRANSLATIONS = (
    ("Bilibili 流请求建立成功", "Bilibili stream request established", "Bilibili 串流請求建立成功"),
    ("Bilibili 下载任务已提交到下载队列", "Bilibili download task submitted to the queue", "Bilibili 下載任務已提交到下載佇列"),
    ("Bilibili 下载任务已装配完成", "Bilibili download task assembled", "Bilibili 下載任務已組裝完成"),
    ("Bilibili 音视频合并完成", "Bilibili audio/video merge completed", "Bilibili 音視訊合併完成"),
    ("Bilibili 音视频合并", "Bilibili audio/video merge", "Bilibili 音視訊合併"),
    ("Bilibili 爬虫任务结束", "Bilibili crawl task finished", "Bilibili 爬蟲任務結束"),
    ("Bilibili 获取播放流失败", "Bilibili playback stream fetch failed", "Bilibili 播放串流取得失敗"),
    ("Bilibili 播放流响应为空", "Bilibili playback stream response is empty", "Bilibili 播放串流回應為空"),
    ("B站流下载失败", "B-site stream download failed", "B 站串流下載失敗"),
    ("B站下载失败", "B-site download failed", "B 站下載失敗"),
    ("检查 Bilibili 登录状态", "Checking Bilibili login status", "檢查 Bilibili 登入狀態"),
    ("获取播放流地址", "Fetching playback stream URL", "取得播放串流位址"),
    ("启动 Bilibili 爬虫任务", "Started Bilibili crawl task", "啟動 Bilibili 爬蟲任務"),
    ("准备下载 Bilibili 音视频流", "Preparing Bilibili audio/video stream download", "準備下載 Bilibili 音視訊流"),
    ("准备合并 Bilibili 音视频流", "Preparing to merge Bilibili audio/video stream", "準備合併 Bilibili 音視訊流"),
    ("音视频流写入完成，准备合并", "Audio/video stream written; preparing to merge", "音視訊流寫入完成，準備合併"),
    ("音视频流下载中", "Audio/video stream downloading", "音視訊流下載中"),
    ("任务进入 Bilibili 下载器", "Task entered Bilibili downloader", "任務進入 Bilibili 下載器"),
    ("ffmpeg 合并音视频中", "ffmpeg merging audio/video", "ffmpeg 合併音視訊中"),
    ("ffmpeg 合并音视频失败", "ffmpeg audio/video merge failed", "ffmpeg 音視訊合併失敗"),
    ("ffmpeg 合并音视频超时", "ffmpeg audio/video merge timed out", "ffmpeg 音視訊合併逾時"),
    ("已刷新 B站 CDN URL，使用新地址重试", "Refreshed B-site CDN URL; retrying with new URL", "已刷新 B 站 CDN URL，使用新位址重試"),
    ("已刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL successfully", "已刷新 B 站 CDN URL 成功"),
    ("重新刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully", "重新刷新 B 站 CDN URL 成功"),
    ("重刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully", "重刷新 B 站 CDN URL 成功"),
    ("爬虫发现可下载资源", "Crawler found downloadable resources", "爬蟲發現可下載資源"),
    ("爬虫任务结束", "Crawl task finished", "爬蟲任務結束"),
    ("下载失败", "Download failed", "下載失敗"),
    ("下载任务已入队", "Download task has been queued", "下載任務已入隊"),
    ("下载任务已加入执行队列", "Download task has been queued for execution", "下載任務已加入執行隊列"),
    ("下载任务开始执行", "Download task started", "下載任務開始執行"),
    ("下载任务完成", "Download task completed", "下載任務完成"),
    ("下载任务被用户停止", "Download task stopped by user", "下載任務被使用者停止"),
    ("下载完成后已按文件签名修正扩展名", "Fixed extension after download by file signature", "下載完成後已依檔案簽章修正副檔名"),
    ("分块下载不可用，回退到后续下载策略", "Chunked download unavailable; falling back to later download strategy", "分塊下載不可用，回退到後續策略"),
    ("下载策略执行失败，回退到后续策略", "Download strategy failed; falling back to later strategy", "下載策略執行失敗，回退到後續策略"),
    ("抖音下载任务已提交到下载队列", "Douyin download task submitted to the queue", "抖音下載任務已提交到下載佇列"),
    ("启动抖音爬虫任务", "Started Douyin crawl task", "啟動抖音爬蟲任務"),
    ("抖音爬虫任务结束", "Douyin crawl task finished", "抖音爬蟲任務結束"),
    ("抖音爬虫运行异常", "Douyin crawl runtime error", "抖音爬蟲執行異常"),
    ("进入抖音任务提交阶段", "Entered Douyin task submit stage", "進入抖音任務提交階段"),
    ("Douyin 参数初始化完成", "Douyin parameters initialized", "Douyin 參數初始化完成"),
    ("抖音作品详情返回", "Douyin work detail returned", "抖音作品詳情返回"),
    ("抖音用户作品分页返回", "Douyin user works page returned", "抖音使用者作品分頁返回"),
    ("抖音合集分页返回", "Douyin collection page returned", "抖音合集分頁返回"),
    ("抖音搜索分页返回", "Douyin search page returned", "抖音搜尋分頁返回"),
    ("抖音用户搜索返回", "Douyin user search returned", "抖音使用者搜尋返回"),
    ("记录抖音用户搜索返回结构", "Recorded Douyin user search response shape", "記錄抖音使用者搜尋返回結構"),
    ("准备下载抖音资源", "Preparing Douyin resource download", "準備下載抖音資源"),
    ("快手分享链接已通过 HTTP 直连解析并提交到下载队列", "Kuaishou share link parsed through direct HTTP and submitted to the queue", "快手分享連結已透過 HTTP 直連解析並提交到下載佇列"),
    ("快手分享链接已解析并提交到下载队列", "Kuaishou share link parsed and submitted to the queue", "快手分享連結已解析並提交到下載佇列"),
    ("快手任务选择已确认", "Kuaishou task selection confirmed", "快手任務選擇已確認"),
    ("快手视频流已捕获并提交到下载队列", "Kuaishou video stream captured and submitted to the queue", "快手影片串流已捕獲並提交到下載佇列"),
    ("快手流捕获流水线结束", "Kuaishou stream capture pipeline finished", "快手串流捕獲流水線結束"),
    ("准备下载快手视频流", "Preparing Kuaishou video stream download", "準備下載快手影片串流"),
    ("快手视频下载完成", "Kuaishou video download completed", "快手影片下載完成"),
    ("启动小红书爬虫任务", "Started Xiaohongshu crawl task", "啟動小紅書爬蟲任務"),
    ("小红书爬虫运行异常", "Xiaohongshu crawl runtime error", "小紅書爬蟲執行異常"),
    ("小红书爬虫任务结束", "Xiaohongshu crawl task finished", "小紅書爬蟲任務結束"),
    ("小红书视频下载失败", "Xiaohongshu video download failed", "小紅書影片下載失敗"),
    ("MissAV m3u8 嗅探成功并提交下载", "MissAV m3u8 sniffed successfully and submitted for download", "MissAV m3u8 嗅探成功並提交下載"),
    ("MissAV 详情页嗅探超时，未发现 playlist.m3u8", "MissAV detail page sniff timed out; playlist.m3u8 was not found", "MissAV 詳情頁嗅探逾時，未發現 playlist.m3u8"),
    ("MissAV 详情页加载失败", "MissAV detail page failed to load", "MissAV 詳情頁載入失敗"),
    ("准备下载 MissAV HLS 流", "Preparing MissAV HLS stream download", "準備下載 MissAV HLS 串流"),
    ("正在尝试以 curl_cffi 浏览器模拟方式下载 MissAV HLS", "Trying curl_cffi browser-impersonated HLS download for MissAV", "正在嘗試以 curl_cffi 瀏覽器模擬方式下載 MissAV HLS"),
    ("正在尝试以 Playwright 浏览器上下文下载 MissAV HLS", "Trying Playwright browser-context HLS download for MissAV", "正在嘗試以 Playwright 瀏覽器上下文下載 MissAV HLS"),
    ("准备 N_m3u8DL-RE HLS 下载", "Preparing N_m3u8DL-RE HLS download", "準備 N_m3u8DL-RE HLS 下載"),
    ("N_m3u8DL-RE 下载完成", "N_m3u8DL-RE download finished", "N_m3u8DL-RE 下載完成"),
    ("已为受保护的 MissAV 流启动本地 HLS 代理", "Started local HLS proxy for protected MissAV stream", "已為受保護的 MissAV 串流啟動本機 HLS 代理"),
    ("应用启动时已清理过期 HLS 工作区", "Swept stale HLS workspaces at application startup", "應用啟動時已清理過期 HLS 工作區"),
    ("yt-dlp 回退在无模拟模式下成功", "yt-dlp fallback succeeded without impersonation", "yt-dlp 回退在無模擬模式下成功"),
    ("ffmpeg 下载前检查真实地址", "ffmpeg checked real URL before download", "ffmpeg 下載前檢查真實位址"),
    ("准备调用 ffmpeg 执行下载", "Preparing to call ffmpeg for download", "準備呼叫 ffmpeg 執行下載"),
    ("ffmpeg 下载完成", "ffmpeg download completed", "ffmpeg 下載完成"),
    ("应用开始初始化", "App initialization started", "應用開始初始化"),
    ("主窗口初始化完成", "Main window initialization completed", "主視窗初始化完成"),
    ("应用开始退出清理", "Application shutdown cleanup started", "應用開始退出清理"),
    ("用户启动爬虫任务", "User started crawl task", "使用者啟動爬蟲任務"),
    ("用户取消任务选择，停止爬虫任务", "User cancelled task selection; crawl task stopped", "使用者取消任務選擇，已停止爬蟲任務"),
    ("用户请求停止爬虫任务", "User requested to stop the crawl task", "使用者要求停止爬蟲任務"),
    ("用户取消下载", "User cancelled download", "使用者取消下載"),
    ("远程主机强迫关闭了一个现有的连接。", "The remote host forcibly closed an existing connection.", "遠端主機強制關閉了一個現有連線。"),
    ("远程主机强迫关闭了一个现有的连接", "The remote host forcibly closed an existing connection", "遠端主機強制關閉了一個現有連線"),
    ("保存目录已变更", "Save directory changed", "儲存目錄已變更"),
    ("仅下载视频模式已跳过非视频资源", "Video-only mode skipped a non-video resource", "僅下載影片模式已略過非影片資源"),
    (
        "已通过重建分发信号量提高并发容量",
        "Increased concurrency by rebuilding dispatch semaphore capacity.",
        "已透過重建分發信號量提高並發容量",
    ),
    (
        "已降低并发：现有下载线程将在完成后自然收尾",
        "Reduced concurrency: existing download workers will wind down as they complete.",
        "已降低並發：現有下載執行緒將在完成後自然收尾",
    ),
    (
        "图片快速通道已关闭：现有轻量线程将在完成后自然收尾",
        "Image fast lane disabled: existing lightweight workers will wind down as they complete.",
        "圖片快速通道已關閉：現有輕量執行緒將在完成後自然收尾",
    ),
    (
        "已从活动并发统计中清理过期完成线程",
        "Pruned stale completed workers from active concurrency accounting.",
        "已從活動並發統計中清理過期完成執行緒",
    ),
    (
        "下载管理器正在停止，清理队列和线程",
        "Download manager stopping, draining queue and workers",
        "下載管理器正在停止，清理佇列和執行緒",
    ),
    ("分发线程未能在 2 秒内停止", "Dispatcher thread failed to stop within 2 seconds", "分發執行緒未能在 2 秒內停止"),
    (
        "并发重建后，过期分发信号量令牌无法归还",
        "Stale dispatch semaphore token could not be returned after concurrency rebuild.",
        "並發重建後，過期分發信號量權杖無法歸還",
    ),
    (
        "已跳过下载槽位释放，因为信号量容量已满",
        "Download slot release skipped because semaphore capacity is already full",
        "已略過下載槽位釋放，因為信號量容量已滿",
    ),
    ("下载线程停止超时，正在强制清理", "Worker stop timeout reached; forcing shutdown cleanup", "下載執行緒停止逾時，正在強制清理"),
    (
        "AppState 变更事件因发布递归超过安全限制而被丢弃",
        "AppState change event dropped because publish recursion exceeded the safety limit",
        "AppState 變更事件因發布遞迴超過安全限制而被丟棄",
    ),
    (
        "已丢弃媒体元数据探测结果：条目已不存在",
        "Completed media metadata probe result was discarded because the item no longer exists",
        "已丟棄媒體中繼資料探測結果：項目已不存在",
    ),
    (
        "已丢弃媒体元数据探测结果：本地路径已变化",
        "Completed media metadata probe result was discarded because the local path changed",
        "已丟棄媒體中繼資料探測結果：本機路徑已變更",
    ),
    (
        "媒体元数据探测已完成，但未获得可用时长或分辨率",
        "Completed media metadata probe finished without usable duration or resolution",
        "媒體中繼資料探測已完成，但未取得可用時長或解析度",
    ),
    (
        "本地媒体元数据探测完成，但未获得可用时长或分辨率",
        "Local media metadata probe finished without usable duration or resolution",
        "本機媒體中繼資料探測完成，但未取得可用時長或解析度",
    ),
    (
        "分块线程仍在运行，已延后清理临时文件",
        "Deferred temp-file cleanup because chunk worker threads are still running",
        "分塊執行緒仍在執行，已延後清理暫存檔",
    ),
    (
        "已跳过 N_m3u8DL-RE 临时目录清理：目录不在受控工作区内",
        "Skip N_m3u8DL-RE temp cleanup because the directory is outside the owned workspace",
        "已略過 N_m3u8DL-RE 暫存目錄清理：目錄不在受控工作區內",
    ),
    (
        "MissAV 浏览器 HLS 在缓存播放列表后失败，已跳过可能再次触发 403 的网络播放列表回退",
        "MissAV browser HLS failed after cached playlist; skipping network playlist fallback that would re-hit 403",
        "MissAV 瀏覽器 HLS 在快取播放清單後失敗，已略過可能再次觸發 403 的網路播放清單回退",
    ),
    (
        "MissAV 浏览器 HLS 失败，跳过 N_m3u8DL-RE 前尝试 yt-dlp",
        "MissAV browser HLS failed; trying yt-dlp before skipping N_m3u8DL-RE",
        "MissAV 瀏覽器 HLS 失敗，略過 N_m3u8DL-RE 前嘗試 yt-dlp",
    ),
    (
        "N_m3u8DL-RE 失败，正在尝试 yt-dlp 模拟回退",
        "N_m3u8DL-RE failed; trying yt-dlp impersonation fallback",
        "N_m3u8DL-RE 失敗，正在嘗試 yt-dlp 模擬回退",
    ),
)

_EN_DYNAMIC_REPLACEMENTS = (
    ("已刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL successfully"),
    ("重新刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully"),
    ("重刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully"),
    ("B站 audio 流连接断开", "B-site audio stream disconnected"),
    ("B站 video 流连接断开", "B-site video stream disconnected"),
    ("Bilibili 爬虫任务结束", "Bilibili crawl task finished"),
    ("爬虫任务结束", "Crawl task finished"),
    ("爬虫发现可下载资源", "Crawler found downloadable resources"),
    ("检查 Bilibili 登录状态", "Checking Bilibili login status"),
    ("已登录，Cookie", "Logged in; Cookie"),
    ("下载任务开始执行", "Download task started"),
    ("下载任务完成", "Download task completed"),
    ("准备下载 Bilibili 音", "Preparing Bilibili audio download"),
    ("准备合并 Bilibili 音", "Preparing to merge Bilibili audio"),
    ("Bilibili 音视频合并", "Bilibili audio/video merge"),
    ("分发队列", "Dispatched queue"),
    ("释放下载", "Released download"),
)

_NON_EN_DYNAMIC_EXACT = {
    "fetch video detail": {
        "zh-CN": "获取视频详情",
        "zh-TW": "取得影片詳情",
    },
    "Download task has been queued": {
        "zh-CN": "下载任务已入队",
        "zh-TW": "下載任務已入隊",
    },
    "Dispatched queued task to a download worker": {
        "zh-CN": "已将排队任务分发给下载线程",
        "zh-TW": "已將排隊任務分發給下載執行緒",
    },
    "Released download concurrency slot": {
        "zh-CN": "已释放下载并发槽位",
        "zh-TW": "已釋放下載並發槽位",
    },
    "Download task started": {
        "zh-CN": "下载任务开始执行",
        "zh-TW": "下載任務開始執行",
    },
    "Download task completed": {
        "zh-CN": "下载任务完成",
        "zh-TW": "下載任務完成",
    },
    "Download task has been queued for execution": {
        "zh-CN": "下载任务已加入执行队列",
        "zh-TW": "下載任務已加入執行隊列",
    },
    "Frontend render exceeded the interactive budget; refresh cadence was relaxed": {
        "zh-CN": "前端渲染超过交互预算，已降低刷新频率",
        "zh-TW": "前端渲染超出互動預算；已降低刷新頻率",
    },
    "App initialization started": {
        "zh-CN": "应用开始初始化",
        "zh-TW": "應用開始初始化",
    },
    "Main window initialized": {
        "zh-CN": "主窗口初始化完成",
        "zh-TW": "主視窗初始化完成",
    },
    "Local media folder scan completed": {
        "zh-CN": "本地媒体目录扫描完成",
        "zh-TW": "本機媒體目錄掃描完成",
    },
    "Started scanning local media folder": {
        "zh-CN": "开始扫描本地媒体目录",
        "zh-TW": "開始掃描本機媒體目錄",
    },
    "Web started scanning local media folder": {
        "zh-CN": "Web 端开始扫描本地媒体目录",
        "zh-TW": "Web 端開始掃描本機媒體目錄",
    },
    "Web started scanning local media folder (async)": {
        "zh-CN": "Web 端开始扫描本地媒体目录（异步）",
        "zh-TW": "Web 端開始掃描本機媒體目錄（非同步）",
    },
    "Clear queue failed": {
        "zh-CN": "清空队列失败",
        "zh-TW": "清空隊列失敗",
    },
    "setting update failed": {
        "zh-CN": "设置更新失败",
        "zh-TW": "設定更新失敗",
    },
    "download options update failed": {
        "zh-CN": "下载选项更新失败",
        "zh-TW": "下載選項更新失敗",
    },
    "download paused": {
        "zh-CN": "下载已暂停",
        "zh-TW": "下載已暫停",
    },
}

_BILIBILI_ROUTE_ALIASES = {
    "direct BV video": {
        "zh-CN": "直接 BV 视频",
        "zh-TW": "直接 BV 影片",
    },
    "direct BV video with search fallback": {
        "zh-CN": "直接 BV 视频，失败后回退搜索",
        "zh-TW": "直接 BV 影片，失敗後回退搜尋",
    },
    "direct av video": {
        "zh-CN": "直接 av 视频",
        "zh-TW": "直接 av 影片",
    },
    "keyword search": {
        "zh-CN": "关键词搜索",
        "zh-TW": "關鍵字搜尋",
    },
}

_STRUCTURED_SEGMENT_ALIASES = {
    "System": {"zh-CN": "系统", "en-US": "System", "zh-TW": "系統"},
    "系统": {"en-US": "System", "zh-TW": "系統"},
    "系統": {"zh-CN": "系统", "en-US": "System"},
    "MainWindow": {"zh-CN": "主窗口", "en-US": "MainWindow", "zh-TW": "主視窗"},
    "主窗口": {"en-US": "MainWindow", "zh-TW": "主視窗"},
    "主視窗": {"zh-CN": "主窗口", "en-US": "MainWindow"},
    "ApplicationContext": {"zh-CN": "应用上下文", "en-US": "ApplicationContext", "zh-TW": "應用上下文"},
    "应用上下文": {"en-US": "ApplicationContext", "zh-TW": "應用上下文"},
    "應用上下文": {"zh-CN": "应用上下文", "en-US": "ApplicationContext"},
    "ApplicationController": {"zh-CN": "应用控制器", "en-US": "ApplicationController", "zh-TW": "應用控制器"},
    "应用控制器": {"en-US": "ApplicationController", "zh-TW": "應用控制器"},
    "應用控制器": {"zh-CN": "应用控制器", "en-US": "ApplicationController"},
    "DownloadManager": {"zh-CN": "下载管理器", "en-US": "DownloadManager", "zh-TW": "下載管理器"},
    "下载管理器": {"en-US": "DownloadManager", "zh-TW": "下載管理器"},
    "下載管理器": {"zh-CN": "下载管理器", "en-US": "DownloadManager"},
    "DownloadWorker": {"zh-CN": "下载线程", "en-US": "DownloadWorker", "zh-TW": "下載執行緒"},
    "下载线程": {"en-US": "DownloadWorker", "zh-TW": "下載執行緒"},
    "下載執行緒": {"zh-CN": "下载线程", "en-US": "DownloadWorker"},
    "Downloader": {"zh-CN": "下载器", "en-US": "Downloader", "zh-TW": "下載器"},
    "下载器": {"en-US": "Downloader", "zh-TW": "下載器"},
    "下載器": {"zh-CN": "下载器", "en-US": "Downloader"},
    "BilibiliDownloader": {"zh-CN": "Bilibili 下载器", "en-US": "BilibiliDownloader", "zh-TW": "Bilibili 下載器"},
    "DouyinDownloader": {"zh-CN": "抖音下载器", "en-US": "DouyinDownloader", "zh-TW": "抖音下載器"},
    "KuaishouDownloader": {"zh-CN": "快手下载器", "en-US": "KuaishouDownloader", "zh-TW": "快手下載器"},
    "XiaohongshuDownloader": {"zh-CN": "小红书下载器", "en-US": "XiaohongshuDownloader", "zh-TW": "小紅書下載器"},
    "MissAVDownloader": {"zh-CN": "MissAV 下载器", "en-US": "MissAVDownloader", "zh-TW": "MissAV 下載器"},
    "N_m3u8DL_RE_Downloader": {
        "zh-CN": "N_m3u8DL-RE 下载器",
        "en-US": "N_m3u8DL_RE_Downloader",
        "zh-TW": "N_m3u8DL-RE 下載器",
    },
    "FFmpegDownloader": {"zh-CN": "FFmpeg 下载器", "en-US": "FFmpegDownloader", "zh-TW": "FFmpeg 下載器"},
    "ChunkedDownloader": {"zh-CN": "分块下载器", "en-US": "ChunkedDownloader", "zh-TW": "分塊下載器"},
    "FrontendStateService": {"zh-CN": "前端状态服务", "en-US": "FrontendStateService", "zh-TW": "前端狀態服務"},
    "AppState": {"zh-CN": "应用状态", "en-US": "AppState", "zh-TW": "應用狀態"},
    "MediaMetadataService": {"zh-CN": "媒体元数据服务", "en-US": "MediaMetadataService", "zh-TW": "媒體中繼資料服務"},
    "WebUI": {"zh-CN": "网页端", "en-US": "WebUI", "zh-TW": "網頁端"},
    "网页端": {"en-US": "WebUI", "zh-TW": "網頁端"},
    "網頁端": {"zh-CN": "网页端", "en-US": "WebUI"},
}

_EVENT_CODE_SEGMENT_ALIASES = {
    "GUI": "图形界面",
    "WebUI": "网页端",
    "MainWindow": "主窗口",
    "ApplicationContext": "应用上下文",
}

_MEDIA_TERM_ALIASES = {
    "audio/video stream": {"zh-CN": "音视频流", "zh-TW": "音視訊流"},
    "audio": {"zh-CN": "音频", "zh-TW": "音訊"},
    "video": {"zh-CN": "视频", "zh-TW": "影片"},
}


def _plural(value: str, singular: str, plural: str) -> str:
    return singular if str(value) == "1" else plural


def _runtime_platform_name(value: str, language: str) -> str:
    text = str(value or "").strip()
    return platform_display_name("", language, fallback=text) if text else text


def _runtime_subject(prefix: str, platform: str, suffix: str) -> str:
    padded = bool(re.search(r"[A-Za-z0-9]$", platform) or re.search(r"^[A-Za-z0-9]", platform))
    return f"{prefix} {platform} {suffix}" if padded else f"{prefix}{platform}{suffix}"


def _localized_media_term(value: str, language: str) -> str:
    text = str(value or "").strip()
    return _localized(_MEDIA_TERM_ALIASES.get(text, {}), language) or text


def _localize_english_dynamic(text: str) -> str:
    match = _LOCAL_FILE_LOADED_RE.match(text)
    if match:
        count = match.group("count")
        noun = _plural(count, "file", "files")
        return (
            f"{match.group('prefix') or ''}Loaded {count} local {noun} "
            f"(videos: {match.group('videos')}, images: {match.group('images')})"
        )

    match = _SCAN_DIR_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Scanning directory: {match.group('path')}"

    match = _DOWNLOAD_DONE_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Download completed: {match.group('title')}"

    match = _DOWNLOAD_FAILED_RE.match(text)
    if match:
        error = _apply_runtime_phrase_translations(match.group("error"), "en-US")
        error = _localize_english_dynamic(error)
        return f"{match.group('prefix') or ''}Download failed [{match.group('title')}]: {error}"

    match = _CRAWL_CONFIRM_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}User confirmed {match.group('count')} tasks"

    match = _CRAWL_FINAL_CONFIRM_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Final confirmation: {match.group('count')} tasks"

    match = _CRAWL_START_RE.match(text)
    if match:
        platform = _runtime_platform_name(match.group("platform"), "en-US")
        return f"{match.group('prefix') or ''}Started {platform} crawl task"

    match = _TASK_START_TARGET_RE.match(text)
    if match:
        platform = _runtime_platform_name(match.group("platform"), "en-US")
        return f"{match.group('prefix') or ''}Started {platform} task | target: {match.group('target')}"

    match = _TASK_START_MODE_KEYWORD_RE.match(text)
    if match:
        return (
            f"{match.group('prefix') or ''}Started task | mode: {match.group('mode')} "
            f"| keyword: {match.group('keyword')}"
        )

    match = _TASK_START_MODE_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Started task | mode: {match.group('mode')}"

    match = _SCAN_FINISH_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Scan finished, total {match.group('count')}{match.group('tail')}"

    match = _FETCH_OK_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Fetched successfully {match.group('detail')}".rstrip()

    match = _PARSE_STREAM_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Parsed stream: {match.group('detail')}"

    match = _EXPANDING_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Expanding: {match.group('detail')}"

    match = _PIPELINE_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Pipeline established: {match.group('detail')}"

    match = _ALL_COMPLETED_RE.match(text)
    if match:
        return (
            f"{match.group('prefix') or ''}All completed: success "
            f"{match.group('success')}/{match.group('total')} | failed {match.group('failed')}"
        )

    result = text
    for source, target in _EN_DYNAMIC_REPLACEMENTS:
        result = result.replace(source, target)
    return result


def _localized(language_map: dict[str, str], language: str) -> str:
    return language_map.get(language) or language_map.get("zh-CN") or ""


def _apply_runtime_phrase_translations(text: str, language: str) -> str:
    target_index = {"zh-CN": 0, "en-US": 1, "zh-TW": 2}.get(language, 0)
    replacements: list[tuple[str, str]] = []
    for entry in _RUNTIME_LOG_PHRASE_TRANSLATIONS:
        target = entry[target_index] or entry[0]
        for source in entry:
            if source and source != target:
                replacements.append((source, target))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    result = text
    for source, target in replacements:
        result = result.replace(source, target)
    return result


def _localize_structured_segments(text: str, language: str) -> str:
    if " · " not in text and " / " not in text:
        mapped = _STRUCTURED_SEGMENT_ALIASES.get(text)
        if mapped:
            return _localized(mapped, language) or text
        return text
    parts = re.split(r"(\s+·\s+|\s+/\s+)", text)
    changed = False
    translated_parts: list[str] = []
    for part in parts:
        if re.fullmatch(r"\s*(?:·|/)\s*", part):
            translated_parts.append(part)
            continue
        translated = tr(part, language)
        mapped = _STRUCTURED_SEGMENT_ALIASES.get(part)
        if mapped:
            translated = _localized(mapped, language) or translated
        changed = changed or translated != part
        translated_parts.append(translated)
    return "".join(translated_parts) if changed else text


def _localize_non_english_dynamic(text: str, language: str) -> str:
    mapped = _NON_EN_DYNAMIC_EXACT.get(text)
    if mapped:
        return _localized(mapped, language)

    match = re.match(r"^Bilibili route:\s*(?P<route>.+)$", text)
    if match:
        route = match.group("route").strip()
        browser_scan = re.match(r"^browser scan\s*(?P<target>.*)$", route)
        if browser_scan:
            target = browser_scan.group("target").strip()
            prefix = "Bilibili 路由：浏览器扫描" if language == "zh-CN" else "Bilibili 路由：瀏覽器掃描"
            return f"{prefix} {target}".rstrip()
        route_label = _BILIBILI_ROUTE_ALIASES.get(route)
        if route_label:
            return f"Bilibili 路由：{_localized(route_label, language)}"

    match = re.match(r"^Bilibili browser producer error:\s*(?P<error>.+)$", text)
    if match:
        prefix = "Bilibili 浏览器生产线程异常" if language == "zh-CN" else "Bilibili 瀏覽器生產執行緒異常"
        return f"{prefix}：{match.group('error')}"

    match = re.match(r"^Download completed:\s*(?P<title>.+)$", text)
    if match:
        prefix = "下载完成" if language == "zh-CN" else "下載完成"
        return f"{prefix}：{match.group('title')}"

    match = re.match(r"^Download failed\s*\[(?P<title>.+?)\]:\s*(?P<error>.+)$", text)
    if match:
        prefix = "下载失败" if language == "zh-CN" else "下載失敗"
        return f"{prefix} [{match.group('title')}]：{match.group('error')}"

    match = re.match(r"^Started\s*(?P<platform>.*?)\s*crawl task$", text)
    if match:
        prefix = "启动" if language == "zh-CN" else "啟動"
        suffix = "爬虫任务" if language == "zh-CN" else "爬蟲任務"
        return _runtime_subject(prefix, _runtime_platform_name(match.group("platform"), language), suffix)

    match = re.match(r"^Started\s*(?P<platform>.*?)\s*task\s*\|\s*target:\s*(?P<target>.*)$", text)
    if match:
        prefix = "启动" if language == "zh-CN" else "啟動"
        task = "任务" if language == "zh-CN" else "任務"
        target = "目标" if language == "zh-CN" else "目標"
        subject = _runtime_subject(prefix, _runtime_platform_name(match.group("platform"), language), task)
        return f"{subject} | {target}：{match.group('target')}"

    match = re.match(r"^Started task\s*\|\s*mode:\s*(?P<mode>.*?)\s*\|\s*keyword:\s*(?P<keyword>.*)$", text)
    if match:
        start = "启动任务" if language == "zh-CN" else "啟動任務"
        keyword = "关键词" if language == "zh-CN" else "關鍵字"
        return f"{start} | 模式：{match.group('mode')} | {keyword}：{match.group('keyword')}"

    match = re.match(r"^Final confirmation:\s*(?P<count>\d+)\s*tasks?$", text)
    if match:
        label = "最终确认" if language == "zh-CN" else "最終確認"
        unit = "个任务" if language == "zh-CN" else "個任務"
        return f"{label} {match.group('count')} {unit}"

    match = re.match(r"^Fetched successfully\s*(?P<detail>.*)$", text)
    if match:
        label = "获取成功" if language == "zh-CN" else "取得成功"
        return f"{label} {match.group('detail')}".rstrip()

    match = re.match(r"^Parsed stream:\s*(?P<detail>.*)$", text)
    if match:
        label = "解析流" if language == "zh-CN" else "解析串流"
        return f"{label}：{match.group('detail')}"

    match = re.match(r"^Pipeline established:\s*(?P<detail>.*)$", text)
    if match:
        label = "流水线已建立" if language == "zh-CN" else "流水線已建立"
        return f"{label}：{match.group('detail')}"

    match = re.match(r"^Scan finished,\s*total\s*(?P<count>\d+)(?P<tail>.*)$", text)
    if match:
        label = "扫描结束，共" if language == "zh-CN" else "掃描結束，共"
        return f"{label} {match.group('count')}{match.group('tail')}"

    match = re.match(r"^All completed:\s*success\s*(?P<success>\d+)\s*/\s*(?P<total>\d+)\s*\|\s*failed\s*(?P<failed>\d+)$", text, re.IGNORECASE)
    if match:
        failed = "失败" if language == "zh-CN" else "失敗"
        return f"全部完成：成功 {match.group('success')}/{match.group('total')} | {failed} {match.group('failed')}"

    match = re.match(r"^Preparing Bilibili\s*(?P<media>.*?)\s*download$", text)
    if match:
        label = "准备下载" if language == "zh-CN" else "準備下載"
        return f"{label} Bilibili {_localized_media_term(match.group('media'), language)}"

    match = re.match(r"^Preparing to merge Bilibili\s*(?P<media>.*)$", text)
    if match:
        label = "准备合并" if language == "zh-CN" else "準備合併"
        return f"{label} Bilibili {_localized_media_term(match.group('media'), language)}"

    match = re.match(r"^XiaoHongShu user confirmed\s*(?P<count>\d+)\s*candidates; starting parse-to-download pipeline\.$", text)
    if match:
        count = match.group("count")
        return (
            f"小红书用户已确认 {count} 个候选，开始解析到下载流水线。"
            if language == "zh-CN"
            else f"小紅書使用者已確認 {count} 個候選，開始解析到下載流水線。"
        )

    match = re.match(r"^XiaoHongShu found\s*(?P<count>\d+)\s*candidates; waiting for user confirmation before parsing details\.$", text)
    if match:
        count = match.group("count")
        return (
            f"小红书发现 {count} 个候选，等待用户确认后解析详情。"
            if language == "zh-CN"
            else f"小紅書發現 {count} 個候選，等待使用者確認後解析詳情。"
        )

    match = re.match(r"^XiaoHongShu confirmed pipeline is active:\s*(?P<count>\d+)\s*selected candidates\.$", text)
    if match:
        count = match.group("count")
        return (
            f"小红书流水线已激活：{count} 个已选候选。"
            if language == "zh-CN"
            else f"小紅書流水線已啟用：{count} 個已選候選。"
        )

    return text


def localize_log_text(text: object, language: str | None) -> str:
    value = str(text or "")
    if not value:
        return value
    normalized = normalize_language(language)
    translated = tr(value, normalized)
    if translated != value:
        return translated
    structured = _localize_structured_segments(value, normalized)
    if structured != value:
        return structured
    phrase = _apply_runtime_phrase_translations(value, normalized)
    if phrase != value:
        if normalized == "en-US":
            return _localize_english_dynamic(phrase)
        dynamic = _localize_non_english_dynamic(phrase, normalized)
        return dynamic
    if normalized == "en-US":
        return _localize_english_dynamic(value)
    return _localize_non_english_dynamic(value, normalized)


def localize_log_event_code(code: object, language: str | None) -> str:
    value = str(code or "")
    normalized = normalize_language(language)
    if not value or value == "-":
        return value
    if normalized != "en-US":
        if normalized == "zh-TW" and "_" in value:
            return "_".join(
                localize_log_text(_EVENT_CODE_SEGMENT_ALIASES.get(part, part), normalized)
                for part in value.split("_")
            )
        return localize_log_text(value, normalized)

    loaded = re.match(
        r"^(?P<prefix>[A-Z0-9_]+)_已加载_(?P<count>\d+)_个本地文件_视频_(?P<videos>\d+)_图片_(?P<images>\d+)$",
        value,
    )
    if loaded:
        return (
            f"{loaded.group('prefix')}_LOADED_{loaded.group('count')}_LOCAL_FILES"
            f"_VIDEOS_{loaded.group('videos')}_IMAGES_{loaded.group('images')}"
        )

    replacements = {
        "日志缓存已刷新": "LOG_CACHE_REFRESHED",
        "正在扫描目录": "SCANNING_DIRECTORY",
        "开始扫描本地媒体目录": "LOCAL_MEDIA_SCAN_START",
        "本地媒体目录扫描完成": "LOCAL_MEDIA_SCAN_OK",
        "主窗口初始化完成": "MAIN_WINDOW_READY",
        "应用开始初始化": "APP_INIT",
        "已切换到浅色主题": "THEME_LIGHT",
        "已切换到深色主题": "THEME_DARK",
        "爬虫任务结束": "CRAWL_FINISH",
    }
    result = value
    for source, target in replacements.items():
        result = result.replace(source, target)
    result = re.sub(r"[^A-Za-z0-9_]+", "_", result)
    result = re.sub(r"_+", "_", result).strip("_")
    return result.upper() if result else value


def localize_log_payload(payload: Any, language: str | None) -> Any:
    if isinstance(payload, dict):
        localized: dict[Any, Any] = {}
        for key, value in payload.items():
            if str(key) in {"status_code", "event_code"}:
                localized[key] = localize_log_event_code(value, language)
            else:
                localized[key] = localize_log_payload(value, language)
        return localized
    if isinstance(payload, list):
        return [localize_log_payload(value, language) for value in payload]
    if isinstance(payload, tuple):
        return tuple(localize_log_payload(value, language) for value in payload)
    if isinstance(payload, str):
        return localize_log_text(payload, language)
    return payload
