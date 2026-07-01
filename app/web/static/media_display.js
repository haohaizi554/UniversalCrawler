(function () {
  let escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  function configure(options = {}) {
    if (typeof options.esc === "function") escapeHtml = options.esc;
  }

  function displayMetadataValue(value, pending = false) {
    const text = String(value || "").trim();
    if (text && text !== "--") return text;
    return pending ? "\u68c0\u6d4b\u4e2d" : "--";
  }

  function basenameFromPath(path) {
    const parts = String(path || "").split(/[\\/]/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : "";
  }

  function dirnameFromPath(path) {
    const text = String(path || "");
    const slash = Math.max(text.lastIndexOf("\\"), text.lastIndexOf("/"));
    return slash > 0 ? text.slice(0, slash) : "";
  }

  function activeEventTimelineHtml(events) {
    const rows = (events || []).slice(-6).map(event => `
      <div class="timeline-row"><i></i><time>${escapeHtml(event.time || "")}</time><span>${escapeHtml(event.message || "")}</span></div>
    `).join("");
    return `<div class="active-timeline">${rows || `<span class="muted">\u6682\u65e0\u4e8b\u4ef6</span>`}</div>`;
  }

  function activeTrendHtml(values, speedLabel = "0 B/s") {
    const raw = (values || []).map(value => Number(value) || 0).slice(-60);
    const normalized = Math.max(...raw, 0) > 1024 ? raw.map(value => value / 1048576) : raw;
    const max = Math.max(...normalized, 6);
    const width = 260;
    const height = 128;
    const left = 12;
    const right = width - 12;
    const top = 22;
    const bottom = height - 30;
    const usableWidth = width - 24;
    const usableHeight = bottom - top;
    const grid1 = bottom - usableHeight / 3;
    const grid2 = bottom - usableHeight * 2 / 3;
    const grid3 = top;
    const points = normalized.map((value, index) => {
      const x = left + (normalized.length <= 1 ? usableWidth : usableWidth * index / (normalized.length - 1));
      const y = bottom - usableHeight * value / max;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `
      <svg class="speed-trend" viewBox="0 0 ${width} ${height}" role="img" aria-label="\u901f\u5ea6\u8d8b\u52bf">
        <path d="M12 ${bottom}H248M12 ${top}V${bottom}" class="axis" />
        <path d="M12 ${grid1.toFixed(1)}H248M12 ${grid2.toFixed(1)}H248M12 ${grid3.toFixed(1)}H248" class="grid" />
        <polyline points="${points}" class="line" />
        <text x="12" y="120">60\u79d2</text><text x="76" y="120">45\u79d2</text><text x="136" y="120">30\u79d2</text><text x="196" y="120">15\u79d2</text><text x="224" y="120">\u73b0\u5728</text>
        <text class="speed-label" x="${right}" y="17" text-anchor="end">${escapeHtml(speedLabel || "0 B/s")}</text>
      </svg>
    `;
  }

  window.UcpMediaDisplay = {
    configure,
    displayMetadataValue,
    basenameFromPath,
    dirnameFromPath,
    activeEventTimelineHtml,
    activeTrendHtml,
  };
})();
