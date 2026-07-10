(function () {
  let dependencies = Object.freeze({});
  const state = {
    selectionItems: [],
    dirCurrentPath: "",
    dirSelectedPath: "",
    dirParentPath: "",
    generation: 0,
    directorySequence: 0,
    focusHandle: null,
    disposed: true,
  };

  function configure(options = {}) {
    dispose();
    dependencies = Object.freeze({ ...options });
    state.selectionItems = [];
    state.dirCurrentPath = "";
    state.dirSelectedPath = "";
    state.dirParentPath = "";
    state.generation += 1;
    state.directorySequence = 0;
    state.disposed = false;
    return window.UcpDialogController;
  }

  function requireDependency(name) {
    const value = dependencies[name];
    if (typeof value !== "function") throw new Error(`UcpDialogController is not configured: ${name}`);
    return value;
  }

  function currentState() {
    return requireDependency("getState")() || {};
  }

  function t(value) {
    return requireDependency("t")(value);
  }

  function esc(value) {
    return requireDependency("esc")(value);
  }

  function escAttr(value) {
    return requireDependency("escAttr")(value);
  }

  function byId(id) {
    return requireDependency("byId")(id);
  }

  function translateText(value) {
    return typeof dependencies.translateText === "function" ? dependencies.translateText(value) : t(value);
  }

  function isCurrentGeneration(generation) {
    return !state.disposed && state.generation === generation;
  }

  function isCurrentDirectoryOperation(generation, sequence) {
    return isCurrentGeneration(generation) && state.directorySequence === sequence;
  }

  function cancelScheduledFocus() {
    const handle = state.focusHandle;
    state.focusHandle = null;
    if (!handle) return;
    if (handle.kind === "frame" && typeof window.cancelAnimationFrame === "function") {
      window.cancelAnimationFrame(handle.id);
      return;
    }
    clearTimeout(handle.id);
  }

  function scheduleModalFocus(element, isVisible) {
    cancelScheduledFocus();
    if (!element) return;
    const generation = state.generation;
    const callback = () => {
      state.focusHandle = null;
      if (!isCurrentGeneration(generation) || (typeof isVisible === "function" && !isVisible())) return;
      element.focus({ preventScroll: true });
    };
    if (typeof window.requestAnimationFrame === "function") {
      state.focusHandle = { kind: "frame", id: window.requestAnimationFrame(callback) };
    } else {
      state.focusHandle = { kind: "timer", id: setTimeout(callback, 0) };
    }
  }

  function patchSetting(group, key, value) {
    return requireDependency("patchSetting")(group, key, value);
  }

  function currentDownloadDirectory() {
    const basic = (currentState().settings_snapshot || {})["基础设置"] || {};
    return String(basic.download_directory || basic.save_directory || "");
  }

  function setDirStatus(message, tone = "") {
    const status = byId("dirStatus");
    if (!status) return;
    status.textContent = translateText(message || "");
    status.dataset.tone = tone || "";
  }

  function setDirBusy(busy) {
    ["dirGoBtn", "dirParentBtn", "dirRefreshBtn", "dirConfirmBtn"].forEach(id => {
      const button = byId(id);
      if (button) button.disabled = !!busy;
    });
  }

  function installDirDialogHandlers() {
    const input = byId("dirInput");
    if (input && !input.dataset.bound) {
      input.dataset.bound = "true";
      input.addEventListener("keydown", event => {
        if (event.key === "Enter") {
          event.preventDefault();
          dirBrowsePath();
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancelDirDialog();
        }
      });
    }
    for (const id of ["dirList", "dirDrivesList"]) {
      const list = byId(id);
      if (!list || list.dataset.bound) continue;
      list.dataset.bound = "true";
      list.addEventListener("click", event => {
        const button = event.target && event.target.closest ? event.target.closest("[data-dir-path]") : null;
        if (!button) return;
        selectDirPath(button.dataset.dirPath || "");
      });
      list.addEventListener("dblclick", event => {
        const button = event.target && event.target.closest ? event.target.closest("[data-dir-path]") : null;
        if (!button) return;
        dirLoadPath(button.dataset.dirPath || "");
      });
    }
  }

  function updateDirStaticText() {
    const textMap = {
      dirTitle: "选择保存目录",
      dirGoBtn: "跳转",
      dirParentBtn: "上一级",
      dirCancelBtn: "取消",
      dirConfirmBtn: "选择此目录",
    };
    for (const [id, label] of Object.entries(textMap)) {
      const element = byId(id);
      if (element) element.textContent = t(label);
    }
    const refresh = byId("dirRefreshBtn");
    if (refresh) {
      refresh.title = t("刷新");
      refresh.setAttribute("aria-label", t("刷新"));
    }
    const input = byId("dirInput");
    if (input) input.placeholder = t("输入目录路径");
  }

  function dirEntryHtml(entry, kind = "folder") {
    const path = String((entry && entry.path) || "");
    const name = String((entry && entry.name) || path || "");
    return `
      <button class="dir-entry" type="button" data-dir-path="${escAttr(path)}" data-dir-kind="${escAttr(kind)}" title="${escAttr(path)}">
        <img src="/ui-icon/action_open_directory.png" alt="" />
        <span>${esc(name)}</span>
      </button>
    `;
  }

  function renderDirEntries(data) {
    const drives = Array.isArray(data.drives) ? data.drives : [];
    const subdirs = Array.isArray(data.subdirs) ? data.subdirs : [];
    const drivesList = byId("dirDrivesList");
    const dirList = byId("dirList");
    if (drivesList) {
      drivesList.innerHTML = drives.length
        ? drives.map(entry => dirEntryHtml(entry, "root")).join("")
        : `<div class="dir-empty">${esc(t("无可用根目录"))}</div>`;
    }
    if (dirList) {
      dirList.innerHTML = subdirs.length
        ? subdirs.map(entry => dirEntryHtml(entry, "folder")).join("")
        : `<div class="dir-empty">${esc(t("没有可进入的子目录"))}</div>`;
    }
  }

  function selectDirPath(path) {
    state.dirSelectedPath = String(path || "");
    const input = byId("dirInput");
    if (input && state.dirSelectedPath) input.value = state.dirSelectedPath;
    document.querySelectorAll(".dir-entry.selected").forEach(item => item.classList.remove("selected"));
    const selectedEntry = state.dirSelectedPath
      ? Array.from(document.querySelectorAll(".dir-entry")).find(item => item.dataset.dirPath === state.dirSelectedPath)
      : null;
    if (selectedEntry) selectedEntry.classList.add("selected");
    if (state.dirSelectedPath) setDirStatus("已选择目录", "ok");
  }

  async function onChangeDirClicked() {
    const generation = state.generation;
    await showDirDialog();
    return isCurrentGeneration(generation);
  }

  async function showDirDialog() {
    const generation = state.generation;
    updateDirStaticText();
    installDirDialogHandlers();
    const modal = byId("dirModal");
    const input = byId("dirInput");
    const startPath = localStorage.getItem("dir_last_browsed") || currentDownloadDirectory();
    if (input) input.value = startPath;
    if (modal) modal.style.display = "flex";
    scheduleModalFocus(input, () => !!modal && modal.style.display === "flex");
    await dirLoadPath(startPath);
    return isCurrentGeneration(generation);
  }

  async function dirLoadPath(path = "") {
    const generation = state.generation;
    const sequence = ++state.directorySequence;
    const target = String(path || (byId("dirInput") && byId("dirInput").value) || "").trim();
    setDirBusy(true);
    setDirStatus("正在加载目录...", "loading");
    try {
      const query = target ? `?path=${encodeURIComponent(target)}` : "";
      const response = await fetch(`/api/dir/list${query}`, { cache: "no-store" });
      if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      const data = await response.json().catch(() => ({}));
      if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      if (!response.ok || data.error || data.status === "error") {
        throw new Error(data.error || data.message || `HTTP ${response.status}`);
      }
      state.dirCurrentPath = String(data.current || target || "");
      state.dirSelectedPath = state.dirCurrentPath;
      state.dirParentPath = String(data.parent || "");
      if (state.dirCurrentPath) localStorage.setItem("dir_last_browsed", state.dirCurrentPath);
      const input = byId("dirInput");
      if (input) input.value = state.dirCurrentPath;
      renderDirEntries(data);
      setDirStatus("单击选择，双击进入子目录", "ok");
      return true;
    } catch (error) {
      if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      renderDirEntries({ drives: [], subdirs: [] });
      setDirStatus(`目录加载失败：${error.message || error}`, "error");
      return false;
    } finally {
      if (isCurrentDirectoryOperation(generation, sequence)) setDirBusy(false);
    }
  }

  function dirBrowsePath() {
    return dirLoadPath((byId("dirInput") && byId("dirInput").value) || "");
  }

  function dirGoParent() {
    if (!state.dirParentPath) {
      setDirStatus("当前目录没有可访问的上一级", "error");
      return Promise.resolve();
    }
    return dirLoadPath(state.dirParentPath);
  }

  function dirRefresh() {
    return dirLoadPath(state.dirCurrentPath || (byId("dirInput") && byId("dirInput").value) || "");
  }

  async function confirmDirDialog() {
    const generation = state.generation;
    const sequence = ++state.directorySequence;
    const directory = String(state.dirSelectedPath || (byId("dirInput") && byId("dirInput").value) || "").trim();
    if (!directory) {
      setDirStatus("目录路径不能为空", "error");
      return;
    }
    setDirBusy(true);
    setDirStatus("正在切换目录...", "loading");
    try {
      const response = await fetch("/api/dir/change", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directory }),
      });
      if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      const data = await response.json().catch(() => ({}));
      if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      if (!response.ok || data.error || data.status === "error") {
        throw new Error(data.error || data.message || `HTTP ${response.status}`);
      }
      if (typeof dependencies.closePreview === "function") dependencies.closePreview();
      const nextDirectory = String(data.directory || directory);
      patchSetting("基础设置", "download_directory", nextDirectory);
      localStorage.setItem("dir_last_browsed", nextDirectory);
      const modal = byId("dirModal");
      if (modal) modal.style.display = "none";
      requireDependency("appendUiLog")(translateText(data.message || "目录已变更"));
      if (typeof dependencies.fetchState === "function") {
        await dependencies.fetchState();
        if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      }
      return true;
    } catch (error) {
      if (!isCurrentDirectoryOperation(generation, sequence)) return false;
      setDirStatus(`切换目录失败：${error.message || error}`, "error");
      return false;
    } finally {
      if (isCurrentDirectoryOperation(generation, sequence)) setDirBusy(false);
    }
  }

  function cancelDirDialog() {
    cancelScheduledFocus();
    state.directorySequence += 1;
    const modal = byId("dirModal");
    if (modal) modal.style.display = "none";
  }

  function fileAssociationLabels() {
    return {
      title: "绑定默认打开方式",
      description: "选择要注册到 Windows 默认应用的资源类型。Windows 可能会要求在系统默认应用页再次确认。",
      video: "视频资源（mp4、mkv、avi、mov、webm 等）",
      image: "图片资源（jpg、png、gif、webp、bmp 等）",
      status: "生效方式：注册成功后会立即影响之后的系统打开行为；若 Windows 拦截，程序会打开默认应用设置页供你确认。",
      cancel: "取消",
      confirm: "绑定",
    };
  }

  function applyFileAssociationLanguage() {
    const labels = fileAssociationLabels();
    const title = byId("associationTitle");
    const description = byId("associationDescription");
    const status = byId("associationStatus");
    const videoLabel = document.querySelector("#fileAssociationModal label[for='associationVideo'] span")
      || document.querySelector("#associationVideo + span");
    const imageLabel = document.querySelector("#fileAssociationModal label[for='associationImage'] span")
      || document.querySelector("#associationImage + span");
    if (title) title.textContent = t(labels.title);
    if (description) description.textContent = t(labels.description);
    if (status) status.textContent = t(labels.status);
    if (videoLabel) videoLabel.textContent = t(labels.video);
    if (imageLabel) imageLabel.textContent = t(labels.image);
    const cancel = byId("associationCancelBtn");
    const confirm = byId("associationConfirmBtn");
    if (cancel) cancel.textContent = t(labels.cancel);
    if (confirm) confirm.textContent = t(labels.confirm);
  }

  function showFileAssociationModal() {
    applyFileAssociationLanguage();
    const modal = byId("fileAssociationModal");
    const video = byId("associationVideo");
    const image = byId("associationImage");
    if (video) video.checked = true;
    if (image) image.checked = true;
    if (modal) modal.style.display = "flex";
    scheduleModalFocus(byId("associationConfirmBtn"), () => {
      const confirm = byId("associationConfirmBtn");
      return !!modal && modal.style.display === "flex" && !!confirm;
    });
  }

  function cancelFileAssociationModal() {
    cancelScheduledFocus();
    const modal = byId("fileAssociationModal");
    if (modal) modal.style.display = "none";
  }

  function confirmFileAssociationModal() {
    cancelScheduledFocus();
    const video = byId("associationVideo");
    const image = byId("associationImage");
    const includeVideo = !!(video && video.checked);
    const includeImage = !!(image && image.checked);
    const modal = byId("fileAssociationModal");
    if (modal) modal.style.display = "none";
    requireDependency("frontendAction")("register_file_associations", { include_video: includeVideo, include_image: includeImage });
  }

  function isFileAssociationModalOpen() {
    const modal = byId("fileAssociationModal");
    return !!modal && modal.style.display === "flex";
  }

  function isTextEntryTarget(target) {
    if (!target || !target.tagName) return false;
    if (target.isContentEditable) return true;
    const tagName = String(target.tagName).toUpperCase();
    if (tagName === "INPUT") {
      const inputType = String(target.type || "text").toLowerCase();
      return !["button", "checkbox", "color", "file", "radio", "range", "reset", "submit"].includes(inputType);
    }
    return ["SELECT", "TEXTAREA"].includes(tagName);
  }

  function handleFileAssociationModalShortcut(event) {
    if (!isFileAssociationModalOpen()) return false;
    if (!["Enter", "Escape"].includes(event.key)) return false;
    if (event.key === "Enter" && isTextEntryTarget(event.target)) return false;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Enter") confirmFileAssociationModal();
    else cancelFileAssociationModal();
    return true;
  }

  function selectionHeaderText(count) {
    return t("共扫描到 {count} 个资源，请勾选需要下载的项目：").replace("{count}", String(count));
  }

  function selectionItemTitle(item, index) {
    if (item && typeof item === "object") return String(item.title || item.name || `项目 ${index + 1}`);
    const text = String(item ?? "").trim();
    return text || `项目 ${index + 1}`;
  }

  function selectionRowHtml(item, index) {
    const rawTitle = selectionItemTitle(item, index);
    return `
      <tr class="selection-row" data-index="${index}" onclick="toggleSelectionItem(${index}, event)">
        <td><input class="selection-checkbox" type="checkbox" data-index="${index}" checked tabindex="-1" aria-checked="true" aria-label="${escAttr(t("选择"))} ${index + 1}" onmousedown="event.preventDefault()" onclick="event.preventDefault();event.stopPropagation();toggleSelectionItem(${index})"></td>
        <td class="selection-title-cell" title="${escAttr(rawTitle)}">${esc(rawTitle)}</td>
      </tr>
    `;
  }

  function syncSelectionRowState(index) {
    const checkbox = document.querySelector(`#selectionBody input[data-index="${index}"]`);
    const row = document.querySelector(`#selectionBody tr[data-index="${index}"]`);
    if (!checkbox || !row) return;
    row.classList.toggle("unchecked", !checkbox.checked);
    checkbox.setAttribute("aria-checked", checkbox.checked ? "true" : "false");
  }

  function toggleSelectionItem(index, event) {
    const checkbox = document.querySelector(`#selectionBody input[data-index="${index}"]`);
    if (!checkbox) return;
    if (event && event.target === checkbox) {
      syncSelectionRowState(index);
      return;
    }
    checkbox.checked = !checkbox.checked;
    syncSelectionRowState(index);
  }

  function selectAllSelectionItems() {
    document.querySelectorAll("#selectionBody input[type='checkbox']").forEach(input => {
      input.checked = true;
      syncSelectionRowState(Number(input.dataset.index));
    });
  }

  function invertSelectionItems() {
    document.querySelectorAll("#selectionBody input[type='checkbox']").forEach(input => {
      input.checked = !input.checked;
      syncSelectionRowState(Number(input.dataset.index));
    });
  }

  function showSelectionModal(items) {
    state.selectionItems = Array.isArray(items) ? items : [];
    byId("selectionTitle").textContent = t("任务清单确认");
    byId("selectionHeader").textContent = selectionHeaderText(state.selectionItems.length);
    const selectionHeadCells = document.querySelectorAll(".selection-table thead th");
    if (selectionHeadCells[0]) selectionHeadCells[0].textContent = t("选择");
    if (selectionHeadCells[1]) selectionHeadCells[1].textContent = t("视频标题 / 描述");
    byId("selectionAllBtn").textContent = t("全选");
    byId("selectionInvertBtn").textContent = t("反选");
    byId("selectionCancelBtn").textContent = t("取消任务");
    byId("selectionConfirmBtn").textContent = t("开始下载");
    byId("selectionBody").innerHTML = state.selectionItems.map(selectionRowHtml).join("");
    const modal = byId("selectionModal");
    modal.style.display = "flex";
    scheduleModalFocus(byId("selectionConfirmBtn"), () => modal.style.display === "flex");
  }

  function confirmSelection() {
    cancelScheduledFocus();
    const indices = [...document.querySelectorAll("#selectionBody input:checked")].map(input => Number(input.dataset.index));
    requireDependency("sendWS")("select_tasks", { indices });
    byId("selectionModal").style.display = "none";
  }

  function cancelSelection() {
    cancelScheduledFocus();
    requireDependency("sendWS")("select_tasks", { indices: null });
    byId("selectionModal").style.display = "none";
  }

  function isSelectionModalOpen() {
    const modal = byId("selectionModal");
    return !!modal && modal.style.display === "flex";
  }

  function handleSelectionModalShortcut(event) {
    if (!isSelectionModalOpen()) return false;
    if (!["Enter", "Escape"].includes(event.key)) return false;
    if (event.key === "Enter" && isTextEntryTarget(event.target)) return false;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Enter") confirmSelection();
    else cancelSelection();
    return true;
  }

  function isDirectoryOpen() {
    const modal = byId("dirModal");
    return !!modal && modal.style.display === "flex";
  }

  function handleShortcut(event) {
    if (state.disposed) return false;
    if (handleSelectionModalShortcut(event)) return true;
    if (handleFileAssociationModalShortcut(event)) return true;
    if (event.key === "Escape" && isDirectoryOpen()) {
      event.preventDefault();
      event.stopPropagation();
      cancelDirDialog();
      return true;
    }
    return false;
  }

  function hideModal(id) {
    const node = typeof dependencies.byId === "function" ? dependencies.byId(id) : document.getElementById(id);
    if (node) node.style.display = "none";
  }

  function dispose() {
    if (state.disposed) return;
    state.disposed = true;
    state.generation += 1;
    state.directorySequence += 1;
    cancelScheduledFocus();
    state.selectionItems = [];
    state.dirCurrentPath = "";
    state.dirSelectedPath = "";
    state.dirParentPath = "";
    hideModal("selectionModal");
    hideModal("fileAssociationModal");
    hideModal("dirModal");
    const selectionBody = typeof dependencies.byId === "function" ? dependencies.byId("selectionBody") : null;
    if (selectionBody) selectionBody.innerHTML = "";
    dependencies = Object.freeze({});
  }

  window.UcpDialogController = Object.freeze({
    configure,
    installDirectoryHandlers: installDirDialogHandlers,
    showDirectory: showDirDialog,
    loadDirectory: dirLoadPath,
    browseDirectory: dirBrowsePath,
    goDirectoryParent: dirGoParent,
    refreshDirectory: dirRefresh,
    confirmDirectory: confirmDirDialog,
    cancelDirectory: cancelDirDialog,
    selectDirectory: selectDirPath,
    showAssociation: showFileAssociationModal,
    applyAssociationLanguage: applyFileAssociationLanguage,
    confirmAssociation: confirmFileAssociationModal,
    cancelAssociation: cancelFileAssociationModal,
    showSelection: showSelectionModal,
    confirmSelection,
    cancelSelection,
    toggleSelection: toggleSelectionItem,
    selectAllSelection: selectAllSelectionItems,
    invertSelection: invertSelectionItems,
    handleShortcut,
    onChangeDirectory: onChangeDirClicked,
    dispose,
  });
})();
