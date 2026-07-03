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
const LOG_RENDER_ROW_BUDGET = 300;
let logFilters = {
  category: "all",
  level: "全部",
  time: "近 24 小时",
  platform: "全部",
  trace: "",
  keyword: "",
};
let currentSettingsGroup = localStorage.getItem("webui_settings_group") || "基础设置";
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
  for (const id of doomed) removePlaybackPosition(id);
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

function configureCustomSelectHelpers() {
  if (window.UcpCustomSelect) window.UcpCustomSelect.configure({ translate: translateUiText, esc, escAttr });
}

function configureMediaDisplayHelpers() {
  if (window.UcpMediaDisplay) window.UcpMediaDisplay.configure({ esc });
}

function configureSettingsRenderHelpers() {
  if (window.UcpSettingsRender) {
    window.UcpSettingsRender.configure({
      esc,
      escAttr,
      t,
      optionLabel,
      countOptionLabel,
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

function renderQueue() {
  byId("queuePath").textContent = (((frontendState.settings_snapshot || {})["基础设置"] || {}).download_directory || "");
  const allItems = frontendState.queue_items || [];
  const totalPages = Math.max(1, Math.ceil(allItems.length / queuePageSize));
  queuePage = Math.max(1, Math.min(queuePage, totalPages));
  const start = (queuePage - 1) * queuePageSize;
  const items = allItems.slice(start, start + queuePageSize);
  patchTableRows("queueBody", items, item => item.id, item => taskRenderService().queueRow(item));
  byId("queueTotal").textContent = `\u5171 ${allItems.length} \u9879`;
  byId("queuePageNow").textContent = String(queuePage);
  byId("queueTotalPages").textContent = String(totalPages);
  byId("queuePageSize").value = String(queuePageSize);
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
  patchTableRows("activeBody", items, item => item.id, item => taskRenderService().activeRow(item, selected.active));
  byId("activeSummary").textContent = `\u5f53\u524d\u8fd0\u884c\uff1a${items.length} \u4e2a\u4efb\u52a1`;
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
  }
  if (concurrent) {
    const maxConcurrent = normalizeDownloadConcurrency(options.max_concurrent);
    concurrent.value = String(maxConcurrent);
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
  const item = (frontendState.active_downloads || []).find(row => row.id === selected.active) || (frontendState.active_downloads || [])[0];
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
  if (!selected.completed && items.length) selected.completed = items[0].id;
  patchTableRows("completedBody", items, item => item.id, item => taskRenderService().completedRow(item, selected.completed));
  byId("completedTotal").textContent = `\u5171 ${allItems.length} \u9879`;
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
  setHtmlIfChanged("completedDetail", taskRenderService().completedDetailHtml(item));
}

function displayMetadataValue(value, pending = false) {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.displayMetadataValue(value, pending) : (String(value || "").trim() || "--");
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
  if (!selected.failed && items.length) selected.failed = items[0].id;
  patchTableRows("failedBody", items, item => item.id, item => taskRenderService().failedRow(item, selected.failed));
  renderFailedDetail();
}

function selectFailed(id) {
  selected.failed = id;
  renderFailed();
}

function renderFailedDetail() {
  const item = (frontendState.failed_items || []).find(row => row.id === selected.failed) || (frontendState.failed_items || [])[0];
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
function renderLogs() {
  syncLogFilterControls();
  const filteredItems = filteredLogItems();
  const items = visibleLogItems(filteredItems);
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
  renderLogDetail(items);
}

function logItemId(item) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.logItemId(item) : String(item.id || "");
}

function selectLog(id) {
  selected.log = String(id);
  renderLogs();
}

function renderLogDetail(itemsOverride) {
  const items = Array.isArray(itemsOverride) ? itemsOverride : visibleLogItems(filteredLogItems());
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
  return window.UcpLogDisplay
    ? window.UcpLogDisplay.filteredLogItems(frontendState.log_items || [], logFilters)
    : (frontendState.log_items || []).filter(logMatchesFilters);
}

function visibleLogItems(items) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.visibleLogItems(items, LOG_RENDER_ROW_BUDGET) : [];
}

function logMatchesFilters(item) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.logMatchesFilters(item, logFilters) : true;
}

function logCategory(item) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.logCategory(item) : "system";
}

function logSearchText(item) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.logSearchText(item) : "";
}

function logMatchesTime(item) {
  return window.UcpLogDisplay ? window.UcpLogDisplay.logMatchesTime(item, logFilters.time) : true;
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

function isPlatformSettingsVisible() {
  return currentPage === "settings" && currentSettingsGroup === "平台设置";
}

function maybeRefreshPlatformAuthStatus(force = false) {
  if (!isPlatformSettingsVisible()) return;
  frontendAction("refresh_platform_auth_status", { force: Boolean(force) });
}

function switchSettingsGroup(group) {
  if (!group) return;
  const sameGroup = group === currentSettingsGroup;
  if (!sameGroup) {
    currentSettingsGroup = group;
    localStorage.setItem("webui_settings_group", group);
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
  if (section === "playback") {
    const playback = ((frontendState.settings_snapshot || {})["\u64ad\u653e\u8bbe\u7f6e"] ||= {});
    playback[key] = key === "image_auto_advance_interval_seconds" ? Number(value || 5) : value;
    if (currentPage === "settings" && currentSettingsGroup === "\u64ad\u653e\u8bbe\u7f6e") renderSettings(true);
    const currentItem = completedItemById(currentPlayingId);
    if (currentItem && isImageItem(currentItem)) scheduleImageAutoAdvance(currentPlayingId);
  }
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
  renderCounts();
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
  const modal = byId("selectionModal");
  modal.style.display = "flex";
  requestAnimationFrame(() => {
    if (modal.style.display === "flex") modal.focus({ preventScroll: true });
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

function hasDisplayDuration(value) { const service = playbackStateService(); if (service) return service.hasDisplayDuration(value); const text = String(value || "").trim(); return !!text && text !== "--" && text !== "\u68c0\u6d4b\u4e2d" && text !== "00:00:00"; }
function isRealResolution(value) { return playbackStateService()?.isRealResolution(value) ?? /^\d{2,5}\s*x\s*\d{2,5}$/i.test(String(value || "").trim()); }
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
