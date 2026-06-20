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
let queueDensity = localStorage.getItem("webui_queue_density") || "comfortable";

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
  const itemSections = ["queue_items", "active_downloads", "completed_items", "failed_items"];
  if (itemSections.some(section => sections.has(section))) {
    rebuildCompatibilityState();
    renderCounts();
  }
  if (sections.has("queue_items") && currentPage === "queue") renderQueue();
  if (sections.has("active_downloads") && currentPage === "active") renderActive();
  if (sections.has("completed_items") && currentPage === "completed") renderCompleted();
  if (sections.has("failed_items") && currentPage === "failed") renderFailed();
  if (sections.has("log_items") && currentPage === "logs") renderLogs();
  if (sections.has("settings_snapshot") && currentPage === "settings") renderSettings();
  if ((sections.has("toolbox_items") || sections.has("toolbox_recent_items")) && currentPage === "toolbox") renderToolbox();
  if (sections.has("app_status")) renderStatus();
}

function applyFrontendDelta(delta) {
  if (!delta || typeof delta !== "object") return;
  const sections = delta.sections || {};
  const changed = Array.isArray(delta.changed_sections) ? delta.changed_sections.slice() : Object.keys(sections);
  if (delta.full && sections && Object.keys(sections).length) {
    frontendState = { ...frontendState, ...sections };
  } else {
    for (const [key, value] of Object.entries(sections)) frontendState[key] = value;
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
  for (const section of ["queue_items", "active_downloads", "completed_items", "failed_items"]) {
    frontendState[section] = (frontendState[section] || []).filter(item => !doomed.has(String(item.id)));
  }
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
  return true;
}


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
      { id: "c1", title: "川西雪山之旅 | 云海翻涌的一天", completed_at: "2026-04-12 18:24:35", duration: "00:00:24", resolution: "1920 x 1080", size: "24.6 MB", format: "MP4", local_path: "D:\\desktop\\视频\\川西雪山之旅_20260412.mp4", content_type: "video", actions: ["play", "open_directory", "delete"] },
    ],
    failed_items: [
      { id: "f1", title: "南岳山间的清晨", failed_at: "2026-04-12 07:31:12", reason: "需要登录", status: "失败", trace_id: "dy_failed_001", platform: "抖音", log_excerpt: ["请求视频链接", "接口返回需要登录", "任务标记为失败"], solutions: [{ title: "确认登录态", description: "检查平台认证状态。" }, { title: "重新获取链接", description: "登录后重新复制分享链接并重试。" }], actions: ["retry", "copy_diagnostics", "delete"] },
    ],
    log_items: [
      { time: "2026-04-12 18:24:35", level: "INFO", source: "下载器", thread: "download-worker-1", trace_id: "dy_log_001", message_summary: "开始下载视频", message: "开始下载视频", detail: "{}", stack: "" },
      { time: "2026-04-12 18:25:03", level: "ERROR", source: "下载器", thread: "download-worker-1", trace_id: "dy_log_002", message_summary: "下载失败：无法解析视频播放地址", message: "下载失败：无法解析视频播放地址", detail: "code: 1001", stack: "" },
    ],
    settings_snapshot: {
      "基础设置": { download_directory: "D:\\desktop\\视频", filename_template: "{platform}_{title}_{date}_{index}", open_after_download: true },
      "下载设置": { max_concurrent: 5, request_timeout: 30, max_retries: 3, resume_enabled: true },
      "平台设置": [{ id: "douyin", name: "抖音", auth_status: "已认证", default_count: 20, proxy: "系统代理" }],
      "播放设置": { default_player: "内置播放器", remember_position: true, autoplay_next: true },
      "日志设置": { retention_days: 30, level: "信息", auto_copy_trace_on_error: true },
      "外观设置": { theme: "light", accent: "#0d6efd", scale: "100%", font_size: "中" },
    },
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
  updatePlaceholder();
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
      if (data.message) appendLog(data.message);
      break;
    default:
      break;
  }
}

function renderAll() {
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
    byId("activeDetail").innerHTML = `<div class="active-detail-card"><h2>\u5f53\u524d\u4e0b\u8f7d</h2><p>\u6682\u65e0\u6b63\u5728\u4e0b\u8f7d\u7684\u4efb\u52a1</p></div>`;
    return;
  }
  const chunk = item.chunk_progress || {};
  const chunkPercent = Number(chunk.percent ?? item.progress ?? 0);
  const chunkText = `${chunkPercent}% (${chunk.completed || 0}/${chunk.total || 0})`;
  byId("activeDetail").innerHTML = `
    <div class="active-detail-card">
      <h2>\u5f53\u524d\u4e0b\u8f7d</h2>
      ${kvHtml([
        ["\u6807\u9898", item.title], ["\u5e73\u53f0", item.platform], ["\u4fdd\u5b58\u76ee\u5f55", item.save_dir || ""], ["\u8f93\u51fa\u6587\u4ef6\u540d", item.output_filename || ""],
        ["\u7ebf\u7a0b\u6570", item.thread_count], ["\u91cd\u8bd5\u6b21\u6570", item.retry_count], ["\u5199\u5165\u72b6\u6001", item.write_status], ["\u5408\u5e76\u72b6\u6001", item.merge_status],
        ["\u6765\u6e90\u94fe\u63a5", item.source_url], ["Trace ID", item.trace_id]
      ], new Set(["\u4fdd\u5b58\u76ee\u5f55", "\u8f93\u51fa\u6587\u4ef6\u540d", "\u6765\u6e90\u94fe\u63a5"]))}
      <div class="active-chunk">
        <div><strong>\u5206\u7247\u8fdb\u5ea6</strong><span>${esc(chunkText)}</span></div>
        ${progressHtml(chunkPercent)}
      </div>
      <h2>\u901f\u5ea6\u8d8b\u52bf\uff08\u8fd160\u79d2\uff09</h2>
      ${activeTrendHtml(item.speed_trend || [], item.speed || "0 B/s")}
    </div>
    <div class="active-events-card">
      <h2>\u5f53\u524d\u4efb\u52a1\u4e8b\u4ef6</h2>
      ${activeEventTimelineHtml(item.events || [])}
    </div>
  `;
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
  const height = 112;
  const left = 12;
  const right = width - 12;
  const top = 20;
  const bottom = height - 18;
  const usableWidth = width - 24;
  const usableHeight = bottom - top;
  const points = normalized.map((value, index) => {
    const x = left + (normalized.length <= 1 ? usableWidth : usableWidth * index / (normalized.length - 1));
    const y = bottom - usableHeight * value / max;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `
    <svg class="speed-trend" viewBox="0 0 ${width} ${height}" role="img" aria-label="\u901f\u5ea6\u8d8b\u52bf">
      <path d="M12 ${bottom}H248M12 ${top}V${bottom}" class="axis" />
      <path d="M12 74H248M12 50H248M12 26H248" class="grid" />
      <polyline points="${points}" class="line" />
      <text x="12" y="108">60\u79d2</text><text x="76" y="108">45\u79d2</text><text x="136" y="108">30\u79d2</text><text x="196" y="108">15\u79d2</text><text x="224" y="108">\u73b0\u5728</text>
      <text class="speed-label" x="${right}" y="16" text-anchor="end">${esc(speedLabel || "0 B/s")}</text>
    </svg>
  `;
}

function renderCompleted() {
  const items = frontendState.completed_items || [];
  if (!selected.completed && items.length) selected.completed = items[0].id;
  byId("completedSummary").textContent = `共 ${items.length} 个`;
  patchTableRows("completedBody", items, item => item.id, item => `
    <tr data-id="${escAttr(item.id)}" class="${selected.completed === item.id ? "selected" : ""}" onclick="selectCompleted('${escAttr(item.id)}')">
      <td title="${escAttr(item.title)}">${esc(item.title)}</td>
      <td>${esc(item.completed_at)}</td>
      <td>${esc(item.duration)}</td>
      <td>${esc(item.resolution)}</td>
      <td>${esc(item.size)}</td>
      <td>${esc(item.format)}</td>
      <td>${actionButton("play", "播放", `event.stopPropagation();playCompleted('${escAttr(item.id)}')`)}${actionButton("open_directory", "打开目录", `event.stopPropagation();openDirectory('${escAttr(item.id)}')`)}${actionButton("delete", "删除", `event.stopPropagation();frontendAction('delete_item',{id:'${escAttr(item.id)}'})`, true)}</td>
    </tr>
  `);
  renderCompletedDetail();
}

function selectCompleted(id) {
  selected.completed = id;
  selectedVideoId = id;
  renderCompleted();
}

function renderCompletedDetail() {
  const item = (frontendState.completed_items || []).find(row => row.id === selected.completed) || (frontendState.completed_items || [])[0];
  if (!item) {
    byId("completedDetail").innerHTML = "<h2>文件信息</h2><p>暂无已完成文件</p>";
    return;
  }
  const html = `
    <h2>文件信息</h2>
    ${kvHtml([["保存路径", item.local_path], ["完成时间", item.completed_at], ["时长", item.duration], ["分辨率", item.resolution], ["格式", item.format], ["大小", item.size]])}
    <h2>完成概览</h2>
    ${kvHtml([["已完成", `${(frontendState.completed_items || []).length} 个`], ["存储占用", item.size]])}
  `;
  setHtmlIfChanged("completedDetail", html);
}

function renderFailed() {
  const items = frontendState.failed_items || [];
  if (!selected.failed && items.length) selected.failed = items[0].id;
  patchTableRows("failedBody", items, item => item.id, item => `
    <tr data-id="${escAttr(item.id)}" class="${selected.failed === item.id ? "selected" : ""}" onclick="selectFailed('${escAttr(item.id)}')">
      <td title="${escAttr(item.title)}">${esc(item.title)}</td>
      <td>${esc(item.failed_at)}</td>
      <td>${esc(item.reason)}</td>
      <td>${esc(item.status)}</td>
      <td>${actionButton("retry", "重试", `event.stopPropagation();frontendAction('retry_failed',{id:'${escAttr(item.id)}'})`)}${actionButton("copy_diagnostics", "复制诊断", `event.stopPropagation();copyDiagnostics('${escAttr(item.id)}')`)}${actionButton("delete", "删除", `event.stopPropagation();frontendAction('delete_item',{id:'${escAttr(item.id)}'})`, true)}</td>
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
    return;
  }
  byId("failedDetail").innerHTML = `
    <h2>错误详情</h2>
    ${kvHtml([["标题", item.title], ["失败时间", item.failed_at], ["失败原因", item.reason], ["平台", item.platform], ["Trace ID", item.trace_id]])}
    <h2>Trace / 日志片段</h2>
    <div class="log-snippet">${esc((item.log_excerpt || []).join("\n"))}</div>
    <h2>可能的解决方案</h2>
    <div class="event-list">${esc((item.solutions || []).map(solution => `${solution.title}: ${solution.description}`).join("\n"))}</div>
  `;
}

function renderLogs() {
  const items = frontendState.log_items || [];
  if (!selected.log && items.length) selected.log = String(items.length - 1);
  patchTableRows("logBody", items, (item, index) => `${index}:${item.time || ""}:${item.trace_id || ""}`, (item, index) => `
    <tr class="${selected.log === String(index) ? "selected" : ""}" onclick="selectLog('${index}')">
      <td>${esc(item.time)}</td>
      <td>${esc(item.level)}</td>
      <td>${esc(item.source)}</td>
      <td>${esc(item.trace_id || "")}</td>
      <td title="${escAttr(item.message_summary || "")}">${esc(item.message_summary || "")}</td>
    </tr>
  `);
  renderLogDetail();
}

function selectLog(index) {
  selected.log = String(index);
  renderLogs();
}

function renderLogDetail() {
  const item = (frontendState.log_items || [])[Number(selected.log)] || (frontendState.log_items || [])[0];
  if (!item) {
    byId("logDetail").innerHTML = "<h2>日志详情</h2><p>暂无日志</p>";
    return;
  }
  byId("logDetail").innerHTML = `
    <h2>日志详情</h2>
    ${kvHtml([["时间", item.time], ["级别", item.level], ["来源", item.source], ["线程", item.thread || ""], ["Trace ID", item.trace_id || ""], ["消息", item.message || item.message_summary]])}
    <h2>详细信息</h2>
    <div class="log-snippet">${esc(item.detail || "")}</div>
    <h2>堆栈跟踪</h2>
    <div class="log-snippet">${esc(item.stack || "无")}</div>
  `;
}

function renderSettings() {
  const settings = frontendState.settings_snapshot || {};
  const html = Object.entries(settings).map(([group, value]) => `
    <article class="setting-card">
      <h2>${esc(group)}</h2>
      ${settingsControls(group, value)}
    </article>
  `).join("");
  if (renderSignatures.settingsGrid && renderSignatures.settingsGrid !== html && hasFocusedDescendant("settingsGrid")) return;
  setHtmlIfChanged("settingsGrid", html);
}

function settingsControls(group, value) {
  if (group === "基础设置") {
    return [
      settingInput("下载目录", "download_directory", value && value.download_directory),
      settingInput("文件命名", "filename_template", value && value.filename_template),
      settingSelect("默认打开方式", "default_open_mode", value && value.default_open_mode, ["系统默认播放器", "内置播放器", "打开目录"]),
      settingCheckbox("下载后自动打开", "open_after_download", !!(value && value.open_after_download)),
      `<button class="btn setting-action" type="button" onclick="frontendAction('register_file_associations',{include_video:true,include_image:false})">绑定默认打开方式</button>`,
    ].join("");
  }
  if (group === "下载设置") {
    return [
      settingNumber("并发数", "max_concurrent", value && value.max_concurrent, 1, 16),
      settingNumber("请求超时", "request_timeout", value && value.request_timeout, 10, 300),
      settingNumber("最大重试", "max_retries", value && value.max_retries, 0, 10),
      settingNumber("速度限制 KB/s", "speed_limit_kb", value && value.speed_limit_kb, 0, 999999),
      settingCheckbox("断点续传", "resume_enabled", !!(value && value.resume_enabled)),
      settingCheckbox("仅下载视频", "video_only", !!(value && value.video_only)),
    ].join("");
  }
  if (group === "平台设置") {
    return (Array.isArray(value) ? value : []).map(row => `
      <div class="setting-row setting-platform">
        <span>${esc(row.name || row.id || "平台")}</span>
        <select><option ${row.auth_status === "已认证" ? "selected" : ""}>已认证</option><option ${row.auth_status !== "已认证" ? "selected" : ""}>未认证</option></select>
        <input type="number" min="1" max="9999" value="${escAttr(row.default_count || 20)}" />
        <input value="${escAttr(row.proxy || "系统代理")}" title="${escAttr(row.proxy || "系统代理")}" />
      </div>
    `).join("");
  }
  if (group === "播放设置") {
    return [
      settingSelect("默认播放器", "default_player", value && value.default_player, ["内置播放器", "系统默认播放器"]),
      settingCheckbox("记住播放位置", "remember_position", !!(value && value.remember_position)),
      settingCheckbox("硬件加速", "hardware_acceleration", !!(value && value.hardware_acceleration)),
      settingCheckbox("自动播放下一项", "autoplay_next", !!(value && value.autoplay_next)),
      settingCheckbox("手动切换图片", "manual_image_switch", !!(value && value.manual_image_switch)),
    ].join("");
  }
  if (group === "日志设置") {
    return [
      settingNumber("保留天数", "retention_days", value && value.retention_days, 1, 365),
      settingSelect("日志级别", "level", value && value.level, ["调试", "信息", "警告", "错误"]),
      settingCheckbox("错误时自动复制 Trace", "auto_copy_trace_on_error", !!(value && value.auto_copy_trace_on_error)),
      settingCheckbox("启动时清理旧日志", "cleanup_old_logs_on_start", !!(value && value.cleanup_old_logs_on_start)),
    ].join("");
  }
  if (group === "外观设置") {
    return [
      settingCheckbox("跟随系统", "follow_system", !!(value && value.follow_system)),
      settingSelect("主题", "theme", value && value.theme, ["light", "dark"]),
      settingInput("强调色", "accent", value && value.accent),
      settingSelect("界面缩放", "scale", value && value.scale, ["90%", "100%", "110%", "125%"]),
      settingSelect("字体大小", "font_size", value && value.font_size, ["小", "中", "大"]),
    ].join("");
  }
  return "";
}

function settingInput(label, key, value) {
  return `<label class="setting-row"><span>${esc(label)}</span><input data-setting="${escAttr(key)}" value="${escAttr(value || "")}" title="${escAttr(value || "")}" /></label>`;
}

function settingNumber(label, key, value, min, max) {
  return `<label class="setting-row"><span>${esc(label)}</span><input data-setting="${escAttr(key)}" type="number" min="${min}" max="${max}" value="${escAttr(value ?? min)}" /></label>`;
}

function settingCheckbox(label, key, checked) {
  return `<label class="setting-row"><span>${esc(label)}</span><input data-setting="${escAttr(key)}" type="checkbox" ${checked ? "checked" : ""} /></label>`;
}

function settingSelect(label, key, value, options) {
  return `<label class="setting-row"><span>${esc(label)}</span><select data-setting="${escAttr(key)}">${options.map(option => `<option ${String(value || options[0]) === option ? "selected" : ""}>${esc(option)}</option>`).join("")}</select></label>`;
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
  byId("statusState").textContent = status.running_state || "空闲中";
  byId("statusDownload").textContent = `下载速度：${status.download_speed || "0 B/s"}`;
  byId("statusUpload").textContent = `上传速度：${status.upload_speed || "0 B/s"}`;
  byId("statusCompleted").textContent = `已完成：${status.completed_count || 0}`;
  byId("statusFailed").textContent = `失败：${status.failed_count || 0}`;
  byId("statusVersion").textContent = status.version || "v1.0.0";
}

function switchPage(pageId) {
  currentPage = pageId;
  document.querySelectorAll(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === pageId));
  document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === pageId));
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
  return `<div class="kv">${pairs.map(([key, value]) => {
    const keyText = String(key);
    const shouldWrap = wrapKeys.has(keyText);
    const valueClass = shouldWrap ? "kv-value smart-wrap" : "kv-value";
    const valueHtml = shouldWrap ? smartWrapText(value) : esc(String(value ?? ""));
    return `<span>${esc(keyText)}</span><span class="${valueClass}">${valueHtml}</span>`;
  }).join("")}</div>`;
}

function startCrawl() {
  const keyword = byId("searchInput").value.trim();
  if (!keyword) {
    appendLog("请输入主页链接、分享链接或合集链接");
    return;
  }
  const source = byId("sourceSelect").value || "douyin";
  const count = Number(byId("videoCountSelect").value) || 20;
  const config = { max_items: count };
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

function frontendAction(action, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    sendWS("frontend_action", { action, payload });
    return;
  }
  fetch("/api/frontend/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, payload }),
  }).then(() => fetchFrontendDelta()).catch(error => appendLog(error.message || String(error)));
}

function playCompleted(id) {
  selectCompleted(id);
  const item = (frontendState.completed_items || []).find(row => row.id === id);
  if (!item) return;
  currentPlayingId = id;
  const video = byId("videoPlayer");
  const placeholder = byId("previewArea");
  if (item.local_path) {
    video.src = `/api/media/${encodeURIComponent(id)}`;
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
    appendLog("诊断信息已复制");
  });
}

function appendLog(message) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);
  frontendState.log_items = frontendState.log_items || [];
  frontendState.log_items.push({ time: now, level: "INFO", source: "WebUI", thread: "browser", trace_id: "", message_summary: String(message), message: String(message), detail: "", stack: "" });
  const legacyPanel = byId("logPanel");
  if (legacyPanel) {
    const line = document.createElement("div");
    line.textContent = String(message);
    legacyPanel.appendChild(line);
  }
  renderLogs();
}

function onChangeDirClicked() {
  byId("dirModal").style.display = "flex";
  byId("dirInput").value = (((frontendState.settings_snapshot || {})["基础设置"] || {}).download_directory || "");
  byId("dirList").textContent = "输入或确认保存目录";
}

function confirmDirDialog() {
  const directory = byId("dirInput").value.trim();
  if (directory) frontendAction("change_directory", { directory });
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
  localStorage.setItem("cached_dark_theme", String(dark));
  sendWS("change_theme", { dark_theme: dark });
}

function restoreTheme() {
  const cached = localStorage.getItem("cached_dark_theme");
  const dark = cached === "true";
  applyTheme(dark);
}

function applyTheme(dark) {
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  byId("themeBtn").textContent = dark ? "☀" : "☾";
}

function cacheSource() {
  localStorage.setItem("cached_last_source", byId("sourceSelect").value);
  updatePlaceholder();
  sendWS("change_source", { source: byId("sourceSelect").value });
}

function updatePlaceholder() {
  const source = byId("sourceSelect").value;
  const platform = platforms.find(item => item.id === source);
  byId("searchInput").placeholder = platform && platform.search_placeholder ? platform.search_placeholder : "输入：主页链接、分享链接或合集链接...";
}

function resizePreviewImage() {}
function closePreview() {
  const video = byId("videoPlayer");
  video.pause();
  video.removeAttribute("src");
  video.style.display = "none";
  byId("previewArea").style.display = "flex";
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
  player.onended = () => {
    if (currentPlayingId === sourceId) autoplayNextPreview();
  };
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
  isFullscreenMode = !isFullscreenMode;
  document.body.classList.toggle("is-fullscreen", isFullscreenMode);
}
function fmtTime(seconds) {
  const value = Number(seconds) || 0;
  const min = Math.floor(value / 60);
  const sec = Math.floor(value % 60);
  return `${String(min).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
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
    if (isFullscreenMode) toggleFullscreen();
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
