importScripts("/static/log_display.js");

self.onmessage = event => {
  const request = event && event.data ? event.data : {};
  try {
    const service = self.UcpLogDisplay;
    const result = service && typeof service.queryLogItems === "function"
      ? service.queryLogItems(request)
      : {
          sequence: Number(request.sequence) || 0,
          pageItems: [],
          tabCounts: { all: 0, crawl: 0, download: 0, system: 0, performance: 0, error: 0 },
          totalCount: Array.isArray(request.items) ? request.items.length : 0,
          matchedCount: 0,
          visibleCount: 0,
          currentPage: 1,
          totalPages: 1,
          selectedId: "",
        };
    self.postMessage({ type: "result", result });
  } catch (error) {
    self.postMessage({
      type: "error",
      sequence: Number(request.sequence) || 0,
      message: error && error.message ? String(error.message) : String(error),
    });
  }
};
