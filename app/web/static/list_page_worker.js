self.onmessage = event => {
  const request = event.data || {};
  if (request.type !== "page") return;
  self.postMessage(buildListPageResult(request));
};

function buildListPageResult(request) {
  const items = Array.isArray(request.items) ? request.items : [];
  const pageSize = normalizeTablePageSize(request.pageSize);
  const totalCount = items.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  let currentPage = clampPage(request.page, totalPages);
  let selectedId = String(request.selectedId || "");

  if (selectedId && request.selectedIdMovesPage) {
    const selectedIndex = items.findIndex(item => String((item || {}).id || "") === selectedId);
    if (selectedIndex >= 0) currentPage = Math.floor(selectedIndex / pageSize) + 1;
  }

  const start = (currentPage - 1) * pageSize;
  const pageItems = items.slice(start, start + pageSize);
  const visibleIds = pageItems
    .map(item => String((item || {}).id || ""))
    .filter(Boolean);

  if ((!selectedId || !visibleIds.includes(selectedId)) && request.selectFirst && visibleIds.length) {
    selectedId = visibleIds[0];
  }
  if (selectedId && !items.some(item => String((item || {}).id || "") === selectedId)) {
    selectedId = "";
  }

  return {
    type: "page",
    pageKey: String(request.pageKey || ""),
    sequence: Number(request.sequence) || 0,
    totalCount,
    totalPages,
    currentPage,
    pageSize,
    pageItems,
    selectedId,
  };
}

function normalizeTablePageSize(value) {
  const numeric = Number(value);
  return [20, 50, 100].includes(numeric) ? numeric : 20;
}

function clampPage(value, totalPages) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 1) return 1;
  return Math.max(1, Math.min(Math.trunc(numeric), totalPages));
}
