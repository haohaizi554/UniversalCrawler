(function () {
  const PLAYBACK_POSITION_PREFIX = "ucp_playback_position_";
  const PLAYBACK_SETTINGS_KEY = "\u64ad\u653e\u8bbe\u7f6e";

  function playbackSettings(state) {
    const snapshot = state && state.settings_snapshot ? state.settings_snapshot : {};
    return snapshot[PLAYBACK_SETTINGS_KEY] || {};
  }

  function shouldUseBuiltinPlayer(state) {
    const settings = playbackSettings(state);
    return String(settings.default_player || "builtin_player") !== "system_default";
  }

  function shouldRememberPlaybackPosition(state) {
    return playbackSettings(state).remember_position !== false;
  }

  function shouldAutoplayNext(state) {
    return playbackSettings(state).autoplay_next !== false;
  }

  function shouldManualSwitchImages(state) {
    return playbackSettings(state).manual_image_switch === true;
  }

  function imageAutoAdvanceIntervalMs(state) {
    const seconds = Number(playbackSettings(state).image_auto_advance_interval_seconds || 5);
    return [1, 3, 5, 10].includes(seconds) ? seconds * 1000 : 5000;
  }

  function completedItemById(state, id) {
    const items = state && Array.isArray(state.completed_items) ? state.completed_items : [];
    return items.find(item => String(item.id) === String(id));
  }

  function playbackPositionIdentity(state, id) {
    const item = completedItemById(state, id);
    return String((item && (item.local_path || item.filename || item.id)) || id || "");
  }

  function playbackPositionKey(state, id) {
    return `${PLAYBACK_POSITION_PREFIX}${encodeURIComponent(playbackPositionIdentity(state, id))}`;
  }

  function legacyPlaybackPositionKey(id) {
    return `${PLAYBACK_POSITION_PREFIX}${id}`;
  }

  function removePlaybackPosition(storage, state, id) {
    if (!storage) return;
    try {
      storage.removeItem(playbackPositionKey(state, id));
      storage.removeItem(legacyPlaybackPositionKey(id));
    } catch (_error) {}
  }

  function cleanupPlaybackPositions(storage, state, items) {
    if (!storage) return;
    const validKeys = new Set();
    for (const item of items || []) {
      if (!item || !item.id) continue;
      validKeys.add(playbackPositionKey(state, item.id));
      validKeys.add(legacyPlaybackPositionKey(item.id));
    }
    try {
      for (let index = storage.length - 1; index >= 0; index -= 1) {
        const key = storage.key(index);
        if (key && key.startsWith(PLAYBACK_POSITION_PREFIX) && !validKeys.has(key)) {
          storage.removeItem(key);
        }
      }
    } catch (_error) {}
  }

  function isImageItem(item) {
    const type = String(item && item.content_type || "").toLowerCase();
    const path = String(item && (item.local_path || item.filename || item.title) || "").toLowerCase();
    return type === "image" || /\.(png|jpe?g|gif|webp|bmp|avif)$/.test(path);
  }

  function hasDisplayDuration(value) {
    const text = String(value || "").trim();
    return !!text && text !== "--" && text !== "\u68c0\u6d4b\u4e2d" && text !== "00:00:00";
  }

  function isRealResolution(value) {
    return /^\d{2,5}\s*x\s*\d{2,5}$/i.test(String(value || "").trim());
  }

  function fmtTime(seconds) {
    const value = Number(seconds) || 0;
    const min = Math.floor(value / 60);
    const sec = Math.floor(value % 60);
    return `${String(min).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }

  function fmtClockTime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  window.UcpPlaybackState = {
    prefix: PLAYBACK_POSITION_PREFIX,
    playbackSettings,
    shouldUseBuiltinPlayer,
    shouldRememberPlaybackPosition,
    shouldAutoplayNext,
    shouldManualSwitchImages,
    imageAutoAdvanceIntervalMs,
    completedItemById,
    playbackPositionIdentity,
    playbackPositionKey,
    legacyPlaybackPositionKey,
    removePlaybackPosition,
    cleanupPlaybackPositions,
    isImageItem,
    hasDisplayDuration,
    isRealResolution,
    fmtTime,
    fmtClockTime,
  };
})();
