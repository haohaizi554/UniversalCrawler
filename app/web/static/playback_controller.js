(function () {
  let dependencies = Object.freeze({});
  const state = {
    generation: 0,
    operation: 0,
    pendingSourceId: "",
    currentPlayingId: "",
    isFullscreenMode: false,
    imageAutoAdvanceTimer: null,
    ownedListeners: [],
    mediaControlsInstalled: false,
    disposed: true,
  };

  function configure(options = {}) {
    dispose();
    dependencies = Object.freeze({ ...options });
    state.generation += 1;
    state.operation = 0;
    state.pendingSourceId = "";
    state.currentPlayingId = "";
    state.isFullscreenMode = false;
    state.imageAutoAdvanceTimer = null;
    state.ownedListeners = [];
    state.mediaControlsInstalled = false;
    state.disposed = false;
    addOwnedListener(document, "fullscreenchange", handleFullscreenChange);
    return window.UcpPlaybackController;
  }

  function requireDependency(name) {
    const value = dependencies[name];
    if (typeof value !== "function") throw new Error(`UcpPlaybackController is not configured: ${name}`);
    return value;
  }

  function currentState() {
    return requireDependency("getState")() || {};
  }

  function getSelectedCompletedId() {
    return String(requireDependency("getSelectedCompletedId")() || "");
  }

  function setSelectedCompletedId(id) {
    requireDependency("setSelectedCompletedId")(String(id || ""));
  }

  function t(value) {
    return requireDependency("t")(value);
  }

  function byId(id) {
    return requireDependency("byId")(id);
  }

  function esc(value) {
    return requireDependency("esc")(value);
  }

  function playbackStateService() {
    if (!window.UcpPlaybackState) throw new Error("UcpPlaybackState is unavailable");
    return window.UcpPlaybackState;
  }

  function mediaDisplayService() {
    return window.UcpMediaDisplay || null;
  }

  function addOwnedListener(target, type, handler, options) {
    if (!target || typeof target.addEventListener !== "function") return;
    target.addEventListener(type, handler, options);
    state.ownedListeners.push({ target, type, handler, options });
  }

  function detachOwnedListeners() {
    for (const listener of state.ownedListeners) {
      listener.target.removeEventListener(listener.type, listener.handler, listener.options);
    }
    state.ownedListeners = [];
    state.mediaControlsInstalled = false;
  }

  function isCurrentGeneration(generation) {
    return !state.disposed && state.generation === generation;
  }

  function isCurrentOperation(generation, operation, sourceId = "") {
    if (!isCurrentGeneration(generation) || state.operation !== operation) return false;
    return !sourceId || state.currentPlayingId === String(sourceId);
  }

  function completedItemById(id) {
    return playbackStateService().completedItemById(currentState(), id);
  }

  function completedPreviewOrder() {
    return (currentState().completed_items || [])
      .map(item => item.id)
      .filter(id => id !== undefined && id !== null && String(id));
  }

  function adjacentCompletedId(currentId, direction, wrap = true) {
    const order = completedPreviewOrder();
    if (!order.length) return "";
    const normalized = String(currentId || "");
    const index = order.findIndex(id => String(id) === normalized);
    if (index < 0) return direction >= 0 ? order[0] : order[order.length - 1];
    let nextIndex = index + (direction >= 0 ? 1 : -1);
    if (wrap) nextIndex = (nextIndex + order.length) % order.length;
    if (nextIndex < 0 || nextIndex >= order.length) return "";
    return order[nextIndex];
  }

  function mediaUrl(id) {
    return `/api/media/${encodeURIComponent(id)}`;
  }

  function playbackItemLabel(item, fallback = "") {
    const mediaDisplay = mediaDisplayService();
    const pathLabel = mediaDisplay && typeof mediaDisplay.basenameFromPath === "function"
      ? mediaDisplay.basenameFromPath(item && item.local_path)
      : "";
    return String((item && (item.title || item.filename)) || pathLabel || fallback || "").trim();
  }

  function appendLog(message) {
    requireDependency("appendLog")(String(message || ""));
  }

  function appendUiLog(label, detail = "", prefix = "") {
    const suffix = String(detail || "").trim();
    appendLog(`${prefix}${t(label)}${suffix ? `: ${suffix}` : ""}`);
  }

  function appendPlaybackFailure(item, error) {
    const label = playbackItemLabel(item);
    const detail = error && (error.message || String(error)) ? `: ${error.message || String(error)}` : "";
    appendLog(`\u274c ${t("\u64ad\u653e\u5931\u8d25")}${label ? ` [${label}]` : ""}${detail}`);
  }

  function shouldUseBuiltinPlayer() {
    return playbackStateService().shouldUseBuiltinPlayer(currentState());
  }

  function shouldRememberPlaybackPosition() {
    return playbackStateService().shouldRememberPlaybackPosition(currentState());
  }

  function shouldAutoplayNext() {
    return playbackStateService().shouldAutoplayNext(currentState());
  }

  function shouldManualSwitchImages() {
    return playbackStateService().shouldManualSwitchImages(currentState());
  }

  function imageAutoAdvanceIntervalMs() {
    return playbackStateService().imageAutoAdvanceIntervalMs(currentState());
  }

  function clearImageAutoAdvanceTimer() {
    if (state.imageAutoAdvanceTimer === null) return;
    clearTimeout(state.imageAutoAdvanceTimer);
    state.imageAutoAdvanceTimer = null;
  }

  function scheduleImageAutoAdvance(id) {
    clearImageAutoAdvanceTimer();
    if (!id || shouldManualSwitchImages()) return;
    const generation = state.generation;
    const operation = state.operation;
    state.imageAutoAdvanceTimer = setTimeout(() => {
      state.imageAutoAdvanceTimer = null;
      if (isCurrentOperation(generation, operation, id)) autoplayNextPreview();
    }, imageAutoAdvanceIntervalMs());
  }

  function rescheduleImageAutoAdvance() {
    const item = completedItemById(state.currentPlayingId);
    if (item && playbackStateService().isImageItem(item)) scheduleImageAutoAdvance(state.currentPlayingId);
    else clearImageAutoAdvanceTimer();
  }

  function removePlaybackPosition(id) {
    playbackStateService().removePlaybackPosition(localStorage, currentState(), id);
  }

  function cleanupPlaybackPositions(items) {
    playbackStateService().cleanupPlaybackPositions(localStorage, currentState(), items);
  }

  function playbackPositionKey(id) {
    return playbackStateService().playbackPositionKey(currentState(), id);
  }

  function legacyPlaybackPositionKey(id) {
    return playbackStateService().legacyPlaybackPositionKey(id);
  }

  function rememberWebPlaybackPosition(sourceId, player) {
    if (!sourceId || !player || !shouldRememberPlaybackPosition()) return;
    if (!Number.isFinite(player.currentTime) || player.currentTime < 1) return;
    if (Number.isFinite(player.duration) && player.duration > 0 && player.currentTime >= player.duration - 1.5) {
      removePlaybackPosition(sourceId);
      return;
    }
    try {
      localStorage.setItem(playbackPositionKey(sourceId), String(Math.floor(player.currentTime)));
      localStorage.removeItem(legacyPlaybackPositionKey(sourceId));
    } catch (_error) {}
  }

  function restoreWebPlaybackPosition(sourceId, player) {
    if (!sourceId || !player || !shouldRememberPlaybackPosition()) return;
    let seconds = 0;
    try {
      const value = localStorage.getItem(playbackPositionKey(sourceId)) || localStorage.getItem(legacyPlaybackPositionKey(sourceId));
      seconds = Number(value || 0);
    } catch (_error) {
      seconds = 0;
    }
    if (seconds > 0 && Number.isFinite(seconds)) player.currentTime = seconds;
  }

  function mediaActionIconSrc(action) {
    const manifest = currentState().icon_manifest || {};
    const fallbackActions = {
      pause: "action_pause.png",
      play: "action_play.png",
    };
    const actions = manifest.actions || fallbackActions;
    const file = actions[action] || fallbackActions[action] || manifest.fallback || "view_grid.png";
    const route = String(manifest.route || "/ui-icon").replace(/\/+$/, "");
    return `${route}/${String(file).replace(/^\/+/, "")}`;
  }

  function mediaHasVideoSource(player) {
    return !!(player && (player.currentSrc || player.getAttribute("src")));
  }

  function mediaDuration(player) {
    const duration = Number(player && player.duration);
    return Number.isFinite(duration) && duration > 0 ? duration : 0;
  }

  function mediaCurrentTime(player) {
    const current = Number(player && player.currentTime);
    return Number.isFinite(current) && current > 0 ? current : 0;
  }

  function setPlayButtonState(playing, disabled = false) {
    const button = byId("playBtn");
    if (!button) return;
    button.disabled = !!disabled;
    const action = playing ? "pause" : "play";
    const label = playing ? t("\u6682\u505c") : t("\u64ad\u653e");
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = `<img src="${esc(mediaActionIconSrc(action))}" alt="" />`;
  }

  function updateNavBtnsState() {
    const disabled = completedPreviewOrder().length <= 1;
    const previous = byId("prevBtn");
    const next = byId("nextBtn");
    if (previous) previous.disabled = disabled;
    if (next) next.disabled = disabled;
  }

  function updateFullscreenButtonState() {
    const button = byId("fullscreenBtn");
    if (!button) return;
    button.textContent = `[ ${t(state.isFullscreenMode ? "\u9000\u51fa" : "\u5168\u5c4f")} ]`;
  }

  function updateMediaControls(player = byId("videoPlayer")) {
    const slider = byId("seekSlider");
    const label = byId("timeLabel");
    const hasVideo = mediaHasVideoSource(player);
    const canStartPreview = !!(state.currentPlayingId || getSelectedCompletedId());
    const duration = hasVideo ? mediaDuration(player) : 0;
    const current = hasVideo ? mediaCurrentTime(player) : 0;
    const dragging = slider && slider.dataset.dragging === "1";
    if (slider) {
      slider.disabled = !hasVideo || duration <= 0;
      slider.max = String(Math.max(0, Math.floor(duration)));
      if (!dragging) slider.value = String(Math.min(Math.floor(current), Math.floor(duration || current)));
    }
    if (label) {
      label.textContent = hasVideo
        ? `${playbackStateService().fmtTime(current)} / ${playbackStateService().fmtTime(duration)}`
        : "00:00";
    }
    setPlayButtonState(hasVideo && !player.paused && !player.ended, !hasVideo && !canStartPreview);
    updateNavBtnsState();
    updateFullscreenButtonState();
  }

  function onSeekInput(value) {
    const player = byId("videoPlayer");
    if (!mediaHasVideoSource(player)) {
      updateMediaControls(player);
      return;
    }
    const duration = mediaDuration(player);
    const nextTime = Math.max(0, Math.min(Number(value) || 0, duration || Number(value) || 0));
    const label = byId("timeLabel");
    if (label) label.textContent = `${playbackStateService().fmtTime(nextTime)} / ${playbackStateService().fmtTime(duration)}`;
  }

  function onSeekCommit(value) {
    const player = byId("videoPlayer");
    if (!mediaHasVideoSource(player)) {
      updateMediaControls(player);
      return;
    }
    const duration = mediaDuration(player);
    const nextTime = Math.max(0, Math.min(Number(value) || 0, duration || Number(value) || 0));
    if (Number.isFinite(nextTime)) player.currentTime = nextTime;
    const slider = byId("seekSlider");
    if (slider) slider.dataset.dragging = "";
    updateMediaControls(player);
  }

  function installMediaControlHandlers() {
    if (state.disposed || state.mediaControlsInstalled) return;
    state.mediaControlsInstalled = true;
    const slider = byId("seekSlider");
    if (slider) {
      const beginDrag = () => { slider.dataset.dragging = "1"; };
      const finishDrag = () => {
        if (slider.dataset.dragging === "1") onSeekCommit(slider.value);
        slider.dataset.dragging = "";
      };
      addOwnedListener(slider, "pointerdown", beginDrag);
      addOwnedListener(slider, "touchstart", beginDrag, { passive: true });
      addOwnedListener(slider, "pointerup", finishDrag);
      addOwnedListener(slider, "pointercancel", finishDrag);
      addOwnedListener(slider, "touchend", finishDrag);
    }
    const player = byId("videoPlayer");
    if (player) {
      addOwnedListener(player, "play", () => updateMediaControls(player));
      addOwnedListener(player, "pause", () => updateMediaControls(player));
      addOwnedListener(player, "durationchange", () => updateMediaControls(player));
    }
  }

  async function validateMediaForPreview(id, generation, operation) {
    try {
      const response = await fetch(mediaUrl(id), {
        method: "GET",
        headers: { Range: "bytes=0-0" },
        cache: "no-store",
      });
      if (!isCurrentOperation(generation, operation)) return false;
      if (response.body && typeof response.body.cancel === "function") {
        response.body.cancel().catch(() => {});
      }
      if (response.ok) return true;
      appendUiLog(
        response.status === 404 ? "\u6587\u4ef6\u4e0d\u5b58\u5728\u6216\u5df2\u88ab\u5220\u9664" : "\u64ad\u653e\u524d\u6821\u9a8c\u5931\u8d25",
        response.status === 404 ? "" : `HTTP ${response.status}`,
        "\u274c ",
      );
      return false;
    } catch (error) {
      if (!isCurrentOperation(generation, operation)) return false;
      appendUiLog("\u64ad\u653e\u524d\u6821\u9a8c\u5931\u8d25", error.message || error, "\u274c ");
      return false;
    }
  }

  function reportCompletedPlayerMetadata(sourceId, player, generation, operation) {
    if (!isCurrentOperation(generation, operation, sourceId) || !player) return;
    const metadata = {};
    if (Number.isFinite(player.duration) && player.duration > 0) {
      metadata.duration = playbackStateService().fmtClockTime(player.duration);
    }
    if (player.videoWidth > 0 && player.videoHeight > 0) {
      metadata.resolution = `${player.videoWidth} x ${player.videoHeight}`;
    }
    if (!Object.keys(metadata).length) return;
    const changed = typeof dependencies.patchCompletedMetadata === "function"
      ? dependencies.patchCompletedMetadata(sourceId, metadata)
      : false;
    const report = requireDependency("frontendAction")("update_completed_metadata", {
      id: sourceId,
      metadata,
      source: "web_player",
    });
    if (report && typeof report.catch === "function") {
      report.catch(error => {
        if (isCurrentOperation(generation, operation, sourceId)) appendPlaybackFailure(completedItemById(sourceId), error);
      });
    }
    if (changed && isCurrentOperation(generation, operation, sourceId)) {
      requireDependency("renderCompletedDetail")();
    }
  }

  function setupPlayerEvents(player, sourceId, generation = state.generation, operation = state.operation) {
    if (!player) return;
    const item = completedItemById(sourceId) || {};
    const isCurrentMedia = () => isCurrentOperation(generation, operation, sourceId);
    player.onloadedmetadata = () => {
      if (!isCurrentMedia()) return;
      reportCompletedPlayerMetadata(sourceId, player, generation, operation);
      if (!isCurrentMedia()) return;
      restoreWebPlaybackPosition(sourceId, player);
      updateMediaControls(player);
    };
    player.ondurationchange = () => { if (isCurrentMedia()) updateMediaControls(player); };
    player.onplay = () => { if (isCurrentMedia()) updateMediaControls(player); };
    player.onpause = () => { if (isCurrentMedia()) updateMediaControls(player); };
    player.ontimeupdate = () => {
      if (!isCurrentMedia()) return;
      rememberWebPlaybackPosition(sourceId, player);
      updateMediaControls(player);
    };
    player.onseeked = () => { if (isCurrentMedia()) updateMediaControls(player); };
    player.onerror = () => {
      if (!isCurrentMedia()) return;
      updateMediaControls(player);
      appendPlaybackFailure(item, player.error || "media error");
    };
    player.onended = () => {
      if (!isCurrentMedia()) return;
      removePlaybackPosition(sourceId);
      updateMediaControls(player);
      if (shouldAutoplayNext()) autoplayNextPreview();
    };
  }

  function safelyResetPlayer(player) {
    if (!player) return;
    try { player.pause(); } catch (_error) {}
    player.removeAttribute("src");
    try { player.load(); } catch (_error) {}
    player.style.display = "none";
  }

  async function playCompleted(id) {
    const sourceId = String(id || "");
    setSelectedCompletedId(sourceId);
    const generation = state.generation;
    const operation = ++state.operation;
    state.pendingSourceId = sourceId;
    const initialItem = completedItemById(sourceId);
    if (!initialItem || !initialItem.local_path) {
      if (isCurrentOperation(generation, operation)) {
        state.pendingSourceId = "";
        appendUiLog("\u6587\u4ef6\u4e0d\u5b58\u5728\u6216\u5df2\u88ab\u5220\u9664", "", "\u274c ");
      }
      return false;
    }
    if (!(await validateMediaForPreview(sourceId, generation, operation))) {
      if (isCurrentOperation(generation, operation)) state.pendingSourceId = "";
      return false;
    }
    if (!isCurrentOperation(generation, operation)) return false;
    const item = completedItemById(sourceId);
    if (!item || !item.local_path) {
      state.pendingSourceId = "";
      return false;
    }
    state.pendingSourceId = "";
    state.currentPlayingId = sourceId;
    if (!shouldUseBuiltinPlayer()) {
      clearImageAutoAdvanceTimer();
      updateMediaControls();
      requireDependency("frontendAction")("open_file", { id: sourceId });
      return true;
    }
    const player = byId("videoPlayer");
    const placeholder = byId("previewArea");
    if (!player || !placeholder) return false;
    if (playbackStateService().isImageItem(item)) {
      safelyResetPlayer(player);
      placeholder.innerHTML = `<img class="preview-image" src="${mediaUrl(sourceId)}" alt="${esc(item.title || item.filename || "")}" />`;
      placeholder.style.display = "flex";
      scheduleImageAutoAdvance(sourceId);
      updateMediaControls(player);
      return true;
    }
    clearImageAutoAdvanceTimer();
    placeholder.textContent = "";
    player.src = mediaUrl(sourceId);
    setupPlayerEvents(player, sourceId, generation, operation);
    player.style.display = "block";
    placeholder.style.display = "none";
    updateMediaControls(player);
    try {
      const playResult = player.play();
      if (playResult && typeof playResult.catch === "function") {
        playResult.catch(error => {
          if (isCurrentOperation(generation, operation, sourceId)) appendPlaybackFailure(item, error);
        });
      }
    } catch (error) {
      if (isCurrentOperation(generation, operation, sourceId)) appendPlaybackFailure(item, error);
    }
    return true;
  }

  function previewVideo(id) {
    return playCompleted(id);
  }

  function autoplayNextPreview() {
    const nextId = adjacentCompletedId(state.currentPlayingId, 1, false);
    if (nextId) void playCompleted(nextId);
  }

  function switchPreview(direction) {
    const current = state.currentPlayingId || getSelectedCompletedId();
    const nextId = adjacentCompletedId(current, Number(direction) || 1, true);
    if (nextId) void playCompleted(nextId);
  }

  function togglePlay() {
    const player = byId("videoPlayer");
    if (!mediaHasVideoSource(player)) {
      const id = state.currentPlayingId || getSelectedCompletedId();
      if (id) void playCompleted(id);
      return;
    }
    const generation = state.generation;
    const operation = state.operation;
    const sourceId = state.currentPlayingId;
    if (player.paused) {
      try {
        const playResult = player.play();
        if (playResult && typeof playResult.catch === "function") {
          playResult.catch(error => {
            if (isCurrentOperation(generation, operation, sourceId)) appendPlaybackFailure(completedItemById(sourceId), error);
          });
        }
      } catch (error) {
        if (isCurrentOperation(generation, operation, sourceId)) appendPlaybackFailure(completedItemById(sourceId), error);
      }
    } else {
      player.pause();
    }
    updateMediaControls(player);
  }

  function handleFullscreenChange() {
    if (state.disposed) return;
    const panel = byId("previewPanel");
    state.isFullscreenMode = !!panel && document.fullscreenElement === panel;
    if (panel) panel.classList.toggle("is-fullscreen", state.isFullscreenMode);
    updateFullscreenButtonState();
  }

  function exitFullscreenSafely() {
    if (typeof document.exitFullscreen !== "function") return Promise.resolve(false);
    try {
      const result = document.exitFullscreen();
      if (result && typeof result.then === "function") return result.then(() => true, () => false);
      return Promise.resolve(true);
    } catch (_error) {
      return Promise.resolve(false);
    }
  }

  function toggleFullscreen() {
    const panel = byId("previewPanel");
    if (!panel || !panel.requestFullscreen) return;
    const generation = state.generation;
    const operation = state.operation;
    if (document.fullscreenElement === panel) {
      return exitFullscreenSafely();
    }
    let request;
    try {
      request = panel.requestFullscreen();
    } catch (error) {
      if (isCurrentOperation(generation, operation)) appendLog(error.message || String(error));
      return Promise.resolve(false);
    }
    return Promise.resolve(request).then(
      () => {
        if (isCurrentOperation(generation, operation)) return true;
        if (document.fullscreenElement === panel) return exitFullscreenSafely();
        return false;
      },
      error => {
        if (isCurrentOperation(generation, operation)) appendLog(error.message || String(error));
        return false;
      },
    );
  }

  function handleShortcut(event) {
    if (state.disposed || !event || event.key !== "Escape") return false;
    const panel = byId("previewPanel");
    if (!state.isFullscreenMode || document.fullscreenElement !== panel) return false;
    void exitFullscreenSafely();
    return true;
  }

  function closePreview() {
    if (state.disposed) return;
    state.operation += 1;
    state.pendingSourceId = "";
    clearImageAutoAdvanceTimer();
    const player = byId("videoPlayer");
    safelyResetPlayer(player);
    const placeholder = byId("previewArea");
    if (placeholder) {
      placeholder.textContent = "";
      placeholder.style.display = "flex";
    }
    state.currentPlayingId = "";
    updateMediaControls(player);
  }

  function prepareDeleteItem(id) {
    const sourceId = String(id || "");
    if (!sourceId || (state.pendingSourceId !== sourceId && state.currentPlayingId !== sourceId)) return;
    state.operation += 1;
    state.pendingSourceId = "";
    if (state.currentPlayingId === sourceId) closePreview();
  }

  function deleteVideo(id) {
    prepareDeleteItem(id);
    requireDependency("frontendAction")("delete_item", { id });
  }

  function neutralizePlayerHandlers(player) {
    if (!player) return;
    for (const property of [
      "onloadedmetadata",
      "ondurationchange",
      "onplay",
      "onpause",
      "ontimeupdate",
      "onseeked",
      "onerror",
      "onended",
    ]) {
      player[property] = null;
    }
  }

  function dispose() {
    if (state.disposed) return;
    state.disposed = true;
    state.generation += 1;
    state.operation += 1;
    clearImageAutoAdvanceTimer();
    detachOwnedListeners();
    const lookup = typeof dependencies.byId === "function" ? dependencies.byId : id => document.getElementById(id);
    const player = lookup("videoPlayer");
    neutralizePlayerHandlers(player);
    safelyResetPlayer(player);
    const placeholder = lookup("previewArea");
    if (placeholder) {
      placeholder.textContent = "";
      placeholder.style.display = "flex";
    }
    const panel = lookup("previewPanel");
    if (panel) panel.classList.remove("is-fullscreen");
    if (panel && document.fullscreenElement === panel && typeof document.exitFullscreen === "function") {
      try {
        const result = document.exitFullscreen();
        if (result && typeof result.catch === "function") result.catch(() => {});
      } catch (_error) {}
    }
    state.currentPlayingId = "";
    state.pendingSourceId = "";
    state.isFullscreenMode = false;
    state.imageAutoAdvanceTimer = null;
    dependencies = Object.freeze({});
  }

  window.UcpPlaybackController = Object.freeze({
    configure,
    playCompleted,
    previewVideo,
    togglePlay,
    toggleFullscreen,
    switchPreview,
    onSeekInput,
    onSeekCommit,
    installMediaControlHandlers,
    updateControls: updateMediaControls,
    rescheduleImageAutoAdvance,
    removePlaybackPosition,
    cleanupPlaybackPositions,
    prepareDeleteItem,
    deleteVideo,
    handleShortcut,
    closePreview,
    dispose,
  });
})();
