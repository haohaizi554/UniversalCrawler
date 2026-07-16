"""运行时日志文本、事件码与结构化 payload 的展示本地化。

文本入口接受任意可转为字符串的值；payload 入口递归保留容器形状和键。处理链
按乱码修复、静态翻译、结构化片段、长短语、动态首命中规则和英文清理执行。
各阶段的输入依赖前一阶段输出，具体正则也从窄到宽排列，不可随意换序。没有
对应规则时保留原文本；空值、``-`` 事件码和非字符串 payload 值按各入口契约
原样返回。
"""

from __future__ import annotations

import re
from typing import Any

from shared.localization import normalize_language, platform_display_name, tr


_EMOJI_PREFIX_PATTERN = r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2139\ufe0e\ufe0f]*"
_LOCAL_FILE_LOADED_RE = re.compile(
    rf"^(?P<prefix>{_EMOJI_PREFIX_PATTERN}\s*)?"
    r"已加载\s*(?P<count>\d+)\s*个本地文件\s*"
    r"\(视频[:：]\s*(?P<videos>\d+)\s*,\s*图片[:：]\s*(?P<images>\d+)\)$"
)
_SCAN_DIR_RE = re.compile(
    rf"^(?P<prefix>{_EMOJI_PREFIX_PATTERN}\s*)?"
    r"正在扫描目录[:：]\s*(?P<path>.+)$"
)
_DOWNLOAD_DONE_RE = re.compile(rf"^(?P<prefix>{_EMOJI_PREFIX_PATTERN}\s*)?下载完成[:：]\s*(?P<title>.+)$")
_DOWNLOAD_FAILED_RE = re.compile(
    rf"^(?P<prefix>{_EMOJI_PREFIX_PATTERN}\s*)?"
    r"下载失败\s*\[(?P<title>.+?)\][：:]\s*(?P<error>.+)$"
)
_DYNAMIC_PREFIX = rf"(?P<prefix>{_EMOJI_PREFIX_PATTERN}\s*)?"
_CONFIG_NOT_LOGGED_RE = re.compile(
    rf"^{_DYNAMIC_PREFIX}配置文件\s+(?P<key>[\w.-]+)\s+参数未登录[，,]\s*数据获取已提前结束$"
)
_CONFIG_NOT_SET_RE = re.compile(
    rf"^{_DYNAMIC_PREFIX}配置文件\s+(?P<key>[\w.-]+)\s+参数未设置[，,]\s*"
    r"(?P<platform>[A-Za-z0-9_.-]+|[\u4e00-\u9fff]+)\s*平台功能可能无法正常使用$"
)
_PARAM_UPDATED_RE = re.compile(
    rf"^{_DYNAMIC_PREFIX}(?P<platform>Douyin|douyin|抖音|TikTok|tiktok)\s*参数更新完毕[!！]?$"
)
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
    rf"^{_DYNAMIC_PREFIX}全部完成[:：]\s*(?:成功|success)\s*(?P<success>\d+)\s*/\s*(?P<total>\d+)\s*\|\s*(?:失败|failed)\s*(?P<failed>\d+)$",
    re.IGNORECASE,
)
_MOJIBAKE_REPAIR_PHRASES = (
    "下载失败",
    "下载任务失败",
    "下载任务完成",
    "应用开始初始化",
    "主窗口初始化完成",
    "用户停止下载",
    "小红书图片下载失败",
    "视频数",
)


def _build_mojibake_repair_map() -> dict[str, str]:
    repair_map: dict[str, str] = {}
    for phrase in _MOJIBAKE_REPAIR_PHRASES:
        for encoding in ("gbk", "gb18030", "cp936"):
            damaged = phrase.encode("utf-8").decode(encoding, errors="replace")
            if damaged and damaged != phrase:
                repair_map[damaged] = phrase
                repair_map[damaged.replace("\ufffd", "?")] = phrase
    return repair_map


_MOJIBAKE_REPAIR_MAP = _build_mojibake_repair_map()


def _repair_mojibake_text(text: str) -> str:
    """修复已知 UTF-8/中文编码误解码短语，未知内容保持不变。"""
    repaired = text
    for damaged, phrase in _MOJIBAKE_REPAIR_MAP.items():
        if damaged in repaired:
            repaired = repaired.replace(damaged, phrase)
    return repaired

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
    ("下载任务失败", "Download task failed", "下載任務失敗"),
    ("UI 回调失败", "ui callback failed", "UI 回調失敗"),
    ("回调失败", "callback failed", "回調失敗"),
    ("下载任务被用户停止", "Download task stopped by user", "下載任務被使用者停止"),
    ("下载完成后已按文件签名修正扩展名", "Fixed extension after download by file signature", "下載完成後已依檔案簽章修正副檔名"),
    ("分块下载不可用，回退到后续下载策略", "Chunked download unavailable; falling back to later download strategy", "分塊下載不可用，回退到後續策略"),
    ("下载策略执行失败，回退到后续策略", "Download strategy failed; falling back to later strategy", "下載策略執行失敗，回退到後續策略"),
    ("抖音下载任务已提交到下载队列", "Douyin download task submitted to the queue", "抖音下載任務已提交到下載佇列"),
    ("启动抖音爬虫任务", "Started Douyin crawl task", "啟動抖音爬蟲任務"),
    ("抖音爬虫任务结束", "Douyin crawl task finished", "抖音爬蟲任務結束"),
    ("抖音爬虫运行异常", "Douyin crawl runtime error", "抖音爬蟲執行異常"),
    ("进入抖音任务提交阶段", "Entered Douyin task submit stage", "進入抖音任務提交階段"),
    ("Douyin 参数初始化完成", "Douyin parameters initialized", "Douyin 參數初始化完成", "Douyin参数初始化完成"),
    ("正在更新抖音参数，请稍等...", "Updating Douyin parameters, please wait...", "正在更新抖音參數，請稍候..."),
    (
        "抖音参数更新完毕！",
        "Douyin parameters updated!",
        "抖音參數更新完成！",
        "Douyin 参数更新完毕！",
        "Douyin 参数更新完毕",
        "Douyin参数更新完毕！",
        "Douyin参数更新完毕!",
        "Douyin参数更新完毕",
    ),
    (
        "TikTok 参数更新完毕！",
        "TikTok parameters updated!",
        "TikTok 參數更新完成！",
        "TikTok参数更新完毕！",
        "TikTok参数更新完毕!",
        "TikTok参数更新完毕",
    ),
    (
        "配置文件 cookie 参数未登录，数据获取已提前结束",
        "Config cookie is not logged in; data fetching ended early",
        "設定檔 cookie 參數未登入，資料取得已提前結束",
    ),
    (
        "配置文件 cookie 参数未设置，抖音平台功能可能无法正常使用",
        "Config cookie is not set; Douyin features may not work properly",
        "設定檔 cookie 參數未設定，抖音平台功能可能無法正常使用",
    ),
    (
        "配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
        "Config cookie_tiktok is not set; TikTok features may not work properly",
        "設定檔 cookie_tiktok 參數未設定，TikTok 平台功能可能無法正常使用",
    ),
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
    (
        "优先尝试通过 HTTP 快速解析快手分享详情...",
        "Trying fast HTTP parsing for Kuaishou share details first...",
        "優先嘗試透過 HTTP 快速解析快手分享詳情...",
    ),
    (
        "正在从快手分享详情页捕获单条作品...",
        "Capturing a single item from the Kuaishou share detail page...",
        "正在從快手分享詳情頁擷取單項作品...",
    ),
    (
        "检测到快手分享/详情链接，使用静默单资源解析流程",
        "Kuaishou share/detail link detected; using the silent single-resource parsing flow",
        "偵測到快手分享/詳情連結，使用靜默單資源解析流程",
    ),
    (
        "HTTP 未获得视频直链，切换无头浏览器继续解析",
        "HTTP did not return a direct video URL; switching to a headless browser to continue parsing",
        "HTTP 未取得影片直連，切換無頭瀏覽器繼續解析",
    ),
    ("页面访问第 ", "Page navigation load attempt ", "頁面造訪載入嘗試 "),
    ("打开快手搜索页第 ", "Opening the Kuaishou search page, load attempt ", "開啟快手搜尋頁載入嘗試 "),
    ("打开快手目标页第 ", "Opening the Kuaishou target page, load attempt ", "開啟快手目標頁載入嘗試 "),
    (" 次加载返回网络错误页", " returned a network error page", " 次載入傳回網路錯誤頁"),
    (
        "快手服务端判定本地登录态无效，需要重新登录",
        "The Kuaishou service rejected the local login state; log in again",
        "快手服務端判定本機登入狀態無效，需要重新登入",
    ),
    (
        "快手页面连续加载失败，已停止本次登录等待；请稍后重试",
        "The Kuaishou page repeatedly failed to load; login waiting stopped; try again later",
        "快手頁面連續載入失敗，已停止本次登入等待；請稍後重試",
    ),
    ("启动小红书爬虫任务", "Started Xiaohongshu crawl task", "啟動小紅書爬蟲任務"),
    ("小红书爬虫运行异常", "Xiaohongshu crawl runtime error", "小紅書爬蟲執行異常"),
    ("小红书爬虫任务结束", "Xiaohongshu crawl task finished", "小紅書爬蟲任務結束"),
    ("小红书视频下载失败", "Xiaohongshu video download failed", "小紅書影片下載失敗"),
    ("MissAV m3u8 嗅探成功并提交下载", "MissAV m3u8 sniffed successfully and submitted for download", "MissAV m3u8 嗅探成功並提交下載"),
    ("MissAV 详情页嗅探超时，未发现 playlist.m3u8", "MissAV detail page sniff timed out; playlist.m3u8 was not found", "MissAV 詳情頁嗅探逾時，未發現 playlist.m3u8"),
    ("MissAV 详情页加载失败", "MissAV detail page failed to load", "MissAV 詳情頁載入失敗"),
    (
        "未找到可用的系统 Chrome/Edge，改用内置浏览器",
        "No usable system Chrome/Edge was found; using the bundled browser",
        "未找到可用的系統 Chrome/Edge，改用內建瀏覽器",
    ),
    (
        "Cloudflare 可能拒绝过旧内核",
        "Cloudflare may reject an outdated browser engine",
        "Cloudflare 可能拒絕過舊核心",
    ),
    (
        "Cloudflare 不支持当前浏览器环境，请更新系统 Chrome/Edge 后重试",
        "Cloudflare does not support the current browser environment; update system Chrome/Edge and try again",
        "Cloudflare 不支援目前瀏覽器環境，請更新系統 Chrome/Edge 後重試",
    ),
    (
        "检测到 Cloudflare，请在浏览器中完成人工验证...",
        "Cloudflare detected; complete the manual verification in the browser...",
        "偵測到 Cloudflare，請在瀏覽器中完成人工驗證...",
    ),
    ("Cloudflare 验证已通过", "Cloudflare verification passed", "Cloudflare 驗證已通過"),
    ("Cloudflare 验证等待超时", "Cloudflare verification timed out", "Cloudflare 驗證等待逾時"),
    (
        "MissAV 人工验证使用系统",
        "MissAV manual verification is using system",
        "MissAV 人工驗證使用系統",
    ),
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
    ("仅下载视频模式已跳过非视频资源", "Video-only mode skipped non-video resource", "僅下載影片模式已略過非影片資源"),
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
    (
        "Web 事件循环不可用，已延后前端增量刷新",
        "Web event loop is unavailable; deferred frontend delta until a later async flush.",
        "Web 事件迴圈不可用，已延後前端增量刷新",
    ),
    (
        "没有可用事件循环，已跳过前端增量刷新",
        "Skipped frontend delta flush because no running event loop is available.",
        "沒有可用事件迴圈，已略過前端增量刷新",
    ),
    ("默认打开方式已生效", "Default open mode is active", "預設開啟方式已生效"),
    ("未选择需要注册的资源类型", "No resource type selected for registration", "未選擇需要註冊的資源類型"),
    ("文件关联注册未完成", "File association registration was not completed", "檔案關聯註冊未完成"),
    ("已设置默认打开方式", "Default open mode has been set", "已設定預設開啟方式"),
    ("部分默认打开方式设置失败", "Some default open mode settings failed", "部分預設開啟方式設定失敗"),
    ("仍需在 Windows 默认应用中确认", "Still needs confirmation in Windows Default Apps", "仍需在 Windows 預設應用程式中確認"),
    (
        "已打开 Windows 默认应用设置，请手动确认剩余默认打开方式",
        "Opened Windows Default Apps settings; please confirm the remaining default open modes manually",
        "已開啟 Windows 預設應用程式設定，請手動確認剩餘預設開啟方式",
    ),
    (
        "请手动打开 Windows 默认应用设置，确认剩余默认打开方式",
        "Please open Windows Default Apps settings manually and confirm the remaining default open modes",
        "請手動開啟 Windows 預設應用程式設定，確認剩餘預設開啟方式",
    ),
    ("自动打开下载结果失败", "Failed to open the downloaded result automatically", "自動開啟下載結果失敗"),
    ("上次任务未正常结束，正在清理", "The previous task did not end cleanly; cleaning up", "上次任務未正常結束，正在清理"),
    ("当前已有任务在运行，请先停止或等待结束", "A task is already running; stop it or wait for it to finish first", "目前已有任務執行中，請先停止或等待結束"),
    ("未知的爬虫源", "Unknown crawler source", "未知的爬蟲來源"),
    ("创建爬虫失败", "Failed to create crawler", "建立爬蟲失敗"),
    ("启动爬虫失败", "Failed to start crawler", "啟動爬蟲失敗"),
    ("正在停止任务", "Stopping task", "正在停止任務"),
    ("扫描目录出错", "Directory scan failed", "掃描目錄出錯"),
    ("目录已变更", "Directory changed", "目錄已變更"),
    ("重命名失败", "Rename failed", "重新命名失敗"),
    ("删除文件失败", "File deletion failed", "刪除檔案失敗"),
    ("文件不存在或已被删除", "File does not exist or has been deleted", "檔案不存在或已被刪除"),
    ("播放:", "Playing:", "播放："),
    ("已清空下载队列", "Download queue cleared", "已清空下載佇列"),
    ("已删除", "Deleted", "已刪除"),
    ("已从下载队列移除，已省略逐条日志", "items were removed from the download queue; per-item logs were omitted", "項已從下載佇列移除，已省略逐條日誌"),
    ("已播放到最后一项", "Already at the last item", "已播放到最後一項"),
    ("队列为空，没有可切换的资源", "The queue is empty; there is no resource to switch to", "佇列為空，沒有可切換的資源"),
    ("清空队列失败", "Clear queue failed", "清空佇列失敗"),
    ("任务已终止", "Task terminated", "任務已終止"),
    ("浏览器已关闭，无法继续需要网页的操作", "Browser is closed; cannot continue operations that require a web page", "瀏覽器已關閉，無法繼續需要網頁的操作"),
    ("抓取已停止，已保留", "Crawl stopped; kept", "抓取已停止，已保留"),
    ("准备生成清单", "preparing to generate the list", "準備生成清單"),
    ("用户取消了任务", "User cancelled the task", "使用者取消了任務"),
    ("未选择有效平台", "No valid platform selected", "未選擇有效平台"),
    ("请先选择一个任务", "Please select a task first", "請先選擇一個任務"),
    ("配置读取错误", "Failed to read configuration", "設定讀取錯誤"),
    ("保存目录更新失败", "Failed to update save directory", "儲存目錄更新失敗"),
    ("任务清单对话框打开失败", "Failed to open the task list dialog", "任務清單對話框開啟失敗"),
    ("下载选项已更新", "Download options updated", "下載選項已更新"),
    ("下载选项更新失败", "download options update failed", "下載選項更新失敗"),
    ("save_dir 必须是字符串", "save_dir must be a string", "save_dir 必須是字串"),
    ("directory 必须是字符串", "directory must be a string", "directory 必須是字串"),
    ("目录路径不能为空", "Directory path cannot be empty", "目錄路徑不能為空"),
    ("dark_theme 必须是布尔值", "dark_theme must be a boolean", "dark_theme 必須是布林值"),
    ("source 必须是字符串", "source must be a string", "source 必須是字串"),
    ("section 和 key 必须是字符串", "section and key must be strings", "section 和 key 必須是字串"),
    ("video_id 必须是字符串", "video_id must be a string", "video_id 必須是字串"),
    ("video_id 和 new_title 必须是字符串", "video_id and new_title must be strings", "video_id 和 new_title 必須是字串"),
    ("frontend_action 参数非法", "Invalid frontend_action parameter", "frontend_action 參數不合法"),
    ("frontend action 不可用", "Frontend action is unavailable", "frontend action 不可用"),
    ("scan_limit 必须是整数", "scan_limit must be an integer", "scan_limit 必須是整數"),
    ("scan_limit 必须大于 0", "scan_limit must be greater than 0", "scan_limit 必須大於 0"),
    ("scan_limit 不能大于", "scan_limit cannot be greater than", "scan_limit 不能大於"),
    ("无效平台", "Invalid platform", "無效平台"),
    ("支持", "supported", "支援"),
    ("保存配置失败", "Failed to save configuration", "儲存設定失敗"),
    ("该配置项不允许通过 Web 修改", "This setting cannot be changed from the WebUI", "此設定不允許透過 WebUI 修改"),
    ("使用代理", "Using proxy", "使用代理"),
    ("爬虫错误", "Crawler error", "爬蟲錯誤"),
    ("加载本地 Cookie 成功", "Loaded local Cookie successfully", "載入本機 Cookie 成功"),
    ("本地 Cookie 加载失败", "Failed to load local Cookie", "本機 Cookie 載入失敗"),
    ("已加载本地 Cookie，尝试刷新页面重新校验登录态", "Loaded local Cookie; refreshing the page to re-check login status", "已載入本機 Cookie，嘗試重新整理頁面以重新校驗登入狀態"),
    ("本地 Cookie 已加载，但当前页面未识别为已登录，可能已失效", "Local Cookie was loaded, but the current page is not logged in and it may have expired", "本機 Cookie 已載入，但目前頁面未識別為已登入，可能已失效"),
    ("检测到登录状态", "Login status detected", "偵測到登入狀態"),
    ("刷新后检测到登录状态", "Login status detected after refresh", "重新整理後偵測到登入狀態"),
    ("登录成功，Cookie 已保存", "Login successful; Cookie saved", "登入成功，Cookie 已儲存"),
    ("已完成扫码登录", "QR-code login completed", "已完成掃碼登入"),
    ("扫码成功，Cookie 已保存", "QR-code login succeeded; Cookie saved", "掃碼成功，Cookie 已儲存"),
    ("未登录或 Cookie 失效，启动扫码", "Not logged in or Cookie expired; starting QR-code login", "未登入或 Cookie 失效，啟動掃碼"),
    ("请在当前快手页面手动登录或扫码，登录成功后程序会自动继续", "Please log in or scan the code on the current Kuaishou page; the program will continue automatically after login", "請在目前快手頁面手動登入或掃碼，登入成功後程式會自動繼續"),
    ("静默模式检测到快手登录态不可用，将打开登录窗口；登录后会重新静默执行当前任务", "Silent mode detected that Kuaishou login is unavailable; a login window will open and the task will rerun silently after login", "靜默模式偵測到快手登入狀態不可用，將開啟登入視窗；登入後會重新靜默執行目前任務"),
    ("正在打开快手登录窗口", "Opening Kuaishou login window", "正在開啟快手登入視窗"),
    ("已自动打开快手扫码登录弹窗", "Opened the Kuaishou QR-code login popup automatically", "已自動開啟快手掃碼登入彈窗"),
    ("未能自动弹出登录框，请直接在当前快手页面手动登录", "Could not open the login popup automatically; please log in manually on the current Kuaishou page", "未能自動彈出登入框，請直接在目前快手頁面手動登入"),
    ("登录失败，以游客身份爬取", "Login failed; crawling as guest", "登入失敗，將以訪客身分抓取"),
    ("已切换到浅色主题", "Switched to light theme", "已切換到淺色主題"),
    ("已切换到深色主题", "Switched to dark theme", "已切換到深色主題"),
    ("该目录下没有找到视频或图片", "No videos or images found in this directory", "該目錄下沒有找到影片或圖片"),
    ("线程未在", "thread did not exit within", "執行緒未在"),
    ("跳过继续收尾", "skipping and continuing cleanup", "略過並繼續收尾"),
    ("获取流失败", "Failed to fetch stream", "取得串流失敗"),
    ("未检测到登录，启动浏览器扫码", "Login not detected; starting browser QR-code login", "未偵測到登入，啟動瀏覽器掃碼"),
    ("爬虫已停止，跳过结果选择", "Crawler stopped; skipping result selection", "爬蟲已停止，略過結果選擇"),
    ("未找到任何有效视频", "No valid videos found", "未找到任何有效影片"),
    ("已达到视频数上限", "Reached the video count limit", "已達到影片數上限"),
    ("剩余选择不会进入下载队列", "remaining selections will not enter the download queue", "剩餘選擇不會進入下載佇列"),
    ("短链解析失败", "Short-link parsing failed", "短連結解析失敗"),
    ("短链解析", "Short-link parsing", "短連結解析"),
    ("Bilibili API 失败，尝试网页兜底扫描", "Bilibili API failed; trying web fallback scan", "Bilibili API 失敗，嘗試網頁兜底掃描"),
    ("Bilibili 扫描 Cookie 恢复失败，继续匿名扫描", "Failed to restore Bilibili scan Cookie; continuing anonymous scan", "Bilibili 掃描 Cookie 恢復失敗，繼續匿名掃描"),
    ("静态搜索页", "static search page", "靜態搜尋頁"),
    ("扫描异常", "Scan error", "掃描異常"),
    ("请在弹出的窗口中扫码登录", "Please scan the QR code in the popup window", "請在彈出的視窗中掃碼登入"),
    ("登录状态校验失败，尝试继续执行", "Login status check failed; trying to continue", "登入狀態校驗失敗，嘗試繼續執行"),
    ("已按视频数上限", "Trimmed by video count limit", "已依影片數上限"),
    ("裁剪可选分集", "trimmed selectable episodes", "裁剪可選分集"),
    ("Bilibili 网页兜底解析失败", "Bilibili web fallback parsing failed", "Bilibili 網頁兜底解析失敗"),
    ("Bilibili 页面不可用，跳过浏览器候选扫描", "Bilibili page is unavailable, skip browser candidate scan", "Bilibili 頁面不可用，略過瀏覽器候選掃描"),
    ("Bilibili 静态搜索页解析失败", "Bilibili static search page parsing failed", "Bilibili 靜態搜尋頁解析失敗"),
    ("已聚合", "Aggregated", "已彙整"),
    ("有效资源", "valid resources", "有效資源"),
    ("停止继续抓取", "stopped further crawling", "停止繼續抓取"),
    ("检测到 UP 主", "Detected UP owner", "偵測到 UP 主"),
    ("视频信息解析失败", "Video info parsing failed", "影片資訊解析失敗"),
    ("API 处理异常", "API processing error", "API 處理異常"),
    ("Bilibili API 未返回可用视频信息", "Bilibili API did not return usable video information", "Bilibili API 未返回可用影片資訊"),
    ("仅保留前", "keeping only the first", "僅保留前"),
    ("供选择", "for selection", "供選擇"),
    ("检查本地 Cookie 文件", "Checking local Cookie file", "檢查本機 Cookie 檔案"),
    ("正在启动独立登录进程", "Starting independent login process", "正在啟動獨立登入程序"),
    ("Cookie 将保存到", "Cookie will be saved to", "Cookie 將儲存到"),
    ("登录失败详情", "Login failure details", "登入失敗詳情"),
    ("无法识别的链接格式", "Unrecognized link format", "無法識別的連結格式"),
    ("请使用以下格式", "Please use one of the following formats", "請使用以下格式"),
    ("用户主页链接", "User homepage link", "使用者主頁連結"),
    ("分享链接", "Share link", "分享連結"),
    ("识别到", "Detected", "識別到"),
    ("个作品 ID，开始获取详情", "work IDs; fetching details", "個作品 ID，開始取得詳情"),
    ("识别到用户 SecUID", "Detected user SecUID", "識別到使用者 SecUID"),
    ("开始爬取主页", "starting homepage crawl", "開始抓取主頁"),
    ("识别到合集 ID", "Detected collection ID", "識別到合集 ID"),
    ("搜索关键词", "Search keyword", "搜尋關鍵字"),
    ("正在搜索用户", "Searching user", "正在搜尋使用者"),
    ("用户搜索无结果，尝试其他方法", "User search returned no results; trying other methods", "使用者搜尋無結果，嘗試其他方法"),
    ("无法找到用户", "Could not find user", "無法找到使用者"),
    ("抖音纯数字 UID 无法直接搜索，请使用以下方式", "Douyin numeric UID cannot be searched directly; please use one of these methods", "抖音純數字 UID 無法直接搜尋，請使用以下方式"),
    ("输入用户主页链接", "Enter a user homepage link", "輸入使用者主頁連結"),
    ("输入用户昵称进行搜索", "Enter a user nickname to search", "輸入使用者暱稱進行搜尋"),
    ("在抖音 APP 中复制分享链接", "Copy the share link in the Douyin app", "在抖音 APP 中複製分享連結"),
    ("扫描完成，共", "Scan completed, total", "掃描完成，共"),
    ("请选择", "please select", "請選擇"),
    ("选中", "Selected", "已選擇"),
    ("无法获取 Cookie，任务终止", "Could not get Cookie; task terminated", "無法取得 Cookie，任務終止"),
    ("Cookie 文件不存在", "Cookie file does not exist", "Cookie 檔案不存在"),
    ("扫码登录成功", "QR-code login succeeded", "掃碼登入成功"),
    ("正在解析链接重定向", "Resolving link redirect", "正在解析連結重定向"),
    ("识别为可能的抖音号", "Detected possible Douyin ID", "識別為可能的抖音號"),
    ("尝试搜索", "trying search", "嘗試搜尋"),
    ("尝试将 modal_id", "Trying modal_id", "嘗試將 modal_id"),
    ("作为合集解析", "as a collection", "作為合集解析"),
    ("获取作品详情失败", "Failed to fetch work details", "取得作品詳情失敗"),
    ("正在获取第", "Fetching page", "正在取得第"),
    ("未找到公开作品", "No public works found", "未找到公開作品"),
    ("未找到作品或ID无效", "found no works or the ID is invalid", "未找到作品或 ID 無效"),
    ("搜索第", "Searching page", "搜尋第"),
    ("个匹配用户", "matching users", "個匹配使用者"),
    ("尝试作为 sec_user_id 访问", "Trying to access as sec_user_id", "嘗試以 sec_user_id 存取"),
    ("尝试请求用户主页获取 sec_user_id", "Trying to request the user homepage to get sec_user_id", "嘗試請求使用者主頁以取得 sec_user_id"),
    ("未找到有效视频", "No valid videos found", "未找到有效影片"),
    ("运行时异常", "Runtime error", "執行階段異常"),
    ("本地 Cookie 缺少 sessionid_ss，可能已过期", "Local Cookie is missing sessionid_ss and may have expired", "本機 Cookie 缺少 sessionid_ss，可能已過期"),
    ("登录成功但 Cookie 缺少 sessionid_ss", "Login succeeded but Cookie is missing sessionid_ss", "登入成功但 Cookie 缺少 sessionid_ss"),
    ("搜索异常", "Search error", "搜尋異常"),
    ("从 HTML 提取到 sec_user_id", "Extracted sec_user_id from HTML", "已從 HTML 提取 sec_user_id"),
    ("主页请求失败", "Homepage request failed", "主頁請求失敗"),
    ("Cookie 文件存在但内容为空", "Cookie file exists but is empty", "Cookie 檔案存在但內容為空"),
    ("登录成功但 Cookie 文件为空", "Login succeeded but the Cookie file is empty", "登入成功但 Cookie 檔案為空"),
    ("Cookie 读取成功，可以开始下载", "Cookie loaded; ready to download", "Cookie 讀取成功，可以開始下載"),
    ("登录态读取失败", "Failed to read login status", "登入狀態讀取失敗"),
    ("找到用户", "Found user", "找到使用者"),
    ("找到多个用户，请选择", "Found multiple users; please select", "找到多個使用者，請選擇"),
    ("用户取消选择", "User cancelled selection", "使用者取消選擇"),
    ("获取用户", "Fetching user", "取得使用者"),
    ("快手分享页未解析到 __APOLLO_STATE__ 视频直链，将回退浏览器链路", "Kuaishou share page did not yield a __APOLLO_STATE__ direct video URL; falling back to browser flow", "快手分享頁未解析到 __APOLLO_STATE__ 影片直連，將回退瀏覽器流程"),
    ("检测到快手分享/详情链接，优先尝试无浏览器直连解析", "Detected Kuaishou share/detail link; trying direct no-browser parsing first", "偵測到快手分享/詳情連結，優先嘗試無瀏覽器直連解析"),
    ("已无浏览器解析分享作品", "Parsed shared work without browser", "已無瀏覽器解析分享作品"),
    ("访问快手首页", "Visiting Kuaishou homepage", "造訪快手首頁"),
    ("访问快手页面", "Visiting Kuaishou page", "造訪快手頁面"),
    ("通过站内搜索查找", "Searching through site search", "透過站內搜尋查找"),
    ("无法执行快手关键词搜索", "Unable to run Kuaishou keyword search", "無法執行快手關鍵字搜尋"),
    ("未找到匹配的快手账号主页", "No matching Kuaishou account homepage found", "未找到匹配的快手帳號主頁"),
    ("检测到快手分享/详情链接，直接解析单条作品", "Detected Kuaishou share/detail link; parsing a single work directly", "偵測到快手分享/詳情連結，直接解析單條作品"),
    ("未能从快手分享链接中解析出可下载视频", "Could not parse a downloadable video from the Kuaishou share link", "未能從快手分享連結解析出可下載影片"),
    ("开始滚动加载列表", "Starting to scroll and load the list", "開始滾動載入列表"),
    ("点击【停止】生成清单", "click Stop to generate the list", "點擊【停止】生成清單"),
    ("解析视频信息", "Parsing video information", "解析影片資訊"),
    ("请选择下载", "please select downloads", "請選擇下載"),
    ("生产者工作开始", "Producer worker started", "生產者工作開始"),
    ("流程结束", "Flow finished", "流程結束"),
    ("未找到快手搜索框", "Kuaishou search box not found", "未找到快手搜尋框"),
    ("当前输入为纯数字，按快手号优先进入用户搜索结果", "Current input is numeric; prioritizing Kuaishou ID user search results", "目前輸入為純數字，優先按快手號進入使用者搜尋結果"),
    ("已解析分享作品", "Parsed shared work", "已解析分享作品"),
    ("无法加载视频列表", "Unable to load video list", "無法載入影片列表"),
    ("未扫描到有效视频", "No valid videos scanned", "未掃描到有效影片"),
    ("用户取消了下载任务", "User cancelled the download task", "使用者取消了下載任務"),
    ("详情页已关闭，无法启动捕获流水线", "Detail page is closed; cannot start capture pipeline", "詳情頁已關閉，無法啟動擷取流水線"),
    ("个视频未捕获", "videos were not captured", "個影片未擷取"),
    ("全部任务完成", "All tasks completed", "全部任務完成"),
    ("流水线启动", "pipeline started", "流水線啟動"),
    ("本地登录态加载失败，继续尝试页面登录", "Failed to load local login state; continuing with page login", "本機登入狀態載入失敗，繼續嘗試頁面登入"),
    ("加载本地登录态成功", "Loaded local login state successfully", "已成功載入本機登入狀態"),
    ("已保存登录态不兼容，改用空白浏览器上下文重新登录", "Saved login state is incompatible; signing in again with a clean browser context", "已儲存的登入狀態不相容，改用空白瀏覽器內容重新登入"),
    ("快手登录态保存失败", "Failed to save Kuaishou login state", "快手登入狀態儲存失敗"),
    ("快手分享详情页请求失败", "Kuaishou share detail page request failed", "快手分享詳情頁請求失敗"),
    ("首页访问或登录态检查失败，继续尝试在当前页面恢复登录", "Homepage access or login check failed; continuing to recover login on the current page", "首頁存取或登入狀態檢查失敗，繼續嘗試在目前頁面恢復登入"),
    ("无法执行快手站内搜索", "Unable to run Kuaishou site search", "無法執行快手站內搜尋"),
    ("点击搜索结果名字进入主页", "Clicking search result name to enter homepage", "點擊搜尋結果名稱進入主頁"),
    ("点击搜索结果头像进入主页", "Clicking search result avatar to enter homepage", "點擊搜尋結果頭像進入主頁"),
    ("点击用户卡片进入主页", "Clicking user card to enter homepage", "點擊使用者卡片進入主頁"),
    ("已加载全部视频", "Loaded all videos", "已載入全部影片"),
    ("加载中", "Loading", "載入中"),
    ("已扫描", "scanned", "已掃描"),
    ("无法进入详情页", "Unable to enter detail page", "無法進入詳情頁"),
    ("详情页已关闭，提前结束当前捕获流程", "Detail page is closed; ending current capture flow early", "詳情頁已關閉，提前結束目前擷取流程"),
    ("刷屏进度", "Swipe progress", "刷屏進度"),
    ("第", "page", "第"),
    ("次重试", "retry", "次重試"),
    ("已进入搜索结果视频列表", "Entered search result video list", "已進入搜尋結果影片列表"),
    ("已从搜索结果进入主页", "Entered homepage from search result", "已從搜尋結果進入主頁"),
    ("似乎卡住了，尝试回滚刷新", "Seems stuck; trying to scroll back and refresh", "似乎卡住了，嘗試回滾刷新"),
    ("所有任务已实时捕获，提前结束", "All tasks captured in real time; ending early", "所有任務已即時擷取，提前結束"),
    ("焦点匹配", "Focus match", "焦點匹配"),
    ("捕获", "Captured", "擷取"),
    ("加入下载队列", "added to download queue", "加入下載佇列"),
    ("快手登录完成，重新以静默模式执行当前任务", "Kuaishou login completed; rerunning the current task silently", "快手登入完成，重新以靜默模式執行目前任務"),
    ("加密流", "Encrypted stream", "加密串流"),
    ("匹配焦点", "matched focus", "匹配焦點"),
    ("按视频数上限裁剪", "Trimmed by video count limit", "依影片數上限裁剪"),
    ("偏好设置", "Preferences", "偏好設定"),
    ("单体", "single item", "單體"),
    ("优先级", "priority", "優先級"),
    ("扫描第", "Scanning page", "掃描第"),
    ("MissAV 输入已归一化", "MissAV input normalized", "MissAV 輸入已正規化"),
    ("构造搜索链接", "Building search link", "建構搜尋連結"),
    ("修正后 URL", "Corrected URL", "修正後 URL"),
    ("识别为单体视频链接", "Recognized as single-video link", "識別為單體影片連結"),
    ("识别为列表/分类链接", "Recognized as list/category link", "識別為列表/分類連結"),
    ("正在访问页面", "Visiting page", "正在造訪頁面"),
    ("个最佳版本", "best versions", "個最佳版本"),
    ("开始嗅探 m3u8", "starting m3u8 sniffing", "開始嗅探 m3u8"),
    ("停止翻页", "stopping pagination", "停止翻頁"),
    ("页面扫描异常", "Page scan error", "頁面掃描異常"),
    ("检测到 Cloudflare，等待通过", "Cloudflare detected; waiting to pass", "偵測到 Cloudflare，等待通過"),
    ("开始第一遍扫描", "Starting first scan", "開始第一輪掃描"),
    ("获取所有视频", "fetching all videos", "取得所有影片"),
    ("智能筛选中", "Smart filtering", "智慧篩選中"),
    ("候选", "candidates", "候選"),
    ("筛选后无有效结果", "No valid results after filtering", "篩選後無有效結果"),
    ("嗅探", "Sniffing", "嗅探"),
    ("任务结束，成功提交", "Task finished, submitted successfully", "任務結束，成功提交"),
    ("任务强制中止", "Task forcibly stopped", "任務強制中止"),
    ("未找到任何视频", "No videos found", "未找到任何影片"),
    ("开始第二遍扫描", "Starting second scan", "開始第二輪掃描"),
    ("校验中文字幕", "checking Chinese subtitles", "校驗中文字幕"),
    ("发现演员主页，自动跳转", "Actor homepage found; redirecting automatically", "發現演員主頁，自動跳轉"),
    ("跳转校验", "Redirect check", "跳轉校驗"),
    ("嗅探成功", "Sniff succeeded", "嗅探成功"),
    ("嗅探超时", "Sniff timed out", "嗅探逾時"),
    ("未找到 playlist.m3u8", "playlist.m3u8 not found", "未找到 playlist.m3u8"),
    ("页面加载错误", "Page load error", "頁面載入錯誤"),
    ("中文校验异常", "Chinese subtitle check error", "中文字幕校驗異常"),
    ("未找到可用的小红书 Cookie，启动浏览器采集会话", "No usable Xiaohongshu Cookie found; starting browser session capture", "未找到可用的小紅書 Cookie，啟動瀏覽器擷取會話"),
    ("已生成", "Generated", "已產生"),
    ("个小红书下载任务", "Xiaohongshu download tasks", "個小紅書下載任務"),
    ("共发现", "found total", "共發現"),
    ("个账号候选，请选择主页", "account candidates; please select a homepage", "個帳號候選，請選擇主頁"),
    ("正在搜索小红书账号", "Searching Xiaohongshu account", "正在搜尋小紅書帳號"),
    ("正在通过网页搜索小红书号", "Searching Xiaohongshu ID through web search", "正在透過網頁搜尋小紅書號"),
    ("小红书流水线模式", "Xiaohongshu pipeline mode", "小紅書流水線模式"),
    ("详情解析成功后立即投递下载队列", "submit to download queue immediately after detail parsing succeeds", "詳情解析成功後立即投遞下載佇列"),
    ("小红书流水线投递完成", "Xiaohongshu pipeline delivery completed", "小紅書流水線投遞完成"),
    ("共投递", "delivered total", "共投遞"),
    ("个下载项", "download items", "個下載項"),
    ("本地小红书 Cookie 已失效，已丢弃并准备重新登录", "Local Xiaohongshu Cookie expired; discarded and preparing to log in again", "本機小紅書 Cookie 已失效，已丟棄並準備重新登入"),
    ("无法确认本地小红书 Cookie 登录态，本次将重新获取会话", "Could not confirm local Xiaohongshu Cookie login status; reacquiring session this time", "無法確認本機小紅書 Cookie 登入狀態，本次將重新取得會話"),
    ("已加载本地小红书 Cookie", "Loaded local Xiaohongshu Cookie", "已載入本機小紅書 Cookie"),
    ("未能获取指定小红书笔记详情", "Failed to fetch the specified Xiaohongshu note detail", "未能取得指定小紅書筆記詳情"),
    ("正在搜索小红书", "Searching Xiaohongshu", "正在搜尋小紅書"),
    ("已发现", "found", "已發現"),
    ("页新增", "page added", "頁新增"),
    ("条候选", "candidates", "條候選"),
    ("正在读取小红书作者笔记列表", "Reading Xiaohongshu author note list", "正在讀取小紅書作者筆記列表"),
    ("已抓到", "collected", "已抓到"),
    ("用户取消了", "User cancelled", "使用者取消了"),
    ("账号选择流程", "account selection flow", "帳號選擇流程"),
    ("预搜索未提取到小红书账号候选，回退网页用户搜索", "Pre-search found no Xiaohongshu account candidates; falling back to web user search", "預搜尋未提取到小紅書帳號候選，回退網頁使用者搜尋"),
    ("未找到可处理的小红书结果", "No processable Xiaohongshu results found", "未找到可處理的小紅書結果"),
    ("未选择小红书项目；抓取结束，未加入下载队列。", "No XiaoHongShu items selected; crawl finished without queueing downloads.", "未選擇小紅書項目；抓取結束，未加入下載佇列。"),
    ("小红书选择已由用户取消。", "XiaoHongShu selection was cancelled by the user.", "小紅書選擇已由使用者取消。"),
    ("未能成功解析任何小红书笔记详情，全程未投递下载项", "Could not parse any Xiaohongshu note details; no download items were submitted", "未能成功解析任何小紅書筆記詳情，全程未投遞下載項"),
    ("小红书分享链接解析失败", "Xiaohongshu share link parsing failed", "小紅書分享連結解析失敗"),
    ("若页面要求登录，请在浏览器中完成登录；程序会继续等待会话稳定", "If the page asks for login, complete it in the browser; the program will keep waiting for the session to stabilize", "若頁面要求登入，請在瀏覽器中完成登入；程式會繼續等待會話穩定"),
    ("无法解析小红书笔记详情", "Unable to parse Xiaohongshu note details", "無法解析小紅書筆記詳情"),
    ("获取小红书笔记失败", "Failed to fetch Xiaohongshu note", "取得小紅書筆記失敗"),
    ("小红书号预搜索失败，回退到网页用户搜索", "Xiaohongshu ID pre-search failed; falling back to web user search", "小紅書號預搜尋失敗，回退到網頁使用者搜尋"),
    ("小红书输入已归一化", "Xiaohongshu input normalized", "小紅書輸入已正規化"),
    ("小红书登录态探活失败，继续尝试使用当前浏览器确认过的会话", "Xiaohongshu login probe failed; continuing with the current browser-confirmed session", "小紅書登入狀態探活失敗，繼續嘗試使用目前瀏覽器確認過的會話"),
    ("小红书任务失败", "Xiaohongshu task failed", "小紅書任務失敗"),
    ("小红书运行时异常", "Xiaohongshu runtime error", "小紅書執行階段異常"),
    ("小红书返回 461，触发限流冷却后继续", "Xiaohongshu returned 461; continuing after rate-limit cooldown", "小紅書返回 461，觸發限流冷卻後繼續"),
    ("搜索候选累计", "Search candidates total", "搜尋候選累計"),
    ("主页候选累计", "Homepage candidates total", "主頁候選累計"),
    ("网页用户搜索被重定向到登录页，无法直接解析小红书号", "Web user search was redirected to login; cannot parse Xiaohongshu ID directly", "網頁使用者搜尋被重定向到登入頁，無法直接解析小紅書號"),
    ("网页用户搜索未找到匹配的小红书号", "Web user search found no matching Xiaohongshu ID", "網頁使用者搜尋未找到匹配的小紅書號"),
    ("已解析详情", "Parsed details", "已解析詳情"),
    ("成功", "success", "成功"),
    ("已投递", "delivered", "已投遞"),
    ("已尝试恢复本地小红书 Cookie", "Tried to restore local Xiaohongshu Cookie", "已嘗試恢復本機小紅書 Cookie"),
    ("检测到已登录的小红书会话，Cookie 已保存", "Detected logged-in Xiaohongshu session; Cookie saved", "偵測到已登入的小紅書會話，Cookie 已儲存"),
    ("小红书笔记详情线程失败", "Xiaohongshu note detail thread failed", "小紅書筆記詳情執行緒失敗"),
    ("本地小红书 Cookie 恢复失败，继续使用新会话", "Failed to restore local Xiaohongshu Cookie; continuing with new session", "本機小紅書 Cookie 恢復失敗，繼續使用新會話"),
    ("小红书号未命中主页结果，回退为关键词搜索", "Xiaohongshu ID did not match homepage results; falling back to keyword search", "小紅書號未命中主頁結果，回退為關鍵字搜尋"),
    ("下载已暂停", "download paused", "下載已暫停"),
    ("Web 端用户请求停止爬虫任务", "Web user requested to stop the crawl task", "Web 端使用者要求停止爬蟲任務"),
    ("Web 端开始扫描本地媒体目录（异步）", "Web started scanning local media folder (async)", "Web 端開始非同步掃描本機媒體目錄"),
    ("Web 端开始扫描本地媒体目录", "Web started scanning local media folder", "Web 端開始掃描本機媒體目錄"),
    ("Web 端启动爬虫任务", "Web started crawl task", "Web 端啟動爬蟲任務"),
    ("Web 端发现可下载资源", "Web found downloadable resources", "Web 端發現可下載資源"),
    ("Web 端下载任务完成", "Web download task completed", "Web 端下載任務完成"),
    ("Web 端下载任务失败", "Web download task failed", "Web 端下載任務失敗"),
    ("Web 端保存目录已变更", "Web save directory changed", "Web 端儲存目錄已變更"),
    ("Web 端爬虫任务结束", "Web crawl task finished", "Web 端爬蟲任務結束"),
    ("用户取消更新下载", "User cancelled the update download", "使用者取消更新下載"),
    ("正在等待上一次更新下载线程停止，暂不能重试。", "Waiting for the previous update download thread to stop; retry is not available yet.", "正在等待上一次更新下載執行緒停止，暫時無法重試。"),
    ("更新安装程序已启动，应用即将退出。", "Update installer started; the app will exit shortly.", "更新安裝程式已啟動，應用程式即將結束。"),
    ("Bilibili 并发解析播放流并批量提交下载项", "Bilibili is resolving streams concurrently and submitting download items in batches", "Bilibili 正在並行解析播放串流並批次提交下載項目"),
    ("Bilibili 并发取流线程失败", "Bilibili concurrent stream worker failed", "Bilibili 並行取流執行緒失敗"),
    ("HTTP 断点续传请求已建立", "HTTP resume request established", "HTTP 斷點續傳請求已建立"),
    ("目录切换后的初始扫描完成", "Initial scan after changing directory completed", "切換目錄後的初始掃描完成"),
    ("收到超长 WebSocket 消息，连接已关闭", "Oversized WebSocket message received; connection closed", "收到過長的 WebSocket 訊息，連線已關閉"),
    ("更新安装包已下载并通过校验", "Update package downloaded and verified", "更新安裝套件已下載並通過校驗"),
    ("更新安装程序启动失败", "Failed to start the update installer", "更新安裝程式啟動失敗"),
    ("已跳过更新版本", "Skipped update version", "已略過更新版本"),
    ("已调度 select_tasks 测试事件", "select_tasks test event dispatched", "已排程 select_tasks 測試事件"),
    ("收到非法 JSON 消息", "Invalid JSON message received", "收到無效的 JSON 訊息"),
    ("Bilibili 登录状态校验失败", "Bilibili login status check failed", "Bilibili 登入狀態校驗失敗"),
    ("等待 Bilibili 扫码登录超时", "Timed out waiting for Bilibili QR-code login", "等待 Bilibili 掃碼登入逾時"),
    ("等待抖音扫码登录超时 (120秒)", "Timed out waiting for Douyin QR-code login (120 seconds)", "等待抖音掃碼登入逾時（120 秒）"),
    ("用户在登录过程中终止任务", "User stopped the task during login", "使用者在登入過程中終止任務"),
    ("HTTP 下载内容不完整，准备重试", "HTTP download incomplete; preparing to retry", "HTTP 下載內容不完整，準備重試"),
    ("HTTP 下载失败，准备重试", "HTTP download failed; preparing to retry", "HTTP 下載失敗，準備重試"),
    ("HTTP 下载异常，准备重试", "HTTP download error; preparing to retry", "HTTP 下載異常，準備重試"),
    ("分块下载失败，准备重试", "Chunked download failed; preparing to retry", "分塊下載失敗，準備重試"),
    (
        "文件删除等待超时前下载线程未停止",
        "Download worker did not stop before file deletion timeout",
        "檔案刪除等待逾時前下載執行緒未停止",
    ),
    ("流断点续传：从", "stream resume: continuing from", "串流斷點續傳：從"),
    ("字节继续下载", "bytes", "位元組繼續下載"),
    ("打开快手目标页", "Opening the Kuaishou target page", "開啟快手目標頁"),
    ("页面访问", "Page navigation", "頁面存取"),
    ("B站", "B-site", "B 站"),
    ("已启动有界下载恢复维护", "Started bounded download recovery maintenance", "已啟動有界下載恢復維護"),
    ("应用启动时已处理过期下载临时文件", "Processed stale download temp artifacts at application startup", "應用程式啟動時已處理過期下載暫存檔"),
    ("已完成有界下载恢复维护", "Completed bounded download recovery maintenance", "已完成有界下載恢復維護"),
    ("无法枚举恢复目录；本次尝试已确认", "Recovery directory could not be enumerated; the attempt was acknowledged", "無法列舉恢復目錄；本次嘗試已確認"),
    ("旧版目录扫描已受限或降级", "A legacy directory scan was bounded or degraded", "舊版目錄掃描已受限或降級"),
    ("旧版临时文件清理已在生产扫描预算处停止", "Stopped legacy temp cleanup at the production scan budget", "舊版暫存檔清理已在生產掃描預算處停止"),
    ("已设置当前用户的默认应用", "Set current-user default apps", "已設定目前使用者的預設應用程式"),
    ("文件关联注册仅支持 Windows", "File association registration is Windows-only", "檔案關聯註冊僅支援 Windows"),
    ("文件关联默认值仅支持 Windows", "File association defaults are Windows-only", "檔案關聯預設值僅支援 Windows"),
    ("文件关联诊断仅支持 Windows", "File association diagnostics are Windows-only", "檔案關聯診斷僅支援 Windows"),
    ("为以下项目设置默认值失败：", "Failed to set defaults for ", "為以下項目設定預設值失敗："),
    ("无法解析当前用户 SID：", "Cannot resolve current user SID: ", "無法解析目前使用者 SID："),
    ("界面可见性探测：", "Shell visibility probe: ", "介面可見性探測："),
    ("界面外壳意外隐藏；正在恢复", "Shell chrome was hidden unexpectedly; restoring shell chrome", "介面外殼意外隱藏；正在恢復"),
    ("恢复界面外壳时已退出残留的媒体全屏状态", "Exited stale media fullscreen while restoring shell chrome", "恢復介面外殼時已退出殘留的媒體全螢幕狀態"),
    ("打开快手搜索页", "Opening the Kuaishou search page", "開啟快手搜尋頁"),
    ("开始切换目录", "Started changing directory", "開始切換目錄"),
    ("任务已停止", "Task stopped", "任務已停止"),
    ("爬虫完成回调已调用", "_on_spider_finished was called", "爬蟲完成回呼已呼叫", "_on_spider_finished 被调用"),
    ("CLI 发现可下载资源", "CLI found downloadable resources", "CLI 發現可下載資源"),
    ("CLI 启动爬虫任务", "CLI started crawl task", "CLI 啟動爬蟲任務"),
    ("CLI 下载任务失败", "CLI download task failed", "CLI 下載任務失敗"),
    ("用户取消操作", "User cancelled operation", "使用者取消操作"),
    ("选择策略异常", "Selection strategy error", "選擇策略異常"),
    ("默认全选", "defaulting to select all", "預設全選"),
    ("返回空选择", "returning an empty selection", "返回空選擇"),
    ("用户已取消，跳过后续选择", "User cancelled; skipping subsequent selections", "使用者已取消，略過後續選擇"),
    ("spider 超过", "spider exceeded", "spider 超過"),
    ("未完成，强制停止", "without finishing; force stopping", "未完成，強制停止"),
    ("item 转换失败", "item conversion failed", "item 轉換失敗"),
    ("防护规则已停止页面跳转", "Guardrail stopped navigation", "防護規則已停止頁面跳轉"),
    ("防护规则已停止页面刷新", "Guardrail stopped reload", "防護規則已停止頁面重新整理"),
    ("失败", "failed", "失敗"),
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

_EN_LOG_FRAGMENT_CLEANUPS = (
    ("参数未设置，程序不会储存任何数据至文件", "parameter is not set; the program will not store data to files"),
    ("响应不是有效的 JSON 格式", "response is not valid JSON format"),
    ("扫描被中断，跳过中文校验", "scan interrupted; skipped Chinese subtitle check"),
    ("[DEBUG] 已调度 select_tasks 测试事件", "[DEBUG] select_tasks test event dispatched"),
    ("无法写入", "failed to write"),
    ("纯数字 UID 暂不supported直接搜索", "numeric UID cannot be searched directly"),
    ("视频下载地址解析failed", "video download URL parsing failed"),
    ("视频下载地址parsing failed", "video download URL parsing failed"),
    ("Share link解析failed", "share-link parsing failed"),
    ("Share link解析", "share-link parsing"),
    ("加载本地 Cookie failed", "failed to load local Cookie"),
    ("继续尝试页面登录", "continuing page login"),
    ("关闭 SDK failed", "failed to close SDK"),
    ("scan完成", "scan completed"),
    ("登录failed", "login failed"),
    ("扫描failed", "scan failed"),
    ("搜索failed", "search failed"),
    ("解析failed", "parsing failed"),
    ("获取success", "fetched successfully"),
    ("数据提取success", "data extracted successfully"),
    ("视频下载地址解析failed", "video download URL parsing failed"),
    ("HTTP 请求异常", "HTTP request error"),
    ("响应内容预览", "response preview"),
    ("参数已设置为", "parameter set to"),
    ("使用本地兜底值", "using local fallback value"),
    ("浏览器信息", "browser info"),
    ("请求值", "request value"),
    ("本地值", "local value"),
    ("开始:", "started:"),
    ("参数:", "parameter:"),
    ("准备生成清单", "preparing to generate the list"),
    ("同时进行中", "running concurrently"),
    ("Cookie 有效", "Cookie is valid"),
    ("sessionid_ss 有效", "sessionid_ss is valid"),
    ("个valid resources", "valid resources"),
    ("个candidates", "candidates"),
    ("个下载项", "download items"),
    ("个有效资源", "valid resources"),
    ("个匹配用户", "matching users"),
    ("个小红书下载任务", "Xiaohongshu download tasks"),
    ("个账号候选", "account candidates"),
    ("个任务", "tasks"),
    ("个项目", "items"),
    ("个视频", "videos"),
    ("个文件", "files"),
    ("个候选", "candidates"),
    ("粉丝", "followers"),
    ("作品", "works"),
    ("合集", "collection"),
    ("小红书", "Xiaohongshu"),
    ("抖音", "Douyin"),
    ("快手", "Kuaishou"),
    ("扫描", "scan"),
    ("解析", "parse"),
    ("聚合", "aggregate"),
    ("有效", "valid"),
    ("最多", "max"),
    ("（如", " (for example "),
    ("）", ")"),
    ("个for selection", "for selection"),
    ("内退出", ""),
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
    "Douyin": {"zh-CN": "抖音", "en-US": "Douyin", "zh-TW": "抖音"},
    "Kuaishou": {"zh-CN": "快手", "en-US": "Kuaishou", "zh-TW": "快手"},
    "Xiaohongshu": {"zh-CN": "小红书", "en-US": "Xiaohongshu", "zh-TW": "小紅書"},
    "XiaoHongShu": {"zh-CN": "小红书", "en-US": "Xiaohongshu", "zh-TW": "小紅書"},
    "小红书": {"en-US": "Xiaohongshu", "zh-TW": "小紅書"},
    "小紅書": {"zh-CN": "小红书", "en-US": "Xiaohongshu"},
    "System": {"zh-CN": "系统", "en-US": "System", "zh-TW": "系統"},
    "系统": {"en-US": "System", "zh-TW": "系統"},
    "系統": {"zh-CN": "系统", "en-US": "System"},
    "MainWindow": {"zh-CN": "主窗口", "en-US": "Main window", "zh-TW": "主視窗"},
    "主窗口": {"en-US": "Main window", "zh-TW": "主視窗"},
    "主視窗": {"zh-CN": "主窗口", "en-US": "Main window"},
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
    "BaseDownloader": {"zh-CN": "基础下载器", "en-US": "BaseDownloader", "zh-TW": "基礎下載器"},
    "BaseSpider": {"zh-CN": "基础爬虫", "en-US": "BaseSpider", "zh-TW": "基礎爬蟲"},
    "BilibiliSpider": {"zh-CN": "Bilibili 爬虫", "en-US": "BilibiliSpider", "zh-TW": "Bilibili 爬蟲"},
    "DouyinSpider": {"zh-CN": "抖音爬虫", "en-US": "DouyinSpider", "zh-TW": "抖音爬蟲"},
    "KuaishouSpider": {"zh-CN": "快手爬虫", "en-US": "KuaishouSpider", "zh-TW": "快手爬蟲"},
    "XiaohongshuSpider": {"zh-CN": "小红书爬虫", "en-US": "XiaohongshuSpider", "zh-TW": "小紅書爬蟲"},
    "XiaoHongShuSpider": {"zh-CN": "小红书爬虫", "en-US": "XiaoHongShuSpider", "zh-TW": "小紅書爬蟲"},
    "MissAVSpider": {"zh-CN": "MissAV 爬虫", "en-US": "MissAVSpider", "zh-TW": "MissAV 爬蟲"},
    "BiliAPI": {"zh-CN": "Bilibili 接口", "en-US": "BiliAPI", "zh-TW": "Bilibili 介面"},
    "DouyinItemParser": {"zh-CN": "抖音条目解析器", "en-US": "DouyinItemParser", "zh-TW": "抖音項目解析器"},
    "DouyinLoginProcess": {"zh-CN": "抖音登录流程", "en-US": "DouyinLoginProcess", "zh-TW": "抖音登入流程"},
    "XiaohongshuClient": {"zh-CN": "小红书客户端", "en-US": "XiaohongshuClient", "zh-TW": "小紅書用戶端"},
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
    "M3U8Downloader": {"zh-CN": "M3U8 下载器", "en-US": "M3U8Downloader", "zh-TW": "M3U8 下載器"},
    "M3U8Proxy": {"zh-CN": "M3U8 代理", "en-US": "M3U8Proxy", "zh-TW": "M3U8 代理"},
    "FFmpegDownloader": {"zh-CN": "FFmpeg 下载器", "en-US": "FFmpegDownloader", "zh-TW": "FFmpeg 下載器"},
    "ChunkedDownloader": {"zh-CN": "分块下载器", "en-US": "ChunkedDownloader", "zh-TW": "分塊下載器"},
    "ExternalToolRunner": {"zh-CN": "外部工具运行器", "en-US": "ExternalToolRunner", "zh-TW": "外部工具執行器"},
    "FailedRecordStore": {"zh-CN": "失败记录存储", "en-US": "FailedRecordStore", "zh-TW": "失敗記錄儲存"},
    "FrontendStateService": {"zh-CN": "前端状态服务", "en-US": "FrontendStateService", "zh-TW": "前端狀態服務"},
    "FrontendLogCache": {"zh-CN": "前端日志缓存", "en-US": "FrontendLogCache", "zh-TW": "前端日誌快取"},
    "FrontendSettingsAdapter": {"zh-CN": "前端设置适配器", "en-US": "FrontendSettingsAdapter", "zh-TW": "前端設定適配器"},
    "FrontendActionWorker": {"zh-CN": "前端动作线程", "en-US": "FrontendActionWorker", "zh-TW": "前端動作執行緒"},
    "FrontendSnapshotWorker": {"zh-CN": "前端快照线程", "en-US": "FrontendSnapshotWorker", "zh-TW": "前端快照執行緒"},
    "LogQueryWorker": {"zh-CN": "日志查询线程", "en-US": "LogQueryWorker", "zh-TW": "日誌查詢執行緒"},
    "LogDetailWorker": {"zh-CN": "日志详情线程", "en-US": "LogDetailWorker", "zh-TW": "日誌詳情執行緒"},
    "ListPageWorker": {"zh-CN": "列表分页线程", "en-US": "ListPageWorker", "zh-TW": "列表分頁執行緒"},
    "LatestRequestWorker": {"zh-CN": "最新请求线程", "en-US": "LatestRequestWorker", "zh-TW": "最新請求執行緒"},
    "SequentialRequestWorker": {"zh-CN": "顺序请求线程", "en-US": "SequentialRequestWorker", "zh-TW": "順序請求執行緒"},
    "AppState": {"zh-CN": "应用状态", "en-US": "AppState", "zh-TW": "應用狀態"},
    "MediaMetadataService": {"zh-CN": "媒体元数据服务", "en-US": "MediaMetadataService", "zh-TW": "媒體中繼資料服務"},
    "CacheService": {"zh-CN": "缓存服务", "en-US": "CacheService", "zh-TW": "快取服務"},
    "MediaLibraryService": {"zh-CN": "媒体库服务", "en-US": "MediaLibraryService", "zh-TW": "媒體庫服務"},
    "PlaybackPositionService": {"zh-CN": "播放位置服务", "en-US": "PlaybackPositionService", "zh-TW": "播放位置服務"},
    "MkvPlaybackRepairService": {"zh-CN": "MKV 播放修复服务", "en-US": "MkvPlaybackRepairService", "zh-TW": "MKV 播放修復服務"},
    "DebugArtifactsService": {"zh-CN": "调试产物服务", "en-US": "DebugArtifactsService", "zh-TW": "偵錯產物服務"},
    "MediaHostControllerMixin": {"zh-CN": "媒体控制器", "en-US": "MediaHostControllerMixin", "zh-TW": "媒體控制器"},
    "SettingsPage": {"zh-CN": "配置页", "en-US": "SettingsPage", "zh-TW": "設定頁"},
    "SettingsPathPicker": {"zh-CN": "路径选择器", "en-US": "SettingsPathPicker", "zh-TW": "路徑選擇器"},
    "WebController": {"zh-CN": "Web 控制器", "en-US": "WebController", "zh-TW": "Web 控制器"},
    "WebControllerRouteService": {"zh-CN": "Web 控制器路由服务", "en-US": "WebControllerRouteService", "zh-TW": "Web 控制器路由服務"},
    "WebWorkflowService": {"zh-CN": "Web 工作流服务", "en-US": "WebWorkflowService", "zh-TW": "Web 工作流服務"},
    "WebWorkflowDownloadService": {"zh-CN": "Web 下载工作流服务", "en-US": "WebWorkflowDownloadService", "zh-TW": "Web 下載工作流服務"},
    "WebDirectoryService": {"zh-CN": "Web 目录服务", "en-US": "WebDirectoryService", "zh-TW": "Web 目錄服務"},
    "WebSearchService": {"zh-CN": "Web 搜索服务", "en-US": "WebSearchService", "zh-TW": "Web 搜尋服務"},
    "WebSocketRuntime": {"zh-CN": "WebSocket 运行时", "en-US": "WebSocketRuntime", "zh-TW": "WebSocket 執行階段"},
    "WebSocketBridge": {"zh-CN": "WebSocket 桥接器", "en-US": "WebSocketBridge", "zh-TW": "WebSocket 橋接器"},
    "WebSocketMessageDispatcher": {"zh-CN": "WebSocket 消息分发器", "en-US": "WebSocketMessageDispatcher", "zh-TW": "WebSocket 訊息分發器"},
    "WebSocketBootstrapper": {"zh-CN": "WebSocket 初始化器", "en-US": "WebSocketBootstrapper", "zh-TW": "WebSocket 初始化器"},
    "WebSocketSessionBinder": {"zh-CN": "WebSocket 会话绑定器", "en-US": "WebSocketSessionBinder", "zh-TW": "WebSocket 工作階段綁定器"},
    "ConnectionManager": {"zh-CN": "连接管理器", "en-US": "ConnectionManager", "zh-TW": "連線管理器"},
    "WindowChrome": {"zh-CN": "窗口标题栏", "en-US": "WindowChrome", "zh-TW": "視窗標題列"},
    "log_platforms": {"zh-CN": "日志平台元数据", "en-US": "log_platforms", "zh-TW": "日誌平台中繼資料"},
    "WebUI": {"zh-CN": "网页端", "en-US": "WebUI", "zh-TW": "網頁端"},
    "网页端": {"en-US": "WebUI", "zh-TW": "網頁端"},
    "網頁端": {"zh-CN": "网页端", "en-US": "WebUI"},
    "GUI": {"zh-CN": "图形界面", "en-US": "GUI", "zh-TW": "圖形介面"},
    "图形界面": {"en-US": "GUI", "zh-TW": "圖形介面"},
    "圖形介面": {"zh-CN": "图形界面", "en-US": "GUI"},
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


def _runtime_config_platform_name(value: str, language: str) -> str:
    text = str(value or "").strip()
    aliases = {
        "Douyin": {"zh-CN": "抖音", "en-US": "Douyin", "zh-TW": "抖音"},
        "douyin": {"zh-CN": "抖音", "en-US": "Douyin", "zh-TW": "抖音"},
        "抖音": {"zh-CN": "抖音", "en-US": "Douyin", "zh-TW": "抖音"},
        "TikTok": {"zh-CN": "TikTok", "en-US": "TikTok", "zh-TW": "TikTok"},
        "tiktok": {"zh-CN": "TikTok", "en-US": "TikTok", "zh-TW": "TikTok"},
    }
    return _localized(aliases.get(text, {}), language) or _runtime_platform_name(text, language)


def _runtime_subject(prefix: str, platform: str, suffix: str) -> str:
    padded = bool(re.search(r"[A-Za-z0-9]$", platform) or re.search(r"^[A-Za-z0-9]", platform))
    return f"{prefix} {platform} {suffix}" if padded else f"{prefix}{platform}{suffix}"


def _localized_media_term(value: str, language: str) -> str:
    text = str(value or "").strip()
    if language == "en-US" and text in _MEDIA_TERM_ALIASES:
        return text
    return _localized(_MEDIA_TERM_ALIASES.get(text, {}), language) or text


def _cleanup_english_log_fragments(text: str) -> str:
    """清理动态翻译后的中英混排片段；规则按声明顺序应用。"""
    result = str(text or "")
    for source, target in _EN_LOG_FRAGMENT_CLEANUPS:
        result = result.replace(source, target)
    result = re.sub(r"另有\s*(?P<count>\d+)\s*items?items were removed", r"\g<count> additional items were removed", result)
    result = re.sub(r"已切换到\s*1\s*主题", "Switched theme", result)
    result = re.sub(r"获取\s*(?P<name>.*?)\s*参数failed", r"failed to fetch \g<name> parameter", result)
    result = re.sub(r"kept\s*(?P<count>\d+)\s*个\s*(?P<label>.*?)\s*[,，;]", r"kept \g<count> \g<label>; ", result)
    result = re.sub(r"共\s*(?P<count>\d+)\s*个", r"total \g<count> items", result)
    result = re.sub(r"total\s+(?P<count>\d+)\s*个", r"total \g<count> items", result)
    result = re.sub(r"发现\s*(?P<count>\d+)\s*个", r"found \g<count> items", result)
    result = re.sub(r"scanned\s*(?P<count>\d+)\s*个", r"scanned \g<count> items", result)
    result = re.sub(r"Selected\s*(?P<count>\d+)\s*个", r"Selected \g<count> items", result)
    result = re.sub(r"(?<=\d)\s*项", " items", result)
    result = re.sub(r"(?<=\d)\s*页", "", result)
    result = re.sub(r"另有\s*(?P<count>\d+)\s*itemsitems were removed", r"\g<count> additional items were removed", result)
    result = re.sub(r"共\s*(?P<count>\d+)\s*candidates", r"total \g<count> candidates", result)
    result = result.replace("scan完成", "scan completed")
    result = result.replace("视频下载地址parsing failed", "video download URL parsing failed")
    result = result.replace("itemsitems", "items")
    result = result.replace("，please", "; please")
    result = result.replace("，preparing", "; preparing")
    result = result.replace("，", ", ")
    result = result.replace("。", ".")
    return result


def _localize_english_dynamic(text: str) -> str:
    """把单个日志片段翻译为英文。

    输入应是不含结构化分隔符的片段。正则按首命中返回，具体完整句必须位于
    宽泛句式之前；未命中正则时才依次应用 ``_EN_DYNAMIC_REPLACEMENTS``，若仍
    无替换则返回输入文本。该顺序是动态翻译契约的一部分。
    """
    select_tasks_relay = re.match(
        r"^select_tasks\s+(?:转发延迟|轉發延遲)=(?P<lag>[\d.]+)\s*毫秒[，,]\s*"
        r"(?:项目数|項目數)=(?P<items>\d+)$",
        text,
    )
    if select_tasks_relay:
        return (
            f"select_tasks relay lag={select_tasks_relay.group('lag')}ms "
            f"items={select_tasks_relay.group('items')}"
        )

    theme_switch = re.match(rf"^{_DYNAMIC_PREFIX}已切换到(?P<mode>浅色|深色)主题[。.]?$", text)
    if theme_switch:
        mode = "light" if theme_switch.group("mode") == "浅色" else "dark"
        return f"{theme_switch.group('prefix') or ''}Switched to {mode} theme"

    media_empty = re.match(rf"^{_DYNAMIC_PREFIX}该目录下没有找到视频或图片[。.]?$", text)
    if media_empty:
        return f"{media_empty.group('prefix') or ''}No videos or images found in this directory"

    matching_users = re.match(rf"^{_DYNAMIC_PREFIX}找到\s*(?P<count>\d+)\s*(?:个匹配用户|matching users)$", text)
    if matching_users:
        return f"{matching_users.group('prefix') or ''}Found {matching_users.group('count')} matching users"

    match = _CONFIG_NOT_LOGGED_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Config {match.group('key')} is not logged in; data fetching ended early"

    match = _CONFIG_NOT_SET_RE.match(text)
    if match:
        platform = _runtime_config_platform_name(match.group("platform"), "en-US")
        return f"{match.group('prefix') or ''}Config {match.group('key')} is not set; {platform} features may not work properly"

    match = _PARAM_UPDATED_RE.match(text)
    if match:
        platform = _runtime_config_platform_name(match.group("platform"), "en-US")
        return f"{match.group('prefix') or ''}{platform} parameters updated!"

    bilibili_stream_retry = re.match(
        r"^(?P<prefix>.*?)(?:B站|Bilibili|B-site)\s+(?P<media>.*?)\s+流连接断开，"
        r"(?P<delay>\d+)s\s+后重试\s+\((?P<attempt>\d+)/(?:\s*)?(?P<total>\d+)\):\s*(?P<error>.+)$",
        text,
    )
    if bilibili_stream_retry:
        media = _localized_media_term(bilibili_stream_retry.group("media"), "en-US")
        return (
            f"{bilibili_stream_retry.group('prefix') or ''}B-site {media} stream disconnected; "
            f"retrying in {bilibili_stream_retry.group('delay')}s "
            f"({bilibili_stream_retry.group('attempt')}/{bilibili_stream_retry.group('total')}): "
            f"{bilibili_stream_retry.group('error')}"
        )

    spider_summary = re.match(
        r"^(?P<prefix>.*?)(?:spider|爬虫)\s*已结束,\s*耗时\s*(?P<elapsed>[^,]+?)s,\s*"
        r"收集到\s*(?P<count>\d+)\s*个项目,\s*二次选择\s*(?P<selection>\d+)\s*次$",
        text,
    )
    if spider_summary:
        return (
            f"{spider_summary.group('prefix') or ''}spider finished, "
            f"elapsed {spider_summary.group('elapsed')}s, "
            f"collected {spider_summary.group('count')} items, "
            f"secondary selections {spider_summary.group('selection')}"
        )

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
    """替换运行时短语，始终先处理较长 source，避免短词截断长句。"""
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
    """翻译来源/动作等结构化片段；没有别名或翻译变化时返回原文本。"""
    if " · " not in text and " / " not in text and " 路 " not in text:
        mapped = _STRUCTURED_SEGMENT_ALIASES.get(text)
        if mapped:
            return _localized(mapped, language) or text
        return text
    parts = re.split(r"(\s+·\s+|\s+/\s+|\s+路\s+)", text)
    changed = False
    translated_parts: list[str] = []
    for part in parts:
        if re.fullmatch(r"\s*(?:·|/|路)\s*", part):
            translated_parts.append(part)
            continue
        translated = tr(part, language)
        mapped = _STRUCTURED_SEGMENT_ALIASES.get(part)
        if mapped:
            translated = _localized(mapped, language) or translated
        changed = changed or translated != part
        translated_parts.append(translated)
    return "".join(translated_parts) if changed else text


def _localize_runtime_dynamic_segments(text: str, language: str) -> str:
    """对每个结构化日志片段应用动态规则。

    来源标签与运行时消息常共用一个展示字符串，例如
    ``MainWindow · fetch video detail``。翻译来源标签后，消息片段仍必须继续
    进入动态规则。分隔符原样保留，每个普通片段未命中时也原样回退。
    """

    parts = re.split(r"(\s+·\s+|\s+/\s+|\s+路\s+)", text)
    localized_parts: list[str] = []
    for part in parts:
        if re.fullmatch(r"\s*(?:·|/|路)\s*", part):
            localized_parts.append(part)
        elif language == "en-US":
            localized_parts.append(_localize_english_dynamic(part))
        else:
            localized_parts.append(_localize_non_english_dynamic(part, language))
    return "".join(localized_parts)


def _localize_non_english_dynamic(text: str, language: str) -> str:
    """把单个片段本地化为简体或繁体中文，未命中时返回输入。

    精确映射优先，后续正则从专用格式到一般格式首命中返回；调整顺序可能让
    动态字段丢失或被宽泛句式提前消费。
    """
    mapped = _NON_EN_DYNAMIC_EXACT.get(text)
    if mapped:
        return _localized(mapped, language)

    select_tasks_relay = re.match(
        r"^select_tasks relay lag=(?P<lag>[\d.]+)ms items=(?P<items>\d+)$",
        text,
        re.IGNORECASE,
    )
    if select_tasks_relay:
        if language == "zh-TW":
            return (
                f"select_tasks 轉發延遲={select_tasks_relay.group('lag')} 毫秒，"
                f"項目數={select_tasks_relay.group('items')}"
            )
        return (
            f"select_tasks 转发延迟={select_tasks_relay.group('lag')} 毫秒，"
            f"项目数={select_tasks_relay.group('items')}"
        )

    match = re.match(rf"^{_DYNAMIC_PREFIX}Switched to\s*(?P<mode>light|dark)\s*theme[。.]?$", text, re.IGNORECASE)
    if match:
        mode = match.group("mode").lower()
        localized_mode = (
            "淺色" if language == "zh-TW" and mode == "light"
            else "深色" if language == "zh-TW"
            else "浅色" if mode == "light"
            else "深色"
        )
        return f"{match.group('prefix') or ''}{'已切換到' if language == 'zh-TW' else '已切换到'}{localized_mode}{'主題' if language == 'zh-TW' else '主题'}"

    match = re.match(rf"^{_DYNAMIC_PREFIX}No videos or images found in this directory[。.]?$", text, re.IGNORECASE)
    if match:
        message = "該目錄下沒有找到影片或圖片" if language == "zh-TW" else "该目录下没有找到视频或图片"
        return f"{match.group('prefix') or ''}{message}"

    match = re.match(
        rf"^{_DYNAMIC_PREFIX}(?:Found|找到)\s*(?P<count>\d+)\s*(?:matching users|个匹配用户|個匹配使用者)$",
        text,
        re.IGNORECASE,
    )
    if match:
        unit = "個匹配使用者" if language == "zh-TW" else "个匹配用户"
        return f"{match.group('prefix') or ''}找到 {match.group('count')} {unit}"

    match = re.match(rf"^{_DYNAMIC_PREFIX}Config\s+(?P<key>[\w.-]+)\s+is not logged in;\s*data fetching ended early$", text, re.IGNORECASE)
    if match:
        if language == "zh-TW":
            return f"{match.group('prefix') or ''}設定檔 {match.group('key')} 參數未登入，資料取得已提前結束"
        return f"{match.group('prefix') or ''}配置文件 {match.group('key')} 参数未登录，数据获取已提前结束"

    match = re.match(
        rf"^{_DYNAMIC_PREFIX}Config\s+(?P<key>[\w.-]+)\s+is not set;\s*(?P<platform>.+?)\s+features may not work properly$",
        text,
        re.IGNORECASE,
    )
    if match:
        platform = _runtime_config_platform_name(match.group("platform"), language)
        if language == "zh-TW":
            return f"{match.group('prefix') or ''}設定檔 {match.group('key')} 參數未設定，{platform} 平台功能可能無法正常使用"
        return f"{match.group('prefix') or ''}配置文件 {match.group('key')} 参数未设置，{platform} 平台功能可能无法正常使用"

    match = re.match(rf"^{_DYNAMIC_PREFIX}(?P<platform>Douyin|douyin|抖音|TikTok|tiktok)\s+parameters updated[!！]?$", text, re.IGNORECASE)
    if match:
        platform = _runtime_config_platform_name(match.group("platform"), language)
        suffix = "參數更新完成！" if language == "zh-TW" else "参数更新完毕！"
        padded = bool(re.search(r"[A-Za-z0-9]$", platform))
        return f"{match.group('prefix') or ''}{platform} {suffix}" if padded else f"{match.group('prefix') or ''}{platform}{suffix}"

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
    """按固定管线本地化展示文本，未知文本保留其当前内容。

    输入先转为字符串并修复已知乱码，再依次经过静态词典、结构化片段别名、
    运行时长短语、逐片段动态规则；英文最后清理混排残留。阶段顺序不可交换，
    因为后续正则以先前归一化结果为输入。空字符串直接返回。
    """
    value = _repair_mojibake_text(str(text or ""))
    if not value:
        return value
    normalized = normalize_language(language)
    result = tr(value, normalized)
    result = _localize_structured_segments(result, normalized)
    result = _apply_runtime_phrase_translations(result, normalized)
    result = _localize_runtime_dynamic_segments(result, normalized)
    return _cleanup_english_log_fragments(result) if normalized == "en-US" else result


def localize_log_event_code(code: object, language: str | None) -> str:
    """本地化事件码，同时保留其可筛选的分段结构。

    空值和 ``-`` 原样返回；繁体中文逐下划线分段翻译，英文先处理已知动态码，
    再做别名替换和 ASCII 规范化。规范化结果为空时回退原事件码。
    """
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
    """递归本地化 payload 值并保留 dict/list/tuple 形状与字典键。

    ``status_code`` 和 ``event_code`` 的值使用事件码规则；普通字符串使用文本
    规则，其他标量原样返回。
    """
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
