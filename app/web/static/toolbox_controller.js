(function () {
  "use strict";

  const ACTION_NAMES = Object.freeze({
    validate: "tool_validate",
    start: "tool_start",
    cancel: "tool_cancel",
    openResult: "tool_open_result",
    clearHistory: "tool_clear_history",
  });
  const ACTION_KEY_ALIASES = Object.freeze({
    validate: ["validate", "tool_validate"],
    start: ["start", "run", "tool_start"],
    cancel: ["cancel", "tool_cancel"],
    openResult: ["openResult", "open_result", "tool_open_result"],
    clearHistory: ["clearHistory", "clear_history", "tool_clear_history"],
  });
  const BUSY_STATUSES = new Set(["validating", "starting", "queued", "running", "cancelling"]);
  const DISPLAY_PROJECTION_KEYS = Object.freeze([
    "toolbox_display_projection",
    "toolbox_projection",
    "toolbox_display",
  ]);
  const DISPLAY_BATCH_KEYS = Object.freeze([
    "toolbox_display_batch",
    "toolbox_projection_batch",
    "toolbox_batch",
  ]);
  const STATUS_ALIASES = Object.freeze({
    idle: "idle",
    pending: "queued",
    queued: "queued",
    validating: "validating",
    validated: "ready",
    valid: "ready",
    ready: "ready",
    starting: "starting",
    started: "running",
    running: "running",
    processing: "running",
    cancelling: "cancelling",
    canceled: "cancelled",
    cancelled: "cancelled",
    success: "completed",
    succeeded: "completed",
    complete: "completed",
    completed: "completed",
    error: "failed",
    failed: "failed",
  });
  const STATUS_LABELS = Object.freeze({
    idle: "待执行",
    queued: "等待执行",
    validating: "验证中",
    ready: "准备就绪",
    starting: "启动中",
    running: "执行中",
    cancelling: "取消中",
    cancelled: "已取消",
    completed: "执行成功",
    failed: "执行失败",
  });

  let dependencies = Object.freeze({});
  const state = {
    configured: false,
    disposed: true,
    generation: 0,
    actionSequence: 0,
    valuesByTool: Object.create(null),
    errorsByTool: Object.create(null),
    touchedTools: new Set(),
    dirtyTools: new Set(),
    projectionCache: Object.create(null),
    cardsSignature: "",
    detailSignature: "",
    detailToolId: "",
    pending: null,
    actionMessage: "",
    pagehideHandler: null,
  };

  function asRecord(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function hasOwn(value, key) {
    return Object.prototype.hasOwnProperty.call(asRecord(value), key);
  }

  function firstDefined(...values) {
    return values.find(value => value !== undefined && value !== null);
  }

  function normalizeOption(option) {
    if (option && typeof option === "object") {
      const value = firstDefined(option.value, option.id, option.key, option.name, "");
      return {
        value,
        label: String(firstDefined(option.label, option.title, option.name, value, "")),
        disabled: !!option.disabled,
      };
    }
    return { value: option, label: String(option ?? ""), disabled: false };
  }

  function normalizeOptions(raw) {
    if (Array.isArray(raw)) return raw.map(normalizeOption);
    if (raw && typeof raw === "object") {
      return Object.entries(raw).map(([value, label]) => normalizeOption({ value, label }));
    }
    return [];
  }

  function parameterRows(rawTool) {
    for (const candidate of [rawTool.parameters, rawTool.params, rawTool.fields]) {
      if (Array.isArray(candidate)) return candidate;
      if (candidate && typeof candidate === "object") {
        return Object.entries(candidate).map(([name, value]) => ({ ...asRecord(value), name }));
      }
    }
    const schema = asRecord(rawTool.parameter_schema || rawTool.input_schema || rawTool.schema);
    const properties = asRecord(schema.properties);
    const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : []);
    return Object.entries(properties).map(([name, value]) => ({
      ...asRecord(value),
      name,
      required: required.has(name) || !!asRecord(value).required,
    }));
  }

  function normalizeParameter(rawParameter, index) {
    const raw = asRecord(rawParameter);
    const name = String(firstDefined(raw.name, raw.key, raw.id, `parameter_${index + 1}`));
    const options = normalizeOptions(firstDefined(raw.options, raw.choices, raw.enum));
    const requestedType = String(firstDefined(raw.control, raw.widget, raw.type, "text")).toLowerCase();
    let type = requestedType;
    if (options.length) type = "select";
    else if (["bool", "boolean", "checkbox", "switch"].includes(type)) type = "boolean";
    else if (["choice", "select", "enum"].includes(type)) type = "select";
    else if (["int", "integer", "spin"].includes(type)) type = "integer";
    else if (["float", "double", "decimal", "number"].includes(type)) type = "number";
    else if (["textarea", "multiline", "text_area", "code"].includes(type)) type = "textarea";
    else type = "text";
    return {
      name,
      label: String(firstDefined(raw.label, raw.title, raw.display_name, name)),
      description: String(firstDefined(raw.description, raw.help_text, raw.help, raw.hint, "")),
      placeholder: String(firstDefined(raw.placeholder, "")),
      type,
      required: !!raw.required,
      readOnly: raw.enabled === false || !!firstDefined(raw.read_only, raw.readonly, raw.disabled, false),
      secret: !!raw.secret || ["password", "secret"].includes(requestedType),
      defaultValue: firstDefined(raw.default, raw.default_value, raw.value, type === "boolean" ? false : ""),
      min: firstDefined(raw.min, raw.minimum),
      max: firstDefined(raw.max, raw.maximum),
      step: firstDefined(raw.step, type === "integer" ? 1 : undefined),
      pattern: String(firstDefined(raw.pattern, "")),
      rows: Math.max(2, Math.min(8, Number(raw.rows) || 3)),
      options,
    };
  }

  function normalizeToolDefinition(rawTool) {
    const raw = asRecord(rawTool);
    return {
      ...raw,
      id: String(firstDefined(raw.id, raw.tool_id, raw.key, "")),
      title: String(firstDefined(raw.title, raw.label, raw.name, "")),
      summary: String(firstDefined(raw.summary, raw.description, "")),
      inputExample: String(firstDefined(raw.input_example, raw.inputExample, "")),
      outputExample: String(firstDefined(raw.output_example, raw.outputExample, "")),
      iconFile: String(firstDefined(raw.icon_file, raw.iconFile, "nav_toolbox.png")),
      parameters: parameterRows(raw).map(normalizeParameter),
      actions: asRecord(raw.actions),
      raw,
    };
  }

  function mergeProjection(base, incoming) {
    const merged = { ...asRecord(base), ...asRecord(incoming) };
    for (const key of ["form", "validation", "actions", "action_payloads"]) {
      if (asRecord(base)[key] && asRecord(incoming)[key]) {
        merged[key] = { ...asRecord(asRecord(base)[key]), ...asRecord(asRecord(incoming)[key]) };
      }
    }
    return merged;
  }

  function batchProjections(batch) {
    const source = asRecord(batch);
    const rows = [];
    for (const candidate of [source.projections, source.updates]) {
      if (Array.isArray(candidate)) rows.push(...candidate.filter(row => row && typeof row === "object"));
    }
    if (source.projection && typeof source.projection === "object") rows.push(source.projection);
    if (!rows.length && (source.tool_id || source.id)) rows.push(source);
    return rows;
  }

  function reduceProjectionCache(previous, snapshot) {
    const source = asRecord(snapshot);
    const cache = Object.fromEntries(
      Object.entries(asRecord(previous)).map(([toolId, projection]) => [toolId, mergeProjection({}, projection)]),
    );
    const apply = candidate => {
      const projection = asRecord(candidate);
      const fallbackId = String(firstDefined(source.toolbox_selected_tool_id, ""));
      const toolId = String(firstDefined(projection.tool_id, projection.id, projection.selected_tool_id, fallbackId, ""));
      if (!toolId) return "";
      cache[toolId] = mergeProjection(cache[toolId], projection);
      cache[toolId].tool_id = toolId;
      return toolId;
    };
    for (const key of DISPLAY_PROJECTION_KEYS) {
      if (source[key] && typeof source[key] === "object" && !Array.isArray(source[key])) apply(source[key]);
    }
    for (const key of DISPLAY_BATCH_KEYS) {
      const rawBatch = source[key];
      const batch = asRecord(rawBatch);
      const candidates = Array.isArray(rawBatch) ? rawBatch : batchProjections(batch);
      const touchedIds = candidates.map(apply).filter(Boolean);
      const historyTarget = String(firstDefined(
        batch.selected_tool_id,
        touchedIds[0],
        source.toolbox_selected_tool_id,
        Object.keys(cache).length === 1 ? Object.keys(cache)[0] : "",
      ));
      if (historyTarget && Array.isArray(batch.history)) {
        cache[historyTarget] = mergeProjection(cache[historyTarget], { tool_id: historyTarget, history: batch.history });
      }
    }
    return cache;
  }

  function projectionFor(snapshot, toolId) {
    const cache = reduceProjectionCache({}, snapshot);
    if (toolId && cache[String(toolId)]) return cache[String(toolId)];
    const keys = Object.keys(cache);
    return keys.length === 1 ? cache[keys[0]] : {};
  }

  function projectionFields(projection) {
    const source = asRecord(projection);
    const form = asRecord(source.form);
    for (const candidate of [form.fields, source.parameter_fields, source.parameters]) {
      if (Array.isArray(candidate)) return candidate;
      if (candidate && typeof candidate === "object") {
        return Object.entries(candidate).map(([name, value]) => ({ ...asRecord(value), name }));
      }
    }
    return [];
  }

  function projectionValues(projection) {
    const source = asRecord(projection);
    const form = asRecord(source.form);
    return {
      ...asRecord(source.parameter_values),
      ...asRecord(source.values),
      ...asRecord(form.values),
    };
  }

  function toolForSnapshot(snapshot, toolId, rawOverride = null) {
    const source = asRecord(snapshot);
    const rows = Array.isArray(source.toolbox_items) ? source.toolbox_items : asRecord(source.toolbox).items;
    const rawTool = rawOverride || (Array.isArray(rows)
      ? rows.find(row => String(firstDefined(asRecord(row).id, asRecord(row).tool_id, "")) === String(toolId || ""))
      : null) || { id: toolId };
    const tool = normalizeToolDefinition(rawTool);
    const projection = projectionFor(source, tool.id || toolId);
    const fields = projectionFields(projection);
    if (fields.length) tool.parameters = fields.map(normalizeParameter);
    tool.initialValues = projectionValues(projection);
    tool.actions = { ...tool.actions, ...asRecord(projection.actions) };
    tool.projection = projection;
    return tool;
  }

  function isBlank(value) {
    return value === undefined || value === null || (typeof value === "string" && !value.trim());
  }

  function normalizedParameterValue(parameter, rawValue) {
    if (parameter.type === "boolean") {
      if (typeof rawValue === "string") return ["true", "1", "yes", "on"].includes(rawValue.toLowerCase());
      return !!rawValue;
    }
    if (parameter.type === "integer" || parameter.type === "number") {
      if (isBlank(rawValue)) return null;
      const value = Number(rawValue);
      return parameter.type === "integer" ? Math.trunc(value) : value;
    }
    return rawValue === undefined || rawValue === null ? "" : String(rawValue);
  }

  function validateParameters(tool, rawValues) {
    const values = {};
    const errors = {};
    const source = asRecord(rawValues);
    for (const parameter of tool.parameters || []) {
      const rawValue = hasOwn(source, parameter.name) ? source[parameter.name] : parameter.defaultValue;
      if (parameter.required && isBlank(rawValue)) {
        errors[parameter.name] = "必填项";
        continue;
      }
      if (isBlank(rawValue) && parameter.type !== "boolean") continue;

      const value = normalizedParameterValue(parameter, rawValue);
      if (["integer", "number"].includes(parameter.type)) {
        if (value === null || !Number.isFinite(value)) {
          errors[parameter.name] = "请输入有效数字";
          continue;
        }
        if (parameter.min !== undefined && Number.isFinite(Number(parameter.min)) && value < Number(parameter.min)) {
          errors[parameter.name] = "数值低于允许范围";
          continue;
        }
        if (parameter.max !== undefined && Number.isFinite(Number(parameter.max)) && value > Number(parameter.max)) {
          errors[parameter.name] = "数值超过允许范围";
          continue;
        }
      }
      if (parameter.type === "select" && parameter.options.length) {
        const allowed = parameter.options.map(option => String(option.value));
        if (!allowed.includes(String(value))) {
          errors[parameter.name] = "请选择有效选项";
          continue;
        }
      }
      if (parameter.pattern && !isBlank(value)) {
        try {
          if (!new RegExp(parameter.pattern).test(String(value))) {
            errors[parameter.name] = "输入格式不正确";
            continue;
          }
        } catch (_error) {
          // Invalid server-side patterns remain a server validation responsibility.
        }
      }
      values[parameter.name] = value;
    }
    return { valid: Object.keys(errors).length === 0, errors, values };
  }

  function actionFromMap(actions, kind) {
    const source = asRecord(actions);
    for (const key of ACTION_KEY_ALIASES[kind] || [kind]) {
      if (typeof source[key] === "string" && source[key].trim()) return source[key].trim();
    }
    return "";
  }

  function hasModernContract(tool, snapshot) {
    if ((tool.parameters || []).length) return true;
    const raw = asRecord(tool.raw);
    if (["parameters", "params", "fields", "parameter_schema", "input_schema", "actions"].some(key => hasOwn(raw, key))) {
      return true;
    }
    const source = asRecord(snapshot);
    return [
      "toolbox_contract",
      "toolbox_execution",
      "toolbox_run_state",
      "toolbox_runtime",
      "toolbox_state",
      "toolbox_history",
      ...DISPLAY_PROJECTION_KEYS,
      ...DISPLAY_BATCH_KEYS,
    ].some(key => hasOwn(source, key));
  }

  function resolveActionName(kind, tool, snapshot) {
    const itemAction = actionFromMap(tool.actions, kind);
    if (itemAction) return itemAction;
    const contractAction = actionFromMap(asRecord(asRecord(snapshot).toolbox_contract).actions, kind);
    if (contractAction) return contractAction;
    if (kind === "start" && !hasModernContract(tool, snapshot)) return "run_tool";
    return ACTION_NAMES[kind] || "";
  }

  function buildActionPayload(kind, tool, values, context = {}) {
    const actionName = ACTION_NAMES[kind] || "";
    const contextActions = asRecord(context.actions);
    const actionDescriptor = asRecord(contextActions[actionName]);
    const payload = {
      ...asRecord(asRecord(context.actionPayloads)[actionName]),
      ...asRecord(asRecord(context.action_payloads)[actionName]),
      ...asRecord(actionDescriptor.payload),
      tool_id: String(tool.id || ""),
    };
    if (kind === "validate" || kind === "start") payload.parameters = { ...asRecord(values) };
    if (kind === "cancel" && context.runId && !payload.run_id) payload.run_id = String(context.runId);
    if (kind === "openResult") {
      if (context.resultId && !payload.result_id) payload.result_id = String(context.resultId);
      if (context.historyId && !payload.history_id) payload.history_id = String(context.historyId);
      if (!payload.result_id && !payload.history_id && context.resultPath && !payload.result_path) {
        payload.result_path = String(context.resultPath);
      }
    }
    return payload;
  }

  function actionEnabled(projection, action, fallback = false) {
    const source = asRecord(projection);
    const actions = source.actions;
    if (actions && typeof actions === "object" && !Array.isArray(actions) && hasOwn(actions, action)) {
      const value = actions[action];
      return value && typeof value === "object" ? value.enabled !== false : !!value;
    }
    if (Array.isArray(actions)) return actions.map(String).includes(action);
    const shortName = String(action || "").replace(/^tool_/, "");
    for (const key of [`can_${shortName}`, `${shortName}_enabled`]) {
      if (hasOwn(source, key)) return !!source[key];
    }
    return !!fallback;
  }

  function displayScalar(value) {
    if (value === undefined || value === null) return "";
    if (["string", "number", "boolean"].includes(typeof value)) return String(value);
    const source = asRecord(value);
    const nested = firstDefined(source.display_text, source.text, "");
    return ["string", "number", "boolean"].includes(typeof nested) ? String(nested) : "";
  }

  function resultDisplayLines(result) {
    if (!result || typeof result !== "object") {
      const scalar = displayScalar(result);
      return scalar ? [scalar] : [];
    }
    const source = asRecord(result);
    const lines = [];
    const append = value => {
      const text = displayScalar(value);
      if (text && !lines.includes(text)) lines.push(text);
    };
    append(source.display_text);
    append(source.summary);
    const rows = Array.isArray(source.rows) ? source.rows : (Array.isArray(source.detail_rows) ? source.detail_rows : []);
    for (const entry of rows) {
      const row = asRecord(entry);
      const label = displayScalar(firstDefined(row.label, row.title, ""));
      const value = displayScalar(firstDefined(row.value, row.display_value, ""));
      if (label && value) append(`${label}: ${value}`);
      else append(firstDefined(row.display_text, entry));
    }
    if (!lines.length) append(firstDefined(source.result_path, source.output_path, source.path, source.url, ""));
    return lines;
  }

  function normalizeStatus(value) {
    const status = String(value || "idle").trim().toLowerCase().replace(/[\s-]+/g, "_");
    return STATUS_ALIASES[status] || status || "idle";
  }

  function normalizeProgress(source) {
    const rawRatio = firstDefined(source.progress_ratio, source.ratio);
    const raw = firstDefined(source.progress_percent, source.percent, rawRatio, source.progress, 0);
    const parsed = Number.parseFloat(String(raw).replace("%", ""));
    if (!Number.isFinite(parsed)) return 0;
    const value = rawRatio !== undefined && rawRatio !== null && parsed >= 0 && parsed <= 1 ? parsed * 100 : parsed;
    return Math.max(0, Math.min(100, Math.round(value * 10) / 10));
  }

  function candidateForTool(candidate, toolId) {
    if (Array.isArray(candidate)) {
      return candidate.find(row => String(asRecord(row).tool_id || asRecord(row).id || "") === toolId) || {};
    }
    const source = asRecord(candidate);
    if (!Object.keys(source).length) return {};
    for (const nested of [source.by_tool, source.tools, source.executions]) {
      const record = asRecord(nested);
      if (record[toolId] && typeof record[toolId] === "object") return asRecord(record[toolId]);
    }
    if (source[toolId] && typeof source[toolId] === "object") return asRecord(source[toolId]);
    for (const nested of [source.current, source.active, source.execution, source.current_run, source.active_run]) {
      const row = asRecord(nested);
      const nestedToolId = String(firstDefined(row.tool_id, row.tool, row.id, ""));
      if (Object.keys(row).length && (!nestedToolId || nestedToolId === toolId)) return row;
    }
    const candidateToolId = String(firstDefined(source.tool_id, source.tool, ""));
    if (!candidateToolId || candidateToolId === toolId) return source;
    return {};
  }

  function normalizeValidationErrors(value) {
    if (Array.isArray(value)) {
      return Object.fromEntries(value.map((entry, index) => {
        const row = asRecord(entry);
        return [String(firstDefined(row.name, row.field, row.key, index)), String(firstDefined(row.message, row.error, entry, ""))];
      }));
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([key, message]) => [key, String(message ?? "")]));
    }
    return {};
  }

  function resultPathFrom(source, result) {
    const resultRecord = asRecord(result);
    return String(firstDefined(
      source.result_path,
      source.output_path,
      source.path,
      resultRecord.result_path,
      resultRecord.output_path,
      resultRecord.path,
      resultRecord.url,
      "",
    ));
  }

  function executionFor(snapshot, toolId) {
    const source = asRecord(snapshot);
    const nested = asRecord(source.toolbox);
    const displayProjection = projectionFor(source, toolId);
    const toolRow = (Array.isArray(source.toolbox_items) ? source.toolbox_items : [])
      .find(row => String(asRecord(row).id || asRecord(row).tool_id || "") === String(toolId || ""));
    let execution = {};
    for (const candidate of [
      displayProjection,
      source.toolbox_execution,
      source.toolbox_run_state,
      source.toolbox_runtime,
      source.toolbox_state,
      source.toolbox_active_run,
      nested.execution,
      nested.runtime,
      nested.state,
      asRecord(toolRow).execution,
      asRecord(toolRow).runtime,
    ]) {
      execution = candidateForTool(candidate, String(toolId || ""));
      if (Object.keys(execution).length) break;
    }
    const result = firstDefined(execution.result, execution.output, execution.data, null);
    const status = normalizeStatus(firstDefined(execution.status, execution.state, execution.phase, "idle"));
    const resultPath = resultPathFrom(execution, result);
    const progressProjection = asRecord(execution.progress);
    const progressSource = Object.keys(progressProjection).length
      ? {
          progress_percent: firstDefined(progressProjection.value, progressProjection.percent, 0),
          progress_ratio: progressProjection.ratio,
        }
      : execution;
    const validation = asRecord(execution.validation);
    const fallbackCanCancel = ["queued", "starting", "running"].includes(status);
    const fallbackCanOpen = !!firstDefined(execution.can_open_result, execution.has_result, resultPath, result);
    return {
      toolId: String(firstDefined(execution.tool_id, execution.tool, toolId, "")),
      runId: String(firstDefined(execution.run_id, execution.execution_id, execution.job_id, "")),
      status,
      statusText: String(firstDefined(execution.status_text, "")),
      progress: normalizeProgress(progressSource),
      progressText: String(firstDefined(progressProjection.text, progressProjection.label, execution.progress_text, "")),
      progressIndeterminate: !!firstDefined(progressProjection.indeterminate, execution.progress_indeterminate, false),
      message: String(firstDefined(execution.message, execution.detail, "")),
      error: String(firstDefined(execution.error, execution.error_message, "")),
      result,
      resultPath,
      resultId: String(firstDefined(execution.result_id, asRecord(result).id, "")),
      validationErrors: normalizeValidationErrors(firstDefined(
        execution.validation_errors,
        execution.errors,
        validation.errors,
        {},
      )),
      validationState: String(firstDefined(validation.state, "")),
      validationMessage: String(firstDefined(validation.message, execution.validation_message, "")),
      actions: asRecord(execution.actions),
      actionPayloads: asRecord(execution.action_payloads),
      parameters: projectionValues(execution),
      canCancel: actionEnabled(execution, "tool_cancel", firstDefined(execution.can_cancel, execution.cancellable, fallbackCanCancel) !== false),
      canOpenResult: actionEnabled(execution, "tool_open_result", fallbackCanOpen),
      canClearHistory: actionEnabled(execution, "tool_clear_history", false),
      startedAt: String(firstDefined(execution.started_at, execution.created_at, "")),
      finishedAt: String(firstDefined(execution.finished_at, execution.completed_at, "")),
    };
  }

  function historySources(snapshot, toolId) {
    const source = asRecord(snapshot);
    const nested = asRecord(source.toolbox);
    const projection = projectionFor(source, toolId);
    for (const candidate of [
      projection.history,
      source.toolbox_history,
      source.toolbox_run_history,
      source.toolbox_recent_items,
      nested.history,
      nested.recent_items,
    ]) {
      if (Array.isArray(candidate)) return candidate;
      const rows = asRecord(candidate).items;
      if (Array.isArray(rows)) return rows;
    }
    return [];
  }

  function historyFor(snapshot, toolId) {
    return historySources(snapshot, toolId)
      .map((entry, index) => {
        const row = asRecord(entry);
        const explicitToolId = String(firstDefined(row.tool_id, row.tool, ""));
        const result = firstDefined(row.result, row.output, null);
        const resultPath = resultPathFrom(row, result);
        return {
          toolId: explicitToolId,
          historyId: String(firstDefined(row.history_id, row.run_id, row.execution_id, row.job_id, row.result_id, row.id, index)),
          runId: String(firstDefined(row.run_id, row.execution_id, row.job_id, "")),
          resultId: String(firstDefined(row.result_id, asRecord(result).id, "")),
          title: String(firstDefined(row.title, row.tool_title, row.label, "")),
          status: normalizeStatus(firstDefined(row.status, row.state, row.phase, row.result ? "completed" : "idle")),
          statusText: String(firstDefined(row.status_text, "")),
          timestamp: String(firstDefined(row.last_used, row.finished_at, row.completed_at, row.created_at, row.time, "")),
          message: String(firstDefined(row.message, row.summary, "")),
          result,
          resultPath,
          canOpenResult: !!firstDefined(row.can_open_result, row.has_result, resultPath, result),
        };
      })
      .filter(row => !row.toolId || !toolId || row.toolId === String(toolId));
  }

  function shouldRender(sections) {
    const values = sections instanceof Set ? Array.from(sections) : (Array.isArray(sections) ? sections : []);
    return values.some(section => String(section || "") === "toolbox" || String(section || "").startsWith("toolbox_"));
  }

  const contract = Object.freeze({
    normalizeToolDefinition,
    projectionFor,
    reduceProjectionCache,
    toolForSnapshot,
    validateParameters,
    resolveActionName,
    buildActionPayload,
    actionEnabled,
    resultDisplayLines,
    executionFor,
    historyFor,
    shouldRender,
  });

  function configure(options = {}) {
    dispose();
    dependencies = Object.freeze({ ...options });
    state.configured = true;
    state.disposed = false;
    state.generation += 1;
    state.actionSequence = 0;
    state.valuesByTool = Object.create(null);
    state.errorsByTool = Object.create(null);
    state.touchedTools = new Set();
    state.dirtyTools = new Set();
    state.projectionCache = Object.create(null);
    state.cardsSignature = "";
    state.detailSignature = "";
    state.detailToolId = "";
    state.pending = null;
    state.actionMessage = "";
    state.pagehideHandler = dispose;
    if (typeof window.addEventListener === "function") window.addEventListener("pagehide", state.pagehideHandler);
    return window.UcpToolboxController;
  }

  function requireDependency(name) {
    const value = dependencies[name];
    if (typeof value !== "function") throw new Error(`UcpToolboxController is not configured: ${name}`);
    return value;
  }

  function currentState() {
    return requireDependency("getState")() || {};
  }

  function byId(id) {
    return requireDependency("byId")(id);
  }

  function t(value) {
    return requireDependency("t")(value);
  }

  function translateText(value) {
    return typeof dependencies.translateText === "function" ? dependencies.translateText(value) : t(value);
  }

  function esc(value) {
    return typeof dependencies.esc === "function"
      ? dependencies.esc(value)
      : String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function escAttr(value) {
    return typeof dependencies.escAttr === "function" ? dependencies.escAttr(value) : esc(value).replace(/'/g, "&#39;");
  }

  function selectedToolId() {
    return typeof dependencies.getSelectedToolId === "function" ? String(dependencies.getSelectedToolId() || "") : "";
  }

  function setSelectedToolId(toolId) {
    if (typeof dependencies.setSelectedToolId === "function") dependencies.setSelectedToolId(String(toolId || ""));
  }

  function ingestDisplayState(snapshot) {
    state.projectionCache = reduceProjectionCache(state.projectionCache, snapshot);
  }

  function ingest(snapshot = null) {
    if (state.disposed) return false;
    ingestDisplayState(snapshot || currentState());
    return true;
  }

  function snapshotForTool(snapshot, toolId) {
    const source = asRecord(snapshot);
    const projection = state.projectionCache[String(toolId || "")] || projectionFor(source, toolId);
    if (!Object.keys(asRecord(projection)).length) return source;
    const next = { ...source };
    for (const key of [...DISPLAY_PROJECTION_KEYS, ...DISPLAY_BATCH_KEYS]) delete next[key];
    next.toolbox_display_projection = projection;
    return next;
  }

  function viewProjection(snapshot, toolId) {
    return projectionFor(snapshotForTool(snapshot, toolId), toolId);
  }

  function viewExecution(snapshot, toolId) {
    return executionFor(snapshotForTool(snapshot, toolId), toolId);
  }

  function viewHistory(snapshot, toolId) {
    return historyFor(snapshotForTool(snapshot, toolId), toolId);
  }

  function toolItems(snapshot = currentState()) {
    const source = asRecord(snapshot);
    const rows = Array.isArray(source.toolbox_items) ? source.toolbox_items : asRecord(source.toolbox).items;
    return (Array.isArray(rows) ? rows : []).map(row => {
      const toolId = String(firstDefined(asRecord(row).id, asRecord(row).tool_id, ""));
      return toolForSnapshot(snapshotForTool(source, toolId), toolId, row);
    });
  }

  function selectedTool(snapshot = currentState()) {
    const toolId = selectedToolId();
    return toolItems(snapshot).find(tool => tool.id === toolId) || null;
  }

  function iconUrl(filename) {
    const manifest = typeof dependencies.getIconManifest === "function"
      ? asRecord(dependencies.getIconManifest())
      : asRecord(currentState().icon_manifest);
    const route = String(manifest.route || "/ui-icon").replace(/\/$/, "");
    return `${route}/${String(filename || "nav_toolbox.png")}`;
  }

  function ensureParameterValues(tool, execution) {
    if (state.valuesByTool[tool.id]) return state.valuesByTool[tool.id];
    const executionValues = {
      ...asRecord(tool.initialValues),
      ...asRecord(execution.parameters),
      ...asRecord(execution.params),
      ...asRecord(execution.input),
    };
    const values = {};
    for (const parameter of tool.parameters) {
      values[parameter.name] = hasOwn(executionValues, parameter.name)
        ? executionValues[parameter.name]
        : parameter.defaultValue;
    }
    state.valuesByTool[tool.id] = values;
    return values;
  }

  function renderCards(items, activeId) {
    const grid = byId("toolGrid");
    if (!grid) return;
    const signature = JSON.stringify(items.map(item => [
      item.id,
      translateText(item.title),
      translateText(item.summary),
      item.iconFile,
      item.id === activeId,
    ]));
    if (signature === state.cardsSignature && grid.childElementCount) return;
    state.cardsSignature = signature;
    if (!items.length) {
      grid.innerHTML = `<div class="empty-note toolbox-empty">${esc(t("暂无可用工具"))}</div>`;
      return;
    }
    grid.innerHTML = items.map(item => `
      <button class="tool-card ${item.id === activeId ? "active" : ""}" type="button"
              aria-pressed="${item.id === activeId ? "true" : "false"}"
              onclick="selectTool('${escAttr(item.id)}')">
        <img src="${escAttr(iconUrl(item.iconFile))}" alt="" />
        <h2>${esc(translateText(item.title))}</h2>
        <p>${esc(translateText(item.summary))}</p>
      </button>
    `).join("");
  }

  function overviewHtml(tool) {
    const rows = [
      ["工具", translateText(tool.title)],
      ["说明", translateText(tool.summary)],
      ["输入示例", translateText(tool.inputExample)],
      ["输出示例", translateText(tool.outputExample)],
    ];
    return `<div class="toolbox-overview-grid">${rows.map(([label, value]) => `
      <span>${esc(t(label))}</span><strong>${esc(value || t("暂无"))}</strong>
    `).join("")}</div>`;
  }

  function parameterControlHtml(parameter, value, index) {
    const id = `toolboxParameter${index}`;
    const common = `id="${id}" data-toolbox-parameter="${escAttr(parameter.name)}" ${parameter.readOnly ? "disabled" : ""}`;
    const change = "updateToolParameter(this.dataset.toolboxParameter, this.type === 'checkbox' ? this.checked : this.value)";
    if (parameter.type === "boolean") {
      return `<label class="toolbox-switch-control" for="${id}">
        <input ${common} class="toolbox-switch" type="checkbox" ${value ? "checked" : ""} onchange="${change}" />
        <span>${esc(t(value ? "已启用" : "未启用"))}</span>
      </label>`;
    }
    if (parameter.type === "select") {
      return `<select ${common} onchange="${change}" aria-label="${escAttr(translateText(parameter.label))}">
        ${parameter.options.map(option => `<option value="${escAttr(option.value)}" ${String(option.value) === String(value) ? "selected" : ""} ${option.disabled ? "disabled" : ""}>${esc(translateText(option.label))}</option>`).join("")}
      </select>`;
    }
    if (parameter.type === "textarea") {
      return `<textarea ${common} rows="${parameter.rows}" placeholder="${escAttr(translateText(parameter.placeholder || "请输入参数"))}" oninput="${change}">${esc(value)}</textarea>`;
    }
    const numberAttributes = ["integer", "number"].includes(parameter.type)
      ? `type="number" ${parameter.min !== undefined ? `min="${escAttr(parameter.min)}"` : ""} ${parameter.max !== undefined ? `max="${escAttr(parameter.max)}"` : ""} ${parameter.step !== undefined ? `step="${escAttr(parameter.step)}"` : ""}`
      : `type="${parameter.secret ? "password" : "text"}"`;
    return `<input ${common} ${numberAttributes} value="${escAttr(value)}" placeholder="${escAttr(translateText(parameter.placeholder || "请输入参数"))}" autocomplete="off" spellcheck="false" oninput="${change}" />`;
  }

  function parameterHtml(tool, values) {
    if (!tool.parameters.length) return `<p class="toolbox-empty-inline">${esc(t("暂无参数"))}</p>`;
    return tool.parameters.map((parameter, index) => `
      <div class="toolbox-parameter" data-toolbox-field="${escAttr(parameter.name)}">
        <label class="toolbox-parameter-label" for="toolboxParameter${index}">
          <strong>${esc(translateText(parameter.label))}${parameter.required ? `<span aria-hidden="true">*</span>` : ""}</strong>
          ${parameter.description ? `<small>${esc(translateText(parameter.description))}</small>` : ""}
        </label>
        <div class="toolbox-parameter-control">
          ${parameterControlHtml(parameter, values[parameter.name], index)}
          <small class="toolbox-field-error" data-toolbox-error="${escAttr(parameter.name)}" aria-live="polite"></small>
        </div>
      </div>
    `).join("");
  }

  function actionsHtml(modern) {
    if (!modern) {
      return `<div class="toolbox-actions toolbox-actions-legacy">
        <button id="toolboxStartButton" class="btn btn-primary" type="button" onclick="startTool()">
          <img src="/ui-icon/action_play.png" alt="" />${esc(t("打开工具"))}
        </button>
      </div>`;
    }
    return `<div class="toolbox-actions">
      <button id="toolboxValidateButton" class="btn" type="button" onclick="validateTool()">${esc(t("验证参数"))}</button>
      <button id="toolboxStartButton" class="btn btn-primary" type="button" onclick="startTool()">
        <img src="/ui-icon/action_play.png" alt="" />${esc(t("启动工具"))}
      </button>
      <button id="toolboxCancelButton" class="btn btn-danger" type="button" onclick="cancelTool()">
        <img src="/ui-icon/action_stop.png" alt="" />${esc(t("取消运行"))}
      </button>
    </div>`;
  }

  function detailHtml(tool, values, modern) {
    return `
      <div class="toolbox-detail-scroll">
        <section class="toolbox-section toolbox-overview">
          <div class="toolbox-section-heading">
            <h2>${esc(t("工具详情"))}</h2>
            <span id="toolboxStatusBadge" class="toolbox-status" data-status="idle">${esc(t("待执行"))}</span>
          </div>
          ${overviewHtml(tool)}
        </section>
        <section class="toolbox-section toolbox-parameters" ${modern ? "" : "hidden"}>
          <h2>${esc(t("工具参数"))}</h2>
          <div class="toolbox-parameter-list">${parameterHtml(tool, values)}</div>
          <p id="toolboxValidationMessage" class="toolbox-validation-message" aria-live="polite"></p>
        </section>
        <section class="toolbox-section toolbox-execution" ${modern ? "" : "hidden"} aria-live="polite">
          <div class="toolbox-section-heading"><h2>${esc(t("执行状态"))}</h2><strong id="toolboxExecutionStatus">${esc(t("待执行"))}</strong></div>
          <div id="toolboxProgress" class="toolbox-progress" role="progressbar" aria-label="${escAttr(t("执行进度"))}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div>
          <div class="toolbox-progress-meta"><span>${esc(t("执行进度"))}</span><strong id="toolboxProgressValue">0%</strong></div>
          <p id="toolboxExecutionMessage" class="toolbox-execution-message"></p>
        </section>
        ${actionsHtml(modern)}
        <section class="toolbox-section toolbox-result" ${modern ? "" : "hidden"}>
          <div class="toolbox-section-heading">
            <h2>${esc(t("执行结果"))}</h2>
            <button id="toolboxOpenResultButton" class="icon-btn" type="button" onclick="openToolResult()" title="${escAttr(t("打开结果"))}" aria-label="${escAttr(t("打开结果"))}" disabled><img src="/ui-icon/action_open_directory.png" alt="" /></button>
          </div>
          <pre id="toolboxResultValue" class="toolbox-result-value">${esc(t("暂无执行结果"))}</pre>
        </section>
        <section class="toolbox-section toolbox-history">
          <div class="toolbox-section-heading">
            <h2>${esc(t(modern ? "使用历史" : "最近使用"))}</h2>
            <button id="toolboxClearHistoryButton" class="icon-btn" type="button" onclick="clearToolHistory()" title="${escAttr(t("清空历史"))}" aria-label="${escAttr(t("清空历史"))}" ${modern ? "" : "hidden"}><img src="/ui-icon/action_clear-all.png" alt="" /></button>
          </div>
          <ol id="toolboxHistoryList" class="toolbox-history-list"></ol>
        </section>
      </div>
    `;
  }

  function detailSignature(tool, modern) {
    return JSON.stringify([
      tool.id,
      tool.title,
      tool.summary,
      tool.inputExample,
      tool.outputExample,
      tool.parameters,
      modern,
      t("工具详情"),
      t("工具参数"),
      t("执行结果"),
      t("使用历史"),
    ]);
  }

  function patchValidationErrors(tool, execution = {}) {
    const detail = byId("toolDetail");
    if (!detail) return;
    const errors = state.errorsByTool[tool.id] || {};
    detail.querySelectorAll("[data-toolbox-field]").forEach(field => {
      const name = field.dataset.toolboxField || "";
      const message = String(errors[name] || "");
      field.classList.toggle("is-invalid", !!message);
      const control = field.querySelector("input, select, textarea, button");
      if (control) control.setAttribute("aria-invalid", message ? "true" : "false");
      const error = field.querySelector("[data-toolbox-error]");
      if (error) error.textContent = message ? translateText(message) : "";
    });
    const summary = byId("toolboxValidationMessage");
    if (summary) {
      const hasErrors = Object.keys(errors).length > 0;
      const dirty = state.dirtyTools.has(tool.id);
      const serverMessage = String(execution.validationMessage || "");
      summary.dataset.state = hasErrors || dirty
        ? "error"
        : (serverMessage || state.touchedTools.has(tool.id) ? "success" : "idle");
      if (hasErrors) summary.textContent = t("请修正标记的参数");
      else if (dirty) summary.textContent = t("参数已更改，请重新验证");
      else if (serverMessage) summary.textContent = translateText(serverMessage);
      else summary.textContent = state.touchedTools.has(tool.id) ? t("参数验证通过") : "";
    }
  }

  function effectiveExecution(execution, toolId) {
    if (!state.pending || state.pending.toolId !== toolId) return execution;
    const pendingStatuses = { validate: "validating", start: "starting", cancel: "cancelling" };
    return { ...execution, status: pendingStatuses[state.pending.kind] || execution.status };
  }

  function resultText(execution) {
    const lines = resultDisplayLines(execution.result);
    if (lines.length) return lines.map(translateText).join("\n");
    return execution.resultPath || t("暂无执行结果");
  }

  function patchExecution(tool, snapshot) {
    const rawExecution = viewExecution(snapshot, tool.id);
    const execution = effectiveExecution(rawExecution, tool.id);
    const statusLabel = execution.statusText || STATUS_LABELS[execution.status] || execution.status || "待执行";
    const badge = byId("toolboxStatusBadge");
    if (badge) {
      badge.dataset.status = execution.status;
      badge.textContent = translateText(statusLabel);
    }
    const status = byId("toolboxExecutionStatus");
    if (status) status.textContent = translateText(statusLabel);
    const progress = byId("toolboxProgress");
    if (progress) {
      progress.setAttribute("aria-valuenow", String(execution.progress));
      progress.setAttribute("aria-valuetext", execution.progressText || `${execution.progress}%`);
      progress.classList.toggle("is-indeterminate", execution.progressIndeterminate);
      const bar = progress.querySelector("i");
      if (bar) bar.style.width = `${execution.progress}%`;
    }
    const progressValue = byId("toolboxProgressValue");
    if (progressValue) progressValue.textContent = translateText(execution.progressText || `${execution.progress}%`);
    const message = byId("toolboxExecutionMessage");
    if (message) {
      const value = state.actionMessage || execution.error || execution.message;
      message.dataset.state = state.actionMessage || execution.error || execution.status === "failed" ? "error" : "normal";
      message.textContent = translateText(value || "");
    }
    const result = byId("toolboxResultValue");
    if (result) result.textContent = resultText(execution);
    const open = byId("toolboxOpenResultButton");
    if (open) open.disabled = !actionEnabled(viewProjection(snapshot, tool.id), "tool_open_result", execution.canOpenResult) || !!state.pending;
    return rawExecution;
  }

  function historyRowHtml(row) {
    const statusLabel = row.statusText || STATUS_LABELS[row.status] || row.status || "待执行";
    return `<li class="toolbox-history-row" data-status="${escAttr(row.status)}">
      <div>
        <strong>${esc(translateText(row.title || t("工具运行")))}</strong>
        <span>${esc(translateText(row.timestamp))}</span>
      </div>
      <span class="toolbox-history-status">${esc(translateText(statusLabel))}</span>
      ${row.canOpenResult ? `<button class="icon-btn" type="button" onclick="openToolResult('${escAttr(row.historyId)}')" title="${escAttr(t("打开结果"))}" aria-label="${escAttr(t("打开结果"))}"><img src="/ui-icon/action_open_directory.png" alt="" /></button>` : ""}
    </li>`;
  }

  function patchHistory(tool, snapshot) {
    const rows = viewHistory(snapshot, tool.id);
    const list = byId("toolboxHistoryList");
    if (list) {
      const signature = JSON.stringify(rows);
      if (list.dataset.signature !== signature) {
        list.dataset.signature = signature;
        list.innerHTML = rows.length
          ? rows.map(historyRowHtml).join("")
          : `<li class="toolbox-empty-inline">${esc(t(hasModernContract(tool, snapshot) ? "暂无使用历史" : "暂无最近使用记录"))}</li>`;
      }
    }
    const clear = byId("toolboxClearHistoryButton");
    if (clear) {
      const projection = viewProjection(snapshot, tool.id);
      clear.disabled = !actionEnabled(projection, "tool_clear_history", rows.length > 0) || !rows.length || !!state.pending;
    }
    return rows;
  }

  function setButtonDisabled(button, disabled, reason = "") {
    if (!button) return;
    button.disabled = !!disabled;
    button.title = disabled && reason ? t(reason) : "";
  }

  function patchActions(tool, snapshot, execution, rows, modern) {
    const values = ensureParameterValues(tool, execution);
    const validation = validateParameters(tool, values);
    const pending = !!state.pending;
    const status = effectiveExecution(execution, tool.id).status;
    const busy = pending || BUSY_STATUSES.has(status);
    const projection = viewProjection(snapshot, tool.id);
    const validateEnabled = actionEnabled(projection, "tool_validate", !busy);
    const startEnabled = actionEnabled(projection, "tool_start", !busy);
    setButtonDisabled(byId("toolboxValidateButton"), busy || !validateEnabled, "操作正在进行");
    setButtonDisabled(
      byId("toolboxStartButton"),
      modern ? busy || !startEnabled || !validation.valid : pending,
      !validation.valid ? "请修正标记的参数" : "操作正在进行",
    );
    const canCancel = !pending && actionEnabled(projection, "tool_cancel", execution.canCancel);
    setButtonDisabled(byId("toolboxCancelButton"), !canCancel, "当前没有可取消的运行");
    const clear = byId("toolboxClearHistoryButton");
    if (clear) clear.disabled = pending || !rows.length || !actionEnabled(projection, "tool_clear_history", rows.length > 0);
  }

  function renderDynamic(tool, snapshot, modern) {
    const execution = patchExecution(tool, snapshot);
    if (Object.keys(execution.validationErrors).length && !Object.keys(state.errorsByTool[tool.id] || {}).length) {
      state.errorsByTool[tool.id] = execution.validationErrors;
    }
    patchValidationErrors(tool, execution);
    const rows = patchHistory(tool, snapshot);
    patchActions(tool, snapshot, execution, rows, modern);
  }

  function renderDetail() {
    if (state.disposed) return false;
    const snapshot = currentState();
    ingestDisplayState(snapshot);
    const tool = selectedTool(snapshot);
    const detail = byId("toolDetail");
    if (!detail) return false;
    if (!tool) {
      detail.innerHTML = `<div class="empty-note toolbox-empty">${esc(t("请选择工具"))}</div>`;
      state.detailSignature = "";
      state.detailToolId = "";
      return true;
    }

    const execution = viewExecution(snapshot, tool.id);
    const values = ensureParameterValues(tool, execution);
    const modern = hasModernContract(tool, snapshot);
    const signature = detailSignature(tool, modern);
    if (signature !== state.detailSignature || state.detailToolId !== tool.id || !detail.childElementCount) {
      detail.innerHTML = detailHtml(tool, values, modern);
      state.detailSignature = signature;
      state.detailToolId = tool.id;
      if (typeof dependencies.enhanceSelects === "function") dependencies.enhanceSelects(detail);
    }
    renderDynamic(tool, snapshot, modern);
    return true;
  }

  function render() {
    if (state.disposed) return false;
    const snapshot = currentState();
    ingestDisplayState(snapshot);
    const title = document.querySelector("#page-toolbox .page-head h1");
    const subtitle = document.querySelector("#page-toolbox .page-head p");
    if (title) title.textContent = t("工具箱");
    if (subtitle) subtitle.textContent = t("高效实用的辅助工具，提升工作效率");
    const items = toolItems(snapshot);
    let activeId = selectedToolId();
    if (!items.some(item => item.id === activeId)) {
      activeId = items.length ? items[0].id : "";
      setSelectedToolId(activeId);
    }
    renderCards(items, activeId);
    return renderDetail();
  }

  function select(toolId) {
    if (state.disposed) return false;
    const id = String(toolId || "");
    if (!toolItems().some(tool => tool.id === id)) return false;
    setSelectedToolId(id);
    state.actionMessage = "";
    state.cardsSignature = "";
    state.detailSignature = "";
    render();
    return true;
  }

  function updateParameter(name, value) {
    const tool = selectedTool();
    if (!tool) return false;
    const parameter = tool.parameters.find(row => row.name === String(name || ""));
    if (!parameter || parameter.readOnly) return false;
    const values = ensureParameterValues(tool, viewExecution(currentState(), tool.id));
    values[parameter.name] = parameter.type === "boolean" ? !!value : value;
    const errors = { ...(state.errorsByTool[tool.id] || {}) };
    delete errors[parameter.name];
    state.errorsByTool[tool.id] = errors;
    state.dirtyTools.add(tool.id);
    state.actionMessage = "";
    const snapshot = currentState();
    const execution = viewExecution(snapshot, tool.id);
    patchValidationErrors(tool, execution);
    if (parameter.type === "boolean") {
      const detail = byId("toolDetail");
      const control = detail && Array.from(detail.querySelectorAll("[data-toolbox-parameter]"))
        .find(element => element.dataset.toolboxParameter === parameter.name);
      const label = control && control.closest(".toolbox-switch-control")?.querySelector("span");
      if (label) label.textContent = t(value ? "已启用" : "未启用");
    }
    patchActions(tool, snapshot, execution, viewHistory(snapshot, tool.id), hasModernContract(tool, snapshot));
    return true;
  }

  function requestAction(action, payload) {
    return requireDependency("requestAction")(action, payload);
  }

  function actionErrors(result) {
    const source = asRecord(result);
    const data = asRecord(source.data);
    return normalizeValidationErrors(firstDefined(source.validation_errors, source.errors, data.validation_errors, data.errors, {}));
  }

  async function dispatch(kind, tool, values, context = {}) {
    const snapshot = currentState();
    const action = resolveActionName(kind, tool, snapshot);
    if (!action) return { status: "error", message: "unsupported toolbox action" };
    const payload = buildActionPayload(kind, tool, values, context);
    const generation = state.generation;
    const sequence = ++state.actionSequence;
    state.pending = { kind, toolId: tool.id, generation, sequence };
    state.actionMessage = "";
    renderDynamic(tool, snapshot, hasModernContract(tool, snapshot));
    try {
      const result = await requestAction(action, payload);
      if (state.disposed || state.generation !== generation || state.actionSequence !== sequence) return result;
      const errors = actionErrors(result);
      if (Object.keys(errors).length) state.errorsByTool[tool.id] = errors;
      if (!result || result === false || (result.status && result.status !== "ok")) {
        state.actionMessage = String(firstDefined(asRecord(result).message, "操作提交失败"));
      }
      return result;
    } catch (error) {
      if (!state.disposed && state.generation === generation && state.actionSequence === sequence) {
        state.actionMessage = String(firstDefined(error && error.message, error, "操作提交失败"));
      }
      return { status: "error", message: state.actionMessage };
    } finally {
      if (!state.disposed && state.generation === generation && state.actionSequence === sequence) {
        state.pending = null;
        renderDetail();
      }
    }
  }

  function validate() {
    const tool = selectedTool();
    if (!tool || state.pending) return Promise.resolve({ status: "error" });
    const values = ensureParameterValues(tool, viewExecution(currentState(), tool.id));
    const validation = validateParameters(tool, values);
    state.errorsByTool[tool.id] = validation.errors;
    state.touchedTools.add(tool.id);
    state.dirtyTools.delete(tool.id);
    patchValidationErrors(tool, viewExecution(currentState(), tool.id));
    if (!validation.valid) return Promise.resolve({ status: "invalid", errors: validation.errors });
    return dispatch("validate", tool, validation.values, viewProjection(currentState(), tool.id));
  }

  function start() {
    const tool = selectedTool();
    if (!tool || state.pending) return Promise.resolve({ status: "error" });
    const values = ensureParameterValues(tool, viewExecution(currentState(), tool.id));
    const validation = validateParameters(tool, values);
    state.errorsByTool[tool.id] = validation.errors;
    state.touchedTools.add(tool.id);
    state.dirtyTools.delete(tool.id);
    patchValidationErrors(tool, viewExecution(currentState(), tool.id));
    if (!validation.valid) return Promise.resolve({ status: "invalid", errors: validation.errors });
    return dispatch("start", tool, validation.values, viewProjection(currentState(), tool.id));
  }

  function cancel() {
    const tool = selectedTool();
    if (!tool || state.pending) return Promise.resolve({ status: "error" });
    const execution = viewExecution(currentState(), tool.id);
    return dispatch("cancel", tool, {}, execution);
  }

  function openResult(historyId = "") {
    const snapshot = currentState();
    const tool = selectedTool(snapshot);
    if (!tool || state.pending) return Promise.resolve({ status: "error" });
    const execution = viewExecution(snapshot, tool.id);
    const history = historyId
      ? viewHistory(snapshot, tool.id).find(row => row.historyId === String(historyId))
      : null;
    return dispatch("openResult", tool, {}, history || execution);
  }

  function clearHistory() {
    const tool = selectedTool();
    if (!tool || state.pending) return Promise.resolve({ status: "error" });
    return dispatch("clearHistory", tool, {}, viewProjection(currentState(), tool.id));
  }

  function dispose() {
    if (state.pagehideHandler && typeof window.removeEventListener === "function") {
      window.removeEventListener("pagehide", state.pagehideHandler);
    }
    state.pagehideHandler = null;
    state.disposed = true;
    state.configured = false;
    state.generation += 1;
    state.actionSequence += 1;
    state.pending = null;
    state.cardsSignature = "";
    state.detailSignature = "";
    dependencies = Object.freeze({});
  }

  window.UcpToolboxController = Object.freeze({
    configure,
    ingest,
    render,
    renderDetail,
    select,
    updateParameter,
    validate,
    start,
    cancel,
    openResult,
    clearHistory,
    shouldRender,
    dispose,
    contract,
  });
})();
