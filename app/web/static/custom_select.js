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
      if (/PageSize$/.test(select.id || "")) wrapper.classList.add("custom-select-page-size");
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
      if (!("originalLabel" in option.dataset)) option.dataset.originalLabel = option.textContent || "";
      if (!("originalValue" in option.dataset)) {
        option.dataset.originalValue = option.hasAttribute("value")
          ? option.getAttribute("value")
          : option.dataset.originalLabel;
      }
      option.value = option.dataset.originalValue;
      option.textContent = helpers.translate(option.dataset.originalLabel);
    });
    const button = wrapper.querySelector(".custom-select-button");
    const menu = wrapper.querySelector(".custom-select-menu");
    const selected = select.selectedOptions && select.selectedOptions[0] ? select.selectedOptions[0] : select.options[select.selectedIndex];
    const text = selected ? selected.textContent : "";
    const selectedIcon = optionIcon(selected);
    wrapper.classList.toggle("is-disabled", select.disabled);
    wrapper.classList.toggle("has-option-icons", !!selectedIcon || Array.from(select.options).some(option => !!optionIcon(option)));
    if (button) {
      const fallbackLabel = select.getAttribute("aria-label") || select.dataset.setting || "Select";
      button.disabled = select.disabled;
      button.innerHTML = optionContentHtml(selected);
      button.title = text || fallbackLabel;
      button.setAttribute("aria-label", text || fallbackLabel);
      button.setAttribute("aria-expanded", String(!menu?.hidden));
    }
    fitWidthToContent(select, wrapper, button);
    if (menu) renderMenu(select, menu);
  }

  function optionIcon(option) {
    return option && option.dataset ? String(option.dataset.icon || "") : "";
  }

  function optionContentHtml(option) {
    const text = helpers.esc(option ? option.textContent || "" : "");
    const icon = optionIcon(option);
    return `${icon ? `<img class="custom-select-icon" src="${helpers.escAttr(icon)}" alt="" />` : ""}<span class="custom-select-label">${text}</span>`;
  }

  function shouldAutoFit(select, wrapper) {
    if (!select || !wrapper) return false;
    return wrapper.classList.contains("custom-select-count")
      || wrapper.classList.contains("custom-select-page-size");
  }

  function optionTextWidth(select, button) {
    if (!select || !select.ownerDocument || !select.ownerDocument.body) return 0;
    const doc = select.ownerDocument;
    const probe = doc.createElement("span");
    const styleSource = button || select;
    const computed = styleSource ? doc.defaultView.getComputedStyle(styleSource) : null;
    probe.style.cssText = [
      "position:absolute",
      "left:-10000px",
      "top:-10000px",
      "visibility:hidden",
      "white-space:nowrap",
      computed ? `font:${computed.font}` : "",
      computed ? `letter-spacing:${computed.letterSpacing}` : "",
    ].filter(Boolean).join(";");
    doc.body.appendChild(probe);
    let widest = 0;
    Array.from(select.options).forEach(option => {
      probe.textContent = option.textContent || "";
      widest = Math.max(widest, probe.getBoundingClientRect().width);
    });
    probe.remove();
    return widest;
  }

  function fitWidthToContent(select, wrapper, button) {
    if (!shouldAutoFit(select, wrapper)) return;
    const widest = optionTextWidth(select, button);
    if (!widest) return;
    const width = Math.max(108, Math.min(260, Math.ceil(widest + 48)));
    wrapper.style.width = `${width}px`;
    wrapper.style.minWidth = `${width}px`;
    if (wrapper.classList.contains("custom-select-count")) {
      wrapper.style.flexBasis = `${width}px`;
    }
  }

  function renderMenu(select, menu) {
    const current = String(select.value ?? "");
    menu.innerHTML = Array.from(select.options).map(option => {
      const selected = String(option.value) === current;
      return `<button type="button" role="option" class="custom-select-option${selected ? " selected" : ""}" data-value="${helpers.escAttr(option.value)}" aria-selected="${selected ? "true" : "false"}">${optionContentHtml(option)}</button>`;
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
    fitWidthToContent,
  };
}());
