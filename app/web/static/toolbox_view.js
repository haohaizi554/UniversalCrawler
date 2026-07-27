(function () {
  "use strict";

  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }
  function byId(id) { return document.getElementById(id); }
  function text(context, value) { return context.translate ? context.translate(value) : String(value ?? ""); }
  function icon(tool) { return `/ui-icon/${encodeURIComponent(tool.iconFile || "nav_toolbox.png")}`; }
  function cardsSignature(items, selected) { return JSON.stringify([items.map(tool => [tool.id, tool.title, tool.summary, tool.iconFile]), selected]); }
  function detailSignature(tool, modern, context) { return JSON.stringify([tool.id, tool.title, tool.summary, tool.inputExample, tool.outputExample, tool.parameters, modern, context.language]); }
  function controlHtml(parameter, value, context) {
    const name = escapeHtml(parameter.name); const disabled = parameter.readOnly ? " disabled" : ""; const required = parameter.required ? " required" : "";
    if (parameter.type === "select") return `<select data-toolbox-parameter="${name}"${disabled}>${parameter.options.map(option => `<option value="${escapeHtml(option.value)}"${String(option.value) === String(value) ? " selected" : ""}${option.disabled ? " disabled" : ""}>${escapeHtml(text(context, option.label))}</option>`).join("")}</select>`;
    if (parameter.type === "boolean") return `<label class="toolbox-switch-control"><input type="checkbox" data-toolbox-parameter="${name}"${value ? " checked" : ""}${disabled}/><span>${escapeHtml(text(context, value ? "已启用" : "未启用"))}</span></label>`;
    if (parameter.type === "textarea") return `<textarea data-toolbox-parameter="${name}" rows="${parameter.rows || 3}"${disabled}${required}>${escapeHtml(value)}</textarea>`;
    const type = parameter.secret ? "password" : (parameter.type === "integer" || parameter.type === "number" ? "number" : "text");
    return `<input type="${type}" data-toolbox-parameter="${name}" value="${escapeHtml(value)}" placeholder="${escapeHtml(text(context, parameter.placeholder))}"${parameter.min !== undefined ? ` min="${escapeHtml(parameter.min)}"` : ""}${parameter.max !== undefined ? ` max="${escapeHtml(parameter.max)}"` : ""}${parameter.step !== undefined ? ` step="${escapeHtml(parameter.step)}"` : ""}${parameter.pattern ? ` pattern="${escapeHtml(parameter.pattern)}"` : ""}${disabled}${required}/>`;
  }
  function parameterHtml(tool, values, context) { return tool.parameters.map(parameter => `<div class="toolbox-parameter" data-toolbox-field="${escapeHtml(parameter.name)}"><label>${escapeHtml(text(context, parameter.label))}${parameter.required ? " *" : ""}</label>${controlHtml(parameter, values[parameter.name], context)}<small>${escapeHtml(text(context, parameter.description))}</small><span class="toolbox-field-error" data-toolbox-error></span></div>`).join("") || `<p class="toolbox-empty-inline">${escapeHtml(text(context, "暂无参数"))}</p>`; }
  function detailHtml(tool, values, modern, context) {
    return `<div class="toolbox-detail-scroll"><section class="toolbox-section toolbox-overview"><div class="toolbox-section-heading"><h2>${escapeHtml(text(context, "工具详情"))}</h2><span id="toolboxStatusBadge" class="toolbox-status" data-status="idle">${escapeHtml(text(context, "等待操作"))}</span></div><p>${escapeHtml(text(context, tool.summary))}</p><dl><dt>${escapeHtml(text(context, "输入示例"))}</dt><dd>${escapeHtml(text(context, tool.inputExample))}</dd><dt>${escapeHtml(text(context, "输出示例"))}</dt><dd>${escapeHtml(text(context, tool.outputExample))}</dd></dl></section><section class="toolbox-section toolbox-parameters"${modern ? "" : " hidden"}><h2>${escapeHtml(text(context, "工具参数"))}</h2><div class="toolbox-parameter-list">${parameterHtml(tool, values, context)}</div><p id="toolboxValidationMessage" class="toolbox-validation-message" aria-live="polite"></p></section><section class="toolbox-section toolbox-execution"${modern ? "" : " hidden"}><div class="toolbox-section-heading"><h2>${escapeHtml(text(context, "执行状态"))}</h2><strong id="toolboxExecutionStatus">${escapeHtml(text(context, "等待操作"))}</strong></div><div id="toolboxProgress" class="toolbox-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div><div class="toolbox-progress-meta"><span>${escapeHtml(text(context, "执行进度"))}</span><strong id="toolboxProgressValue">0%</strong></div><p id="toolboxExecutionMessage" class="toolbox-execution-message"></p></section><div class="toolbox-actions"><button id="toolboxValidateButton" class="btn" type="button">${escapeHtml(text(context, "验证参数"))}</button><button id="toolboxStartButton" class="btn btn-primary" type="button">${escapeHtml(text(context, "启动工具"))}</button><button id="toolboxCancelButton" class="btn btn-danger" type="button">${escapeHtml(text(context, "取消运行"))}</button></div><section class="toolbox-section toolbox-result"${modern ? "" : " hidden"}><div class="toolbox-section-heading"><h2>${escapeHtml(text(context, "执行结果"))}</h2><button id="toolboxOpenResultButton" class="icon-btn" type="button" disabled>${escapeHtml(text(context, "打开结果"))}</button></div><pre id="toolboxResultValue" class="toolbox-result-value">${escapeHtml(text(context, "暂无执行结果"))}</pre></section><section class="toolbox-section toolbox-history"><div class="toolbox-section-heading"><h2>${escapeHtml(text(context, "使用历史"))}</h2><button id="toolboxClearHistoryButton" class="icon-btn" type="button"${modern ? "" : " hidden"}>${escapeHtml(text(context, "清空历史"))}</button></div><ol id="toolboxHistoryList" class="toolbox-history-list"></ol></section></div>`;
  }
  function renderEmpty(context) {
    const root = byId("toolDetail"); if (!root) return false;
    root.dataset.signature = ""; root.innerHTML = `<div class="empty-note toolbox-empty">${escapeHtml(text(context, "请选择工具"))}</div>`;
    return true;
  }
  function renderCards(items, selected, context) {
    const root = byId("toolGrid"); if (!root) return ""; const signature = cardsSignature(items, selected);
    if (root.dataset.signature !== signature) {
      root.dataset.signature = signature;
      root.innerHTML = items.map(tool => `<button class="tool-card${tool.id === selected ? " is-active" : ""}" type="button" data-toolbox-id="${escapeHtml(tool.id)}"><img src="${icon(tool)}" alt=""/><span><strong>${escapeHtml(text(context, tool.title))}</strong><small>${escapeHtml(text(context, tool.summary))}</small></span></button>`).join("");
      root.querySelectorAll("[data-toolbox-id]").forEach(button => button.addEventListener("click", () => context.select(button.dataset.toolboxId)));
    }
    return signature;
  }
  function renderDetail(tool, values, modern, context) {
    const root = byId("toolDetail"); if (!root) return ""; const signature = detailSignature(tool, modern, context);
    if (root.dataset.signature !== signature) {
      root.dataset.signature = signature; root.innerHTML = detailHtml(tool, values, modern, context);
      root.querySelectorAll("[data-toolbox-parameter]").forEach(control => control.addEventListener("change", event => context.updateParameter(control.dataset.toolboxParameter, control.type === "checkbox" ? control.checked : event.target.value)));
      [["toolboxValidateButton", context.validate], ["toolboxStartButton", context.start], ["toolboxCancelButton", context.cancel], ["toolboxOpenResultButton", context.openResult], ["toolboxClearHistoryButton", context.clearHistory]].forEach(([id, callback]) => { const button = byId(id); if (button) button.addEventListener("click", () => callback()); });
      if (context.enhanceSelects) context.enhanceSelects(root);
    }
    return signature;
  }
  function patchDetail(model, context) {
    const root = byId("toolDetail"); if (!root) return;
    const execution = model.execution; const pending = !!model.pending; const status = execution.statusText || execution.status || "等待操作";
    const badge = byId("toolboxStatusBadge"); if (badge) { badge.dataset.status = execution.status; badge.textContent = text(context, status); }
    const label = byId("toolboxExecutionStatus"); if (label) label.textContent = text(context, status);
    const progress = byId("toolboxProgress"); if (progress) { progress.setAttribute("aria-valuenow", String(execution.progress)); progress.classList.toggle("is-indeterminate", execution.progressIndeterminate); const bar = progress.querySelector("i"); if (bar) bar.style.width = `${execution.progress}%`; }
    const progressValue = byId("toolboxProgressValue"); if (progressValue) progressValue.textContent = text(context, execution.progressText || `${execution.progress}%`);
    const message = byId("toolboxExecutionMessage"); if (message) { message.dataset.state = model.actionMessage || execution.error ? "error" : "normal"; message.textContent = text(context, model.actionMessage || execution.error || execution.message || ""); }
    const result = byId("toolboxResultValue"); if (result) result.textContent = text(context, model.resultText || "暂无执行结果");
    const validation = byId("toolboxValidationMessage"); if (validation) validation.textContent = text(context, model.validationText || "");
    root.querySelectorAll("[data-toolbox-field]").forEach(field => { const error = model.errors[field.dataset.toolboxField] || ""; field.classList.toggle("is-invalid", !!error); const errorNode = field.querySelector("[data-toolbox-error]"); if (errorNode) errorNode.textContent = text(context, error); });
    const buttons = { toolboxValidateButton: model.validateEnabled, toolboxStartButton: model.startEnabled, toolboxCancelButton: model.cancelEnabled, toolboxOpenResultButton: model.openEnabled, toolboxClearHistoryButton: model.clearEnabled };
    Object.entries(buttons).forEach(([id, enabled]) => { const button = byId(id); if (button) button.disabled = !enabled || pending; });
    const list = byId("toolboxHistoryList"); if (list) { const signature = JSON.stringify(model.history); if (list.dataset.signature !== signature) { list.dataset.signature = signature; list.innerHTML = model.history.length ? model.history.map(row => `<li class="toolbox-history-row"><span>${escapeHtml(text(context, row.title))}</span><span>${escapeHtml(text(context, row.statusText || row.status))}</span></li>`).join("") : `<li class="toolbox-empty-inline">${escapeHtml(text(context, "暂无使用历史"))}</li>`; } }
  }

  window.UcpToolboxView = Object.freeze({ renderCards, renderEmpty, renderDetail, patchDetail });
})();
