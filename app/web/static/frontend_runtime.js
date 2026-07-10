(function () {
  const MODULE_DISPOSERS = (
    "UcpLogCenter UcpListPages UcpSettingsController UcpDialogController UcpPlaybackController"
  ).split(" ");

  let dependencies = Object.freeze({});
  let configured = false;
  let active = false;
  let lifecycleListenersBound = false;
  let lifecycleGeneration = 0;
  let disposedGeneration = -1;
  let stateFetchSequence = 0;
  let deltaFetchSequence = 0;
  let stateOperationEpoch = 0;
  let actionSequence = 0;
  let socketSequence = 0;
  let frontendVersion = 0;
  let frontendSectionSignatures = {};
  let pendingRenderSections = new Set();
  let pendingActionSequences = new Set();
  let renderFrame = null;
  let ws = null;
  let wsReconnectTimer = null;
  let frontendDeltaTimer = null;
  let startPromise = null;

  function configure(options = {}) {
    if (active) return window.UcpFrontendRuntime;
    dependencies = Object.freeze({ ...options });
    configured = true;
    frontendVersion = Number((currentState() || {}).version || 0);
    frontendSectionSignatures = {};
    stateOperationEpoch = 0;
    return window.UcpFrontendRuntime;
  }

  function currentState() {
    if (typeof dependencies.getState === "function") return dependencies.getState();
    if (typeof dependencies.buildMockState === "function") return dependencies.buildMockState();
    return {};
  }

  function replaceState(nextState) {
    if (typeof dependencies.replaceState !== "function") {
      throw new Error("UcpFrontendRuntime requires replaceState");
    }
    dependencies.replaceState(nextState);
  }

  function markStateOperation() {
    stateOperationEpoch += 1;
  }

  function isCurrentGeneration(generation) {
    return active && generation === lifecycleGeneration;
  }

  function appendUiLog(label, detail = "") {
    if (typeof dependencies.appendUiLog === "function") dependencies.appendUiLog(label, detail);
  }

  function patchSection(section, value, context = {}) {
    if (typeof dependencies.patchSection !== "function") return [];
    const result = dependencies.patchSection(section, value, context);
    if (Array.isArray(result)) return result;
    if (!result || typeof result !== "object") return [];
    if (result.fetchDeltaDelay !== undefined) scheduleFrontendDeltaFetch(result.fetchDeltaDelay);
    if (result.renderAll && typeof dependencies.renderAll === "function") dependencies.renderAll();
    return Array.isArray(result.sections) ? result.sections : [];
  }

  function frontendSectionSignature(value) {
    try {
      return JSON.stringify(value === undefined ? null : value);
    } catch (_error) {
      return String(value);
    }
  }

  function rememberFrontendSectionSignatures(keys) {
    const state = currentState() || {};
    for (const key of keys || []) {
      frontendSectionSignatures[key] = frontendSectionSignature(state[key]);
    }
  }

  function scheduleFrame(callback) {
    if (typeof window.requestAnimationFrame === "function") {
      return { kind: "raf", id: window.requestAnimationFrame(callback) };
    }
    return { kind: "timer", id: setTimeout(callback, 16) };
  }

  function cancelRenderFrame() {
    if (!renderFrame) return;
    if (renderFrame.kind === "raf" && typeof window.cancelAnimationFrame === "function") {
      window.cancelAnimationFrame(renderFrame.id);
    } else {
      clearTimeout(renderFrame.id);
    }
    renderFrame = null;
  }

  function scheduleRenderSections(sections) {
    if (!active) return;
    const list = Array.isArray(sections) ? sections : [sections || "all"];
    for (const section of list) pendingRenderSections.add(section || "all");
    if (renderFrame) return;
    const generation = lifecycleGeneration;
    renderFrame = scheduleFrame(() => {
      renderFrame = null;
      if (!isCurrentGeneration(generation)) return;
      flushRenderSections(generation);
    });
  }

  function flushRenderSections(generation = lifecycleGeneration) {
    if (!isCurrentGeneration(generation)) return;
    const sections = new Set(pendingRenderSections);
    pendingRenderSections.clear();
    if (!sections.size) return;
    if (sections.has("all")) {
      if (typeof dependencies.renderAll === "function") dependencies.renderAll();
      return;
    }
    if (typeof dependencies.renderSections === "function") dependencies.renderSections(sections);
  }

  function applyFullState(data, context = {}) {
    if (!data || typeof data !== "object" || !Array.isArray(data.queue_items)) return false;
    const hasVersion = data.version !== undefined && data.version !== null && Number.isFinite(Number(data.version));
    const incomingVersion = hasVersion ? Number(data.version) : 0;
    const operationAdvanced = context.operationEpoch !== undefined && context.operationEpoch !== stateOperationEpoch;
    if (hasVersion && incomingVersion < frontendVersion) return false;
    if (operationAdvanced && (!hasVersion || incomingVersion <= frontendVersion)) return false;
    const nextState = { ...data };
    frontendVersion = hasVersion ? incomingVersion : Number(frontendVersion || 0);
    if (frontendVersion && !nextState.version) nextState.version = frontendVersion;
    replaceState(nextState);
    markStateOperation();
    const keys = Object.keys(nextState);
    for (const key of keys) patchSection(key, nextState[key], { ...context, full: true });
    rememberFrontendSectionSignatures(keys);
    if (typeof dependencies.renderAll === "function") dependencies.renderAll();
    return true;
  }

  function removeDeletedFromState(ids, context = {}) {
    const doomed = new Set((ids || []).map(id => String(id)).filter(Boolean));
    if (!doomed.size) return [];
    const itemSections = ["queue_items", "active_downloads", "completed_items", "failed_items"];
    const state = currentState() || {};
    const nextState = { ...state };
    for (const section of itemSections) {
      nextState[section] = (state[section] || []).filter(item => !doomed.has(String(item.id)));
    }
    replaceState(nextState);
    markStateOperation();
    const extra = patchSection("deleted_ids", Array.from(doomed), context);
    rememberFrontendSectionSignatures(itemSections);
    return Array.from(new Set([...itemSections, ...extra]));
  }

  function applyFrontendDelta(delta, generation = lifecycleGeneration) {
    if (!isCurrentGeneration(generation) || !delta || typeof delta !== "object") return false;
    const localVersion = Number(frontendVersion || 0);
    const deltaVersion = Number(delta.version || 0);
    if (!delta.full && deltaVersion && deltaVersion <= localVersion) return false;
    const deltaBaseVersion = Number(delta.base_version || 0);
    if (!delta.full && deltaBaseVersion > localVersion) {
      appendUiLog("增量状态基线不连续，正在重新同步...");
      fetchFrontendState();
      return false;
    }

    const state = currentState() || {};
    const sections = delta.sections && typeof delta.sections === "object" ? delta.sections : {};
    const requestedChanged = Array.isArray(delta.changed_sections)
      ? delta.changed_sections.slice()
      : Object.keys(sections);
    const changed = [];
    const nextState = { ...state };
    for (const [key, value] of Object.entries(sections)) {
      if (frontendSectionSignatures[key] === undefined) {
        frontendSectionSignatures[key] = frontendSectionSignature(state[key]);
      }
      const nextSignature = frontendSectionSignature(value);
      nextState[key] = value;
      if (delta.full || frontendSectionSignatures[key] !== nextSignature) changed.push(key);
      frontendSectionSignatures[key] = nextSignature;
    }
    if (delta.full) changed.push(...requestedChanged);
    frontendVersion = Number(delta.version || frontendVersion || 0);
    if (frontendVersion) nextState.version = frontendVersion;
    replaceState(nextState);
    markStateOperation();

    for (const [key, value] of Object.entries(sections)) {
      changed.push(...patchSection(key, value, { source: "delta", delta }));
    }
    if (Array.isArray(delta.deleted_ids) && delta.deleted_ids.length) {
      changed.push(...removeDeletedFromState(delta.deleted_ids, { source: "delta", delta }));
    }
    const uniqueChanged = Array.from(new Set(changed.filter(Boolean)));
    rememberFrontendSectionSignatures(Object.keys(sections));
    if (uniqueChanged.length) scheduleRenderSections(uniqueChanged);
    return uniqueChanged.length > 0;
  }

  function patchLegacyProgress(data) {
    const videoId = String(data.video_id || data.id || "");
    if (!videoId) return false;
    const state = currentState() || {};
    let changed = false;
    const rows = (state.active_downloads || []).map(item => {
      if (String(item.id) !== videoId) return item;
      const next = { ...item };
      if (data.progress !== undefined && data.progress !== null) next.progress = Number(data.progress) || 0;
      if (data.status) next.status = data.status;
      if (data.speed) next.speed = data.speed;
      changed = true;
      return next;
    });
    if (!changed) return false;
    replaceState({ ...state, active_downloads: rows });
    markStateOperation();
    rememberFrontendSectionSignatures(["active_downloads"]);
    return true;
  }

  function applyLegacyFrontendEvent(type, data) {
    if (type === "video_removed") {
      scheduleRenderSections([
        ...removeDeletedFromState([data.video_id || data.id || ""], { source: "legacy", type }),
        "app_status",
      ]);
      return;
    }
    if (type === "clear_videos") {
      const state = currentState() || {};
      const sections = ["queue_items", "active_downloads", "completed_items", "failed_items"];
      replaceState({ ...state, ...Object.fromEntries(sections.map(section => [section, []])) });
      markStateOperation();
      rememberFrontendSectionSignatures(sections);
      patchSection("clear_videos", data, { source: "legacy", type });
      scheduleRenderSections([...sections, "app_status"]);
      return;
    }
    if (type === "video_state_changed" || type === "task_progress") {
      if (patchLegacyProgress(data || {})) scheduleRenderSections(["active_downloads", "app_status"]);
      return;
    }
    scheduleFrontendDeltaFetch(300);
  }

  function scheduleFrontendDeltaFetch(delayMs = 200) {
    if (!active) return;
    if (frontendDeltaTimer) clearTimeout(frontendDeltaTimer);
    const generation = lifecycleGeneration;
    frontendDeltaTimer = setTimeout(() => {
      frontendDeltaTimer = null;
      if (!isCurrentGeneration(generation)) return;
      fetchFrontendDelta();
    }, Math.max(0, Number(delayMs) || 0));
  }

  async function fetchFrontendState() {
    if (!active) return false;
    const generation = lifecycleGeneration;
    const sequence = ++stateFetchSequence;
    const operationEpoch = stateOperationEpoch;
    let loaded = false;
    try {
      const response = await fetch("/api/frontend/state", { cache: "no-store" });
      if (!isCurrentGeneration(generation) || sequence !== stateFetchSequence || !response.ok) return false;
      const data = await response.json();
      if (!isCurrentGeneration(generation) || sequence !== stateFetchSequence) return false;
      loaded = applyFullState(data, { source: "fetch", generation, sequence, operationEpoch });
      return loaded;
    } catch (error) {
      if (isCurrentGeneration(generation) && sequence === stateFetchSequence) {
        appendUiLog("加载状态失败", error.message || error);
      }
      return false;
    } finally {
      if (isCurrentGeneration(generation) && sequence === stateFetchSequence && typeof dependencies.onSettled === "function") {
        dependencies.onSettled({ loaded, settled: true });
      }
    }
  }

  async function fetchFrontendDelta() {
    if (!active) return false;
    const generation = lifecycleGeneration;
    const sequence = ++deltaFetchSequence;
    try {
      const response = await fetch(
        `/api/frontend/delta?since_version=${encodeURIComponent(frontendVersion || 0)}`,
        { cache: "no-store" },
      );
      if (!isCurrentGeneration(generation) || sequence !== deltaFetchSequence || !response.ok) return false;
      const data = await response.json();
      if (!isCurrentGeneration(generation) || sequence !== deltaFetchSequence) return false;
      return applyFrontendDelta(data, generation);
    } catch (error) {
      if (isCurrentGeneration(generation) && sequence === deltaFetchSequence) {
        appendUiLog("加载增量状态失败", error.message || error);
      }
      return false;
    }
  }

  function connectWS() {
    if (!active || typeof window.WebSocket !== "function") return null;
    const WebSocketType = window.WebSocket;
    if (ws && [WebSocketType.CONNECTING, WebSocketType.OPEN].includes(ws.readyState)) return ws;
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    const generation = lifecycleGeneration;
    const sequence = ++socketSequence;
    try {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocketType(`${protocol}//${location.host}/ws`);
      ws = socket;
      socket.onopen = () => {
        if (!isCurrentGeneration(generation) || sequence !== socketSequence || ws !== socket) return;
        if (typeof dependencies.onConnected === "function") dependencies.onConnected(socket);
      };
      socket.onmessage = event => {
        if (!isCurrentGeneration(generation) || sequence !== socketSequence || ws !== socket) return;
        try {
          handleServerMessage(JSON.parse(event.data), generation, socket);
        } catch (error) {
          appendUiLog("处理服务器消息失败", error.message || error);
        }
      };
      socket.onclose = () => {
        if (!isCurrentGeneration(generation) || sequence !== socketSequence || ws !== socket) return;
        ws = null;
        wsReconnectTimer = setTimeout(() => {
          wsReconnectTimer = null;
          if (!isCurrentGeneration(generation) || sequence !== socketSequence) return;
          connectWS();
        }, 2000);
      };
      return socket;
    } catch (_error) {
      if (isCurrentGeneration(generation) && sequence === socketSequence) ws = null;
      return null;
    }
  }

  function handleServerMessage(message, generation = lifecycleGeneration, socket = null) {
    if (!isCurrentGeneration(generation) || (socket && socket !== ws)) return false;
    const type = message && message.type;
    const data = (message && message.data) || {};
    switch (type) {
      case "frontend_state":
        return applyFullState(data, { source: "socket", type });
      case "frontend_delta":
        return applyFrontendDelta(data, generation);
      case "init_state":
      case "platforms":
      case "config":
      case "select_tasks":
        scheduleRenderSections(patchSection(type, data, { source: "socket", type }));
        return true;
      case "crawl_state":
        patchSection(type, data, { source: "socket", type });
        scheduleFrontendDeltaFetch(200);
        return true;
      case "log":
        scheduleRenderSections(patchSection(type, data, { source: "socket", type }));
        return true;
      case "item_found":
      case "video_state_changed":
      case "video_renamed":
      case "video_removed":
      case "clear_videos":
      case "task_started":
      case "task_progress":
      case "task_finished":
      case "task_error":
      case "scan_result":
        applyLegacyFrontendEvent(type, data);
        return true;
      case "frontend_action_result":
        if (data.frontend_delta) applyFrontendDelta(data.frontend_delta, generation);
        if (data.message) patchSection("frontend_action_message", data.message, { source: "socket", type });
        return true;
      default:
        scheduleRenderSections(patchSection(type, data, { source: "socket", type }));
        return true;
    }
  }

  async function sendFrontendAction(data, generation, sequence) {
    try {
      const response = await fetch("/api/frontend/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!isCurrentGeneration(generation) || !pendingActionSequences.has(sequence)) return;
      const result = await response.json();
      if (!isCurrentGeneration(generation) || !pendingActionSequences.has(sequence)) return;
      if (result && result.frontend_delta) applyFrontendDelta(result.frontend_delta, generation);
      else await fetchFrontendDelta();
      if (isCurrentGeneration(generation) && pendingActionSequences.has(sequence) && result && result.message) {
        patchSection("frontend_action_message", result.message, { source: "fetch", sequence });
      }
    } catch (error) {
      if (isCurrentGeneration(generation) && pendingActionSequences.has(sequence)) {
        patchSection("frontend_action_error", error.message || String(error), { source: "fetch", sequence });
      }
    } finally {
      pendingActionSequences.delete(sequence);
    }
  }

  function send(type, data = {}) {
    if (!active) return false;
    const payload = type === "frontend_action"
      ? { ...data, frontend_version: Number(frontendVersion || 0) }
      : data;
    const WebSocketType = window.WebSocket;
    if (ws && WebSocketType && ws.readyState === WebSocketType.OPEN) {
      ws.send(JSON.stringify({ type, data: payload }));
      return true;
    }
    if (type !== "frontend_action") return false;
    const generation = lifecycleGeneration;
    const sequence = ++actionSequence;
    pendingActionSequences.add(sequence);
    void sendFrontendAction(payload, generation, sequence);
    return true;
  }

  function bindLifecycleListeners() {
    if (lifecycleListenersBound) return;
    lifecycleListenersBound = true;
    window.addEventListener("pagehide", cleanupPageResources);
    window.addEventListener("beforeunload", cleanupPageResources);
  }

  function start() {
    if (active) return startPromise;
    if (!configured) throw new Error("UcpFrontendRuntime must be configured before start");
    active = true;
    lifecycleGeneration += 1;
    disposedGeneration = -1;
    frontendVersion = Number((currentState() || {}).version || 0);
    frontendSectionSignatures = {};
    stateOperationEpoch = 0;
    pendingRenderSections.clear();
    bindLifecycleListeners();
    connectWS();
    startPromise = fetchFrontendState();
    return startPromise;
  }

  function cleanupPageResources() {
    dispose();
  }

  function disposeModulesOnce(generation) {
    if (disposedGeneration === generation) return;
    disposedGeneration = generation;
    for (const name of MODULE_DISPOSERS) {
      const module = window[name];
      if (module && typeof module.dispose === "function") module.dispose();
    }
  }

  function dispose() {
    const generation = lifecycleGeneration;
    if (!active || disposedGeneration === generation) return;
    active = false;
    lifecycleGeneration += 1;
    stateFetchSequence += 1;
    deltaFetchSequence += 1;
    socketSequence += 1;
    pendingActionSequences.clear();
    pendingRenderSections.clear();
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    if (frontendDeltaTimer) {
      clearTimeout(frontendDeltaTimer);
      frontendDeltaTimer = null;
    }
    cancelRenderFrame();
    if (ws) {
      const socket = ws;
      ws = null;
      try {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      } catch (_error) {
        // Page teardown must continue even when the browser rejects close().
      }
    }
    disposeModulesOnce(generation);
    startPromise = null;
  }

  window.UcpFrontendRuntime = Object.freeze({
    configure,
    start,
    connect: connectWS,
    fetchState: fetchFrontendState,
    fetchDelta: fetchFrontendDelta,
    scheduleDelta: scheduleFrontendDeltaFetch,
    scheduleSections: scheduleRenderSections,
    handleServerMessage,
    send,
    dispose,
  });
})();
