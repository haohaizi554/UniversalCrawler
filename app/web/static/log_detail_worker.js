(function () {
  "use strict";

  function normalizeLogDetailPayload(item) {
    // detail 可能是对象、JSON 字符串或普通文本；统一成可展示/导出的对象。
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

  function hintValue(hints, key, value) {
    const text = readableLogDetailValue(value);
    if (!text) return text;
    const scoped = `${String(key || "")}:${text}`;
    return hints[scoped] || hints[text] || hints[text.trim()] || text;
  }

  function localizedLogDetailValue(value, key = "", hints = {}) {
    if (Array.isArray(value)) return value.map(item => localizedLogDetailValue(item, key, hints));
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([childKey, item]) => [childKey, localizedLogDetailValue(item, childKey, hints)]));
    }
    if (typeof value === "string") return hintValue(hints, key, value);
    return value;
  }

  function formatLogDetailDisplayText(payload) {
    if (!payload || typeof payload !== "object") return readableLogDetailValue(payload);
    const entries = Object.entries(payload);
    if (!entries.length) return "{}";
    return entries.map(([key, value]) => {
      const readable = readableLogDetailValue(value);
      return readable.includes("\n") ? `${key}:\n${readable}` : `${key}: ${readable}`;
    }).join("\n");
  }

  function translated(hints, key, fallback = "") {
    return hintValue(hints, key, fallback || "");
  }

  function logItemId(item) {
    return String(item.id || `${item.time || ""}|${item.trace_id || ""}|${item.source || ""}|${item.message_summary || ""}`);
  }

  function safeFilenameSuffix(value) {
    return String(value || "current").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 80) || "current";
  }

  function buildLogDetailResult(request = {}) {
    // 同时产出显示文本和完整 JSON，避免主线程重复格式化日志详情。
    const item = request.item || {};
    const hints = request.translations || {};
    const detailPayload = localizedLogDetailValue(normalizeLogDetailPayload(item), "", hints);
    const detailJson = JSON.stringify(detailPayload, null, 2);
    const detailDisplayText = formatLogDetailDisplayText(detailPayload);
    const fullPayload = {
      time: item.time || "",
      level: item.level || item.raw_level || "",
      platform: translated(hints, "platform", item.platform_display || item.platform || ""),
      source: translated(hints, "source", item.source || ""),
      trace_id: item.trace_id || "",
      message: translated(hints, "message", item.message || item.message_summary || ""),
      detail: detailPayload,
      stack: item.stack || "",
    };
    return {
      sequence: Number(request.sequence) || 0,
      itemId: String(request.itemId || logItemId(item)),
      language: String(request.language || ""),
      item,
      detailPayload,
      detailJson,
      detailDisplayText,
      fullPayload,
      fullJson: JSON.stringify(fullPayload, null, 2),
      stack: String(item.stack || "").trim(),
      filename: `log_detail_${safeFilenameSuffix(item.trace_id || request.itemId || logItemId(item))}.json`,
    };
  }

  self.onmessage = event => {
    const request = event && event.data ? event.data : {};
    try {
      self.postMessage({ type: "result", result: buildLogDetailResult(request) });
    } catch (error) {
      self.postMessage({
        type: "error",
        sequence: Number(request.sequence) || 0,
        itemId: String(request.itemId || ""),
        message: error && error.message ? String(error.message) : String(error),
      });
    }
  };
})();
