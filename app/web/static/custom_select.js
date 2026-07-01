(function () {
  let openCustomSelect = null;
  let helpers = {
    translate: value => String(value ?? ""),
    esc: value => String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char] || char)),
    escAttr: value => String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char] || char)),
  };

  function configure(nextHelpers = {}) {
    helpers = {
      ...helpers,
      ...(typeof nextHelpers.translate === "function" ? { translate: nextHelpers.translate } : {}),
      ...(typeof nextHelpers.esc === "function" ? { esc: nextHelpers.esc } : {}),
      ...(typeof nextHelpers.escAttr === "function" ? { escAttr: nextHelpers.escAttr } : {}),
    };
  }

  function enhance(root = document) {
    const scope = root || document;
    scope.querySelectorAll("select").forEach(select => {
      if (select.closest(".custom-select")) {
        syncForSelect(select);
        return;
      }
      const wrapper = document.createElement("span");
      wrapper.className = "custom-select";
      if (select.classList.contains("source-select")) wrapper.classList.add("custom-select-source");
      if (select.classList.contains("count-select")) wrapper.classList.add("custom-select-count");
      for (const className of ["platform-auth", "platform-count", "platform-proxy"]) {
        if (select.classList.contains(className)) wrapper.classList.add(className);
      }
      select.parentNode.insertBefore(wrapper, select);
      wrapper.appendChild(select);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "custom-select-button";
      button.setAttribute("aria-haspopup", "listbox");
      button.setAttribute("aria-expanded", "false");
      wrapper.appendChild(button);

      const menu = document.createElement("div");
      menu.className = "custom-select-menu";
      menu.setAttribute("role", "listbox");
      menu.hidden = true;
      wrapper.appendChild(menu);

      button.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        toggle(wrapper);
      });
      button.addEventListener("keydown", event => handleKeydown(event, wrapper));
      select.addEventListener("change", () => syncForSelect(select));
      syncForSelect(select);
    });
  }

  function syncAll(root = document) {
    (root || document).querySelectorAll(".custom-select > select").forEach(syncForSelect);
  }

  function syncForSelect(select) {
    const wrapper = select && select.closest(".custom-select");
    if (!wrapper) return;
    wrapper.style.setProperty("--option-count", String(Math.max(1, select.options.length)));
    Array.from(select.options).forEach(option => {
      if (!option.dataset.originalLabel) option.dataset.originalLabel = option.textContent || "";
      option.textContent = helpers.translate(option.dataset.originalLabel);
    });
    const button = wrapper.querySelector(".custom-select-button");
    const menu = wrapper.querySelector(".custom-select-menu");
    const selected = select.selectedOptions && select.selectedOptions[0] ? select.selectedOptions[0] : select.options[select.selectedIndex];
    const text = selected ? selected.textContent : "";
    wrapper.classList.toggle("is-disabled", select.disabled);
    if (button) {
      const fallbackLabel = select.getAttribute("aria-label") || select.dataset.setting || "Select";
      button.disabled = select.disabled;
      button.textContent = text;
      button.title = text || fallbackLabel;
      button.setAttribute("aria-label", text || fallbackLabel);
      button.setAttribute("aria-expanded", String(!menu?.hidden));
    }
    if (menu) renderMenu(select, menu);
  }

  function renderMenu(select, menu) {
    const current = String(select.value ?? "");
    menu.innerHTML = Array.from(select.options).map(option => {
      const selected = String(option.value) === current;
      return `<button type="button" role="option" class="custom-select-option${selected ? " selected" : ""}" data-value="${helpers.escAttr(option.value)}" aria-selected="${selected ? "true" : "false"}">${helpers.esc(option.textContent || "")}</button>`;
    }).join("");
    menu.querySelectorAll(".custom-select-option").forEach(optionButton => {
      optionButton.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        choose(select, optionButton.dataset.value || "");
      });
    });
  }

  function toggle(wrapper) {
    const select = wrapper.querySelector("select");
    if (!select || select.disabled) return;
    if (openCustomSelect === wrapper) {
      close(wrapper, true);
      return;
    }
    close();
    const menu = wrapper.querySelector(".custom-select-menu");
    const button = wrapper.querySelector(".custom-select-button");
    renderMenu(select, menu);
    wrapper.classList.add("open");
    if (menu) menu.hidden = false;
    if (button) button.setAttribute("aria-expanded", "true");
    openCustomSelect = wrapper;
  }

  function close(wrapper = openCustomSelect, focusButton = false) {
    if (!wrapper) return;
    const menu = wrapper.querySelector(".custom-select-menu");
    const button = wrapper.querySelector(".custom-select-button");
    wrapper.classList.remove("open");
    if (menu) menu.hidden = true;
    if (button) {
      button.setAttribute("aria-expanded", "false");
      if (focusButton) button.focus();
    }
    if (openCustomSelect === wrapper) openCustomSelect = null;
  }

  function choose(select, value) {
    if (!select || select.disabled) return;
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    syncForSelect(select);
    close(select.closest(".custom-select"), true);
  }

  function handleKeydown(event, wrapper) {
    const select = wrapper.querySelector("select");
    if (!select || select.disabled) return;
    const options = Array.from(select.options);
    const currentIndex = Math.max(0, select.selectedIndex);
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle(wrapper);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(wrapper, true);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const next = Math.max(0, Math.min(options.length - 1, currentIndex + delta));
      if (options[next]) choose(select, options[next].value);
    }
  }

  document.addEventListener("click", event => {
    if (openCustomSelect && !openCustomSelect.contains(event.target)) close();
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") close();
  });

  window.UcpCustomSelect = {
    configure,
    enhance,
    syncAll,
    syncForSelect,
    renderMenu,
    toggle,
    close,
    choose,
    handleKeydown,
  };
}());
