from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = ROOT / "app" / "web" / "static"
TOOLBOX_JS = STATIC_DIR / "toolbox_controller.js"
TOOLBOX_CSS = STATIC_DIR / "toolbox.css"
TOOLBOX_CONTRACT_JS = STATIC_DIR / "toolbox_contract.js"
TOOLBOX_VIEW_JS = STATIC_DIR / "toolbox_view.js"


def _run_toolbox_contract(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the toolbox JavaScript contract")

    script = r"""
const fs = require("fs");
const vm = require("vm");
global.window = {};
const filenames = process.env.UCP_TOOLBOX_JS.split(require("path").delimiter);
for (const filename of filenames) {
  vm.runInThisContext(fs.readFileSync(filename, "utf8"), { filename });
}
const contract = window.UcpToolboxContract;
const result = Function("contract", `return (${process.env.UCP_TOOLBOX_EXPRESSION});`)(contract);
process.stdout.write(JSON.stringify(result));
"""
    env = {
        **os.environ,
        "UCP_TOOLBOX_JS": os.pathsep.join((str(TOOLBOX_CONTRACT_JS),)),
        "UCP_TOOLBOX_EXPRESSION": expression,
    }
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    return json.loads(completed.stdout)


def test_toolbox_assets_load_before_composition_root() -> None:
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert TOOLBOX_JS.is_file()
    assert TOOLBOX_CONTRACT_JS.is_file()
    assert TOOLBOX_VIEW_JS.is_file()
    assert TOOLBOX_CSS.is_file()
    assert '/static/toolbox.css?' in index
    scripts = [
        '/static/toolbox_contract.js?',
        '/static/toolbox_view.js?',
        '/static/toolbox_controller.js?',
        '/static/app.js?',
    ]
    assert all(script in index for script in scripts)
    assert [index.index(script) for script in scripts] == sorted(index.index(script) for script in scripts)


def test_toolbox_contract_evaluates_without_browser_globals() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the toolbox JavaScript contract")

    script = """
const fs = require("fs");
const vm = require("vm");
const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.env.UCP_TOOLBOX_CONTRACT, "utf8"), context);
process.stdout.write(JSON.stringify(Object.isFrozen(context.window.UcpToolboxContract)));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "UCP_TOOLBOX_CONTRACT": str(TOOLBOX_CONTRACT_JS)},
    )
    assert json.loads(completed.stdout) is True


def test_toolbox_controller_requests_once_and_ignores_disposed_promise_resolution() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the toolbox JavaScript contract")

    script = r"""
const fs = require("fs");
const vm = require("vm");
let lookups = 0;
global.window = { addEventListener() {}, removeEventListener() {} };
global.document = { getElementById() { lookups += 1; return null; } };
for (const filename of process.env.UCP_TOOLBOX_MODULES.split(require("path").delimiter)) {
  vm.runInThisContext(fs.readFileSync(filename, "utf8"), { filename });
}
let resolveAction;
let calls = 0;
const snapshot = {
  toolbox_items: [{ id: "media_probe", parameters: [{ name: "source", required: true, default: "input.mp4" }] }]
};
const controller = window.UcpToolboxController;
controller.configure({
  getState: () => snapshot,
  requestAction: () => { calls += 1; return new Promise(resolve => { resolveAction = resolve; }); }
});
const pending = controller.start();
const lookupsBeforeDispose = lookups;
controller.dispose();
resolveAction({ status: "ok" });
pending.then(() => process.stdout.write(JSON.stringify({ calls, lookupsBeforeDispose, lookupsAfterResolve: lookups })));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UCP_TOOLBOX_MODULES": os.pathsep.join(
                (str(TOOLBOX_CONTRACT_JS), str(TOOLBOX_VIEW_JS), str(TOOLBOX_JS))
            ),
        },
    )
    result = json.loads(completed.stdout)
    assert result["calls"] == 1
    assert result["lookupsAfterResolve"] == result["lookupsBeforeDispose"]


def test_toolbox_controller_reconfigure_drops_previous_session_projection() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the toolbox JavaScript contract")

    script = r"""
const fs = require("fs");
const vm = require("vm");
global.window = {
  UcpToolboxView: {
    renderCards() {}, renderEmpty() {}, renderDetail() {},
    patchDetail(model) { global.models.push(model); }
  },
  addEventListener() {}, removeEventListener() {}
};
global.models = [];
for (const filename of process.env.UCP_TOOLBOX_MODULES.split(require("path").delimiter)) {
  vm.runInThisContext(fs.readFileSync(filename, "utf8"), { filename });
}
const controller = window.UcpToolboxController;
const tool = { id: "file_verify", parameters: [] };
controller.configure({
  getState: () => ({
    toolbox_items: [tool],
    toolbox_display_projection: {
      tool_id: "file_verify", state: "running", progress: { value: 71 }
    }
  }),
  requestAction: async () => ({ status: "ok" })
});
controller.render();
controller.configure({
  getState: () => ({ toolbox_items: [tool] }),
  requestAction: async () => ({ status: "ok" })
});
controller.render();
process.stdout.write(JSON.stringify(global.models.map(model => model.execution.progress)));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UCP_TOOLBOX_MODULES": os.pathsep.join((str(TOOLBOX_CONTRACT_JS), str(TOOLBOX_JS))),
        },
    )

    assert json.loads(completed.stdout) == [71, 0]


def test_toolbox_controller_resumes_after_persisted_page_cache_restore() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the toolbox JavaScript contract")

    script = r"""
const fs = require("fs");
const vm = require("vm");
const listeners = new Map();
let cardRenders = 0;
global.window = {
  UcpToolboxView: {
    renderCards() { cardRenders += 1; }, renderEmpty() {}, renderDetail() {}, patchDetail() {}
  },
  addEventListener(name, handler) { listeners.set(name, handler); },
  removeEventListener(name, handler) { if (listeners.get(name) === handler) listeners.delete(name); }
};
for (const filename of process.env.UCP_TOOLBOX_MODULES.split(require("path").delimiter)) {
  vm.runInThisContext(fs.readFileSync(filename, "utf8"), { filename });
}
const controller = window.UcpToolboxController;
controller.configure({
  getState: () => ({ toolbox_items: [{ id: "file_verify", parameters: [] }] }),
  requestAction: async () => ({ status: "ok" })
});
controller.render();
listeners.get("pagehide")({ persisted: true });
const renderedWhileSuspended = controller.render();
listeners.get("pageshow")({ persisted: true });
process.stdout.write(JSON.stringify({ cardRenders, renderedWhileSuspended, handlers: [...listeners.keys()].sort() }));
"""
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UCP_TOOLBOX_MODULES": os.pathsep.join((str(TOOLBOX_CONTRACT_JS), str(TOOLBOX_JS))),
        },
    )
    result = json.loads(completed.stdout)

    assert result == {
        "cardRenders": 2,
        "renderedWhileSuspended": False,
        "handlers": ["pagehide", "pageshow"],
    }


def test_toolbox_controller_owns_interaction_instead_of_app_monolith() -> None:
    module = TOOLBOX_JS.read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "window.UcpToolboxController = Object.freeze" in module
    for export in (
        "configure",
        "ingest",
        "render",
        "select",
        "updateParameter",
        "validate",
        "start",
        "cancel",
        "openResult",
        "clearHistory",
        "shouldRender",
        "dispose",
        "contract",
    ):
        assert export in module.split("window.UcpToolboxController = Object.freeze({", 1)[1]

    assert "window.UcpToolboxController.configure" in app
    assert "toolboxControllerService().ingest();" in app
    assert "toolboxControllerService().render()" in app
    assert "toolboxControllerService().shouldRender(sections)" in app
    assert "function normalizeToolDefinition" not in app
    assert "function validateParameters" not in app
    assert "function renderParameter" not in app
    assert "document" not in module
    assert '"Action failed"' not in module
    assert '"操作提交失败"' in module


def test_toolbox_view_routes_visible_copy_through_translation_context() -> None:
    module = TOOLBOX_VIEW_JS.read_text(encoding="utf-8")
    labels = (
        "工具详情",
        "输入示例",
        "输出示例",
        "工具参数",
        "执行状态",
        "执行进度",
        "验证参数",
        "启动工具",
        "取消运行",
        "执行结果",
        "打开结果",
        "使用历史",
        "清空历史",
        "请选择工具",
        "暂无参数",
        "暂无执行结果",
        "暂无使用历史",
        "已启用",
        "未启用",
        "等待操作",
    )

    assert "renderEmpty" in module.split("window.UcpToolboxView = Object.freeze({", 1)[1]
    for label in labels:
        matching_lines = [line for line in module.splitlines() if f'"{label}"' in line]
        assert matching_lines
        assert any("text(context" in line for line in matching_lines)
    for untranslated in ("Tool details", "No parameters", "No result", "No history", "Enabled", "Disabled"):
        assert f'"{untranslated}"' not in module


def test_toolbox_parameter_contract_normalizes_and_validates_values() -> None:
    result = _run_toolbox_contract(
        """
(() => {
  const tool = contract.normalizeToolDefinition({
    id: "media_probe",
    parameters: [
      { name: "source", type: "text", required: true },
      { name: "count", type: "integer", min: 1, max: 5, default: 2 },
      { name: "mode", type: "select", options: ["fast", "safe"] },
      { name: "enabled", type: "boolean", default: false }
    ]
  });
  return {
    names: tool.parameters.map(parameter => parameter.name),
    invalid: contract.validateParameters(tool, {
      source: "",
      count: "9",
      mode: "fast",
      enabled: true
    }),
    valid: contract.validateParameters(tool, {
      source: "input.mp4",
      count: "3",
      mode: "safe",
      enabled: true
    })
  };
})()
"""
    )

    assert result["names"] == ["source", "count", "mode", "enabled"]
    assert result["invalid"]["valid"] is False
    assert set(result["invalid"]["errors"]) == {"source", "count"}
    assert result["valid"] == {
        "valid": True,
        "errors": {},
        "values": {
            "source": "input.mp4",
            "count": 3,
            "mode": "safe",
            "enabled": True,
        },
    }


def test_toolbox_actions_use_new_contract_with_legacy_start_fallback() -> None:
    result = _run_toolbox_contract(
        """
(() => {
  const modern = contract.normalizeToolDefinition({
    id: "media_probe",
    parameters: [{ name: "source", required: true }]
  });
  const legacy = contract.normalizeToolDefinition({ id: "link_parser" });
  return {
    modern: ["validate", "start", "cancel", "openResult", "clearHistory"]
      .map(kind => contract.resolveActionName(kind, modern, {})),
    legacyStart: contract.resolveActionName("start", legacy, {}),
    explicitStart: contract.resolveActionName(
      "start",
      legacy,
      { toolbox_contract: { actions: { start: "tool_start" } } }
    ),
    startPayload: contract.buildActionPayload(
      "start",
      modern,
      { source: "input.mp4" },
      { runId: "run-7" }
    ),
    cancelPayload: contract.buildActionPayload("cancel", modern, {}, { runId: "run-7" }),
    openPayload: contract.buildActionPayload(
      "openResult",
      modern,
      {},
      { runId: "run-7", resultId: "result-9" }
    )
  };
})()
"""
    )

    assert result["modern"] == [
        "tool_validate",
        "tool_start",
        "tool_cancel",
        "tool_open_result",
        "tool_clear_history",
    ]
    assert result["legacyStart"] == "run_tool"
    assert result["explicitStart"] == "tool_start"
    assert result["startPayload"] == {
        "tool_id": "media_probe",
        "parameters": {"source": "input.mp4"},
    }
    assert result["cancelPayload"] == {"tool_id": "media_probe", "run_id": "run-7"}
    assert result["openPayload"] == {"tool_id": "media_probe", "result_id": "result-9"}


def test_toolbox_runtime_consumes_delta_sections_without_polling() -> None:
    module = TOOLBOX_JS.read_text(encoding="utf-8")
    result = _run_toolbox_contract(
        """
({
  relevant: contract.shouldRender(new Set(["app_status", "toolbox_execution"])),
  irrelevant: contract.shouldRender(new Set(["app_status", "queue_items"])),
  execution: contract.executionFor({
    toolbox_execution: {
      tool_id: "media_probe",
      run_id: "run-7",
      status: "running",
      progress: 42,
      result: { path: "D:/output/report.json" }
    }
  }, "media_probe")
})
"""
    )

    assert result["relevant"] is True
    assert result["irrelevant"] is False
    assert result["execution"]["status"] == "running"
    assert result["execution"]["progress"] == 42
    assert result["execution"]["runId"] == "run-7"
    assert result["execution"]["resultPath"] == "D:/output/report.json"
    assert "setInterval(" not in module
    assert "/api/frontend/state" not in module
    assert "/api/frontend/delta" not in module
    assert 'requestAction(action, payload)' in module


def test_toolbox_consumes_shared_display_projection_contract() -> None:
    result = _run_toolbox_contract(
        """
(() => {
  const snapshot = {
    toolbox_items: [{ id: "file_verify", title: "File verify" }],
    toolbox_display_projection: {
      tool_id: "file_verify",
      state: "running",
      status_text: "Calculating",
      run_id: "run-7",
      form: {
        fields: [
          { id: "source", label: "File", type: "text", required: true },
          {
            id: "algorithm",
            label: "Algorithm",
            type: "choice",
            options: [{ value: "sha256", label: "SHA256" }]
          }
        ],
        values: { source: "D:/media/demo.mp4", algorithm: "sha256" }
      },
      progress: { value: 63, text: "63% - demo.mp4" },
      validation: { state: "valid", message: "Parameters are valid" },
      actions: {
        tool_validate: false,
        tool_start: false,
        tool_cancel: true,
        tool_open_result: false,
        tool_clear_history: false
      }
    }
  };
  const projection = contract.projectionFor(snapshot, "file_verify");
  const tool = contract.toolForSnapshot(snapshot, "file_verify");
  return {
    fields: tool.parameters.map(field => [field.name, field.type]),
    values: tool.initialValues,
    execution: contract.executionFor(snapshot, "file_verify"),
    validateEnabled: contract.actionEnabled(projection, "tool_validate", true),
    cancelEnabled: contract.actionEnabled(projection, "tool_cancel", false)
  };
})()
"""
    )

    assert result["fields"] == [["source", "text"], ["algorithm", "select"]]
    assert result["values"] == {"source": "D:/media/demo.mp4", "algorithm": "sha256"}
    assert result["execution"]["status"] == "running"
    assert result["execution"]["statusText"] == "Calculating"
    assert result["execution"]["progress"] == 63
    assert result["execution"]["progressText"] == "63% - demo.mp4"
    assert result["execution"]["runId"] == "run-7"
    assert result["validateEnabled"] is False
    assert result["cancelEnabled"] is True


def test_toolbox_display_batch_wins_and_result_projection_omits_raw_logs() -> None:
    result = _run_toolbox_contract(
        """
(() => {
  const snapshot = {
    toolbox_display_projection: { tool_id: "file_verify", state: "ready" },
    toolbox_display_batch: {
      projections: [{
        tool_id: "file_verify",
        state: "success",
        result: {
          id: "result-9",
          display_text: "SHA256 complete",
          rows: [{ label: "Digest", value: "abc123" }],
          raw_logs: ["RAW_LOG_MUST_NOT_RENDER"]
        },
        history: [{
          id: "history-1",
          title: "File verify",
          status_text: "Success",
          finished_at: "2026-07-27 10:20"
        }],
        actions: { tool_open_result: true, tool_clear_history: true }
      }],
      events: [{ message: "RAW_EVENT_MUST_NOT_RENDER" }]
    }
  };
  const projection = contract.projectionFor(snapshot, "file_verify");
  const execution = contract.executionFor(snapshot, "file_verify");
  return {
    state: projection.state,
    lines: contract.resultDisplayLines(execution.result),
    history: contract.historyFor(snapshot, "file_verify"),
    openEnabled: contract.actionEnabled(projection, "tool_open_result", false)
  };
})()
"""
    )

    assert result["state"] == "success"
    assert result["lines"] == ["SHA256 complete", "Digest: abc123"]
    assert "RAW_LOG_MUST_NOT_RENDER" not in json.dumps(result)
    assert "RAW_EVENT_MUST_NOT_RENDER" not in json.dumps(result)
    assert result["history"][0]["historyId"] == "history-1"
    assert result["history"][0]["title"] == "File verify"
    assert result["openEnabled"] is True


def test_toolbox_projection_reducer_preserves_form_across_progress_only_delta() -> None:
    result = _run_toolbox_contract(
        """
(() => {
  let cache = contract.reduceProjectionCache({}, {
    toolbox_display_projection: {
      tool_id: "file_verify",
      state: "ready",
      form: {
        fields: [{ id: "source", type: "text" }],
        values: { source: "D:/media/demo.mp4" }
      }
    }
  });
  cache = contract.reduceProjectionCache(cache, {
    toolbox_display_batch: [{
      tool_id: "file_verify",
      state: "running",
      progress: { value: 28, text: "2 / 7" }
    }]
  });
  return cache.file_verify;
})()
"""
    )

    assert result["state"] == "running"
    assert result["progress"] == {"value": 28, "text": "2 / 7"}
    assert result["form"]["fields"] == [{"id": "source", "type": "text"}]
    assert result["form"]["values"] == {"source": "D:/media/demo.mp4"}


def test_toolbox_styles_use_theme_tokens_and_responsive_constraints() -> None:
    css = TOOLBOX_CSS.read_text(encoding="utf-8")

    for token in ("var(--panel)", "var(--text)", "var(--muted)", "var(--border)", "var(--accent)"):
        assert token in css
    assert "#page-toolbox" in css
    assert ".toolbox-parameter" in css
    assert ".toolbox-progress" in css
    assert ".toolbox-history" in css
    assert "@media (max-width:" in css
    assert "#" not in "\n".join(
        line for line in css.splitlines() if not line.lstrip().startswith("#page-toolbox")
    )


def test_toolbox_visible_labels_have_all_webui_translations() -> None:
    i18n = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    english = i18n.split('"en-US": {', 1)[1].split('"zh-TW": {', 1)[0]
    traditional = i18n.split('"zh-TW": {', 1)[1].split("};", 1)[0]
    labels = (
        "工具参数",
        "验证参数",
        "启动工具",
        "取消运行",
        "执行状态",
        "执行进度",
        "执行结果",
        "使用历史",
        "打开结果",
        "清空历史",
        "请选择工具",
        "暂无参数",
        "暂无执行结果",
        "暂无使用历史",
        "请修正标记的参数",
        "参数已更改，请重新验证",
        "等待操作",
        "正在启动",
        "运行中",
        "正在取消",
    )

    for label in labels:
        assert f'"{label}":' in english
        assert f'"{label}":' in traditional
