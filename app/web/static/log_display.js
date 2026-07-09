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

  function logItemId(item) {
    return String(item.id || `${item.time || ""}|${item.trace_id || ""}|${item.source || ""}|${item.message_summary || ""}`);
  }

  function visibleLogItems(items, rowBudget = 300) {
    // UI 展示条数只影响前端可见窗口，不裁剪后端日志文件。
    if (!Array.isArray(items)) return [];
    const budget = Math.max(1, Number(rowBudget) || 300);
    if (items.length <= budget) return items;
    return items.slice(-budget);
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
      if (String(item.level || "").toUpperCase() === "ERROR" && category !== "error") counts.error += 1;
    }
    return counts;
  }

  function queryLogItems(request = {}) {
    // 日志筛选、分页和 tab 计数集中在纯函数里，Worker/主线程可复用。
    const allItems = Array.isArray(request.items) ? request.items : [];
    const filters = request.filters || {};
    const rowBudget = Math.max(1, Number(request.rowBudget) || 300);
    const pageSize = Number(request.pageSize) || 20;
    const nowMs = Number(request.nowMs) || Date.now();
    const filteredItems = filteredLogItems(allItems, filters, nowMs);
    const boundedItems = visibleLogItems(filteredItems, rowBudget);
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
    if (selectedCategory === "error") {
      if (String(item.level || "").toUpperCase() !== "ERROR" && category !== "error") return false;
    } else if (selectedCategory !== "all" && category !== selectedCategory) {
      return false;
    }
    if (!isAllFilter(filters.level) && String(item.level || "").toUpperCase() !== String(filters.level || "").toUpperCase()) return false;
    if (!logMatchesTime(item, filters.time, nowMs)) return false;
    const searchText = logSearchText(item);
    const haystack = searchText.toLowerCase();
    if (!isAllFilter(filters.platform) && !searchText.includes(String(filters.platform || ""))) return false;
    if (filters.trace && !String(item.trace_id || "").toLowerCase().includes(String(filters.trace).toLowerCase())) return false;
    if (filters.keyword && !haystack.includes(String(filters.keyword).toLowerCase())) return false;
    return true;
  }

  function logCategory(item) {
    // 后端未显式分类时，用关键词兜底，保证旧日志也能落入对应 tab。
    const level = String(item.level || "").toUpperCase();
    if (level === "ERROR") return "error";
    if (item.category) return String(item.category);
    const text = logSearchText(item).toLowerCase();
    if (/(performance|perf|\u6027\u80fd|\u8017\u65f6|latency|duration|speed_trend)/.test(text)) return "performance";
    if (/(crawl|crawler|spider|parse|scan|\u91c7\u96c6|\u722c\u53d6|\u722c\u866b|\u626b\u63cf|\u89e3\u6790|\u4e3b\u9875)/.test(text)) return "crawl";
    if (/(download|\u4e0b\u8f7d|\u6d41\u8bf7\u6c42|\u5206\u7247|\u5408\u5e76|bilibili|douyin|kuaishou|missav|\u5c0f\u7ea2\u4e66|\u6296\u97f3|\u5feb\u624b)/.test(text)) return "download";
    return "system";
  }

  function logSearchText(item) {
    return [
      item.platform,
      item.source,
      item.trace_id,
      item.level,
      item.message_summary,
      item.message,
      item.detail,
      item.stack,
    ].map(value => String(value || "")).join(" ");
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
    logItemId,
    visibleLogItems,
    filteredLogItems,
    queryLogItems,
    logTabCounts,
    logMatchesFilters,
    logCategory,
    logSearchText,
    logMatchesTime,
  };
})(typeof window !== "undefined" ? window : self);
