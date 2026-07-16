let frontendState = buildInitialState();
let currentPage = "queue";
let platforms = [];
let platformLoadDegraded = false;
let selected = {
  active: "",
  completed: "",
  failed: "",
  tool: "link_parser",
};
let systemThemeListenerRegistered = false;
/*
 * `__ucrawlFrontendStateLoaded` 在本生命周期首次接受可用的 REST 或 WebSocket 状态后置为 `true`，重试不会清零。
 * `__ucrawlFrontendStateSettled` 表示最近一次未被替代的 REST 全量快照请求已经结束，重试开始时重置为 `false`。
 * `frontendLoadState` 驱动 `loading`、`ready`、`error`：WebSocket 可在 REST 结束前先推进到 `ready`，
 * REST 结束时仅在仍无已加载状态的情况下进入 `error`。重试采用 `stale-while-revalidate`，
 * 进入 `loading` 不清空 `frontendState`；已有状态时即使 REST 失败也继续显示旧数据。
 */
window.__ucrawlFrontendStateLoaded = false;
window.__ucrawlFrontendStateSettled = false;
let frontendLoadState = "loading";

function buildInitialState() {
  return {
    version: 0,
    pages: [],
    queue_items: [],
    active_downloads: [],
    completed_items: [],
    failed_items: [],
    log_items: [],
    settings_snapshot: {},
    settings_contract: {},
    download_options: {},
    toolbox_items: [],
    toolbox_recent_items: [],
    app_status: {
      running_state: "加载中",
      download_speed: "0 B/s",
      queue_count: 0,
      active_count: 0,
      completed_count: 0,
      failed_count: 0,
      version: "v3.6.17",
    },
  };
}

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
  return true;
}

function i18nService() {
  return window.UcpI18n || null;
}

function logI18nService() {
  return window.UcpLogI18n || null;
}

function logCenterService() {
  if (!window.UcpLogCenter) throw new Error("UcpLogCenter is unavailable");
  return window.UcpLogCenter;
}

function listPagesService() {
  if (!window.UcpListPages) throw new Error("UcpListPages is unavailable");
  return window.UcpListPages;
}

function settingsControllerService() {
  if (!window.UcpSettingsController) throw new Error("UcpSettingsController is unavailable");
  return window.UcpSettingsController;
}

function dialogControllerService() {
  if (!window.UcpDialogController) throw new Error("UcpDialogController is unavailable");
  return window.UcpDialogController;
}

function playbackControllerService() {
  if (!window.UcpPlaybackController) throw new Error("UcpPlaybackController is unavailable");
  return window.UcpPlaybackController;
}

function frontendRuntimeService() {
  if (!window.UcpFrontendRuntime) throw new Error("UcpFrontendRuntime is unavailable");
  return window.UcpFrontendRuntime;
}

function listPageDependencies() {
  return {
    getState: () => frontendState,
    getSelection: domain => domain === "queue" ? selectedVideoId : selected[domain],
    setSelection: (domain, id, options = {}) => {
      const value = String(id || "");
      if (domain === "queue") {
        selectedVideoId = value || null;
        return;
      }
      if (Object.prototype.hasOwnProperty.call(selected, domain)) selected[domain] = value;
      if (domain === "completed" && options.activate === true) selectedVideoId = value || null;
    },
    t,
    esc,
    escAttr,
    byId,
    frontendAction,
    request: (url, options) => fetch(url, options),
    writeClipboard: text => {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") return Promise.resolve(false);
      return navigator.clipboard.writeText(String(text ?? "")).then(() => true);
    },
    appendUiLog,
    playCompleted: id => playbackControllerService().playCompleted(id),
    renderStatus: () => {
      renderStatus();
      playbackControllerService().updateControls();
    },
  };
}

function configureListPagesHelpers() {
  return listPagesService().configure(listPageDependencies());
}

function logCenterDependencies() {
  return {
    getState: () => frontendState,
    getIconManifest: () => iconManifest,
    getLanguage: currentLanguage,
    t,
    esc,
    escAttr,
    byId,
    writeClipboard,
    runOperation: performLogOperation,
    onFiltersChange: () => {},
  };
}

function configureLogCenterHelpers() {
  return logCenterService().configure(logCenterDependencies());
}

function patchSettingSnapshot(group, key, value) {
  if (!group || !key) return false;
  const snapshot = (frontendState.settings_snapshot ||= {});
  const section = (snapshot[group] ||= {});
  if (!section || typeof section !== "object" || Array.isArray(section)) return false;
  section[key] = value;
  return true;
}

function patchPlatformSettingSnapshot(platformId, key, value) {
  if (!platformId || !key) return false;
  const rows = (frontendState.settings_snapshot || {})["平台设置"];
  if (!Array.isArray(rows)) return false;
  const row = rows.find(item => String(item.id || "") === String(platformId));
  if (!row) return false;
  row[key] = value;
  return true;
}

function syncSettingsAppearance(change = {}) {
  if (change.applyAppearance) {
    applyAppearance((frontendState.settings_snapshot || {})["外观设置"] || {});
  }
  if (change.refreshLanguage) {
    renderSignatures = {};
    renderAll();
  } else if (change.renderCurrentPage) {
    renderCurrentPage();
  }
  if (change.reschedulePlayback) {
    playbackControllerService().rescheduleImageAutoAdvance();
  }
}

function settingsControllerDependencies() {
  return {
    getState: () => ({ ...frontendState, icon_manifest: iconManifest }),
    t,
    optionLabel,
    byId,
    sendWS: (action, payload) => frontendAction(action, payload),
    patchSetting: patchSettingSnapshot,
    patchPlatformSetting: patchPlatformSettingSnapshot,
    syncAppearance: syncSettingsAppearance,
    enhanceSelects,
  };
}

function dialogControllerDependencies() {
  return {
    getState: () => frontendState,
    t,
    esc,
    escAttr,
    byId,
    frontendAction: (action, payload) => frontendAction(action, payload),
    sendWS: (type, payload) => sendWS(type, payload),
    appendUiLog: message => appendLog(message),
    patchSetting: patchSettingSnapshot,
    translateText: translateUiText,
    closePreview: () => playbackControllerService().closePreview(),
    fetchState: () => frontendRuntimeService().fetchState(),
  };
}

function configureSettingsControllerHelpers() {
  return settingsControllerService().configure(settingsControllerDependencies());
}

function configureDialogControllerHelpers() {
  return dialogControllerService().configure(dialogControllerDependencies());
}

function patchCompletedMetadata(sourceId, metadata) {
  const item = (frontendState.completed_items || []).find(row => String(row.id) === String(sourceId));
  if (!item) return false;
  const playbackState = window.UcpPlaybackState;
  let changed = false;
  if (metadata.duration && playbackState && !playbackState.hasDisplayDuration(item.duration)) {
    item.duration = metadata.duration;
    changed = true;
  }
  if (metadata.resolution && playbackState && !playbackState.isRealResolution(item.resolution)) {
    item.resolution = metadata.resolution;
    changed = true;
  }
  if (playbackState && playbackState.hasDisplayDuration(item.duration) && playbackState.isRealResolution(item.resolution)) {
    item.metadata_pending = false;
  }
  return changed;
}

function playbackControllerDependencies() {
  return {
    getState: () => ({ ...frontendState, icon_manifest: iconManifest }),
    getSelectedCompletedId: () => selected.completed || selectedVideoId || "",
    setSelectedCompletedId: id => selectCompleted(id),
    patchCompletedMetadata,
    t,
    byId,
    esc,
    frontendAction,
    appendLog,
    renderCompletedDetail,
  };
}

function configurePlaybackControllerHelpers() {
  return playbackControllerService().configure(playbackControllerDependencies());
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

function configureLogI18nHelpers() {
  const service = logI18nService();
  if (!service) return null;
  return service.configure({ currentLanguage, translateUiText, canonicalUiText, getState: () => frontendState });
}

function replaceFrontendState(nextState) {
  frontendState = nextState && typeof nextState === "object" ? nextState : buildInitialState();
  refreshDegradedPlatformsFromSnapshot();
  window.__ucrawlFrontendStateLoaded = true;
  setFrontendLoadState("ready");
}

function removeDeletedSelectionState(ids) {
  const doomed = new Set((ids || []).map(id => String(id)));
  for (const id of doomed) {
    playbackControllerService().prepareDeleteItem(id);
    playbackControllerService().removePlaybackPosition(id);
  }
  for (const key of ["active", "completed", "failed"]) {
    if (doomed.has(String(selected[key] || ""))) selected[key] = "";
  }
  if (doomed.has(String(selectedVideoId || ""))) selectedVideoId = null;
}

function patchRuntimeSection(section, value) {
  if (section === "log_items") {
    trimFrontendLogItems();
    return [];
  }
  if (section === "icon_manifest") {
    updateIconManifest(value);
    return [];
  }
  if (section === "deleted_ids") {
    removeDeletedSelectionState(value);
    return [];
  }
  if (section === "init_state") {
    if (value && typeof value.is_crawling === "boolean") setCrawlUiState(value.is_crawling);
    return [];
  }
  if (section === "platforms") {
    acceptPlatformList(value, { degraded: false, persist: true });
    return [];
  }
  if (section === "config") {
    return { fetchDeltaDelay: 0 };
  }
  if (section === "crawl_state") {
    setCrawlUiState(!!(value && value.is_running));
    return [];
  }
  if (section === "log") {
    appendLog((value && value.message) || "");
    return ["log_items", "app_status"];
  }
  if (section === "select_tasks") {
    showSelectionModal((value && value.items) || []);
    return [];
  }
  if (section === "frontend_action_message") {
    appendLog(translateUiText(value));
    return [];
  }
  if (section === "frontend_action_error") {
    appendLog(translateUiText(value));
    return [];
  }
  return [];
}

function runtimeDependencies() {
  return {
    getState: () => frontendState,
    replaceState: replaceFrontendState,
    buildMockState,
    patchSection: patchRuntimeSection,
    renderSections: renderFrontendSections,
    renderAll,
    onConnected: () => {},
    onSettled: result => {
      const loaded = !!(result && result.loaded) || window.__ucrawlFrontendStateLoaded;
      window.__ucrawlFrontendStateLoaded = loaded;
      window.__ucrawlFrontendStateSettled = true;
      setFrontendLoadState(loaded ? "ready" : "error", result && result.error);
    },
    appendUiLog,
  };
}

let featureModulesConfigured = false;

function configureFeatureModules() {
  if (featureModulesConfigured) return;
  configureI18nHelpers();
  window.UcpLogI18n.configure({
    currentLanguage,
    translateUiText,
    canonicalUiText,
    getState: () => frontendState,
  });
  window.UcpLogCenter.configure(logCenterDependencies());
  window.UcpListPages.configure(listPageDependencies());
  window.UcpSettingsController.configure(settingsControllerDependencies());
  window.UcpDialogController.configure(dialogControllerDependencies());
  window.UcpPlaybackController.configure(playbackControllerDependencies());
  window.UcpFrontendRuntime.configure(runtimeDependencies());
  featureModulesConfigured = true;
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
  if (window.UcpLogCenter) window.UcpLogCenter.render();
}

// 少量旧版浏览器测试仍从全局读取这些兼容状态。
let videos = {};
let videoOrder = [];
let selectedVideoId = null;
let crawlRunning = false;

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
  playbackControllerService().updateControls();
}

let renderSignatures = {};
let scheduleRenderSections = sections => frontendRuntimeService().scheduleSections(sections);
let fetchFrontendState = () => frontendRuntimeService().fetchState();
let fetchFrontendDelta = () => frontendRuntimeService().fetchDelta();
window.fetchFrontendState = (...args) => frontendRuntimeService().fetchState(...args);
window.fetchFrontendDelta = (...args) => frontendRuntimeService().fetchDelta(...args);
window.scheduleRenderSections = (...args) => frontendRuntimeService().scheduleSections(...args);
window.sendWS = (...args) => frontendRuntimeService().send(...args);

function renderFrontendSections(sections) {
  const previousLanguage = document.documentElement.dataset.language || "zh-CN";
  const itemSections = ["queue_items", "active_downloads", "completed_items", "failed_items"];
  if (sections.has("settings_snapshot")) {
    syncAppearanceFromSettings();
    syncPlatformSourceFromSettings();
    playbackControllerService().rescheduleImageAutoAdvance();
    if ((document.documentElement.dataset.language || "zh-CN") !== previousLanguage) {
      renderAll();
      return;
    }
  }
  if (itemSections.some(section => sections.has(section))) {
    rebuildCompatibilityState();
    renderCounts();
  }
  if (sections.has("completed_items")) playbackControllerService().rescheduleImageAutoAdvance();
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
    settingsControllerService().render();
  }
  if (sections.has("settings_snapshot")) updatePlaceholder();
  if ((sections.has("toolbox_items") || sections.has("toolbox_recent_items")) && currentPage === "toolbox") renderToolbox();
  if (sections.has("icon_manifest")) renderCurrentPage();
  if (sections.has("app_status")) renderStatus();
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
  configureFeatureModules();
  restoreTheme();
  restoreLayoutState();
  installDetailResizeHandlers();
  restoreQueueControls();
  loadUiTextCatalogs();
  setFrontendLoadState("loading");
  renderAll();
  loadPlatforms();
  frontendRuntimeService().start();
  dialogControllerService().installDirectoryHandlers();
  playbackControllerService().installMediaControlHandlers();
  playbackControllerService().updateControls();
  document.getElementById("sourceSelect").addEventListener("change", cacheSource);
  document.getElementById("searchInput").addEventListener("keydown", event => {
    if (event.key === "Enter") startCrawl();
  });
});

function setFrontendLoadState(state, detail = "") {
  frontendLoadState = ["loading", "ready", "error"].includes(state) ? state : "error";
  const banner = byId("frontendStateBanner");
  const message = byId("frontendStateMessage");
  const retry = byId("frontendStateRetry");
  const panel = byId("rightPanel");
  if (banner) {
    banner.dataset.state = frontendLoadState;
    banner.hidden = frontendLoadState === "ready";
  }
  if (message) {
    const label = frontendLoadState === "error" ? t("加载状态失败") : t("正在加载应用状态...");
    message.textContent = detail && frontendLoadState === "error" ? `${label}: ${detail}` : label;
  }
  if (retry) {
    retry.textContent = t("重试");
    retry.hidden = frontendLoadState !== "error";
  }
  if (panel) panel.setAttribute("aria-busy", frontendLoadState === "loading" ? "true" : "false");
  setCrawlUiState(crawlRunning);
}

function retryFrontendStateLoad() {
  setFrontendLoadState("loading");
  window.__ucrawlFrontendStateSettled = false;
  return frontendRuntimeService().fetchState();
}

window.retryFrontendStateLoad = retryFrontendStateLoad;

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
      "\u57fa\u7840\u8bbe\u7f6e": { download_directory: "D:\\desktop\\Videos", filename_template: "current", filename_template_label: "\u9ed8\u8ba4", open_after_download: false, show_browser_window: true, default_open_mode: "builtin_player", default_open_mode_label: "\u5185\u7f6e\u64ad\u653e\u5668", _options: { filename_template: [{ value: "current", label: "\u9ed8\u8ba4" }, { value: "{title}", label: "\u6807\u9898" }], default_open_mode: [{ value: "builtin_player", label: "\u5185\u7f6e\u64ad\u653e\u5668" }, { value: "system_default", label: "\u7cfb\u7edf\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f" }] } },
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
      "日志设置": { retention_days: 1, failed_record_retention_days: 7, ui_log_max_display_count: 300, auto_copy_trace_on_error: true, _options: { retention_days: [{ value: "1", label: "1 天（推荐）" }, { value: "3", label: "3 天" }, { value: "5", label: "5 天" }, { value: "7", label: "7 天" }], failed_record_retention_days: [{ value: "3", label: "3 天" }, { value: "7", label: "7 天（推荐）" }, { value: "14", label: "14 天" }, { value: "30", label: "30 天" }], ui_log_max_display_count: [{ value: "100", label: "100 条" }, { value: "300", label: "300 条（推荐）" }, { value: "500", label: "500 条" }] } },
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

async function loadPlatforms() {
  setPlatformLoadState("loading");
  try {
    const response = await fetch("/api/platforms", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const rows = normalizePlatformList(await response.json());
    if (!rows.length) throw new Error("empty platform list");
    acceptPlatformList(rows, { degraded: false, persist: true });
  } catch (error) {
    const fallback = firstPlatformFallback();
    acceptPlatformList(fallback, { degraded: true, persist: false });
    appendUiLog("平台列表加载失败", error.message || error, "⚠️ ");
  }
}

const PLATFORM_CACHE_KEY = "webui_platforms_cache_v1";

function normalizePlatformList(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.flatMap(item => {
    if (!item || typeof item !== "object") return [];
    const id = String(item.id || "").trim();
    if (!id || seen.has(id)) return [];
    seen.add(id);
    return [{ ...item, id, name: String(item.name || id) }];
  });
}

function snapshotPlatformList() {
  const rows = (frontendState.settings_snapshot || {})["平台设置"];
  if (!Array.isArray(rows)) return [];
  return normalizePlatformList(rows.map(row => ({
    id: row.id,
    name: row.name,
    icon_file: (iconManifest.platforms || {})[String(row.id || "").toLowerCase()] || "platform_web.png",
  })));
}

function cachedPlatformList() {
  try {
    return normalizePlatformList(JSON.parse(localStorage.getItem(PLATFORM_CACHE_KEY) || "[]"));
  } catch (_error) {
    localStorage.removeItem(PLATFORM_CACHE_KEY);
    return [];
  }
}

function firstPlatformFallback() {
  const candidates = [normalizePlatformList(platforms), cachedPlatformList(), snapshotPlatformList()];
  return candidates.find(rows => rows.length) || [];
}

function setPlatformLoadState(state) {
  const select = byId("sourceSelect");
  const retry = byId("platformRetry");
  const island = select?.closest(".platform-island");
  if (select) select.dataset.loadState = state;
  if (retry) {
    retry.hidden = state !== "degraded";
    retry.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  }
  if (island) island.classList.toggle("has-platform-retry", state === "degraded");
}

function acceptPlatformList(value, { degraded = false, persist = false } = {}) {
  const rows = normalizePlatformList(value);
  if (rows.length || !platforms.length) platforms = rows;
  platformLoadDegraded = Boolean(degraded);
  if (persist && rows.length) {
    try {
      localStorage.setItem(PLATFORM_CACHE_KEY, JSON.stringify(rows));
    } catch (_error) {
      // 存储失败不能遮蔽当前有效的平台注册表。
    }
  }
  renderPlatforms();
  setPlatformLoadState(platformLoadDegraded ? "degraded" : "ready");
}

function refreshDegradedPlatformsFromSnapshot() {
  if (!platformLoadDegraded) return;
  const rows = snapshotPlatformList();
  if (!rows.length) return;
  platforms = rows;
  renderPlatforms();
  setPlatformLoadState("degraded");
}

function renderPlatforms() {
  const select = document.getElementById("sourceSelect");
  const preferred = preferredPlatformSource();
  select.innerHTML = platforms.map(platform => {
    const id = String(platform.id || "");
    const iconFile = platform.icon_file || (iconManifest.platforms || {})[id.toLowerCase()] || "platform_web.png";
    return `<option value="${escAttr(id)}" data-icon="${escAttr(iconFileUrl(iconFile))}" data-original-label="${escAttr(platform.name)}">${esc(platform.name)}</option>`;
  }).join("");
  if (preferred && platforms.some(platform => String(platform.id) === preferred)) select.value = preferred;
  if (!select.value && platforms.length) select.value = String(platforms[0].id || "");
  if (select.value) localStorage.setItem("cached_last_source", select.value);
  enhanceSelects(select.parentElement || document);
  syncCustomSelectForSelect(select);
  updatePlaceholder();
  setCrawlUiState(crawlRunning);
}

function configuredPlatformSource() {
  const basic = (frontendState.settings_snapshot || {})["\u57fa\u7840\u8bbe\u7f6e"] || {};
  return String(basic.last_source || "").trim();
}

function preferredPlatformSource() {
  const configured = configuredPlatformSource();
  if (configured && platforms.some(platform => String(platform.id || "") === configured)) return configured;
  const cached = String(localStorage.getItem("cached_last_source") || "").trim();
  if (cached && platforms.some(platform => String(platform.id || "") === cached)) return cached;
  return platforms.length ? String(platforms[0].id || "") : "";
}

function syncPlatformSourceFromSettings() {
  const select = byId("sourceSelect");
  const configured = configuredPlatformSource();
  if (!select || !configured || !platforms.some(platform => String(platform.id || "") === configured)) {
    return false;
  }
  const changed = select.value !== configured;
  if (changed) select.value = configured;
  localStorage.setItem("cached_last_source", configured);
  syncCustomSelectForSelect(select);
  return changed;
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
function normalizeTopCountOption(option) {
  if (option && typeof option === "object") {
    const value = String(option.value ?? option.id ?? option.label ?? "");
    return { value, label: String(option.label ?? value) };
  }
  return { value: String(option ?? ""), label: String(option ?? "") };
}
function configureTopCountForSource(sourceId) {
  const row = platformSettingsRow(sourceId);
  const unit = row && row.count_unit ? row.count_unit : "videos";
  const select = byId("videoCountSelect");
  const label = document.querySelector(".count-label");
  if (!select) return;

  let options = ((row && row.count_options) || countFallbackOptions(unit)).map(normalizeTopCountOption).filter(option => option.value);
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

function renderAll() {
  syncAppearanceFromSettings();
  syncPlatformSourceFromSettings();
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
  else if (currentPage === "settings") settingsControllerService().render();
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

function queueNavigationOrder() { return listPagesService().navigationOrder(); }
function renderQueue() { return listPagesService().renderQueue(); }
function restoreQueueControls() { return listPagesService().restoreQueueControls(); }
function setQueuePage(delta) { return listPagesService().setQueuePage(delta); }
function setQueuePageSize(value) { return listPagesService().setQueuePageSize(value); }
function setQueueDensity(mode) { return listPagesService().setQueueDensity(mode); }
function renderActive() { return listPagesService().renderActive(); }
function updateDownloadOptions() { return listPagesService().updateDownloadOptions(); }
function selectActive(id) { return listPagesService().selectActive(id); }
function renderActiveDetail() { return listPagesService().renderActiveDetail(); }
function activeEventTimelineHtml(events) {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.activeEventTimelineHtml(events) : "";
}

function activeTrendHtml(values, speedLabel = "0 B/s") {
  configureMediaDisplayHelpers();
  return window.UcpMediaDisplay ? window.UcpMediaDisplay.activeTrendHtml(values, speedLabel) : "";
}

function renderCompleted() { return listPagesService().renderCompleted(); }
function selectCompleted(id) { return listPagesService().selectCompleted(id); }
function setCompletedPage(delta) { return listPagesService().setCompletedPage(delta); }
function setCompletedPageSize(value) { return listPagesService().setCompletedPageSize(value); }
function renderCompletedDetail() { return listPagesService().renderCompletedDetail(); }
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

function renderFailed() { return listPagesService().renderFailed(); }
function selectFailed(id) { return listPagesService().selectFailed(id); }
function setFailedPage(delta) { return listPagesService().setFailedPage(delta); }
function setFailedPageSize(value) { return listPagesService().setFailedPageSize(value); }
function renderFailedDetail() { return listPagesService().renderFailedDetail(); }
function iconFileUrl(file) {
  return taskRenderService().iconFileUrl(file);
}

function writeClipboard(text, successMessage = "", successDetail = "") {
  const value = String(text ?? "");
  if (!value) {
    if (successMessage) appendUiLog(successMessage, successDetail);
    return Promise.resolve(false);
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(value)
      .then(() => {
        if (successMessage) appendUiLog(successMessage, successDetail);
        return true;
      })
      .catch(() => {
        appendLog(value);
        return false;
      });
  }
  appendLog(value);
  return Promise.resolve(false);
}

function performLogOperation(operation) {
  frontendAction("log_operation", { operation });
  if (operation === "refresh" || operation === "clear") frontendRuntimeService().scheduleDelta(200);
}

function renderLogs() { return logCenterService().render(); }
function selectLog(id) { return logCenterService().select(id); }
function setLogTab(category) { return logCenterService().setTab(category); }
window.syncLogFiltersFromDom = () => logCenterService().syncFiltersFromDom();
function setLogPage(delta) { return logCenterService().setPage(delta); }
function setLogPageSize(value) { return logCenterService().setPageSize(value); }
function copySelectedLogTraceId() { return logCenterService().copyTraceId(); }
function copyCurrentLogDetail() { return logCenterService().copyDetail(); }
function copyCurrentLogJson() { return logCenterService().copyJson(); }
function exportCurrentLogDetail() { return logCenterService().exportDetail(); }
function runLogOperation(operation) { return logCenterService().runOperation(operation); }

window.switchSettingsGroup = group => settingsControllerService().switchGroup(group);
window.handleProxySelect = (platformId, key, select) => settingsControllerService().handleProxySelect(platformId, key, select);
window.commitProxyCustom = (platformId, key, input) => settingsControllerService().commitProxyCustom(platformId, key, input);
window.selectAppearanceTheme = value => settingsControllerService().selectAppearanceTheme(value);
window.updateBasicSetting = (key, value) => settingsControllerService().updateBasic(key, value);
window.updateSetting = (section, key, value) => settingsControllerService().update(section, key, value);

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
    <div class="recent-list">${recent.length ? recent.map(row => `${esc(t(row.title || ""))}  ${esc(translateUiText(row.last_used || ""))}`).join("\n") : esc(t("暂无最近使用记录"))}</div>
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

let updateCheckSequence = 0;
let updateReleaseUrl = "";
let selectedUpdateVersion = "";

function trustedUpdateReleaseUrl(value) {
  try {
    const url = new URL(String(value || ""));
    const trustedPath = url.pathname.toLowerCase().startsWith("/haohaizi554/universalcrawler/releases/");
    return url.protocol === "https:" && url.hostname === "github.com" && trustedPath ? url.href : "";
  } catch (_error) {
    return "";
  }
}

function updateCheckStatusLabel(result) {
  const status = String((result && result.status) || "error");
  const latest = String((result && result.latest_version) || "");
  if (status === "available") return `${t("检测到新版本")} v${latest.replace(/^v/i, "")}`;
  if (status === "current") return t("当前已经是最新版本");
  if (status === "local_newer") return t("当前版本高于最新发布版本");
  if (status === "untrusted") return t("检测到版本，但安全更新清单未通过验证");
  return t("检查更新失败");
}

function setUpdateModalBusy(busy) {
  const modal = byId("updateModal");
  if (!modal) return;
  const isBusy = Boolean(busy);
  modal.setAttribute("aria-busy", isBusy ? "true" : "false");
  const spinner = byId("updateSpinner");
  if (spinner) spinner.hidden = !isBusy;
}

function waitForUpdateModalPaint() {
  return new Promise(resolve => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    const fallback = window.setTimeout(finish, 80);
    if (typeof window.requestAnimationFrame !== "function") return;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        window.clearTimeout(fallback);
        finish();
      });
    });
  });
}

async function showUpdateCheckModal() {
  const modal = byId("updateModal");
  if (!modal) return;
  const sequence = ++updateCheckSequence;
  updateReleaseUrl = "";
  selectedUpdateVersion = "";
  modal.style.display = "flex";
  setUpdateModalBusy(true);
  byId("updateTitle").textContent = t("检查更新");
  byId("updateLocalLabel").textContent = t("当前版本");
  byId("updateLatestLabel").textContent = t("Release 版本");
  byId("updateViewLogBtn").textContent = t("查看日志");
  byId("updateReleaseLink").textContent = t("查看发布页");
  byId("updatePrepareBtn").textContent = t("下载并验证");
  byId("updateInstallBtn").textContent = t("安装并重启");
  byId("updateCloseBtn").textContent = t("确定");
  byId("updateCloseIcon").setAttribute("aria-label", t("关闭"));
  byId("updateStatus").dataset.status = "checking";
  byId("updateStatus").textContent = t("正在检查更新...");
  byId("updateLocalVersion").textContent = byId("statusVersion").textContent || "--";
  byId("updateLatestVersion").textContent = "--";
  byId("updateNotes").textContent = "";
  byId("updateReleaseLink").hidden = true;
  byId("updatePrepareBtn").hidden = true;
  byId("updateInstallBtn").hidden = true;
  byId("updateCloseBtn").disabled = false;
  byId("updateCloseIcon").disabled = false;
  byId("statusVersion").disabled = true;
  byId("updateCloseBtn").focus({ preventScroll: true });
  try {
    await waitForUpdateModalPaint();
    if (sequence !== updateCheckSequence || modal.style.display === "none") return;
    const response = await fetch("/api/update/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ local_version: byId("statusVersion").textContent || "" }),
    });
    const result = await response.json();
    if (sequence !== updateCheckSequence) return;
    if (!response.ok || !result || result.status === "error") {
      throw new Error((result && (result.message || result.error)) || `HTTP ${response.status}`);
    }
    byId("updateStatus").dataset.status = String(result.status || "current");
    byId("updateStatus").textContent = updateCheckStatusLabel(result);
    byId("updateLocalVersion").textContent = result.local_version || "--";
    byId("updateLatestVersion").textContent = result.latest_version || "--";
    byId("updateNotes").textContent = result.notes || t("未提供更新说明");
    updateReleaseUrl = trustedUpdateReleaseUrl(result.html_url);
    byId("updateReleaseLink").hidden = !updateReleaseUrl;
    selectedUpdateVersion = String(result.latest_version || "");
    byId("updatePrepareBtn").hidden = !(result.status === "available" && result.can_prepare);
  } catch (error) {
    if (sequence !== updateCheckSequence) return;
    byId("updateStatus").dataset.status = "error";
    byId("updateStatus").textContent = t("检查更新失败");
    byId("updateNotes").textContent = String(error && (error.message || error) || "");
  } finally {
    if (sequence === updateCheckSequence) {
      setUpdateModalBusy(false);
      byId("statusVersion").disabled = false;
    }
  }
}

async function prepareWebUpdate() {
  const modal = byId("updateModal");
  const button = byId("updatePrepareBtn");
  if (!modal || !button || !selectedUpdateVersion || modal.getAttribute("aria-busy") === "true") return;
  const sequence = ++updateCheckSequence;
  setUpdateModalBusy(true);
  button.disabled = true;
  byId("updateStatus").dataset.status = "preparing";
  byId("updateStatus").textContent = t("正在下载并验证更新...");
  try {
    const response = await fetch("/api/update/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        local_version: byId("updateLocalVersion").textContent || "",
        selected_version: selectedUpdateVersion,
      }),
    });
    const result = await response.json();
    if (sequence !== updateCheckSequence) return;
    if (!response.ok || !result || result.status !== "ready") {
      throw new Error((result && (result.message || result.error)) || `HTTP ${response.status}`);
    }
    byId("updateStatus").dataset.status = "ready";
    byId("updateStatus").textContent = t("更新包已下载并通过验证");
    byId("updateNotes").textContent = `${t("安装包")}: ${result.installer_name || "--"}`;
    button.hidden = true;
    byId("updateInstallBtn").hidden = false;
  } catch (error) {
    if (sequence !== updateCheckSequence) return;
    byId("updateStatus").dataset.status = "error";
    byId("updateStatus").textContent = t("更新下载失败");
    byId("updateNotes").textContent = String(error && (error.message || error) || "");
  } finally {
    if (sequence === updateCheckSequence) {
      setUpdateModalBusy(false);
      button.disabled = false;
    }
  }
}

async function installWebUpdate() {
  const modal = byId("updateModal");
  const button = byId("updateInstallBtn");
  if (!modal || !button || button.hidden || modal.getAttribute("aria-busy") === "true") return;
  const sequence = ++updateCheckSequence;
  setUpdateModalBusy(true);
  button.disabled = true;
  byId("updateCloseBtn").disabled = true;
  byId("updateCloseIcon").disabled = true;
  byId("updateStatus").dataset.status = "installing";
  byId("updateStatus").textContent = t("正在启动安装程序...");
  try {
    const response = await fetch("/api/update/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await response.json();
    if (sequence !== updateCheckSequence) return;
    if (!response.ok || !result || result.status !== "installing") {
      throw new Error((result && (result.message || result.error)) || `HTTP ${response.status}`);
    }
    byId("updateStatus").dataset.status = "installing";
    byId("updateStatus").textContent = t("安装程序已启动，应用即将重启");
    byId("updateNotes").textContent = t("请勿关闭安装程序窗口");
    button.hidden = true;
    byId("updateCloseBtn").disabled = true;
    byId("updateCloseIcon").disabled = true;
  } catch (error) {
    if (sequence !== updateCheckSequence) return;
    byId("updateStatus").dataset.status = "error";
    byId("updateStatus").textContent = t("启动安装程序失败");
    byId("updateNotes").textContent = String(error && (error.message || error) || "");
    setUpdateModalBusy(false);
    button.disabled = false;
    byId("updateCloseBtn").disabled = false;
    byId("updateCloseIcon").disabled = false;
  }
}

function isUpdateModalCloseDisabled() {
  return [byId("updateCloseBtn"), byId("updateCloseIcon")]
    .some(control => Boolean(control && control.disabled));
}

function closeUpdateCheckModal() {
  const modal = byId("updateModal");
  if (!modal || modal.style.display === "none" || isUpdateModalCloseDisabled()) return false;
  updateCheckSequence += 1;
  modal.style.display = "none";
  setUpdateModalBusy(false);
  byId("statusVersion").disabled = false;
  byId("statusVersion").focus({ preventScroll: true });
  return true;
}

function openUpdateReleasePage() {
  if (updateReleaseUrl) window.open(updateReleaseUrl, "_blank", "noopener");
}

function openUpdateLog() {
  window.open("/api/debug/latest-log", "_blank", "noopener");
}

window.showUpdateCheckModal = showUpdateCheckModal;
window.closeUpdateCheckModal = closeUpdateCheckModal;
window.openUpdateReleasePage = openUpdateReleasePage;
window.openUpdateLog = openUpdateLog;
window.prepareWebUpdate = prepareWebUpdate;
window.installWebUpdate = installWebUpdate;

function switchPage(pageId) {
  currentPage = pageId;
  document.querySelectorAll(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === pageId));
  document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === pageId));
  renderCurrentPage();
  settingsControllerService().refreshPlatformAuthStatus(false);
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
  const stateReady = frontendLoadState === "ready";
  const startBtn = byId("startBtn");
  const stopBtn = byId("stopBtn");
  const searchInput = byId("searchInput");
  const sourceSelect = byId("sourceSelect");
  const countSelect = byId("videoCountSelect");
  if (startBtn) {
    startBtn.disabled = crawlRunning || !stateReady;
    startBtn.classList.toggle("is-running", crawlRunning);
    startBtn.setAttribute("aria-busy", crawlRunning ? "true" : "false");
  }
  if (stopBtn) stopBtn.disabled = !crawlRunning || !stateReady;
  [searchInput, sourceSelect, countSelect].forEach(control => {
    if (control) control.disabled = crawlRunning || !stateReady;
  });
  const changeDirBtn = byId("changeDirBtn");
  if (changeDirBtn) changeDirBtn.disabled = !stateReady;
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

let sendWS = (type, data) => frontendRuntimeService().send(type, data);

const defaultSendWS = sendWS;

function frontendAction(action, payload) {
  if (action === "delete_item") playbackControllerService().prepareDeleteItem(payload && (payload.id || payload.video_id));
  let rollback = null;
  if (action === "delete_item") {
    rollback = listPagesService().optimisticallyMutateCompleted(action, payload || {});
  } else if (action === "delete_failed_record" || action === "clear_failed_records") {
    rollback = listPagesService().optimisticallyMutateFailed(action, payload || {});
  }
  const sent = frontendRuntimeService().send("frontend_action", { action, payload });
  if (!sent && rollback) rollback();
  if (action === "register_file_associations") appendUiLog("正在绑定默认打开方式...");
  return sent;
}

function openDirectory(id) {
  frontendAction("open_directory", { id });
}

function copyDiagnostics(id) { return listPagesService().copyDiagnostics(id); }

function appendLog(message) {
  const now = formatLocalDateTime();
  frontendState.log_items = frontendState.log_items || [];
  frontendState.log_items.push({ time: now, level: "INFO", source: "WebUI", thread: "browser", trace_id: "", message_summary: String(message), message: String(message), detail: "", stack: "" });
  trimFrontendLogItems();
  const legacyPanel = byId("logPanel");
  if (legacyPanel) {
    const line = document.createElement("div");
    line.textContent = logI18nService()?.translateStructuredLogText(message) ?? String(message ?? "");
    legacyPanel.appendChild(line);
  }
  scheduleRenderSections(["log_items", "app_status"]);
}

window.onChangeDirClicked = () => dialogControllerService().onChangeDirectory();
window.showDirDialog = () => dialogControllerService().showDirectory();
window.dirBrowsePath = () => dialogControllerService().browseDirectory();
window.dirGoParent = () => dialogControllerService().goDirectoryParent();
window.dirRefresh = () => dialogControllerService().refreshDirectory();
window.confirmDirDialog = () => dialogControllerService().confirmDirectory();
window.cancelDirDialog = () => dialogControllerService().cancelDirectory();

window.applyFileAssociationLanguage = () => dialogControllerService().applyAssociationLanguage();
window.showFileAssociationModal = () => dialogControllerService().showAssociation();
window.cancelFileAssociationModal = () => dialogControllerService().cancelAssociation();
window.confirmFileAssociationModal = () => dialogControllerService().confirmAssociation();

window.toggleSelectionItem = (index, event) => dialogControllerService().toggleSelection(index, event);
window.selectAllSelectionItems = () => dialogControllerService().selectAllSelection();
window.invertSelectionItems = () => dialogControllerService().invertSelection();
window.showSelectionModal = items => dialogControllerService().showSelection(items);
window.confirmSelection = () => dialogControllerService().confirmSelection();
window.cancelSelection = () => dialogControllerService().cancelSelection();

let themeToggleInFlight = false;
let pendingThemeValue = "";
const APPEARANCE_ACCENT_MAP = Object.freeze({
  blue: { light: ["#1677ff", "#eaf3ff"], dark: ["#3b82f6", "#1f2d46"] },
  green: { light: ["#16a34a", "#e7f8ee"], dark: ["#22c55e", "#153523"] },
  purple: { light: ["#7c3aed", "#f1eaff"], dark: ["#a78bfa", "#312548"] },
  orange: { light: ["#ea580c", "#fff1e7"], dark: ["#fb923c", "#3d2718"] },
  red: { light: ["#dc2626", "#feecec"], dark: ["#f87171", "#402020"] },
});

function currentAppearanceSettings() {
  return (frontendState.settings_snapshot || {})["\u5916\u89c2\u8bbe\u7f6e"] || {};
}

function applyThemeDependentTokens(dark, appearanceOverride = null) {
  const appearance = appearanceOverride || currentAppearanceSettings();
  const accent = APPEARANCE_ACCENT_MAP[String(appearance.accent || "blue").toLowerCase()]
    || APPEARANCE_ACCENT_MAP.blue;
  const palette = accent[dark ? "dark" : "light"];
  document.documentElement.style.setProperty("--accent", palette[0]);
  document.documentElement.style.setProperty("--accent-soft", palette[1]);
  document.documentElement.style.setProperty("--row-selected", palette[1]);
}

function applyOptimisticTheme(theme) {
  const dark = theme === "dark";
  applyTheme(dark);
  localStorage.setItem("cached_theme", theme);
  localStorage.setItem("cached_dark_theme", String(dark));
}

function setThemeToggleBusy(busy) {
  const button = byId("themeBtn");
  if (button) button.setAttribute("aria-busy", busy ? "true" : "false");
}

async function commitPendingTheme() {
  if (themeToggleInFlight) return;
  themeToggleInFlight = true;
  setThemeToggleBusy(true);
  try {
    while (pendingThemeValue) {
      const target = pendingThemeValue;
      pendingThemeValue = "";
      const runtime = frontendRuntimeService();
      const result = typeof runtime.requestAction === "function"
        ? await runtime.requestAction("update_setting", { section: "common", key: "theme", value: target })
        : { status: "error", message: "theme action acknowledgement unavailable" };
      if (!result || result.status !== "ok") {
        pendingThemeValue = "";
        applyAppearance((frontendState.settings_snapshot || {})["外观设置"] || {});
        break;
      }
      if (pendingThemeValue === target) pendingThemeValue = "";
      applyOptimisticTheme(pendingThemeValue || target);
    }
  } finally {
    themeToggleInFlight = false;
    setThemeToggleBusy(false);
  }
}

function toggleTheme() {
  const effectiveTheme = pendingThemeValue || document.documentElement.dataset.theme || "light";
  pendingThemeValue = effectiveTheme === "dark" ? "light" : "dark";
  applyOptimisticTheme(pendingThemeValue);
  void commitPendingTheme();
}

function restoreTheme() {
  const serverTheme = String(document.documentElement.dataset.theme || "").toLowerCase();
  const cached = String(localStorage.getItem("cached_theme") || "").toLowerCase();
  const initialTheme = ["light", "dark"].includes(serverTheme) ? serverTheme : cached;
  applyTheme(initialTheme === "dark");
  setThemeToggleBusy(false);
}

function applyAppearance(appearance = {}) {
  const theme = String(appearance.theme || "").toLowerCase();
  const followsSystem = appearance.follow_system === true;
  const systemTheme = typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
  if (!systemThemeListenerRegistered && systemTheme && typeof systemTheme.addEventListener === "function") {
    systemTheme.addEventListener("change", event => {
      const current = (frontendState.settings_snapshot || {})["\u5916\u89c2\u8bbe\u7f6e"] || {};
      if (current.follow_system !== true) return;
      applyAppearance(current);
    });
    systemThemeListenerRegistered = true;
  }
  if (followsSystem && systemTheme) {
    applyTheme(systemTheme.matches, appearance);
  } else if (theme === "dark" || theme === "light") {
    applyTheme(theme === "dark", appearance);
    localStorage.setItem("cached_theme", theme);
    localStorage.setItem("cached_dark_theme", String(theme === "dark"));
  }
  const scaleMap = { "90%": .9, "100%": 1, "110%": 1.1, "125%": 1.25 };
  const fontMap = { small: 13, medium: 14, large: 16 };
  const scale = scaleMap[String(appearance.scale || "100%")] || 1;
  const fontSize = fontMap[String(appearance.font_size || "medium").toLowerCase()] || 14;
  document.documentElement.style.setProperty("--ui-scale", String(scale));
  document.documentElement.style.setProperty("--base-font-size", `${Math.max(12, Math.round(fontSize * scale))}px`);
  const configuredLanguage = String(appearance.language || "").trim();
  const language = ["zh-CN", "en-US", "zh-TW"].includes(configuredLanguage)
    ? configuredLanguage
    : currentLanguage();
  document.documentElement.dataset.language = language;
  document.documentElement.lang = { "en-US": "en", "zh-TW": "zh" }[language] || language;
  applyStaticLanguage();
}

function applyTheme(dark, appearanceOverride = null) {
  const theme = dark ? "dark" : "light";
  if (document.documentElement.dataset.theme !== theme) {
    document.documentElement.dataset.theme = theme;
  }
  applyThemeDependentTokens(dark, appearanceOverride);
  const themeButton = byId("themeBtn");
  if (themeButton) {
    const iconFile = dark ? "action_theme_night.png" : "action_theme_light.png";
    themeButton.innerHTML = `<img src="/ui-icon/${iconFile}" alt="" />`;
    themeButton.setAttribute("aria-label", t("切换主题"));
  }
}

function cacheSource() {
  const source = byId("sourceSelect").value;
  localStorage.setItem("cached_last_source", source);
  patchSettingSnapshot("\u57fa\u7840\u8bbe\u7f6e", "last_source", source);
  updatePlaceholder();
  void frontendRuntimeService().requestAction("update_basic_setting", {
    key: "last_source",
    value: source,
  });
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

window.playCompleted = id => playbackControllerService().playCompleted(id);
window.previewVideo = id => playbackControllerService().previewVideo(id);
window.togglePlay = () => playbackControllerService().togglePlay();
window.toggleFullscreen = () => playbackControllerService().toggleFullscreen();
window.switchPreview = direction => playbackControllerService().switchPreview(direction);
window.onSeekInput = value => playbackControllerService().onSeekInput(value);
window.onSeekCommit = value => playbackControllerService().onSeekCommit(value);
window.deleteVideo = id => playbackControllerService().deleteVideo(id);
window.closePreview = () => playbackControllerService().closePreview();

function selectVideo(id) {
  const nextId = String(id || "");
  const oldId = selectedVideoId;
  selectedVideoId = nextId;
  if ((frontendState.completed_items || []).some(item => String(item.id || "") === nextId)) {
    selectCompleted(nextId);
    return;
  }
  updateSelection(oldId, nextId);
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

function visibleTaskNavigationContext() {
  const contexts = {
    queue: { bodyId: "queueBody", selectedId: selectedVideoId, select: selectVideo },
    active: { bodyId: "activeBody", selectedId: selected.active, select: selectActive },
    completed: { bodyId: "completedBody", selectedId: selected.completed, select: selectCompleted },
    failed: { bodyId: "failedBody", selectedId: selected.failed, select: selectFailed },
  };
  const context = contexts[currentPage];
  if (!context) return null;
  const body = byId(context.bodyId);
  if (!body || !body.closest(".page.active")) return null;
  return {
    ...context,
    order: Array.from(body.querySelectorAll("tr[data-id]"))
      .map(row => String(row.dataset.id || ""))
      .filter(Boolean),
  };
}

document.addEventListener("keydown", event => {
  if (event.key === "Escape" && byId("updateModal")?.style.display === "flex") {
    event.preventDefault();
    closeUpdateCheckModal();
    return;
  }
  if (dialogControllerService().handleShortcut(event)) return;
  if (playbackControllerService().handleShortcut(event)) return;
  const navigation = visibleTaskNavigationContext();
  if ((event.key === "ArrowUp" || event.key === "ArrowDown") && navigation && navigation.order.length > 0) {
    const tag = document.activeElement && document.activeElement.tagName;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
    event.preventDefault();
    const current = navigation.selectedId ? navigation.order.indexOf(String(navigation.selectedId)) : -1;
    const next = event.key === "ArrowDown"
      ? (current < navigation.order.length - 1 ? current + 1 : 0)
      : (current > 0 ? current - 1 : navigation.order.length - 1);
    navigation.select(navigation.order[next]);
  }
  const selectedQueueRow = selectedVideoId
    ? document.querySelector(`#page-queue.active #queueBody tr[data-id="${cssEscape(selectedVideoId)}"]`)
    : null;
  if (event.key === "Delete" && currentPage === "queue" && selectedQueueRow && document.activeElement === document.body) {
    playbackControllerService().deleteVideo(selectedVideoId);
  }
}, true);

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
