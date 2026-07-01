(function () {
  const TIME_FILTER_MINUTES = {
    "\u8fd1 30 \u5206\u949f": 30,
    "\u8fd1 1 \u5c0f\u65f6": 60,
    "\u8fd1 24 \u5c0f\u65f6": 24 * 60,
  };

  function logItemId(item) {
    return String(item.id || `${item.time || ""}|${item.trace_id || ""}|${item.source || ""}|${item.message_summary || ""}`);
  }

  function visibleLogItems(items, rowBudget = 300) {
    if (!Array.isArray(items)) return [];
    const budget = Math.max(1, Number(rowBudget) || 300);
    if (items.length <= budget) return items;
    return items.slice(-budget);
  }

  function filteredLogItems(items, filters = {}, nowMs = Date.now()) {
    return (items || []).filter(item => logMatchesFilters(item, filters, nowMs));
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
    const level = String(item.level || "").toUpperCase();
    if (level === "ERROR") return "error";
    if (item.category) return String(item.category);
    const text = logSearchText(item).toLowerCase();
    if (/(download|\u4e0b\u8f7d|bilibili|douyin|kuaishou|missav|\u5c0f\u7ea2\u4e66|\u6296\u97f3|\u5feb\u624b)/.test(text)) return "download";
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

  window.UcpLogDisplay = {
    logItemId,
    visibleLogItems,
    filteredLogItems,
    logMatchesFilters,
    logCategory,
    logSearchText,
    logMatchesTime,
  };
})();
