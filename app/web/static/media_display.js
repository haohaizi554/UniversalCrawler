(function () {
  let escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
  let translate = value => String(value || "");

  function configure(options = {}) {
    if (typeof options.esc === "function") escapeHtml = options.esc;
    if (typeof options.translate === "function") translate = options.translate;
  }

  function displayMetadataValue(value, pending = false) {
    const text = String(value || "").trim();
    if (text && text !== "--") return translate(text);
    return pending ? translate("\u68c0\u6d4b\u4e2d") : "--";
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
      <div class="timeline-row"><i></i><time>${escapeHtml(event.time || "")}</time><span>${escapeHtml(translate(event.message || ""))}</span></div>
    `).join("");
    return `<div class="active-timeline">${rows || `<span class="muted">${escapeHtml(translate("\u6682\u65e0\u4e8b\u4ef6"))}</span>`}</div>`;
  }

  function smoothTrendPath(points) {
    if (!points.length) return "";
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    const top = Math.min(...points.map(point => point.y));
    const bottom = Math.max(...points.map(point => point.y));
    const tension = 1 / 6;
    let d = `M${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
    for (let index = 0; index < points.length - 1; index += 1) {
      const p0 = points[index - 1] || points[index];
      const p1 = points[index];
      const p2 = points[index + 1];
      const p3 = points[index + 2] || p2;
      const c1x = p1.x + (p2.x - p0.x) * tension;
      const c1y = clamp(p1.y + (p2.y - p0.y) * tension, top, bottom);
      const c2x = p2.x - (p3.x - p1.x) * tension;
      const c2y = clamp(p2.y - (p3.y - p1.y) * tension, top, bottom);
      d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
    }
    return d;
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
      return { x, y };
    });
    const linePath = smoothTrendPath(points);
    return `
      <svg class="speed-trend" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(translate("\u901f\u5ea6\u8d8b\u52bf"))}">
        <path d="M12 ${bottom}H248M12 ${top}V${bottom}" class="axis" />
        <path d="M12 ${grid1.toFixed(1)}H248M12 ${grid2.toFixed(1)}H248M12 ${grid3.toFixed(1)}H248" class="grid" />
        <path d="${linePath}" class="line" />
        <text x="12" y="120">${escapeHtml(translate("60\u79d2"))}</text><text x="76" y="120">${escapeHtml(translate("45\u79d2"))}</text><text x="136" y="120">${escapeHtml(translate("30\u79d2"))}</text><text x="196" y="120">${escapeHtml(translate("15\u79d2"))}</text><text x="224" y="120">${escapeHtml(translate("\u73b0\u5728"))}</text>
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
