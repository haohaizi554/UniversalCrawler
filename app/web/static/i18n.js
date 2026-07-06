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
    "高效实用的辅助工具，提升工作效率": "Practical helpers for faster daily work",
    "配置中心": "Settings",
    "集中管理下载行为、平台状态、播放体验、日志策略与界面外观": "Manage download behavior, platform status, playback, logs, and appearance in one place",
    "设置分类": "Categories",
    "启动任务": "Start",
    "停止": "Stop",
    "更改目录": "Change folder",
    "选择保存目录": "Choose save folder",
    "输入目录路径": "Enter folder path",
    "输入或确认保存目录": "Enter or confirm a save folder",
    "选择此目录": "Choose this folder",
    "跳转": "Go",
    "上一级": "Parent",
    "无可用根目录": "No available roots",
    "没有可进入的子目录": "No subfolders",
    "已选择目录": "Folder selected",
    "正在加载目录...": "Loading folder...",
    "单击选择，双击进入子目录": "Click to select, double-click to enter",
    "当前目录没有可访问的上一级": "No accessible parent folder",
    "目录路径不能为空": "Folder path cannot be empty",
    "正在切换目录...": "Changing folder...",
    "目录已变更": "Folder changed",
    "目录加载失败": "Failed to load folder",
    "切换目录失败": "Failed to change folder",
    "视频数:": "Videos:",
    "笔记数:": "Notes:",
    "页数:": "Pages:",
    "输入：主页链接、分享链接或合集链接...": "Enter a profile, shared, or collection link...",
    "输入：快手主页链接、分享链接、快手号或关键词...": "Enter a Kuaishou profile link, share link, Kuaishou ID, or keyword...",
    "输入：番号或老师名...": "Enter an ID or performer name...",
    "输入：BV号、UP主ID、合集链接、主页链接、视频链接、分享链接或关键词...": "Enter a BV ID, creator ID, collection link, profile link, video link, share link, or keyword...",
    "输入：关键词、分享链接、视频/笔记链接、主页链接，或小红书号...": "Enter a keyword, share link, video/note link, profile link, or Xiaohongshu ID...",
    "切换主题": "Toggle theme",
    "打开项目主页": "Open project page",
    "空闲中": "Idle",
    "运行中": "Running",
    "增量状态基线不连续，正在重新同步...": "State update is out of sync. Resyncing...",
    "加载增量状态失败": "Failed to load incremental state",
    "加载状态失败": "Failed to load state",
    "检测中": "Checking",
    "请输入主页链接、分享链接或合集链接": "Enter a profile, shared, or collection link",
    "未选择有效模式": "No valid mode selected",
    "前端连接尚未就绪，请稍后重试": "Frontend connection is not ready. Try again shortly",
    "正在绑定默认打开方式...": "Binding the default open mode...",
    "下载速度": "Download",
    "失败": "Failed",
    "下载目录、命名规则和打开行为": "Download folder, filename rules, and open behavior",
    "下载目录、文件命名和打开行为": "Download folder, filename rules, and open behavior",
    "下载目录、命名规则、打开行为": "Download folder, filename rules, and open behavior",
    "并发、超时、重试和下载策略": "Concurrency, timeout, retry, and download policy",
    "下载并发、超时、重试、下载策略": "Concurrency, timeout, retry, and download policy",
    "认证状态、默认数量和代理入口": "Auth status, default count, and proxy entry",
    "认证状态、爬取数量和代理入口": "Auth status, crawl quantity, and proxy entry",
    "账号验证、爬取数量和代理入口": "Account auth, crawl quantity, and proxy entry",
    "播放器、进度记忆和预览行为": "Player, progress memory, and preview behavior",
    "播放器、断点续播和预览行为": "Player, resume playback, and preview behavior",
    "播放器、进度记录和预览行为": "Player, progress memory, and preview behavior",
    "保留策略、展示数量和错误追踪": "Retention policy, display limits, and error tracing",
    "保留策略、显示上限和错误追踪": "Retention policy, display limits, and error tracing",
    "日志留存、显示条数与错误追踪": "Log retention, display count, and error tracing",
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
    "保存下载文件的位置": "Where downloaded files are saved",
    "从预设模板中选择": "Choose from preset templates",
    "下载完成后的打开行为": "How completed downloads open",
    "任务完成后自动打开": "Open automatically after completion",
    "最大同时下载数": "Maximum simultaneous downloads",
    "控制图片快车道": "Control the image fast lane",
    "网络请求等待时间": "Network request wait time",
    "失败后重试次数": "Retry attempts after failure",
    "限制最大下载速度": "Limit maximum download speed",
    "继续未完成任务": "Continue unfinished tasks",
    "跳过图片资源": "Skip image resources",
    "默认播放方式": "Default playback mode",
    "下次恢复播放位置": "Resume playback next time",
    "结束后播放下一项": "Play the next item after finishing",
    "关闭图片自动轮播": "Disable automatic image rotation",
    "启动时自动清理": "Clean automatically at startup",
    "限制日志中心展示条数": "Limit rows shown in Log Center",
    "异常时复制追踪编号": "Copy trace ID on errors",
    "界面语言": "Interface language",
    "跟随系统主题": "Follow the system theme",
    "主题模式": "Theme mode",
    "界面强调色": "Interface accent color",
    "界面比例": "Interface scale",
    "文字大小": "Text size",
    "路径支持粘贴和选择，命名规则使用预设模板，避免非法文件名。": "Paths support paste and browse. Filename rules use preset templates to avoid illegal names.",
    "路径支持粘贴和选择；命名规则使用预设模板，避免非法文件名。": "Paths support paste and browse. Filename rules use preset templates to avoid illegal names.",
    "并发越高不一定越快，建议根据网络和磁盘性能调整。": "Higher concurrency is not always faster. Tune it for your network and disk.",
    "认证状态自动检测；代理仅对需要的平台开放。": "Authentication is detected automatically. Proxy controls are shown only where needed.",
    "播放设置只影响本地预览，不影响下载文件。": "Playback settings affect local preview only, not downloaded files.",
    "UI 显示数量只影响日志中心显示，不影响日志文件本身。": "The UI display limit affects Log Center only, not the log files.",
    "外观设置会即时生效，并保存到本地配置。": "Appearance changes apply immediately and are saved locally.",
    "选择要注册到 Windows 默认应用的资源类型。Windows 可能会要求在系统默认应用页再次确认。": "Choose the resource types to register with Windows default apps. Windows may still ask for confirmation in Settings.",
    "视频资源（mp4、mkv、avi、mov、webm 等）": "Video resources (mp4, mkv, avi, mov, webm, etc.)",
    "图片资源（jpg、png、gif、webp、bmp 等）": "Image resources (jpg, png, gif, webp, bmp, etc.)",
    "生效方式：注册成功后会立即影响之后的系统打开行为；若 Windows 拦截，程序会打开默认应用设置页供你确认。": "Effective after registration for future system opens. If Windows blocks it, the app opens Default Apps settings for confirmation.",
    "确定": "OK",
    "取消": "Cancel",
    "绑定": "Bind",
    "并发数": "Concurrency",
    "图片受并发数限制": "Limit images by concurrency",
    "请求超时": "Request timeout",
    "最大重试": "Max retries",
    "重试次数": "Retries",
    "速度限制 KB/s": "Speed limit KB/s",
    "下载速度限制（KB/s）": "Speed limit (KB/s)",
    "仅下载视频": "Video only",
    "队列控制": "Queue controls",
    "默认播放器": "Default player",
    "打开方式": "Open mode",
    "记住播放位置": "Remember position",
    "记住播放进度": "Remember position",
    "自动播放下一项": "Autoplay next",
    "视频播放完自动下一项": "Autoplay next",
    "手动切换图片": "Manual image switching",
    "图片只手动切换": "Manual image switching",
    "保留天数": "Retention",
    "日志保留天数": "Log retention",
    "UI最大显示数": "Max UI logs",
    "UI日志最大显示数量": "Max UI logs",
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
    "抖音": "Douyin",
    "小红书": "Xiaohongshu",
    "快手": "Kuaishou",
    "认证状态": "Auth status",
    "默认数量": "Default count",
    "爬取数量": "Crawl quantity",
    "超时": "Timeout",
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
    "保存至：": "Save to:",
    "视频标题": "Video title",
    "标题": "Title",
    "状态": "Status",
    "进度": "Progress",
    "操作": "Actions",
    "播放": "Play",
    "暂停": "Pause",
    "播放/暂停": "Play/Pause",
    "上一个资源": "Previous item",
    "下一个资源": "Next item",
    "媒体全屏": "Fullscreen",
    "媒体全屏（双击画面）": "Fullscreen media (double-click video)",
    "全屏": "Fullscreen",
    "退出": "Exit",
    "播放进度": "Playback progress",
    "打开目录": "Open folder",
    "删除": "Delete",
    "复制 Trace ID": "Copy Trace ID",
    "删除所有": "Delete all",
    "立即刷新": "Refresh now",
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
    "任务清单确认": "Task confirmation",
    "共扫描到 {count} 个资源，请勾选需要下载的项目：": "{count} resources found. Select items to download:",
    "选择": "Select",
    "视频标题 / 描述": "Video title / description",
    "全选": "Select all",
    "反选": "Invert",
    "取消任务": "Cancel task",
    "开始下载": "Start download",
    "当前下载": "Current download",
    "暂无正在下载的任务": "No active downloads",
    "保存目录": "Save folder",
    "输出文件名": "Output filename",
    "来源链接": "Source URL",
    "分片进度": "Segment progress",
    "速度趋势（近60秒）": "Speed trend (last 60s)",
    "速度趋势": "Speed trend",
    "现在": "Now",
    "当前任务事件": "Current task events",
    "暂无事件": "No events",
    "文件信息": "File info",
    "文件名": "Filename",
    "保存路径": "Save path",
    "分辨率": "Resolution",
    "大小": "Size",
    "暂无已完成文件": "No completed files",
    "错误详情": "Error details",
    "暂无失败任务": "No failed tasks",
    "可能的解决方案": "Possible solutions",
    "暂无建议": "No suggestions",
    "全部日志": "All logs",
    "采集日志": "Crawl logs",
    "下载日志": "Download logs",
    "系统日志": "System logs",
    "性能日志": "Performance logs",
    "错误日志": "Error logs",
    "异常日志": "Error logs",
    "日志级别": "Log level",
    "全部": "All",
    "时间范围": "Time range",
    "近 30 分钟": "Last 30 min",
    "近 1 小时": "Last 1 hour",
    "近 24 小时": "Last 24 hours",
    "关键词搜索": "Keyword search",
    "请输入 Trace ID": "Enter Trace ID",
    "请输入关键词...": "Enter keyword...",
    "清空日志": "Clear logs",
    "导出日志": "Export logs",
    "刷新缓冲": "Refresh buffer",
    "刷新": "Refresh",
    "清空": "Clear",
    "导出": "Export",
    "复制": "Copy",
    "暂无匹配日志": "No matching logs",
    "调整筛选条件 或点击「刷新缓冲」重新加载日志": "Adjust filters or click Refresh buffer to reload logs",
    "调整筛选条件": "Adjust filters",
    "或点击「刷新缓冲」重新加载日志": "or click Refresh buffer to reload logs",
    "暂无日志": "No logs",
    "堆栈跟踪": "Stack trace",
    "已复制日志详情": "Copied log details",
    "已复制详细信息": "Copied details",
    "已导出日志详情": "Exported log details",
    "复制TraceID": "Copy TraceID",
    "上一页": "Previous page",
    "下一页": "Next page",
    "当前日志没有可复制的 Trace ID": "No Trace ID is available for the current log",
    "Trace ID 已复制": "Trace ID copied",
    "已复制 Trace ID": "Copied Trace ID",
    "未找到 Trace ID": "No Trace ID found",
    "时间": "Time",
    "级别": "Level",
    "来源": "Source",
    "消息摘要": "Summary",
    "日志详情": "Log details",
    "线程": "Thread",
    "消息": "Message",
    "详细信息": "Details",
    "系统": "System",
    "本地": "Local",
    "未知": "Unknown",
    "下载器": "Downloader",
    "性质": "Nature",
    "范围": "Scope",
    "阶段": "Stage",
    "事件码": "Event code",
    "过程": "Process",
    "成功": "Success",
    "预警": "Warning",
    "错误": "Error",
    "命令": "Command",
    "采集": "Crawl",
    "下载": "Download",
    "性能": "Performance",
    "异常": "Error",
    "初始化": "Init",
    "配置": "Config",
    "扫描": "Scan",
    "启动": "Start",
    "登录": "Login",
    "聚合": "Aggregate",
    "展开": "Expand",
    "确认": "Confirm",
    "解析": "Parse",
    "获取": "Fetch",
    "请求": "Request",
    "发现": "Found",
    "提交": "Emit",
    "入队": "Queued",
    "分发": "Dispatch",
    "准备": "Prepare",
    "合并": "Merge",
    "修正": "Normalize",
    "释放": "Release",
    "完成": "Finish",
    "步骤": "Step",
    "说明": "Description",
    "状态码": "Status code",
    "上下文": "Context",
    "详情": "Details",
    "日志片段": "Log excerpt",
    "建议": "Suggestion",
    "日志缓存已刷新": "Log cache refreshed",
    "Web 端开始扫描本地媒体目录": "Web started scanning local media folder",
    "Web 端开始扫描本地媒体目录（异步）": "Web started scanning local media folder (async)",
    "开始扫描本地媒体目录": "Started scanning local media folder",
    "应用开始初始化": "App initialization started",
    "主窗口初始化完成": "Main window initialized",
    "正在扫描目录": "Scanning folder",
    "本地媒体目录扫描完成": "Local media folder scan completed",
    "开始下载视频": "Started downloading video",
    "主窗口": "Main window",
    "应用上下文": "Application context",
    "图形界面": "GUI",
    "网页端": "WebUI",
    "前端渲染超过交互预算，已降低刷新频率": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
    "下载失败：无法解析视频播放地址": "Download failed: could not parse video URL",
    "采集主页解析完成": "Profile parsing completed",
    "下载分片完成": "Segment download completed",
    "任务异常退出": "Task exited unexpectedly",
    "可见日志": "Visible log",
    "Frontend render exceeded the interactive budget; refresh cadence was relaxed": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
    "待下载": "Pending",
    "排队中": "Queued",
    "已解析": "Parsed",
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
    "播放失败": "Playback failed",
    "文件不存在或已被删除": "File does not exist or has been deleted",
    "播放前校验失败": "Pre-playback check failed",
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
    "高效实用的辅助工具，提升工作效率": "高效實用的輔助工具，提升工作效率",
    "配置中心": "配置中心",
    "集中管理下载行为、平台状态、播放体验、日志策略与界面外观": "集中管理下載行為、平台狀態、播放體驗、日誌策略與介面外觀",
    "设置分类": "設定分類",
    "启动任务": "啟動任務",
    "停止": "停止",
    "更改目录": "變更目錄",
    "选择保存目录": "選擇儲存目錄",
    "输入目录路径": "輸入目錄路徑",
    "输入或确认保存目录": "輸入或確認儲存目錄",
    "选择此目录": "選擇此目錄",
    "跳转": "跳轉",
    "上一级": "上一層",
    "无可用根目录": "無可用根目錄",
    "没有可进入的子目录": "沒有可進入的子目錄",
    "已选择目录": "已選擇目錄",
    "正在加载目录...": "正在載入目錄...",
    "单击选择，双击进入子目录": "單擊選擇，雙擊進入子目錄",
    "当前目录没有可访问的上一级": "目前目錄沒有可存取的上一層",
    "目录路径不能为空": "目錄路徑不能為空",
    "正在切换目录...": "正在切換目錄...",
    "目录已变更": "目錄已變更",
    "目录加载失败": "目錄載入失敗",
    "切换目录失败": "切換目錄失敗",
    "视频数:": "影片數:",
    "笔记数:": "筆記數:",
    "页数:": "頁數:",
    "输入：主页链接、分享链接或合集链接...": "輸入：主頁連結、分享連結或合集連結...",
    "输入：快手主页链接、分享链接、快手号或关键词...": "輸入：快手主頁連結、分享連結、快手號或關鍵字...",
    "输入：番号或老师名...": "輸入：番號或老師名...",
    "输入：BV号、UP主ID、合集链接、主页链接、视频链接、分享链接或关键词...": "輸入：BV 號、UP 主 ID、合集連結、主頁連結、影片連結、分享連結或關鍵字...",
    "输入：关键词、分享链接、视频/笔记链接、主页链接，或小红书号...": "輸入：關鍵字、分享連結、影片/筆記連結、主頁連結，或小紅書號...",
    "切换主题": "切換主題",
    "打开项目主页": "開啟專案首頁",
    "空闲中": "閒置中",
    "运行中": "執行中",
    "增量状态基线不连续，正在重新同步...": "增量狀態基線不連續，正在重新同步...",
    "加载增量状态失败": "載入增量狀態失敗",
    "加载状态失败": "載入狀態失敗",
    "检测中": "檢測中",
    "请输入主页链接、分享链接或合集链接": "請輸入主頁連結、分享連結或合集連結",
    "未选择有效模式": "未選擇有效模式",
    "前端连接尚未就绪，请稍后重试": "前端連線尚未就緒，請稍後重試",
    "正在绑定默认打开方式...": "正在綁定預設開啟方式...",
    "下载速度": "下載速度",
    "失败": "失敗",
    "下载目录、命名规则和打开行为": "下載目錄、命名規則和開啟行為",
    "下载目录、文件命名和打开行为": "下載目錄、檔案命名和開啟行為",
    "下载目录、命名规则、打开行为": "下載目錄、命名規則、開啟行為",
    "并发、超时、重试和下载策略": "並發、逾時、重試和下載策略",
    "下载并发、超时、重试、下载策略": "下載並發、逾時、重試、下載策略",
    "认证状态、默认数量和代理入口": "認證狀態、預設數量和代理入口",
    "认证状态、爬取数量和代理入口": "認證狀態、爬取數量和代理入口",
    "账号验证、爬取数量和代理入口": "帳號驗證、爬取數量和代理入口",
    "播放器、进度记忆和预览行为": "播放器、進度記憶和預覽行為",
    "播放器、断点续播和预览行为": "播放器、斷點續播和預覽行為",
    "播放器、进度记录和预览行为": "播放器、進度記錄和預覽行為",
    "保留策略、展示数量和错误追踪": "保留策略、展示數量和錯誤追蹤",
    "保留策略、显示上限和错误追踪": "保留策略、顯示上限和錯誤追蹤",
    "日志留存、显示条数与错误追踪": "日誌留存、顯示條數與錯誤追蹤",
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
    "保存下载文件的位置": "保存下載檔案的位置",
    "从预设模板中选择": "從預設範本中選擇",
    "下载完成后的打开行为": "下載完成後的開啟行為",
    "任务完成后自动打开": "任務完成後自動開啟",
    "最大同时下载数": "最大同時下載數",
    "控制图片快车道": "控制圖片快車道",
    "网络请求等待时间": "網路請求等待時間",
    "失败后重试次数": "失敗後重試次數",
    "限制最大下载速度": "限制最大下載速度",
    "继续未完成任务": "繼續未完成任務",
    "跳过图片资源": "跳過圖片資源",
    "默认播放方式": "預設播放方式",
    "下次恢复播放位置": "下次恢復播放位置",
    "结束后播放下一项": "結束後播放下一項",
    "关闭图片自动轮播": "關閉圖片自動輪播",
    "启动时自动清理": "啟動時自動清理",
    "限制日志中心展示条数": "限制日誌中心展示筆數",
    "异常时复制追踪编号": "異常時複製追蹤編號",
    "界面语言": "介面語言",
    "跟随系统主题": "跟隨系統主題",
    "主题模式": "主題模式",
    "界面强调色": "介面強調色",
    "界面比例": "介面比例",
    "文字大小": "文字大小",
    "路径支持粘贴和选择，命名规则使用预设模板，避免非法文件名。": "路徑支援貼上和選擇，命名規則使用預設範本，避免非法檔名。",
    "路径支持粘贴和选择；命名规则使用预设模板，避免非法文件名。": "路徑支援貼上和選擇；命名規則使用預設範本，避免非法檔名。",
    "并发越高不一定越快，建议根据网络和磁盘性能调整。": "並發越高不一定越快，建議依網路和磁碟效能調整。",
    "认证状态自动检测；代理仅对需要的平台开放。": "認證狀態會自動偵測；代理只對需要的平台開放。",
    "播放设置只影响本地预览，不影响下载文件。": "播放設定只影響本機預覽，不影響下載檔案。",
    "UI 显示数量只影响日志中心显示，不影响日志文件本身。": "UI 顯示數量只影響日誌中心顯示，不影響日誌檔案本身。",
    "外观设置会即时生效，并保存到本地配置。": "外觀設定會即時生效，並保存到本機設定。",
    "选择要注册到 Windows 默认应用的资源类型。Windows 可能会要求在系统默认应用页再次确认。": "選擇要註冊到 Windows 預設應用程式的資源類型。Windows 可能仍會要求在系統設定頁再次確認。",
    "视频资源（mp4、mkv、avi、mov、webm 等）": "影片資源（mp4、mkv、avi、mov、webm 等）",
    "图片资源（jpg、png、gif、webp、bmp 等）": "圖片資源（jpg、png、gif、webp、bmp 等）",
    "生效方式：注册成功后会立即影响之后的系统打开行为；若 Windows 拦截，程序会打开默认应用设置页供你确认。": "生效方式：註冊成功後會立即影響之後的系統開啟行為；若 Windows 攔截，程式會開啟預設應用程式設定頁供你確認。",
    "确定": "確定",
    "取消": "取消",
    "绑定": "綁定",
    "并发数": "並發數",
    "图片受并发数限制": "圖片受並發數限制",
    "请求超时": "請求逾時",
    "最大重试": "最大重試",
    "重试次数": "重試次數",
    "速度限制 KB/s": "速度限制 KB/s",
    "下载速度限制（KB/s）": "下載速度限制（KB/s）",
    "仅下载视频": "僅下載影片",
    "队列控制": "佇列控制",
    "默认播放器": "預設播放器",
    "打开方式": "開啟方式",
    "记住播放位置": "記住播放位置",
    "记住播放进度": "記住播放進度",
    "自动播放下一项": "自動播放下一項",
    "视频播放完自动下一项": "影片播放完自動下一項",
    "手动切换图片": "手動切換圖片",
    "图片只手动切换": "圖片只手動切換",
    "保留天数": "保留天數",
    "日志保留天数": "日誌保留天數",
    "UI最大显示数": "UI 最大顯示數",
    "UI日志最大显示数量": "UI 日誌最大顯示數量",
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
    "抖音": "抖音",
    "小红书": "小紅書",
    "快手": "快手",
    "认证状态": "認證狀態",
    "默认数量": "預設數量",
    "爬取数量": "爬取數量",
    "超时": "逾時",
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
    "保存至：": "儲存至：",
    "视频标题": "影片標題",
    "标题": "標題",
    "状态": "狀態",
    "进度": "進度",
    "操作": "操作",
    "播放": "播放",
    "暂停": "暫停",
    "播放/暂停": "播放/暫停",
    "上一个资源": "上一個資源",
    "下一个资源": "下一個資源",
    "媒体全屏": "媒體全螢幕",
    "媒体全屏（双击画面）": "媒體全螢幕（雙擊畫面）",
    "全屏": "全螢幕",
    "退出": "退出",
    "播放进度": "播放進度",
    "打开目录": "開啟目錄",
    "删除": "刪除",
    "复制 Trace ID": "複製 Trace ID",
    "删除所有": "刪除所有",
    "立即刷新": "立即重新整理",
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
    "任务清单确认": "任務清單確認",
    "共扫描到 {count} 个资源，请勾选需要下载的项目：": "共掃描到 {count} 個資源，請勾選需要下載的項目：",
    "选择": "選擇",
    "视频标题 / 描述": "影片標題 / 描述",
    "全选": "全選",
    "反选": "反選",
    "取消任务": "取消任務",
    "开始下载": "開始下載",
    "当前下载": "目前下載",
    "暂无正在下载的任务": "暫無正在下載的任務",
    "保存目录": "儲存目錄",
    "输出文件名": "輸出檔名",
    "来源链接": "來源連結",
    "分片进度": "分片進度",
    "速度趋势（近60秒）": "速度趨勢（近60秒）",
    "速度趋势": "速度趨勢",
    "现在": "現在",
    "当前任务事件": "目前任務事件",
    "暂无事件": "暫無事件",
    "文件信息": "檔案資訊",
    "文件名": "檔案名稱",
    "保存路径": "儲存路徑",
    "分辨率": "解析度",
    "大小": "大小",
    "暂无已完成文件": "暫無已完成檔案",
    "错误详情": "錯誤詳情",
    "暂无失败任务": "暫無失敗任務",
    "可能的解决方案": "可能的解決方案",
    "暂无建议": "暫無建議",
    "全部日志": "全部日誌",
    "采集日志": "採集日誌",
    "下载日志": "下載日誌",
    "系统日志": "系統日誌",
    "性能日志": "性能日誌",
    "错误日志": "錯誤日誌",
    "异常日志": "異常日誌",
    "日志级别": "日誌級別",
    "全部": "全部",
    "时间范围": "時間範圍",
    "近 30 分钟": "近 30 分鐘",
    "近 1 小时": "近 1 小時",
    "近 24 小时": "近 24 小時",
    "关键词搜索": "關鍵字搜尋",
    "请输入 Trace ID": "請輸入 Trace ID",
    "请输入关键词...": "請輸入關鍵字...",
    "清空日志": "清空日誌",
    "导出日志": "匯出日誌",
    "刷新缓冲": "刷新緩衝",
    "刷新": "刷新",
    "清空": "清空",
    "导出": "匯出",
    "复制": "複製",
    "暂无匹配日志": "暫無匹配日誌",
    "调整筛选条件 或点击「刷新缓冲」重新加载日志": "調整篩選條件 或點擊「刷新緩衝」重新載入日誌",
    "调整筛选条件": "調整篩選條件",
    "或点击「刷新缓冲」重新加载日志": "或點擊「刷新緩衝」重新載入日誌",
    "暂无日志": "暫無日誌",
    "堆栈跟踪": "堆疊追蹤",
    "已复制日志详情": "已複製日誌詳情",
    "已复制详细信息": "已複製詳細資訊",
    "已导出日志详情": "已匯出日誌詳情",
    "复制TraceID": "複製TraceID",
    "上一页": "上一頁",
    "下一页": "下一頁",
    "当前日志没有可复制的 Trace ID": "目前日誌沒有可複製的 Trace ID",
    "Trace ID 已复制": "Trace ID 已複製",
    "已复制 Trace ID": "已複製 Trace ID",
    "未找到 Trace ID": "未找到 Trace ID",
    "时间": "時間",
    "级别": "級別",
    "来源": "來源",
    "消息摘要": "訊息摘要",
    "日志详情": "日誌詳情",
    "线程": "執行緒",
    "消息": "訊息",
    "详细信息": "詳細資訊",
    "系统": "系統",
    "本地": "本機",
    "未知": "未知",
    "下载器": "下載器",
    "性质": "性質",
    "范围": "範圍",
    "阶段": "階段",
    "事件码": "事件碼",
    "过程": "過程",
    "成功": "成功",
    "预警": "預警",
    "错误": "錯誤",
    "命令": "命令",
    "采集": "採集",
    "下载": "下載",
    "性能": "性能",
    "异常": "異常",
    "初始化": "初始化",
    "配置": "配置",
    "扫描": "掃描",
    "启动": "啟動",
    "登录": "登入",
    "聚合": "聚合",
    "展开": "展開",
    "确认": "確認",
    "解析": "解析",
    "获取": "取得",
    "请求": "請求",
    "发现": "發現",
    "提交": "提交",
    "入队": "入隊",
    "分发": "分發",
    "准备": "準備",
    "合并": "合併",
    "修正": "修正",
    "释放": "釋放",
    "完成": "完成",
    "步骤": "步驟",
    "说明": "說明",
    "状态码": "狀態碼",
    "上下文": "上下文",
    "详情": "詳情",
    "日志片段": "日誌片段",
    "建议": "建議",
    "日志缓存已刷新": "日誌快取已刷新",
    "Web 端开始扫描本地媒体目录": "Web 端開始掃描本機媒體目錄",
    "Web 端开始扫描本地媒体目录（异步）": "Web 端開始掃描本機媒體目錄（非同步）",
    "开始扫描本地媒体目录": "開始掃描本機媒體目錄",
    "应用开始初始化": "應用開始初始化",
    "主窗口初始化完成": "主視窗初始化完成",
    "正在扫描目录": "正在掃描目錄",
    "本地媒体目录扫描完成": "本機媒體目錄掃描完成",
    "开始下载视频": "開始下載影片",
    "主窗口": "主視窗",
    "应用上下文": "應用程式上下文",
    "图形界面": "圖形介面",
    "网页端": "網頁端",
    "前端渲染超过交互预算，已降低刷新频率": "前端渲染超過互動預算，已降低刷新頻率",
    "下载失败：无法解析视频播放地址": "下載失敗：無法解析影片播放位址",
    "采集主页解析完成": "採集主頁解析完成",
    "下载分片完成": "下載分片完成",
    "任务异常退出": "任務異常退出",
    "可见日志": "可見日誌",
    "Frontend render exceeded the interactive budget; refresh cadence was relaxed": "前端渲染超出互動預算；已降低刷新頻率",
    "待下载": "待下載",
    "排队中": "排隊中",
    "已解析": "已解析",
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
    "播放失败": "播放失敗",
    "文件不存在或已被删除": "檔案不存在或已被刪除",
    "播放前校验失败": "播放前校驗失敗",
  },
};

let UI_TEXT = FALLBACK_UI_TEXT;
let i18nCatalogLoadStarted = false;
let REVERSE_UI_TEXT = Object.create(null);

const CANONICAL_UI_TEXT_ALIASES = {
  "Last 30 minutes": "近 30 分钟",
  "Last 30 min": "近 30 分钟",
  "Last 1 hour": "近 1 小时",
  "Last 24 hours": "近 24 小时",
  "MainWindow": "主窗口",
  "Main window": "主窗口",
  "ApplicationContext": "应用上下文",
  "Application context": "应用上下文",
  "GUI": "图形界面",
  "WebUI": "网页端",
  "Frontend render exceeded the interactive budget; refresh cadence was relaxed": "前端渲染超过交互预算，已降低刷新频率",
  "Frontend render e...": "前端渲染超过交互预算，已降低刷新频率",
  "Error logs": "错误日志",
  "異常日誌": "异常日志",
};

function rebuildReverseTextIndex() {
  const reverse = Object.create(null);
  for (const catalog of Object.values(UI_TEXT || {})) {
    if (!catalog || typeof catalog !== "object") continue;
    for (const [source, translated] of Object.entries(catalog)) {
      const sourceText = String(source || "").trim();
      const translatedText = String(translated || "").trim();
      if (!sourceText || !translatedText || sourceText === translatedText) continue;
      if (!reverse[translatedText]) reverse[translatedText] = sourceText;
    }
  }
  for (const [translated, source] of Object.entries(CANONICAL_UI_TEXT_ALIASES)) {
    reverse[translated] = source;
  }
  REVERSE_UI_TEXT = reverse;
}

function canonicalUiText(text) {
  const value = String(text ?? "").trim();
  return REVERSE_UI_TEXT[value] || value;
}

rebuildReverseTextIndex();

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
    rebuildReverseTextIndex();
    applyStaticLanguage();
    helpers.renderCurrentPage();
  } catch (error) {
    console.warn("Failed to load UI i18n catalogs", error);
  }
}

function normalizeUiLanguage(value) {
  const language = String(value || "").trim();
  return ["zh-CN", "en-US", "zh-TW"].includes(language) ? language : "";
}

function currentLanguage() {
  const domLanguage = normalizeUiLanguage(document.documentElement?.dataset?.language);
  if (domLanguage) return domLanguage;
  const state = helpers.getState() || {};
  const appearance = (state.settings_snapshot || {})["外观设置"] || {};
  return normalizeUiLanguage(appearance.language) || "zh-CN";
}

function t(text) {
  const value = String(text || "");
  if (!value) return value;
  const lang = currentLanguage();
  const dict = UI_TEXT[lang] || {};
  const canonical = canonicalUiText(value);
  if (lang === "zh-CN") return canonical;
  return dict[value] || dict[canonical] || canonical;
}

function translateUiText(text) {
  const lang = currentLanguage();
  const value = String(text || "");
  if (!value.trim()) return value;
  const leading = value.match(/^\s*/)?.[0] || "";
  const trailing = value.match(/\s*$/)?.[0] || "";
  const core = value.trim();
  const translated = translateUiCore(core, lang);
  return translated === core ? value : `${leading}${translated}${trailing}`;
}

function translateUiCore(text, lang = currentLanguage()) {
  const dict = UI_TEXT[lang] || {};
  const canonical = canonicalUiText(text);
  if (lang === "zh-CN" && canonical !== text) return canonical;
  if (dict[text]) return dict[text];
  if (dict[canonical]) return dict[canonical];
  if (canonical !== text) return canonical;
  const iconPrefix = text.match(/^([\p{Extended_Pictographic}✅⚠️❌ℹ️🔗📂]+\s+)(.+)$/u);
  if (iconPrefix) return `${iconPrefix[1]}${translateUiCore(iconPrefix[2].trim(), lang)}`;
  if (text.includes(" · ")) {
    return text.split(" · ").map(part => translateUiCore(part.trim(), lang)).join(" · ");
  }
  if (text.includes("\n")) {
    return text.split("\n").map(part => translateUiCore(part.trim(), lang)).join("\n");
  }
  if (text.includes("\t")) {
    return text.split("\t").map(part => translateUiCore(part.trim(), lang)).join("\t");
  }
  let match = text.match(/^\[\s*(.+?)\s*\]$/);
  if (match) return `[ ${translateUiCore(match[1].trim(), lang)} ]`;
  match = text.match(/^(.+?)\s+(\d+)$/);
  if (match) {
    const label = translateUiCore(match[1].trim(), lang);
    if (label !== match[1].trim()) return `${label} ${match[2]}`;
  }
  match = text.match(/^(\d+)\s+videos?(\s*\((?:Recommended|Rec\.)\))?$/i);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 個影片${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 个视频${match[2] ? "（推荐）" : ""}` : `${match[1]} ${Number(match[1]) === 1 ? "video" : "videos"}${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s+notes?(\s*\((?:Recommended|Rec\.)\))?$/i);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 篇筆記${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 篇笔记${match[2] ? "（推荐）" : ""}` : `${match[1]} ${Number(match[1]) === 1 ? "note" : "notes"}${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s+pages?(\s*\((?:Recommended|Rec\.)\))?$/i);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 頁${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 页${match[2] ? "（推荐）" : ""}` : `${match[1]} ${Number(match[1]) === 1 ? "page" : "pages"}${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s+rows?(\s*\((?:Recommended|Rec\.)\))?$/i);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 條${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 条${match[2] ? "（推荐）" : ""}` : `${match[1]} rows${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s+days?(\s*\((?:Recommended|Rec\.)\))?$/i);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 天${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 天${match[2] ? "（推荐）" : ""}` : `${match[1]} ${Number(match[1]) === 1 ? "day" : "days"}${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s+sec(?:onds?)?(\s*\((?:Recommended|Rec\.)\))?$/i);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 秒${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 秒${match[2] ? "（推荐）" : ""}` : `${match[1]} sec${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s+times?$/i);
  if (match) return lang === "zh-TW" ? `${match[1]} 次` : (lang === "zh-CN" ? `${match[1]}次` : `${match[1]} times`);
  match = text.match(/^(\d+)\s*\((?:Recommended|Rec\.)\)$/i);
  if (match) return lang === "zh-TW" ? `${match[1]}（推薦）` : (lang === "zh-CN" ? `${match[1]}（推荐）` : `${match[1]} (Recommended)`);
  match = text.match(/^(\d+)\s*\/\s*page$/i);
  if (match) return lang === "zh-TW" ? `${match[1]} 條/頁` : (lang === "zh-CN" ? `${match[1]} 条/页` : `${match[1]} / page`);
  match = text.match(/^Page\s*(\d+)\s*\/\s*(\d+)$/i);
  if (match) return lang === "zh-TW" ? `第 ${match[1]} / ${match[2]} 頁` : (lang === "zh-CN" ? `第 ${match[1]} / ${match[2]} 页` : `Page ${match[1]} / ${match[2]}`);
  match = text.match(/^Total\s*(\d+)\s*\/\s*matched\s*(\d+)\s*\/\s*showing\s*(\d+)$/i);
  if (match) return lang === "zh-TW"
    ? `共 ${match[1]} 條 / 匹配 ${match[2]} 條 / 目前顯示 ${match[3]} 條`
    : (lang === "zh-CN" ? `共 ${match[1]} 条 / 匹配 ${match[2]} 条 / 当前显示 ${match[3]} 条` : `Total ${match[1]} / matched ${match[2]} / showing ${match[3]}`);
  match = text.match(/^Running:\s*(\d+)\s*tasks?$/i);
  if (match) return lang === "zh-TW" ? `目前執行：${match[1]} 個任務` : (lang === "zh-CN" ? `当前运行：${match[1]} 个任务` : `Running: ${match[1]} tasks`);
  match = text.match(/^Scanning folder[:：]\s*(.*)$/i);
  if (match) return lang === "zh-TW" ? `正在掃描目錄：${match[1]}` : (lang === "zh-CN" ? `正在扫描目录：${match[1]}` : `Scanning folder: ${match[1]}`);
  match = text.match(/^Loaded\s*(\d+)\s*local files\s*\(videos:\s*(\d+),\s*images:\s*(\d+)\)$/i);
  if (match) return lang === "zh-TW"
    ? `已載入 ${match[1]} 個本機檔案（影片：${match[2]}，圖片：${match[3]}）`
    : (lang === "zh-CN" ? `已加载 ${match[1]} 个本地文件（视频：${match[2]}，图片：${match[3]}）` : `Loaded ${match[1]} local files (videos: ${match[2]}, images: ${match[3]})`);
  match = text.match(/^Loaded\s*(\d+)\s*local files$/i);
  if (match) return lang === "zh-TW" ? `已載入 ${match[1]} 個本機檔案` : (lang === "zh-CN" ? `已加载 ${match[1]} 个本地文件` : `Loaded ${match[1]} local files`);
  match = text.match(/^任务进入\s*(.*?)\s*下载器$/);
  if (match) {
    const platform = translateUiCore(match[1].trim(), lang);
    return lang === "zh-TW" ? `任務進入 ${platform} 下載器` : (lang === "zh-CN" ? `任务进入 ${platform} 下载器` : `Task entered ${platform} downloader`);
  }
  match = text.match(/^任务进入下载器[:：]\s*(.*)$/);
  if (match) {
    const platform = translateUiCore(match[1].trim(), lang);
    return lang === "zh-TW" ? `任務進入下載器：${platform}` : (lang === "zh-CN" ? `任务进入下载器：${platform}` : `Task entered downloader: ${platform}`);
  }
  match = text.match(/^进度[:：]\s*(.*)$/);
  if (match) return lang === "zh-TW" ? `進度：${match[1]}` : (lang === "zh-CN" ? `进度：${match[1]}` : `Progress: ${match[1]}`);
  match = text.match(/^当前速度[:：]\s*(.*?)\s*[,，]\s*剩余[:：]\s*(.*)$/);
  if (match) return lang === "zh-TW" ? `目前速度：${match[1]}，剩餘：${match[2]}` : (lang === "zh-CN" ? `当前速度：${match[1]}，剩余：${match[2]}` : `Current speed: ${match[1]}, remaining: ${match[2]}`);
  match = text.match(/^当前速度[:：]\s*(.*)$/);
  if (match) return lang === "zh-TW" ? `目前速度：${match[1]}` : (lang === "zh-CN" ? `当前速度：${match[1]}` : `Current speed: ${match[1]}`);
  match = text.match(/^写入状态[:：]\s*(.*)$/);
  if (match) return lang === "zh-TW" ? `寫入狀態：${match[1]}` : (lang === "zh-CN" ? `写入状态：${match[1]}` : `Write status: ${match[1]}`);
  match = text.match(/^合并状态[:：]\s*(.*)$/);
  if (match) return lang === "zh-TW" ? `合併狀態：${match[1]}` : (lang === "zh-CN" ? `合并状态：${match[1]}` : `Merge status: ${match[1]}`);
  if (text === "音视频流下载中") return lang === "zh-TW" ? "音視訊流下載中" : (lang === "zh-CN" ? text : "Audio/video stream downloading");
  if (text === "来源链接已记录") return lang === "zh-TW" ? "來源連結已記錄" : (lang === "zh-CN" ? text : "Source link recorded");
  if (text === "等待下载器上报详细事件") return lang === "zh-TW" ? "等待下載器回報詳細事件" : (lang === "zh-CN" ? text : "Waiting for downloader events");
  match = text.match(/^保存至：(.*)$/);
  if (match) return lang === "zh-TW" ? `儲存至：${match[1]}` : (lang === "zh-CN" ? `保存至：${match[1]}` : `Save to: ${match[1]}`);
  match = text.match(/^共\s*(\d+)\s*项$/);
  if (match) return lang === "zh-TW" ? `共 ${match[1]} 項` : (lang === "zh-CN" ? `共 ${match[1]} 项` : `Total ${match[1]} items`);
  match = text.match(/^共\s*(\d+)\s*条\s*\/\s*匹配\s*(\d+)\s*条\s*\/\s*当前显示\s*(\d+)\s*条$/);
  if (match) return lang === "zh-TW"
    ? `共 ${match[1]} 條 / 匹配 ${match[2]} 條 / 目前顯示 ${match[3]} 條`
    : (lang === "zh-CN" ? `共 ${match[1]} 条 / 匹配 ${match[2]} 条 / 当前显示 ${match[3]} 条` : `Total ${match[1]} / matched ${match[2]} / showing ${match[3]}`);
  match = text.match(/^第\s*(\d+)\s*\/\s*(\d+)\s*页$/);
  if (match) return lang === "zh-TW" ? `第 ${match[1]} / ${match[2]} 頁` : (lang === "zh-CN" ? `第 ${match[1]} / ${match[2]} 页` : `Page ${match[1]} / ${match[2]}`);
  match = text.match(/^(\d+)\s*\/\s*(\d+)\s*页$/);
  if (match) return lang === "zh-TW" ? `${match[1]} / ${match[2]} 頁` : (lang === "zh-CN" ? `${match[1]} / ${match[2]} 页` : `${match[1]} / ${match[2]} pages`);
  match = text.match(/^(\d+)\s*条\/页$/);
  if (match) return lang === "zh-TW" ? `${match[1]} 條/頁` : (lang === "zh-CN" ? `${match[1]} 条/页` : `${match[1]} / page`);
  match = text.match(/^(\d+)\s*条(（推荐）)?$/);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 條${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 条${match[2] ? "（推荐）" : ""}` : `${match[1]} rows${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)\s*天(（推荐）)?$/);
  if (match) {
    const noun = Number(match[1]) === 1 ? "day" : "days";
    return lang === "zh-TW"
      ? `${match[1]} 天${match[2] ? "（推薦）" : ""}`
      : (lang === "zh-CN" ? `${match[1]} 天${match[2] ? "（推荐）" : ""}` : `${match[1]} ${noun}${match[2] ? " (Recommended)" : ""}`);
  }
  match = text.match(/^(\d+)\s*秒(（推荐）)?$/);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 秒${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]} 秒${match[2] ? "（推荐）" : ""}` : `${match[1]} sec${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)次$/);
  if (match) return lang === "zh-TW" ? `${match[1]} 次` : (lang === "zh-CN" ? `${match[1]}次` : `${match[1]} times`);
  match = text.match(/^(\d+)\s*次(（推荐）)?$/);
  if (match) return lang === "zh-TW"
    ? `${match[1]} 次${match[2] ? "（推薦）" : ""}`
    : (lang === "zh-CN" ? `${match[1]}次${match[2] ? "（推荐）" : ""}` : `${match[1]} times${match[2] ? " (Recommended)" : ""}`);
  match = text.match(/^(\d+)（推荐）$/);
  if (match) return lang === "zh-TW" ? `${match[1]}（推薦）` : (lang === "zh-CN" ? `${match[1]}（推荐）` : `${match[1]} (Recommended)`);
  match = text.match(/^当前运行：(\d+)\s*个任务$/);
  if (match) return lang === "zh-TW" ? `目前執行：${match[1]} 個任務` : (lang === "zh-CN" ? `当前运行：${match[1]} 个任务` : `Running: ${match[1]} tasks`);
  match = text.match(/^正在扫描目录[:：]\s*(.*)$/);
  if (match) return lang === "zh-TW" ? `正在掃描目錄：${match[1]}` : (lang === "zh-CN" ? `正在扫描目录：${match[1]}` : `Scanning folder: ${match[1]}`);
  match = text.match(/^已加载\s*(\d+)\s*个本地文件\s*\(视频:\s*(\d+),\s*图片:\s*(\d+)\)$/);
  if (match) return lang === "zh-TW"
    ? `已載入 ${match[1]} 個本機檔案（影片：${match[2]}，圖片：${match[3]}）`
    : (lang === "zh-CN" ? `已加载 ${match[1]} 个本地文件（视频：${match[2]}，图片：${match[3]}）` : `Loaded ${match[1]} local files (videos: ${match[2]}, images: ${match[3]})`);
  match = text.match(/^已加载\s*(\d+)\s*个本地文件$/);
  if (match) return lang === "zh-TW" ? `已載入 ${match[1]} 個本機檔案` : (lang === "zh-CN" ? `已加载 ${match[1]} 个本地文件` : `Loaded ${match[1]} local files`);
  match = text.match(/^打开\s+(.+)$/);
  if (match) return lang === "zh-TW" ? `開啟 ${match[1]}` : (lang === "zh-CN" ? `打开 ${match[1]}` : `Open ${match[1]}`);
  match = text.match(/^(.+?)[:：]\s*(.*)$/);
  if (match && dict[match[1].trim()]) {
    const label = translateUiCore(match[1].trim(), lang);
    const detail = translateUiCore(match[2].trim(), lang);
    if (lang === "zh-TW") return detail ? `${label}：${detail}` : label;
    if (lang === "zh-CN") return detail ? `${label}：${detail}` : label;
    return detail ? `${label}: ${detail}` : label;
  }
  match = text.match(/^(.+)\s+今天\s+(.+)$/);
  if (match) return `${translateUiCore(match[1].trim(), lang)}  ${translateUiCore("今天", lang)} ${match[2]}`;
  return text;
}

function translateVisibleText(root = document.body) {
  if (!root) return;
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
  return translateUiCore(text);
}

function setButtonContent(buttonId, label) {
  const button = helpers.byId(buttonId);
  if (!button) return;
  const icon = button.querySelector("img");
  button.innerHTML = `${icon ? icon.outerHTML : ""}${helpers.esc(t(label))}`;
}

function setLeadingText(selector, label) {
  const element = document.querySelector(selector);
  if (!element) return;
  const translated = `${t(label)} `;
  const textNode = Array.from(element.childNodes).find(node => node.nodeType === Node.TEXT_NODE && node.nodeValue.trim());
  if (textNode) {
    textNode.nodeValue = translated;
    return;
  }
  element.insertBefore(document.createTextNode(translated), element.firstChild);
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
  const queuePathLabel = document.querySelector("#page-queue .queue-path-label");
  if (queuePathLabel) queuePathLabel.textContent = t("保存至：");
  const queueHeaders = ["视频标题", "平台", "状态", "操作"];
  document.querySelectorAll("#page-queue th").forEach((header, index) => {
    if (queueHeaders[index]) header.textContent = t(queueHeaders[index]);
  });
  const activeHeaders = ["标题", "平台", "进度", "速度", "剩余时间", "操作"];
  document.querySelectorAll("#page-active th").forEach((header, index) => {
    if (activeHeaders[index]) header.textContent = t(activeHeaders[index]);
  });
  const activeControlTitle = document.querySelector("#page-active .active-control-title");
  if (activeControlTitle) activeControlTitle.textContent = t("队列控制");
  const activeRetryLabel = document.querySelector("#page-active .active-toggle span");
  if (activeRetryLabel) activeRetryLabel.textContent = t("失败自动重试");
  setLeadingText("#page-active .active-control-row label:nth-of-type(2)", "最大重试次数");
  setLeadingText("#page-active .active-control-row label:nth-of-type(3)", "并发数");
  const completedHeaders = ["标题", "完成时间", "时长", "格式", "操作"];
  document.querySelectorAll("#page-completed th").forEach((header, index) => {
    if (completedHeaders[index]) header.textContent = t(completedHeaders[index]);
  });
  const failedHeaders = ["标题", "失败时间", "失败原因", "状态", "操作"];
  document.querySelectorAll("#page-failed th").forEach((header, index) => {
    if (failedHeaders[index]) header.textContent = t(failedHeaders[index]);
  });
  const clearQueueButton = document.querySelector("#page-queue [onclick=\"frontendAction('clear_queue',{})\"]");
  if (clearQueueButton) {
    clearQueueButton.title = t("删除所有");
    clearQueueButton.setAttribute("aria-label", t("删除所有"));
  }
  const refreshQueueButton = document.querySelector("#page-queue [onclick=\"fetchFrontendState()\"]");
  if (refreshQueueButton) {
    refreshQueueButton.title = t("立即刷新");
    refreshQueueButton.setAttribute("aria-label", t("立即刷新"));
  }
  const logTabLabels = {
    all: "全部日志",
    crawl: "采集日志",
    download: "下载日志",
    system: "系统日志",
    performance: "性能日志",
    error: "错误日志",
  };
  document.querySelectorAll("#logTabs [data-log-tab]").forEach(button => {
    const label = logTabLabels[button.dataset.logTab];
    if (label) button.textContent = t(label);
  });
  if (typeof syncLogTabLabels === "function") syncLogTabLabels();
  const logFilterLabels = ["日志级别", "时间范围", "平台", "Trace ID", "关键词搜索"];
  document.querySelectorAll("#page-logs .log-filter-label").forEach((label, index) => {
    if (logFilterLabels[index]) label.textContent = t(logFilterLabels[index]);
  });
  const logTraceFilter = helpers.byId("logTraceFilter");
  if (logTraceFilter) logTraceFilter.placeholder = t("请输入 Trace ID");
  const logKeywordFilter = helpers.byId("logKeywordFilter");
  if (logKeywordFilter) logKeywordFilter.placeholder = t("请输入关键词...");
  const logHeaders = ["时间", "级别", "来源", "Trace ID", "消息摘要"];
  document.querySelectorAll("#page-logs th").forEach((header, index) => {
    if (logHeaders[index]) header.textContent = t(logHeaders[index]);
  });
  const logActionLabels = [
    ["runLogOperation('refresh')", "刷新"],
    ["runLogOperation('clear')", "清空"],
    ["runLogOperation('export')", "导出"],
    ["runLogOperation('open_latest')", "debug.log"],
    ["runLogOperation('open_error_summary')", "error.md"],
    ["copySelectedLogTraceId()", "复制TraceID"],
  ];
  for (const [onclick, label] of logActionLabels) {
    const button = document.querySelector(`#page-logs .log-actions [onclick="${onclick}"]`);
    if (button) button.textContent = t(label);
  }
  setButtonContent("logPrevPage", "上一页");
  setButtonContent("logNextPage", "下一页");
  const pagerIconButtons = {
    queuePrevPage: "上一页",
    queueNextPage: "下一页",
    completedPrevPage: "上一页",
    completedNextPage: "下一页",
  };
  for (const [id, label] of Object.entries(pagerIconButtons)) {
    const button = helpers.byId(id);
    if (button) {
      button.title = t(label);
      button.setAttribute("aria-label", t(label));
    }
  }
  const dirLabels = {
    dirTitle: "选择保存目录",
    dirGoBtn: "跳转",
    dirParentBtn: "上一级",
    dirCancelBtn: "取消",
    dirConfirmBtn: "选择此目录",
  };
  for (const [id, label] of Object.entries(dirLabels)) {
    const element = helpers.byId(id);
    if (element) element.textContent = t(label);
  }
  const dirInput = helpers.byId("dirInput");
  if (dirInput) dirInput.placeholder = t("输入目录路径");
  const dirRefresh = helpers.byId("dirRefreshBtn");
  if (dirRefresh) {
    dirRefresh.title = t("刷新");
    dirRefresh.setAttribute("aria-label", t("刷新"));
  }
  if (typeof window.applyFileAssociationLanguage === "function") {
    window.applyFileAssociationLanguage();
  }
  const selectionTitle = helpers.byId("selectionTitle");
  if (selectionTitle) selectionTitle.textContent = t("任务清单确认");
  const selectionHeader = helpers.byId("selectionHeader");
  if (selectionHeader) {
    const count = document.querySelectorAll("#selectionBody .selection-row").length;
    selectionHeader.textContent = t("共扫描到 {count} 个资源，请勾选需要下载的项目：").replace("{count}", String(count));
  }
  const selectionHeadCells = document.querySelectorAll(".selection-table thead th");
  if (selectionHeadCells[0]) selectionHeadCells[0].textContent = t("选择");
  if (selectionHeadCells[1]) selectionHeadCells[1].textContent = t("视频标题 / 描述");
  const selectionButtons = {
    selectionAllBtn: "全选",
    selectionInvertBtn: "反选",
    selectionCancelBtn: "取消任务",
    selectionConfirmBtn: "开始下载",
  };
  for (const [id, label] of Object.entries(selectionButtons)) {
    const button = helpers.byId(id);
    if (button) button.textContent = t(label);
  }
  const themeButton = byId("themeBtn");
  if (themeButton) {
    themeButton.title = t("切换主题");
    themeButton.setAttribute("aria-label", t("切换主题"));
  }
  const helpButton = byId("statusHelpBtn");
  if (helpButton) {
    helpButton.title = t("打开项目主页");
    helpButton.setAttribute("aria-label", t("打开项目主页"));
  }
  const mediaButtons = {
    playBtn: "播放/暂停",
    prevBtn: "上一个资源",
    nextBtn: "下一个资源",
    fullscreenBtn: "媒体全屏（双击画面）",
  };
  for (const [id, label] of Object.entries(mediaButtons)) {
    const button = helpers.byId(id);
    if (button) {
      button.title = t(label);
      button.setAttribute("aria-label", id === "fullscreenBtn" ? t("媒体全屏") : t(label));
    }
  }
  const fullscreenButton = helpers.byId("fullscreenBtn");
  if (fullscreenButton) {
    const isExit = /\bexit\b|退出/.test(String(fullscreenButton.textContent || "").toLowerCase());
    fullscreenButton.textContent = `[ ${t(isExit ? "退出" : "全屏")} ]`;
  }
  const seekSlider = helpers.byId("seekSlider");
  if (seekSlider) seekSlider.setAttribute("aria-label", t("播放进度"));
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
    canonicalUiText,
    translateVisibleText,
    optionLabel,
    setButtonContent,
    applyStaticLanguage,
    fallbackText: FALLBACK_UI_TEXT,
  };
})();
