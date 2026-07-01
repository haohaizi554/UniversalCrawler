(function () {
  "use strict";

  const noop = () => {};
  let helpers = {
    getState: () => ({}),
    byId: id => document.getElementById(id),
    esc: value => String(value ?? ""),
    renderCurrentPage: noop,
    updatePlaceholder: noop,
    renderStatus: noop,
    syncAllCustomSelects: noop,
  };

  function configure(next = {}) {
    helpers = { ...helpers, ...next };
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
    helpers.renderCurrentPage();
  } catch (error) {
    console.warn("Failed to load UI i18n catalogs", error);
  }
}

function currentLanguage() {
  const state = helpers.getState() || {};
  const appearance = (state.settings_snapshot || {})["外观设置"] || {};
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
  const button = helpers.byId(buttonId);
  if (!button) return;
  const icon = button.querySelector("img");
  button.innerHTML = `${icon ? icon.outerHTML : ""}${helpers.esc(t(label))}`;
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
  helpers.updatePlaceholder();
  helpers.renderStatus();
  helpers.syncAllCustomSelects();
}

  window.UcpI18n = {
    configure,
    loadUiTextCatalogs,
    currentLanguage,
    t,
    translateUiText,
    translateUiCore,
    translateVisibleText,
    optionLabel,
    setButtonContent,
    applyStaticLanguage,
    fallbackText: FALLBACK_UI_TEXT,
  };
})();
