(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpLogI18n;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  function currentLanguage() {
    return typeof dependencies.currentLanguage === "function"
      ? dependencies.currentLanguage()
      : "zh-CN";
  }

  function translateUiText(value) {
    return typeof dependencies.translateUiText === "function"
      ? dependencies.translateUiText(value)
      : String(value || "");
  }

  function canonicalUiText(value) {
    return typeof dependencies.canonicalUiText === "function"
      ? dependencies.canonicalUiText(value)
      : String(value || "");
  }

function localizedLogTabLabel(category) {
  const key = String(category || "all");
  const state = typeof dependencies.getState === "function" ? dependencies.getState() || {} : {};
  const labels = state.log_contract && state.log_contract.category_labels
    ? state.log_contract.category_labels
    : {};
  return translateUiText(labels[key] || key);
}

const STRUCTURED_LOG_SEGMENT_ALIASES = {
  Douyin: { "zh-CN": "抖音", "en-US": "Douyin", "zh-TW": "抖音" },
  Kuaishou: { "zh-CN": "快手", "en-US": "Kuaishou", "zh-TW": "快手" },
  Xiaohongshu: { "zh-CN": "小红书", "en-US": "Xiaohongshu", "zh-TW": "小紅書" },
  XiaoHongShu: { "zh-CN": "小红书", "en-US": "Xiaohongshu", "zh-TW": "小紅書" },
  "小红书": { "zh-CN": "小红书", "en-US": "Xiaohongshu", "zh-TW": "小紅書" },
  "小紅書": { "zh-CN": "小红书", "en-US": "Xiaohongshu", "zh-TW": "小紅書" },
  System: { "zh-CN": "系统", "en-US": "System", "zh-TW": "系統" },
  "系统": { "zh-CN": "系统", "en-US": "System", "zh-TW": "系統" },
  "系統": { "zh-CN": "系统", "en-US": "System", "zh-TW": "系統" },
  Browser: { "zh-CN": "浏览器", "en-US": "Browser", "zh-TW": "瀏覽器" },
  "浏览器": { "zh-CN": "浏览器", "en-US": "Browser", "zh-TW": "瀏覽器" },
  "瀏覽器": { "zh-CN": "浏览器", "en-US": "Browser", "zh-TW": "瀏覽器" },
  DownloadManager: { "zh-CN": "下载管理器", "en-US": "DownloadManager", "zh-TW": "下載管理器" },
  MainWindow: { "zh-CN": "主窗口", "en-US": "Main window", "zh-TW": "主視窗" },
  ApplicationContext: { "zh-CN": "应用上下文", "en-US": "ApplicationContext", "zh-TW": "應用程式上下文" },
  GUI: { "zh-CN": "图形界面", "en-US": "GUI", "zh-TW": "圖形介面" },
  CLI: { "zh-CN": "CLI", "en-US": "CLI", "zh-TW": "CLI" },
  Web: { "zh-CN": "Web", "en-US": "Web", "zh-TW": "Web" },
  Crawler: { "zh-CN": "爬虫", "en-US": "Crawler", "zh-TW": "爬蟲" },
  "爬虫": { "zh-CN": "爬虫", "en-US": "Crawler", "zh-TW": "爬蟲" },
  "爬蟲": { "zh-CN": "爬虫", "en-US": "Crawler", "zh-TW": "爬蟲" },
  Downloader: { "zh-CN": "下载器", "en-US": "Downloader", "zh-TW": "下載器" },
  "下载器": { "zh-CN": "下载器", "en-US": "Downloader", "zh-TW": "下載器" },
  "下載器": { "zh-CN": "下载器", "en-US": "Downloader", "zh-TW": "下載器" },
  BaseDownloader: { "zh-CN": "基础下载器", "en-US": "BaseDownloader", "zh-TW": "基礎下載器" },
  BaseSpider: { "zh-CN": "基础爬虫", "en-US": "BaseSpider", "zh-TW": "基礎爬蟲" },
  BilibiliSpider: { "zh-CN": "Bilibili 爬虫", "en-US": "BilibiliSpider", "zh-TW": "Bilibili 爬蟲" },
  DouyinSpider: { "zh-CN": "抖音爬虫", "en-US": "DouyinSpider", "zh-TW": "抖音爬蟲" },
  KuaishouSpider: { "zh-CN": "快手爬虫", "en-US": "KuaishouSpider", "zh-TW": "快手爬蟲" },
  XiaohongshuSpider: { "zh-CN": "小红书爬虫", "en-US": "XiaohongshuSpider", "zh-TW": "小紅書爬蟲" },
  XiaoHongShuSpider: { "zh-CN": "小红书爬虫", "en-US": "XiaoHongShuSpider", "zh-TW": "小紅書爬蟲" },
  MissAVSpider: { "zh-CN": "MissAV 爬虫", "en-US": "MissAVSpider", "zh-TW": "MissAV 爬蟲" },
  BiliAPI: { "zh-CN": "Bilibili 接口", "en-US": "BiliAPI", "zh-TW": "Bilibili 介面" },
  DouyinItemParser: { "zh-CN": "抖音条目解析器", "en-US": "DouyinItemParser", "zh-TW": "抖音項目解析器" },
  DouyinLoginProcess: { "zh-CN": "抖音登录流程", "en-US": "DouyinLoginProcess", "zh-TW": "抖音登入流程" },
  XiaohongshuClient: { "zh-CN": "小红书客户端", "en-US": "XiaohongshuClient", "zh-TW": "小紅書用戶端" },
  BilibiliDownloader: { "zh-CN": "Bilibili 下载器", "en-US": "BilibiliDownloader", "zh-TW": "Bilibili 下載器" },
  DouyinDownloader: { "zh-CN": "抖音下载器", "en-US": "DouyinDownloader", "zh-TW": "抖音下載器" },
  KuaishouDownloader: { "zh-CN": "快手下载器", "en-US": "KuaishouDownloader", "zh-TW": "快手下載器" },
  XiaohongshuDownloader: { "zh-CN": "小红书下载器", "en-US": "XiaohongshuDownloader", "zh-TW": "小紅書下載器" },
  MissAVDownloader: { "zh-CN": "MissAV 下载器", "en-US": "MissAVDownloader", "zh-TW": "MissAV 下載器" },
  N_m3u8DL_RE_Downloader: { "zh-CN": "N_m3u8DL-RE 下载器", "en-US": "N_m3u8DL_RE_Downloader", "zh-TW": "N_m3u8DL-RE 下載器" },
  M3U8Downloader: { "zh-CN": "M3U8 下载器", "en-US": "M3U8Downloader", "zh-TW": "M3U8 下載器" },
  M3U8Proxy: { "zh-CN": "M3U8 代理", "en-US": "M3U8Proxy", "zh-TW": "M3U8 代理" },
  FFmpegDownloader: { "zh-CN": "FFmpeg 下载器", "en-US": "FFmpegDownloader", "zh-TW": "FFmpeg 下載器" },
  ChunkedDownloader: { "zh-CN": "分块下载器", "en-US": "ChunkedDownloader", "zh-TW": "分塊下載器" },
  ExternalToolRunner: { "zh-CN": "外部工具运行器", "en-US": "ExternalToolRunner", "zh-TW": "外部工具執行器" },
  FailedRecordStore: { "zh-CN": "失败记录存储", "en-US": "FailedRecordStore", "zh-TW": "失敗記錄儲存" },
  FrontendStateService: { "zh-CN": "前端状态服务", "en-US": "FrontendStateService", "zh-TW": "前端狀態服務" },
  FrontendLogCache: { "zh-CN": "前端日志缓存", "en-US": "FrontendLogCache", "zh-TW": "前端日誌快取" },
  FrontendSettingsAdapter: { "zh-CN": "前端设置适配器", "en-US": "FrontendSettingsAdapter", "zh-TW": "前端設定適配器" },
  FrontendActionWorker: { "zh-CN": "前端动作线程", "en-US": "FrontendActionWorker", "zh-TW": "前端動作執行緒" },
  FrontendSnapshotWorker: { "zh-CN": "前端快照线程", "en-US": "FrontendSnapshotWorker", "zh-TW": "前端快照執行緒" },
  LogQueryWorker: { "zh-CN": "日志查询线程", "en-US": "LogQueryWorker", "zh-TW": "日誌查詢執行緒" },
  LogDetailWorker: { "zh-CN": "日志详情线程", "en-US": "LogDetailWorker", "zh-TW": "日誌詳情執行緒" },
  ListPageWorker: { "zh-CN": "列表分页线程", "en-US": "ListPageWorker", "zh-TW": "列表分頁執行緒" },
  LatestRequestWorker: { "zh-CN": "最新请求线程", "en-US": "LatestRequestWorker", "zh-TW": "最新請求執行緒" },
  SequentialRequestWorker: { "zh-CN": "顺序请求线程", "en-US": "SequentialRequestWorker", "zh-TW": "順序請求執行緒" },
  AppState: { "zh-CN": "应用状态", "en-US": "AppState", "zh-TW": "應用狀態" },
  MediaMetadataService: { "zh-CN": "媒体元数据服务", "en-US": "MediaMetadataService", "zh-TW": "媒體中繼資料服務" },
  CacheService: { "zh-CN": "缓存服务", "en-US": "CacheService", "zh-TW": "快取服務" },
  MediaLibraryService: { "zh-CN": "媒体库服务", "en-US": "MediaLibraryService", "zh-TW": "媒體庫服務" },
  PlaybackPositionService: { "zh-CN": "播放位置服务", "en-US": "PlaybackPositionService", "zh-TW": "播放位置服務" },
  MkvPlaybackRepairService: { "zh-CN": "MKV 播放修复服务", "en-US": "MkvPlaybackRepairService", "zh-TW": "MKV 播放修復服務" },
  DebugArtifactsService: { "zh-CN": "调试产物服务", "en-US": "DebugArtifactsService", "zh-TW": "偵錯產物服務" },
  MediaHostControllerMixin: { "zh-CN": "媒体控制器", "en-US": "MediaHostControllerMixin", "zh-TW": "媒體控制器" },
  SettingsPage: { "zh-CN": "配置页", "en-US": "SettingsPage", "zh-TW": "設定頁" },
  SettingsPathPicker: { "zh-CN": "路径选择器", "en-US": "SettingsPathPicker", "zh-TW": "路徑選擇器" },
  WebController: { "zh-CN": "Web 控制器", "en-US": "WebController", "zh-TW": "Web 控制器" },
  WebControllerRouteService: { "zh-CN": "Web 控制器路由服务", "en-US": "WebControllerRouteService", "zh-TW": "Web 控制器路由服務" },
  WebWorkflowService: { "zh-CN": "Web 工作流服务", "en-US": "WebWorkflowService", "zh-TW": "Web 工作流服務" },
  WebWorkflowDownloadService: { "zh-CN": "Web 下载工作流服务", "en-US": "WebWorkflowDownloadService", "zh-TW": "Web 下載工作流服務" },
  WebDirectoryService: { "zh-CN": "Web 目录服务", "en-US": "WebDirectoryService", "zh-TW": "Web 目錄服務" },
  WebSearchService: { "zh-CN": "Web 搜索服务", "en-US": "WebSearchService", "zh-TW": "Web 搜尋服務" },
  WebSocketRuntime: { "zh-CN": "WebSocket 运行时", "en-US": "WebSocketRuntime", "zh-TW": "WebSocket 執行階段" },
  WebSocketBridge: { "zh-CN": "WebSocket 桥接器", "en-US": "WebSocketBridge", "zh-TW": "WebSocket 橋接器" },
  WebSocketMessageDispatcher: { "zh-CN": "WebSocket 消息分发器", "en-US": "WebSocketMessageDispatcher", "zh-TW": "WebSocket 訊息分發器" },
  WebSocketBootstrapper: { "zh-CN": "WebSocket 初始化器", "en-US": "WebSocketBootstrapper", "zh-TW": "WebSocket 初始化器" },
  WebSocketSessionBinder: { "zh-CN": "WebSocket 会话绑定器", "en-US": "WebSocketSessionBinder", "zh-TW": "WebSocket 工作階段綁定器" },
  ConnectionManager: { "zh-CN": "连接管理器", "en-US": "ConnectionManager", "zh-TW": "連線管理器" },
  WindowChrome: { "zh-CN": "窗口标题栏", "en-US": "WindowChrome", "zh-TW": "視窗標題列" },
  log_platforms: { "zh-CN": "日志平台元数据", "en-US": "log_platforms", "zh-TW": "日誌平台中繼資料" },
  WebUI: { "zh-CN": "网页端", "en-US": "WebUI", "zh-TW": "網頁端" },
  "网页端": { "zh-CN": "网页端", "en-US": "WebUI", "zh-TW": "網頁端" },
  "網頁端": { "zh-CN": "网页端", "en-US": "WebUI", "zh-TW": "網頁端" },
};

function localizedStructuredLogSegment(part, language = currentLanguage()) {
  const text = String(part ?? "");
  const trimmed = text.trim();
  const mapped = STRUCTURED_LOG_SEGMENT_ALIASES[trimmed];
  if (mapped) {
    const localized = mapped[language] || mapped["zh-CN"] || trimmed;
    return trimmed === text ? localized : text.replace(trimmed, localized);
  }
  const translated = translateUiText(text);
  if (translated !== text) return translated;
  if (trimmed && trimmed !== text) {
    const translatedTrimmed = translateUiText(trimmed);
    if (translatedTrimmed !== trimmed) return text.replace(trimmed, translatedTrimmed);
  }
  return text;
}

function translateStructuredLogText(value) {
  const text = String(value ?? "");
  if (!text.trim()) return text;
  const language = currentLanguage();
  return text
    .split(/(\s+·\s+|\s+\/\s+|\s+路\s+)/)
    .map(part => (/^\s*(?:·|\/|路)\s*$/.test(part) ? part : localizedStructuredLogSegment(part, language)))
    .join("");
}

function translateRuntimeLogText(value) {
  const text = String(value ?? "");
  if (!text.trim()) return text;
  const language = currentLanguage();
  let translated = translateStructuredLogText(text);
  translated = applyRuntimePhraseTranslations(translated, language);
  translated = localizeRuntimeDynamicSegments(translated, language);
  return language === "en-US" ? cleanupEnglishLogFragments(translated) : translated;
}

const RUNTIME_LOG_PHRASE_TRANSLATIONS = [
  { zh: "Bilibili 流请求建立成功", en: "Bilibili stream request established", tw: "Bilibili 串流請求建立成功" },
  { zh: "Bilibili 下载任务已提交到下载队列", en: "Bilibili download task submitted to the queue", tw: "Bilibili 下載任務已提交到下載佇列" },
  { zh: "Bilibili 下载任务已装配完成", en: "Bilibili download task assembled", tw: "Bilibili 下載任務已組裝完成" },
  { zh: "Bilibili 音视频合并完成", en: "Bilibili audio/video merge completed", tw: "Bilibili 音視訊合併完成" },
  { zh: "Bilibili 音视频合并", en: "Bilibili audio/video merge", tw: "Bilibili 音視訊合併" },
  { zh: "Bilibili 爬虫任务结束", en: "Bilibili crawl task finished", tw: "Bilibili 爬蟲任務結束" },
  { zh: "Bilibili 获取播放流失败", en: "Bilibili playback stream fetch failed", tw: "Bilibili 播放串流取得失敗" },
  { zh: "Bilibili 播放流响应为空", en: "Bilibili playback stream response is empty", tw: "Bilibili 播放串流回應為空" },
  { zh: "B站流下载失败", en: "B-site stream download failed", tw: "B 站串流下載失敗" },
  { zh: "B站下载失败", en: "B-site download failed", tw: "B 站下載失敗" },
  { zh: "检查 Bilibili 登录状态", en: "Checking Bilibili login status", tw: "檢查 Bilibili 登入狀態" },
  { zh: "获取播放流地址", en: "Fetching playback stream URL", tw: "取得播放串流位址" },
  { zh: "启动 Bilibili 爬虫任务", en: "Started Bilibili crawl task", tw: "啟動 Bilibili 爬蟲任務" },
  { zh: "准备下载 Bilibili 音视频流", en: "Preparing Bilibili audio/video stream download", tw: "準備下載 Bilibili 音視訊流" },
  { zh: "准备合并 Bilibili 音视频流", en: "Preparing to merge Bilibili audio/video stream", tw: "準備合併 Bilibili 音視訊流" },
  { zh: "音视频流写入完成，准备合并", en: "Audio/video stream written; preparing to merge", tw: "音視訊流寫入完成，準備合併" },
  { zh: "音视频流下载中", en: "Audio/video stream downloading", tw: "音視訊流下載中" },
  { zh: "任务进入 Bilibili 下载器", en: "Task entered Bilibili downloader", tw: "任務進入 Bilibili 下載器" },
  { zh: "ffmpeg 合并音视频中", en: "ffmpeg merging audio/video", tw: "ffmpeg 合併音視訊中" },
  { zh: "ffmpeg 合并音视频失败", en: "ffmpeg audio/video merge failed", tw: "ffmpeg 音視訊合併失敗" },
  { zh: "ffmpeg 合并音视频超时", en: "ffmpeg audio/video merge timed out", tw: "ffmpeg 音視訊合併逾時" },
  { zh: "已刷新 B站 CDN URL，使用新地址重试", en: "Refreshed B-site CDN URL; retrying with new URL", tw: "已刷新 B 站 CDN URL，使用新位址重試" },
  { zh: "已刷新 B站 CDN URL 成功", en: "Refreshed B-site CDN URL successfully", tw: "已刷新 B 站 CDN URL 成功" },
  { zh: "重新刷新 B站 CDN URL 成功", en: "Refreshed B-site CDN URL again successfully", tw: "重新刷新 B 站 CDN URL 成功" },
  { zh: "重刷新 B站 CDN URL 成功", en: "Refreshed B-site CDN URL again successfully", tw: "重刷新 B 站 CDN URL 成功" },
  { zh: "爬虫发现可下载资源", en: "Crawler found downloadable resources", tw: "爬蟲發現可下載資源" },
  { zh: "爬虫任务结束", en: "Crawl task finished", tw: "爬蟲任務結束" },
  { zh: "下载失败", en: "Download failed", tw: "下載失敗" },
  { zh: "下载任务已入队", en: "Download task has been queued", tw: "下載任務已入隊" },
  { zh: "下载任务已加入执行队列", en: "Download task has been queued for execution", tw: "下載任務已加入執行隊列" },
  { zh: "下载任务开始执行", en: "Download task started", tw: "下載任務開始執行" },
  { zh: "下载任务完成", en: "Download task completed", tw: "下載任務完成" },
  { zh: "下载任务失败", en: "Download task failed", tw: "下載任務失敗" },
  { zh: "UI 回调失败", en: "ui callback failed", tw: "UI 回調失敗" },
  { zh: "回调失败", en: "callback failed", tw: "回調失敗" },
  { zh: "下载任务被用户停止", en: "Download task stopped by user", tw: "下載任務被使用者停止" },
  { zh: "下载完成后已按文件签名修正扩展名", en: "Fixed extension after download by file signature", tw: "下載完成後已依檔案簽章修正副檔名" },
  { zh: "分块下载不可用，回退到后续下载策略", en: "Chunked download unavailable; falling back to later download strategy", tw: "分塊下載不可用，回退到後續策略" },
  { zh: "下载策略执行失败，回退到后续策略", en: "Download strategy failed; falling back to later strategy", tw: "下載策略執行失敗，回退到後續策略" },
  { zh: "抖音下载任务已提交到下载队列", en: "Douyin download task submitted to the queue", tw: "抖音下載任務已提交到下載佇列" },
  { zh: "启动抖音爬虫任务", en: "Started Douyin crawl task", tw: "啟動抖音爬蟲任務" },
  { zh: "抖音爬虫任务结束", en: "Douyin crawl task finished", tw: "抖音爬蟲任務結束" },
  { zh: "抖音爬虫运行异常", en: "Douyin crawl runtime error", tw: "抖音爬蟲執行異常" },
  { zh: "进入抖音任务提交阶段", en: "Entered Douyin task submit stage", tw: "進入抖音任務提交階段" },
  { zh: "Douyin 参数初始化完成", en: "Douyin parameters initialized", tw: "Douyin 參數初始化完成", aliases: ["Douyin参数初始化完成"] },
  { zh: "正在更新抖音参数，请稍等...", en: "Updating Douyin parameters, please wait...", tw: "正在更新抖音參數，請稍候..." },
  { zh: "抖音参数更新完毕！", en: "Douyin parameters updated!", tw: "抖音參數更新完成！", aliases: ["Douyin 参数更新完毕！", "Douyin 参数更新完毕", "Douyin参数更新完毕！", "Douyin参数更新完毕!", "Douyin参数更新完毕"] },
  { zh: "TikTok 参数更新完毕！", en: "TikTok parameters updated!", tw: "TikTok 參數更新完成！", aliases: ["TikTok参数更新完毕！", "TikTok参数更新完毕!", "TikTok参数更新完毕"] },
  { zh: "配置文件 cookie 参数未登录，数据获取已提前结束", en: "Config cookie is not logged in; data fetching ended early", tw: "設定檔 cookie 參數未登入，資料取得已提前結束" },
  { zh: "配置文件 cookie 参数未设置，抖音平台功能可能无法正常使用", en: "Config cookie is not set; Douyin features may not work properly", tw: "設定檔 cookie 參數未設定，抖音平台功能可能無法正常使用" },
  { zh: "配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用", en: "Config cookie_tiktok is not set; TikTok features may not work properly", tw: "設定檔 cookie_tiktok 參數未設定，TikTok 平台功能可能無法正常使用" },
  { zh: "抖音作品详情返回", en: "Douyin work detail returned", tw: "抖音作品詳情返回" },
  { zh: "抖音用户作品分页返回", en: "Douyin user works page returned", tw: "抖音使用者作品分頁返回" },
  { zh: "抖音合集分页返回", en: "Douyin collection page returned", tw: "抖音合集分頁返回" },
  { zh: "抖音搜索分页返回", en: "Douyin search page returned", tw: "抖音搜尋分頁返回" },
  { zh: "抖音用户搜索返回", en: "Douyin user search returned", tw: "抖音使用者搜尋返回" },
  { zh: "记录抖音用户搜索返回结构", en: "Recorded Douyin user search response shape", tw: "記錄抖音使用者搜尋返回結構" },
  { zh: "准备下载抖音资源", en: "Preparing Douyin resource download", tw: "準備下載抖音資源" },
  { zh: "快手分享链接已通过 HTTP 直连解析并提交到下载队列", en: "Kuaishou share link parsed through direct HTTP and submitted to the queue", tw: "快手分享連結已透過 HTTP 直連解析並提交到下載佇列" },
  { zh: "快手分享链接已解析并提交到下载队列", en: "Kuaishou share link parsed and submitted to the queue", tw: "快手分享連結已解析並提交到下載佇列" },
  { zh: "快手任务选择已确认", en: "Kuaishou task selection confirmed", tw: "快手任務選擇已確認" },
  { zh: "快手视频流已捕获并提交到下载队列", en: "Kuaishou video stream captured and submitted to the queue", tw: "快手影片串流已捕獲並提交到下載佇列" },
  { zh: "快手流捕获流水线结束", en: "Kuaishou stream capture pipeline finished", tw: "快手串流捕獲流水線結束" },
  { zh: "准备下载快手视频流", en: "Preparing Kuaishou video stream download", tw: "準備下載快手影片串流" },
  { zh: "快手视频下载完成", en: "Kuaishou video download completed", tw: "快手影片下載完成" },
  { zh: "优先尝试通过 HTTP 快速解析快手分享详情...", en: "Trying fast HTTP parsing for Kuaishou share details first...", tw: "優先嘗試透過 HTTP 快速解析快手分享詳情..." },
  { zh: "正在从快手分享详情页捕获单条作品...", en: "Capturing a single item from the Kuaishou share detail page...", tw: "正在從快手分享詳情頁擷取單項作品..." },
  { zh: "检测到快手分享/详情链接，使用静默单资源解析流程", en: "Kuaishou share/detail link detected; using the silent single-resource parsing flow", tw: "偵測到快手分享/詳情連結，使用靜默單資源解析流程" },
  { zh: "HTTP 未获得视频直链，切换无头浏览器继续解析", en: "HTTP did not return a direct video URL; switching to a headless browser to continue parsing", tw: "HTTP 未取得影片直連，切換無頭瀏覽器繼續解析" },
  { zh: "页面访问第 ", en: "Page navigation load attempt ", tw: "頁面造訪載入嘗試 " },
  { zh: "打开快手搜索页第 ", en: "Opening the Kuaishou search page, load attempt ", tw: "開啟快手搜尋頁載入嘗試 " },
  { zh: "打开快手目标页第 ", en: "Opening the Kuaishou target page, load attempt ", tw: "開啟快手目標頁載入嘗試 " },
  { zh: " 次加载返回网络错误页", en: " returned a network error page", tw: " 次載入傳回網路錯誤頁" },
  { zh: "快手服务端判定本地登录态无效，需要重新登录", en: "The Kuaishou service rejected the local login state; log in again", tw: "快手服務端判定本機登入狀態無效，需要重新登入" },
  { zh: "快手页面连续加载失败，已停止本次登录等待；请稍后重试", en: "The Kuaishou page repeatedly failed to load; login waiting stopped; try again later", tw: "快手頁面連續載入失敗，已停止本次登入等待；請稍後重試" },
  { zh: "快手登录态快照缺少既有认证 Cookie，已保留原登录文件", en: "Kuaishou login-state snapshot lacked the existing authentication Cookie; the original login file was preserved", tw: "快手登入狀態快照缺少既有認證 Cookie，已保留原登入檔案" },
  { zh: "已加载本地 Cookie，短暂等待后重新校验登录态", en: "Loaded local Cookie; waiting briefly before rechecking login status", tw: "已載入本機 Cookie，短暫等待後重新校驗登入狀態" },
  { zh: "复检后检测到登录状态", en: "Login status detected after recheck", tw: "複檢後偵測到登入狀態" },
  { zh: "服务端暂未确认登录态，保留原登录文件", en: "The server has not confirmed the login status yet; preserving the original login file", tw: "服務端暫未確認登入狀態，保留原登入檔案" },
  { zh: "快手分享页读取超过总时间预算，将回退浏览器链路", en: "Kuaishou share-page retrieval exceeded the total time budget; falling back to the browser flow", tw: "快手分享頁讀取超過總時間預算，將回退瀏覽器流程" },
  { zh: "快手分享页 HTML 超过解析预算，将回退浏览器链路", en: "Kuaishou share-page HTML exceeded the parsing budget; falling back to the browser flow", tw: "快手分享頁 HTML 超過解析預算，將回退瀏覽器流程" },
  { zh: "启动小红书爬虫任务", en: "Started Xiaohongshu crawl task", tw: "啟動小紅書爬蟲任務" },
  { zh: "小红书爬虫运行异常", en: "Xiaohongshu crawl runtime error", tw: "小紅書爬蟲執行異常" },
  { zh: "小红书爬虫任务结束", en: "Xiaohongshu crawl task finished", tw: "小紅書爬蟲任務結束" },
  { zh: "小红书视频下载失败", en: "Xiaohongshu video download failed", tw: "小紅書影片下載失敗" },
  { zh: "MissAV m3u8 嗅探成功并提交下载", en: "MissAV m3u8 sniffed successfully and submitted for download", tw: "MissAV m3u8 嗅探成功並提交下載" },
  { zh: "MissAV 详情页嗅探超时，未发现 playlist.m3u8", en: "MissAV detail page sniff timed out; playlist.m3u8 was not found", tw: "MissAV 詳情頁嗅探逾時，未發現 playlist.m3u8" },
  { zh: "MissAV 详情页加载失败", en: "MissAV detail page failed to load", tw: "MissAV 詳情頁載入失敗" },
  { zh: "未找到可用的系统 Chrome/Edge，改用内置浏览器", en: "No usable system Chrome/Edge was found; using the bundled browser", tw: "未找到可用的系統 Chrome/Edge，改用內建瀏覽器" },
  { zh: "Cloudflare 可能拒绝过旧内核", en: "Cloudflare may reject an outdated browser engine", tw: "Cloudflare 可能拒絕過舊核心" },
  { zh: "Cloudflare 不支持当前浏览器环境，请更新系统 Chrome/Edge 后重试", en: "Cloudflare does not support the current browser environment; update system Chrome/Edge and try again", tw: "Cloudflare 不支援目前瀏覽器環境，請更新系統 Chrome/Edge 後重試" },
  { zh: "检测到 Cloudflare，请在浏览器中完成人工验证...", en: "Cloudflare detected; complete the manual verification in the browser...", tw: "偵測到 Cloudflare，請在瀏覽器中完成人工驗證..." },
  { zh: "Cloudflare 验证已通过", en: "Cloudflare verification passed", tw: "Cloudflare 驗證已通過" },
  { zh: "Cloudflare 验证等待超时", en: "Cloudflare verification timed out", tw: "Cloudflare 驗證等待逾時" },
  { zh: "MissAV 人工验证使用系统", en: "MissAV manual verification is using system", tw: "MissAV 人工驗證使用系統" },
  { zh: "MissAV 已接管系统浏览器", en: "MissAV attached to the system browser", tw: "MissAV 已接管系統瀏覽器" },
  { zh: "未找到系统 Chrome/Edge，改用 Playwright 浏览器", en: "No system Chrome/Edge was found; using the Playwright browser", tw: "未找到系統 Chrome/Edge，改用 Playwright 瀏覽器" },
  { zh: "准备下载 MissAV HLS 流", en: "Preparing MissAV HLS stream download", tw: "準備下載 MissAV HLS 串流" },
  { zh: "正在尝试以 curl_cffi 浏览器模拟方式下载 MissAV HLS", en: "Trying curl_cffi browser-impersonated HLS download for MissAV", tw: "正在嘗試以 curl_cffi 瀏覽器模擬方式下載 MissAV HLS" },
  { zh: "正在尝试以 Playwright 浏览器上下文下载 MissAV HLS", en: "Trying Playwright browser-context HLS download for MissAV", tw: "正在嘗試以 Playwright 瀏覽器上下文下載 MissAV HLS" },
  { zh: "准备 N_m3u8DL-RE HLS 下载", en: "Preparing N_m3u8DL-RE HLS download", tw: "準備 N_m3u8DL-RE HLS 下載" },
  { zh: "N_m3u8DL-RE 下载完成", en: "N_m3u8DL-RE download finished", tw: "N_m3u8DL-RE 下載完成" },
  { zh: "已为受保护的 MissAV 流启动本地 HLS 代理", en: "Started local HLS proxy for protected MissAV stream", tw: "已為受保護的 MissAV 串流啟動本機 HLS 代理" },
  { zh: "应用启动时已清理过期 HLS 工作区", en: "Swept stale HLS workspaces at application startup", tw: "應用啟動時已清理過期 HLS 工作區" },
  { zh: "yt-dlp 回退在无模拟模式下成功", en: "yt-dlp fallback succeeded without impersonation", tw: "yt-dlp 回退在無模擬模式下成功" },
  { zh: "ffmpeg 下载前检查真实地址", en: "ffmpeg checked real URL before download", tw: "ffmpeg 下載前檢查真實位址" },
  { zh: "准备调用 ffmpeg 执行下载", en: "Preparing to call ffmpeg for download", tw: "準備呼叫 ffmpeg 執行下載" },
  { zh: "ffmpeg 下载完成", en: "ffmpeg download completed", tw: "ffmpeg 下載完成" },
  { zh: "应用开始初始化", en: "App initialization started", tw: "應用開始初始化" },
  { zh: "主窗口初始化完成", en: "Main window initialization completed", tw: "主視窗初始化完成" },
  { zh: "应用开始退出清理", en: "Application shutdown cleanup started", tw: "應用開始退出清理" },
  { zh: "用户启动爬虫任务", en: "User started crawl task", tw: "使用者啟動爬蟲任務" },
  { zh: "用户取消任务选择，停止爬虫任务", en: "User cancelled task selection; crawl task stopped", tw: "使用者取消任務選擇，已停止爬蟲任務" },
  { zh: "用户请求停止爬虫任务", en: "User requested to stop the crawl task", tw: "使用者要求停止爬蟲任務" },
  { zh: "用户取消下载", en: "User cancelled download", tw: "使用者取消下載" },
  { zh: "远程主机强迫关闭了一个现有的连接。", en: "The remote host forcibly closed an existing connection.", tw: "遠端主機強制關閉了一個現有連線。" },
  { zh: "远程主机强迫关闭了一个现有的连接", en: "The remote host forcibly closed an existing connection", tw: "遠端主機強制關閉了一個現有連線" },
  { zh: "保存目录已变更", en: "Save directory changed", tw: "儲存目錄已變更" },
  { zh: "仅下载视频模式已跳过非视频资源", en: "Video-only mode skipped a non-video resource", tw: "僅下載影片模式已略過非影片資源" },
  { zh: "仅下载视频模式已跳过非视频资源", en: "Video-only mode skipped non-video resource", tw: "僅下載影片模式已略過非影片資源" },
  { zh: "已通过重建分发信号量提高并发容量", en: "Increased concurrency by rebuilding dispatch semaphore capacity.", tw: "已透過重建分發信號量提高並發容量" },
  { zh: "已降低并发：现有下载线程将在完成后自然收尾", en: "Reduced concurrency: existing download workers will wind down as they complete.", tw: "已降低並發：現有下載執行緒將在完成後自然收尾" },
  { zh: "图片快速通道已关闭：现有轻量线程将在完成后自然收尾", en: "Image fast lane disabled: existing lightweight workers will wind down as they complete.", tw: "圖片快速通道已關閉：現有輕量執行緒將在完成後自然收尾" },
  { zh: "已从活动并发统计中清理过期完成线程", en: "Pruned stale completed workers from active concurrency accounting.", tw: "已從活動並發統計中清理過期完成執行緒" },
  { zh: "下载管理器正在停止，清理队列和线程", en: "Download manager stopping, draining queue and workers", tw: "下載管理器正在停止，清理佇列和執行緒" },
  { zh: "分发线程未能在 2 秒内停止", en: "Dispatcher thread failed to stop within 2 seconds", tw: "分發執行緒未能在 2 秒內停止" },
  { zh: "并发重建后，过期分发信号量令牌无法归还", en: "Stale dispatch semaphore token could not be returned after concurrency rebuild.", tw: "並發重建後，過期分發信號量權杖無法歸還" },
  { zh: "已跳过下载槽位释放，因为信号量容量已满", en: "Download slot release skipped because semaphore capacity is already full", tw: "已略過下載槽位釋放，因為信號量容量已滿" },
  { zh: "下载线程停止超时，正在强制清理", en: "Worker stop timeout reached; forcing shutdown cleanup", tw: "下載執行緒停止逾時，正在強制清理" },
  { zh: "AppState 变更事件因发布递归超过安全限制而被丢弃", en: "AppState change event dropped because publish recursion exceeded the safety limit", tw: "AppState 變更事件因發布遞迴超過安全限制而被丟棄" },
  { zh: "已丢弃媒体元数据探测结果：条目已不存在", en: "Completed media metadata probe result was discarded because the item no longer exists", tw: "已丟棄媒體中繼資料探測結果：項目已不存在" },
  { zh: "已丢弃媒体元数据探测结果：本地路径已变化", en: "Completed media metadata probe result was discarded because the local path changed", tw: "已丟棄媒體中繼資料探測結果：本機路徑已變更" },
  { zh: "媒体元数据探测已完成，但未获得可用时长或分辨率", en: "Completed media metadata probe finished without usable duration or resolution", tw: "媒體中繼資料探測已完成，但未取得可用時長或解析度" },
  { zh: "本地媒体元数据探测完成，但未获得可用时长或分辨率", en: "Local media metadata probe finished without usable duration or resolution", tw: "本機媒體中繼資料探測完成，但未取得可用時長或解析度" },
  { zh: "分块线程仍在运行，已延后清理临时文件", en: "Deferred temp-file cleanup because chunk worker threads are still running", tw: "分塊執行緒仍在執行，已延後清理暫存檔" },
  { zh: "已跳过 N_m3u8DL-RE 临时目录清理：目录不在受控工作区内", en: "Skip N_m3u8DL-RE temp cleanup because the directory is outside the owned workspace", tw: "已略過 N_m3u8DL-RE 暫存目錄清理：目錄不在受控工作區內" },
  { zh: "MissAV 浏览器 HLS 在缓存播放列表后失败，已跳过可能再次触发 403 的网络播放列表回退", en: "MissAV browser HLS failed after cached playlist; skipping network playlist fallback that would re-hit 403", tw: "MissAV 瀏覽器 HLS 在快取播放清單後失敗，已略過可能再次觸發 403 的網路播放清單回退" },
  { zh: "MissAV 浏览器 HLS 失败，跳过 N_m3u8DL-RE 前尝试 yt-dlp", en: "MissAV browser HLS failed; trying yt-dlp before skipping N_m3u8DL-RE", tw: "MissAV 瀏覽器 HLS 失敗，略過 N_m3u8DL-RE 前嘗試 yt-dlp" },
  { zh: "N_m3u8DL-RE 失败，正在尝试 yt-dlp 模拟回退", en: "N_m3u8DL-RE failed; trying yt-dlp impersonation fallback", tw: "N_m3u8DL-RE 失敗，正在嘗試 yt-dlp 模擬回退" },
  { zh: "Web 事件循环不可用，已延后前端增量刷新", en: "Web event loop is unavailable; deferred frontend delta until a later async flush.", tw: "Web 事件迴圈不可用，已延後前端增量刷新" },
  { zh: "没有可用事件循环，已跳过前端增量刷新", en: "Skipped frontend delta flush because no running event loop is available.", tw: "沒有可用事件迴圈，已略過前端增量刷新" },
  { zh: "默认打开方式已生效", en: "Default open mode is active", tw: "預設開啟方式已生效" },
  { zh: "未选择需要注册的资源类型", en: "No resource type selected for registration", tw: "未選擇需要註冊的資源類型" },
  { zh: "文件关联注册未完成", en: "File association registration was not completed", tw: "檔案關聯註冊未完成" },
  { zh: "已设置默认打开方式", en: "Default open mode has been set", tw: "已設定預設開啟方式" },
  { zh: "部分默认打开方式设置失败", en: "Some default open mode settings failed", tw: "部分預設開啟方式設定失敗" },
  { zh: "仍需在 Windows 默认应用中确认", en: "Still needs confirmation in Windows Default Apps", tw: "仍需在 Windows 預設應用程式中確認" },
  { zh: "已打开 Windows 默认应用设置，请手动确认剩余默认打开方式", en: "Opened Windows Default Apps settings; please confirm the remaining default open modes manually", tw: "已開啟 Windows 預設應用程式設定，請手動確認剩餘預設開啟方式" },
  { zh: "请手动打开 Windows 默认应用设置，确认剩余默认打开方式", en: "Please open Windows Default Apps settings manually and confirm the remaining default open modes", tw: "請手動開啟 Windows 預設應用程式設定，確認剩餘預設開啟方式" },
  { zh: "自动打开下载结果失败", en: "Failed to open the downloaded result automatically", tw: "自動開啟下載結果失敗" },
  { zh: "上次任务未正常结束，正在清理", en: "The previous task did not end cleanly; cleaning up", tw: "上次任務未正常結束，正在清理" },
  { zh: "当前已有任务在运行，请先停止或等待结束", en: "A task is already running; stop it or wait for it to finish first", tw: "目前已有任務執行中，請先停止或等待結束" },
  { zh: "未知的爬虫源", en: "Unknown crawler source", tw: "未知的爬蟲來源" },
  { zh: "创建爬虫失败", en: "Failed to create crawler", tw: "建立爬蟲失敗" },
  { zh: "启动爬虫失败", en: "Failed to start crawler", tw: "啟動爬蟲失敗" },
  { zh: "正在停止任务", en: "Stopping task", tw: "正在停止任務" },
  { zh: "扫描目录出错", en: "Directory scan failed", tw: "掃描目錄出錯" },
  { zh: "目录已变更", en: "Directory changed", tw: "目錄已變更" },
  { zh: "重命名失败", en: "Rename failed", tw: "重新命名失敗" },
  { zh: "删除文件失败", en: "File deletion failed", tw: "刪除檔案失敗" },
  { zh: "文件不存在或已被删除", en: "File does not exist or has been deleted", tw: "檔案不存在或已被刪除" },
  { zh: "播放:", en: "Playing:", tw: "播放：" },
  { zh: "已清空下载队列", en: "Download queue cleared", tw: "已清空下載佇列" },
  { zh: "已删除", en: "Deleted", tw: "已刪除" },
  { zh: "已从下载队列移除，已省略逐条日志", en: "items were removed from the download queue; per-item logs were omitted", tw: "項已從下載佇列移除，已省略逐條日誌" },
  { zh: "已播放到最后一项", en: "Already at the last item", tw: "已播放到最後一項" },
  { zh: "队列为空，没有可切换的资源", en: "The queue is empty; there is no resource to switch to", tw: "佇列為空，沒有可切換的資源" },
  { zh: "清空队列失败", en: "Clear queue failed", tw: "清空佇列失敗" },
  { zh: "任务已终止", en: "Task terminated", tw: "任務已終止" },
  { zh: "浏览器已关闭，无法继续需要网页的操作", en: "Browser is closed; cannot continue operations that require a web page", tw: "瀏覽器已關閉，無法繼續需要網頁的操作" },
  { zh: "抓取已停止，已保留", en: "Crawl stopped; kept", tw: "抓取已停止，已保留" },
  { zh: "准备生成清单", en: "preparing to generate the list", tw: "準備生成清單" },
  { zh: "用户取消了任务", en: "User cancelled the task", tw: "使用者取消了任務" },
  { zh: "未选择有效平台", en: "No valid platform selected", tw: "未選擇有效平台" },
  { zh: "请先选择一个任务", en: "Please select a task first", tw: "請先選擇一個任務" },
  { zh: "配置读取错误", en: "Failed to read configuration", tw: "設定讀取錯誤" },
  { zh: "保存目录更新失败", en: "Failed to update save directory", tw: "儲存目錄更新失敗" },
  { zh: "任务清单对话框打开失败", en: "Failed to open the task list dialog", tw: "任務清單對話框開啟失敗" },
  { zh: "下载选项已更新", en: "Download options updated", tw: "下載選項已更新" },
  { zh: "下载选项更新失败", en: "download options update failed", tw: "下載選項更新失敗" },
  { zh: "save_dir 必须是字符串", en: "save_dir must be a string", tw: "save_dir 必須是字串" },
  { zh: "directory 必须是字符串", en: "directory must be a string", tw: "directory 必須是字串" },
  { zh: "目录路径不能为空", en: "Directory path cannot be empty", tw: "目錄路徑不能為空" },
  { zh: "dark_theme 必须是布尔值", en: "dark_theme must be a boolean", tw: "dark_theme 必須是布林值" },
  { zh: "source 必须是字符串", en: "source must be a string", tw: "source 必須是字串" },
  { zh: "section 和 key 必须是字符串", en: "section and key must be strings", tw: "section 和 key 必須是字串" },
  { zh: "video_id 必须是字符串", en: "video_id must be a string", tw: "video_id 必須是字串" },
  { zh: "video_id 和 new_title 必须是字符串", en: "video_id and new_title must be strings", tw: "video_id 和 new_title 必須是字串" },
  { zh: "frontend_action 参数非法", en: "Invalid frontend_action parameter", tw: "frontend_action 參數不合法" },
  { zh: "frontend action 不可用", en: "Frontend action is unavailable", tw: "frontend action 不可用" },
  { zh: "scan_limit 必须是整数", en: "scan_limit must be an integer", tw: "scan_limit 必須是整數" },
  { zh: "scan_limit 必须大于 0", en: "scan_limit must be greater than 0", tw: "scan_limit 必須大於 0" },
  { zh: "scan_limit 不能大于", en: "scan_limit cannot be greater than", tw: "scan_limit 不能大於" },
  { zh: "无效平台", en: "Invalid platform", tw: "無效平台" },
  { zh: "支持", en: "supported", tw: "支援" },
  { zh: "保存配置失败", en: "Failed to save configuration", tw: "儲存設定失敗" },
  { zh: "该配置项不允许通过 Web 修改", en: "This setting cannot be changed from the WebUI", tw: "此設定不允許透過 WebUI 修改" },
  { zh: "使用代理", en: "Using proxy", tw: "使用代理" },
  { zh: "爬虫错误", en: "Crawler error", tw: "爬蟲錯誤" },
  { zh: "加载本地 Cookie 成功", en: "Loaded local Cookie successfully", tw: "載入本機 Cookie 成功" },
  { zh: "本地 Cookie 加载失败", en: "Failed to load local Cookie", tw: "本機 Cookie 載入失敗" },
  { zh: "已加载本地 Cookie，尝试刷新页面重新校验登录态", en: "Loaded local Cookie; refreshing the page to re-check login status", tw: "已載入本機 Cookie，嘗試重新整理頁面以重新校驗登入狀態" },
  { zh: "本地 Cookie 已加载，但当前页面未识别为已登录，可能已失效", en: "Local Cookie was loaded, but the current page is not logged in and it may have expired", tw: "本機 Cookie 已載入，但目前頁面未識別為已登入，可能已失效" },
  { zh: "检测到登录状态", en: "Login status detected", tw: "偵測到登入狀態" },
  { zh: "刷新后检测到登录状态", en: "Login status detected after refresh", tw: "重新整理後偵測到登入狀態" },
  { zh: "登录成功，Cookie 已保存", en: "Login successful; Cookie saved", tw: "登入成功，Cookie 已儲存" },
  { zh: "已完成扫码登录", en: "QR-code login completed", tw: "已完成掃碼登入" },
  { zh: "扫码成功，Cookie 已保存", en: "QR-code login succeeded; Cookie saved", tw: "掃碼成功，Cookie 已儲存" },
  { zh: "未登录或 Cookie 失效，启动扫码", en: "Not logged in or Cookie expired; starting QR-code login", tw: "未登入或 Cookie 失效，啟動掃碼" },
  { zh: "请在当前快手页面手动登录或扫码，登录成功后程序会自动继续", en: "Please log in or scan the code on the current Kuaishou page; the program will continue automatically after login", tw: "請在目前快手頁面手動登入或掃碼，登入成功後程式會自動繼續" },
  { zh: "静默模式检测到快手登录态不可用，将打开登录窗口；登录后会重新静默执行当前任务", en: "Silent mode detected that Kuaishou login is unavailable; a login window will open and the task will rerun silently after login", tw: "靜默模式偵測到快手登入狀態不可用，將開啟登入視窗；登入後會重新靜默執行目前任務" },
  { zh: "正在打开快手登录窗口", en: "Opening Kuaishou login window", tw: "正在開啟快手登入視窗" },
  { zh: "已自动打开快手扫码登录弹窗", en: "Opened the Kuaishou QR-code login popup automatically", tw: "已自動開啟快手掃碼登入彈窗" },
  { zh: "未能自动弹出登录框，请直接在当前快手页面手动登录", en: "Could not open the login popup automatically; please log in manually on the current Kuaishou page", tw: "未能自動彈出登入框，請直接在目前快手頁面手動登入" },
  { zh: "登录失败，以游客身份爬取", en: "Login failed; crawling as guest", tw: "登入失敗，將以訪客身分抓取" },
  { zh: "已切换到浅色主题", en: "Switched to light theme", tw: "已切換到淺色主題" },
  { zh: "已切换到深色主题", en: "Switched to dark theme", tw: "已切換到深色主題" },
  { zh: "该目录下没有找到视频或图片", en: "No videos or images found in this directory", tw: "該目錄下沒有找到影片或圖片" },
  { zh: "线程未在", en: "thread did not exit within", tw: "執行緒未在" },
  { zh: "跳过继续收尾", en: "skipping and continuing cleanup", tw: "略過並繼續收尾" },
  { zh: "获取流失败", en: "Failed to fetch stream", tw: "取得串流失敗" },
  { zh: "未检测到登录，启动浏览器扫码", en: "Login not detected; starting browser QR-code login", tw: "未偵測到登入，啟動瀏覽器掃碼" },
  { zh: "爬虫已停止，跳过结果选择", en: "Crawler stopped; skipping result selection", tw: "爬蟲已停止，略過結果選擇" },
  { zh: "未找到任何有效视频", en: "No valid videos found", tw: "未找到任何有效影片" },
  { zh: "已达到视频数上限", en: "Reached the video count limit", tw: "已達到影片數上限" },
  { zh: "剩余选择不会进入下载队列", en: "remaining selections will not enter the download queue", tw: "剩餘選擇不會進入下載佇列" },
  { zh: "短链解析失败", en: "Short-link parsing failed", tw: "短連結解析失敗" },
  { zh: "短链解析", en: "Short-link parsing", tw: "短連結解析" },
  { zh: "Bilibili API 失败，尝试网页兜底扫描", en: "Bilibili API failed; trying web fallback scan", tw: "Bilibili API 失敗，嘗試網頁兜底掃描" },
  { zh: "Bilibili 扫描 Cookie 恢复失败，继续匿名扫描", en: "Failed to restore Bilibili scan Cookie; continuing anonymous scan", tw: "Bilibili 掃描 Cookie 恢復失敗，繼續匿名掃描" },
  { zh: "静态搜索页", en: "static search page", tw: "靜態搜尋頁" },
  { zh: "扫描异常", en: "Scan error", tw: "掃描異常" },
  { zh: "请在弹出的窗口中扫码登录", en: "Please scan the QR code in the popup window", tw: "請在彈出的視窗中掃碼登入" },
  { zh: "登录状态校验失败，尝试继续执行", en: "Login status check failed; trying to continue", tw: "登入狀態校驗失敗，嘗試繼續執行" },
  { zh: "已按视频数上限", en: "Trimmed by video count limit", tw: "已依影片數上限" },
  { zh: "裁剪可选分集", en: "trimmed selectable episodes", tw: "裁剪可選分集" },
  { zh: "Bilibili 网页兜底解析失败", en: "Bilibili web fallback parsing failed", tw: "Bilibili 網頁兜底解析失敗" },
  { zh: "Bilibili 页面不可用，跳过浏览器候选扫描", en: "Bilibili page is unavailable, skip browser candidate scan", tw: "Bilibili 頁面不可用，略過瀏覽器候選掃描" },
  { zh: "Bilibili 静态搜索页解析失败", en: "Bilibili static search page parsing failed", tw: "Bilibili 靜態搜尋頁解析失敗" },
  { zh: "已聚合", en: "Aggregated", tw: "已彙整" },
  { zh: "有效资源", en: "valid resources", tw: "有效資源" },
  { zh: "停止继续抓取", en: "stopped further crawling", tw: "停止繼續抓取" },
  { zh: "检测到 UP 主", en: "Detected UP owner", tw: "偵測到 UP 主" },
  { zh: "视频信息解析失败", en: "Video info parsing failed", tw: "影片資訊解析失敗" },
  { zh: "API 处理异常", en: "API processing error", tw: "API 處理異常" },
  { zh: "Bilibili API 未返回可用视频信息", en: "Bilibili API did not return usable video information", tw: "Bilibili API 未返回可用影片資訊" },
  { zh: "仅保留前", en: "keeping only the first", tw: "僅保留前" },
  { zh: "供选择", en: "for selection", tw: "供選擇" },
  { zh: "检查本地 Cookie 文件", en: "Checking local Cookie file", tw: "檢查本機 Cookie 檔案" },
  { zh: "正在启动独立登录进程", en: "Starting independent login process", tw: "正在啟動獨立登入程序" },
  { zh: "Cookie 将保存到", en: "Cookie will be saved to", tw: "Cookie 將儲存到" },
  { zh: "登录失败详情", en: "Login failure details", tw: "登入失敗詳情" },
  { zh: "无法识别的链接格式", en: "Unrecognized link format", tw: "無法識別的連結格式" },
  { zh: "请使用以下格式", en: "Please use one of the following formats", tw: "請使用以下格式" },
  { zh: "用户主页链接", en: "User homepage link", tw: "使用者主頁連結" },
  { zh: "分享链接", en: "Share link", tw: "分享連結" },
  { zh: "识别到", en: "Detected", tw: "識別到" },
  { zh: "个作品 ID，开始获取详情", en: "work IDs; fetching details", tw: "個作品 ID，開始取得詳情" },
  { zh: "识别到用户 SecUID", en: "Detected user SecUID", tw: "識別到使用者 SecUID" },
  { zh: "开始爬取主页", en: "starting homepage crawl", tw: "開始抓取主頁" },
  { zh: "识别到合集 ID", en: "Detected collection ID", tw: "識別到合集 ID" },
  { zh: "搜索关键词", en: "Search keyword", tw: "搜尋關鍵字" },
  { zh: "正在搜索用户", en: "Searching user", tw: "正在搜尋使用者" },
  { zh: "用户搜索无结果，尝试其他方法", en: "User search returned no results; trying other methods", tw: "使用者搜尋無結果，嘗試其他方法" },
  { zh: "无法找到用户", en: "Could not find user", tw: "無法找到使用者" },
  { zh: "抖音纯数字 UID 无法直接搜索，请使用以下方式", en: "Douyin numeric UID cannot be searched directly; please use one of these methods", tw: "抖音純數字 UID 無法直接搜尋，請使用以下方式" },
  { zh: "输入用户主页链接", en: "Enter a user homepage link", tw: "輸入使用者主頁連結" },
  { zh: "输入用户昵称进行搜索", en: "Enter a user nickname to search", tw: "輸入使用者暱稱進行搜尋" },
  { zh: "在抖音 APP 中复制分享链接", en: "Copy the share link in the Douyin app", tw: "在抖音 APP 中複製分享連結" },
  { zh: "扫描完成，共", en: "Scan completed, total", tw: "掃描完成，共" },
  { zh: "请选择", en: "please select", tw: "請選擇" },
  { zh: "选中", en: "Selected", tw: "已選擇" },
  { zh: "无法获取 Cookie，任务终止", en: "Could not get Cookie; task terminated", tw: "無法取得 Cookie，任務終止" },
  { zh: "Cookie 文件不存在", en: "Cookie file does not exist", tw: "Cookie 檔案不存在" },
  { zh: "扫码登录成功", en: "QR-code login succeeded", tw: "掃碼登入成功" },
  { zh: "正在解析链接重定向", en: "Resolving link redirect", tw: "正在解析連結重定向" },
  { zh: "识别为可能的抖音号", en: "Detected possible Douyin ID", tw: "識別為可能的抖音號" },
  { zh: "尝试搜索", en: "trying search", tw: "嘗試搜尋" },
  { zh: "尝试将 modal_id", en: "Trying modal_id", tw: "嘗試將 modal_id" },
  { zh: "作为合集解析", en: "as a collection", tw: "作為合集解析" },
  { zh: "获取作品详情失败", en: "Failed to fetch work details", tw: "取得作品詳情失敗" },
  { zh: "正在获取第", en: "Fetching page", tw: "正在取得第" },
  { zh: "未找到公开作品", en: "No public works found", tw: "未找到公開作品" },
  { zh: "未找到作品或ID无效", en: "found no works or the ID is invalid", tw: "未找到作品或 ID 無效" },
  { zh: "搜索第", en: "Searching page", tw: "搜尋第" },
  { zh: "个匹配用户", en: "matching users", tw: "個匹配使用者" },
  { zh: "尝试作为 sec_user_id 访问", en: "Trying to access as sec_user_id", tw: "嘗試以 sec_user_id 存取" },
  { zh: "尝试请求用户主页获取 sec_user_id", en: "Trying to request the user homepage to get sec_user_id", tw: "嘗試請求使用者主頁以取得 sec_user_id" },
  { zh: "未找到有效视频", en: "No valid videos found", tw: "未找到有效影片" },
  { zh: "运行时异常", en: "Runtime error", tw: "執行階段異常" },
  { zh: "本地 Cookie 缺少 sessionid_ss，可能已过期", en: "Local Cookie is missing sessionid_ss and may have expired", tw: "本機 Cookie 缺少 sessionid_ss，可能已過期" },
  { zh: "登录成功但 Cookie 缺少 sessionid_ss", en: "Login succeeded but Cookie is missing sessionid_ss", tw: "登入成功但 Cookie 缺少 sessionid_ss" },
  { zh: "搜索异常", en: "Search error", tw: "搜尋異常" },
  { zh: "从 HTML 提取到 sec_user_id", en: "Extracted sec_user_id from HTML", tw: "已從 HTML 提取 sec_user_id" },
  { zh: "主页请求失败", en: "Homepage request failed", tw: "主頁請求失敗" },
  { zh: "Cookie 文件存在但内容为空", en: "Cookie file exists but is empty", tw: "Cookie 檔案存在但內容為空" },
  { zh: "登录成功但 Cookie 文件为空", en: "Login succeeded but the Cookie file is empty", tw: "登入成功但 Cookie 檔案為空" },
  { zh: "Cookie 读取成功，可以开始下载", en: "Cookie loaded; ready to download", tw: "Cookie 讀取成功，可以開始下載" },
  { zh: "登录态读取失败", en: "Failed to read login status", tw: "登入狀態讀取失敗" },
  { zh: "找到用户", en: "Found user", tw: "找到使用者" },
  { zh: "找到多个用户，请选择", en: "Found multiple users; please select", tw: "找到多個使用者，請選擇" },
  { zh: "用户取消选择", en: "User cancelled selection", tw: "使用者取消選擇" },
  { zh: "获取用户", en: "Fetching user", tw: "取得使用者" },
  { zh: "快手分享页未解析到 __APOLLO_STATE__ 视频直链，将回退浏览器链路", en: "Kuaishou share page did not yield a __APOLLO_STATE__ direct video URL; falling back to browser flow", tw: "快手分享頁未解析到 __APOLLO_STATE__ 影片直連，將回退瀏覽器流程" },
  { zh: "检测到快手分享/详情链接，优先尝试无浏览器直连解析", en: "Detected Kuaishou share/detail link; trying direct no-browser parsing first", tw: "偵測到快手分享/詳情連結，優先嘗試無瀏覽器直連解析" },
  { zh: "已无浏览器解析分享作品", en: "Parsed shared work without browser", tw: "已無瀏覽器解析分享作品" },
  { zh: "访问快手首页", en: "Visiting Kuaishou homepage", tw: "造訪快手首頁" },
  { zh: "访问快手页面", en: "Visiting Kuaishou page", tw: "造訪快手頁面" },
  { zh: "通过站内搜索查找", en: "Searching through site search", tw: "透過站內搜尋查找" },
  { zh: "无法执行快手关键词搜索", en: "Unable to run Kuaishou keyword search", tw: "無法執行快手關鍵字搜尋" },
  { zh: "未找到匹配的快手账号主页", en: "No matching Kuaishou account homepage found", tw: "未找到匹配的快手帳號主頁" },
  { zh: "检测到快手分享/详情链接，直接解析单条作品", en: "Detected Kuaishou share/detail link; parsing a single work directly", tw: "偵測到快手分享/詳情連結，直接解析單條作品" },
  { zh: "未能从快手分享链接中解析出可下载视频", en: "Could not parse a downloadable video from the Kuaishou share link", tw: "未能從快手分享連結解析出可下載影片" },
  {
    zh: "开始滚动加载列表... (点击【停止】生成清单)",
    en: "Starting to scroll and load the list... (click Stop to generate the list)",
    tw: "開始滾動載入列表...（點擊【停止】產生清單）"
  },
  { zh: "开始滚动加载列表", en: "Starting to scroll and load the list", tw: "開始滾動載入列表" },
  { zh: "点击【停止】生成清单", en: "click Stop to generate the list", tw: "點擊【停止】生成清單" },
  { zh: "解析视频信息", en: "Parsing video information", tw: "解析影片資訊" },
  { zh: "请选择下载", en: "please select downloads", tw: "請選擇下載" },
  { zh: "生产者工作开始", en: "Producer worker started", tw: "生產者工作開始" },
  { zh: "流程结束", en: "Flow finished", tw: "流程結束" },
  { zh: "未找到快手搜索框", en: "Kuaishou search box not found", tw: "未找到快手搜尋框" },
  { zh: "当前输入为纯数字，按快手号优先进入用户搜索结果", en: "Current input is numeric; prioritizing Kuaishou ID user search results", tw: "目前輸入為純數字，優先按快手號進入使用者搜尋結果" },
  { zh: "已解析分享作品", en: "Parsed shared work", tw: "已解析分享作品" },
  { zh: "无法加载视频列表", en: "Unable to load video list", tw: "無法載入影片列表" },
  { zh: "未扫描到有效视频", en: "No valid videos scanned", tw: "未掃描到有效影片" },
  { zh: "用户取消了下载任务", en: "User cancelled the download task", tw: "使用者取消了下載任務" },
  { zh: "详情页已关闭，无法启动捕获流水线", en: "Detail page is closed; cannot start capture pipeline", tw: "詳情頁已關閉，無法啟動擷取流水線" },
  { zh: "个视频未捕获", en: "videos were not captured", tw: "個影片未擷取" },
  { zh: "全部任务完成", en: "All tasks completed", tw: "全部任務完成" },
  { zh: "流水线启动", en: "pipeline started", tw: "流水線啟動" },
  { zh: "本地登录态加载失败，继续尝试页面登录", en: "Failed to load local login state; continuing with page login", tw: "本機登入狀態載入失敗，繼續嘗試頁面登入" },
  { zh: "加载本地登录态成功", en: "Loaded local login state successfully", tw: "已成功載入本機登入狀態" },
  { zh: "已保存登录态不兼容，改用空白浏览器上下文重新登录", en: "Saved login state is incompatible; signing in again with a clean browser context", tw: "已儲存的登入狀態不相容，改用空白瀏覽器內容重新登入" },
  { zh: "快手登录态保存失败", en: "Failed to save Kuaishou login state", tw: "快手登入狀態儲存失敗" },
  { zh: "快手分享详情页请求失败", en: "Kuaishou share detail page request failed", tw: "快手分享詳情頁請求失敗" },
  { zh: "首页访问或登录态检查失败，继续尝试在当前页面恢复登录", en: "Homepage access or login check failed; continuing to recover login on the current page", tw: "首頁存取或登入狀態檢查失敗，繼續嘗試在目前頁面恢復登入" },
  { zh: "无法执行快手站内搜索", en: "Unable to run Kuaishou site search", tw: "無法執行快手站內搜尋" },
  { zh: "点击搜索结果名字进入主页", en: "Clicking search result name to enter homepage", tw: "點擊搜尋結果名稱進入主頁" },
  { zh: "点击搜索结果头像进入主页", en: "Clicking search result avatar to enter homepage", tw: "點擊搜尋結果頭像進入主頁" },
  { zh: "点击用户卡片进入主页", en: "Clicking user card to enter homepage", tw: "點擊使用者卡片進入主頁" },
  { zh: "已加载全部视频", en: "Loaded all videos", tw: "已載入全部影片" },
  { zh: "加载中", en: "Loading", tw: "載入中" },
  { zh: "已扫描", en: "scanned", tw: "已掃描" },
  { zh: "无法进入详情页", en: "Unable to enter detail page", tw: "無法進入詳情頁" },
  { zh: "详情页已关闭，提前结束当前捕获流程", en: "Detail page is closed; ending current capture flow early", tw: "詳情頁已關閉，提前結束目前擷取流程" },
  { zh: "刷屏进度", en: "Swipe progress", tw: "刷屏進度" },
  { zh: "第", en: "page", tw: "第" },
  { zh: "次重试", en: "retry", tw: "次重試" },
  { zh: "已进入搜索结果视频列表", en: "Entered search result video list", tw: "已進入搜尋結果影片列表" },
  { zh: "已从搜索结果进入主页", en: "Entered homepage from search result", tw: "已從搜尋結果進入主頁" },
  { zh: "似乎卡住了，尝试回滚刷新", en: "Seems stuck; trying to scroll back and refresh", tw: "似乎卡住了，嘗試回滾刷新" },
  { zh: "所有任务已实时捕获，提前结束", en: "All tasks captured in real time; ending early", tw: "所有任務已即時擷取，提前結束" },
  { zh: "焦点匹配", en: "Focus match", tw: "焦點匹配" },
  { zh: "捕获", en: "Captured", tw: "擷取" },
  { zh: "加入下载队列", en: "added to download queue", tw: "加入下載佇列" },
  { zh: "快手登录完成，重新以静默模式执行当前任务", en: "Kuaishou login completed; rerunning the current task silently", tw: "快手登入完成，重新以靜默模式執行目前任務" },
  { zh: "加密流", en: "Encrypted stream", tw: "加密串流" },
  { zh: "匹配焦点", en: "matched focus", tw: "匹配焦點" },
  { zh: "按视频数上限裁剪", en: "Trimmed by video count limit", tw: "依影片數上限裁剪" },
  { zh: "偏好设置", en: "Preferences", tw: "偏好設定" },
  { zh: "单体", en: "single item", tw: "單體" },
  { zh: "优先级", en: "priority", tw: "優先級" },
  { zh: "扫描第", en: "Scanning page", tw: "掃描第" },
  { zh: "MissAV 输入已归一化", en: "MissAV input normalized", tw: "MissAV 輸入已正規化" },
  { zh: "构造搜索链接", en: "Building search link", tw: "建構搜尋連結" },
  { zh: "修正后 URL", en: "Corrected URL", tw: "修正後 URL" },
  { zh: "识别为单体视频链接", en: "Recognized as single-video link", tw: "識別為單體影片連結" },
  { zh: "识别为列表/分类链接", en: "Recognized as list/category link", tw: "識別為列表/分類連結" },
  { zh: "正在访问页面", en: "Visiting page", tw: "正在造訪頁面" },
  { zh: "个最佳版本", en: "best versions", tw: "個最佳版本" },
  { zh: "开始嗅探 m3u8", en: "starting m3u8 sniffing", tw: "開始嗅探 m3u8" },
  { zh: "停止翻页", en: "stopping pagination", tw: "停止翻頁" },
  { zh: "页面扫描异常", en: "Page scan error", tw: "頁面掃描異常" },
  { zh: "检测到 Cloudflare，等待通过", en: "Cloudflare detected; waiting to pass", tw: "偵測到 Cloudflare，等待通過" },
  { zh: "开始第一遍扫描", en: "Starting first scan", tw: "開始第一輪掃描" },
  { zh: "获取所有视频", en: "fetching all videos", tw: "取得所有影片" },
  { zh: "智能筛选中", en: "Smart filtering", tw: "智慧篩選中" },
  { zh: "候选", en: "candidates", tw: "候選" },
  { zh: "筛选后无有效结果", en: "No valid results after filtering", tw: "篩選後無有效結果" },
  { zh: "嗅探", en: "Sniffing", tw: "嗅探" },
  { zh: "任务结束，成功提交", en: "Task finished, submitted successfully", tw: "任務結束，成功提交" },
  { zh: "任务强制中止", en: "Task forcibly stopped", tw: "任務強制中止" },
  { zh: "未找到任何视频", en: "No videos found", tw: "未找到任何影片" },
  { zh: "开始第二遍扫描", en: "Starting second scan", tw: "開始第二輪掃描" },
  { zh: "校验中文字幕", en: "checking Chinese subtitles", tw: "校驗中文字幕" },
  { zh: "发现演员主页，自动跳转", en: "Actor homepage found; redirecting automatically", tw: "發現演員主頁，自動跳轉" },
  { zh: "跳转校验", en: "Redirect check", tw: "跳轉校驗" },
  { zh: "嗅探成功", en: "Sniff succeeded", tw: "嗅探成功" },
  { zh: "嗅探超时", en: "Sniff timed out", tw: "嗅探逾時" },
  { zh: "未找到 playlist.m3u8", en: "playlist.m3u8 not found", tw: "未找到 playlist.m3u8" },
  { zh: "页面加载错误", en: "Page load error", tw: "頁面載入錯誤" },
  { zh: "中文校验异常", en: "Chinese subtitle check error", tw: "中文字幕校驗異常" },
  { zh: "未找到可用的小红书 Cookie，启动浏览器采集会话", en: "No usable Xiaohongshu Cookie found; starting browser session capture", tw: "未找到可用的小紅書 Cookie，啟動瀏覽器擷取會話" },
  { zh: "已生成", en: "Generated", tw: "已產生" },
  { zh: "个小红书下载任务", en: "Xiaohongshu download tasks", tw: "個小紅書下載任務" },
  { zh: "共发现", en: "found total", tw: "共發現" },
  { zh: "个账号候选，请选择主页", en: "account candidates; please select a homepage", tw: "個帳號候選，請選擇主頁" },
  { zh: "正在搜索小红书账号", en: "Searching Xiaohongshu account", tw: "正在搜尋小紅書帳號" },
  { zh: "正在通过网页搜索小红书号", en: "Searching Xiaohongshu ID through web search", tw: "正在透過網頁搜尋小紅書號" },
  { zh: "小红书流水线模式", en: "Xiaohongshu pipeline mode", tw: "小紅書流水線模式" },
  { zh: "详情解析成功后立即投递下载队列", en: "submit to download queue immediately after detail parsing succeeds", tw: "詳情解析成功後立即投遞下載佇列" },
  { zh: "小红书流水线投递完成", en: "Xiaohongshu pipeline delivery completed", tw: "小紅書流水線投遞完成" },
  { zh: "共投递", en: "delivered total", tw: "共投遞" },
  { zh: "个下载项", en: "download items", tw: "個下載項" },
  { zh: "本地小红书 Cookie 已失效，已丢弃并准备重新登录", en: "Local Xiaohongshu Cookie expired; discarded and preparing to log in again", tw: "本機小紅書 Cookie 已失效，已丟棄並準備重新登入" },
  { zh: "无法确认本地小红书 Cookie 登录态，本次将重新获取会话", en: "Could not confirm local Xiaohongshu Cookie login status; reacquiring session this time", tw: "無法確認本機小紅書 Cookie 登入狀態，本次將重新取得會話" },
  { zh: "已加载本地小红书 Cookie", en: "Loaded local Xiaohongshu Cookie", tw: "已載入本機小紅書 Cookie" },
  { zh: "未能获取指定小红书笔记详情", en: "Failed to fetch the specified Xiaohongshu note detail", tw: "未能取得指定小紅書筆記詳情" },
  { zh: "正在搜索小红书", en: "Searching Xiaohongshu", tw: "正在搜尋小紅書" },
  { zh: "已发现", en: "found", tw: "已發現" },
  { zh: "页新增", en: "page added", tw: "頁新增" },
  { zh: "条候选", en: "candidates", tw: "條候選" },
  { zh: "正在读取小红书作者笔记列表", en: "Reading Xiaohongshu author note list", tw: "正在讀取小紅書作者筆記列表" },
  { zh: "已抓到", en: "collected", tw: "已抓到" },
  { zh: "用户取消了", en: "User cancelled", tw: "使用者取消了" },
  { zh: "账号选择流程", en: "account selection flow", tw: "帳號選擇流程" },
  { zh: "预搜索未提取到小红书账号候选，回退网页用户搜索", en: "Pre-search found no Xiaohongshu account candidates; falling back to web user search", tw: "預搜尋未提取到小紅書帳號候選，回退網頁使用者搜尋" },
  { zh: "未找到可处理的小红书结果", en: "No processable Xiaohongshu results found", tw: "未找到可處理的小紅書結果" },
  { zh: "未选择小红书项目；抓取结束，未加入下载队列。", en: "No XiaoHongShu items selected; crawl finished without queueing downloads.", tw: "未選擇小紅書項目；抓取結束，未加入下載佇列。" },
  { zh: "小红书选择已由用户取消。", en: "XiaoHongShu selection was cancelled by the user.", tw: "小紅書選擇已由使用者取消。" },
  { zh: "未能成功解析任何小红书笔记详情，全程未投递下载项", en: "Could not parse any Xiaohongshu note details; no download items were submitted", tw: "未能成功解析任何小紅書筆記詳情，全程未投遞下載項" },
  { zh: "小红书分享链接解析失败", en: "Xiaohongshu share link parsing failed", tw: "小紅書分享連結解析失敗" },
  { zh: "若页面要求登录，请在浏览器中完成登录；程序会继续等待会话稳定", en: "If the page asks for login, complete it in the browser; the program will keep waiting for the session to stabilize", tw: "若頁面要求登入，請在瀏覽器中完成登入；程式會繼續等待會話穩定" },
  { zh: "无法解析小红书笔记详情", en: "Unable to parse Xiaohongshu note details", tw: "無法解析小紅書筆記詳情" },
  { zh: "获取小红书笔记失败", en: "Failed to fetch Xiaohongshu note", tw: "取得小紅書筆記失敗" },
  { zh: "小红书号预搜索失败，回退到网页用户搜索", en: "Xiaohongshu ID pre-search failed; falling back to web user search", tw: "小紅書號預搜尋失敗，回退到網頁使用者搜尋" },
  { zh: "小红书输入已归一化", en: "Xiaohongshu input normalized", tw: "小紅書輸入已正規化" },
  { zh: "小红书登录态探活失败，继续尝试使用当前浏览器确认过的会话", en: "Xiaohongshu login probe failed; continuing with the current browser-confirmed session", tw: "小紅書登入狀態探活失敗，繼續嘗試使用目前瀏覽器確認過的會話" },
  { zh: "小红书任务失败", en: "Xiaohongshu task failed", tw: "小紅書任務失敗" },
  { zh: "小红书运行时异常", en: "Xiaohongshu runtime error", tw: "小紅書執行階段異常" },
  { zh: "小红书返回 461，触发限流冷却后继续", en: "Xiaohongshu returned 461; continuing after rate-limit cooldown", tw: "小紅書返回 461，觸發限流冷卻後繼續" },
  { zh: "搜索候选累计", en: "Search candidates total", tw: "搜尋候選累計" },
  { zh: "主页候选累计", en: "Homepage candidates total", tw: "主頁候選累計" },
  { zh: "网页用户搜索被重定向到登录页，无法直接解析小红书号", en: "Web user search was redirected to login; cannot parse Xiaohongshu ID directly", tw: "網頁使用者搜尋被重定向到登入頁，無法直接解析小紅書號" },
  { zh: "网页用户搜索未找到匹配的小红书号", en: "Web user search found no matching Xiaohongshu ID", tw: "網頁使用者搜尋未找到匹配的小紅書號" },
  { zh: "已解析详情", en: "Parsed details", tw: "已解析詳情" },
  { zh: "成功", en: "success", tw: "成功" },
  { zh: "已投递", en: "delivered", tw: "已投遞" },
  { zh: "已尝试恢复本地小红书 Cookie", en: "Tried to restore local Xiaohongshu Cookie", tw: "已嘗試恢復本機小紅書 Cookie" },
  { zh: "检测到已登录的小红书会话，Cookie 已保存", en: "Detected logged-in Xiaohongshu session; Cookie saved", tw: "偵測到已登入的小紅書會話，Cookie 已儲存" },
  { zh: "小红书笔记详情线程失败", en: "Xiaohongshu note detail thread failed", tw: "小紅書筆記詳情執行緒失敗" },
  { zh: "本地小红书 Cookie 恢复失败，继续使用新会话", en: "Failed to restore local Xiaohongshu Cookie; continuing with new session", tw: "本機小紅書 Cookie 恢復失敗，繼續使用新會話" },
  { zh: "小红书号未命中主页结果，回退为关键词搜索", en: "Xiaohongshu ID did not match homepage results; falling back to keyword search", tw: "小紅書號未命中主頁結果，回退為關鍵字搜尋" },
  { zh: "下载已暂停", en: "download paused", tw: "下載已暫停" },
  { zh: "Web 端用户请求停止爬虫任务", en: "Web user requested to stop the crawl task", tw: "Web 端使用者要求停止爬蟲任務" },
  { zh: "Web 端开始扫描本地媒体目录（异步）", en: "Web started scanning local media folder (async)", tw: "Web 端開始非同步掃描本機媒體目錄" },
  { zh: "Web 端开始扫描本地媒体目录", en: "Web started scanning local media folder", tw: "Web 端開始掃描本機媒體目錄" },
  { zh: "Web 端启动爬虫任务", en: "Web started crawl task", tw: "Web 端啟動爬蟲任務" },
  { zh: "Web 端发现可下载资源", en: "Web found downloadable resources", tw: "Web 端發現可下載資源" },
  { zh: "Web 端下载任务完成", en: "Web download task completed", tw: "Web 端下載任務完成" },
  { zh: "Web 端下载任务失败", en: "Web download task failed", tw: "Web 端下載任務失敗" },
  { zh: "Web 端保存目录已变更", en: "Web save directory changed", tw: "Web 端儲存目錄已變更" },
  { zh: "Web 端爬虫任务结束", en: "Web crawl task finished", tw: "Web 端爬蟲任務結束" },
  { zh: "用户取消更新下载", en: "User cancelled the update download", tw: "使用者取消更新下載" },
  { zh: "正在等待上一次更新下载线程停止，暂不能重试。", en: "Waiting for the previous update download thread to stop; retry is not available yet.", tw: "正在等待上一次更新下載執行緒停止，暫時無法重試。" },
  { zh: "更新安装程序已启动，应用即将退出。", en: "Update installer started; the app will exit shortly.", tw: "更新安裝程式已啟動，應用程式即將結束。" },
  { zh: "Bilibili 并发解析播放流并批量提交下载项", en: "Bilibili is resolving streams concurrently and submitting download items in batches", tw: "Bilibili 正在並行解析播放串流並批次提交下載項目" },
  { zh: "Bilibili 并发取流线程失败", en: "Bilibili concurrent stream worker failed", tw: "Bilibili 並行取流執行緒失敗" },
  { zh: "HTTP 断点续传请求已建立", en: "HTTP resume request established", tw: "HTTP 斷點續傳請求已建立" },
  { zh: "目录切换后的初始扫描完成", en: "Initial scan after changing directory completed", tw: "切換目錄後的初始掃描完成" },
  { zh: "收到超长 WebSocket 消息，连接已关闭", en: "Oversized WebSocket message received; connection closed", tw: "收到過長的 WebSocket 訊息，連線已關閉" },
  { zh: "更新安装包已下载并通过校验", en: "Update package downloaded and verified", tw: "更新安裝套件已下載並通過校驗" },
  { zh: "更新安装程序启动失败", en: "Failed to start the update installer", tw: "更新安裝程式啟動失敗" },
  { zh: "已跳过更新版本", en: "Skipped update version", tw: "已略過更新版本" },
  { zh: "已调度 select_tasks 测试事件", en: "select_tasks test event dispatched", tw: "已排程 select_tasks 測試事件" },
  { zh: "收到非法 JSON 消息", en: "Invalid JSON message received", tw: "收到無效的 JSON 訊息" },
  { zh: "Bilibili 登录状态校验失败", en: "Bilibili login status check failed", tw: "Bilibili 登入狀態校驗失敗" },
  { zh: "等待 Bilibili 扫码登录超时", en: "Timed out waiting for Bilibili QR-code login", tw: "等待 Bilibili 掃碼登入逾時" },
  { zh: "等待抖音扫码登录超时 (120秒)", en: "Timed out waiting for Douyin QR-code login (120 seconds)", tw: "等待抖音掃碼登入逾時（120 秒）" },
  { zh: "用户在登录过程中终止任务", en: "User stopped the task during login", tw: "使用者在登入過程中終止任務" },
  { zh: "HTTP 下载内容不完整，准备重试", en: "HTTP download incomplete; preparing to retry", tw: "HTTP 下載內容不完整，準備重試" },
  { zh: "HTTP 下载失败，准备重试", en: "HTTP download failed; preparing to retry", tw: "HTTP 下載失敗，準備重試" },
  { zh: "HTTP 下载异常，准备重试", en: "HTTP download error; preparing to retry", tw: "HTTP 下載異常，準備重試" },
  { zh: "分块下载失败，准备重试", en: "Chunked download failed; preparing to retry", tw: "分塊下載失敗，準備重試" },
  { zh: "文件删除等待超时前下载线程未停止", en: "Download worker did not stop before file deletion timeout", tw: "檔案刪除等待逾時前下載執行緒未停止" },
  { zh: "流断点续传：从", en: "stream resume: continuing from", tw: "串流斷點續傳：從" },
  { zh: "字节继续下载", en: "bytes", tw: "位元組繼續下載" },
  { zh: "打开快手目标页", en: "Opening the Kuaishou target page", tw: "開啟快手目標頁" },
  { zh: "页面访问", en: "Page navigation", tw: "頁面存取" },
  { zh: "B站", en: "B-site", tw: "B 站" },
  { zh: "已启动有界下载恢复维护", en: "Started bounded download recovery maintenance", tw: "已啟動有界下載恢復維護" },
  { zh: "应用启动时已处理过期下载临时文件", en: "Processed stale download temp artifacts at application startup", tw: "應用程式啟動時已處理過期下載暫存檔" },
  { zh: "已完成有界下载恢复维护", en: "Completed bounded download recovery maintenance", tw: "已完成有界下載恢復維護" },
  { zh: "无法枚举恢复目录；本次尝试已确认", en: "Recovery directory could not be enumerated; the attempt was acknowledged", tw: "無法列舉恢復目錄；本次嘗試已確認" },
  { zh: "旧版目录扫描已受限或降级", en: "A legacy directory scan was bounded or degraded", tw: "舊版目錄掃描已受限或降級" },
  { zh: "旧版临时文件清理已在生产扫描预算处停止", en: "Stopped legacy temp cleanup at the production scan budget", tw: "舊版暫存檔清理已在生產掃描預算處停止" },
  { zh: "已设置当前用户的默认应用", en: "Set current-user default apps", tw: "已設定目前使用者的預設應用程式" },
  { zh: "文件关联注册仅支持 Windows", en: "File association registration is Windows-only", tw: "檔案關聯註冊僅支援 Windows" },
  { zh: "文件关联默认值仅支持 Windows", en: "File association defaults are Windows-only", tw: "檔案關聯預設值僅支援 Windows" },
  { zh: "文件关联诊断仅支持 Windows", en: "File association diagnostics are Windows-only", tw: "檔案關聯診斷僅支援 Windows" },
  { zh: "为以下项目设置默认值失败：", en: "Failed to set defaults for ", tw: "為以下項目設定預設值失敗：" },
  { zh: "无法解析当前用户 SID：", en: "Cannot resolve current user SID: ", tw: "無法解析目前使用者 SID：" },
  { zh: "界面可见性探测：", en: "Shell visibility probe: ", tw: "介面可見性探測：" },
  { zh: "界面外壳意外隐藏；正在恢复", en: "Shell chrome was hidden unexpectedly; restoring shell chrome", tw: "介面外殼意外隱藏；正在恢復" },
  { zh: "恢复界面外壳时已退出残留的媒体全屏状态", en: "Exited stale media fullscreen while restoring shell chrome", tw: "恢復介面外殼時已退出殘留的媒體全螢幕狀態" },
  { zh: "打开快手搜索页", en: "Opening the Kuaishou search page", tw: "開啟快手搜尋頁" },
  { zh: "开始切换目录", en: "Started changing directory", tw: "開始切換目錄" },
  { zh: "任务已停止", en: "Task stopped", tw: "任務已停止" },
  { zh: "爬虫完成回调已调用", en: "_on_spider_finished was called", tw: "爬蟲完成回呼已呼叫", aliases: ["_on_spider_finished 被调用"] },
  { zh: "CLI 发现可下载资源", en: "CLI found downloadable resources", tw: "CLI 發現可下載資源" },
  { zh: "CLI 启动爬虫任务", en: "CLI started crawl task", tw: "CLI 啟動爬蟲任務" },
  { zh: "CLI 下载任务失败", en: "CLI download task failed", tw: "CLI 下載任務失敗" },
  { zh: "用户取消操作", en: "User cancelled operation", tw: "使用者取消操作" },
  { zh: "选择策略异常", en: "Selection strategy error", tw: "選擇策略異常" },
  { zh: "默认全选", en: "defaulting to select all", tw: "預設全選" },
  { zh: "返回空选择", en: "returning an empty selection", tw: "返回空選擇" },
  { zh: "用户已取消，跳过后续选择", en: "User cancelled; skipping subsequent selections", tw: "使用者已取消，略過後續選擇" },
  { zh: "spider 超过", en: "spider exceeded", tw: "spider 超過" },
  { zh: "未完成，强制停止", en: "without finishing; force stopping", tw: "未完成，強制停止" },
  { zh: "item 转换失败", en: "item conversion failed", tw: "item 轉換失敗" },
  { zh: "防护规则已停止页面跳转", en: "Guardrail stopped navigation", tw: "防護規則已停止頁面跳轉" },
  { zh: "防护规则已停止页面刷新", en: "Guardrail stopped reload", tw: "防護規則已停止頁面重新整理" },
  { zh: "失败", en: "failed", tw: "失敗" },
];

function applyRuntimePhraseTranslations(text, language) {
  const replacements = [];
  for (const entry of RUNTIME_LOG_PHRASE_TRANSLATIONS) {
    const target = language === "en-US" ? entry.en : language === "zh-TW" ? (entry.tw || entry.zh) : entry.zh;
    const sources = [entry.zh, entry.en, entry.tw].concat(Array.isArray(entry.aliases) ? entry.aliases : []);
    for (const source of sources) {
      if (source && source !== target) replacements.push([source, target]);
    }
  }
  replacements.sort((left, right) => right[0].length - left[0].length);
  let result = text;
  for (const [source, target] of replacements) result = result.split(source).join(target);
  return result;
}

const EN_LOG_FRAGMENT_CLEANUPS = [
  ["参数未设置，程序不会储存任何数据至文件", "parameter is not set; the program will not store data to files"],
  ["响应不是有效的 JSON 格式", "response is not valid JSON format"],
  ["扫描被中断，跳过中文校验", "scan interrupted; skipped Chinese subtitle check"],
  ["[DEBUG] 已调度 select_tasks 测试事件", "[DEBUG] select_tasks test event dispatched"],
  ["无法写入", "failed to write"],
  ["纯数字 UID 暂不supported直接搜索", "numeric UID cannot be searched directly"],
  ["视频下载地址解析failed", "video download URL parsing failed"],
  ["视频下载地址parsing failed", "video download URL parsing failed"],
  ["Share link解析failed", "share-link parsing failed"],
  ["Share link解析", "share-link parsing"],
  ["加载本地 Cookie failed", "failed to load local Cookie"],
  ["继续尝试页面登录", "continuing page login"],
  ["关闭 SDK failed", "failed to close SDK"],
  ["scan完成", "scan completed"],
  ["登录failed", "login failed"],
  ["扫描failed", "scan failed"],
  ["搜索failed", "search failed"],
  ["解析failed", "parsing failed"],
  ["获取success", "fetched successfully"],
  ["数据提取success", "data extracted successfully"],
  ["视频下载地址解析failed", "video download URL parsing failed"],
  ["HTTP 请求异常", "HTTP request error"],
  ["响应内容预览", "response preview"],
  ["参数已设置为", "parameter set to"],
  ["使用本地兜底值", "using local fallback value"],
  ["浏览器信息", "browser info"],
  ["请求值", "request value"],
  ["本地值", "local value"],
  ["开始:", "started:"],
  ["参数:", "parameter:"],
  ["准备生成清单", "preparing to generate the list"],
  ["同时进行中", "running concurrently"],
  ["Cookie 有效", "Cookie is valid"],
  ["sessionid_ss 有效", "sessionid_ss is valid"],
  ["个valid resources", "valid resources"],
  ["个candidates", "candidates"],
  ["个下载项", "download items"],
  ["个有效资源", "valid resources"],
  ["个匹配用户", "matching users"],
  ["个小红书下载任务", "Xiaohongshu download tasks"],
  ["个账号候选", "account candidates"],
  ["个任务", "tasks"],
  ["个项目", "items"],
  ["个视频", "videos"],
  ["个文件", "files"],
  ["个候选", "candidates"],
  ["粉丝", "followers"],
  ["作品", "works"],
  ["合集", "collection"],
  ["小红书", "Xiaohongshu"],
  ["抖音", "Douyin"],
  ["快手", "Kuaishou"],
  ["扫描", "scan"],
  ["解析", "parse"],
  ["聚合", "aggregate"],
  ["有效", "valid"],
  ["最多", "max"],
  ["（如", " (for example "],
  ["）", ")"],
  ["个for selection", "for selection"],
  ["内退出", ""],
];

function cleanupEnglishLogFragments(value) {
  let result = String(value ?? "");
  for (const [source, target] of EN_LOG_FRAGMENT_CLEANUPS) {
    result = result.split(source).join(target);
  }
  result = result.replace(/另有\s*(\d+)\s*items?items were removed/gu, "$1 additional items were removed");
  result = result.replace(/已切换到\s*1\s*主题/gu, "Switched theme");
  result = result.replace(/获取\s*(.*?)\s*参数failed/gu, "failed to fetch $1 parameter");
  result = result.replace(/kept\s*(\d+)\s*个\s*(.*?)\s*[,，;]/gu, "kept $1 $2; ");
  result = result.replace(/共\s*(\d+)\s*个/gu, "total $1 items");
  result = result.replace(/total\s+(\d+)\s*个/gu, "total $1 items");
  result = result.replace(/发现\s*(\d+)\s*个/gu, "found $1 items");
  result = result.replace(/scanned\s*(\d+)\s*个/gu, "scanned $1 items");
  result = result.replace(/Selected\s*(\d+)\s*个/gu, "Selected $1 items");
  result = result.replace(/(\d)\s*项/gu, "$1 items");
  result = result.replace(/(\d)\s*页/gu, "$1");
  result = result.replace(/另有\s*(\d+)\s*itemsitems were removed/gu, "$1 additional items were removed");
  result = result.replace(/共\s*(\d+)\s*candidates/gu, "total $1 candidates");
  result = result.split("scan完成").join("scan completed");
  result = result.split("视频下载地址parsing failed").join("video download URL parsing failed");
  result = result.split("itemsitems").join("items");
  result = result.split("，please").join("; please");
  result = result.split("，preparing").join("; preparing");
  result = result.split("，").join(", ");
  result = result.split("。").join(".");
  return result;
}

function localizeEnglishDynamicLogText(text) {
  const selectTasksRelay = text.match(/^select_tasks\s+(?:转发延迟|轉發延遲)=([\d.]+)\s*毫秒[，,]\s*(?:项目数|項目數)=(\d+)$/u);
  if (selectTasksRelay) {
    return `select_tasks relay lag=${selectTasksRelay[1]}ms items=${selectTasksRelay[2]}`;
  }

  const themeSwitch = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0F]*\s*)?已切换到(浅色|深色)主题[。.]?$/u);
  if (themeSwitch) return `${themeSwitch[1] || ""}Switched to ${themeSwitch[2] === "浅色" ? "light" : "dark"} theme`;
  const mediaEmpty = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0F]*\s*)?该目录下没有找到视频或图片[。.]?$/u);
  if (mediaEmpty) return `${mediaEmpty[1] || ""}No videos or images found in this directory`;
  const matchingUsers = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0F]*\s*)?找到\s*(\d+)\s*(?:个匹配用户|matching users)$/u);
  if (matchingUsers) return `${matchingUsers[1] || ""}Found ${matchingUsers[2]} matching users`;
  const configNotLogged = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?配置文件\s+([\w.-]+)\s+参数未登录[，,]\s*数据获取已提前结束$/u);
  if (configNotLogged) return `${configNotLogged[1] || ""}Config ${configNotLogged[2]} is not logged in; data fetching ended early`;
  const configNotSet = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?配置文件\s+([\w.-]+)\s+参数未设置[，,]\s*([A-Za-z0-9_.-]+|[\u4e00-\u9fff]+)\s*平台功能可能无法正常使用$/u);
  if (configNotSet) return `${configNotSet[1] || ""}Config ${configNotSet[2]} is not set; ${localizedRuntimePlatformName(configNotSet[3], "en-US")} features may not work properly`;
  const paramUpdated = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?(Douyin|douyin|抖音|TikTok|tiktok)\s*参数更新完毕[!！]?$/u);
  if (paramUpdated) return `${paramUpdated[1] || ""}${localizedRuntimePlatformName(paramUpdated[2], "en-US")} parameters updated!`;
  const bilibiliStreamRetry = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?(?:B站|Bilibili|B-site)\s+(.*?)\s+流连接断开，(\d+)s\s+后重试\s+\((\d+)\/\s*(\d+)\):\s*(.+)$/u);
  if (bilibiliStreamRetry) {
    const media = localizedMediaTerm(bilibiliStreamRetry[2], "en-US");
    return `${bilibiliStreamRetry[1] || ""}B-site ${media} stream disconnected; retrying in ${bilibiliStreamRetry[3]}s (${bilibiliStreamRetry[4]}/${bilibiliStreamRetry[5]}): ${bilibiliStreamRetry[6]}`;
  }
  const spiderSummary = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?(?:spider|爬虫)\s*已结束,\s*耗时\s*([^,]+?)s,\s*收集到\s*(\d+)\s*个项目,\s*二次选择\s*(\d+)\s*次$/u);
  if (spiderSummary) {
    return `${spiderSummary[1] || ""}spider finished, elapsed ${spiderSummary[2]}s, collected ${spiderSummary[3]} items, secondary selections ${spiderSummary[4]}`;
  }
  const loaded = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?已加载\s*(\d+)\s*个本地文件\s*\(视频[:：]\s*(\d+)\s*,\s*图片[:：]\s*(\d+)\)$/u);
  if (loaded) {
    const noun = loaded[2] === "1" ? "file" : "files";
    return `${loaded[1] || ""}Loaded ${loaded[2]} local ${noun} (videos: ${loaded[3]}, images: ${loaded[4]})`;
  }
  const scanning = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?正在扫描目录[:：]\s*(.+)$/u);
  if (scanning) return `${scanning[1] || ""}Scanning directory: ${scanning[2]}`;
  const done = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?下载完成[:：]\s*(.+)$/u);
  if (done) return `${done[1] || ""}Download completed: ${done[2]}`;
  const failed = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?下载失败\s*\[(.+?)\][：:]\s*(.+)$/u);
  if (failed) return `${failed[1] || ""}Download failed [${failed[2]}]: ${failed[3]}`;
  const patterns = [
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?用户确认了\s*(\d+)\s*个任务$/u, match => `${match[1] || ""}User confirmed ${match[2]} tasks`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?最终确认\s*(\d+)\s*个.*$/u, match => `${match[1] || ""}Final confirmation: ${match[2]} tasks`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?启动\s*(.*?)\s*爬虫任务$/u, match => `${match[1] || ""}Started ${localizedRuntimePlatformName(match[2], "en-US")} crawl task`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?启动\s*(.*?)\s*任务\s*\|\s*目标[:：]\s*(.*)$/u, match => `${match[1] || ""}Started ${localizedRuntimePlatformName(match[2], "en-US")} task | target: ${match[3]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?启动任务\s*\|\s*模式[:：]\s*(.*?)\s*\|\s*关键词[:：]\s*(.*)$/u, match => `${match[1] || ""}Started task | mode: ${match[2]} | keyword: ${match[3]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?启动任务\s*\|\s*模式[:：]\s*(.*)$/u, match => `${match[1] || ""}Started task | mode: ${match[2]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?扫描(?:结束|完成)[，,]\s*共\s*(\d+)(.*)$/u, match => `${match[1] || ""}Scan finished, total ${match[2]}${match[3]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?获取成功\s*(.*)$/u, match => `${match[1] || ""}Fetched successfully ${match[2]}`.trimEnd()],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?解析流[:：]\s*(.*)$/u, match => `${match[1] || ""}Parsed stream: ${match[2]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?正在展开[:：]\s*(.*)$/u, match => `${match[1] || ""}Expanding: ${match[2]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?流水线已建立[:：]\s*(.*)$/u, match => `${match[1] || ""}Pipeline established: ${match[2]}`],
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?全部完成[:：]\s*(?:成功|success)\s*(\d+)\s*\/\s*(\d+)\s*\|\s*(?:失败|failed)\s*(\d+)$/iu, match => `${match[1] || ""}All completed: success ${match[2]}/${match[3]} | failed ${match[4]}`],
  ];
  for (const [pattern, formatter] of patterns) {
    const match = text.match(pattern);
    if (match) return formatter(match);
  }
  const phraseResult = applyRuntimePhraseTranslations(text, "en-US");
  if (phraseResult !== text) return phraseResult;
  const replacements = [
    ["Bilibili 流请求建立成功", "Bilibili stream request established"],
    ["Bilibili 下载任务已提交到下载队列", "Bilibili download task submitted to the queue"],
    ["Bilibili 下载任务已装配完成", "Bilibili download task assembled"],
    ["准备下载 Bilibili 音视频流", "Preparing Bilibili audio/video stream download"],
    ["准备合并 Bilibili 音视频流", "Preparing to merge Bilibili audio/video stream"],
    ["音视频流写入完成，准备合并", "Audio/video stream written; preparing to merge"],
    ["已刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL successfully"],
    ["重新刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully"],
    ["重刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully"],
    ["B站 audio 流连接断开", "B-site audio stream disconnected"],
    ["B站 video 流连接断开", "B-site video stream disconnected"],
    ["Bilibili 爬虫任务结束", "Bilibili crawl task finished"],
    ["爬虫任务结束", "Crawl task finished"],
    ["爬虫发现可下载资源", "Crawler found downloadable resources"],
    ["检查 Bilibili 登录状态", "Checking Bilibili login status"],
    ["已登录，Cookie", "Logged in; Cookie"],
    ["下载任务开始执行", "Download task started"],
    ["下载任务完成", "Download task completed"],
    ["下载任务已进入队列", "Download task has been queued"],
    ["下载任务已加入执行队列", "Download task has been queued for execution"],
    ["准备下载 Bilibili 音", "Preparing Bilibili audio download"],
    ["准备合并 Bilibili 音", "Preparing to merge Bilibili audio"],
    ["Bilibili 音视频合并", "Bilibili audio/video merge"],
    ["分发队列", "Dispatched queue"],
    ["释放下载", "Released download"],
  ];
  let result = text;
  for (const [source, target] of replacements) result = result.split(source).join(target);
  return result;
}

const NON_EN_DYNAMIC_LOG_TEXT = {
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
  "Bilibili stream request established": {
    "zh-CN": "Bilibili 流请求建立成功",
    "zh-TW": "Bilibili 串流請求建立成功",
  },
  "Bilibili download task submitted to the queue": {
    "zh-CN": "Bilibili 下载任务已提交到下载队列",
    "zh-TW": "Bilibili 下載任務已提交到下載佇列",
  },
  "Bilibili download task assembled": {
    "zh-CN": "Bilibili 下载任务已装配完成",
    "zh-TW": "Bilibili 下載任務已組裝完成",
  },
  "Preparing Bilibili audio/video stream download": {
    "zh-CN": "准备下载 Bilibili 音视频流",
    "zh-TW": "準備下載 Bilibili 音視訊流",
  },
  "Preparing to merge Bilibili audio/video stream": {
    "zh-CN": "准备合并 Bilibili 音视频流",
    "zh-TW": "準備合併 Bilibili 音視訊流",
  },
  "Audio/video stream written; preparing to merge": {
    "zh-CN": "音视频流写入完成，准备合并",
    "zh-TW": "音視訊流寫入完成，準備合併",
  },
  "Bilibili audio/video merge": {
    "zh-CN": "Bilibili 音视频合并",
    "zh-TW": "Bilibili 音視訊合併",
  },
  "Bilibili crawl task finished": {
    "zh-CN": "Bilibili 爬虫任务结束",
    "zh-TW": "Bilibili 爬蟲任務結束",
  },
  "Crawl task finished": {
    "zh-CN": "爬虫任务结束",
    "zh-TW": "爬蟲任務結束",
  },
  "Crawler found downloadable resources": {
    "zh-CN": "爬虫发现可下载资源",
    "zh-TW": "爬蟲發現可下載資源",
  },
};

const BILIBILI_ROUTE_ALIASES = {
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
};

function localizedDynamicValue(map, language) {
  return (map && (map[language] || map["zh-CN"])) || "";
}

function localizedRuntimePlatformName(value, language) {
  const text = String(value || "").trim();
  const aliases = {
    Douyin: { "zh-CN": "抖音", "zh-TW": "抖音", "en-US": "Douyin" },
    douyin: { "zh-CN": "抖音", "zh-TW": "抖音", "en-US": "Douyin" },
    抖音: { "zh-CN": "抖音", "zh-TW": "抖音", "en-US": "Douyin" },
    TikTok: { "zh-CN": "TikTok", "zh-TW": "TikTok", "en-US": "TikTok" },
    tiktok: { "zh-CN": "TikTok", "zh-TW": "TikTok", "en-US": "TikTok" },
    Xiaohongshu: { "zh-CN": "小红书", "zh-TW": "小紅書", "en-US": "Xiaohongshu" },
    XiaoHongShu: { "zh-CN": "小红书", "zh-TW": "小紅書", "en-US": "Xiaohongshu" },
    小红书: { "zh-CN": "小红书", "zh-TW": "小紅書", "en-US": "Xiaohongshu" },
    小紅書: { "zh-CN": "小红书", "zh-TW": "小紅書", "en-US": "Xiaohongshu" },
    Kuaishou: { "zh-CN": "快手", "zh-TW": "快手", "en-US": "Kuaishou" },
    快手: { "zh-CN": "快手", "zh-TW": "快手", "en-US": "Kuaishou" },
    Bilibili: { "zh-CN": "Bilibili", "zh-TW": "Bilibili", "en-US": "Bilibili" },
    MissAV: { "zh-CN": "MissAV", "zh-TW": "MissAV", "en-US": "MissAV" },
  };
  return localizedDynamicValue(aliases[text] || null, language) || text;
}

function localizedRuntimeSubject(prefix, platform, suffix) {
  const padded = /^[A-Za-z0-9]/.test(platform) || /[A-Za-z0-9]$/.test(platform);
  return padded ? `${prefix} ${platform} ${suffix}` : `${prefix}${platform}${suffix}`;
}

function localizedMediaTerm(value, language) {
  const text = String(value || "").trim();
  const terms = {
    "audio/video stream": {
      "zh-CN": "音视频流",
      "zh-TW": "音視訊流",
    },
    "audio": {
      "zh-CN": "音频",
      "zh-TW": "音訊",
    },
    "video": {
      "zh-CN": "视频",
      "zh-TW": "影片",
    },
  };
  if (language === "en-US" && Object.prototype.hasOwnProperty.call(terms, text)) return text;
  return localizedDynamicValue(terms[text] || null, language) || text;
}

function localizeNonEnglishDynamicLogText(text, language) {
  const exact = NON_EN_DYNAMIC_LOG_TEXT[text];
  if (exact) return localizedDynamicValue(exact, language);

  const selectTasksRelay = text.match(/^select_tasks relay lag=([\d.]+)ms items=(\d+)$/iu);
  if (selectTasksRelay) {
    return language === "zh-TW"
      ? `select_tasks 轉發延遲=${selectTasksRelay[1]} 毫秒，項目數=${selectTasksRelay[2]}`
      : `select_tasks 转发延迟=${selectTasksRelay[1]} 毫秒，项目数=${selectTasksRelay[2]}`;
  }

  let match = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0F]*\s*)?Switched to\s*(light|dark)\s*theme[。.]?$/iu);
  if (match) {
    const light = match[2].toLowerCase() === "light";
    const mode = language === "zh-TW" ? (light ? "淺色" : "深色") : (light ? "浅色" : "深色");
    return `${match[1] || ""}${language === "zh-TW" ? "已切換到" : "已切换到"}${mode}${language === "zh-TW" ? "主題" : "主题"}`;
  }

  match = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0F]*\s*)?No videos or images found in this directory[。.]?$/iu);
  if (match) {
    return `${match[1] || ""}${language === "zh-TW" ? "該目錄下沒有找到影片或圖片" : "该目录下没有找到视频或图片"}`;
  }

  match = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0F]*\s*)?(?:Found|找到)\s*(\d+)\s*(?:matching users|个匹配用户|個匹配使用者)$/iu);
  if (match) {
    return `${match[1] || ""}找到 ${match[2]} ${language === "zh-TW" ? "個匹配使用者" : "个匹配用户"}`;
  }

  match = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?Config\s+([\w.-]+)\s+is not logged in;\s*data fetching ended early$/iu);
  if (match) {
    return language === "zh-TW"
      ? `${match[1] || ""}設定檔 ${match[2]} 參數未登入，資料取得已提前結束`
      : `${match[1] || ""}配置文件 ${match[2]} 参数未登录，数据获取已提前结束`;
  }

  match = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?Config\s+([\w.-]+)\s+is not set;\s*(.+?)\s+features may not work properly$/iu);
  if (match) {
    const platform = localizedRuntimePlatformName(match[3], language);
    return language === "zh-TW"
      ? `${match[1] || ""}設定檔 ${match[2]} 參數未設定，${platform} 平台功能可能無法正常使用`
      : `${match[1] || ""}配置文件 ${match[2]} 参数未设置，${platform} 平台功能可能无法正常使用`;
  }

  match = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2139\uFE0E\uFE0F]*\s*)?(Douyin|douyin|抖音|TikTok|tiktok)\s+parameters updated[!！]?$/iu);
  if (match) {
    const platform = localizedRuntimePlatformName(match[2], language);
    const suffix = language === "zh-TW" ? "參數更新完成！" : "参数更新完毕！";
    return /[A-Za-z0-9]$/.test(platform)
      ? `${match[1] || ""}${platform} ${suffix}`
      : `${match[1] || ""}${platform}${suffix}`;
  }

  const phraseResult = applyRuntimePhraseTranslations(text, language);
  if (phraseResult !== text) return phraseResult;

  match = text.match(/^Bilibili route:\s*(.+)$/);
  if (match) {
    const route = match[1].trim();
    const browserScan = route.match(/^browser scan\s*(.*)$/);
    if (browserScan) {
      const prefix = language === "zh-TW" ? "Bilibili 路由：瀏覽器掃描" : "Bilibili 路由：浏览器扫描";
      return `${prefix} ${browserScan[1].trim()}`.trimEnd();
    }
    const routeLabel = BILIBILI_ROUTE_ALIASES[route];
    if (routeLabel) return `Bilibili 路由：${localizedDynamicValue(routeLabel, language)}`;
  }

  match = text.match(/^Bilibili browser producer error:\s*(.+)$/);
  if (match) {
    const prefix = language === "zh-TW" ? "Bilibili 瀏覽器生產執行緒異常" : "Bilibili 浏览器生产线程异常";
    return `${prefix}：${match[1]}`;
  }

  match = text.match(/^Download completed:\s*(.+)$/);
  if (match) {
    const prefix = language === "zh-TW" ? "下載完成" : "下载完成";
    return `${prefix}：${match[1]}`;
  }

  match = text.match(/^Download failed\s*\[(.+?)\]:\s*(.+)$/);
  if (match) {
    const prefix = language === "zh-TW" ? "下載失敗" : "下载失败";
    return `${prefix} [${match[1]}]：${match[2]}`;
  }

  match = text.match(/^Started\s*(.*?)\s*crawl task$/);
  if (match) {
    const prefix = language === "zh-TW" ? "啟動" : "启动";
    const suffix = language === "zh-TW" ? "爬蟲任務" : "爬虫任务";
    return localizedRuntimeSubject(prefix, localizedRuntimePlatformName(match[1], language), suffix);
  }

  match = text.match(/^Started\s*(.*?)\s*task\s*\|\s*target:\s*(.*)$/);
  if (match) {
    const prefix = language === "zh-TW" ? "啟動" : "启动";
    const task = language === "zh-TW" ? "任務" : "任务";
    const target = language === "zh-TW" ? "目標" : "目标";
    return `${localizedRuntimeSubject(prefix, localizedRuntimePlatformName(match[1], language), task)} | ${target}：${match[2]}`;
  }

  match = text.match(/^Started task\s*\|\s*mode:\s*(.*?)\s*\|\s*keyword:\s*(.*)$/);
  if (match) {
    const start = language === "zh-TW" ? "啟動任務" : "启动任务";
    const mode = language === "zh-TW" ? "模式" : "模式";
    const keyword = language === "zh-TW" ? "關鍵字" : "关键词";
    return `${start} | ${mode}：${match[1]} | ${keyword}：${match[2]}`;
  }

  match = text.match(/^Final confirmation:\s*(\d+)\s*tasks?$/);
  if (match) {
    const label = language === "zh-TW" ? "最終確認" : "最终确认";
    const unit = language === "zh-TW" ? "個任務" : "个任务";
    return `${label} ${match[1]} ${unit}`;
  }

  match = text.match(/^Fetched successfully\s*(.*)$/);
  if (match) {
    const label = language === "zh-TW" ? "取得成功" : "获取成功";
    return `${label} ${match[1]}`.trimEnd();
  }

  match = text.match(/^Parsed stream:\s*(.*)$/);
  if (match) {
    const label = language === "zh-TW" ? "解析串流" : "解析流";
    return `${label}：${match[1]}`;
  }

  match = text.match(/^Pipeline established:\s*(.*)$/);
  if (match) {
    const label = language === "zh-TW" ? "流水線已建立" : "流水线已建立";
    return `${label}：${match[1]}`;
  }

  match = text.match(/^Scan finished,\s*total\s*(\d+)(.*)$/);
  if (match) {
    const label = language === "zh-TW" ? "掃描結束，共" : "扫描结束，共";
    return `${label} ${match[1]}${match[2]}`;
  }

  match = text.match(/^All completed:\s*success\s*(\d+)\s*\/\s*(\d+)\s*\|\s*failed\s*(\d+)$/i);
  if (match) {
    const ok = language === "zh-TW" ? "全部完成：成功" : "全部完成：成功";
    const failed = language === "zh-TW" ? "失敗" : "失败";
    return `${ok} ${match[1]}/${match[2]} | ${failed} ${match[3]}`;
  }

  match = text.match(/^Preparing Bilibili\s*(.*?)\s*download$/);
  if (match) {
    const label = language === "zh-TW" ? "準備下載" : "准备下载";
    return `${label} Bilibili ${localizedMediaTerm(match[1], language)}`;
  }

  match = text.match(/^Preparing to merge Bilibili\s*(.*)$/);
  if (match) {
    const label = language === "zh-TW" ? "準備合併" : "准备合并";
    return `${label} Bilibili ${localizedMediaTerm(match[1], language)}`;
  }

  match = text.match(/^XiaoHongShu user confirmed\s*(\d+)\s*candidates; starting parse-to-download pipeline\.$/);
  if (match) return language === "zh-TW"
    ? `小紅書使用者已確認 ${match[1]} 個候選，開始解析到下載流水線。`
    : `小红书用户已确认 ${match[1]} 个候选，开始解析到下载流水线。`;

  match = text.match(/^XiaoHongShu found\s*(\d+)\s*candidates; waiting for user confirmation before parsing details\.$/);
  if (match) return language === "zh-TW"
    ? `小紅書發現 ${match[1]} 個候選，等待使用者確認後解析詳情。`
    : `小红书发现 ${match[1]} 个候选，等待用户确认后解析详情。`;

  match = text.match(/^XiaoHongShu confirmed pipeline is active:\s*(\d+)\s*selected candidates\.$/);
  if (match) return language === "zh-TW"
    ? `小紅書流水線已啟用：${match[1]} 個已選候選。`
    : `小红书流水线已激活：${match[1]} 个已选候选。`;

  return text;
}

function localizeRuntimeDynamicSegments(text, language) {
  return String(text ?? "")
    .split(/(\s+·\s+|\s+\/\s+|\s+路\s+)/)
    .map(part => {
      if (/^\s*(?:·|\/|路)\s*$/.test(part)) return part;
      return language === "en-US"
        ? localizeEnglishDynamicLogText(part)
        : localizeNonEnglishDynamicLogText(part, language);
    })
    .join("");
}

const LOG_EVENT_CODE_EXACT_ALIASES = {
  "KUAISHOU_开始滚动加载列表_点击_停止_生成清单": {
    "zh-CN": "KUAISHOU_开始滚动加载列表_点击_停止_生成清单",
    "en-US": "KUAISHOU_SCROLL_LIST_START_STOP_TO_BUILD_SELECTION",
    "zh-TW": "KUAISHOU_開始滾動載入列表_點擊_停止_產生清單"
  }
};

function localizeLogEventCode(value) {
  const text = String(value || "-");
  const language = currentLanguage();
  if (!text || text === "-") return text;
  const exact = LOG_EVENT_CODE_EXACT_ALIASES[text];
  if (exact) return exact[language] || exact["zh-CN"] || text;
  if (language !== "en-US") {
    if (language === "zh-TW" && text.includes("_")) {
      return text
        .split("_")
        .map(part => translateRuntimeLogText(part))
        .join("_");
    }
    return translateRuntimeLogText(text);
  }
  const loaded = text.match(/^([A-Za-z0-9_]+)_已加载_(\d+)_个本地文件_视频_(\d+)_图片_(\d+)$/u);
  if (loaded) return `${loaded[1]}_LOADED_${loaded[2]}_LOCAL_FILES_VIDEOS_${loaded[3]}_IMAGES_${loaded[4]}`;
  const replacements = {
    日志缓存已刷新: "LOG_CACHE_REFRESHED",
    正在扫描目录: "SCANNING_DIRECTORY",
    开始扫描本地媒体目录: "LOCAL_MEDIA_SCAN_START",
    本地媒体目录扫描完成: "LOCAL_MEDIA_SCAN_OK",
    主窗口初始化完成: "MAIN_WINDOW_READY",
    应用开始初始化: "APP_INIT",
    已切换到浅色主题: "THEME_LIGHT",
    已切换到深色主题: "THEME_DARK",
    爬虫任务结束: "CRAWL_FINISH",
  };
  let result = text;
  for (const [source, target] of Object.entries(replacements)) {
    result = result.split(source).join(target);
  }
  if (result !== text || /[\u4e00-\u9fff]/u.test(result)) {
    const translated = result.split("_").map(part => translateRuntimeLogText(part)).join("_");
    return translated.replace(/[^A-Za-z0-9_]+/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "").toUpperCase() || text;
  }
  return result;
}

function logResultNatureText(item) {
  const display = item.result_type_display || item.type_display || item.nature_display || "";
  if (display) return display;
  const rawType = String(item.result_type || item.type || item.nature || "").trim();
  const resultType = rawType.toLowerCase();
  if (resultType === "info") return "过程";
  if (resultType === "success") return "成功";
  if (resultType === "warn") return "预警";
  if (resultType === "warning") return "预警";
  if (resultType === "error") return "错误";
  if (resultType === "command") return "命令";
  if (rawType) return rawType;
  return "过程";
}

function logScopeDisplayText(item) {
  const display = item.log_scope_display || item.scope_display || "";
  if (display) return display;
  const rawScope = item.log_scope || item.scope || item.category || "";
  return {
    system: "系统",
    crawl: "采集",
    download: "下载",
    performance: "性能",
    error: "异常",
  }[String(rawScope).toLowerCase()] || rawScope || "-";
}

function logStageDisplayText(item) {
  const display = item.event_stage_display || item.stage_display || "";
  if (display) return display;
  const rawStage = item.event_stage || item.stage || "";
  return {
    init: "初始化",
    config: "配置",
    scan: "扫描",
    start: "启动",
    login: "登录",
    aggregate: "聚合",
    expand: "展开",
    confirm: "确认",
    parse: "解析",
    fetch: "获取",
    request: "请求",
    found: "发现",
    emit: "提交",
    queue: "入队",
    dispatch: "分发",
    prepare: "准备",
    download: "下载",
    merge: "合并",
    normalize: "修正",
    release: "释放",
    finish: "完成",
    performance: "性能",
    error: "异常",
    step: "步骤",
  }[String(rawStage).toLowerCase()] || rawStage || "-";
}

function translationHints(item) {
  const hints = {};
  const add = (key, value, translatedValue) => {
    const text = String(value ?? "");
    if (!text) return;
    const translated = translatedValue === undefined ? translateRuntimeLogText(text) : String(translatedValue ?? "");
    hints[text] = translated;
    hints[text.trim()] = translated;
    if (key) hints[`${key}:${text}`] = translated;
  };
  const projectedDetail = item && item.detail_payload;
  const rawDetail = item && item.detail;
  const detail = projectedDetail && typeof projectedDetail === "object"
    ? projectedDetail
    : (rawDetail && typeof rawDetail === "object" ? rawDetail : {});
  add("platform", item.platform_display || item.platform || "");
  add("source", item.source_display || item.source || "");
  add("message", item.message || item.message_summary || "");
  add("description", item.message || item.message_summary || "");
  add("description", detail.description || "");
  add("type", detail.type || item.type || item.result_type || item.result_type_display || item.type_display || "", translateRuntimeLogText(logResultNatureText(item)));
  add("scope", detail.scope || item.scope || item.log_scope || item.category || "", translateRuntimeLogText(logScopeDisplayText(item)));
  add("stage", detail.stage || item.stage || item.event_stage || "", translateRuntimeLogText(logStageDisplayText(item)));
  add("platform", detail.platform || "");
  add("source", detail.source || "");
  add("status_code", item.status_code || "", localizeLogEventCode(item.status_code || ""));
  add("event_code", item.event_code || "", localizeLogEventCode(item.event_code || ""));
  return hints;
}

  window.UcpLogI18n = Object.freeze({
    configure,
    dispose,
    localizedLogTabLabel,
    translateRuntimeLogText,
    translateStructuredLogText,
    localizeLogEventCode,
    logScopeDisplayText,
    logStageDisplayText,
    logResultNatureText,
    translationHints,
  });
})();
