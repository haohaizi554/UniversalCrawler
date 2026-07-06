let frontendState = buildMockState();
let currentPage = "queue";
let ws = null;
let wsReconnectTimer = null;
let pageIsUnloading = false;
let platforms = [];
let selected = {
  active: "",
  completed: "",
  failed: "",
  log: "",
  tool: "link_parser",
};
let queuePage = 1;
let queuePageSize = normalizeTablePageSize(localStorage.getItem("webui_queue_page_size") || 20);
let completedPage = 1;
let completedPageSize = normalizeTablePageSize(localStorage.getItem("webui_completed_page_size") || 20);
let logPage = 1;
let logPageSize = normalizeLogPageSize(localStorage.getItem("webui_log_page_size") || 20);
const LOG_RENDER_ROW_BUDGET = 300;
const LOG_QUERY_WORKER_THRESHOLD = 80;
let logQueryWorker = null;
let logQueryWorkerAvailable = typeof Worker !== "undefined";
let logQuerySequence = 0;
let logQueryState = {
  signature: "",
  result: null,
  pending: false,
};
window.__ucrawlFrontendStateLoaded = false;
window.__ucrawlFrontendStateSettled = false;

function closeLogQueryWorker() {
  if (!logQueryWorker) return;
  try {
    logQueryWorker.terminate();
  } catch (_error) {
    // Browser teardown is best-effort; stale workers must not block navigation.
  }
  logQueryWorker = null;
  logQueryState.pending = false;
}

function cleanupPageResources() {
  pageIsUnloading = true;
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  if (ws) {
    const socket = ws;
    ws = null;
    try {
      socket.onclose = null;
      socket.close();
    } catch (_error) {
      // The page is leaving; close failures are intentionally ignored.
    }
  }
  closeLogQueryWorker();
}

window.addEventListener("pagehide", cleanupPageResources, { once: true });
window.addEventListener("beforeunload", cleanupPageResources, { once: true });

function pad2(value) {
  return String(value).padStart(2, "0");
}

function formatLocalDateTime(date = new Date()) {
  const value = date instanceof Date ? date : new Date(date);
  return [
    `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`,
    `${pad2(value.getHours())}:${pad2(value.getMinutes())}:${pad2(value.getSeconds())}`,
  ].join(" ");
}

function normalizeLogPageSize(value) {
  const numeric = Number(value);
  if (numeric === 0) return 0;
  return [20, 50, 100].includes(numeric) ? numeric : 20;
}

function normalizeTablePageSize(value) {
  const numeric = Number(value);
  return [20, 50, 100].includes(numeric) ? numeric : 20;
}

let logFilters = {
  category: "all",
  level: "all",
  time: "30m",
  platform: "all",
  trace: "",
  keyword: "",
};
let currentSettingsGroup = localStorage.getItem("webui_settings_group") || "基础设置";
let imageAutoAdvanceTimer = null;
let selectionItems = [];
let dirCurrentPath = "";
let dirSelectedPath = "";
let dirParentPath = "";

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

const SETTINGS_GROUP_HINTS_FALLBACK = {
  "基础设置": "路径支持粘贴和选择，命名规则使用预设模板，避免非法文件名。",
  "下载设置": "并发越高不一定越快，建议根据网络和磁盘性能调整。",
  "平台设置": "认证状态自动检测；代理仅对需要的平台开放。",
  "播放设置": "播放设置只影响本地预览，不影响下载文件。",
  "日志设置": "UI 显示数量只影响日志中心显示，不影响日志文件本身。",
  "外观设置": "外观设置会即时生效，并保存到本地配置。",
};

const SETTINGS_GROUP_ICONS = {
  "基础设置": "action_open_directory.png",
  "下载设置": "action_download.png",
  "平台设置": "platform_web.png",
  "播放设置": "action_play.png",
  "日志设置": "nav_log_center.png",
  "外观设置": "action_theme_palette.png",
};

function normalizeSettingsGroupName(group) {
  const canonical = canonicalUiText(group);
  return SETTINGS_GROUP_ORDER_FALLBACK.includes(canonical) ? canonical : String(group || "");
}

function settingsContract() {
  const contract = frontendState.settings_contract || {};
  const order = Array.isArray(contract.group_order) ? contract.group_order.filter(Boolean) : [];
  return {
    order,
    descriptions: contract.group_descriptions || {},
    hints: contract.group_hints || {},
  };
}

function logSettingsSnapshot() {
  const snapshot = frontendState.settings_snapshot || {};
  return snapshot["日志设置"] || snapshot["鏃ュ織璁剧疆"] || {};
}

function uiLogDisplayLimit() {
  const raw = Number(logSettingsSnapshot().ui_log_max_display_count || 300);
  const value = Number.isFinite(raw) ? Math.floor(raw) : 300;
  return [100, 300, 500].includes(value) ? value : 300;
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

function i18nService() {
  return window.UcpI18n || null;
}

function configureI18nHelpers() {
  const service = i18nService();
  if (!service) return null;
  service.configure({
    getState: () => frontendState,
    byId,
    esc,
    renderCurrentPage,
    updatePlaceholder,
    renderStatus,
    syncAllCustomSelects,
  });
  return service;
}

async function loadUiTextCatalogs() {
  const service = configureI18nHelpers();
  if (service) return service.loadUiTextCatalogs();
}

function currentLanguage() {
  const service = i18nService();
  return service ? service.currentLanguage() : "zh-CN";
}

function t(text) {
  const service = i18nService();
  return service ? service.t(text) : String(text || "");
}

function translateUiText(text) {
  const service = i18nService();
  return service ? service.translateUiText(text) : String(text || "");
}

function translateUiCore(text, lang = currentLanguage()) {
  const service = i18nService();
  return service ? service.translateUiCore(text, lang) : String(text || "");
}

function canonicalUiText(text) {
  const service = i18nService();
  return service && typeof service.canonicalUiText === "function"
    ? service.canonicalUiText(text)
    : String(text || "");
}

function isAllLogFilterText(value) {
  const text = String(value || "").trim().toLowerCase();
  return !text || text === "all" || text === "全部" || text === "所有";
}

function normalizeLogFilterValue(key, value) {
  const raw = String(value || "").trim();
  const canonical = canonicalUiText(raw);
  if (key === "level") {
    if (isAllLogFilterText(raw) || isAllLogFilterText(canonical)) return "all";
    return raw.toUpperCase();
  }
  if (key === "time") {
    if (isAllLogFilterText(raw) || isAllLogFilterText(canonical)) return "all";
    const aliases = {
      "30m": "30m",
      "1h": "1h",
      "24h": "24h",
      "近 30 分钟": "30m",
      "近 1 小时": "1h",
      "近 24 小时": "24h",
      "Last 30 minutes": "30m",
      "Last 30 min": "30m",
      "Last 1 hour": "1h",
      "Last 24 hours": "24h",
    };
    return aliases[raw] || aliases[canonical] || raw || "30m";
  }
  if (key === "platform") {
    if (isAllLogFilterText(raw) || isAllLogFilterText(canonical)) return "all";
    return canonical || raw;
  }
  return raw;
}

function uiTextWithDetail(label, detail = "") {
  const base = t(label);
  const extra = String(detail || "").trim();
  if (!extra) return base;
  return `${base}${currentLanguage() === "en-US" ? ": " : "："}${extra}`;
}

function appendUiLog(label, detail = "", prefix = "") {
  appendLog(`${prefix}${uiTextWithDetail(label, detail)}`);
}

function translateVisibleText(root = document.body) {
  const service = i18nService();
  if (service) service.translateVisibleText(root);
}

function optionLabel(label) {
  const service = i18nService();
  return service ? service.optionLabel(label) : String(label || "");
}

function setButtonContent(buttonId, label) {
  const service = i18nService();
  if (service) service.setButtonContent(buttonId, label);
}

function applyStaticLanguage() {
  const service = configureI18nHelpers();
  if (service) service.applyStaticLanguage();
}

configureI18nHelpers();

// Compatibility globals used by a few older browser tests.
let videos = {};
let videoOrder = [];
let selectedVideoId = null;
let currentPlayingId = null;
let isFullscreenMode = false;
let crawlRunning = false;
let previewRequestToken = 0;

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

function updateIconManifest(manifest) {
  if (!manifest || typeof manifest !== "object") return;
  iconManifest = {
    ...iconManifest,
    ...manifest,
    actions: {
      ...ACTION_ICON_FILES,
      ...((iconManifest && iconManifest.actions) || {}),
      ...((manifest && manifest.actions) || {}),
    },
  };
  configureTaskRenderHelpers();
  updateMediaControls();
}

let renderSignatures = {};
let frontendSectionSignatures = {};
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
  if (sections.has("settings_snapshot")) updatePlaceholder();
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
    appendUiLog("增量状态基线不连续，正在重新同步...");
    fetchFrontendState();
    return;
  }
  const sections = delta.sections || {};
  const requestedChanged = Array.isArray(delta.changed_sections) ? delta.changed_sections.slice() : Object.keys(sections);
  const changed = [];
  if (delta.full && sections && Object.keys(sections).length) {
    frontendState = { ...frontendState, ...sections };
    rememberFrontendSectionSignatures(Object.keys(sections));
    changed.push(...requestedChanged);
  } else {
    for (const [key, value] of Object.entries(sections)) {
      if (frontendSectionSignatures[key] === undefined) {
        frontendSectionSignatures[key] = frontendSectionSignature(frontendState[key]);
      }
      const nextSignature = frontendSectionSignature(value);
      frontendState[key] = value;
      if (frontendSectionSignatures[key] !== nextSignature) changed.push(key);
      frontendSectionSignatures[key] = nextSignature;
    }
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
  if (changed.length) scheduleRenderSections(changed);
}

function frontendSectionSignature(value) {
  try {
    return JSON.stringify(value === undefined ? null : value);
  } catch (error) {
    return String(value);
  }
}

function rememberFrontendSectionSignatures(keys) {
  for (const key of keys || []) {
    frontendSectionSignatures[key] = frontendSectionSignature(frontendState[key]);
  }
}

function removeDeletedFromFrontendState(ids) {
  const doomed = new Set(ids.map(id => String(id)));
  const playingId = String(currentPlayingId || "");
  const removesPlayingItem = !!playingId && doomed.has(playingId);
  for (const id of doomed) removePlaybackPosition(id);
  if (removesPlayingItem) closePreview();
  for (const section of ["queue_items", "active_downloads", "completed_items", "failed_items"]) {
    frontendState[section] = (frontendState[section] || []).filter(item => !doomed.has(String(item.id)));
    frontendSectionSignatures[section] = frontendSectionSignature(frontendState[section]);
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
    appendUiLog("加载增量状态失败", error.message || error);
  }
}

function setHtmlIfChanged(id, html, key = id) {
  if (renderSignatures[key] === html) return false;
  byId(id).innerHTML = html;
  renderSignatures[key] = html;
  queueMicrotask(() => enhanceSelects(byId(id)));
  return true;
}

function configureCustomSelectHelpers() {
  if (window.UcpCustomSelect) window.UcpCustomSelect.configure({ translate: translateUiText, canonical: canonicalUiText, esc, escAttr });
}

function configureMediaDisplayHelpers() {
  if (window.UcpMediaDisplay) window.UcpMediaDisplay.configure({ esc, translate: translateUiText });
}

function configureSettingsRenderHelpers() {
  if (window.UcpSettingsRender) {
    window.UcpSettingsRender.configure({
      esc,
      escAttr,
      t,
      optionLabel,
      countOptionLabel,
      platformIconUrl: (platformId, iconFile) => {
        const id = String(platformId || "").toLowerCase();
        return iconFileUrl(iconFile || (iconManifest.platforms || {})[id] || "platform_web.png");
      },
    });
  }
}
function configureTaskRenderHelpers() {
  if (window.UcpTaskRender) {
    window.UcpTaskRender.configure({
      esc,
      escAttr,
      t,
      getIconManifest: () => iconManifest,
      activeTrendHtml,
      activeEventTimelineHtml,
      displayMetadataValue,
      basenameFromPath,
      dirnameFromPath,
    });
  }
}

function enhanceSelects(root = document) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.enhance(root);
}

function syncAllCustomSelects(root = document) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.syncAll(root);
}

function syncCustomSelectForSelect(select) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.syncForSelect(select);
}

function renderCustomSelectMenu(select, menu) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.renderMenu(select, menu);
}

function toggleCustomSelect(wrapper) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.toggle(wrapper);
}

function closeCustomSelect(wrapper = undefined, focusButton = false) {
  if (window.UcpCustomSelect) window.UcpCustomSelect.close(wrapper, focusButton);
}

function chooseCustomSelectOption(select, value) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.choose(select, value);
}

function handleCustomSelectKeydown(event, wrapper) {
  configureCustomSelectHelpers();
  if (window.UcpCustomSelect) window.UcpCustomSelect.handleKeydown(event, wrapper);
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
  loadUiTextCatalogs();
  renderAll();
  loadPlatforms();
  fetchFrontendState();
  connectWS();
  installDirDialogHandlers();
  installMediaControlHandlers();
  updateMediaControls();
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
      { id: "f1", title: "南岳山间的清晨", failed_at: "2026-04-12 07:31:12", reason: "需要登录", status: "失败", trace_id: "dy_failed_001", platform: "抖音", log_excerpt: ["请求视频链接", "接口返回需要登录", "任务标记为失败"], solutions: [{ title: "确认登录态", description: "检查平台认证状态。" }, { title: "重新获取链接", description: "登录后重新复制分享链接并重试。" }], actions: ["copy_diagnostics", "delete"] },
    ],
    log_items: [
      { time: "2026-04-12 18:24:35", level: "INFO", source: "下载器", thread: "download-worker-1", trace_id: "dy_log_001", message_summary: "开始下载视频", message: "开始下载视频", detail: "{}", stack: "" },
      { time: "2026-04-12 18:25:03", level: "ERROR", source: "下载器", thread: "download-worker-1", trace_id: "dy_log_002", message_summary: "下载失败：无法解析视频播放地址", message: "下载失败：无法解析视频播放地址", detail: "code: 1001", stack: "" },
    ],
    settings_snapshot: {
      "\u57fa\u7840\u8bbe\u7f6e": { download_directory: "D:\\desktop\\Videos", filename_template: "current", filename_template_label: "\u9ed8\u8ba4", open_after_download: false, default_open_mode: "builtin_player", default_open_mode_label: "\u5185\u7f6e\u64ad\u653e\u5668", _options: { filename_template: [{ value: "current", label: "\u9ed8\u8ba4" }, { value: "{title}", label: "\u6807\u9898" }], default_open_mode: [{ value: "builtin_player", label: "\u5185\u7f6e\u64ad\u653e\u5668" }, { value: "system_default", label: "\u7cfb\u7edf\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f" }] } },
      "下载设置": {
        max_concurrent: 3,
        request_timeout: 30,
        max_retries: 3,
        resume_enabled: true,
        speed_limit_kb: 0,
        video_only: false,
        image_respects_concurrency: false,
        _options: {
          max_concurrent: [{ value: "1", label: "1" }, { value: "3", label: "3（推荐）" }, { value: "5", label: "5" }],
        },
      },
      "平台设置": [{ id: "douyin", name: "抖音", auth_status: "已认证", default_count: 20, count_config_key: "max_items", count_unit: "videos", count_editable: true, count_options: countFallbackOptions("videos"), default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒" }], proxy: "系统代理", proxy_config_key: "", proxy_editable: false }],
      "播放设置": {
        default_player: "builtin_player",
        default_player_label: "内置播放器",
        remember_position: true,
        autoplay_next: true,
        manual_image_switch: false,
        image_auto_advance_interval_seconds: 5,
        _options: {
          default_player: [{ value: "builtin_player", label: "内置播放器" }, { value: "system_default", label: "系统默认播放器" }],
          image_auto_advance_interval_seconds: [{ value: "1", label: "1 秒" }, { value: "3", label: "3 秒" }, { value: "5", label: "5 秒（推荐）" }, { value: "10", label: "10 秒" }],
        },
      },
      "日志设置": { retention_days: 1, ui_log_max_display_count: 300, auto_copy_trace_on_error: true, _options: { retention_days: [{ value: "1", label: "1 天（推荐）" }, { value: "3", label: "3 天" }, { value: "5", label: "5 天" }, { value: "7", label: "7 天" }], ui_log_max_display_count: [{ value: "100", label: "100 条" }, { value: "300", label: "300 条（推荐）" }, { value: "500", label: "500 条" }] } },
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
      { id: "link_parser", title: "链接解析", summary: "解析网页或文本中的链接，提取视频、图片等资源地址", input_example: "https://www.douyin.com/user/MS4wLjABAAAA...", output_example: "解析出视频、图片、作者主页等可下载资源地址", icon_file: "tool_link_parser.png" },
      { id: "batch_rename", title: "批量重命名", summary: "按规则、序号和预览结果批量重命名本地文件", input_example: "D:\\Videos\\*.mp4 + {platform}_{title}_{index}", output_example: "生成可预览、可回滚的批量重命名方案", icon_file: "tool_batch_rename.png" },
      { id: "cover_extract", title: "封面提取", summary: "从视频文件中提取封面图片，支持单个或批量提取", input_example: "选择本地视频文件或下载完成列表", output_example: "导出 JPG/PNG 封面图并写入文件信息", icon_file: "tool_cover_extract.png" },
      { id: "video_to_audio", title: "视频转音频", summary: "将视频文件转换为音频，支持多种格式和质量设置", input_example: "MP4/MKV/WebM 视频文件", output_example: "输出 MP3/AAC/WAV 音频文件", icon_file: "tool_video_to_audio.png" },
      { id: "dedupe_scan", title: "本地去重扫描", summary: "扫描并查找重复文件，支持按内容或文件名去重", input_example: "选择下载目录或任意本地目录", output_example: "生成重复文件分组和可清理建议", icon_file: "tool_duplicate_scan.png" },
      { id: "metadata_viewer", title: "元数据查看", summary: "查看视频、音频和图片文件的详细元数据", input_example: "本地视频、音频、图片文件", output_example: "展示编码、分辨率、时长、码率和容器信息", icon_file: "tool_metadata_view.png" },
      { id: "format_convert", title: "格式转换", summary: "转换视频、音频和图片文件格式", input_example: "选择源文件和目标格式", output_example: "输出转换后的媒体文件并保留来源记录", icon_file: "tool_format_convert.png" },
      { id: "file_verify", title: "文件校验", summary: "计算并校验文件哈希值，支持 MD5、SHA1、SHA256", input_example: "选择一个或多个本地文件", output_example: "输出 MD5、SHA1、SHA256 校验值", icon_file: "tool_file_verify.png" },
    ],
    toolbox_recent_items: [
      { id: "link_parser", title: "链接解析", last_used: "今天 18:24" },
      { id: "video_to_audio", title: "视频转音频", last_used: "今天 17:35" },
      { id: "metadata_viewer", title: "元数据查看", last_used: "今天 14:10" },
    ],
    app_status: { running_state: "空闲中", download_speed: "0 B/s", completed_count: 128, failed_count: 7, version: "v3.6.17" },
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
      window.__ucrawlFrontendStateLoaded = true;
      renderAll();
    }
  } catch (error) {
    appendUiLog("加载状态失败", error.message || error);
  } finally {
    window.__ucrawlFrontendStateSettled = true;
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
  select.innerHTML = platforms.map(platform => {
    const id = String(platform.id || "");
    const iconFile = platform.icon_file || (iconManifest.platforms || {})[id.toLowerCase()] || "platform_web.png";
    return `<option value="${escAttr(id)}" data-icon="${escAttr(iconFileUrl(iconFile))}" data-original-label="${escAttr(platform.name)}">${esc(platform.name)}</option>`;
  }).join("");
  if (cached && platforms.some(platform => String(platform.id) === cached)) select.value = cached;
  if (!select.value && platforms.length) select.value = String(platforms[0].id || "");
  enhanceSelects(select.parentElement || document);
  syncCustomSelectForSelect(select);
  updatePlaceholder();
  setCrawlUiState(crawlRunning);
}

function platformSettingsRow(platformId) {
  const rows = (frontendState.settings_snapshot || {})["平台设置"] || [];
  return Array.isArray(rows) ? rows.find(row => row.id === platformId) || null : null;
}

function platformLimitService() { return window.UcpPlatformLimits || null; }
function countFallbackOptions(unit) { return platformLimitService()?.countFallbackOptions(unit) || []; }
function countOptionLabel(value, unit) { return platformLimitService()?.countOptionLabel(value, unit) || String(value || ""); }
function countLabelText(unit) { return platformLimitService()?.countLabelText(unit) || "\u89c6\u9891\u6570:"; }
function defaultCountForUnit(unit) { return platformLimitService()?.defaultCount(unit) || (unit === "pages" ? "1" : "20"); }
function configureTopCountForSource(sourceId) {
  const row = platformSettingsRow(sourceId);
  const unit = row && row.count_unit ? row.count_unit : "videos";
  const select = byId("videoCountSelect");
  const label = document.querySelector(".count-label");
  if (!select) return;

  let options = ((row && row.count_options) || countFallbackOptions(unit)).map(normalizeSettingOption).filter(option => option.value);
  const currentValue = String((row && row.default_count) || defaultCountForUnit(unit));
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
  setCrawlUiState(crawlRunning);
}

function connectWS() {
  if (pageIsUnloading) return;
  if (ws && [WebSocket.CONNECTING, WebSocket.OPEN].includes(ws.readyState)) return;
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  try {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws`);
    ws = socket;
    socket.onmessage = event => handleServerMessage(JSON.parse(event.data));
    socket.onclose = () => {
      if (ws === socket) ws = null;
      if (pageIsUnloading) return;
      wsReconnectTimer = setTimeout(() => {
        wsReconnectTimer = null;
        connectWS();
      }, 2000);
    };
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
        setCrawlUiState(data.is_crawling);
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
      setCrawlUiState(!!data.is_running);
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
      if (data.message) appendLog(translateUiText(data.message));
      break;
    default:
      break;
  }
}

function renderAll() {
  syncAppearanceFromSettings();
  trimFrontendLogItems();
  updatePlaceholder();
  rebuildCompatibilityState();
  renderCounts();
  renderCurrentPage();
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

function taskRenderService() {
  configureTaskRenderHelpers();
  return window.UcpTaskRender || null;
}
function renderCounts() {
  const status = frontendState.app_status || {};
  const countFor = (key, section) => {
    if (Object.prototype.hasOwnProperty.call(status, key)) return Number(status[key] || 0);
    return (frontendState[section] || []).length;
  };
  byId("countQueue").textContent = String(countFor("queue_count", "queue_items"));
  byId("countActive").textContent = String(countFor("active_count", "active_downloads"));
  byId("countCompleted").textContent = String(countFor("completed_count", "completed_items"));
  byId("countFailed").textContent = String(countFor("failed_count", "failed_items"));
}

function reconcileSelectedTask(key, items) {
  const rows = Array.isArray(items) ? items : [];
  const current = String((selected && selected[key]) || "");
  const currentStillVisible = current && rows.some(item => String(item.id || "") === current);
  if (currentStillVisible) return current;
  selected[key] = rows.length ? String(rows[0].id || "") : "";
  return selected[key];
}

function selectedTaskItem(key, items) {
  const rows = Array.isArray(items) ? items : [];
  const id = String((selected && selected[key]) || "");
  return rows.find(row => String(row.id || "") === id) || null;
}

function renderQueue() {
  byId("queuePath").textContent = (((frontendState.settings_snapshot || {})["基础设置"] || {}).download_directory || "");
  const allItems = frontendState.queue_items || [];
  const totalPages = Math.max(1, Math.ceil(allItems.length / queuePageSize));
  queuePage = Math.max(1, Math.min(queuePage, totalPages));
  const start = (queuePage - 1) * queuePageSize;
  const items = allItems.slice(start, start + queuePageSize);
  patchTableRows("queueBody", items, item => item.id, item => taskRenderService().queueRow(item));
  byId("queueTotal").textContent = translateUiText(`\u5171 ${allItems.length} \u9879`);
  byId("queuePageNow").textContent = String(queuePage);
  byId("queueTotalPages").textContent = String(totalPages);
  byId("queuePageSize").value = String(queuePageSize);
  syncCustomSelectForSelect(byId("queuePageSize"));
  byId("queuePrevPage").disabled = queuePage <= 1;
  byId("queueNextPage").disabled = queuePage >= totalPages;
  setHtmlIfChanged("queueEvents", taskRenderService().queueEventsHtml(frontendState.queue_items || []));
}

function queueTitleHtml(item) {
  return taskRenderService().queueTitleHtml(item);
}

function platformHtml(platform, platformId) {
  return taskRenderService().platformHtml(platform, platformId);
}

function platformIcon(platformId) {
  return taskRenderService().platformIcon(platformId);
}

function queueStatusHtml(status) {
  return taskRenderService().queueStatusHtml(status);
}
function restoreQueueControls() {
  document.body.classList.remove("queue-compact");
}

function setQueuePage(delta) {
  queuePage += Number(delta) || 0;
  renderQueue();
}

function setQueuePageSize(value) {
  queuePageSize = normalizeTablePageSize(value);
  queuePage = 1;
  localStorage.setItem("webui_queue_page_size", String(queuePageSize));
  renderQueue();
}

function setQueueDensity(_mode) {
  localStorage.removeItem("webui_queue_density");
  document.body.classList.remove("queue-compact");
  renderQueue();
}

function renderActive() {
  syncActiveDownloadOptions();
  const items = frontendState.active_downloads || [];
  reconcileSelectedTask("active", items);
  patchTableRows("activeBody", items, item => item.id, item => taskRenderService().activeRow(item, selected.active));
  byId("activeSummary").textContent = translateUiText(`\u5f53\u524d\u8fd0\u884c\uff1a${items.length} \u4e2a\u4efb\u52a1`);
  renderActiveDetail();
}

function currentDownloadOptions() {
  const settings = (frontendState.settings_snapshot || {})["\u4e0b\u8f7d\u8bbe\u7f6e"] || {};
  const options = {
    auto_retry: true,
    max_retries: Number(settings.max_retries || 3),
    max_concurrent: normalizeDownloadConcurrency(settings.max_concurrent || 3),
    ...(frontendState.download_options || {}),
  };
  options.max_concurrent = normalizeDownloadConcurrency(options.max_concurrent);
  return options;
}

function normalizeDownloadConcurrency(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 1) return 1;
  if (numeric <= 3) return 3;
  return 5;
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
    syncCustomSelectForSelect(retries);
  }
  if (concurrent) {
    const maxConcurrent = normalizeDownloadConcurrency(options.max_concurrent);
    concurrent.value = String(maxConcurrent);
    syncCustomSelectForSelect(concurrent);
  }
}

function updateDownloadOptions() {
  const autoRetry = Boolean(byId("activeAutoRetry") && byId("activeAutoRetry").checked);
  const maxRetries = Number(byId("activeMaxRetries") && byId("activeMaxRetries").value) || 3;
  const maxConcurrent = normalizeDownloadConcurrency(byId("activeMaxConcurrent") && byId("activeMaxConcurrent").value);
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
  const item = selectedTaskItem("active", frontendState.active_downloads || []);
  setHtmlIfChanged("activeDetail", taskRenderService().activeDetailHtml(item));
}

function activeEventTimelineHtml(events) {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.activeEventTimelineHtml(events) : "";
}

function activeTrendHtml(values, speedLabel = "0 B/s") {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.activeTrendHtml(values, speedLabel) : "";
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
  reconcileSelectedTask("completed", items);
  patchTableRows("completedBody", items, item => item.id, item => taskRenderService().completedRow(item, selected.completed));
  byId("completedTotal").textContent = translateUiText(`\u5171 ${allItems.length} \u9879`);
  byId("completedPageNow").textContent = String(completedPage);
  byId("completedTotalPages").textContent = String(totalPages);
  byId("completedPageSize").value = String(completedPageSize);
  syncCustomSelectForSelect(byId("completedPageSize"));
  byId("completedPrevPage").disabled = completedPage <= 1;
  byId("completedNextPage").disabled = completedPage >= totalPages;
  renderCompletedDetail();
  updateNavBtnsState();
  updateMediaControls();
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
  completedPageSize = normalizeTablePageSize(value);
  completedPage = 1;
  selected.completed = "";
  localStorage.setItem("webui_completed_page_size", String(completedPageSize));
  renderCompleted();
}

function renderCompletedDetail() {
  const item = selectedTaskItem("completed", frontendState.completed_items || []);
  setHtmlIfChanged("completedDetail", taskRenderService().completedDetailHtml(item));
}

function displayMetadataValue(value, pending = false) {
  configureMediaDisplayHelpers();
  if (window.UcpMediaDisplay) return window.UcpMediaDisplay.displayMetadataValue(value, pending);
  const text = String(value || "").trim();
  if (pending && (!text || text === "--" || ["检测中", "Checking", "檢測中"].includes(text))) {
    return pendingMetadataLabel();
  }
  if (text && text !== "--") return translateUiText(text);
  return pending ? pendingMetadataLabel() : "--";
}

function pendingMetadataLabel() {
  const language = String(document.documentElement?.dataset?.language || currentLanguage() || "zh-CN").trim();
  if (language === "en-US") return "Checking";
  if (language === "zh-TW") return "檢測中";
  return "检测中";
}

function basenameFromPath(path) {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.basenameFromPath(path) : "";
}

function dirnameFromPath(path) {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.dirnameFromPath(path) : "";
}

function renderFailed() {
  const items = frontendState.failed_items || [];
  reconcileSelectedTask("failed", items);
  patchTableRows("failedBody", items, item => item.id, item => taskRenderService().failedRow(item, selected.failed));
  renderFailedDetail();
}

function selectFailed(id) {
  selected.failed = id;
  renderFailed();
}

function renderFailedDetail() {
  const item = selectedTaskItem("failed", frontendState.failed_items || []);
  setHtmlIfChanged("failedDetail", taskRenderService().failedDetailHtml(item));
  setHtmlIfChanged("failedSolutions", taskRenderService().failedSolutionsHtml(item));
}

function iconFileUrl(file) {
  return taskRenderService().iconFileUrl(file);
}

function iconTextHtml(text, iconFile) {
  return taskRenderService().iconTextHtml(text, iconFile);
}

function failedStatusHtml(text) {
  return taskRenderService().failedStatusHtml(text);
}

function detailRowHtml(label, value, iconFile = "") {
  return taskRenderService().detailRowHtml(label, value, iconFile);
}

function failedLogLevel(entry) {
  return taskRenderService().failedLogLevel(entry);
}

function failedLogLevelClass(level) {
  return taskRenderService().failedLogLevelClass(level);
}

function failedLogRowHtml(entry) {
  return taskRenderService().failedLogRowHtml(entry);
}

function failedLogTime(value) {
  return taskRenderService().failedLogTime(value);
}

function solutionRowHtml(solution) {
  return taskRenderService().solutionRowHtml(solution);
}

function logLevelClass(level) {
  const normalized = String(level || "").toUpperCase();
  if (["SUCCESS", "OK"].includes(normalized)) return "success";
  if (["WARN", "WARNING"].includes(normalized)) return "warn";
  if (normalized === "ERROR") return "error";
  if (["CMD", "COMMAND"].includes(normalized)) return "cmd";
  return "info";
}

const LOG_TAB_LABELS = {
  all: "全部日志",
  crawl: "采集日志",
  download: "下载日志",
  system: "系统日志",
  performance: "性能日志",
  error: "错误日志",
};

const LOG_TAB_TRANSLATIONS = {
  "zh-CN": {
    all: "全部日志",
    crawl: "采集日志",
    download: "下载日志",
    system: "系统日志",
    performance: "性能日志",
    error: "错误日志",
  },
  "en-US": {
    all: "All logs",
    crawl: "Crawl logs",
    download: "Download logs",
    system: "System logs",
    performance: "Performance logs",
    error: "Error logs",
  },
  "zh-TW": {
    all: "全部日誌",
    crawl: "採集日誌",
    download: "下載日誌",
    system: "系統日誌",
    performance: "性能日誌",
    error: "錯誤日誌",
  },
};

function localizedLogTabLabel(category) {
  const key = String(category || "all");
  const language = currentLanguage();
  const table = LOG_TAB_TRANSLATIONS[language] || LOG_TAB_TRANSLATIONS["zh-CN"];
  return table[key] || t(LOG_TAB_LABELS[key] || key);
}

function emptyLogTabCounts() {
  const counts = Object.fromEntries(Object.keys(LOG_TAB_LABELS).map(key => [key, 0]));
  return counts;
}

function currentLogTabCounts() {
  return (logQueryState.result && logQueryState.result.tabCounts) || emptyLogTabCounts();
}

function syncLogTabLabels(countsOverride) {
  const counts = countsOverride || currentLogTabCounts();
  document.querySelectorAll("#logTabs [data-log-tab]").forEach(button => {
    const category = button.dataset.logTab || "all";
    button.textContent = `${localizedLogTabLabel(category)} ${counts[category] || 0}`;
  });
}

function syncLogStaticLanguage() {
  syncLogTabLabels();
  const logFilterLabels = ["日志级别", "时间范围", "平台", "Trace ID", "关键词搜索"];
  document.querySelectorAll("#page-logs .log-filter-label").forEach((label, index) => {
    if (logFilterLabels[index]) label.textContent = t(logFilterLabels[index]);
  });
  const logTraceFilter = byId("logTraceFilter");
  if (logTraceFilter) logTraceFilter.placeholder = t("请输入 Trace ID");
  const logKeywordFilter = byId("logKeywordFilter");
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
}

function logLevelCellHtml(item) {
  const label = item.level_display || item.level || "INFO";
  return `<span class="log-level-badge log-level-${logLevelClass(label)}">${esc(label)}</span>`;
}

function translateStructuredLogText(value) {
  const text = String(value ?? "");
  if (!text.trim()) return text;
  return text
    .split(/(\s+·\s+|\s+\/\s+)/)
    .map(part => (/^\s*(?:·|\/)\s*$/.test(part) ? part : translateUiText(part)))
    .join("");
}

function translateRuntimeLogText(value) {
  const text = String(value ?? "");
  if (!text.trim()) return text;
  const language = currentLanguage();
  const translated = translateStructuredLogText(text);
  if (translated !== text) return translated;
  if (language !== "en-US") return localizeNonEnglishDynamicLogText(text, language);
  return localizeEnglishDynamicLogText(text);
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
  { zh: "下载任务已进入队列", en: "Download task has been queued", tw: "下載任務已入隊" },
  { zh: "下载任务已加入执行队列", en: "Download task has been queued for execution", tw: "下載任務已加入執行隊列" },
  { zh: "下载任务开始执行", en: "Download task started", tw: "下載任務開始執行" },
  { zh: "下载任务完成", en: "Download task completed", tw: "下載任務完成" },
  { zh: "下载任务被用户停止", en: "Download task stopped by user", tw: "下載任務被使用者停止" },
  { zh: "下载完成后已按文件签名修正扩展名", en: "Fixed extension after download by file signature", tw: "下載完成後已依檔案簽章修正副檔名" },
  { zh: "分块下载不可用，回退到后续下载策略", en: "Chunked download unavailable; falling back to later download strategy", tw: "分塊下載不可用，回退到後續下載策略" },
  { zh: "下载策略执行失败，回退到后续策略", en: "Download strategy failed; falling back to later strategy", tw: "下載策略執行失敗，回退到後續策略" },
  { zh: "抖音下载任务已提交到下载队列", en: "Douyin download task submitted to the queue", tw: "抖音下載任務已提交到下載佇列" },
  { zh: "启动抖音爬虫任务", en: "Started Douyin crawl task", tw: "啟動抖音爬蟲任務" },
  { zh: "抖音爬虫任务结束", en: "Douyin crawl task finished", tw: "抖音爬蟲任務結束" },
  { zh: "抖音爬虫运行异常", en: "Douyin crawl runtime error", tw: "抖音爬蟲執行異常" },
  { zh: "进入抖音任务提交阶段", en: "Entered Douyin task submit stage", tw: "進入抖音任務提交階段" },
  { zh: "Douyin 参数初始化完成", en: "Douyin parameters initialized", tw: "Douyin 參數初始化完成" },
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
  { zh: "启动小红书爬虫任务", en: "Started Xiaohongshu crawl task", tw: "啟動小紅書爬蟲任務" },
  { zh: "小红书爬虫运行异常", en: "Xiaohongshu crawl runtime error", tw: "小紅書爬蟲執行異常" },
  { zh: "小红书爬虫任务结束", en: "Xiaohongshu crawl task finished", tw: "小紅書爬蟲任務結束" },
  { zh: "小红书视频下载失败", en: "Xiaohongshu video download failed", tw: "小紅書影片下載失敗" },
  { zh: "MissAV m3u8 嗅探成功并提交下载", en: "MissAV m3u8 sniffed successfully and submitted for download", tw: "MissAV m3u8 嗅探成功並提交下載" },
  { zh: "MissAV 详情页嗅探超时，未发现 playlist.m3u8", en: "MissAV detail page sniff timed out; playlist.m3u8 was not found", tw: "MissAV 詳情頁嗅探逾時，未發現 playlist.m3u8" },
  { zh: "MissAV 详情页加载失败", en: "MissAV detail page failed to load", tw: "MissAV 詳情頁載入失敗" },
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
];

function applyRuntimePhraseTranslations(text, language) {
  const replacements = [];
  for (const entry of RUNTIME_LOG_PHRASE_TRANSLATIONS) {
    const target = language === "en-US" ? entry.en : language === "zh-TW" ? (entry.tw || entry.zh) : entry.zh;
    for (const source of [entry.zh, entry.en, entry.tw]) {
      if (source && source !== target) replacements.push([source, target]);
    }
  }
  replacements.sort((left, right) => right[0].length - left[0].length);
  let result = text;
  for (const [source, target] of replacements) result = result.split(source).join(target);
  return result;
}

function localizeEnglishDynamicLogText(text) {
  const loaded = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?已加载\s*(\d+)\s*个本地文件\s*\(视频[:：]\s*(\d+)\s*,\s*图片[:：]\s*(\d+)\)$/u);
  if (loaded) {
    const noun = loaded[2] === "1" ? "file" : "files";
    return `${loaded[1] || ""}Loaded ${loaded[2]} local ${noun} (videos: ${loaded[3]}, images: ${loaded[4]})`;
  }
  const scanning = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?正在扫描目录[:：]\s*(.+)$/u);
  if (scanning) return `${scanning[1] || ""}Scanning directory: ${scanning[2]}`;
  const done = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?下载完成[:：]\s*(.+)$/u);
  if (done) return `${done[1] || ""}Download completed: ${done[2]}`;
  const failed = text.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?下载失败\s*\[(.+?)\][：:]\s*(.+)$/u);
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
    [/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF]*\s*)?全部完成[:：]\s*成功\s*(\d+)\s*\/\s*(\d+)\s*\|\s*失败\s*(\d+)$/u, match => `${match[1] || ""}All completed: success ${match[2]}/${match[3]} | failed ${match[4]}`],
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
    抖音: { "zh-CN": "抖音", "zh-TW": "抖音", "en-US": "Douyin" },
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
  return localizedDynamicValue(terms[text] || null, language) || text;
}

function localizeNonEnglishDynamicLogText(text, language) {
  const exact = NON_EN_DYNAMIC_LOG_TEXT[text];
  if (exact) return localizedDynamicValue(exact, language);
  const phraseResult = applyRuntimePhraseTranslations(text, language);
  if (phraseResult !== text) return phraseResult;

  let match = text.match(/^Bilibili route:\s*(.+)$/);
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

function localizeLogEventCode(value) {
  const text = String(value || "-");
  const language = currentLanguage();
  if (!text || text === "-") return text;
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

function logValueHtml(value) {
  return esc(translateRuntimeLogText(value));
}

function logEventCodeText(value) {
  return localizeLogEventCode(value);
}

function logSourceCellHtml(item) {
  const label = item.source_display || item.source || item.platform || "";
  const iconFile = item.source_display_icon_file || "";
  const translated = translateRuntimeLogText(label);
  if (!iconFile) return esc(translated);
  return `<span class="platform-cell log-source-cell"><img src="${iconFileUrl(iconFile)}" alt="" />${esc(translated)}</span>`;
}

function logDetailRowHtml(label, valueHtml) {
  return `<span>${esc(t(label))}</span><span class="kv-value">${valueHtml}</span>`;
}

function logDetailSummaryHtml(item) {
  const platformLabel = item.platform_display || item.platform_label || item.platform || "";
  const rows = [
    ["时间", esc(item.time || "")],
    ["级别", logLevelCellHtml(item)],
    ["性质", logValueHtml(logResultNatureText(item))],
    ["范围", logValueHtml(logScopeDisplayText(item))],
    ["阶段", logValueHtml(logStageDisplayText(item))],
    ["事件码", esc(logEventCodeText(item.event_code || item.status_code || "-"))],
    ["来源", logSourceCellHtml(item)],
    ["平台", logValueHtml(platformLabel || "-")],
    ["Trace ID", esc(item.trace_id || "-")],
    ["消息", logValueHtml(item.message || item.message_summary || "-")],
  ];
  return `<div class="kv log-detail-kv">${rows.map(([label, value]) => logDetailRowHtml(label, value)).join("")}</div>`;
}

function emptyLogDetailSummaryHtml() {
  const rows = [
    ["时间", "-"],
    ["级别", "-"],
    ["性质", "-"],
    ["范围", "-"],
    ["阶段", "-"],
    ["事件码", "-"],
    ["来源", "-"],
    ["平台", "-"],
    ["Trace ID", "-"],
    ["消息", "-"],
  ];
  return `<div class="kv log-detail-kv">${rows.map(([label, value]) => logDetailRowHtml(label, esc(value))).join("")}</div>`;
}

function logQueryItems() {
  trimFrontendLogItems();
  return Array.isArray(frontendState.log_items) ? frontendState.log_items : [];
}

function logQuerySignature(items) {
  const first = items[0] || {};
  const last = items[items.length - 1] || {};
  return JSON.stringify({
    count: items.length,
    first: logItemId(first),
    last: logItemId(last),
    firstTime: first.time || "",
    lastTime: last.time || "",
    filters: logFilters,
    page: logPage,
    pageSize: logPageSize,
    limit: uiLogDisplayLimit(),
  });
}

function buildLogQueryRequest(items, sequence) {
  return {
    sequence,
    items,
    filters: { ...logFilters },
    page: logPage,
    pageSize: logPageSize,
    rowBudget: uiLogDisplayLimit(),
    selectedId: selected.log,
    nowMs: Date.now(),
  };
}

function queryLogsSync(items, sequence) {
  if (
    !window.UcpLogDisplay ||
    typeof window.UcpLogDisplay.queryLogItems !== "function" ||
    typeof window.UcpLogDisplay.filteredLogItems !== "function" ||
    typeof window.UcpLogDisplay.visibleLogItems !== "function"
  ) {
    return {
      sequence,
      pageItems: [],
      tabCounts: emptyLogTabCounts(),
      totalCount: items.length,
      matchedCount: 0,
      visibleCount: 0,
      currentPage: 1,
      totalPages: 1,
      selectedId: "",
    };
  }
  return window.UcpLogDisplay.queryLogItems(buildLogQueryRequest(items, sequence));
}

function ensureLogQueryWorker() {
  if (!logQueryWorkerAvailable) return null;
  if (logQueryWorker) return logQueryWorker;
  try {
    logQueryWorker = new Worker("/static/log_query_worker.js?v=20260707-log-worker");
    logQueryWorker.onmessage = event => {
      const payload = event && event.data ? event.data : {};
      if (payload.type === "result") {
        receiveLogQueryResult(payload.result);
      } else if (payload.type === "error") {
        logQueryWorkerAvailable = false;
        logQueryState.pending = false;
        appendLog(payload.message || "log query worker failed");
        renderLogs();
      }
    };
    logQueryWorker.onerror = () => {
      logQueryWorkerAvailable = false;
      logQueryState.pending = false;
      if (logQueryWorker) {
        logQueryWorker.terminate();
        logQueryWorker = null;
      }
      renderLogs();
    };
  } catch (_error) {
    logQueryWorkerAvailable = false;
    logQueryWorker = null;
  }
  return logQueryWorker;
}

function shouldUseLogQueryWorker(items) {
  return items.length > LOG_QUERY_WORKER_THRESHOLD && Boolean(ensureLogQueryWorker());
}

function receiveLogQueryResult(result) {
  if (!result || Number(result.sequence) !== logQuerySequence) return;
  logQueryState = {
    signature: logQueryState.signature,
    result,
    pending: false,
  };
  if (currentPage === "logs") renderLogQueryResult(result);
}

function submitLogQuery(items, signature) {
  const sequence = ++logQuerySequence;
  logQueryState = {
    signature,
    result: logQueryState.result,
    pending: true,
  };
  const worker = ensureLogQueryWorker();
  if (!worker) {
    receiveLogQueryResult(queryLogsSync(items, sequence));
    return;
  }
  worker.postMessage(buildLogQueryRequest(items, sequence));
}

function renderLogs() {
  syncLogStaticLanguage();
  syncLogFilterControls();
  const allItems = logQueryItems();
  const signature = logQuerySignature(allItems);
  if (logQueryState.signature === signature && logQueryState.result && !logQueryState.pending) {
    renderLogQueryResult(logQueryState.result);
    return;
  }
  if (shouldUseLogQueryWorker(allItems)) {
    submitLogQuery(allItems, signature);
    if (logQueryState.result) renderLogQueryResult(logQueryState.result);
    return;
  }
  const sequence = ++logQuerySequence;
  const result = queryLogsSync(allItems, sequence);
  logQueryState = { signature, result, pending: false };
  renderLogQueryResult(result);
}

function renderLogQueryResult(result) {
  syncLogStaticLanguage();
  syncLogFilterControls();
  const items = Array.isArray(result.pageItems) ? result.pageItems : [];
  const boundedItems = { length: Number(result.matchedCount) || 0 };
  const totalPages = Number(result.totalPages) || 1;
  logPage = Number(result.currentPage) || 1;
  syncLogTabLabels(result.tabCounts || emptyLogTabCounts());
  if (!items.some(item => logItemId(item) === selected.log)) selected.log = items.length ? logItemId(items[0]) : "";
  patchTableRows("logBody", items, item => logItemId(item), item => `
    <tr class="${selected.log === logItemId(item) ? "selected" : ""}" onclick="selectLog('${escAttr(logItemId(item))}')">
      <td>${esc(item.time)}</td>
      <td>${logLevelCellHtml(item)}</td>
      <td>${logSourceCellHtml(item)}</td>
      <td>${esc(item.trace_id || "")}</td>
      <td title="${escAttr(translateRuntimeLogText(item.message_summary || ""))}">${logValueHtml(item.message_summary || "")}</td>
    </tr>
  `);
  syncLogEmptyState(items.length === 0);
  byId("logTotal").textContent = translateUiText(`共 ${(frontendState.log_items || []).length} 条 / 匹配 ${boundedItems.length} 条 / 当前显示 ${items.length} 条`);
  byId("logPageIndicator").textContent = translateUiText(`第 ${logPage} / ${totalPages} 页`);
  byId("logPageSize").value = String(logPageSize);
  syncCustomSelectForSelect(byId("logPageSize"));
  byId("logPrevPage").disabled = logPage <= 1 || logPageSize <= 0;
  byId("logNextPage").disabled = logPage >= totalPages || logPageSize <= 0;
  renderLogDetail(items);
}

function syncLogEmptyState(empty) {
  const panel = byId("logEmptyState");
  if (!panel) return;
  panel.hidden = !empty;
  if (!empty) return;
  const title = panel.querySelector("strong");
  const subtitle = panel.querySelector(".log-empty-subtitle");
  const subtitlePrimary = panel.querySelector("[data-log-empty-primary]");
  const subtitleSecondary = panel.querySelector("[data-log-empty-secondary]");
  if (title) title.textContent = t("暂无匹配日志");
  if (subtitle) subtitle.setAttribute("aria-label", t("调整筛选条件 或点击「刷新缓冲」重新加载日志"));
  if (subtitlePrimary) subtitlePrimary.textContent = t("调整筛选条件");
  if (subtitleSecondary) subtitleSecondary.textContent = t("或点击「刷新缓冲」重新加载日志");
}

function logItemId(item) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.logItemId(item) : String(item.id || "");
}

function selectLog(id) {
  selected.log = String(id);
  renderLogs();
}

function currentLogDetailItem(itemsOverride) {
  const items = Array.isArray(itemsOverride)
    ? itemsOverride
    : ((logQueryState.result && Array.isArray(logQueryState.result.pageItems)) ? logQueryState.result.pageItems : []);
  return items.find(row => logItemId(row) === selected.log) || null;
}

function normalizeLogDetailPayload(item) {
  if (!item) return {};
  const detail = item.detail;
  if (detail && typeof detail === "object") return detail;
  const text = String(detail || "").trim();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_error) {
    return {
      description: text,
      status_code: item.event_code || item.status_code || "",
    };
  }
}

function readableLogDetailValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch (_error) {
      return String(value);
    }
  }
  return String(value)
    .replace(/\\r\\n|\\n|\\r/g, "\n")
    .replace(/\r\n?/g, "\n")
    .replace(/[-=]{36,}/g, "----------------------------");
}

function localizedLogDetailValue(value, key = "") {
  if (Array.isArray(value)) return value.map(item => localizedLogDetailValue(item, key));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([childKey, item]) => [childKey, localizedLogDetailValue(item, childKey)]));
  }
  if (typeof value === "string") {
    const readable = readableLogDetailValue(value);
    return ["status_code", "event_code"].includes(String(key)) ? localizeLogEventCode(readable) : translateRuntimeLogText(readable);
  }
  return value;
}

function formatLogDetailDisplayText(payload) {
  if (!payload || typeof payload !== "object") return readableLogDetailValue(payload);
  const entries = Object.entries(localizedLogDetailValue(payload));
  if (!entries.length) return "{}";
  return entries.map(([key, value]) => {
    const readable = readableLogDetailValue(value);
    return readable.includes("\n") ? `${key}:\n${readable}` : `${key}: ${readable}`;
  }).join("\n");
}

function buildLogDetailPayload(item) {
  const detailPayload = normalizeLogDetailPayload(item);
  return {
    time: item.time || "",
    level: item.level || item.raw_level || "",
    platform: item.platform_display || item.platform || "",
    source: item.source || "",
    trace_id: item.trace_id || "",
    message: item.message || item.message_summary || "",
    detail: detailPayload,
    stack: item.stack || "",
  };
}

function writeTextToClipboard(text, successMessage) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => appendUiLog(successMessage))
      .catch(() => appendLog(text));
    return;
  }
  appendLog(text);
}

function copyCurrentLogDetail() {
  const item = currentLogDetailItem();
  if (!item) {
    appendLog(t("暂无日志"));
    return;
  }
  writeTextToClipboard(JSON.stringify(buildLogDetailPayload(item), null, 2), t("已复制日志详情"));
}

function copyCurrentLogJson() {
  const item = currentLogDetailItem();
  if (!item) {
    appendLog(t("暂无日志"));
    return;
  }
  writeTextToClipboard(JSON.stringify(normalizeLogDetailPayload(item), null, 2), t("已复制详细信息"));
}

function exportCurrentLogDetail() {
  const item = currentLogDetailItem();
  if (!item) {
    appendLog(t("暂无日志"));
    return;
  }
  const text = JSON.stringify(buildLogDetailPayload(item), null, 2);
  const blob = new Blob([text], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const suffix = String(item.trace_id || logItemId(item) || "current").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 80);
  const filename = `log_detail_${suffix || "current"}.json`;
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  appendUiLog(t("已导出日志详情"), filename);
}

function renderLogDetail(itemsOverride) {
  const items = Array.isArray(itemsOverride)
    ? itemsOverride
    : ((logQueryState.result && Array.isArray(logQueryState.result.pageItems)) ? logQueryState.result.pageItems : []);
  const item = currentLogDetailItem(items);
  if (!item) {
    byId("logDetail").innerHTML = `
      <div class="log-inspector-header">
        <h2>${esc(t("日志详情"))}</h2>
        <div class="log-inspector-actions">
          <button class="btn" type="button" disabled>${esc(t("复制"))}</button>
          <button class="btn" type="button" disabled>${esc(t("导出"))}</button>
        </div>
      </div>
      <div class="log-detail-card">
        ${emptyLogDetailSummaryHtml()}
      </div>
      <div class="log-extra-card log-json-card">
        <div class="log-card-head">
          <h2>${esc(t("详细信息"))}</h2>
          <button class="btn" type="button" disabled>${esc(t("复制"))}</button>
        </div>
        <pre class="log-snippet">{}</pre>
      </div>
    `;
    return;
  }
  const detailPayload = normalizeLogDetailPayload(item);
  const detailJson = JSON.stringify(detailPayload, null, 2);
  const detailDisplayText = formatLogDetailDisplayText(detailPayload);
  const stack = String(item.stack || "").trim();
  const extraBlocks = [];
  extraBlocks.push(`
    <div class="log-extra-card log-json-card">
      <div class="log-card-head">
        <h2>${esc(t("详细信息"))}</h2>
        <button class="btn" type="button" onclick="copyCurrentLogJson()">${esc(t("复制"))}</button>
      </div>
      <pre class="log-snippet log-detail-readable" data-json="${escAttr(detailJson)}">${esc(detailDisplayText)}</pre>
    </div>
  `);
  if (stack && stack !== "无") {
    extraBlocks.push(`
      <div class="log-extra-card">
        <h2>${esc(t("堆栈跟踪"))}</h2>
        <pre class="log-snippet">${esc(stack)}</pre>
      </div>
    `);
  }
  byId("logDetail").innerHTML = `
    <div class="log-inspector-header">
      <h2>${esc(t("日志详情"))}</h2>
      <div class="log-inspector-actions">
        <button class="btn" type="button" onclick="copyCurrentLogDetail()">${esc(t("复制"))}</button>
        <button class="btn" type="button" onclick="exportCurrentLogDetail()">${esc(t("导出"))}</button>
      </div>
    </div>
    <div class="log-detail-card">
      ${logDetailSummaryHtml(item)}
    </div>
    ${extraBlocks.join("")}
  `;
}

function setLogTab(category) {
  logFilters.category = category || "all";
  selected.log = "";
  logPage = 1;
  renderLogs();
}

function syncLogFiltersFromDom() {
  logFilters.level = normalizeLogFilterValue("level", byId("logLevelFilter")?.value || "all");
  logFilters.time = normalizeLogFilterValue("time", byId("logTimeFilter")?.value || "30m");
  logFilters.platform = normalizeLogFilterValue("platform", byId("logPlatformFilter")?.value || "all");
  logFilters.trace = byId("logTraceFilter")?.value.trim() || "";
  logFilters.keyword = byId("logKeywordFilter")?.value.trim() || "";
  selected.log = "";
  logPage = 1;
  renderLogs();
}

function selectValueOrFallback(select, preferredValue, fallbackValue) {
  if (!select || select.tagName !== "SELECT") return String(preferredValue ?? "");
  const options = Array.from(select.options);
  const preferred = String(preferredValue ?? "");
  if (options.some(option => String(option.value) === preferred)) return preferred;
  const fallback = String(fallbackValue ?? "");
  if (options.some(option => String(option.value) === fallback)) return fallback;
  const defaultOption = options.find(option => option.defaultSelected) || options[0];
  return defaultOption ? String(defaultOption.value) : "";
}

function syncLogFilterControls() {
  document.querySelectorAll("#logTabs [data-log-tab]").forEach(button => button.classList.toggle("active", button.dataset.logTab === logFilters.category));
  const selectBindings = [
    ["logLevelFilter", "level", "all"],
    ["logTimeFilter", "time", "30m"],
    ["logPlatformFilter", "platform", "all"],
  ];
  for (const [id, key, fallback] of selectBindings) {
    const node = byId(id);
    const value = selectValueOrFallback(node, normalizeLogFilterValue(key, logFilters[key]), fallback);
    if (node && node.value !== value) node.value = value;
    logFilters[key] = normalizeLogFilterValue(key, value);
    syncCustomSelectForSelect(node);
  }
  const textBindings = [
    ["logTraceFilter", logFilters.trace],
    ["logKeywordFilter", logFilters.keyword],
  ];
  for (const [id, value] of textBindings) {
    const node = byId(id);
    if (node && node.value !== value) node.value = value;
  }
}

function setLogPage(delta) {
  logPage += Number(delta) || 0;
  renderLogs();
}

function setLogPageSize(value) {
  logPageSize = normalizeLogPageSize(value);
  logPage = 1;
  localStorage.setItem("webui_log_page_size", String(logPageSize));
  renderLogs();
  syncCustomSelectForSelect(byId("logPageSize"));
}

function currentLogTraceId() {
  const items = (logQueryState.result && Array.isArray(logQueryState.result.pageItems)) ? logQueryState.result.pageItems : [];
  const current = items.find(row => logItemId(row) === selected.log);
  const trace = String((current && current.trace_id) || "").trim();
  if (trace) return trace;
  const fallback = items.find(row => String(row.trace_id || "").trim());
  return String((fallback && fallback.trace_id) || "").trim();
}

function copySelectedLogTraceId() {
  const traceId = currentLogTraceId();
  if (!traceId) {
    appendLog(t("当前日志没有可复制的 Trace ID"));
    return;
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(traceId)
      .then(() => appendUiLog("已复制 Trace ID", traceId))
      .catch(() => appendLog(traceId));
    return;
  }
  appendLog(traceId);
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
  currentSettingsGroup = normalizeSettingsGroupName(currentSettingsGroup);
  if (!orderedGroups.includes(currentSettingsGroup)) currentSettingsGroup = orderedGroups[0] || "基础设置";
  const currentValue = settings[currentSettingsGroup] || {};
  const description =
    contract.descriptions?.[currentSettingsGroup]
    || SETTINGS_GROUP_DESCRIPTIONS_FALLBACK[currentSettingsGroup]
    || "";
  const hint =
    contract.hints?.[currentSettingsGroup]
    || SETTINGS_GROUP_HINTS_FALLBACK[currentSettingsGroup]
    || "";
  const title = document.querySelector("#page-settings .page-head h1");
  if (title) title.textContent = t("配置中心");
  const subtitle = document.querySelector("#page-settings .page-head p");
  if (subtitle) subtitle.textContent = t("集中管理下载行为、平台状态、播放体验、日志策略与界面外观");
  const navHtml = orderedGroups.map(group => `
    <button class="settings-nav-btn ${group === currentSettingsGroup ? "active" : ""}" type="button" data-group="${escAttr(group)}" onclick="switchSettingsGroup('${escAttr(group)}')">
      <img src="${escAttr(iconManifest.route || "/ui-icon")}/${escAttr(settingGroupIconFile(group))}" alt="" />
      <span>${esc(t(group))}</span>
    </button>
  `).join("");
  const html = `
    <div class="settings-shell">
      <aside class="settings-side-nav">
        <div class="settings-nav-title">${esc(t("设置分类"))}</div>
        ${navHtml}
      </aside>
      <section class="settings-detail-panel">
        <header class="settings-detail-head">
          <span class="settings-detail-icon" aria-hidden="true">
            <img src="${escAttr(iconManifest.route || "/ui-icon")}/${escAttr(settingGroupIconFile(currentSettingsGroup))}" alt="" />
          </span>
          <h2>${esc(t(currentSettingsGroup))}</h2>
          <p>${esc(t(description))}</p>
        </header>
        <div class="settings-detail-body ${currentSettingsGroup === "\u5e73\u53f0\u8bbe\u7f6e" ? "settings-platform-body" : ""}">
          ${settingsControls(currentSettingsGroup, currentValue)}
        </div>
        ${hint ? `<div class="settings-hint-card"><span class="settings-hint-icon">i</span><span>${esc(t(hint))}</span></div>` : ""}
      </section>
    </div>
  `;
  if (!force && renderSignatures.settingsGrid && renderSignatures.settingsGrid !== html && hasFocusedDescendant("settingsGrid")) return;
  setHtmlIfChanged("settingsGrid", html);
}

function isPlatformSettingsVisible() {
  return currentPage === "settings" && normalizeSettingsGroupName(currentSettingsGroup) === "平台设置";
}

function maybeRefreshPlatformAuthStatus(force = false) {
  if (!isPlatformSettingsVisible()) return;
  frontendAction("refresh_platform_auth_status", { force: Boolean(force) });
}

function switchSettingsGroup(group) {
  if (!group) return;
  const nextGroup = normalizeSettingsGroupName(group);
  const sameGroup = nextGroup === normalizeSettingsGroupName(currentSettingsGroup);
  if (!sameGroup) {
    currentSettingsGroup = nextGroup;
    localStorage.setItem("webui_settings_group", nextGroup);
    renderSettings(true);
  }
  maybeRefreshPlatformAuthStatus(false);
}

function settingsRenderService() {
  configureSettingsRenderHelpers();
  return window.UcpSettingsRender || null;
}

function settingsControls(group, value) {
  const service = settingsRenderService();
  return service ? service.settingsControls(group, value) : "";
}

function platformSettingsSummary(rows) {
  const service = settingsRenderService();
  return service ? service.platformSettingsSummary(rows) : "";
}

function platformSettingsHeader() {
  const service = settingsRenderService();
  return service ? service.platformSettingsHeader() : "";
}

function platformSettingRow(row) {
  const service = settingsRenderService();
  return service ? service.platformSettingRow(row) : "";
}

function isCustomProxyValue(value) {
  const service = settingsRenderService();
  return service ? service.isCustomProxyValue(value) : false;
}

function proxyCustomDisplayValue(value) {
  const service = settingsRenderService();
  return service ? service.proxyCustomDisplayValue(value) : String(value || "");
}

function updatePlatformSettingSnapshot(platformId, key, value) {
  const rows = (frontendState.settings_snapshot || {})["\u5e73\u53f0\u8bbe\u7f6e"];
  if (!Array.isArray(rows)) return false;
  const row = rows.find(item => String(item.id || "") === String(platformId || ""));
  if (!row) return false;
  const text = String(value ?? "").trim();
  if (key === row.proxy_config_key || key === "proxy" || key === "proxy_url") {
    const proxyOptions = row.proxy_options || ["\u7cfb\u7edf\u4ee3\u7406", "\u76f4\u8fde", "Clash (7890)", "v2rayN (10809)", "\u81ea\u5b9a\u4e49"];
    const options = proxyOptions.map(normalizeSettingOption).filter(option => option.value);
    const optionKnown = options.some(option => String(option.value) === text);
    row.proxy = text || "\u7cfb\u7edf\u4ee3\u7406";
    row.proxy_custom_active = text === "\u81ea\u5b9a\u4e49" || (!!text && !optionKnown);
    if (text && text !== "\u81ea\u5b9a\u4e49" && !optionKnown) row.proxy_custom_value = text;
    return true;
  }
  if (key === row.count_config_key || key === "default_count" || key === "max_items") {
    row.default_count = Number.isFinite(Number(text)) ? Number(text) : text;
    return true;
  }
  if (key === row.timeout_config_key || key === "timeout" || key === "default_timeout") {
    row.default_timeout = Number.isFinite(Number(text)) ? Number(text) : text;
    return true;
  }
  row[key] = value;
  return true;
}

function handleProxySelect(platformId, key, select) {
  const value = String(select.value || "").trim();
  const row = select.closest(".setting-platform");
  const input = row ? row.querySelector(".proxy-custom") : null;
  const proxyEntry = row ? row.querySelector(".platform-proxy-entry") : null;
  if (input) {
    const custom = isCustomProxyValue(value);
    row.classList.toggle("has-proxy-custom", custom);
    if (proxyEntry) proxyEntry.classList.toggle("has-custom", custom);
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

function selectAppearanceTheme(value) {
  const theme = String(value || "").toLowerCase() === "dark" ? "dark" : "light";
  updateSetting("common", "theme", theme);
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
    appearance.follow_system = false;
    appearance.theme = dark ? "dark" : "light";
    localStorage.setItem("cached_dark_theme", String(dark));
    applyAppearance(appearance);
    if (currentPage === "settings" && normalizeSettingsGroupName(currentSettingsGroup) === "外观设置") renderSettings(true);
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
  if (section === "playback") {
    const playback = ((frontendState.settings_snapshot || {})["\u64ad\u653e\u8bbe\u7f6e"] ||= {});
    playback[key] = key === "image_auto_advance_interval_seconds" ? Number(value || 5) : value;
    if (currentPage === "settings" && normalizeSettingsGroupName(currentSettingsGroup) === "\u64ad\u653e\u8bbe\u7f6e") renderSettings(true);
    const currentItem = completedItemById(currentPlayingId);
    if (currentItem && isImageItem(currentItem)) scheduleImageAutoAdvance(currentPlayingId);
  }
  updatePlatformSettingSnapshot(section, key, value);
  frontendAction("update_setting", { section, key, value });
}

function settingInput(label, key, value, scope = "") {
  const service = settingsRenderService();
  return service ? service.settingInput(label, key, value, scope) : "";
}

function settingCheckbox(label, key, checked, scope = "") {
  const service = settingsRenderService();
  return service ? service.settingCheckbox(label, key, checked, scope) : "";
}

function imageManualSwitchSetting(value, options) {
  const service = settingsRenderService();
  return service ? service.imageManualSwitchSetting(value, options) : "";
}

function normalizeSettingOption(option) {
  const service = settingsRenderService();
  if (service) return service.normalizeSettingOption(option);
  if (option && typeof option === "object") {
    const value = String(option.value ?? option.id ?? option.label ?? "");
    const label = String(option.label ?? value);
    return { value, label };
  }
  return { value: String(option ?? ""), label: String(option ?? "") };
}

function settingSelect(label, key, value, options, scope = "", extraAttrs = "") {
  const service = settingsRenderService();
  return service ? service.settingSelect(label, key, value, options, scope, extraAttrs) : "";
}

function settingGroupIconFile(group) {
  return SETTINGS_GROUP_ICONS[group] || "nav_settings.png";
}

function renderToolbox() {
  const title = document.querySelector("#page-toolbox .page-head h1");
  if (title) title.textContent = t("工具箱");
  const subtitle = document.querySelector("#page-toolbox .page-head p");
  if (subtitle) subtitle.textContent = t("高效实用的辅助工具，提升工作效率");
  const items = frontendState.toolbox_items || [];
  reconcileSelectedTask("tool", items);
  byId("toolGrid").innerHTML = items.map(item => `
    <button class="tool-card ${selected.tool === item.id ? "active" : ""}" onclick="selectTool('${escAttr(item.id)}')">
      <img src="${escAttr(iconManifest.route || "/ui-icon")}/${escAttr(item.icon_file || "nav_toolbox.png")}" alt="" />
      <h2>${esc(t(item.title))}</h2>
      <p>${esc(t(item.summary))}</p>
    </button>
  `).join("");
  renderToolDetail();
}

function selectTool(id) {
  selected.tool = id;
  renderToolbox();
}

function renderToolDetail() {
  const item = selectedTaskItem("tool", frontendState.toolbox_items || []) || {};
  const recent = frontendState.toolbox_recent_items || [];
  byId("toolDetail").innerHTML = `
    <h2>${esc(t("最近使用"))}</h2>
    <div class="recent-list">${recent.length ? recent.map(row => `${esc(t(row.title || ""))}  ${esc(t(row.last_used || ""))}`).join("\n") : esc(t("暂无最近使用记录"))}</div>
    <h2>${esc(t("工具详情"))}</h2>
    ${kvHtml([["工具", t(item.title || "")], ["说明", t(item.summary || "")], ["输入示例", t(item.input_example || "")], ["输出示例", t(item.output_example || "")]])}
    <button class="btn btn-primary" onclick="frontendAction('run_tool',{tool_id:'${escAttr(item.id || "")}'})">${esc(t("打开工具"))}</button>
  `;
}

function renderStatus() {
  const status = frontendState.app_status || {};
  renderCounts();
  const failedCount = Number(status.failed_count || 0) || 0;
  let indicator = String(status.status_indicator || "").trim().toLowerCase();
  if (!["idle", "running", "error"].includes(indicator)) {
    if (String(status.running_state || "") === "运行中") indicator = "running";
    else if (failedCount > 0) indicator = "error";
    else indicator = "idle";
  }
  const statusIndicator = byId("statusIndicator");
  if (statusIndicator) statusIndicator.className = `status-dot ${indicator === "idle" ? "" : indicator}`.trim();
  document.querySelectorAll("[data-status-caption]").forEach(caption => {
    caption.textContent = `${t(caption.dataset.statusCaption || "")}:`;
  });
  byId("statusState").textContent = t(status.running_state || "空闲中");
  byId("statusDownload").textContent = status.download_speed || "0 B/s";
  byId("statusCompleted").textContent = String(status.completed_count || 0);
  byId("statusFailed").textContent = String(failedCount);
  byId("statusVersion").textContent = status.version || "v3.6.17";
}

function switchPage(pageId) {
  currentPage = pageId;
  document.querySelectorAll(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === pageId));
  document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === pageId));
  renderCurrentPage();
  maybeRefreshPlatformAuthStatus(false);
}

function progressHtml(value) {
  return taskRenderService().progressHtml(value);
}

function actionButton(actionId, label, onclick, danger = false) {
  return taskRenderService().actionButton(actionId, label, onclick, danger);
}

function smartWrapText(value) {
  return taskRenderService().smartWrapText(value);
}

function kvHtml(pairs, wrapKeys = new Set()) {
  return taskRenderService().kvHtml(pairs, wrapKeys);
}

function setCrawlUiState(isRunning) {
  crawlRunning = !!isRunning;
  const startBtn = byId("startBtn");
  const stopBtn = byId("stopBtn");
  const searchInput = byId("searchInput");
  const sourceSelect = byId("sourceSelect");
  const countSelect = byId("videoCountSelect");
  if (startBtn) {
    startBtn.disabled = crawlRunning;
    startBtn.classList.toggle("is-running", crawlRunning);
    startBtn.setAttribute("aria-busy", crawlRunning ? "true" : "false");
  }
  if (stopBtn) stopBtn.disabled = !crawlRunning;
  [searchInput, sourceSelect, countSelect].forEach(control => {
    if (control) control.disabled = crawlRunning;
  });
  syncCustomSelectForSelect(sourceSelect);
  syncCustomSelectForSelect(countSelect);
}

function startCrawl() {
  const keyword = byId("searchInput").value.trim();
  if (!keyword) {
    appendUiLog("请输入主页链接、分享链接或合集链接");
    return;
  }
  const source = byId("sourceSelect").value || "";
  const settingsRow = platformSettingsRow(source);
  const platformKnown = !!settingsRow || platforms.some(platform => String(platform.id) === source);
  if (!source || !platformKnown) {
    appendUiLog("未选择有效模式", "", "❌ ");
    return;
  }
  const platformRow = settingsRow || {};
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
  if (!sendWS("start_crawl", { source_id: source, source, keyword, config })) {
    appendUiLog("前端连接尚未就绪，请稍后重试", "", "⚠️ ");
    return;
  }
  setCrawlUiState(true);
}

function stopCrawl() {
  if (sendWS("stop_crawl", {})) byId("stopBtn").disabled = true;
  else appendUiLog("前端连接尚未就绪，请稍后重试", "", "⚠️ ");
}

function sendWS(type, data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, data }));
    return true;
  }
  return false;
}

const defaultSendWS = sendWS;

function playbackStateService() { return window.UcpPlaybackState || null; }
function playbackSettings() { return playbackStateService()?.playbackSettings(frontendState) || (((frontendState.settings_snapshot || {})["\u64ad\u653e\u8bbe\u7f6e"] || {})); }
function shouldUseBuiltinPlayer() { return playbackStateService()?.shouldUseBuiltinPlayer(frontendState) ?? String(playbackSettings().default_player || "builtin_player") !== "system_default"; }
function shouldRememberPlaybackPosition() { return playbackStateService()?.shouldRememberPlaybackPosition(frontendState) ?? playbackSettings().remember_position !== false; }
function shouldAutoplayNext() { return playbackStateService()?.shouldAutoplayNext(frontendState) ?? playbackSettings().autoplay_next !== false; }
function shouldManualSwitchImages() { return playbackStateService()?.shouldManualSwitchImages(frontendState) ?? playbackSettings().manual_image_switch === true; }
function imageAutoAdvanceIntervalMs() { return playbackStateService()?.imageAutoAdvanceIntervalMs(frontendState) ?? 5000; }
function completedItemById(id) { return playbackStateService()?.completedItemById(frontendState, id) || (frontendState.completed_items || []).find(item => String(item.id) === String(id)); }
function playbackPositionIdentity(id) { return playbackStateService()?.playbackPositionIdentity(frontendState, id) || String((completedItemById(id) && (completedItemById(id).local_path || completedItemById(id).filename || completedItemById(id).id)) || id || ""); }
function playbackPositionKey(id) { return playbackStateService()?.playbackPositionKey(frontendState, id) || `${PLAYBACK_POSITION_PREFIX}${encodeURIComponent(playbackPositionIdentity(id))}`; }
function legacyPlaybackPositionKey(id) { return playbackStateService()?.legacyPlaybackPositionKey(id) || `${PLAYBACK_POSITION_PREFIX}${id}`; }
function removePlaybackPosition(id) { const service = playbackStateService(); if (service) return service.removePlaybackPosition(localStorage, frontendState, id); try { localStorage.removeItem(playbackPositionKey(id)); localStorage.removeItem(legacyPlaybackPositionKey(id)); } catch (_error) {} }
function cleanupWebPlaybackPositions(items) { playbackStateService()?.cleanupPlaybackPositions(localStorage, frontendState, items); }
function isImageItem(item) { return playbackStateService()?.isImageItem(item) ?? (String(item && item.content_type || "").toLowerCase() === "image" || /\.(png|jpe?g|gif|webp|bmp|avif)$/.test(String(item && (item.local_path || item.filename || item.title) || "").toLowerCase())); }
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
  }, imageAutoAdvanceIntervalMs());
}

function frontendAction(action, payload) {
  if (action === "delete_item") prepareDeleteItem(payload && (payload.id || payload.video_id));
  if (ws && ws.readyState === WebSocket.OPEN) {
    sendWS("frontend_action", {
      action,
      payload,
      frontend_version: Number(frontendVersion || 0),
    });
    if (action === "register_file_associations") appendUiLog("正在绑定默认打开方式...");
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
      if (result && result.message) appendLog(translateUiText(result.message));
    })
    .catch(error => appendLog(translateUiText(error.message || String(error))));
}

function mediaUrl(id) {
  return `/api/media/${encodeURIComponent(id)}`;
}

function playbackItemLabel(item, fallback = "") {
  return String((item && (item.title || item.filename || item.local_path)) || fallback || "").trim();
}

function appendPlaybackFailure(item, error) {
  const label = playbackItemLabel(item);
  const detail = error && (error.message || String(error)) ? `: ${error.message || String(error)}` : "";
  appendLog(`❌ ${t("播放失败")}${label ? ` [${label}]` : ""}${detail}`);
}

async function validateMediaForPreview(id) {
  try {
    const response = await fetch(mediaUrl(id), {
      method: "GET",
      headers: { Range: "bytes=0-0" },
      cache: "no-store",
    });
    if (response.body && typeof response.body.cancel === "function") {
      response.body.cancel().catch(() => {});
    }
    if (response.ok) return true;
    appendUiLog(response.status === 404 ? "文件不存在或已被删除" : "播放前校验失败", response.status === 404 ? "" : `HTTP ${response.status}`, "❌ ");
    return false;
  } catch (error) {
    appendUiLog("播放前校验失败", error.message || error, "❌ ");
    return false;
  }
}

async function playCompleted(id) {
  selectCompleted(id);
  const item = (frontendState.completed_items || []).find(row => row.id === id);
  const requestToken = ++previewRequestToken;
  if (!item || !item.local_path) {
    appendUiLog("文件不存在或已被删除", "", "❌ ");
    return;
  }
  if (!(await validateMediaForPreview(id)) || requestToken !== previewRequestToken) return;
  if (!shouldUseBuiltinPlayer()) {
    currentPlayingId = id;
    clearImageAutoAdvanceTimer();
    updateMediaControls();
    frontendAction("open_file", { id });
    return;
  }
  currentPlayingId = id;
  const video = byId("videoPlayer");
  const placeholder = byId("previewArea");
  if (isImageItem(item)) {
    video.pause();
    video.removeAttribute("src");
    video.style.display = "none";
    placeholder.innerHTML = `<img class="preview-image" src="${mediaUrl(id)}" alt="${escAttr(item.title || item.filename || "")}" />`;
    placeholder.style.display = "flex";
    scheduleImageAutoAdvance(id);
    updateMediaControls(video);
    return;
  }
  clearImageAutoAdvanceTimer();
  placeholder.textContent = "";
  video.src = mediaUrl(id);
  setupPlayerEvents(video, id);
  video.style.display = "block";
  placeholder.style.display = "none";
  updateMediaControls(video);
  video.play().catch(error => appendPlaybackFailure(item, error));
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
    appendUiLog(text ? "Trace ID 已复制" : "未找到 Trace ID");
  });
}

function appendLog(message) {
  const now = formatLocalDateTime();
  frontendState.log_items = frontendState.log_items || [];
  frontendState.log_items.push({ time: now, level: "INFO", source: "WebUI", thread: "browser", trace_id: "", message_summary: String(message), message: String(message), detail: "", stack: "" });
  trimFrontendLogItems();
  const legacyPanel = byId("logPanel");
  if (legacyPanel) {
    const line = document.createElement("div");
    line.textContent = translateStructuredLogText(message);
    legacyPanel.appendChild(line);
  }
  scheduleRenderSections(["log_items", "app_status"]);
}

function currentDownloadDirectory() {
  const basic = (frontendState.settings_snapshot || {})["基础设置"] || {};
  return String(basic.download_directory || basic.save_directory || "");
}

function setDirStatus(message, tone = "") {
  const status = byId("dirStatus");
  if (!status) return;
  status.textContent = translateUiText(message || "");
  status.dataset.tone = tone || "";
}

function setDirBusy(busy) {
  ["dirGoBtn", "dirParentBtn", "dirRefreshBtn", "dirConfirmBtn"].forEach(id => {
    const button = byId(id);
    if (button) button.disabled = !!busy;
  });
}

function installDirDialogHandlers() {
  const input = byId("dirInput");
  if (input && !input.dataset.bound) {
    input.dataset.bound = "true";
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        dirBrowsePath();
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancelDirDialog();
      }
    });
  }
  for (const id of ["dirList", "dirDrivesList"]) {
    const list = byId(id);
    if (!list || list.dataset.bound) continue;
    list.dataset.bound = "true";
    list.addEventListener("click", event => {
      const button = event.target && event.target.closest ? event.target.closest("[data-dir-path]") : null;
      if (!button) return;
      selectDirPath(button.dataset.dirPath || "");
    });
    list.addEventListener("dblclick", event => {
      const button = event.target && event.target.closest ? event.target.closest("[data-dir-path]") : null;
      if (!button) return;
      dirLoadPath(button.dataset.dirPath || "");
    });
  }
}

function updateDirStaticText() {
  const textMap = {
    dirTitle: "选择保存目录",
    dirGoBtn: "跳转",
    dirParentBtn: "上一级",
    dirCancelBtn: "取消",
    dirConfirmBtn: "选择此目录",
  };
  for (const [id, label] of Object.entries(textMap)) {
    const element = byId(id);
    if (element) element.textContent = t(label);
  }
  const refresh = byId("dirRefreshBtn");
  if (refresh) {
    refresh.title = t("刷新");
    refresh.setAttribute("aria-label", t("刷新"));
  }
  const input = byId("dirInput");
  if (input) input.placeholder = t("输入目录路径");
}

function dirEntryHtml(entry, kind = "folder") {
  const path = String(entry && entry.path || "");
  const name = String(entry && entry.name || path || "");
  return `
    <button class="dir-entry" type="button" data-dir-path="${escAttr(path)}" data-dir-kind="${escAttr(kind)}" title="${escAttr(path)}">
      <img src="/ui-icon/action_open_directory.png" alt="" />
      <span>${esc(name)}</span>
    </button>
  `;
}

function renderDirEntries(data) {
  const drives = Array.isArray(data.drives) ? data.drives : [];
  const subdirs = Array.isArray(data.subdirs) ? data.subdirs : [];
  const drivesList = byId("dirDrivesList");
  const dirList = byId("dirList");
  if (drivesList) {
    drivesList.innerHTML = drives.length
      ? drives.map(entry => dirEntryHtml(entry, "root")).join("")
      : `<div class="dir-empty">${esc(t("无可用根目录"))}</div>`;
  }
  if (dirList) {
    dirList.innerHTML = subdirs.length
      ? subdirs.map(entry => dirEntryHtml(entry, "folder")).join("")
      : `<div class="dir-empty">${esc(t("没有可进入的子目录"))}</div>`;
  }
}

function selectDirPath(path) {
  dirSelectedPath = String(path || "");
  const input = byId("dirInput");
  if (input && dirSelectedPath) input.value = dirSelectedPath;
  document.querySelectorAll(".dir-entry.selected").forEach(item => item.classList.remove("selected"));
  const selectedEntry = dirSelectedPath
    ? Array.from(document.querySelectorAll(".dir-entry")).find(item => item.dataset.dirPath === dirSelectedPath)
    : null;
  if (selectedEntry) selectedEntry.classList.add("selected");
  if (dirSelectedPath) setDirStatus("已选择目录", "ok");
}

async function onChangeDirClicked() {
  await showDirDialog();
}

async function showDirDialog() {
  updateDirStaticText();
  installDirDialogHandlers();
  const modal = byId("dirModal");
  const input = byId("dirInput");
  const startPath = localStorage.getItem("dir_last_browsed") || currentDownloadDirectory();
  if (input) input.value = startPath;
  modal.style.display = "flex";
  requestAnimationFrame(() => input && input.focus({ preventScroll: true }));
  await dirLoadPath(startPath);
}

async function dirLoadPath(path = "") {
  const target = String(path || byId("dirInput")?.value || "").trim();
  setDirBusy(true);
  setDirStatus("正在加载目录...", "loading");
  try {
    const query = target ? `?path=${encodeURIComponent(target)}` : "";
    const response = await fetch(`/api/dir/list${query}`, { cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error || data.status === "error") {
      throw new Error(data.error || data.message || `HTTP ${response.status}`);
    }
    dirCurrentPath = String(data.current || target || "");
    dirSelectedPath = dirCurrentPath;
    dirParentPath = String(data.parent || "");
    if (dirCurrentPath) localStorage.setItem("dir_last_browsed", dirCurrentPath);
    const input = byId("dirInput");
    if (input) input.value = dirCurrentPath;
    renderDirEntries(data);
    setDirStatus("单击选择，双击进入子目录", "ok");
  } catch (error) {
    renderDirEntries({ drives: [], subdirs: [] });
    setDirStatus(`目录加载失败：${error.message || error}`, "error");
  } finally {
    setDirBusy(false);
  }
}

function dirBrowsePath() {
  return dirLoadPath(byId("dirInput")?.value || "");
}

function dirGoParent() {
  if (!dirParentPath) {
    setDirStatus("当前目录没有可访问的上一级", "error");
    return Promise.resolve();
  }
  return dirLoadPath(dirParentPath);
}

function dirRefresh() {
  return dirLoadPath(dirCurrentPath || byId("dirInput")?.value || "");
}

async function confirmDirDialog() {
  const directory = String(dirSelectedPath || byId("dirInput")?.value || "").trim();
  if (!directory) {
    setDirStatus("目录路径不能为空", "error");
    return;
  }
  setDirBusy(true);
  setDirStatus("正在切换目录...", "loading");
  try {
    const response = await fetch("/api/dir/change", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directory }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error || data.status === "error") {
      throw new Error(data.error || data.message || `HTTP ${response.status}`);
    }
    closePreview();
    const basic = ((frontendState.settings_snapshot ||= {})["基础设置"] ||= {});
    basic.download_directory = String(data.directory || directory);
    localStorage.setItem("dir_last_browsed", basic.download_directory);
    byId("dirModal").style.display = "none";
    appendLog(translateUiText(data.message || "目录已变更"));
    await fetchFrontendState();
  } catch (error) {
    setDirStatus(`切换目录失败：${error.message || error}`, "error");
  } finally {
    setDirBusy(false);
  }
}

function cancelDirDialog() {
  byId("dirModal").style.display = "none";
}

function fileAssociationLabels() {
  return {
    title: "绑定默认打开方式",
    description: "选择要注册到 Windows 默认应用的资源类型。Windows 可能会要求在系统默认应用页再次确认。",
    video: "视频资源（mp4、mkv、avi、mov、webm 等）",
    image: "图片资源（jpg、png、gif、webp、bmp 等）",
    status: "生效方式：注册成功后会立即影响之后的系统打开行为；若 Windows 拦截，程序会打开默认应用设置页供你确认。",
    cancel: "取消",
    confirm: "绑定",
  };
}

function applyFileAssociationLanguage() {
  const labels = fileAssociationLabels();
  const title = byId("associationTitle");
  const description = byId("associationDescription");
  const status = byId("associationStatus");
  const videoLabel = document.querySelector("#fileAssociationModal label[for='associationVideo'] span")
    || document.querySelector("#associationVideo + span");
  const imageLabel = document.querySelector("#fileAssociationModal label[for='associationImage'] span")
    || document.querySelector("#associationImage + span");
  if (title) title.textContent = t(labels.title);
  if (description) description.textContent = t(labels.description);
  if (status) status.textContent = t(labels.status);
  if (videoLabel) videoLabel.textContent = t(labels.video);
  if (imageLabel) imageLabel.textContent = t(labels.image);
  const cancel = byId("associationCancelBtn");
  const confirm = byId("associationConfirmBtn");
  if (cancel) cancel.textContent = t(labels.cancel);
  if (confirm) confirm.textContent = t(labels.confirm);
}

function showFileAssociationModal() {
  applyFileAssociationLanguage();
  const modal = byId("fileAssociationModal");
  const video = byId("associationVideo");
  const image = byId("associationImage");
  if (video) video.checked = true;
  if (image) image.checked = true;
  modal.style.display = "flex";
  requestAnimationFrame(() => {
    if (modal.style.display === "flex") byId("associationConfirmBtn").focus({ preventScroll: true });
  });
}

function cancelFileAssociationModal() {
  byId("fileAssociationModal").style.display = "none";
}

function confirmFileAssociationModal() {
  const includeVideo = !!(byId("associationVideo") && byId("associationVideo").checked);
  const includeImage = !!(byId("associationImage") && byId("associationImage").checked);
  byId("fileAssociationModal").style.display = "none";
  frontendAction("register_file_associations", { include_video: includeVideo, include_image: includeImage });
}

function isFileAssociationModalOpen() {
  const modal = byId("fileAssociationModal");
  return !!modal && modal.style.display === "flex";
}

function handleFileAssociationModalShortcut(event) {
  if (!isFileAssociationModalOpen()) return false;
  if (!["Enter", "Escape"].includes(event.key)) return false;
  if (event.key === "Enter" && isTextEntryTarget(event.target)) return false;
  event.preventDefault();
  event.stopPropagation();
  if (event.key === "Enter") confirmFileAssociationModal();
  else cancelFileAssociationModal();
  return true;
}

function selectionHeaderText(count) {
  return t("共扫描到 {count} 个资源，请勾选需要下载的项目：").replace("{count}", String(count));
}

function selectionItemTitle(item, index) {
  if (item && typeof item === "object") return String(item.title || item.name || `项目 ${index + 1}`);
  const text = String(item ?? "").trim();
  return text || `项目 ${index + 1}`;
}

function selectionRowHtml(item, index) {
  const rawTitle = selectionItemTitle(item, index);
  const title = esc(rawTitle);
  return `
    <tr class="selection-row" data-index="${index}" onclick="toggleSelectionItem(${index}, event)">
      <td><input class="selection-checkbox" type="checkbox" data-index="${index}" checked tabindex="-1" aria-checked="true" aria-label="${escAttr(t("选择"))} ${index + 1}" onmousedown="event.preventDefault()" onclick="event.preventDefault();event.stopPropagation();toggleSelectionItem(${index})"></td>
      <td class="selection-title-cell" title="${escAttr(rawTitle)}">${title}</td>
    </tr>
  `;
}

function syncSelectionRowState(index) {
  const checkbox = document.querySelector(`#selectionBody input[data-index="${index}"]`);
  const row = document.querySelector(`#selectionBody tr[data-index="${index}"]`);
  if (!checkbox || !row) return;
  row.classList.toggle("unchecked", !checkbox.checked);
  checkbox.setAttribute("aria-checked", checkbox.checked ? "true" : "false");
}

function toggleSelectionItem(index, event) {
  const checkbox = document.querySelector(`#selectionBody input[data-index="${index}"]`);
  if (!checkbox) return;
  if (event && event.target === checkbox) {
    syncSelectionRowState(index);
    return;
  }
  checkbox.checked = !checkbox.checked;
  syncSelectionRowState(index);
}

function selectAllSelectionItems() {
  document.querySelectorAll("#selectionBody input[type='checkbox']").forEach(input => {
    input.checked = true;
    syncSelectionRowState(Number(input.dataset.index));
  });
}

function invertSelectionItems() {
  document.querySelectorAll("#selectionBody input[type='checkbox']").forEach(input => {
    input.checked = !input.checked;
    syncSelectionRowState(Number(input.dataset.index));
  });
}

function showSelectionModal(items) {
  selectionItems = Array.isArray(items) ? items : [];
  byId("selectionTitle").textContent = t("任务清单确认");
  byId("selectionHeader").textContent = selectionHeaderText(selectionItems.length);
  const selectionHeadCells = document.querySelectorAll(".selection-table thead th");
  if (selectionHeadCells[0]) selectionHeadCells[0].textContent = t("选择");
  if (selectionHeadCells[1]) selectionHeadCells[1].textContent = t("视频标题 / 描述");
  byId("selectionAllBtn").textContent = t("全选");
  byId("selectionInvertBtn").textContent = t("反选");
  byId("selectionCancelBtn").textContent = t("取消任务");
  byId("selectionConfirmBtn").textContent = t("开始下载");
  byId("selectionBody").innerHTML = selectionItems.map(selectionRowHtml).join("");
  const modal = byId("selectionModal");
  modal.style.display = "flex";
  requestAnimationFrame(() => {
    if (modal.style.display === "flex") byId("selectionConfirmBtn").focus({ preventScroll: true });
  });
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

function isSelectionModalOpen() {
  const modal = byId("selectionModal");
  return !!modal && modal.style.display === "flex";
}

function isTextEntryTarget(target) {
  if (!target || !target.tagName) return false;
  if (target.isContentEditable) return true;
  const tagName = String(target.tagName).toUpperCase();
  if (tagName === "INPUT") {
    const inputType = String(target.type || "text").toLowerCase();
    return !["button", "checkbox", "color", "file", "radio", "range", "reset", "submit"].includes(inputType);
  }
  return ["SELECT", "TEXTAREA"].includes(tagName);
}

function handleSelectionModalShortcut(event) {
  if (!isSelectionModalOpen()) return false;
  if (!["Enter", "Escape"].includes(event.key)) return false;
  if (event.key === "Enter" && isTextEntryTarget(event.target)) return false;
  event.preventDefault();
  event.stopPropagation();
  if (event.key === "Enter") confirmSelection();
  else cancelSelection();
  return true;
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
  const configuredLanguage = String(appearance.language || "").trim();
  const language = ["zh-CN", "en-US", "zh-TW"].includes(configuredLanguage)
    ? configuredLanguage
    : currentLanguage();
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
  if (themeButton) {
    const iconFile = dark ? "action_theme_night.png" : "action_theme_light.png";
    themeButton.innerHTML = `<img src="/ui-icon/${iconFile}" alt="" />`;
    themeButton.setAttribute("aria-label", t("切换主题"));
  }
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
function mediaActionIconSrc(action) {
  const manifest = iconManifest || {};
  const actions = manifest.actions || ACTION_ICON_FILES;
  const file = actions[action] || ACTION_ICON_FILES[action] || manifest.fallback || "view_grid.png";
  const route = String(manifest.route || "/ui-icon").replace(/\/+$/, "");
  return `${route}/${String(file).replace(/^\/+/, "")}`;
}
function setPlayButtonState(playing, disabled = false) {
  const button = byId("playBtn");
  if (!button) return;
  button.disabled = !!disabled;
  const action = playing ? "pause" : "play";
  const label = playing ? t("暂停") : t("播放");
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = `<img src="${escAttr(mediaActionIconSrc(action))}" alt="" />`;
}
function mediaHasVideoSource(player) {
  return !!(player && (player.currentSrc || player.getAttribute("src")));
}
function mediaDuration(player) {
  const duration = Number(player && player.duration);
  return Number.isFinite(duration) && duration > 0 ? duration : 0;
}
function mediaCurrentTime(player) {
  const current = Number(player && player.currentTime);
  return Number.isFinite(current) && current > 0 ? current : 0;
}
function hasPreviewContent() {
  const player = byId("videoPlayer");
  const placeholder = byId("previewArea");
  return mediaHasVideoSource(player) || !!(placeholder && placeholder.querySelector(".preview-image"));
}
function completedPreviewOrder() {
  return (frontendState.completed_items || []).map(item => item.id).filter(id => id !== undefined && id !== null && String(id));
}
function adjacentCompletedId(currentId, direction, wrap = true) {
  const order = completedPreviewOrder();
  if (!order.length) return "";
  const normalized = String(currentId || "");
  const index = order.findIndex(id => String(id) === normalized);
  if (index < 0) return direction >= 0 ? order[0] : order[order.length - 1];
  let nextIndex = index + (direction >= 0 ? 1 : -1);
  if (wrap) nextIndex = (nextIndex + order.length) % order.length;
  if (nextIndex < 0 || nextIndex >= order.length) return "";
  return order[nextIndex];
}
function updateFullscreenButtonState() {
  const button = byId("fullscreenBtn");
  if (!button) return;
  button.textContent = `[ ${t(isFullscreenMode ? "退出" : "全屏")} ]`;
}
function updateMediaControls(player = byId("videoPlayer")) {
  const slider = byId("seekSlider");
  const label = byId("timeLabel");
  const hasVideo = mediaHasVideoSource(player);
  const canStartPreview = !!(currentPlayingId || selected.completed || selectedVideoId);
  const duration = hasVideo ? mediaDuration(player) : 0;
  const current = hasVideo ? mediaCurrentTime(player) : 0;
  const dragging = slider && slider.dataset.dragging === "1";
  if (slider) {
    slider.disabled = !hasVideo || duration <= 0;
    slider.max = String(Math.max(0, Math.floor(duration)));
    if (!dragging) slider.value = String(Math.min(Math.floor(current), Math.floor(duration || current)));
  }
  if (label) {
    label.textContent = hasVideo ? `${fmtTime(current)} / ${fmtTime(duration)}` : "00:00";
  }
  setPlayButtonState(hasVideo && !player.paused && !player.ended, !hasVideo && !canStartPreview);
  updateNavBtnsState();
  updateFullscreenButtonState();
}
function installMediaControlHandlers() {
  const slider = byId("seekSlider");
  if (slider && slider.dataset.mediaHandlers !== "1") {
    slider.dataset.mediaHandlers = "1";
    const beginDrag = () => { slider.dataset.dragging = "1"; };
    const finishDrag = () => {
      if (slider.dataset.dragging === "1") onSeekCommit(slider.value);
      slider.dataset.dragging = "";
    };
    slider.addEventListener("pointerdown", beginDrag);
    slider.addEventListener("touchstart", beginDrag, { passive: true });
    slider.addEventListener("pointerup", finishDrag);
    slider.addEventListener("pointercancel", finishDrag);
    slider.addEventListener("touchend", finishDrag);
  }
  const player = byId("videoPlayer");
  if (player && player.dataset.mediaHandlers !== "1") {
    player.dataset.mediaHandlers = "1";
    player.addEventListener("play", () => updateMediaControls(player));
    player.addEventListener("pause", () => updateMediaControls(player));
    player.addEventListener("durationchange", () => updateMediaControls(player));
  }
}
function closePreview() {
  previewRequestToken += 1;
  clearImageAutoAdvanceTimer();
  const video = byId("videoPlayer");
  video.pause();
  video.removeAttribute("src");
  video.load();
  video.style.display = "none";
  const placeholder = byId("previewArea");
  placeholder.textContent = "";
  placeholder.style.display = "flex";
  currentPlayingId = null;
  updateMediaControls(video);
}
function updateNavBtnsState() {
  const order = completedPreviewOrder();
  const disabled = order.length <= 1;
  const prev = byId("prevBtn");
  const next = byId("nextBtn");
  if (prev) prev.disabled = disabled;
  if (next) next.disabled = disabled;
}
function switchPreview(direction) {
  const current = currentPlayingId || selected.completed || selectedVideoId;
  const nextId = adjacentCompletedId(current, Number(direction) || 1, true);
  if (nextId) void playCompleted(nextId);
}
function onSeekInput(value) {
  const player = byId("videoPlayer");
  if (!mediaHasVideoSource(player)) {
    updateMediaControls(player);
    return;
  }
  const duration = mediaDuration(player);
  const nextTime = Math.max(0, Math.min(Number(value) || 0, duration || Number(value) || 0));
  const label = byId("timeLabel");
  if (label) label.textContent = `${fmtTime(nextTime)} / ${fmtTime(duration)}`;
}
function onSeekCommit(value) {
  const player = byId("videoPlayer");
  if (!mediaHasVideoSource(player)) {
    updateMediaControls(player);
    return;
  }
  const duration = mediaDuration(player);
  const nextTime = Math.max(0, Math.min(Number(value) || 0, duration || Number(value) || 0));
  if (Number.isFinite(nextTime)) player.currentTime = nextTime;
  const slider = byId("seekSlider");
  if (slider) slider.dataset.dragging = "";
  updateMediaControls(player);
}
function prepareDeleteItem(id) {
  const videoId = String(id || "");
  if (videoId && String(currentPlayingId || "") === videoId) closePreview();
}
function deleteVideo(id) {
  prepareDeleteItem(id);
  if (typeof window !== "undefined" && window.sendWS !== defaultSendWS && typeof window.sendWS === "function") {
    window.sendWS("delete_video", { video_id: id });
    return;
  }
  frontendAction("delete_item", { id });
}
async function previewVideo(id) {
  const oldId = selectedVideoId;
  await playCompleted(id);
  updateSelection(oldId, id);
  const player = byId("videoPlayer");
  setupPlayerEvents(player, id);
}
function setupPlayerEvents(player, sourceId) {
  if (!player) return;
  const item = completedItemById(sourceId) || {};
  player.onloadedmetadata = () => {
    reportCompletedPlayerMetadata(sourceId, player);
    restoreWebPlaybackPosition(sourceId, player);
    updateMediaControls(player);
  };
  player.ondurationchange = () => updateMediaControls(player);
  player.onplay = () => updateMediaControls(player);
  player.onpause = () => updateMediaControls(player);
  player.ontimeupdate = () => {
    rememberWebPlaybackPosition(sourceId, player);
    updateMediaControls(player);
  };
  player.onseeked = () => updateMediaControls(player);
  player.onerror = () => {
    updateMediaControls(player);
    if (currentPlayingId === sourceId) appendPlaybackFailure(item, player.error || "media error");
  };
  player.onended = () => {
    removePlaybackPosition(sourceId);
    updateMediaControls(player);
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

function hasDisplayDuration(value) { const service = playbackStateService(); if (service) return service.hasDisplayDuration(value); const text = String(value || "").trim(); return !!text && text !== "--" && text !== "\u68c0\u6d4b\u4e2d" && text !== "00:00:00"; }
function isRealResolution(value) { return playbackStateService()?.isRealResolution(value) ?? /^\d{2,5}\s*x\s*\d{2,5}$/i.test(String(value || "").trim()); }
function autoplayNextPreview() {
  const nextId = adjacentCompletedId(currentPlayingId, 1, false);
  if (nextId) void playCompleted(nextId);
}
function togglePlay() {
  const video = byId("videoPlayer");
  if (!mediaHasVideoSource(video)) {
    const id = currentPlayingId || selected.completed || selectedVideoId;
    if (id) void playCompleted(id);
    return;
  }
  if (video.paused) video.play().catch(error => appendPlaybackFailure(completedItemById(currentPlayingId), error)); else video.pause();
  updateMediaControls(video);
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
function fmtTime(seconds) { return playbackStateService()?.fmtTime(seconds) || `${String(Math.floor((Number(seconds) || 0) / 60)).padStart(2, "0")}:${String(Math.floor((Number(seconds) || 0) % 60)).padStart(2, "0")}`; }
function fmtClockTime(seconds) { return playbackStateService()?.fmtClockTime(seconds) || "00:00:00"; }
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
  if (handleSelectionModalShortcut(event)) return;
  if (handleFileAssociationModalShortcut(event)) return;
  if (event.key === "Escape") {
    if (byId("dirModal").style.display === "flex") cancelDirDialog();
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
}, true);

document.addEventListener("fullscreenchange", () => {
  const panel = byId("previewPanel");
  isFullscreenMode = !!panel && document.fullscreenElement === panel;
  if (panel) panel.classList.toggle("is-fullscreen", isFullscreenMode);
  updateFullscreenButtonState();
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
