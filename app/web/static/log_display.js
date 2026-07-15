(function (root) {
  const TIME_FILTER_MINUTES = {
    "30m": 30,
    "1h": 60,
    "24h": 24 * 60,
    "\u8fd1 30 \u5206\u949f": 30,
    "\u8fd1 1 \u5c0f\u65f6": 60,
    "\u8fd1 24 \u5c0f\u65f6": 24 * 60,
    "Last 30 minutes": 30,
    "Last 30 min": 30,
    "Last 1 hour": 60,
    "Last 24 hours": 24 * 60,
  };

  const UNIQUE_ROW_ID_FIELD = "__ucp_log_row_id";
  const LOG_CATEGORIES = new Set(["crawl", "download", "system", "performance", "error"]);
  const PLATFORM_ALIASES = [
    ["douyin", ["douyin", "抖音"]],
    ["bilibili", ["bilibili", "bili"]],
    ["kuaishou", ["kuaishou", "快手"]],
    ["missav", ["missav"]],
    ["xiaohongshu", ["xiaohongshu", "xhs", "小红书"]],
    ["system", ["system", "系统"]],
  ];

  function baseLogItemId(item) {
    const row = item || {};
    return String(row.id || `${row.time || ""}|${row.trace_id || ""}|${row.source || ""}|${row.message_summary || ""}`);
  }

  function logItemId(item) {
    const row = item || {};
    return String(row[UNIQUE_ROW_ID_FIELD] || baseLogItemId(row));
  }

  function visibleLogItems(items, rowBudget = 300) {
    // UI 展示条数只影响前端可见窗口，不裁剪后端日志文件。
    if (!Array.isArray(items)) return [];
    const budget = Math.max(1, Number(rowBudget) || 300);
    if (items.length <= budget) return items;
    return items.slice(0, budget);
  }

  function logTimestampMs(item) {
    const explicit = Number(item && item.timestamp_ms);
    if (Number.isFinite(explicit) && explicit !== 0) return explicit;
    const parsed = Date.parse(String((item && item.time) || "").replace(" ", "T"));
    return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
  }

  function sortLogItems(items) {
    return (Array.isArray(items) ? items : [])
      .map((item, index) => ({ item, index, timestamp: logTimestampMs(item) }))
      .sort((left, right) => {
        if (left.timestamp !== right.timestamp) return left.timestamp > right.timestamp ? -1 : 1;
        return right.index - left.index;
      })
      .map(entry => entry.item);
  }

  function filteredLogItems(items, filters = {}, nowMs = Date.now()) {
    return (items || []).filter(item => logMatchesFilters(item, filters, nowMs));
  }

  function logTabCounts(items, filters = {}, nowMs = Date.now()) {
    const counts = {
      all: 0,
      crawl: 0,
      download: 0,
      system: 0,
      performance: 0,
      error: 0,
    };
    const baseFilters = { ...filters, category: "all" };
    const rows = filteredLogItems(items || [], baseFilters, nowMs);
    for (const item of rows) {
      counts.all += 1;
      const category = logCategory(item);
      if (Object.prototype.hasOwnProperty.call(counts, category)) counts[category] += 1;
    }
    return counts;
  }

  function queryLogItems(request = {}) {
    // 日志筛选、分页和标签页计数集中在纯函数里，供 Worker 与主线程复用。
    const allItems = Array.isArray(request.items) ? request.items : [];
    const filters = request.filters || {};
    const rowBudget = Math.max(1, Number(request.rowBudget) || 300);
    const parsedPageSize = Number(request.pageSize);
    const pageSize = Number.isFinite(parsedPageSize) && parsedPageSize >= 0
      ? Math.floor(parsedPageSize)
      : 20;
    const nowMs = Number(request.nowMs) || Date.now();
    const filteredItems = filteredLogItems(allItems, filters, nowMs);
    const sortedItems = sortLogItems(filteredItems);
    const boundedItems = visibleLogItems(sortedItems, rowBudget);
    const totalPages = pageSize <= 0 ? 1 : Math.max(1, Math.ceil(boundedItems.length / pageSize));
    const page = Math.max(1, Math.min(Number(request.page) || 1, totalPages));
    const start = pageSize <= 0 ? 0 : (page - 1) * pageSize;
    const pageItems = pageSize <= 0 ? boundedItems : boundedItems.slice(start, start + pageSize);
    let selectedId = String(request.selectedId || "");
    if (!pageItems.some(item => logItemId(item) === selectedId)) {
      selectedId = pageItems.length ? logItemId(pageItems[0]) : "";
    }
    return {
      sequence: Number(request.sequence) || 0,
      pageItems,
      tabCounts: logTabCounts(allItems, filters, nowMs),
      totalCount: allItems.length,
      matchedCount: boundedItems.length,
      visibleCount: pageItems.length,
      currentPage: page,
      totalPages,
      selectedId,
    };
  }

  function logMatchesFilters(item, filters = {}, nowMs = Date.now()) {
    const category = logCategory(item);
    const selectedCategory = filters.category || "all";
    if (selectedCategory !== "all" && category !== selectedCategory) {
      return false;
    }
    if (!isAllFilter(filters.level) && logDisplayLevel(item) !== normalizeDisplayLevel(filters.level)) return false;
    if (!logMatchesTime(item, filters.time, nowMs)) return false;
    const searchText = logSearchText(item);
    const haystack = searchText.toLowerCase();
    if (!logMatchesPlatform(item, filters.platform)) return false;
    if (filters.trace && !String(item.trace_id || "").toLowerCase().includes(String(filters.trace).toLowerCase())) return false;
    if (filters.keyword && !haystack.includes(String(filters.keyword).toLowerCase())) return false;
    return true;
  }

  function logCategory(item) {
    // 后端行携带 GUI 使用的规范 log_scope；关键词匹配只兼容该契约建立前的旧快照。
    for (const value of [item && item.log_scope, item && item.category]) {
      const normalized = String(value || "").trim().toLowerCase();
      if (LOG_CATEGORIES.has(normalized)) return normalized;
    }
    const level = normalizeDisplayLevel(item && (item.raw_level || item.level));
    if (level === "ERROR") return "error";
    const text = logSearchText(item).toLowerCase();
    if (/(performance|perf|\u6027\u80fd|\u8017\u65f6|latency|duration|speed_trend)/.test(text)) return "performance";
    if (/(crawl|crawler|spider|parse|scan|\u91c7\u96c6|\u722c\u53d6|\u722c\u866b|\u626b\u63cf|\u89e3\u6790|\u4e3b\u9875)/.test(text)) return "crawl";
    if (/(download|\u4e0b\u8f7d|\u6d41\u8bf7\u6c42|\u5206\u7247|\u5408\u5e76|bilibili|douyin|kuaishou|missav|\u5c0f\u7ea2\u4e66|\u6296\u97f3|\u5feb\u624b)/.test(text)) return "download";
    return "system";
  }

  function normalizeDisplayLevel(value) {
    const normalized = String(value || "INFO").trim().toUpperCase();
    if (normalized === "WARNING") return "WARN";
    if (normalized === "COMMAND") return "CMD";
    if (normalized === "OK") return "SUCCESS";
    return normalized;
  }

  function logDisplayLevel(item) {
    const row = item || {};
    if (row.level_display) return normalizeDisplayLevel(row.level_display);
    const resultType = String(row.result_type || "").trim().toLowerCase();
    const fromResult = {
      info: "INFO",
      success: "SUCCESS",
      warn: "WARN",
      error: "ERROR",
      command: "CMD",
    }[resultType];
    return fromResult || normalizeDisplayLevel(row.level);
  }

  function canonicalPlatformId(value) {
    const normalized = String(value || "").trim().toLowerCase();
    if (!normalized) return "";
    for (const [platformId, aliases] of PLATFORM_ALIASES) {
      if (aliases.some(alias => normalized === alias.toLowerCase())) return platformId;
    }
    return normalized;
  }

  function logPlatformId(item) {
    const row = item || {};
    const explicit = String(row.platform_id || row.source_id || "").trim();
    if (explicit) return canonicalPlatformId(explicit);
    const platform = String(row.platform || row.platform_label || "").trim();
    const exact = canonicalPlatformId(platform);
    if (PLATFORM_ALIASES.some(([platformId]) => platformId === exact)) return exact;
    const text = logSearchText(row).toLowerCase();
    for (const [platformId, aliases] of PLATFORM_ALIASES) {
      if (aliases.some(alias => alias.length > 1 && text.includes(alias.toLowerCase()))) return platformId;
    }
    return "";
  }

  function logMatchesPlatform(item, selectedPlatform) {
    if (isAllFilter(selectedPlatform)) return true;
    const selectedId = canonicalPlatformId(selectedPlatform);
    const itemId = logPlatformId(item);
    if (itemId) return itemId === selectedId;
    return logSearchText(item).toLowerCase().includes(String(selectedPlatform || "").toLowerCase());
  }

  function logSearchText(item) {
    return [
      item.platform,
      item.source,
      item.trace_id,
      item.traceId,
      item.level,
      item.raw_level,
      item.level_display,
      item.result_type,
      item.category,
      item.log_scope,
      item.event_stage,
      item.event_code,
      item.status_code,
      item.action,
      item.event,
      item.event_type,
      item.message_summary,
      item.message,
      item.detail,
      item.stack,
    ].map(searchableValue).join(" ");
  }

  function searchableValue(value) {
    if (value && typeof value === "object") {
      try { return JSON.stringify(value); } catch (_error) { return String(value); }
    }
    return String(value || "");
  }

  function logMatchesTime(item, timeFilter, nowMs = Date.now()) {
    if (isAllFilter(timeFilter)) return true;
    const minutes = TIME_FILTER_MINUTES[String(timeFilter || "")];
    if (!minutes) return true;
    const timestamp = Number(item.timestamp_ms || Date.parse(String(item.time || "").replace(" ", "T")));
    if (!timestamp) return false;
    return timestamp >= Number(nowMs) - minutes * 60 * 1000;
  }

  function isAllFilter(value) {
    const text = String(value || "").trim().toLowerCase();
    return !text || text === "all" || text === "\u5168\u90e8";
  }

  root.UcpLogDisplay = {
    baseLogItemId,
    logItemId,
    visibleLogItems,
    sortLogItems,
    filteredLogItems,
    queryLogItems,
    logTabCounts,
    logMatchesFilters,
    logCategory,
    logDisplayLevel,
    logMatchesPlatform,
    logSearchText,
    logMatchesTime,
  };
})(typeof window !== "undefined" ? window : self);
