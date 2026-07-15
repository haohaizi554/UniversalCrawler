(function () {
  "use strict";

  function stripLeadingEmoji(value) {
    return String(value || "")
      .trim()
      .replace(/^[\p{Extended_Pictographic}\u2600-\u27BF\uFE0F\u200D]+/u, "")
      .trim();
  }

  function looksLikePath(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    return text.includes(":\\") || text.startsWith("/") || text.startsWith("\\\\") || (text.includes("\\") && text.length >= 8);
  }

  function extractMessagePayload(value) {
    const clean = stripLeadingEmoji(value);
    const delimiter = clean.indexOf(":");
    if (delimiter < 0) return null;
    const description = clean.slice(0, delimiter).trim();
    const path = clean.slice(delimiter + 1).trim();
    return description && looksLikePath(path) ? { description, path } : null;
  }

  function parsedDetailPayload(detail) {
    if (detail && typeof detail === "object") {
      return Array.isArray(detail) ? [...detail] : { ...detail };
    }
    const text = String(detail || "").trim();
    if (!text) return {};
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" ? parsed : { detail: parsed };
    } catch (_error) {
      return { detail: text };
    }
  }

  function normalizeLogDetailPayload(item, hints = {}) {
    // 与 GUI 共用的 normalize_detail_payload 契约保持一致：优先使用服务端投影，
    // 本地归一化只补充尚未进入服务端快照的临时客户端行。
    if (!item) return {};
    const projected = item.detail_payload;
    const payload = parsedDetailPayload(
      projected && typeof projected === "object" ? projected : item.detail
    );
    if (!payload || Array.isArray(payload) || typeof payload !== "object") return payload || {};

    const description = String(payload.description || "").trim();
    if (description) {
      const localizedDescription = hintValue(hints, "description", description);
      const extracted = extractMessagePayload(localizedDescription);
      payload.description = extracted ? extracted.description : stripLeadingEmoji(localizedDescription);
      if (extracted && !payload.path) payload.path = extracted.path;
    }

    const detailText = String(payload.detail || "").trim();
    if (detailText && !payload.description) {
      const localizedDetail = hintValue(hints, "detail", detailText);
      const extracted = extractMessagePayload(localizedDetail);
      payload.description = extracted ? extracted.description : stripLeadingEmoji(localizedDetail);
      if (extracted && !payload.path) payload.path = extracted.path;
    }

    const rawMessage = String(item.message || item.message_summary || "").trim();
    const message = hintValue(hints, "message", rawMessage);
    const messagePayload = message ? extractMessagePayload(message) : null;
    if (messagePayload) {
      if (!payload.description) payload.description = messagePayload.description;
      if (!payload.path) payload.path = messagePayload.path;
    } else if (message && !payload.description) {
      payload.description = stripLeadingEmoji(message);
    }

    const event = item.event || item.event_type || item.status_code || "";
    if (event && !payload.status_code && !payload.event) payload.event = event;
    const statusCode = String(item.status_code || item.event_code || "").trim();
    if (statusCode && !payload.status_code) payload.status_code = statusCode;
    for (const key of ["platform", "source", "trace_id"]) {
      const value = item[key];
      if (value && !payload[key]) payload[key] = value;
    }
    return Object.fromEntries(
      Object.entries(payload).filter(([_key, value]) => value !== null && value !== "" && !(Array.isArray(value) && value.length === 0))
    );
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
    const detailPayload = localizedLogDetailValue(normalizeLogDetailPayload(item, hints), "", hints);
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
