let frontendState = buildMockState();
let currentPage = "queue";
let ws = null;
let platforms = [];
let selected = {
  active: "",
  completed: "",
  failed: "",
  log: "",
  tool: "link_parser",
};
let queuePage = 1;
let queuePageSize = Number(localStorage.getItem("webui_queue_page_size") || 20);
let completedPage = 1;
let completedPageSize = Number(localStorage.getItem("webui_completed_page_size") || 20);
let queueDensity = localStorage.getItem("webui_queue_density") || "comfortable";
let logFilters = {
  category: "all",
  level: "全部",
  time: "近 24 小时",
  platform: "全部",
  trace: "",
  keyword: "",
};
let currentSettingsGroup = localStorage.getItem("webui_settings_group") || "基础设置";
let openCustomSelect = null;
let imageAutoAdvanceTimer = null;

const PLAYBACK_POSITION_PREFIX = "ucp_playback_position_";

const SETTINGS_GROUP_ORDER_FALLBACK = ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"];
const SETTINGS_GROUP_DESCRIPTIONS_FALLBACK = {
  "基础设置": "下载目录、命名规则和打开行为",
  "下载设置": "并发、超时、重试和下载策略",
  "平台设置": "认证状态、爬取数量和代理入口",
  "播放设置": "播放器、进度记忆和预览行为",
  "日志设置": "保留策略、展示数量和错误追踪",
  "外观设置": "语言、主题色、缩放和字体",
};

function settingsContract() {
  const contract = frontendState.settings_contract || {};
  const order = Array.isArray(contract.group_order) ? contract.group_order.filter(Boolean) : [];
  return {
    order,
    descriptions: contract.group_descriptions || {},
  };
}

function logSettingsSnapshot() {
  const snapshot = frontendState.settings_snapshot || {};
  return snapshot["日志设置"] || snapshot["鏃ュ織璁剧疆"] || {};
}

function uiLogDisplayLimit() {
  const raw = Number(logSettingsSnapshot().ui_log_max_display_count || 300);
  const value = Number.isFinite(raw) ? raw : 300;
  return Math.max(100, Math.min(value, 5000));
}

function trimFrontendLogItems() {
  if (!Array.isArray(frontendState.log_items)) return false;
  const limit = uiLogDisplayLimit();
  if (frontendState.log_items.length <= limit) return false;
  frontendState.log_items = frontendState.log_items.slice(-limit);
  if (selected.log && !frontendState.log_items.some(item => logItemId(item) === selected.log)) {
    selected.log = "";
  }
  return true;
}

const FALLBACK_UI_TEXT = {
  "en-US": {
    "基础设置": "Basic",
    "下载设置": "Downloads",
    "平台设置": "Platforms",
    "播放设置": "Playback",
    "日志设置": "Logs",
    "外观设置": "Appearance",
    "下载队列": "Queue",
    "正在下载": "Active",
    "已完成": "Completed",
    "失败列表": "Failed",
    "日志中心": "Logs",
    "工具箱": "Toolbox",
    "配置中心": "Settings",
    "设置分类": "Categories",
    "启动任务": "Start",
    "停止": "Stop",
    "更改目录": "Change folder",
    "视频数:": "Videos:",
    "笔记数:": "Notes:",
    "页数:": "Pages:",
    "输入：主页链接、分享链接或合集链接...": "Enter a profile, shared, or collection link...",
    "切换主题": "Toggle theme",
    "空闲中": "Idle",
    "运行中": "Running",
    "下载速度": "Download",
    "上传速度": "Upload",
    "失败": "Failed",
    "下载目录、命名规则和打开行为": "Download folder, filename rules, and open behavior",
    "并发、超时、重试和下载策略": "Concurrency, timeout, retry, and download policy",
    "认证状态、默认数量和代理入口": "Auth status, default count, and proxy entry",
    "认证状态、爬取数量和代理入口": "Auth status, crawl quantity, and proxy entry",
    "播放器、进度记忆和预览行为": "Player, progress memory, and preview behavior",
    "保留策略、展示数量和错误追踪": "Retention policy, display limits, and error tracing",
    "语言、主题色、缩放和字体": "Language, accent, scale, and font",
    "语言、主题、配色和字体": "Language, theme, accent, and font",
    "语言、主题、界面缩放和字体": "Language, theme, scale, and font",
    "平台总数": "Platforms",
    "可配置代理": "Proxy-ready",
    "下载目录": "Download folder",
    "文件命名规则": "Filename rule",
    "下载后自动打开": "Open after download",
    "默认打开方式": "Default open mode",
    "绑定默认打开方式": "Bind default app",
    "并发数": "Concurrency",
    "图片受并发数限制": "Limit images by concurrency",
    "请求超时": "Request timeout",
    "最大重试": "Max retries",
    "速度限制 KB/s": "Speed limit KB/s",
    "仅下载视频": "Video only",
    "默认播放器": "Default player",
    "打开方式": "Open mode",
    "记住播放位置": "Remember position",
    "自动播放下一项": "Autoplay next",
    "手动切换图片": "Manual image switching",
    "保留天数": "Retention",
    "UI最大显示数": "Max UI logs",
    "日志级别": "Log level",
    "错误时自动复制 Trace": "Auto-copy Trace on error",
    "启动时清理旧日志": "Clean old logs on start",
    "语言": "Language",
    "跟随系统": "Follow system",
    "主题": "Theme",
    "主题色": "Accent color",
    "界面缩放": "UI scale",
    "字体大小": "Font size",
    "浅色": "Light",
    "深色": "Dark",
    "蓝色": "Blue",
    "绿色": "Green",
    "紫色": "Purple",
    "橙色": "Orange",
    "红色": "Red",
    "小": "Small",
    "中（推荐）": "Medium (Recommended)",
    "大": "Large",
    "100%（推荐）": "100% (Recommended)",
    "简体中文（推荐）": "Simplified Chinese (Recommended)",
    "繁體中文": "Traditional Chinese",
    "平台": "Platform",
    "认证状态": "Auth status",
    "默认数量": "Default count",
    "爬取数量": "Crawl quantity",
    "代理入口": "Proxy",
    "已认证": "Authed",
    "未认证": "Unauthed",
    "系统代理": "System proxy",
    "直连": "Direct",
    "直连（不使用代理）": "Direct (no proxy)",
    "自定义": "Custom",
    "自定义 HTTP/SOCKS5 端点": "Custom HTTP/SOCKS5 endpoint",
    "自定义端点，如 127.0.0.1:7890": "Custom endpoint, e.g. 127.0.0.1:7890",
    "端口": "Port",
    "当前命名方式": "Current naming rule",
    "默认": "Default",
    "标题": "Title",
    "平台_标题": "Platform_Title",
    "平台_标题_日期": "Platform_Title_Date",
    "平台_标题_序号": "Platform_Title_Index",
    "内置播放器": "Built-in player",
    "系统默认打开方式": "System default app",
    "系统默认播放器": "System default player",
    "打开所在目录": "Open containing folder",
    "无限制": "Unlimited",
    "保存至": "Save to",
    "标题": "Title",
    "状态": "Status",
    "进度": "Progress",
    "操作": "Actions",
    "速度": "Speed",
    "剩余时间": "Remaining",
    "完成时间": "Completed at",
    "时长": "Duration",
    "格式": "Format",
    "失败时间": "Failed at",
    "失败原因": "Reason",
    "任务动态（最近 3 条）": "Activity (latest 3)",
    "暂无队列任务": "No queued tasks",
    "失败自动重试": "Auto retry failed tasks",
    "最大重试次数": "Max retries",
    "并发数": "Concurrency",
    "当前下载": "Current download",
    "暂无正在下载的任务": "No active downloads",
    "选择已完成文件进行播放": "Select a completed file to play",
    "文件信息": "File info",
    "暂无已完成文件": "No completed files",
    "错误详情": "Error details",
    "暂无失败任务": "No failed tasks",
    "可能的解决方案": "Possible solutions",
    "暂无建议": "No suggestions",
    "全部日志": "All logs",
    "下载日志": "Download logs",
    "系统日志": "System logs",
    "错误日志": "Error logs",
    "日志级别": "Log level",
    "全部": "All",
    "时间范围": "Time range",
    "近 30 分钟": "Last 30 min",
    "近 1 小时": "Last 1 hour",
    "近 24 小时": "Last 24 hours",
    "关键词搜索": "Keyword search",
    "清空日志": "Clear logs",
    "导出日志": "Export logs",
    "刷新缓冲": "Refresh buffer",
    "时间": "Time",
    "级别": "Level",
    "来源": "Source",
    "消息摘要": "Summary",
    "日志详情": "Log details",
    "线程": "Thread",
    "消息": "Message",
    "详细信息": "Details",
    "系统": "System",
    "说明": "Description",
    "状态码": "Status code",
    "上下文": "Context",
    "详情": "Details",
    "页": "pages",
    "工具箱": "Toolbox",
    "链接解析": "Link parser",
    "批量重命名": "Batch rename",
    "封面提取": "Cover extraction",
    "视频转音频": "Video to audio",
    "本地去重扫描": "Local dedupe scan",
    "元数据查看": "Metadata viewer",
    "格式转换": "Format conversion",
    "文件校验": "File checksum",
    "最近使用": "Recent",
    "工具详情": "Tool details",
    "工具": "Tool",
    "说明": "Description",
    "输入示例": "Input example",
    "输出示例": "Output example",
    "打开工具": "Open tool",
    "今天": "Today",
    "解析网页或文本中的链接，提取视频、图片等资源地址": "Parse links from webpages or text and extract video/image resource URLs",
    "按规则、序号和预览结果批量重命名本地文件": "Batch rename local files by rules, sequence, and preview",
    "从视频文件中提取封面图片，支持单个或批量提取": "Extract cover images from videos individually or in batches",
    "将视频文件转换为音频，支持多种格式和质量设置": "Convert videos to audio with format and quality options",
    "扫描并查找重复文件，支持按内容或文件名去重": "Scan for duplicate files by content or filename",
    "查看视频、音频和图片文件的详细元数据": "Inspect detailed metadata for video, audio, and image files",
    "转换视频、音频和图片文件格式": "Convert video, audio, and image formats",
    "计算并校验文件哈希值，支持 MD5、SHA1、SHA256": "Calculate and verify file hashes including MD5, SHA1, and SHA256",
    "解析出视频、图片、作者主页等可下载资源地址": "Extract downloadable video, image, and author profile URLs",
  },
  "zh-TW": {
    "基础设置": "基礎設定",
    "下载设置": "下載設定",
    "平台设置": "平台設定",
    "播放设置": "播放設定",
    "日志设置": "日誌設定",
    "外观设置": "外觀設定",
    "下载队列": "下載隊列",
    "正在下载": "正在下載",
    "已完成": "已完成",
    "失败列表": "失敗列表",
    "日志中心": "日誌中心",
    "工具箱": "工具箱",
    "配置中心": "配置中心",
    "设置分类": "設定分類",
    "启动任务": "啟動任務",
    "停止": "停止",
    "更改目录": "變更目錄",
    "视频数:": "影片數:",
    "笔记数:": "筆記數:",
    "页数:": "頁數:",
    "输入：主页链接、分享链接或合集链接...": "輸入：主頁連結、分享連結或合集連結...",
    "切换主题": "切換主題",
    "空闲中": "閒置中",
    "运行中": "執行中",
    "下载速度": "下載速度",
    "上传速度": "上傳速度",
    "失败": "失敗",
    "下载目录、命名规则和打开行为": "下載目錄、命名規則和開啟行為",
    "并发、超时、重试和下载策略": "並發、逾時、重試和下載策略",
    "认证状态、默认数量和代理入口": "認證狀態、預設數量和代理入口",
    "认证状态、爬取数量和代理入口": "認證狀態、爬取數量和代理入口",
    "播放器、进度记忆和预览行为": "播放器、進度記憶和預覽行為",
    "保留策略、展示数量和错误追踪": "保留策略、展示數量和錯誤追蹤",
    "语言、主题色、缩放和字体": "語言、主題色、縮放和字體",
    "语言、主题、配色和字体": "語言、主題、配色和字體",
    "语言、主题、界面缩放和字体": "語言、主題、介面縮放和字體",
    "平台总数": "平台總數",
    "可配置代理": "可配置代理",
    "下载目录": "下載目錄",
    "文件命名规则": "檔案命名規則",
    "下载后自动打开": "下載後自動開啟",
    "默认打开方式": "預設開啟方式",
    "绑定默认打开方式": "綁定預設開啟方式",
    "并发数": "並發數",
    "图片受并发数限制": "圖片受並發數限制",
    "请求超时": "請求逾時",
    "最大重试": "最大重試",
    "速度限制 KB/s": "速度限制 KB/s",
    "仅下载视频": "僅下載影片",
    "默认播放器": "預設播放器",
    "打开方式": "開啟方式",
    "记住播放位置": "記住播放位置",
    "自动播放下一项": "自動播放下一項",
    "手动切换图片": "手動切換圖片",
    "保留天数": "保留天數",
    "UI最大显示数": "UI 最大顯示數",
    "日志级别": "日誌級別",
    "错误时自动复制 Trace": "錯誤時自動複製 Trace",
    "启动时清理旧日志": "啟動時清理舊日誌",
    "语言": "語言",
    "跟随系统": "跟隨系統",
    "主题": "主題",
    "主题色": "主題色",
    "界面缩放": "介面縮放",
    "字体大小": "字體大小",
    "浅色": "淺色",
    "深色": "深色",
    "蓝色": "藍色",
    "绿色": "綠色",
    "紫色": "紫色",
    "橙色": "橙色",
    "红色": "紅色",
    "小": "小",
    "中（推荐）": "中（推薦）",
    "大": "大",
    "100%（推荐）": "100%（推薦）",
    "简体中文（推荐）": "簡體中文（推薦）",
    "繁體中文": "繁體中文",
    "平台": "平台",
    "认证状态": "認證狀態",
    "默认数量": "預設數量",
    "爬取数量": "爬取數量",
    "代理入口": "代理入口",
    "已认证": "已認證",
    "未认证": "未認證",
    "系统代理": "系統代理",
    "直连": "直連",
    "直连（不使用代理）": "直連（不使用代理）",
    "自定义": "自訂",
    "自定义 HTTP/SOCKS5 端点": "自訂 HTTP/SOCKS5 端點",
    "自定义端点，如 127.0.0.1:7890": "自訂端點，如 127.0.0.1:7890",
    "端口": "連接埠",
    "当前命名方式": "目前命名方式",
    "默认": "預設",
    "标题": "標題",
    "平台_标题": "平台_標題",
    "平台_标题_日期": "平台_標題_日期",
    "平台_标题_序号": "平台_標題_序號",
    "内置播放器": "內建播放器",
    "系统默认打开方式": "系統預設開啟方式",
    "系统默认播放器": "系統預設播放器",
    "打开所在目录": "開啟所在目錄",
    "无限制": "無限制",
    "保存至": "儲存至",
    "标题": "標題",
    "状态": "狀態",
    "进度": "進度",
    "操作": "操作",
    "速度": "速度",
    "剩余时间": "剩餘時間",
    "完成时间": "完成時間",
    "时长": "時長",
    "格式": "格式",
    "失败时间": "失敗時間",
    "失败原因": "失敗原因",
    "任务动态（最近 3 条）": "任務動態（最近 3 條）",
    "暂无队列任务": "暫無佇列任務",
    "失败自动重试": "失敗自動重試",
    "最大重试次数": "最大重試次數",
    "并发数": "並發數",
    "当前下载": "目前下載",
    "暂无正在下载的任务": "暫無正在下載的任務",
    "选择已完成文件进行播放": "選擇已完成檔案進行播放",
    "文件信息": "檔案資訊",
    "暂无已完成文件": "暫無已完成檔案",
    "错误详情": "錯誤詳情",
    "暂无失败任务": "暫無失敗任務",
    "可能的解决方案": "可能的解決方案",
    "暂无建议": "暫無建議",
    "全部日志": "全部日誌",
    "下载日志": "下載日誌",
    "系统日志": "系統日誌",
    "错误日志": "錯誤日誌",
    "日志级别": "日誌級別",
    "全部": "全部",
    "时间范围": "時間範圍",
    "近 30 分钟": "近 30 分鐘",
    "近 1 小时": "近 1 小時",
    "近 24 小时": "近 24 小時",
    "关键词搜索": "關鍵字搜尋",
    "清空日志": "清空日誌",
    "导出日志": "匯出日誌",
    "刷新缓冲": "刷新緩衝",
    "时间": "時間",
    "级别": "級別",
    "来源": "來源",
    "消息摘要": "訊息摘要",
    "日志详情": "日誌詳情",
    "线程": "執行緒",
    "消息": "訊息",
    "详细信息": "詳細資訊",
    "系统": "系統",
    "说明": "說明",
    "状态码": "狀態碼",
    "上下文": "上下文",
    "详情": "詳情",
    "页": "頁",
    "工具箱": "工具箱",
    "链接解析": "連結解析",
    "批量重命名": "批次重新命名",
    "封面提取": "封面擷取",
    "视频转音频": "影片轉音訊",
    "本地去重扫描": "本機去重掃描",
    "元数据查看": "中繼資料檢視",
    "格式转换": "格式轉換",
    "文件校验": "檔案校驗",
    "最近使用": "最近使用",
    "工具详情": "工具詳情",
    "工具": "工具",
    "说明": "說明",
    "输入示例": "輸入範例",
    "输出示例": "輸出範例",
    "打开工具": "開啟工具",
    "今天": "今天",
    "解析网页或文本中的链接，提取视频、图片等资源地址": "解析網頁或文字中的連結，擷取影片、圖片等資源地址",
    "按规则、序号和预览结果批量重命名本地文件": "依規則、序號和預覽結果批次重新命名本機檔案",
    "从视频文件中提取封面图片，支持单个或批量提取": "從影片檔案擷取封面圖片，支援單個或批次處理",
    "将视频文件转换为音频，支持多种格式和质量设置": "將影片檔案轉換為音訊，支援多種格式和品質設定",
    "扫描并查找重复文件，支持按内容或文件名去重": "掃描並查找重複檔案，支援依內容或檔名去重",
    "查看视频、音频和图片文件的详细元数据": "檢視影片、音訊和圖片檔案的詳細中繼資料",
    "转换视频、音频和图片文件格式": "轉換影片、音訊和圖片檔案格式",
    "计算并校验文件哈希值，支持 MD5、SHA1、SHA256": "計算並校驗檔案雜湊值，支援 MD5、SHA1、SHA256",
    "解析出视频、图片、作者主页等可下载资源地址": "解析出影片、圖片、作者主頁等可下載資源地址",
  },
};

let UI_TEXT = FALLBACK_UI_TEXT;
let i18nCatalogLoadStarted = false;

async function loadUiTextCatalogs() {
  if (i18nCatalogLoadStarted) return;
  i18nCatalogLoadStarted = true;
  try {
    const entries = await Promise.all(["en-US", "zh-TW"].map(async language => {
      const response = await fetch(`/api/i18n/${encodeURIComponent(language)}`, { cache: "no-store" });
      if (!response.ok) return [language, {}];
      const catalog = await response.json();
      return [language, catalog && typeof catalog === "object" ? catalog : {}];
    }));
    UI_TEXT = { ...FALLBACK_UI_TEXT };
    for (const [language, catalog] of entries) {
      UI_TEXT[language] = { ...(FALLBACK_UI_TEXT[language] || {}), ...catalog };
    }
    applyStaticLanguage();
    renderCurrentPage();
  } catch (error) {
    console.warn("Failed to load UI i18n catalogs", error);
  }
}

function currentLanguage() {
  const appearance = (frontendState.settings_snapshot || {})["外观设置"] || {};
  const value = String(appearance.language || "zh-CN");
  return ["zh-CN", "en-US", "zh-TW"].includes(value) ? value : "zh-CN";
}

function t(text) {
  const value = String(text || "");
  return (UI_TEXT[currentLanguage()] || {})[value] || value;
}

function translateUiText(text) {
  const lang = currentLanguage();
  const value = String(text || "");
  if (lang === "zh-CN" || !value.trim()) return value;
  const leading = value.match(/^\s*/)?.[0] || "";
  const trailing = value.match(/\s*$/)?.[0] || "";
  const core = value.trim();
  const translated = translateUiCore(core, lang);
  return translated === core ? value : `${leading}${translated}${trailing}`;
}

function translateUiCore(text, lang = currentLanguage()) {
  const dict = UI_TEXT[lang] || {};
  if (dict[text]) return dict[text];
  if (text.includes("\n")) {
    return text.split("\n").map(part => translateUiCore(part.trim(), lang)).join("\n");
  }
  if (text.includes("\t")) {
    return text.split("\t").map(part => translateUiCore(part.trim(), lang)).join("\t");
  }
  let match = text.match(/^保存至：(.*)$/);
  if (match) return lang === "zh-TW" ? `儲存至：${match[1]}` : `Save to: ${match[1]}`;
  match = text.match(/^共\s*(\d+)\s*项$/);
  if (match) return lang === "zh-TW" ? `共 ${match[1]} 項` : `Total ${match[1]} items`;
  match = text.match(/^(\d+)\s*\/\s*(\d+)\s*页$/);
  if (match) return lang === "zh-TW" ? `${match[1]} / ${match[2]} 頁` : `${match[1]} / ${match[2]} pages`;
  match = text.match(/^(\d+)\s*条\/页$/);
  if (match) return lang === "zh-TW" ? `${match[1]} 條/頁` : `${match[1]} / page`;
  match = text.match(/^(\d+)次$/);
  if (match) return lang === "zh-TW" ? `${match[1]} 次` : `${match[1]} times`;
  match = text.match(/^当前运行：(\d+)\s*个任务$/);
  if (match) return lang === "zh-TW" ? `目前執行：${match[1]} 個任務` : `Running: ${match[1]} tasks`;
  match = text.match(/^打开\s+(.+)$/);
  if (match) return lang === "zh-TW" ? `開啟 ${match[1]}` : `Open ${match[1]}`;
  match = text.match(/^(.+?)[:：]\s*(.*)$/);
  if (match && dict[match[1].trim()]) {
    const label = translateUiCore(match[1].trim(), lang);
    return `${label}: ${match[2]}`;
  }
  match = text.match(/^(.+)\s+今天\s+(.+)$/);
  if (match) return `${translateUiCore(match[1].trim(), lang)}  ${translateUiCore("今天", lang)} ${match[2]}`;
  return text;
}

function translateVisibleText(root = document.body) {
  if (currentLanguage() === "zh-CN" || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      if (parent.closest("script, style, textarea, option, select")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(node => {
    const next = translateUiText(node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
  });
}

function optionLabel(label) {
  const text = String(label || "");
  if (text.toLowerCase() === "max") return "max";
  const videoMatch = text.match(/^(\d+)\s*个(?:视频|作品)(（推荐）)?$/);
  if (videoMatch && currentLanguage() === "en-US") {
    const noun = Number(videoMatch[1]) === 1 ? "video" : "videos";
    return `${videoMatch[1]} ${noun}${videoMatch[2] ? " (Recommended)" : ""}`;
  }
  if (videoMatch && currentLanguage() === "zh-TW") {
    return `${videoMatch[1]} 個影片${videoMatch[2] ? "（推薦）" : ""}`;
  }
  const noteMatch = text.match(/^(\d+)\s*篇笔记(（推荐）)?$/);
  if (noteMatch && currentLanguage() === "en-US") {
    const noun = Number(noteMatch[1]) === 1 ? "note" : "notes";
    return `${noteMatch[1]} ${noun}${noteMatch[2] ? " (Recommended)" : ""}`;
  }
  if (noteMatch && currentLanguage() === "zh-TW") {
    return `${noteMatch[1]} 篇筆記${noteMatch[2] ? "（推薦）" : ""}`;
  }
  const pageMatch = text.match(/^(\d+)\s*页(（推荐）)?$/);
  if (pageMatch && currentLanguage() === "en-US") {
    const noun = Number(pageMatch[1]) === 1 ? "page" : "pages";
    return `${pageMatch[1]} ${noun}${pageMatch[2] ? " (Recommended)" : ""}`;
  }
  if (pageMatch && currentLanguage() === "zh-TW") {
    return `${pageMatch[1]} 頁${pageMatch[2] ? "（推薦）" : ""}`;
  }
  return t(text);
}

function setButtonContent(buttonId, label) {
  const button = byId(buttonId);
  if (!button) return;
  const icon = button.querySelector("img");
  button.innerHTML = `${icon ? icon.outerHTML : ""}${esc(t(label))}`;
}

function applyStaticLanguage() {
  const navLabels = {
    queue: "下载队列",
    active: "正在下载",
    completed: "已完成",
    failed: "失败列表",
    logs: "日志中心",
    settings: "配置中心",
    toolbox: "工具箱",
  };
  document.querySelectorAll(".nav-item").forEach(button => {
    const label = navLabels[button.dataset.page];
    const target = button.querySelector("b");
    if (label && target) target.textContent = t(label);
  });
  setButtonContent("startBtn", "启动任务");
  setButtonContent("stopBtn", "停止");
  setButtonContent("changeDirBtn", "更改目录");
  const themeButton = byId("themeBtn");
  if (themeButton) themeButton.title = t("切换主题");
  updatePlaceholder();
  renderStatus();
  syncAllCustomSelects();
}

// Compatibility globals used by a few older browser tests.
let videos = {};
let videoOrder = [];
let selectedVideoId = null;
let currentPlayingId = null;
let isFullscreenMode = false;

const ACTION_ICON_FILES = {
  delete: "action_delete.png",
  pause: "action_pause.png",
  play: "action_play.png",
  open_directory: "action_open_directory.png",
  retry: "action_refresh.png",
  copy_diagnostics: "action_copy.png",
};

let iconManifest = {
  route: "/ui-icon",
  fallback: "view_grid.png",
  actions: ACTION_ICON_FILES,
};
let renderSignatures = {};
let frontendVersion = 0;
let pendingRenderSections = new Set();
let renderFrame = null;
let frontendDeltaTimer = null;


function scheduleFrame(callback) {
  const raf = window.requestAnimationFrame || (fn => setTimeout(fn, 16));
  raf(callback);
}

function scheduleRenderSections(sections) {
  const list = Array.isArray(sections) ? sections : [sections || "all"];
  for (const section of list) pendingRenderSections.add(section || "all");
  if (renderFrame) return;
  renderFrame = true;
  scheduleFrame(() => {
    renderFrame = null;
    flushRenderSections();
  });
}

function flushRenderSections() {
  const sections = new Set(pendingRenderSections);
  pendingRenderSections.clear();
  if (!sections.size || sections.has("all")) {
    renderAll();
    return;
  }
  const previousLanguage = document.documentElement.dataset.language || "zh-CN";
  const itemSections = ["queue_items", "active_downloads", "completed_items", "failed_items"];
  if (sections.has("settings_snapshot")) {
    syncAppearanceFromSettings();
    if ((document.documentElement.dataset.language || "zh-CN") !== previousLanguage) {
      renderAll();
      return;
    }
  }
  if (itemSections.some(section => sections.has(section))) {
    rebuildCompatibilityState();
    renderCounts();
  }
  if (sections.has("queue_items") && currentPage === "queue") renderQueue();
  if (sections.has("settings_snapshot") && currentPage === "queue" && !sections.has("queue_items")) renderQueue();
  const shouldRenderActive =
    currentPage === "active" &&
    (sections.has("active_downloads") || sections.has("download_options") || sections.has("settings_snapshot"));
  if (shouldRenderActive) renderActive();
  if (sections.has("completed_items") && currentPage === "completed") renderCompleted();
  if (sections.has("failed_items") && currentPage === "failed") renderFailed();
  if (sections.has("log_items") && currentPage === "logs") renderLogs();
  if ((sections.has("settings_snapshot") || sections.has("settings_contract")) && currentPage === "settings") {
    renderSettings();
  }
  if (sections.has("settings_snapshot")) configureTopCountForSource(byId("sourceSelect")?.value || "douyin");
  if ((sections.has("toolbox_items") || sections.has("toolbox_recent_items")) && currentPage === "toolbox") renderToolbox();
  if (sections.has("icon_manifest")) renderCurrentPage();
  if (sections.has("app_status")) renderStatus();
}

function applyFrontendDelta(delta) {
  if (!delta || typeof delta !== "object") return;
  const localVersion = Number(frontendVersion || 0);
  const deltaVersion = Number(delta.version || 0);
  if (!delta.full && deltaVersion && deltaVersion <= localVersion) return;
  const deltaBaseVersion = Number(delta.base_version || 0);
  if (!delta.full && deltaBaseVersion > localVersion) {
    appendLog("\u589e\u91cf\u72b6\u6001\u57fa\u7ebf\u4e0d\u8fde\u7eed\uff0c\u6b63\u5728\u91cd\u65b0\u540c\u6b65...");
    fetchFrontendState();
    return;
  }
  const sections = delta.sections || {};
  const changed = Array.isArray(delta.changed_sections) ? delta.changed_sections.slice() : Object.keys(sections);
  if (delta.full && sections && Object.keys(sections).length) {
    frontendState = { ...frontendState, ...sections };
  } else {
    for (const [key, value] of Object.entries(sections)) frontendState[key] = value;
  }
  if (trimFrontendLogItems() && !changed.includes("log_items")) changed.push("log_items");
  if (sections.icon_manifest) {
    updateIconManifest(sections.icon_manifest);
    if (!changed.includes("icon_manifest")) changed.push("icon_manifest");
  }
  if (Array.isArray(delta.deleted_ids) && delta.deleted_ids.length) {
    removeDeletedFromFrontendState(delta.deleted_ids);
    for (const section of ["queue_items", "active_downloads", "completed_items", "failed_items"]) {
      if (!changed.includes(section)) changed.push(section);
    }
  }
  frontendVersion = Number(delta.version || frontendVersion || 0);
  scheduleRenderSections(changed.length ? changed : ["all"]);
}

function removeDeletedFromFrontendState(ids) {
  const doomed = new Set(ids.map(id => String(id)));
  for (const id of doomed) removePlaybackPosition(id);
  for (const section of ["queue_items", "active_downloads", "completed_items", "failed_items"]) {
    frontendState[section] = (frontendState[section] || []).filter(item => !doomed.has(String(item.id)));
  }
  for (const key of ["active", "completed", "failed"]) {
    if (doomed.has(String(selected[key] || ""))) selected[key] = "";
  }
  if (doomed.has(String(selectedVideoId || ""))) selectedVideoId = null;
  if (doomed.has(String(currentPlayingId || ""))) currentPlayingId = null;
}

function applyLegacyFrontendEvent(type, data) {
  if (type === "video_removed") {
    removeDeletedFromFrontendState([data.video_id || data.id || ""]);
    scheduleRenderSections(["queue_items", "active_downloads", "completed_items", "failed_items", "app_status"]);
    return;
  }
  if (type === "clear_videos") {
    frontendState.queue_items = [];
    frontendState.active_downloads = [];
    frontendState.completed_items = [];
    frontendState.failed_items = [];
    scheduleRenderSections(["queue_items", "active_downloads", "completed_items", "failed_items", "app_status"]);
    return;
  }
  if (type === "video_state_changed" || type === "task_progress") {
    patchLegacyProgress(data || {});
    scheduleRenderSections(["active_downloads", "app_status"]);
    return;
  }
  scheduleFrontendDeltaFetch(300);
}

function patchLegacyProgress(data) {
  const videoId = String(data.video_id || data.id || "");
  if (!videoId) return;
  const rows = frontendState.active_downloads || [];
  const row = rows.find(item => String(item.id) === videoId);
  if (!row) return;
  if (data.progress !== undefined && data.progress !== null) row.progress = Number(data.progress) || 0;
  if (data.status) row.status = data.status;
  if (data.speed) row.speed = data.speed;
}

function scheduleFrontendDeltaFetch(delayMs = 200) {
  if (frontendDeltaTimer) clearTimeout(frontendDeltaTimer);
  frontendDeltaTimer = setTimeout(fetchFrontendDelta, delayMs);
}

async function fetchFrontendDelta() {
  try {
    const response = await fetch(`/api/frontend/delta?since_version=${encodeURIComponent(frontendVersion || 0)}`, { cache: "no-store" });
    if (!response.ok) return;
    applyFrontendDelta(await response.json());
  } catch (error) {
    appendLog(`\u52a0\u8f7d\u589e\u91cf\u72b6\u6001\u5931\u8d25: ${error.message || error}`);
  }
}

function setHtmlIfChanged(id, html, key = id) {
  if (renderSignatures[key] === html) return false;
  byId(id).innerHTML = html;
  renderSignatures[key] = html;
  queueMicrotask(() => enhanceSelects(byId(id)));
  return true;
}

function enhanceSelects(root = document) {
  const scope = root || document;
  scope.querySelectorAll("select").forEach(select => {
    if (select.closest(".custom-select")) {
      syncCustomSelectForSelect(select);
      return;
    }
    const wrapper = document.createElement("span");
    wrapper.className = "custom-select";
    if (select.classList.contains("source-select")) wrapper.classList.add("custom-select-source");
    if (select.classList.contains("count-select")) wrapper.classList.add("custom-select-count");
    for (const className of ["platform-auth", "platform-count", "platform-proxy"]) {
      if (select.classList.contains(className)) wrapper.classList.add(className);
    }
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "custom-select-button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    wrapper.appendChild(button);

    const menu = document.createElement("div");
    menu.className = "custom-select-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    wrapper.appendChild(menu);

    button.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      toggleCustomSelect(wrapper);
    });
    button.addEventListener("keydown", event => handleCustomSelectKeydown(event, wrapper));
    select.addEventListener("change", () => syncCustomSelectForSelect(select));
    syncCustomSelectForSelect(select);
  });
}

function syncAllCustomSelects(root = document) {
  (root || document).querySelectorAll(".custom-select > select").forEach(syncCustomSelectForSelect);
}

function syncCustomSelectForSelect(select) {
  const wrapper = select && select.closest(".custom-select");
  if (!wrapper) return;
  wrapper.style.setProperty("--option-count", String(Math.max(1, select.options.length)));
  Array.from(select.options).forEach(option => {
    if (!option.dataset.originalLabel) option.dataset.originalLabel = option.textContent || "";
    option.textContent = translateUiText(option.dataset.originalLabel);
  });
  const button = wrapper.querySelector(".custom-select-button");
  const menu = wrapper.querySelector(".custom-select-menu");
  const selected = select.selectedOptions && select.selectedOptions[0] ? select.selectedOptions[0] : select.options[select.selectedIndex];
  const text = selected ? selected.textContent : "";
  wrapper.classList.toggle("is-disabled", select.disabled);
  if (button) {
    const fallbackLabel = select.getAttribute("aria-label") || select.dataset.setting || "Select";
    button.disabled = select.disabled;
    button.textContent = text;
    button.title = text || fallbackLabel;
    button.setAttribute("aria-label", text || fallbackLabel);
    button.setAttribute("aria-expanded", String(!menu?.hidden));
  }
  if (menu) renderCustomSelectMenu(select, menu);
}

function renderCustomSelectMenu(select, menu) {
  const current = String(select.value ?? "");
  menu.innerHTML = Array.from(select.options).map(option => {
    const selected = String(option.value) === current;
    return `<button type="button" role="option" class="custom-select-option${selected ? " selected" : ""}" data-value="${escAttr(option.value)}" aria-selected="${selected ? "true" : "false"}">${esc(option.textContent || "")}</button>`;
  }).join("");
  menu.querySelectorAll(".custom-select-option").forEach(optionButton => {
    optionButton.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      chooseCustomSelectOption(select, optionButton.dataset.value || "");
    });
  });
}

function toggleCustomSelect(wrapper) {
  const select = wrapper.querySelector("select");
  if (!select || select.disabled) return;
  if (openCustomSelect === wrapper) {
    closeCustomSelect(wrapper, true);
    return;
  }
  closeCustomSelect();
  const menu = wrapper.querySelector(".custom-select-menu");
  const button = wrapper.querySelector(".custom-select-button");
  renderCustomSelectMenu(select, menu);
  wrapper.classList.add("open");
  if (menu) menu.hidden = false;
  if (button) button.setAttribute("aria-expanded", "true");
  openCustomSelect = wrapper;
}

function closeCustomSelect(wrapper = openCustomSelect, focusButton = false) {
  if (!wrapper) return;
  const menu = wrapper.querySelector(".custom-select-menu");
  const button = wrapper.querySelector(".custom-select-button");
  wrapper.classList.remove("open");
  if (menu) menu.hidden = true;
  if (button) {
    button.setAttribute("aria-expanded", "false");
    if (focusButton) button.focus();
  }
  if (openCustomSelect === wrapper) openCustomSelect = null;
}

function chooseCustomSelectOption(select, value) {
  if (!select || select.disabled) return;
  select.value = value;
  select.dispatchEvent(new Event("change", { bubbles: true }));
  syncCustomSelectForSelect(select);
  closeCustomSelect(select.closest(".custom-select"), true);
}

function handleCustomSelectKeydown(event, wrapper) {
  const select = wrapper.querySelector("select");
  if (!select || select.disabled) return;
  const options = Array.from(select.options);
  const currentIndex = Math.max(0, select.selectedIndex);
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    toggleCustomSelect(wrapper);
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeCustomSelect(wrapper, true);
  } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const next = Math.max(0, Math.min(options.length - 1, currentIndex + delta));
    if (options[next]) chooseCustomSelectOption(select, options[next].value);
  }
}

document.addEventListener("click", event => {
  if (openCustomSelect && !openCustomSelect.contains(event.target)) closeCustomSelect();
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeCustomSelect();
});


function patchTableRows(tbodyId, rows, keyFn, rowHtmlFn) {
  const tbody = byId(tbodyId);
  if (!tbody) return;
  const existing = new Map();
  Array.from(tbody.children).forEach(row => {
    const key = row.dataset.key || row.dataset.id;
    if (key) existing.set(key, row);
  });
  const seen = new Set();
  rows.forEach((item, index) => {
    const key = String(keyFn(item, index));
    seen.add(key);
    const html = String(rowHtmlFn(item, index) || "").trim();
    const sigKey = `${tbodyId}:${key}`;
    let row = existing.get(key);
    if (!row || renderSignatures[sigKey] !== html) {
      const template = document.createElement("template");
      template.innerHTML = html;
      const next = template.content.firstElementChild;
      if (!next) return;
      next.dataset.key = key;
      if (row) row.replaceWith(next);
      row = next;
      renderSignatures[sigKey] = html;
    }
    const current = tbody.children[index];
    if (current !== row) tbody.insertBefore(row, current || null);
  });
  Array.from(tbody.children).forEach(row => {
    const key = row.dataset.key || row.dataset.id;
    if (key && !seen.has(key)) {
      delete renderSignatures[`${tbodyId}:${key}`];
      row.remove();
    }
  });
}

function hasFocusedDescendant(id) {
  const root = byId(id);
  return !!(root && document.activeElement && root.contains(document.activeElement));
}

function restoreLayoutState() {
  const width = Number(localStorage.getItem("webui_detail_width") || 0);
  if (width >= 320) document.documentElement.style.setProperty("--detail-width", `${Math.min(width, 680)}px`);
}

function installDetailResizeHandlers() {
  let resizing = false;
  document.addEventListener("pointerdown", event => {
    const panel = event.target && event.target.closest ? event.target.closest(".detail-panel") : null;
    if (!panel || event.clientX - panel.getBoundingClientRect().left > 10) return;
    resizing = true;
    event.preventDefault();
  });
  document.addEventListener("pointermove", event => {
    if (!resizing) return;
    const width = Math.max(320, Math.min(680, window.innerWidth - event.clientX - 24));
    document.documentElement.style.setProperty("--detail-width", `${width}px`);
    localStorage.setItem("webui_detail_width", String(width));
  });
  document.addEventListener("pointerup", () => { resizing = false; });
}

document.addEventListener("DOMContentLoaded", () => {
  restoreTheme();
  restoreLayoutState();
  installDetailResizeHandlers();
  restoreQueueControls();
  loadUiTextCatalogs();
  renderAll();
  loadPlatforms();
  fetchFrontendState();
  connectWS();
  document.getElementById("sourceSelect").addEventListener("change", cacheSource);
  document.getElementById("searchInput").addEventListener("keydown", event => {
    if (event.key === "Enter") startCrawl();
  });
});

function buildMockState() {
  return {
    pages: [
      { id: "queue", title: "下载队列" },
      { id: "active", title: "正在下载" },
      { id: "completed", title: "已完成" },
      { id: "failed", title: "失败列表" },
      { id: "logs", title: "日志中心" },
      { id: "settings", title: "配置中心" },
      { id: "toolbox", title: "工具箱" },
    ],
    queue_items: [
      { id: "q1", title: "川西雪山之旅 | 云海翻涌的一天", platform: "抖音", platform_id: "douyin", status: "已解析", progress: 100, created_at: "2026-04-12 18:24", actions: ["delete"] },
      { id: "q2", title: "雨后山间的清晨", platform: "抖音", platform_id: "douyin", status: "待下载", progress: 0, created_at: "2026-04-12 07:31", actions: ["delete"] },
      { id: "q3", title: "城市夜景延时摄影", platform: "Bilibili", platform_id: "bilibili", status: "排队中", progress: 0, created_at: "2026-04-11 21:18", actions: ["delete"] },
    ],
    active_downloads: [
      { id: "a1", title: "川西雪山之旅 | 云海翻涌的一天", platform: "抖音", progress: 65, speed: "4.2 MB/s", remaining_time: "00:01:42", eta: "00:01:42", trace_id: "dy_20260412_182452_a1", save_dir: "D:\\desktop\\Videos", output_filename: "douyin_snow_mountain_20260412.mp4", thread_count: 8, retry_count: 0, write_status: "正在写入（39 个分片）", merge_status: "等待全部分片完成后自动合并", source_url: "https://v.douyin.com/abc123", chunk_progress: { completed: 39, total: 60, percent: 65 }, speed_trend: [3.2, 3.6, 3.1, 4.2, 3.8, 4.9], events: [{ time: "20:12:03", message: "开始下载" }, { time: "20:12:06", message: "写入分片 #39" }] },
    ],
    completed_items: [
      { id: "c1", title: "川西雪山之旅 | 云海翻涌的一天", completed_at: "2026-04-12 18:24:35", completed_at_table: "04-12 18:24", duration: "00:00:24", resolution: "1920 x 1080", size: "24.6 MB", format: "MP4", filename: "川西雪山之旅_20260412.mp4", save_dir: "D:\\desktop\\视频", download_speed: "4.2 MB/s", download_speed_bps: 4404019, local_path: "D:\\desktop\\视频\\川西雪山之旅_20260412.mp4", content_type: "video", metadata_pending: false, actions: ["play", "open_directory", "delete"] },
    ],
    failed_items: [
      { id: "f1", title: "南岳山间的清晨", failed_at: "2026-04-12 07:31:12", reason: "需要登录", status: "失败", trace_id: "dy_failed_001", platform: "抖音", log_excerpt: ["请求视频链接", "接口返回需要登录", "任务标记为失败"], solutions: [{ title: "确认登录态", description: "检查平台认证状态。" }, { title: "重新获取链接", description: "登录后重新复制分享链接并重试。" }], actions: ["retry", "copy_diagnostics", "delete"] },
    ],
    log_items: [
      { time: "2026-04-12 18:24:35", level: "INFO", source: "下载器", thread: "download-worker-1", trace_id: "dy_log_001", message_summary: "开始下载视频", message: "开始下载视频", detail: "{}", stack: "" },
      { time: "2026-04-12 18:25:03", level: "ERROR", source: "下载器", thread: "download-worker-1", trace_id: "dy_log_002", message_summary: "下载失败：无法解析视频播放地址", message: "下载失败：无法解析视频播放地址", detail: "code: 1001", stack: "" },
    ],
    settings_snapshot: {
      "\u57fa\u7840\u8bbe\u7f6e": { download_directory: "D:\\desktop\\Videos", filename_template: "current", filename_template_label: "\u9ed8\u8ba4", open_after_download: false, default_open_mode: "builtin_player", default_open_mode_label: "\u5185\u7f6e\u64ad\u653e\u5668", _options: { filename_template: [{ value: "current", label: "\u9ed8\u8ba4" }, { value: "{title}", label: "\u6807\u9898" }], default_open_mode: [{ value: "builtin_player", label: "\u5185\u7f6e\u64ad\u653e\u5668" }, { value: "system_default", label: "\u7cfb\u7edf\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f" }, { value: "open_directory", label: "\u6253\u5f00\u6240\u5728\u76ee\u5f55" }] } },
      "下载设置": {
        max_concurrent: 3,
        request_timeout: 30,
        max_retries: 3,
        resume_enabled: true,
        speed_limit_kb: 0,
        video_only: false,
        image_respects_concurrency: false,
      },
      "平台设置": [{ id: "douyin", name: "抖音", auth_status: "已认证", default_count: 20, count_config_key: "max_items", count_unit: "videos", count_editable: true, count_options: countFallbackOptions("videos"), default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒" }], proxy: "系统代理", proxy_config_key: "", proxy_editable: false }],
      "播放设置": {
        default_player: "builtin_player",
        default_player_label: "内置播放器",
        remember_position: true,
        autoplay_next: true,
        manual_image_switch: true,
        image_auto_advance_interval_seconds: 5,
        _options: {
          default_player: [{ value: "builtin_player", label: "内置播放器" }, { value: "system_default", label: "系统默认播放器" }],
          image_auto_advance_interval_seconds: [{ value: "1", label: "1 秒" }, { value: "3", label: "3 秒" }, { value: "5", label: "5 秒（推荐）" }, { value: "10", label: "10 秒" }],
        },
      },
      "日志设置": { retention_days: 1, ui_log_max_display_count: 300, auto_copy_trace_on_error: true, _options: { retention_days: [{ value: "1", label: "1 天（推荐）" }, { value: "3", label: "3 天" }, { value: "5", label: "5 天" }, { value: "7", label: "7 天" }], ui_log_max_display_count: [{ value: "300", label: "300 条（推荐）" }, { value: "500", label: "500 条" }, { value: "1000", label: "1000 条" }, { value: "2000", label: "2000 条" }, { value: "5000", label: "5000 条" }] } },
      "外观设置": { follow_system: false, theme: "light", accent: "blue", accent_label: "蓝色", scale: "100%", font_size: "medium", font_size_label: "中（推荐）", language: "zh-CN", language_label: "简体中文（推荐）", _options: { theme: [{ value: "light", label: "浅色" }, { value: "dark", label: "深色" }], accent: [{ value: "blue", label: "蓝色" }, { value: "green", label: "绿色" }], scale: [{ value: "90%", label: "90%" }, { value: "100%", label: "100%（推荐）" }, { value: "110%", label: "110%" }, { value: "125%", label: "125%" }], font_size: [{ value: "small", label: "小" }, { value: "medium", label: "中（推荐）" }, { value: "large", label: "大" }], language: [{ value: "zh-CN", label: "简体中文（推荐）" }, { value: "en-US", label: "English" }, { value: "zh-TW", label: "繁體中文" }] } },
    },
    settings_contract: {
      group_order: ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"],
      group_descriptions: {
        "基础设置": "下载目录、命名规则、打开行为",
        "下载设置": "下载并发、超时、重试、下载策略",
      "平台设置": "账号验证、爬取数量和代理入口",
        "播放设置": "播放器、进度记录和预览行为",
        "日志设置": "日志留存、显示条数与错误追踪",
        "外观设置": "语言、主题、配色和字体",
      },
    },
    download_options: { auto_retry: true, max_retries: 3, max_concurrent: 3, image_respects_concurrency: false },
    toolbox_items: [
      { id: "link_parser", title: "链接解析", summary: "解析网页或文本中的链接，提取视频、图片等资源地址", input_example: "https://www.douyin.com/user/MS4wLjABAAAA...", output_example: "解析出视频、图片、作者主页等可下载资源地址" },
      { id: "batch_rename", title: "批量重命名", summary: "批量重命名文件，支持规则、序号和预览", input_example: "D:\\Videos\\*.mp4 + {platform}_{title}_{index}", output_example: "生成可预览、可回滚的批量重命名方案" },
      { id: "cover_extract", title: "封面提取", summary: "提取视频封面图片，支持单个或批量提取", input_example: "选择本地视频文件或下载完成列表", output_example: "导出 JPG/PNG 封面图并写入文件信息" },
      { id: "video_to_audio", title: "视频转音频", summary: "将视频文件转换为音频", input_example: "MP4/MKV/WebM 视频文件", output_example: "输出 MP3/AAC/WAV 音频文件" },
      { id: "dedupe_scan", title: "本地去重扫描", summary: "扫描并查找重复文件", input_example: "选择下载目录或任意本地目录", output_example: "生成重复文件分组和可清理建议" },
      { id: "metadata_viewer", title: "元数据查看", summary: "查看视频、音频和图片元数据", input_example: "本地视频、音频、图片文件", output_example: "展示编码、分辨率、时长、码率和容器信息" },
      { id: "format_convert", title: "格式转换", summary: "转换视频、音频和图片格式", input_example: "选择源文件和目标格式", output_example: "输出转换后的媒体文件并保留来源记录" },
      { id: "file_verify", title: "文件校验", summary: "计算并校验文件哈希值", input_example: "选择一个或多个本地文件", output_example: "输出 MD5、SHA1、SHA256 校验值" },
    ],
    toolbox_recent_items: [
      { id: "link_parser", title: "链接解析", last_used: "今天 18:24" },
      { id: "video_to_audio", title: "视频转音频", last_used: "今天 17:35" },
      { id: "metadata_viewer", title: "元数据查看", last_used: "今天 14:10" },
    ],
    app_status: { running_state: "空闲中", download_speed: "0 B/s", upload_speed: "0 B/s", completed_count: 128, failed_count: 7, version: "v1.0.0" },
  };
}

async function fetchFrontendState() {
  try {
    const response = await fetch("/api/frontend/state", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (data && data.queue_items) {
      frontendState = data;
      trimFrontendLogItems();
      frontendVersion = Number(data.version || frontendVersion || 0);
      updateIconManifest(data.icon_manifest);
      renderAll();
    }
  } catch (error) {
    appendLog(`加载状态失败: ${error.message || error}`);
  }
}

async function loadPlatforms() {
  try {
    const response = await fetch("/api/platforms", { cache: "no-store" });
    platforms = await response.json();
    renderPlatforms();
  } catch (_error) {
    platforms = [
      { id: "douyin", name: "抖音", search_placeholder: "输入：主页链接、分享链接或合集链接..." },
      { id: "bilibili", name: "Bilibili", search_placeholder: "\u8f93\u5165\uff1aBV\u53f7\u3001UP\u4e3bID\u3001\u5408\u96c6\u94fe\u63a5\u3001\u4e3b\u9875\u94fe\u63a5\u3001\u89c6\u9891\u94fe\u63a5\u3001\u5206\u4eab\u94fe\u63a5\u6216\u5173\u952e\u8bcd..." },
    ];
    renderPlatforms();
  }
}

function renderPlatforms() {
  const select = document.getElementById("sourceSelect");
  const cached = localStorage.getItem("cached_last_source") || "";
  select.innerHTML = platforms.map(platform => `<option value="${esc(platform.id)}">${esc(platform.name)}</option>`).join("");
  if (cached) select.value = cached;
  enhanceSelects(select.parentElement || document);
  syncCustomSelectForSelect(select);
  updatePlaceholder();
}

function platformSettingsRow(platformId) {
  const rows = (frontendState.settings_snapshot || {})["平台设置"] || [];
  return Array.isArray(rows) ? rows.find(row => row.id === platformId) || null : null;
}

function countFallbackOptions(unit) {
  if (unit === "pages") {
    return [
      { value: "1", label: "1 页（推荐）" },
      { value: "2", label: "2 页" },
      { value: "3", label: "3 页" },
      { value: "5", label: "5 页" },
      { value: "9999", label: "max" },
    ];
  }
  if (unit === "notes") {
    return [
      { value: "10", label: "10 篇笔记" },
      { value: "20", label: "20 篇笔记（推荐）" },
      { value: "30", label: "30 篇笔记" },
      { value: "50", label: "50 篇笔记" },
      { value: "9999", label: "max" },
    ];
  }
  return [
    { value: "10", label: "10 个视频" },
    { value: "20", label: "20 个视频（推荐）" },
    { value: "30", label: "30 个视频" },
    { value: "50", label: "50 个视频" },
    { value: "9999", label: "max" },
  ];
}

function countOptionLabel(value, unit) {
  const text = String(value || "");
  if (!text) return "";
  if (text === "9999") return "max";
  if (unit === "pages") return `${text} 页`;
  if (unit === "notes") return `${text} 篇笔记`;
  return `${text} 个视频`;
}

function countLabelText(unit) {
  if (unit === "pages") return "页数:";
  if (unit === "notes") return "笔记数:";
  return "视频数:";
}

function configureTopCountForSource(sourceId) {
  const row = platformSettingsRow(sourceId);
  const unit = row && row.count_unit ? row.count_unit : "videos";
  const select = byId("videoCountSelect");
  const label = document.querySelector(".count-label");
  if (!select) return;

  let options = ((row && row.count_options) || countFallbackOptions(unit)).map(normalizeSettingOption).filter(option => option.value);
  const currentValue = String((row && row.default_count) || (unit === "pages" ? 1 : 20));
  if (!options.some(option => option.value === currentValue)) {
    options.unshift({
      value: currentValue,
      label: countOptionLabel(currentValue, unit),
    });
  }
  select.innerHTML = options.map(option => `<option value="${escAttr(option.value)}" ${option.value === currentValue ? "selected" : ""}>${esc(optionLabel(option.label))}</option>`).join("");
  const labelText = countLabelText(unit);
  if (label) label.textContent = t(labelText);
  select.setAttribute("aria-label", t(labelText));
  enhanceSelects(select.parentElement || document);
  syncCustomSelectForSelect(select);
}

function connectWS() {
  try {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.onmessage = event => handleServerMessage(JSON.parse(event.data));
    ws.onclose = () => setTimeout(connectWS, 2000);
  } catch (_error) {
    ws = null;
  }
}

function handleServerMessage(message) {
  const type = message.type;
  const data = message.data || {};
  switch (type) {
    case "init_state":
      if (data && typeof data.is_crawling === "boolean") {
        byId("startBtn").disabled = data.is_crawling;
        byId("stopBtn").disabled = !data.is_crawling;
      }
      break;
    case "frontend_state":
      frontendState = data;
      trimFrontendLogItems();
      frontendVersion = Number(data.version || frontendVersion || 0);
      updateIconManifest(data.icon_manifest);
      renderAll();
      break;
    case "frontend_delta":
      applyFrontendDelta(data);
      break;
    case "platforms":
      platforms = data;
      renderPlatforms();
      break;
    case "config":
      restoreTheme();
      break;
    case "crawl_state":
      document.getElementById("startBtn").disabled = !!data.is_running;
      document.getElementById("stopBtn").disabled = !data.is_running;
      scheduleFrontendDeltaFetch(200);
      break;
    case "log":
      appendLog(data.message || "");
      scheduleRenderSections(["log_items", "app_status"]);
      break;
    case "item_found":
    case "video_state_changed":
    case "video_renamed":
    case "video_removed":
    case "clear_videos":
    case "task_started":
    case "task_progress":
    case "task_finished":
    case "task_error":
    case "scan_result":
      applyLegacyFrontendEvent(type, data);
      break;
    case "select_tasks":
      showSelectionModal(data.items || []);
      break;
    case "frontend_action_result":
      if (data.frontend_delta) {
        applyFrontendDelta(data.frontend_delta);
      }
      if (data.message) appendLog(data.message);
      break;
    default:
      break;
  }
}

function renderAll() {
  syncAppearanceFromSettings();
  trimFrontendLogItems();
  configureTopCountForSource(byId("sourceSelect")?.value || "douyin");
  rebuildCompatibilityState();
  renderCounts();
  renderQueue();
  renderActive();
  renderCompleted();
  renderFailed();
  renderLogs();
  renderSettings();
  renderToolbox();
  renderStatus();
  enhanceSelects();
  translateVisibleText();
}

function renderCurrentPage() {
  if (currentPage === "queue") renderQueue();
  else if (currentPage === "active") renderActive();
  else if (currentPage === "completed") renderCompleted();
  else if (currentPage === "failed") renderFailed();
  else if (currentPage === "logs") renderLogs();
  else if (currentPage === "settings") renderSettings();
  else if (currentPage === "toolbox") renderToolbox();
  renderStatus();
  enhanceSelects();
  translateVisibleText();
}

function syncThemeFromSettings() {
  syncAppearanceFromSettings();
}

function syncAppearanceFromSettings() {
  const appearance = (frontendState.settings_snapshot || {})["\u5916\u89c2\u8bbe\u7f6e"] || {};
  applyAppearance(appearance);
}
function rebuildCompatibilityState() {
  videos = {};
  videoOrder = [];
  const all = [
    ...(frontendState.queue_items || []),
    ...(frontendState.active_downloads || []),
    ...(frontendState.completed_items || []),
    ...(frontendState.failed_items || []),
  ];
  for (const item of all) {
    videos[item.id] = item;
    videoOrder.push(item.id);
  }
}

function renderCounts() {
  byId("countQueue").textContent = String((frontendState.queue_items || []).length);
  byId("countActive").textContent = String((frontendState.active_downloads || []).length);
  byId("countCompleted").textContent = String((frontendState.completed_items || []).length);
  byId("countFailed").textContent = String((frontendState.failed_items || []).length);
}

function renderQueue() {
  byId("queuePath").textContent = (((frontendState.settings_snapshot || {})["基础设置"] || {}).download_directory || "");
  const allItems = frontendState.queue_items || [];
  const totalPages = Math.max(1, Math.ceil(allItems.length / queuePageSize));
  queuePage = Math.max(1, Math.min(queuePage, totalPages));
  const start = (queuePage - 1) * queuePageSize;
  const items = allItems.slice(start, start + queuePageSize);
  patchTableRows("queueBody", items, item => item.id, item => `
    <tr data-id="${escAttr(item.id)}">
      <td title="${escAttr(item.title)}">${queueTitleHtml(item)}</td>
      <td>${platformHtml(item.platform, item.platform_id)}</td>
      <td>${queueStatusHtml(item.status)}</td>
      <td>${progressHtml(item.progress)}</td>
      <td>${actionButton("delete", "删除", `event.stopPropagation();frontendAction('delete_item',{id:'${escAttr(item.id)}'})`, true)}</td>
    </tr>
  `);
  byId("queueTotal").textContent = `共 ${allItems.length} 项`;
  byId("queuePageNow").textContent = String(queuePage);
  byId("queueTotalPages").textContent = String(totalPages);
  byId("queuePageSize").value = String(queuePageSize);
  const recent = (frontendState.queue_items || []).slice(-3).reverse();
  const eventsHtml = `
    <strong>任务动态（最近 3 条）</strong>
    ${recent.length ? recent.map(item => `<span title="${escAttr(item.title)}">${esc(item.status || "待下载")}：${esc(item.title || "")}</span>`).join("") : "<span>暂无队列任务</span>"}
  `;
  setHtmlIfChanged("queueEvents", eventsHtml);
}

function queueTitleHtml(item) {
  const subtitle = item.created_at || item.discovered_at || item.added_at || "";
  return `<span class="title-main">${esc(item.title)}</span>${subtitle ? `<span class="title-sub">${esc(subtitle)}</span>` : ""}`;
}

function platformHtml(platform, platformId) {
  const icon = platformId ? platformIcon(platformId) : "";
  return `<span class="platform-cell">${icon ? `<img src="${escAttr(icon)}" alt="" />` : ""}${esc(platform || "本地")}</span>`;
}

function platformIcon(platformId) {
  const file = {
    douyin: "platform_douyin.png",
    bilibili: "platform_bilibili.png",
    kuaishou: "platform_kuaishou.png",
    missav: "platform_missav.png",
    xiaohongshu: "platform_xiaohongshu.png",
  }[String(platformId || "").toLowerCase()];
  return file ? `${iconManifest.route || "/ui-icon"}/${file}` : "";
}

function queueStatusHtml(status) {
  const label = status || "待下载";
  const kind = label.includes("解析") || label.includes("存在") ? "success"
    : label.includes("排队") ? "warning"
    : "pending";
  return `<span class="status-pill ${kind}"><i></i>${esc(label)}</span>`;
}

function restoreQueueControls() {
  document.body.classList.toggle("queue-compact", queueDensity === "compact");
  byId("queueComfortableBtn").classList.toggle("active", queueDensity !== "compact");
  byId("queueCompactBtn").classList.toggle("active", queueDensity === "compact");
}

function setQueuePage(delta) {
  queuePage += Number(delta) || 0;
  renderQueue();
}

function setQueuePageSize(value) {
  queuePageSize = Math.max(20, Number(value) || 20);
  queuePage = 1;
  localStorage.setItem("webui_queue_page_size", String(queuePageSize));
  renderQueue();
}

function setQueueDensity(mode) {
  queueDensity = mode === "compact" ? "compact" : "comfortable";
  localStorage.setItem("webui_queue_density", queueDensity);
  document.body.classList.toggle("queue-compact", queueDensity === "compact");
  byId("queueComfortableBtn").classList.toggle("active", queueDensity !== "compact");
  byId("queueCompactBtn").classList.toggle("active", queueDensity === "compact");
  renderQueue();
}

function renderActive() {
  syncActiveDownloadOptions();
  const items = frontendState.active_downloads || [];
  if (!selected.active && items.length) selected.active = items[0].id;
  patchTableRows("activeBody", items, item => item.id, item => `
    <tr data-id="${escAttr(item.id)}" class="${selected.active === item.id ? "selected" : ""}" onclick="selectActive('${escAttr(item.id)}')">
      <td title="${escAttr(item.title)}">${esc(item.title)}</td>
      <td>${platformHtml(item.platform, item.platform_id)}</td>
      <td>${progressHtml(item.progress)}</td>
      <td>${esc(item.speed || "0 B/s")}</td>
      <td>${esc(item.remaining_time || item.eta || "--")}</td>
      <td>${actionButton("delete", "\u5220\u9664", `event.stopPropagation();frontendAction('delete_item',{id:'${escAttr(item.id)}'})`, true)}</td>
    </tr>
  `);
  byId("activeSummary").textContent = `\u5f53\u524d\u8fd0\u884c\uff1a${items.length} \u4e2a\u4efb\u52a1`;
  renderActiveDetail();
}

function currentDownloadOptions() {
  const settings = (frontendState.settings_snapshot || {})["\u4e0b\u8f7d\u8bbe\u7f6e"] || {};
  return {
    auto_retry: true,
    max_retries: Number(settings.max_retries || 3),
    max_concurrent: Number(settings.max_concurrent || 3),
    ...(frontendState.download_options || {}),
  };
}

function ensureSelectOption(select, value, label = String(value)) {
  if (!select) return;
  const target = String(value);
  if (!Array.from(select.options).some(option => option.value === target)) {
    const option = document.createElement("option");
    option.value = target;
    option.textContent = label;
    select.appendChild(option);
    Array.from(select.options)
      .sort((a, b) => Number(a.value) - Number(b.value))
      .forEach(optionNode => select.appendChild(optionNode));
  }
}

function syncActiveDownloadOptions() {
  const options = currentDownloadOptions();
  const autoRetry = byId("activeAutoRetry");
  const retries = byId("activeMaxRetries");
  const concurrent = byId("activeMaxConcurrent");
  if (autoRetry) autoRetry.checked = Boolean(options.auto_retry);
  if (retries) {
    ensureSelectOption(retries, options.max_retries, `${options.max_retries}\u6b21`);
    retries.value = String(options.max_retries);
  }
  if (concurrent) {
    ensureSelectOption(concurrent, options.max_concurrent);
    concurrent.value = String(options.max_concurrent);
  }
}

function updateDownloadOptions() {
  const autoRetry = Boolean(byId("activeAutoRetry") && byId("activeAutoRetry").checked);
  const maxRetries = Number(byId("activeMaxRetries") && byId("activeMaxRetries").value) || 3;
  const maxConcurrent = Number(byId("activeMaxConcurrent") && byId("activeMaxConcurrent").value) || 3;
  frontendAction("update_download_options", {
    auto_retry: autoRetry,
    max_retries: maxRetries,
    max_concurrent: maxConcurrent,
  });
}

function selectActive(id) {
  selected.active = id;
  renderActive();
}

function renderActiveDetail() {
  const item = (frontendState.active_downloads || []).find(row => row.id === selected.active) || (frontendState.active_downloads || [])[0];
  if (!item) {
    const emptyHtml = `<div class="active-detail-card"><h2>${esc(t("\u5f53\u524d\u4e0b\u8f7d"))}</h2><div class="active-detail-fields"><p>${esc(t("\u6682\u65e0\u6b63\u5728\u4e0b\u8f7d\u7684\u4efb\u52a1"))}</p></div></div>`;
    setHtmlIfChanged("activeDetail", emptyHtml);
    return;
  }
  const chunk = item.chunk_progress || {};
  const chunkPercent = Number(chunk.percent ?? item.progress ?? 0);
  const chunkText = `${chunkPercent}% (${chunk.completed || 0}/${chunk.total || 0})`;
  const html = `
    <div class="active-detail-card">
      <h2>${esc(t("\u5f53\u524d\u4e0b\u8f7d"))}</h2>
      <div class="active-detail-fields">
        ${kvHtml([
          ["\u6807\u9898", item.title], ["\u5e73\u53f0", item.platform], ["\u4fdd\u5b58\u76ee\u5f55", item.save_dir || ""], ["\u8f93\u51fa\u6587\u4ef6\u540d", item.output_filename || ""],
          ["\u6765\u6e90\u94fe\u63a5", item.source_url], ["Trace ID", item.trace_id]
        ], new Set(["\u4fdd\u5b58\u76ee\u5f55", "\u8f93\u51fa\u6587\u4ef6\u540d", "\u6765\u6e90\u94fe\u63a5"]))}
      </div>
      <div class="active-detail-metrics">
        <div class="active-chunk">
          <div><strong>${esc(t("\u5206\u7247\u8fdb\u5ea6"))}</strong><span>${esc(chunkText)}</span></div>
          ${progressHtml(chunkPercent)}
        </div>
        <h2>${esc(t("\u901f\u5ea6\u8d8b\u52bf\uff08\u8fd160\u79d2\uff09"))}</h2>
        ${activeTrendHtml(item.speed_trend || [], item.speed || "0 B/s")}
      </div>
    </div>
    <div class="active-events-card">
      <h2>${esc(t("\u5f53\u524d\u4efb\u52a1\u4e8b\u4ef6"))}</h2>
      ${activeEventTimelineHtml(item.events || [])}
    </div>
  `;
  setHtmlIfChanged("activeDetail", html);
}

function activeEventTimelineHtml(events) {
  const rows = (events || []).slice(-6).map(event => `
    <div class="timeline-row"><i></i><time>${esc(event.time || "")}</time><span>${esc(event.message || "")}</span></div>
  `).join("");
  return `<div class="active-timeline">${rows || `<span class="muted">\u6682\u65e0\u4e8b\u4ef6</span>`}</div>`;
}

function activeTrendHtml(values, speedLabel = "0 B/s") {
  const raw = (values || []).map(value => Number(value) || 0).slice(-60);
  const normalized = Math.max(...raw, 0) > 1024 ? raw.map(value => value / 1048576) : raw;
  const max = Math.max(...normalized, 6);
  const width = 260;
  const height = 128;
  const left = 12;
  const right = width - 12;
  const top = 22;
  const bottom = height - 30;
  const usableWidth = width - 24;
  const usableHeight = bottom - top;
  const grid1 = bottom - usableHeight / 3;
  const grid2 = bottom - usableHeight * 2 / 3;
  const grid3 = top;
  const points = normalized.map((value, index) => {
    const x = left + (normalized.length <= 1 ? usableWidth : usableWidth * index / (normalized.length - 1));
    const y = bottom - usableHeight * value / max;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `
    <svg class="speed-trend" viewBox="0 0 ${width} ${height}" role="img" aria-label="\u901f\u5ea6\u8d8b\u52bf">
      <path d="M12 ${bottom}H248M12 ${top}V${bottom}" class="axis" />
      <path d="M12 ${grid1.toFixed(1)}H248M12 ${grid2.toFixed(1)}H248M12 ${grid3.toFixed(1)}H248" class="grid" />
      <polyline points="${points}" class="line" />
      <text x="12" y="120">60\u79d2</text><text x="76" y="120">45\u79d2</text><text x="136" y="120">30\u79d2</text><text x="196" y="120">15\u79d2</text><text x="224" y="120">\u73b0\u5728</text>
      <text class="speed-label" x="${right}" y="17" text-anchor="end">${esc(speedLabel || "0 B/s")}</text>
    </svg>
  `;
}

function renderCompleted() {
  const allItems = frontendState.completed_items || [];
  cleanupWebPlaybackPositions(allItems);
  const totalPages = Math.max(1, Math.ceil(allItems.length / completedPageSize));
  completedPage = Math.max(1, Math.min(completedPage, totalPages));
  if (selected.completed) {
    const selectedIndex = allItems.findIndex(item => item.id === selected.completed);
    if (selectedIndex >= 0) completedPage = Math.floor(selectedIndex / completedPageSize) + 1;
  }
  const start = (completedPage - 1) * completedPageSize;
  const items = allItems.slice(start, start + completedPageSize);
  if (!selected.completed && items.length) selected.completed = items[0].id;
  patchTableRows("completedBody", items, item => item.id, item => `
    <tr data-id="${escAttr(item.id)}" class="${selected.completed === item.id ? "selected" : ""}" onclick="selectCompleted('${escAttr(item.id)}')">
      <td title="${escAttr(item.title)}">${esc(item.title)}</td>
      <td>${esc(item.completed_at_table || item.completed_at || "")}</td>
      <td>${esc(displayMetadataValue(item.duration, item.metadata_pending))}</td>
      <td>${esc(item.format)}</td>
      <td>${actionButton("play", "播放", `event.stopPropagation();playCompleted('${escAttr(item.id)}')`)}${actionButton("open_directory", "打开目录", `event.stopPropagation();openDirectory('${escAttr(item.id)}')`)}${actionButton("delete", "删除", `event.stopPropagation();frontendAction('delete_item',{id:'${escAttr(item.id)}'})`, true)}</td>
    </tr>
  `);
  byId("completedTotal").textContent = `共 ${allItems.length} 项`;
  byId("completedPageNow").textContent = String(completedPage);
  byId("completedTotalPages").textContent = String(totalPages);
  byId("completedPageSize").value = String(completedPageSize);
  renderCompletedDetail();
}

function selectCompleted(id) {
  selected.completed = id;
  selectedVideoId = id;
  renderCompleted();
}

function setCompletedPage(delta) {
  completedPage += Number(delta) || 0;
  selected.completed = "";
  renderCompleted();
}

function setCompletedPageSize(value) {
  completedPageSize = Math.max(20, Number(value) || 20);
  completedPage = 1;
  selected.completed = "";
  localStorage.setItem("webui_completed_page_size", String(completedPageSize));
  renderCompleted();
}

function renderCompletedDetail() {
  const item = (frontendState.completed_items || []).find(row => row.id === selected.completed) || (frontendState.completed_items || [])[0];
  if (!item) {
    byId("completedDetail").innerHTML = "<h2>文件信息</h2><p>暂无已完成文件</p>";
    return;
  }
  const filename = item.filename || basenameFromPath(item.local_path) || item.title || "";
  const saveDir = item.save_dir || dirnameFromPath(item.local_path) || "";
  const html = `
    <h2>文件信息</h2>
    ${kvHtml([["文件名", filename], ["保存路径", saveDir], ["完成时间", item.completed_at], ["时长", displayMetadataValue(item.duration, item.metadata_pending)], ["分辨率", displayMetadataValue(item.resolution, item.metadata_pending)], ["大小", item.size], ["格式", item.format]])}
  `;
  setHtmlIfChanged("completedDetail", html);
}

function displayMetadataValue(value, pending = false) {
  const text = String(value || "").trim();
  if (text && text !== "--") return text;
  return pending ? "检测中" : "--";
}

function basenameFromPath(path) {
  const parts = String(path || "").split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

function dirnameFromPath(path) {
  const text = String(path || "");
  const slash = Math.max(text.lastIndexOf("\\"), text.lastIndexOf("/"));
  return slash > 0 ? text.slice(0, slash) : "";
}

function renderFailed() {
  const items = frontendState.failed_items || [];
  if (!selected.failed && items.length) selected.failed = items[0].id;
  patchTableRows("failedBody", items, item => item.id, item => `
    <tr data-id="${escAttr(item.id)}" class="${selected.failed === item.id ? "selected" : ""}" onclick="selectFailed('${escAttr(item.id)}')">
      <td title="${escAttr(item.title)}">${esc(item.title)}</td>
      <td>${esc(item.failed_at_table || item.failed_at)}</td>
      <td>${iconTextHtml(item.reason_label || item.reason || "", item.reason_icon_file || "status_error_warning.png")}</td>
      <td>${failedStatusHtml(item.status_label || item.status || "失败")}</td>
      <td>${actionButton("copy_diagnostics", "复制 Trace ID", `event.stopPropagation();copyDiagnostics('${escAttr(item.id)}')`)}${actionButton("delete", "删除", `event.stopPropagation();frontendAction('delete_item',{id:'${escAttr(item.id)}'})`, true)}</td>
    </tr>
  `);
  renderFailedDetail();
}

function selectFailed(id) {
  selected.failed = id;
  renderFailed();
}

function renderFailedDetail() {
  const item = (frontendState.failed_items || []).find(row => row.id === selected.failed) || (frontendState.failed_items || [])[0];
  if (!item) {
    byId("failedDetail").innerHTML = "<h2>错误详情</h2><p>暂无失败任务</p>";
    byId("failedSolutions").innerHTML = "<h2>可能的解决方案</h2><p>暂无建议</p>";
    return;
  }
  const platformIcon = iconManifest.platforms?.[String(item.platform_id || "").toLowerCase()] || "platform_web.png";
  const logItems = item.log_excerpt_items || (item.log_excerpt || []).map(message => ({ level: "INFO", time: "", message, icon_file: "log_level_info.png" }));
  byId("failedDetail").innerHTML = `
    <h2>错误详情</h2>
    <div class="failed-summary">
      ${detailRowHtml("标题", item.title)}
      ${detailRowHtml("失败时间", item.failed_at)}
      ${detailRowHtml("失败原因", item.reason_detail || item.reason, item.reason_icon_file || "status_error_warning.png")}
      ${detailRowHtml("平台", item.platform, platformIcon)}
      ${detailRowHtml("Trace ID", item.trace_id)}
    </div>
    <h2>Trace / 日志片段</h2>
    <div class="failed-log-list">${logItems.length ? logItems.map(failedLogRowHtml).join("") : `<div class="empty-note">暂无日志片段</div>`}</div>
  `;
  byId("failedSolutions").innerHTML = `
    <h2>可能的解决方案</h2>
    <div class="failed-solution-list">${(item.solutions || []).length ? (item.solutions || []).map(solutionRowHtml).join("") : `<div class="empty-note">暂无建议</div>`}</div>
  `;
}

function iconFileUrl(file) {
  return `${escAttr(iconManifest.route || "/ui-icon")}/${escAttr(file || iconManifest.fallback || "view_grid.png")}`;
}

function iconTextHtml(text, iconFile) {
  return `<span class="icon-text"><img src="${iconFileUrl(iconFile)}" alt="" />${esc(text || "")}</span>`;
}

function failedStatusHtml(text) {
  return `<span class="failed-status-chip"><i aria-hidden="true">×</i>${esc(text || "失败")}</span>`;
}

function detailRowHtml(label, value, iconFile = "") {
  const icon = iconFile ? `<img src="${iconFileUrl(iconFile)}" alt="" />` : "";
  return `<div class="failed-detail-row"><span>${esc(label)}</span><strong>${icon}${esc(value || "")}</strong></div>`;
}

function failedLogLevel(entry) {
  const raw = String(entry.level || entry.raw_level || "").trim().toUpperCase();
  let level = raw;
  if (!level) {
    const icon = String(entry.icon_file || "").toLowerCase();
    if (icon.includes("error")) level = "ERROR";
    else if (icon.includes("warn")) level = "WARN";
    else if (icon.includes("success") || icon.includes("ok")) level = "SUCCESS";
    else if (icon.includes("cmd") || icon.includes("command")) level = "CMD";
    else level = "INFO";
  }
  if (level === "WARNING") return "WARN";
  if (level === "OK") return "SUCCESS";
  if (level === "COMMAND") return "CMD";
  if (["INFO", "SUCCESS", "WARN", "ERROR", "CMD"].includes(level)) return level;
  return level.slice(0, 8) || "INFO";
}

function failedLogLevelClass(level) {
  const normalized = String(level || "INFO").toLowerCase();
  return ["info", "success", "warn", "error", "cmd"].includes(normalized) ? normalized : "info";
}

function failedLogRowHtml(entry) {
  const level = failedLogLevel(entry);
  return `
    <div class="failed-log-row">
      <span class="log-time">${esc(failedLogTime(entry.time))}</span>
      <span class="log-level log-level-${failedLogLevelClass(level)}">${esc(level)}</span>
      <span class="log-message">${esc(entry.message || "")}</span>
    </div>
  `;
}

function failedLogTime(value) {
  const text = String(value || "").trim();
  if (!text) return "--:--:--";
  let candidate = text.split(/\s+/).pop() || text;
  candidate = candidate.split(".")[0];
  if (/^\d{1,2}:\d{2}:\d{2}$/.test(candidate)) return candidate.padStart(8, "0");
  const match = text.match(/(\d{1,2}:\d{2}:\d{2})(?:\.\d+)?/);
  if (match) return match[1].padStart(8, "0");
  return text.slice(-8).padStart(8, "-");
}

function solutionRowHtml(solution) {
  return `
    <div class="failed-solution-row">
      <img src="${iconFileUrl(solution.icon_file || "action_help.png")}" alt="" />
      <span><strong>${esc(solution.title || "建议")}</strong><small>${esc(solution.description || "")}</small></span>
    </div>
  `;
}

function renderLogs() {
  syncLogFilterControls();
  const items = filteredLogItems();
  if (!items.some(item => logItemId(item) === selected.log)) selected.log = items.length ? logItemId(items[0]) : "";
  patchTableRows("logBody", items, item => logItemId(item), item => `
    <tr class="${selected.log === logItemId(item) ? "selected" : ""}" onclick="selectLog('${escAttr(logItemId(item))}')">
      <td>${esc(item.time)}</td>
      <td>${esc(item.level)}</td>
      <td>${esc(item.source)}</td>
      <td>${esc(item.trace_id || "")}</td>
      <td title="${escAttr(item.message_summary || "")}">${esc(item.message_summary || "")}</td>
    </tr>
  `);
  renderLogDetail();
}

function logItemId(item) {
  return String(item.id || `${item.time || ""}|${item.trace_id || ""}|${item.source || ""}|${item.message_summary || ""}`);
}

function selectLog(id) {
  selected.log = String(id);
  renderLogs();
}

function renderLogDetail() {
  const items = filteredLogItems();
  const item = items.find(row => logItemId(row) === selected.log) || items[0];
  if (!item) {
    byId("logDetail").innerHTML = `<div class="log-detail-card"><h2>日志详情</h2><p>暂无日志</p></div>`;
    return;
  }
  const detail = String(item.detail || "").trim();
  const stack = String(item.stack || "").trim();
  const extraBlocks = [];
  if (detail) extraBlocks.push(`<div class="log-extra-card"><h2>详细信息</h2><pre class="log-snippet">${esc(detail)}</pre></div>`);
  if (stack && stack !== "无") extraBlocks.push(`<div class="log-extra-card"><h2>堆栈跟踪</h2><pre class="log-snippet">${esc(stack)}</pre></div>`);
  byId("logDetail").innerHTML = `
    <div class="log-detail-card">
      <h2>日志详情</h2>
      ${kvHtml([["时间", item.time], ["级别", item.level], ["来源", item.source], ["平台", item.platform || ""], ["线程", item.thread || ""], ["Trace ID", item.trace_id || ""], ["消息", item.message || item.message_summary]])}
    </div>
    ${extraBlocks.join("")}
  `;
}

function setLogTab(category) {
  logFilters.category = category || "all";
  selected.log = "";
  renderLogs();
}

function syncLogFiltersFromDom() {
  logFilters.level = byId("logLevelFilter")?.value || "全部";
  logFilters.time = byId("logTimeFilter")?.value || "近 24 小时";
  logFilters.platform = byId("logPlatformFilter")?.value || "全部";
  logFilters.trace = byId("logTraceFilter")?.value.trim() || "";
  logFilters.keyword = byId("logKeywordFilter")?.value.trim() || "";
  selected.log = "";
  renderLogs();
}

function syncLogFilterControls() {
  document.querySelectorAll("#logTabs [data-log-tab]").forEach(button => button.classList.toggle("active", button.dataset.logTab === logFilters.category));
  const bindings = [
    ["logLevelFilter", logFilters.level],
    ["logTimeFilter", logFilters.time],
    ["logPlatformFilter", logFilters.platform],
    ["logTraceFilter", logFilters.trace],
    ["logKeywordFilter", logFilters.keyword],
  ];
  for (const [id, value] of bindings) {
    const node = byId(id);
    if (node && node.value !== value) node.value = value;
  }
}

function filteredLogItems() {
  trimFrontendLogItems();
  return (frontendState.log_items || []).filter(logMatchesFilters);
}

function logMatchesFilters(item) {
  const category = logCategory(item);
  if (logFilters.category === "error") {
    if (String(item.level || "").toUpperCase() !== "ERROR" && category !== "error") return false;
  } else if (logFilters.category !== "all" && category !== logFilters.category) {
    return false;
  }
  if (logFilters.level !== "全部" && String(item.level || "").toUpperCase() !== logFilters.level) return false;
  if (!logMatchesTime(item)) return false;
  const haystack = logSearchText(item).toLowerCase();
  if (logFilters.platform !== "全部" && !logSearchText(item).includes(logFilters.platform)) return false;
  if (logFilters.trace && !String(item.trace_id || "").toLowerCase().includes(logFilters.trace.toLowerCase())) return false;
  if (logFilters.keyword && !haystack.includes(logFilters.keyword.toLowerCase())) return false;
  return true;
}

function logCategory(item) {
  const level = String(item.level || "").toUpperCase();
  if (level === "ERROR") return "error";
  if (item.category) return String(item.category);
  const text = logSearchText(item).toLowerCase();
  if (/(download|下载|bilibili|douyin|kuaishou|missav|小红书|抖音|快手)/.test(text)) return "download";
  return "system";
}

function logSearchText(item) {
  return [item.platform, item.source, item.trace_id, item.level, item.message_summary, item.message, item.detail, item.stack].map(value => String(value || "")).join(" ");
}

function logMatchesTime(item) {
  const minutes = {"近 30 分钟": 30, "近 1 小时": 60, "近 24 小时": 24 * 60}[logFilters.time];
  if (!minutes) return true;
  const timestamp = Number(item.timestamp_ms || Date.parse(String(item.time || "").replace(" ", "T")));
  if (!timestamp) return false;
  return timestamp >= Date.now() - minutes * 60 * 1000;
}

function runLogOperation(operation) {
  frontendAction("log_operation", { operation });
  if (operation === "refresh" || operation === "clear") {
    setTimeout(fetchFrontendDelta, 200);
  }
}

function renderSettings(force = false) {
  const settings = frontendState.settings_snapshot || {};
  const contract = settingsContract();
  const fallbackOrder = contract.order.length ? contract.order : SETTINGS_GROUP_ORDER_FALLBACK;
  const orderedGroups = fallbackOrder.filter(group => Object.prototype.hasOwnProperty.call(settings, group));
  for (const group of Object.keys(settings)) {
    if (!orderedGroups.includes(group)) orderedGroups.push(group);
  }
  if (!orderedGroups.includes(currentSettingsGroup)) currentSettingsGroup = orderedGroups[0] || "基础设置";
  const currentValue = settings[currentSettingsGroup] || {};
  const description =
    contract.descriptions?.[currentSettingsGroup]
    || SETTINGS_GROUP_DESCRIPTIONS_FALLBACK[currentSettingsGroup]
    || "";
  const title = document.querySelector("#page-settings .page-head h1");
  if (title) title.textContent = t("配置中心");
  const navHtml = orderedGroups.map(group => `
    <button class="settings-nav-btn ${group === currentSettingsGroup ? "active" : ""}" type="button" data-group="${escAttr(group)}" onclick="switchSettingsGroup('${escAttr(group)}')">${esc(t(group))}</button>
  `).join("");
  const html = `
    <div class="settings-shell">
      <aside class="settings-side-nav">
        <div class="settings-nav-title">${esc(t("设置分类"))}</div>
        ${navHtml}
      </aside>
      <section class="settings-detail-panel">
        <header class="settings-detail-head">
          <h2>${esc(t(currentSettingsGroup))}</h2>
          <p>${esc(t(description))}</p>
        </header>
        <div class="settings-detail-body ${currentSettingsGroup === "\u5e73\u53f0\u8bbe\u7f6e" ? "settings-platform-body" : ""}">
          ${settingsControls(currentSettingsGroup, currentValue)}
        </div>
      </section>
    </div>
  `;
  if (!force && renderSignatures.settingsGrid && renderSignatures.settingsGrid !== html && hasFocusedDescendant("settingsGrid")) return;
  setHtmlIfChanged("settingsGrid", html);
}

function switchSettingsGroup(group) {
  if (!group || group === currentSettingsGroup) return;
  currentSettingsGroup = group;
  localStorage.setItem("webui_settings_group", group);
  renderSettings(true);
}

function settingsControls(group, value) {
  const options = value && value._options ? value._options : {};
  if (value && Object.prototype.hasOwnProperty.call(value, "download_directory")) {
    return [
      settingInput("\u4e0b\u8f7d\u76ee\u5f55", "download_directory", value && value.download_directory, "basic"),
      settingSelect("\u6587\u4ef6\u547d\u540d\u89c4\u5219", "filename_template", value && value.filename_template, options.filename_template || [], "basic"),
      settingSelect("\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f", "default_open_mode", value && value.default_open_mode, options.default_open_mode || [], "basic"),
      settingCheckbox("\u4e0b\u8f7d\u540e\u81ea\u52a8\u6253\u5f00", "open_after_download", !!(value && value.open_after_download), "basic"),
      `<button class="btn setting-action" type="button" onclick="frontendAction('register_file_associations',{include_video:true,include_image:true})">${esc(t("\u7ed1\u5b9a\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f"))}</button>`,
    ].join("");
  }
  if (group === "\u4e0b\u8f7d\u8bbe\u7f6e") {
    return [
      settingSelect("\u5e76\u53d1\u6570", "max_concurrent", value && value.max_concurrent, options.max_concurrent || [], "download"),
      settingCheckbox("\u56fe\u7247\u53d7\u5e76\u53d1\u6570\u9650\u5236", "image_respects_concurrency", !!(value && value.image_respects_concurrency), "download"),
      settingSelect("\u8bf7\u6c42\u8d85\u65f6", "request_timeout", value && value.request_timeout, options.request_timeout || [], "download"),
      settingSelect("\u6700\u5927\u91cd\u8bd5", "max_retries", value && value.max_retries, options.max_retries || [], "download"),
      settingSelect("\u901f\u5ea6\u9650\u5236 KB/s", "speed_limit_kb", value && value.speed_limit_kb, options.speed_limit_kb || [{ value: "0", label: "\u65e0\u9650\u5236" }], "download"),
      settingCheckbox("\u65ad\u70b9\u7eed\u4f20", "resume_enabled", !!(value && value.resume_enabled), "download"),
      settingCheckbox("\u4ec5\u4e0b\u8f7d\u89c6\u9891", "video_only", !!(value && value.video_only), "download"),
    ].join("");
  }
  if (group === "\u5e73\u53f0\u8bbe\u7f6e") {
    const rows = Array.isArray(value) ? value : [];
    return `${platformSettingsSummary(rows)}${platformSettingsHeader()}${rows.map(platformSettingRow).join("")}`;
  }
  if (group === "\u64ad\u653e\u8bbe\u7f6e") {
    return [
      settingSelect("\u6253\u5f00\u65b9\u5f0f", "default_player", value && value.default_player, options.default_player || [], "playback"),
      settingCheckbox("\u8bb0\u4f4f\u64ad\u653e\u4f4d\u7f6e", "remember_position", !!(value && value.remember_position), "playback"),
      settingCheckbox("\u81ea\u52a8\u64ad\u653e\u4e0b\u4e00\u9879", "autoplay_next", !!(value && value.autoplay_next), "playback"),
      settingCheckbox("\u624b\u52a8\u5207\u6362\u56fe\u7247", "manual_image_switch", !!(value && value.manual_image_switch), "playback"),
    ].join("");
  }
  if (group === "\u65e5\u5fd7\u8bbe\u7f6e") {
    return [
      settingSelect("\u4fdd\u7559\u5929\u6570", "retention_days", value && value.retention_days, options.retention_days || [], "logging"),
      settingSelect("UI\u6700\u5927\u663e\u793a\u6570", "ui_log_max_display_count", value && value.ui_log_max_display_count, options.ui_log_max_display_count || [], "logging"),
      settingCheckbox("\u9519\u8bef\u65f6\u81ea\u52a8\u590d\u5236 Trace", "auto_copy_trace_on_error", !!(value && value.auto_copy_trace_on_error), "logging"),
    ].join("");
  }
  if (group === "\u5916\u89c2\u8bbe\u7f6e") {
    return [
      settingSelect("语言", "language", value && value.language, options.language || [], "appearance"),
      settingCheckbox("\u8ddf\u968f\u7cfb\u7edf", "follow_system", !!(value && value.follow_system), "appearance"),
      settingSelect("\u4e3b\u9898", "theme", value && value.theme, options.theme || [], "common"),
      settingSelect("\u4e3b\u9898\u8272", "accent", value && value.accent, options.accent || [], "appearance"),
      settingSelect("\u754c\u9762\u7f29\u653e", "scale", value && value.scale, options.scale || [], "appearance"),
      settingSelect("\u5b57\u4f53\u5927\u5c0f", "font_size", value && value.font_size, options.font_size || [], "appearance"),
    ].join("");
  }
  return "";
}

function platformSettingsSummary(rows) {
  const total = rows.length;
  const authed = rows.filter(row => row.auth_status === "\u5df2\u8ba4\u8bc1").length;
  const unauthed = Math.max(0, total - authed);
  const proxyReady = rows.filter(row => row.proxy_editable && row.proxy_config_key).length;
  const chips = [
    ["\u5e73\u53f0\u603b\u6570", total],
    ["\u5df2\u8ba4\u8bc1", authed],
    ["\u672a\u8ba4\u8bc1", unauthed],
    ["\u53ef\u914d\u7f6e\u4ee3\u7406", proxyReady],
  ];
  return `
    <div class="platform-summary">
      ${chips.map(([label, value]) => `<span class="platform-chip"><b>${esc(t(label))}</b><strong>${esc(value)}</strong></span>`).join("")}
    </div>
  `;
}

function platformSettingsHeader() {
  return `
    <div class="setting-platform setting-platform-header" aria-hidden="true">
      <span class="platform-name">${esc(t("\u5e73\u53f0"))}</span>
      <span>${esc(t("\u8ba4\u8bc1\u72b6\u6001"))}</span>
      <span>${esc(t("\u722c\u53d6\u6570\u91cf"))}</span>
      <span>${esc(t("\u8d85\u65f6"))}</span>
      <span>${esc(t("\u4ee3\u7406\u5165\u53e3"))}</span>
    </div>
  `;
}

function platformSettingRow(row) {
  const countKey = row.count_config_key || "";
  const timeoutKey = row.timeout_config_key || "";
  const proxyKey = row.proxy_config_key || "";
  const countDisabled = row.count_editable && countKey ? "" : " disabled";
  const timeoutDisabled = row.timeout_editable && timeoutKey ? "" : " disabled";
  const proxyDisabled = row.proxy_editable && proxyKey ? "" : " disabled";
  let countOptions = (row.count_options || []).map(normalizeSettingOption).filter(option => option.value);
  const countValue = String(row.default_count || 20);
  if (!countOptions.some(option => option.value === countValue)) {
    const countUnit = ["pages", "notes"].includes(row.count_unit) ? row.count_unit : "videos";
    countOptions.unshift({ value: countValue, label: countOptionLabel(countValue, countUnit) });
  }
  let timeoutOptions = (row.timeout_options || []).map(normalizeSettingOption).filter(option => option.value);
  const timeoutValue = String(row.default_timeout || row.timeout || 60);
  if (timeoutKey && !timeoutOptions.some(option => option.value === timeoutValue)) {
    timeoutOptions.unshift({ value: timeoutValue, label: `${timeoutValue} \u79d2` });
  }
  let proxyOptions = (row.proxy_options || ["\u7cfb\u7edf\u4ee3\u7406", "\u76f4\u8fde", "Clash (7890)", "v2rayN (10809)", "\u81ea\u5b9a\u4e49"]).map(normalizeSettingOption).filter(option => option.value);
  let proxyValue = String(row.proxy || "\u7cfb\u7edf\u4ee3\u7406");
  let proxyCustomValue = String(row.proxy_custom_value || "");
  if (proxyValue && !proxyOptions.some(option => option.value === proxyValue)) {
    proxyCustomValue = proxyCustomValue || proxyValue;
    proxyValue = "\u81ea\u5b9a\u4e49";
  }
  const proxyCustom = !!(row.proxy_custom_active || isCustomProxyValue(proxyValue));
  const hasCustomProxy = !!(row.proxy_custom_allowed && row.proxy_editable && proxyKey);
  const customProxy = hasCustomProxy
    ? `<input class="proxy-custom${proxyCustom ? " active" : ""}" data-platform="${escAttr(row.id || "")}" data-setting="proxy_url" value="${escAttr(proxyCustomDisplayValue(proxyCustomValue))}" placeholder="${escAttr(t("\u7aef\u53e3"))}" ${proxyCustom ? "" : "hidden disabled"} onblur="commitProxyCustom('${escAttr(row.id || "")}', 'proxy_url', this)" />`
    : "";
  return `
    <div class="setting-row setting-platform${hasCustomProxy && proxyCustom ? " has-proxy-custom" : ""}">
      <span class="platform-name">${esc(row.name || row.id || "\u5e73\u53f0")}</span>
      <select class="platform-auth" disabled title="${escAttr(row.auth_detail || "")}"><option ${row.auth_status === "\u5df2\u8ba4\u8bc1" ? "selected" : ""}>${esc(t("\u5df2\u8ba4\u8bc1"))}</option><option ${row.auth_status !== "\u5df2\u8ba4\u8bc1" ? "selected" : ""}>${esc(t("\u672a\u8ba4\u8bc1"))}</option></select>
      <select class="platform-count" data-setting="${escAttr(countKey)}"${countDisabled} onchange="updateSetting('${escAttr(row.id || "")}', '${escAttr(countKey)}', this.value)">${countOptions.map(option => `<option value="${escAttr(option.value)}" ${countValue === option.value ? "selected" : ""}>${esc(optionLabel(option.label))}</option>`).join("")}</select>
      <select class="platform-timeout" data-setting="${escAttr(timeoutKey)}"${timeoutDisabled} onchange="updateSetting('${escAttr(row.id || "")}', '${escAttr(timeoutKey)}', this.value)">${timeoutOptions.map(option => `<option value="${escAttr(option.value)}" ${timeoutValue === option.value ? "selected" : ""}>${esc(optionLabel(option.label))}</option>`).join("")}</select>
      <select class="platform-proxy" data-setting="${escAttr(proxyKey)}"${proxyDisabled} onchange="handleProxySelect('${escAttr(row.id || "")}', '${escAttr(proxyKey)}', this)">${proxyOptions.map(option => `<option value="${escAttr(option.value)}" ${proxyValue === option.value ? "selected" : ""}>${esc(optionLabel(option.label))}</option>`).join("")}</select>
      ${customProxy}
    </div>
  `;
}

function isCustomProxyValue(value) {
  const text = String(value || "").trim();
  return text === "\u81ea\u5b9a\u4e49" || text.includes("://") || text.includes(":");
}

function proxyCustomDisplayValue(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const withoutScheme = text.includes("://") ? text.split("://", 2)[1] : text;
  const withoutAuth = withoutScheme.includes("@") ? withoutScheme.split("@").pop() : withoutScheme;
  const hostPart = withoutAuth.split("/", 1)[0];
  const port = hostPart.match(/:(\d{1,5})$/);
  return port ? port[1] : text;
}

function handleProxySelect(platformId, key, select) {
  const value = String(select.value || "").trim();
  const row = select.closest(".setting-platform");
  const input = row ? row.querySelector(".proxy-custom") : null;
  if (input) {
    const custom = isCustomProxyValue(value);
    row.classList.toggle("has-proxy-custom", custom);
    input.hidden = !custom;
    input.disabled = !custom;
    input.classList.toggle("active", custom);
    if (custom) {
      if (value !== "\u81ea\u5b9a\u4e49") input.value = proxyCustomDisplayValue(value);
      updateSetting(platformId, key, "\u81ea\u5b9a\u4e49");
      input.focus();
      return;
    }
  }
  updateSetting(platformId, key, value);
}

function commitProxyCustom(platformId, key, input) {
  const value = String(input.value || "").trim();
  if (!value) return;
  updateSetting(platformId, key, value);
}

function updateBasicSetting(key, value) {
  frontendAction("update_basic_setting", { key, value });
}

function updateSetting(section, key, value) {
  if (!section || !key) return;
  if (section === "basic") {
    updateBasicSetting(key, value);
    return;
  }
  if (section === "common" && key === "theme") {
    const dark = String(value).toLowerCase() === "dark";
    const appearance = ((frontendState.settings_snapshot || {})["\u5916\u89c2\u8bbe\u7f6e"] ||= {});
    appearance.theme = dark ? "dark" : "light";
    localStorage.setItem("cached_dark_theme", String(dark));
    applyAppearance(appearance);
    if (currentPage === "settings" && currentSettingsGroup === "外观设置") renderSettings(true);
  }
  if (section === "appearance" && ["scale", "font_size", "accent", "language"].includes(key)) {
    const appearance = ((frontendState.settings_snapshot || {})["\u5916\u89c2\u8bbe\u7f6e"] ||= {});
    appearance[key] = value;
    applyAppearance(appearance);
    if (key === "language") {
      renderSignatures = {};
      renderAll();
    }
    else if (key === "font_size" || key === "scale") renderCurrentPage();
  }
  frontendAction("update_setting", { section, key, value });
}

function settingInput(label, key, value, scope = "") {
  const action = scope === "basic"
    ? ` onblur="updateBasicSetting('${escAttr(key)}', this.value)"`
    : (scope ? ` onblur="updateSetting('${escAttr(scope)}', '${escAttr(key)}', this.value)"` : "");
  return `<label class="setting-row"><span>${esc(t(label))}</span><input data-setting="${escAttr(key)}" value="${escAttr(value || "")}" title="${escAttr(value || "")}"${action} /></label>`;
}

function settingCheckbox(label, key, checked, scope = "") {
  const action = scope === "basic"
    ? ` onchange="updateBasicSetting('${escAttr(key)}', this.checked)"`
    : (scope ? ` onchange="updateSetting('${escAttr(scope)}', '${escAttr(key)}', this.checked)"` : "");
  return `<label class="setting-row"><span>${esc(t(label))}</span><input data-setting="${escAttr(key)}" type="checkbox" ${checked ? "checked" : ""}${action} /></label>`;
}

function normalizeSettingOption(option) {
  if (option && typeof option === "object") {
    const value = String(option.value ?? option.id ?? option.label ?? "");
    const label = String(option.label ?? value);
    return { value, label };
  }
  return { value: String(option ?? ""), label: String(option ?? "") };
}

function settingSelect(label, key, value, options, scope = "", extraAttrs = "") {
  let normalized = (options || []).map(normalizeSettingOption).filter(option => option.value);
  const current = String(value ?? (normalized[0] ? normalized[0].value : ""));
  if (current && !normalized.some(option => option.value === current)) normalized.unshift({ value: current, label: current });
  const action = scope === "basic"
    ? ` onchange="updateBasicSetting('${escAttr(key)}', this.value)"`
    : (scope ? ` onchange="updateSetting('${escAttr(scope)}', '${escAttr(key)}', this.value)"` : "");
  const labelHtml = label ? `<span>${esc(t(label))}</span>` : "";
  return `<label class="setting-row">${labelHtml}<select data-setting="${escAttr(key)}"${action}${extraAttrs}>${normalized.map(option => `<option value="${escAttr(option.value)}" ${current === option.value ? "selected" : ""}>${esc(optionLabel(option.label))}</option>`).join("")}</select></label>`;
}
function renderToolbox() {
  const items = frontendState.toolbox_items || [];
  if (!selected.tool && items.length) selected.tool = items[0].id;
  byId("toolGrid").innerHTML = items.map(item => `
    <button class="tool-card ${selected.tool === item.id ? "active" : ""}" onclick="selectTool('${escAttr(item.id)}')">
      <img src="${escAttr(iconManifest.route || "/ui-icon")}/${escAttr(item.icon_file || "nav_toolbox.png")}" alt="" />
      <h2>${esc(item.title)}</h2>
      <p>${esc(item.summary)}</p>
    </button>
  `).join("");
  renderToolDetail();
}

function selectTool(id) {
  selected.tool = id;
  renderToolbox();
}

function renderToolDetail() {
  const item = (frontendState.toolbox_items || []).find(row => row.id === selected.tool) || {};
  const recent = frontendState.toolbox_recent_items || [];
  byId("toolDetail").innerHTML = `
    <h2>最近使用</h2>
    <div class="recent-list">${recent.length ? recent.map(row => `${esc(row.title || "")}  ${esc(row.last_used || "")}`).join("\n") : "暂无最近使用记录"}</div>
    <h2>工具详情</h2>
    ${kvHtml([["工具", item.title || ""], ["说明", item.summary || ""], ["输入示例", item.input_example || ""], ["输出示例", item.output_example || ""]])}
    <button class="btn btn-primary" onclick="frontendAction('run_tool',{tool_id:'${escAttr(item.id || "")}'})">打开工具</button>
  `;
}

function renderStatus() {
  const status = frontendState.app_status || {};
  byId("statusState").textContent = t(status.running_state || "空闲中");
  byId("statusDownload").textContent = `${t("下载速度")}：${status.download_speed || "0 B/s"}`;
  byId("statusUpload").textContent = `${t("上传速度")}：${status.upload_speed || "0 B/s"}`;
  byId("statusCompleted").textContent = `${t("已完成")}：${status.completed_count || 0}`;
  byId("statusFailed").textContent = `${t("失败")}：${status.failed_count || 0}`;
  byId("statusVersion").textContent = status.version || "v1.0.0";
}

function switchPage(pageId) {
  currentPage = pageId;
  document.querySelectorAll(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === pageId));
  document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === pageId));
  renderCurrentPage();
}

function progressHtml(value) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return `<span class="progress"><i style="width:${pct}%"></i></span>${pct}%`;
}

function actionButton(actionId, label, onclick, danger = false) {
  const icon = iconManifest.actions?.[actionId] || iconManifest.fallback || "view_grid.png";
  const route = iconManifest.route || "/ui-icon";
  const dangerClass = danger ? " danger" : "";
  const clickAttr = onclick ? ` onclick="${onclick}"` : "";
  return `<button class="op icon${dangerClass}" type="button" title="${escAttr(label)}" aria-label="${escAttr(label)}"${clickAttr}><img src="${escAttr(route)}/${escAttr(icon)}" alt="" /></button>`;
}

function updateIconManifest(manifest) {
  if (!manifest || typeof manifest !== "object") return;
  iconManifest = {
    ...iconManifest,
    ...manifest,
    actions: { ...iconManifest.actions, ...(manifest.actions || {}) },
  };
}

function smartWrapText(value) {
  return esc(String(value ?? "")).replace(/([\\/])/g, "$1<wbr>");
}

function kvHtml(pairs, wrapKeys = new Set()) {
  const implicitWrapKeys = new Set(["文件名", "保存路径", "保存目录", "输出文件名", "来源链接"]);
  return `<div class="kv">${pairs.map(([key, value]) => {
    const keyText = String(key);
    const shouldWrap = wrapKeys.has(keyText) || implicitWrapKeys.has(keyText);
    const valueClass = shouldWrap ? "kv-value smart-wrap" : "kv-value";
    const valueHtml = shouldWrap ? smartWrapText(value) : esc(String(value ?? ""));
    return `<span>${esc(t(keyText))}</span><span class="${valueClass}">${valueHtml}</span>`;
  }).join("")}</div>`;
}

function startCrawl() {
  const keyword = byId("searchInput").value.trim();
  if (!keyword) {
    appendLog("请输入主页链接、分享链接或合集链接");
    return;
  }
  const source = byId("sourceSelect").value || "douyin";
  const platformRow = platformSettingsRow(source) || {};
  const countUnit = platformRow.count_unit || "videos";
  const count = Number(byId("videoCountSelect").value) || (countUnit === "pages" ? 1 : 20);
  const countKey = platformRow.count_config_key || "max_items";
  const config = { [countKey]: count };
  if (countKey === "max_pages") config.max_items = 9999;
  const timeoutKey = platformRow.timeout_config_key || "";
  const timeoutValue = Number(platformRow.default_timeout || platformRow.timeout || 0);
  if (timeoutKey && timeoutValue > 0) {
    config[timeoutKey] = timeoutValue;
  }
  sendWS("start_crawl", { source_id: source, source, keyword, config });
  byId("startBtn").disabled = true;
  byId("stopBtn").disabled = false;
}

function stopCrawl() {
  sendWS("stop_crawl", {});
  byId("stopBtn").disabled = true;
}

function sendWS(type, data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, data }));
  }
}

const defaultSendWS = sendWS;

function playbackSettings() {
  return ((frontendState.settings_snapshot || {})["播放设置"] || {});
}

function shouldUseBuiltinPlayer() {
  const settings = playbackSettings();
  return String(settings.default_player || "builtin_player") !== "system_default";
}

function shouldRememberPlaybackPosition() {
  return playbackSettings().remember_position !== false;
}

function shouldAutoplayNext() {
  return playbackSettings().autoplay_next !== false;
}

function shouldManualSwitchImages() {
  return playbackSettings().manual_image_switch !== false;
}

function completedItemById(id) {
  return (frontendState.completed_items || []).find(item => String(item.id) === String(id));
}

function playbackPositionIdentity(id) {
  const item = completedItemById(id);
  return String((item && (item.local_path || item.filename || item.id)) || id || "");
}

function playbackPositionKey(id) {
  return `${PLAYBACK_POSITION_PREFIX}${encodeURIComponent(playbackPositionIdentity(id))}`;
}

function legacyPlaybackPositionKey(id) {
  return `${PLAYBACK_POSITION_PREFIX}${id}`;
}

function removePlaybackPosition(id) {
  try {
    localStorage.removeItem(playbackPositionKey(id));
    localStorage.removeItem(legacyPlaybackPositionKey(id));
  } catch (_error) {}
}

function cleanupWebPlaybackPositions(items) {
  const validKeys = new Set();
  for (const item of items || []) {
    if (!item || !item.id) continue;
    validKeys.add(playbackPositionKey(item.id));
    validKeys.add(legacyPlaybackPositionKey(item.id));
  }
  try {
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (key && key.startsWith(PLAYBACK_POSITION_PREFIX) && !validKeys.has(key)) {
        localStorage.removeItem(key);
      }
    }
  } catch (_error) {}
}

function isImageItem(item) {
  const type = String(item && item.content_type || "").toLowerCase();
  const path = String(item && (item.local_path || item.filename || item.title) || "").toLowerCase();
  return type === "image" || /\.(png|jpe?g|gif|webp|bmp|avif)$/.test(path);
}

function clearImageAutoAdvanceTimer() {
  if (imageAutoAdvanceTimer) {
    clearTimeout(imageAutoAdvanceTimer);
    imageAutoAdvanceTimer = null;
  }
}

function scheduleImageAutoAdvance(id) {
  clearImageAutoAdvanceTimer();
  if (!id || shouldManualSwitchImages()) return;
  imageAutoAdvanceTimer = setTimeout(() => {
    imageAutoAdvanceTimer = null;
    if (currentPlayingId === id) autoplayNextPreview();
  }, 5000);
}

function frontendAction(action, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    sendWS("frontend_action", {
      action,
      payload,
      frontend_version: Number(frontendVersion || 0),
    });
    if (action === "register_file_associations") appendLog("\u6b63\u5728\u7ed1\u5b9a\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f...");
    return;
  }
  fetch("/api/frontend/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      payload,
      frontend_version: Number(frontendVersion || 0),
    }),
  })
    .then(response => response.json())
    .then(result => {
      if (result && result.frontend_delta) {
        applyFrontendDelta(result.frontend_delta);
      } else {
        return fetchFrontendDelta();
      }
      return result;
    })
    .then(result => {
      if (result && result.message) appendLog(result.message);
    })
    .catch(error => appendLog(error.message || String(error)));
}

function playCompleted(id) {
  selectCompleted(id);
  const item = (frontendState.completed_items || []).find(row => row.id === id);
  if (!item) return;
  if (!shouldUseBuiltinPlayer()) {
    currentPlayingId = id;
    clearImageAutoAdvanceTimer();
    frontendAction("open_file", { id });
    return;
  }
  currentPlayingId = id;
  const video = byId("videoPlayer");
  const placeholder = byId("previewArea");
  if (item.local_path) {
    if (isImageItem(item)) {
      video.pause();
      video.removeAttribute("src");
      video.style.display = "none";
      placeholder.innerHTML = `<img class="preview-image" src="/api/media/${encodeURIComponent(id)}" alt="${escAttr(item.title || item.filename || "")}" />`;
      placeholder.style.display = "flex";
      scheduleImageAutoAdvance(id);
      return;
    }
    clearImageAutoAdvanceTimer();
    placeholder.textContent = "";
    video.src = `/api/media/${encodeURIComponent(id)}`;
    setupPlayerEvents(video, id);
    video.style.display = "block";
    placeholder.style.display = "none";
    video.play().catch(() => {});
  }
}

function openDirectory(id) {
  frontendAction("open_directory", { id });
}

function copyDiagnostics(id) {
  fetch("/api/frontend/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "copy_diagnostics", payload: { id } }),
  }).then(response => response.json()).then(result => {
    const text = result.data && result.data.text ? result.data.text : "";
    if (text && navigator.clipboard) navigator.clipboard.writeText(text);
    appendLog(text ? "Trace ID 已复制" : "未找到 Trace ID");
  });
}

function appendLog(message) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);
  frontendState.log_items = frontendState.log_items || [];
  frontendState.log_items.push({ time: now, level: "INFO", source: "WebUI", thread: "browser", trace_id: "", message_summary: String(message), message: String(message), detail: "", stack: "" });
  trimFrontendLogItems();
  const legacyPanel = byId("logPanel");
  if (legacyPanel) {
    const line = document.createElement("div");
    line.textContent = String(message);
    legacyPanel.appendChild(line);
  }
  scheduleRenderSections(["log_items", "app_status"]);
}

function onChangeDirClicked() {
  byId("dirModal").style.display = "flex";
  byId("dirInput").value = (((frontendState.settings_snapshot || {})["基础设置"] || {}).download_directory || "");
  byId("dirList").textContent = "输入或确认保存目录";
}

function confirmDirDialog() {
  const directory = byId("dirInput").value.trim();
  if (directory) frontendAction("update_basic_setting", { key: "download_directory", value: directory });
  byId("dirModal").style.display = "none";
}

function cancelDirDialog() {
  byId("dirModal").style.display = "none";
}

function showSelectionModal(items) {
  byId("selectionHeader").textContent = `共扫描到 ${items.length} 个资源，请选择下载项目`;
  byId("selectionBody").innerHTML = items.map((item, index) => `<tr><td><input type="checkbox" data-index="${index}" checked></td><td>${esc(item.title || "")}</td></tr>`).join("");
  byId("selectionModal").style.display = "flex";
}

function confirmSelection() {
  const indices = [...document.querySelectorAll("#selectionBody input:checked")].map(input => Number(input.dataset.index));
  sendWS("select_tasks", { indices });
  byId("selectionModal").style.display = "none";
}

function cancelSelection() {
  sendWS("select_tasks", { indices: null });
  byId("selectionModal").style.display = "none";
}

function toggleTheme() {
  const dark = document.documentElement.dataset.theme !== "dark";
  applyTheme(dark);
  localStorage.setItem("cached_theme", dark ? "dark" : "light");
  localStorage.setItem("cached_dark_theme", String(dark));
  updateSetting("common", "theme", dark ? "dark" : "light");
}

function restoreTheme() {
  const cached = localStorage.getItem("cached_theme");
  applyTheme(cached === "dark");
}

function applyAppearance(appearance = {}) {
  const theme = String(appearance.theme || "").toLowerCase();
  if (theme === "dark" || theme === "light") {
    applyTheme(theme === "dark");
    localStorage.setItem("cached_theme", theme);
    localStorage.setItem("cached_dark_theme", String(theme === "dark"));
  }
  const scaleMap = { "90%": .9, "100%": 1, "110%": 1.1, "125%": 1.25 };
  const fontMap = { small: 13, medium: 14, large: 16 };
  const accentMap = {
    blue: { light: ["#1677ff", "#eaf3ff"], dark: ["#3b82f6", "#1f2d46"] },
    green: { light: ["#16a34a", "#e7f8ee"], dark: ["#22c55e", "#153523"] },
    purple: { light: ["#7c3aed", "#f1eaff"], dark: ["#a78bfa", "#312548"] },
    orange: { light: ["#ea580c", "#fff1e7"], dark: ["#fb923c", "#3d2718"] },
    red: { light: ["#dc2626", "#feecec"], dark: ["#f87171", "#402020"] },
  };
  const scale = scaleMap[String(appearance.scale || "100%")] || 1;
  const fontSize = fontMap[String(appearance.font_size || "medium").toLowerCase()] || 14;
  const accent = accentMap[String(appearance.accent || "blue").toLowerCase()] || accentMap.blue;
  const mode = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  document.documentElement.style.setProperty("--ui-scale", String(scale));
  document.documentElement.style.setProperty("--base-font-size", `${Math.max(12, Math.round(fontSize * scale))}px`);
  document.documentElement.style.setProperty("--accent", accent[mode][0]);
  document.documentElement.style.setProperty("--accent-soft", accent[mode][1]);
  document.documentElement.style.setProperty("--row-selected", accent[mode][1]);
  const language = currentLanguage();
  document.documentElement.dataset.language = language;
  document.documentElement.lang = { "en-US": "en", "zh-TW": "zh" }[language] || language;
  applyStaticLanguage();
}

function applyTheme(dark) {
  const theme = dark ? "dark" : "light";
  if (document.documentElement.dataset.theme !== theme) {
    document.documentElement.dataset.theme = theme;
  }
  const themeButton = byId("themeBtn");
  if (themeButton) themeButton.textContent = dark ? "☀" : "☾";
}

function cacheSource() {
  localStorage.setItem("cached_last_source", byId("sourceSelect").value);
  updatePlaceholder();
  sendWS("change_source", { source: byId("sourceSelect").value });
}

function updatePlaceholder() {
  const sourceSelect = byId("sourceSelect");
  const searchInput = byId("searchInput");
  if (!sourceSelect || !searchInput) return;
  const source = sourceSelect.value;
  const platform = platforms.find(item => item.id === source);
  const genericPlaceholder = "输入：主页链接、分享链接或合集链接...";
  const platformPlaceholder = platform && platform.search_placeholder ? String(platform.search_placeholder) : genericPlaceholder;
  const translatedPlatformPlaceholder = t(platformPlaceholder);
  searchInput.placeholder = currentLanguage() === "zh-CN" || translatedPlatformPlaceholder !== platformPlaceholder
    ? translatedPlatformPlaceholder
    : t(genericPlaceholder);
  configureTopCountForSource(source);
}

function resizePreviewImage() {}
function closePreview() {
  clearImageAutoAdvanceTimer();
  const video = byId("videoPlayer");
  video.pause();
  video.removeAttribute("src");
  video.style.display = "none";
  const placeholder = byId("previewArea");
  placeholder.textContent = "选择已完成文件进行播放";
  placeholder.style.display = "flex";
  currentPlayingId = null;
}
function updateNavBtnsState() {}
function deleteVideo(id) {
  if (typeof window !== "undefined" && window.sendWS !== defaultSendWS && typeof window.sendWS === "function") {
    window.sendWS("delete_video", { video_id: id });
    return;
  }
  frontendAction("delete_item", { id });
}
function previewVideo(id) {
  const oldId = selectedVideoId;
  playCompleted(id);
  updateSelection(oldId, id);
  const player = byId("videoPlayer");
  setupPlayerEvents(player, id);
}
function setupPlayerEvents(player, sourceId) {
  if (!player) return;
  player.onloadedmetadata = () => {
    reportCompletedPlayerMetadata(sourceId, player);
    restoreWebPlaybackPosition(sourceId, player);
  };
  player.ontimeupdate = () => rememberWebPlaybackPosition(sourceId, player);
  player.onended = () => {
    removePlaybackPosition(sourceId);
    if (currentPlayingId === sourceId && shouldAutoplayNext()) autoplayNextPreview();
  };
}

function rememberWebPlaybackPosition(sourceId, player) {
  if (!sourceId || !player || !shouldRememberPlaybackPosition()) return;
  if (!Number.isFinite(player.currentTime) || player.currentTime < 1) return;
  if (Number.isFinite(player.duration) && player.duration > 0 && player.currentTime >= player.duration - 1.5) {
    removePlaybackPosition(sourceId);
    return;
  }
  try {
    localStorage.setItem(playbackPositionKey(sourceId), String(Math.floor(player.currentTime)));
    localStorage.removeItem(legacyPlaybackPositionKey(sourceId));
  } catch (_error) {}
}

function restoreWebPlaybackPosition(sourceId, player) {
  if (!sourceId || !player || !shouldRememberPlaybackPosition()) return;
  let seconds = 0;
  try {
    const value = localStorage.getItem(playbackPositionKey(sourceId)) || localStorage.getItem(legacyPlaybackPositionKey(sourceId));
    seconds = Number(value || 0);
  } catch (_error) { seconds = 0; }
  if (seconds > 0 && Number.isFinite(seconds)) player.currentTime = seconds;
}

function reportCompletedPlayerMetadata(sourceId, player) {
  if (!sourceId || !player) return;
  const metadata = {};
  if (Number.isFinite(player.duration) && player.duration > 0) {
    metadata.duration = fmtClockTime(player.duration);
  }
  if (player.videoWidth > 0 && player.videoHeight > 0) {
    metadata.resolution = `${player.videoWidth} x ${player.videoHeight}`;
  }
  if (!Object.keys(metadata).length) return;
  const changed = applyCompletedMetadataLocally(sourceId, metadata);
  frontendAction("update_completed_metadata", { id: sourceId, metadata, source: "web_player" });
  if (changed) renderCompleted();
}

function applyCompletedMetadataLocally(sourceId, metadata) {
  const item = (frontendState.completed_items || []).find(row => row.id === sourceId);
  if (!item) return false;
  let changed = false;
  if (metadata.duration && !hasDisplayDuration(item.duration)) {
    item.duration = metadata.duration;
    changed = true;
  }
  if (metadata.resolution && !isRealResolution(item.resolution)) {
    item.resolution = metadata.resolution;
    changed = true;
  }
  if (hasDisplayDuration(item.duration) && isRealResolution(item.resolution)) {
    item.metadata_pending = false;
  }
  return changed;
}

function hasDisplayDuration(value) {
  const text = String(value || "").trim();
  return !!text && text !== "--" && text !== "检测中" && text !== "00:00:00";
}

function isRealResolution(value) {
  return /^\d{2,5}\s*x\s*\d{2,5}$/i.test(String(value || "").trim());
}
function autoplayNextPreview() {
  const order = (frontendState.completed_items || []).map(item => item.id);
  const index = order.indexOf(currentPlayingId);
  const nextId = index >= 0 && index < order.length - 1 ? order[index + 1] : "";
  if (nextId) playCompleted(nextId);
}
function togglePlay() {
  const video = byId("videoPlayer");
  if (video.paused) video.play().catch(() => {}); else video.pause();
}
function toggleFullscreen() {
  const panel = byId("previewPanel");
  if (!panel || !panel.requestFullscreen) return;
  if (document.fullscreenElement === panel) {
    document.exitFullscreen().catch(() => {});
    return;
  }
  panel.requestFullscreen().catch(error => appendLog(error.message || String(error)));
}
function fmtTime(seconds) {
  const value = Number(seconds) || 0;
  const min = Math.floor(value / 60);
  const sec = Math.floor(value % 60);
  return `${String(min).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function fmtClockTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
function selectVideo(id) {
  selectedVideoId = id;
  if ((frontendState.completed_items || []).some(item => item.id === id)) selectCompleted(id);
}
function updateSelection(oldId, newId) {
  if (oldId) {
    const oldRow = document.querySelector(`tr[data-id="${cssEscape(oldId)}"]`);
    if (oldRow) oldRow.classList.remove("selected");
  }
  selectedVideoId = newId;
  if (newId) {
    const newRow = document.querySelector(`tr[data-id="${cssEscape(newId)}"]`);
    if (newRow) newRow.classList.add("selected");
  }
}
function renderQueueCompat() { renderQueue(); }

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    if (byId("dirModal").style.display === "flex") cancelDirDialog();
    if (byId("selectionModal").style.display === "flex") cancelSelection();
    if (isFullscreenMode && document.fullscreenElement === byId("previewPanel")) {
      document.exitFullscreen().catch(() => {});
    }
  }
  if ((event.key === "ArrowUp" || event.key === "ArrowDown") && videoOrder.length > 0) {
    const tag = document.activeElement && document.activeElement.tagName;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
    event.preventDefault();
    const current = selectedVideoId ? videoOrder.indexOf(selectedVideoId) : -1;
    const next = event.key === "ArrowDown"
      ? (current < videoOrder.length - 1 ? current + 1 : 0)
      : (current > 0 ? current - 1 : videoOrder.length - 1);
    selectVideo(videoOrder[next]);
  }
  if (event.key === "Delete" && selectedVideoId && document.activeElement === document.body) {
    deleteVideo(selectedVideoId);
  }
});

document.addEventListener("fullscreenchange", () => {
  const panel = byId("previewPanel");
  isFullscreenMode = !!panel && document.fullscreenElement === panel;
  if (panel) panel.classList.toggle("is-fullscreen", isFullscreenMode);
});

function byId(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escAttr(value) {
  return esc(value).replace(/'/g, "&#39;");
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
}
