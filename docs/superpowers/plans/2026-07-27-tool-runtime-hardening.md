# Tool Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the new toolbox code into a bounded, owner_id-scoped, fail-closed runtime that is genuinely connected to GUI and WebUI, while keeping execution disabled in the public Web profile.

**Architecture:** Reuse the host-owned `ExecutionProfile` from `shared/execution_profile.py`; tool code declares `ToolRequirements`, while `ToolGrantEvaluator` compares those requirements with the immutable host grant before plugin validation or execution. Keep discovery in `app/core/tools`, scheduling and durable state in `ToolRunnerService`, and frontend translation in a small `FrontendToolRuntime` adapter. GUI and browser controllers remain thin state-machine views, split by responsibility so current architecture budgets stay enforceable.

**Tech Stack:** Python 3.10+, dataclasses, `ThreadPoolExecutor`, SQLite recovery ledger, PyQt6, vanilla JavaScript, pytest, Ruff, repository architecture contracts.

## Global Constraints

- All collected tests must live under exactly one canonical root: `tests/unit/`, `tests/integration/`, `tests/contract/`, `tests/e2e/`, `tests/architecture/`, `tests/performance/`, `tests/release/`, or `tests/testkit/`.
- Test modules follow `tests/<suite>/<production namespace>/test_<observable responsibility>.py`; never add exact-file suite allowlists.
- Production files under `app/ui/` remain at or below 800 lines; other new production Python files remain at or below 1,500 lines.
- `toolbox.css` is a first-class responsibility stylesheet and is loaded exactly once in `CSS_LOAD_ORDER` before `overlays_responsive.css`.
- `ExecutionProfile` is defined only in `shared/execution_profile.py` and contains host-owned `host_surface`, `owner_id`, `allow_machine_credentials`, `allow_caller_proxy`, `require_public_network`, `allow_tool_execution`, `tool_permissions`, `approved_roots`, and `allow_external_plugins` grants. Tool manifests and request payloads cannot widen it.
- External directory tools and `ucrawl.tools` entry points are disabled by default; discovery or execution requires `execution_profile.allow_external_plugins is True`.
- Path-capable tools fail closed when `execution_profile.approved_roots` is empty; a relative or absolute path must resolve below at least one host-approved root before validation or execution.
- Runtime admission is bounded at 32 non-terminal runs globally and 8 non-terminal runs per owner_id.
- A run can be read, cancelled, or cleared only by its owner_id; terminal public history never crosses owner_id boundaries.
- Durable history is a recursive positive projection: unknown keys, parameters, progress details, result data, local paths, credentials, proxies, cookies, headers, tokens, and arbitrary plugin payloads are not persisted.
- Shutdown converts queued futures to terminal `cancelled` records before executor teardown, cooperatively cancels running tools, flushes the final history snapshot, and is idempotent.
- CLI `tools run` is synchronous and prints one terminal result; Ctrl+C cancels that same in-process run. A standalone CLI invocation never claims it can cancel a run owned by another process.
- Download-residue cleanup never deletes an active recovery-ledger row or any workspace beneath an active ledger save directory.
- GUI derives a per-process profile with `local_execution_profile`; Public WebUI derives a per-session profile with `public_web_profile` and receives real manifests, state, validation, denial, and history projections, but `tool_start`, `tool_cancel`, destructive cleanup, result-path opening, and external plugins remain disabled.

---

## File Structure

### Test ownership

- `tests/contract/cli/test_tools_command.py` — CLI command and synchronous-output contract.
- `tests/contract/python/test_tools_api.py` — public Python SDK facade and close semantics.
- `tests/contract/frontend/test_toolbox.py` — browser asset, action, projection, and state-machine contract.
- `tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py` — PyQt page signal and rendering lifecycle.
- `tests/integration/app/core/tools/test_download_residue_tool.py` — filesystem plus recovery-ledger cleanup behavior.
- `tests/integration/app/core/tools/test_environment_diagnostics_tool.py` — environment probe orchestration.
- `tests/integration/app/core/tools/test_media_health_tool.py` — media probe integration.

### Production ownership

- `shared/execution_profile.py` — single host-owned execution grant shared by public networking and tools; this plan consumes but does not redefine it.
- `app/core/tools/contracts.py` — immutable manifest, requirements, grant evaluation, context, validation, result, and cancellation types.
- `app/core/tools/registry.py` — discovery, provenance, and opt-in external loading.
- `app/services/tool_history_projection.py` — recursive positive projection and durable-history schema.
- `app/services/tool_runner_service.py` — bounded owner_id-aware admission, execution, cancellation, ordering, persistence, and shutdown.
- `app/services/frontend_tool_runtime.py` — translates frontend actions and runner events into toolbox snapshots.
- `app/services/frontend_toolbox_adapter.py` — converts manifests and runs to shared GUI/Web display projections.
- `app/ui/pages/toolbox_models.py` — pure normalization, selection, form values, and action-state reducers.
- `app/ui/pages/toolbox_widgets.py` — reusable Qt card, parameter editor, status, result, and history widgets.
- `app/ui/pages/toolbox_page.py` — page composition and action signal orchestration only.
- `app/web/static/toolbox_contract.js` — browser normalization, validation, and action payload contract.
- `app/web/static/toolbox_view.js` — toolbox DOM rendering and bounded patches.
- `app/web/static/toolbox_controller.js` — lifecycle, pending-action state, and dependency orchestration.
- `app/web/static/toolbox.css` — toolbox-only WebUI styling.
- `cli/commands/tools.py` — synchronous process-scoped CLI workflow.
- `ucrawl/tools.py` and `shared/sdk_runtime.py` — SDK resource ownership and close propagation.

### Task 1: Move Every New Test into Its Canonical Suite

**Files:**
- Move: `tests/cli/test_tools_command.py` → `tests/contract/cli/test_tools_command.py`
- Move: `tests/sdk/test_tools_api.py` → `tests/contract/python/test_tools_api.py`
- Move: `tests/ui/test_toolbox_page_lifecycle.py` → `tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py`
- Move: `tests/web/test_toolbox_web_contract.py` → `tests/contract/frontend/test_toolbox.py`
- Move: `tests/core/tools/test_download_residue_tool.py` → `tests/integration/app/core/tools/test_download_residue_tool.py`
- Move: `tests/core/tools/test_environment_diagnostics_tool.py` → `tests/integration/app/core/tools/test_environment_diagnostics_tool.py`
- Move: `tests/core/tools/test_media_health_tool.py` → `tests/integration/app/core/tools/test_media_health_tool.py`
- Test: `tests/architecture/test_test_suite_layout.py`
- Test: `tests/testkit/test_catalog.py`

**Interfaces:**
- Consumes: `tests.support.catalog.BUILTIN_SUITE_ROOTS` and `TEST_MODULE_GLOB == "test_*.py"`.
- Produces: directory-driven collection with no toolbox filename allowlist.

- [ ] **Step 1: Run the architecture test before moving files**

Run: `python -m pytest tests/architecture/test_test_suite_layout.py::TestSuiteLayoutArchitecture::test_all_test_modules_live_below_a_canonical_suite_root -q`

Expected: FAIL listing the seven `tests/cli`, `tests/sdk`, `tests/ui`, `tests/web`, and `tests/core/tools` modules.

- [ ] **Step 2: Move the modules without changing their test bodies**

```powershell
New-Item -ItemType Directory -Force tests/contract/cli, tests/contract/python, tests/contract/frontend, tests/unit/app/ui/pages, tests/integration/app/core/tools | Out-Null
git mv tests/cli/test_tools_command.py tests/contract/cli/test_tools_command.py
git mv tests/sdk/test_tools_api.py tests/contract/python/test_tools_api.py
git mv tests/ui/test_toolbox_page_lifecycle.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py
git mv tests/web/test_toolbox_web_contract.py tests/contract/frontend/test_toolbox.py
git mv tests/core/tools/test_download_residue_tool.py tests/integration/app/core/tools/test_download_residue_tool.py
git mv tests/core/tools/test_environment_diagnostics_tool.py tests/integration/app/core/tools/test_environment_diagnostics_tool.py
git mv tests/core/tools/test_media_health_tool.py tests/integration/app/core/tools/test_media_health_tool.py
```

- [ ] **Step 3: Verify canonical collection and unchanged behavior**

Run: `python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py tests/contract/cli/test_tools_command.py tests/contract/python/test_tools_api.py tests/contract/frontend/test_toolbox.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py tests/integration/app/core/tools -q`

Expected: PASS; `pytest --collect-only` reports every moved module once.

- [ ] **Step 4: Commit the taxonomy-only change**

```bash
git add tests/contract/cli/test_tools_command.py tests/contract/python/test_tools_api.py tests/contract/frontend/test_toolbox.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py tests/integration/app/core/tools/test_download_residue_tool.py tests/integration/app/core/tools/test_environment_diagnostics_tool.py tests/integration/app/core/tools/test_media_health_tool.py
git commit -m "test: place toolbox coverage in canonical suites"
```

### Task 2: Split GUI and Browser Toolbox Responsibilities and Register CSS

**Files:**
- Create: `app/ui/pages/toolbox_models.py`
- Create: `app/ui/pages/toolbox_widgets.py`
- Modify: `app/ui/pages/toolbox_page.py`
- Create: `app/web/static/toolbox_contract.js`
- Create: `app/web/static/toolbox_view.js`
- Modify: `app/web/static/toolbox_controller.js`
- Modify: `app/web/static/index.html`
- Modify: `tests/architecture/test_frontend_file_boundaries.py`
- Modify: `tests/architecture/test_file_size_limits.py`
- Modify: `tests/contract/frontend/test_toolbox.py`
- Modify: `tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py`

**Interfaces:**
- Consumes: `ToolboxPage.action_requested(str, dict)` and existing `window.UcpToolboxController` public methods.
- Produces: `normalize_toolbox_snapshot(snapshot) -> ToolboxSnapshot`, Qt widget classes, `window.UcpToolboxContract`, `window.UcpToolboxView`, and the same controller facade with stable DOM updates.

- [ ] **Step 1: Write architecture and browser ownership tests that fail on the current monoliths**

```python
def test_toolbox_responsibilities_stay_split_and_ordered() -> None:
    assert _line_count(PROJECT_ROOT / "app/ui/pages/toolbox_page.py") <= 800
    assert _line_count(PROJECT_ROOT / "app/web/static/toolbox_controller.js") <= 700
    assert stylesheet_names_from_index()[-2:] == ("toolbox.css", "overlays_responsive.css")
    assert script_names_from_index().index("toolbox_contract.js") < script_names_from_index().index("toolbox_view.js")
    assert script_names_from_index().index("toolbox_view.js") < script_names_from_index().index("toolbox_controller.js")
```

Run: `python -m pytest tests/architecture/test_frontend_file_boundaries.py tests/architecture/test_file_size_limits.py tests/contract/frontend/test_toolbox.py -q`

Expected: FAIL because `toolbox_page.py` exceeds 800 lines, `toolbox_controller.js` owns all responsibilities, and `toolbox.css` is absent from `CSS_LOAD_ORDER`.

- [ ] **Step 2: Extract pure Qt normalization and view widgets**

```python
# app/ui/pages/toolbox_models.py
@dataclass(frozen=True, slots=True)
class ToolboxSnapshot:
    items: tuple[dict[str, Any], ...]
    recent_items: tuple[dict[str, Any], ...]
    selected_tool_id: str
    display_projection: Mapping[str, Any]

def normalize_toolbox_snapshot(snapshot: Mapping[str, Any]) -> ToolboxSnapshot:
    items = tuple(dict(item) for item in snapshot.get("toolbox_items", ()) if isinstance(item, Mapping))
    recent = tuple(dict(item) for item in snapshot.get("toolbox_recent_items", ()) if isinstance(item, Mapping))
    projection = snapshot.get("toolbox_display_projection", {})
    return ToolboxSnapshot(
        items,
        recent,
        str(snapshot.get("toolbox_selected_tool_id") or ""),
        dict(projection) if isinstance(projection, Mapping) else {},
    )

def build_tool_action_payload(action: str, tool_id: str, values: Mapping[str, Any], run_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"tool_id": tool_id}
    if action in {"tool_validate", "tool_start"}:
        payload["parameters"] = dict(values)
    if action == "tool_cancel":
        payload["run_id"] = run_id
    return payload

# app/ui/pages/toolbox_widgets.py
class ToolParameterEditor(QWidget):
    values_changed = pyqtSignal(dict)

class ToolExecutionPanel(QWidget):
    open_result_requested = pyqtSignal(str)
```

Move `_mapping_list`, `_parameter_fields_and_values`, `_int_value`, `_float_value`, `_freeze_display`, `_phase`, `_action_enabled`, `_display_scalar`, `_append_unique`, and `_action_payload` into `toolbox_models.py` as pure functions. Move `_build_parameter_tab`, `_build_result_tab`, `_build_history_tab`, `_render_parameter_form`, `_clear_form`, `_build_parameter_editor`, `_render_lifecycle`, `_render_result`, `_render_recent`, and `_history_line` into `toolbox_widgets.py`; these functions may create or patch widgets but cannot load snapshots or emit host actions. Keep `ToolboxPage` responsible for construction, `render`/display-batch ingestion, current selection/form retention, and emitting exactly one `action_requested` signal. Delete the moved definitions from `toolbox_page.py` rather than retaining forwarding copies.

In `tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py`, instantiate the page once, keep object identities for the card grid and active editor, apply a progress-only projection, and assert both identities are unchanged. Emit `_emit_start()` and assert `action_requested` receives one `("tool_start", payload)` tuple while `tool_requested` receives no event.

- [ ] **Step 3: Extract browser contract and rendering modules**

```javascript
// toolbox_contract.js
window.UcpToolboxContract = Object.freeze({
  normalizeSnapshot,
  normalizeTool,
  validateParameters,
  buildActionPayload,
  actionEnabled,
});

// toolbox_view.js
window.UcpToolboxView = Object.freeze({
  renderCards,
  renderDetailShell,
  patchValidation,
  patchExecution,
  patchHistory,
  patchActions,
});
```

`toolbox_controller.js` retains only lifecycle state, dependency injection, action sequencing, BFCache-safe `configure`/`dispose`, and calls into the two modules.

Move functions `asRecord` through `shouldRender` (current lines 83–627) into `toolbox_contract.js`; this module may normalize plain values but must not reference `document`, `localStorage`, or `requestAction`. Move DOM helpers and rendering functions `byId`, `t`, `translateText`, `esc`, `escAttr`, `renderCards`, `overviewHtml`, `parameterControlHtml`, `parameterHtml`, `actionsHtml`, `detailHtml`, `patchValidationErrors`, `patchExecution`, `historyRowHtml`, `patchHistory`, `patchActions`, and `renderDynamic` into `toolbox_view.js`; every state value and callback is passed as an argument, and this module cannot call `requestAction`. Keep `configure`, `ingest`, selection/form state, `dispatch`, `validate`, `start`, `cancel`, `openResult`, `clearHistory`, and `dispose` in `toolbox_controller.js`; delete migrated functions from the controller.

In `tests/contract/frontend/test_toolbox.py`, load all three scripts in a Node VM and assert: `toolbox_contract.js` evaluates with no `document`; a progress-only `view.patchExecution` leaves the form node identity unchanged; one controller `start()` calls the injected `requestAction` exactly once; after `dispose()`, resolving the prior promise cannot render or mutate pending state.

- [ ] **Step 4: Register assets in canonical order**

Insert `"toolbox.css"` immediately before `"overlays_responsive.css"` in `CSS_LOAD_ORDER`. In `index.html`, load `toolbox_contract.js`, then `toolbox_view.js`, then `toolbox_controller.js`, then the composition root.

- [ ] **Step 5: Run focused GUI/browser and architecture tests**

Run: `python -m pytest tests/architecture/test_frontend_file_boundaries.py tests/architecture/test_file_size_limits.py tests/contract/frontend/test_toolbox.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py -q`

Expected: PASS; changing progress does not recreate Qt cards or replace the browser form DOM.

- [ ] **Step 6: Commit the responsibility split**

```bash
git add app/ui/pages/toolbox_models.py app/ui/pages/toolbox_widgets.py app/ui/pages/toolbox_page.py app/web/static/toolbox_contract.js app/web/static/toolbox_view.js app/web/static/toolbox_controller.js app/web/static/toolbox.css app/web/static/index.html tests/architecture/test_frontend_file_boundaries.py tests/architecture/test_file_size_limits.py tests/contract/frontend/test_toolbox.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py
git commit -m "refactor: split toolbox view responsibilities"
```

### Task 3: Declare Dynamic Tool Requirements and Host-Owned Provenance

**Files:**
- Modify: `app/core/tools/contracts.py`
- Modify: `app/core/tools/registry.py`
- Modify: `app/core/tools/builtin/download_residue.py`
- Modify: `app/core/tools/builtin/environment_diagnostics.py`
- Modify: `app/core/tools/builtin/media_health.py`
- Modify: `tests/unit/app/core/tools/test_contracts.py`
- Modify: `tests/unit/app/core/tools/test_registry.py`

**Interfaces:**
- Consumes: `shared.execution_profile.ExecutionProfile`, `local_execution_profile`, and `public_web_profile`; existing `ToolManifest`, `ToolContext`, and `ToolRegistry.get/list/manifests`.
- Produces: `ToolRequirements`, `ToolGrant`, `ToolGrantEvaluator.evaluate`, `ToolPlugin.requirements_for(parameters)`, `ToolDescriptor`, and provenance-aware registry lookup.

- [ ] **Step 1: Write failing host-grant, dynamic-requirement, and inert-discovery tests**

```python
def test_registry_defaults_to_builtins_without_executing_external_sources(tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    (tmp_path / "unsafe.py").write_text(f"open({str(marker)!r}, 'w').write('x')", encoding="utf-8")
    monkeypatch.setenv("UCRAWL_TOOL_PLUGIN_ROOT", str(tmp_path))
    registry = ToolRegistry()
    assert not marker.exists()
    assert all(row["provenance"] == "builtin" for row in registry.manifests())

def test_download_residue_requirements_change_with_requested_mode():
    diagnose = DOWNLOAD_RESIDUE_TOOL.requirements_for({"mode": "diagnose"})
    cleanup = DOWNLOAD_RESIDUE_TOOL.requirements_for({"mode": "cleanup"})
    assert diagnose == ToolRequirements(frozenset({"read_file"}), requires_approved_roots=True)
    assert cleanup == ToolRequirements(
        frozenset({"read_file", "write_file", "destructive"}),
        requires_approved_roots=True,
    )

def test_public_web_host_grant_cannot_be_widened_by_tool_parameters():
    profile = public_web_profile(owner_id="web:test", approved_roots=())
    requirements = ToolRequirements(frozenset({"read_file"}), requires_approved_roots=True)
    grant = ToolGrantEvaluator.evaluate(
        requirements=requirements,
        declared_permissions=frozenset({"read_file"}),
        provenance="builtin",
        execution_profile=profile,
    )
    assert grant.allowed is False
    assert grant.code == "tool_run_disabled"
```

Run: `python -m pytest tests/unit/app/core/tools/test_contracts.py tests/unit/app/core/tools/test_registry.py -q`

Expected: FAIL because environment-directory and entry-point Python is loaded by default, tools have no host-evaluated dynamic requirements, and the tool package has no provenance grant contract.

- [ ] **Step 2: Define requirement, grant, and descriptor contracts without redefining `ExecutionProfile`**

```python
@dataclass(frozen=True, slots=True)
class ToolRequirements:
    permissions: frozenset[str] = frozenset()
    requires_approved_roots: bool = False

@dataclass(frozen=True, slots=True)
class ToolGrant:
    allowed: bool
    code: str = ""
    message: str = ""

@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool: ToolPlugin
    provenance: str
```

Import `ExecutionProfile` from `shared.execution_profile`; do not declare profile constants or a second profile type under `app/core/tools`. `ToolContext` receives `execution_profile: ExecutionProfile` and `provenance: str`; its `owner_id` and approved-root accessors return `execution_profile.owner_id` and `execution_profile.approved_roots`. Registry manifest dictionaries receive host-generated `provenance`; plugin-authored `ToolManifest` cannot set it.

- [ ] **Step 3: Require every plugin to declare parameter-dependent requirements**

Extend `ToolPlugin` with `requirements_for(self, parameters: Mapping[str, Any]) -> ToolRequirements`. Registry coercion rejects an object missing this method. Define these exact built-in requirements:

```python
class DownloadResidueTool:
    def requirements_for(self, parameters: Mapping[str, Any]) -> ToolRequirements:
        mode = str(parameters.get("mode") or "diagnose").strip().lower()
        permissions = {"read_file"}
        if mode == "cleanup":
            permissions.update({"write_file", "destructive"})
        return ToolRequirements(frozenset(permissions), requires_approved_roots=True)

class EnvironmentDiagnosticsTool:
    def requirements_for(self, parameters: Mapping[str, Any]) -> ToolRequirements:
        return ToolRequirements(frozenset({"network", "process"}))

class MediaHealthTool:
    def requirements_for(self, parameters: Mapping[str, Any]) -> ToolRequirements:
        return ToolRequirements(frozenset({"read_file", "process"}), requires_approved_roots=True)
```

The download-residue manifest declares the maximum set `("read_file", "write_file", "destructive")`; diagnose is not over-granted because the host evaluates `requirements_for` against the actual normalized parameters before calling plugin validation.

- [ ] **Step 4: Make external discovery opt-in and provenance host-owned**

Set `ToolRegistry(..., include_entry_points=False, enable_external=False)` defaults. Do not read `UCRAWL_TOOL_PLUGIN_ROOT`, entry points, or an external directory until `enable_external=True` and the caller's `execution_profile.allow_external_plugins` are both true. Define `descriptor(tool_id: str) -> ToolDescriptor | None`; keep `get(tool_id)` as a compatibility wrapper returning `descriptor.tool`. Origins are fixed strings `builtin`, `explicit`, `entry_point:<distribution>`, or `external:<resolved path>` assigned only by registry code.

- [ ] **Step 5: Evaluate host grants before plugin code**

```python
class ToolGrantEvaluator:
    @staticmethod
    def evaluate(
        *,
        requirements: ToolRequirements,
        declared_permissions: frozenset[str],
        provenance: str,
        execution_profile: ExecutionProfile,
    ) -> ToolGrant:
        if not execution_profile.allow_tool_execution:
            return ToolGrant(False, "tool_run_disabled", "tool execution is disabled for this host")
        if not provenance.startswith("builtin") and not execution_profile.allow_external_plugins:
            return ToolGrant(False, "external_plugins_disabled", "external tools are disabled for this host")
        if not requirements.permissions <= declared_permissions:
            return ToolGrant(False, "undeclared_tool_permission", "tool requested an undeclared permission")
        if not requirements.permissions <= execution_profile.tool_permissions:
            return ToolGrant(False, "tool_permission_denied", "tool permissions are not granted")
        if requirements.requires_approved_roots and not execution_profile.approved_roots:
            return ToolGrant(False, "approved_roots_required", "at least one approved root is required")
        return ToolGrant(True)
```

`ToolRunnerService.validate` and `run` compute requirements and evaluate the grant before calling `tool.validate`. The request payload cannot supply `host_surface`, `owner_id`, credential policy, proxy policy, network policy, tool permissions, approved roots, or external-plugin permission.

- [ ] **Step 6: Verify dynamic grants and discovery**

Run: `python -m pytest tests/unit/app/core/tools/test_contracts.py tests/unit/app/core/tools/test_registry.py tests/release/packaging/test_release_tool_runner.py -q`

Expected: PASS; listing built-ins never imports user-directory or entry-point code, diagnose is allowed by a read-only local grant, cleanup is denied without `write_file` plus `destructive`, and denied tools have zero validation/run calls.

- [ ] **Step 7: Commit requirement and provenance contracts**

```bash
git add app/core/tools/contracts.py app/core/tools/registry.py app/core/tools/builtin/download_residue.py app/core/tools/builtin/environment_diagnostics.py app/core/tools/builtin/media_health.py tests/unit/app/core/tools/test_contracts.py tests/unit/app/core/tools/test_registry.py
git commit -m "feat: evaluate host-owned tool grants"
```

### Task 4: Enforce Permissions, Approved Roots, and Positive Public Projection

**Files:**
- Create: `app/services/tool_history_projection.py`
- Modify: `app/core/tools/contracts.py`
- Modify: `app/services/tool_runner_service.py`
- Modify: `tests/unit/app/core/tools/test_contracts.py`
- Modify: `tests/unit/app/services/test_tool_runner_service.py`

**Interfaces:**
- Consumes: `shared.execution_profile.ExecutionProfile`, `ToolRequirements`, `ToolGrantEvaluator`, `ToolDescriptor.provenance`, and `ToolContext.authorize_path`.
- Produces: profile-bound contexts, `project_history_record(record)`, and fail-closed validation/run responses.

- [ ] **Step 1: Write failing authorization and recursive projection tests**

```python
def test_path_authorization_rejects_empty_roots(tmp_path):
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:path",
        approved_roots=(),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    context = ToolContext(parameters={}, execution_profile=profile, provenance="builtin")
    with pytest.raises(PermissionError, match="approved root"):
        context.authorize_path(tmp_path / "video.mp4")

def test_history_projection_drops_nested_unknown_and_secret_fields():
    raw = {
        "run_id": "run-1", "tool_id": "media_health", "status": "failed",
        "parameters": {"cookie": "secret"},
        "progress_details": {"phase": "probe", "headers": {"Authorization": "secret"}},
        "result": {"status": "failed", "message": "safe", "data": {"token": "secret"}},
    }
    assert project_history_record(raw) == {
        "run_id": "run-1", "tool_id": "media_health", "status": "failed",
        "result": {"status": "failed", "message": "safe"},
    }
```

In the same test module, define a counting tool whose `requirements_for` returns `ToolRequirements(frozenset({"write_file"}))`; assert a profile with only `read_file` receives `status == "forbidden"`, `code == "tool_permission_denied"`, and both `validate_calls` and `run_calls` stay zero. Register it with `origin="external:test"`, use a profile with `allow_external_plugins=False`, and assert `code == "external_plugins_disabled"` with the counters still zero.

Run: `python -m pytest tests/unit/app/core/tools/test_contracts.py tests/unit/app/services/test_tool_runner_service.py -q`

Expected: FAIL because empty roots are fail-open, manifest policy is declarative only, and redaction only examines top-level parameter names.

- [ ] **Step 2: Make path authorization fail closed**

```python
def authorize_path(self, path: str | os.PathLike[str]) -> Path:
    resolved = Path(path).expanduser().resolve()
    roots = tuple(Path(root).expanduser().resolve() for root in self.execution_profile.approved_roots if str(root).strip())
    if not roots:
        raise PermissionError("at least one approved root is required")
    if not any(_is_relative_to(resolved, root) for root in roots):
        raise PermissionError("path is outside approved roots")
    return resolved
```

Retain an injected `path_authorizer`, but require its returned path to remain inside the normalized non-empty host roots. Do not accept roots as a `validate` or `run` argument.

- [ ] **Step 3: Bind every runner operation to the shared host profile**

```python
def validate(
    self,
    tool_id: str,
    params: Mapping[str, Any] | None,
    *,
    execution_profile: ExecutionProfile,
) -> dict[str, Any]:
    descriptor = self.registry.descriptor(tool_id)
    requirements = descriptor.tool.requirements_for(dict(params or {}))
    grant = ToolGrantEvaluator.evaluate(
        requirements=requirements,
        declared_permissions=frozenset(descriptor.tool.manifest.permissions),
        provenance=descriptor.provenance,
        execution_profile=execution_profile,
    )
    if not grant.allowed:
        return {"status": "forbidden", "code": grant.code, "message": grant.message}
    return self._validate_granted(descriptor, dict(params or {}), execution_profile)
```

`run` repeats evaluation after validation normalization and before allocating a record, so a validator cannot change `mode=diagnose` into `mode=cleanup` without triggering the stronger requirements. It stores `host_surface=execution_profile.host_surface` and `owner_id=execution_profile.owner_id` on the record; credential, proxy, network, permission, and root grants are never copied into public state.

- [ ] **Step 4: Persist only a fixed recursive positive schema**

Define `project_history_record` with explicit keys at each level: run fields `run_id`, `tool_id`, `host_surface`, `owner_id`, `status`, `created_at`, `started_at`, `finished_at`, `progress`, and `message`; result fields `status`, `message`, and scalar `warnings`. The function constructs a new dictionary and recursively accepts only `str`, `int`, `float`, `bool`, `None`, and lists of those scalars for warnings. It never copies `parameters`, `progress_details`, `data`, `output_paths`, arbitrary mappings, or plugin-defined keys. Use this projection for the disk snapshot, public Web events, and history API.

- [ ] **Step 5: Verify policy and leakage regressions**

Run: `python -m pytest tests/unit/app/core/tools/test_contracts.py tests/unit/app/services/test_tool_runner_service.py tests/contract/python/test_tools_api.py -q`

Expected: PASS; denied plugins have zero `validate`/`run` calls and the history file contains none of the injected secret sentinel strings.

- [ ] **Step 6: Commit authorization and projection**

```bash
git add app/core/tools/contracts.py app/services/tool_history_projection.py app/services/tool_runner_service.py tests/unit/app/core/tools/test_contracts.py tests/unit/app/services/test_tool_runner_service.py
git commit -m "fix: enforce tool permissions and safe history projection"
```

### Task 5: Bound Admission, Scope Runs by Owner, and Make History/Shutdown Deterministic

**Files:**
- Modify: `app/services/tool_runner_service.py`
- Modify: `tests/unit/app/services/test_tool_runner_service.py`

**Interfaces:**
- Consumes: `ToolRunnerService.run`, `cancel`, `history`, `get_run`, `clear_history`, `wait_for_idle`, and `shutdown`.
- Produces: profile-bound operations, `wait_for_run(run_id, execution_profile, timeout)`, global/per-owner_id admission bounds, chronological persistence, and terminal queued cancellation.

- [ ] **Step 1: Write failing concurrency, ownership, load-order, and shutdown tests**

```python
def test_admission_is_bounded_per_owner_and_globally(blocking_tool, tmp_path):
    service = ToolRunnerService(_registry(blocking_tool), history_path=tmp_path / "h.json", max_pending=2, max_pending_per_owner=1)
    permissions = ("read_file", "write_file", "network", "process", "destructive")
    gui = local_execution_profile(host_surface="desktop_gui", owner_id="gui:1", approved_roots=(), tool_permissions=permissions, allow_external_plugins=False)
    sdk = local_execution_profile(host_surface="sdk", owner_id="sdk:1", approved_roots=(), tool_permissions=permissions, allow_external_plugins=False)
    cli = local_execution_profile(host_surface="cli", owner_id="cli:1", approved_roots=(), tool_permissions=permissions, allow_external_plugins=False)
    first = service.run("blocking", {}, execution_profile=gui)
    assert service.run("blocking", {}, execution_profile=gui)["status"] == "busy"
    assert service.run("blocking", {}, execution_profile=sdk)["status"] == "queued"
    assert service.run("blocking", {}, execution_profile=cli)["status"] == "busy"

def test_owner_cannot_read_or_cancel_another_owners_run(blocking_tool, tmp_path):
    service = ToolRunnerService(_registry(blocking_tool), history_path=tmp_path / "h.json")
    gui = local_execution_profile(host_surface="desktop_gui", owner_id="gui:1", approved_roots=(), tool_permissions=(), allow_external_plugins=False)
    other = local_execution_profile(host_surface="desktop_gui", owner_id="gui:2", approved_roots=(), tool_permissions=(), allow_external_plugins=False)
    row = service.run("blocking", {}, execution_profile=gui)
    assert service.get_run(row["run_id"], execution_profile=other) is None
    assert service.cancel(row["run_id"], execution_profile=other)["status"] == "forbidden"

def test_loaded_history_is_newest_first_at_api_boundary(tmp_path):
    path = tmp_path / "h.json"
    path.write_text(json.dumps([_terminal_row("old", 1.0), _terminal_row("new", 2.0)]), encoding="utf-8")
    service = ToolRunnerService(_registry(), history_path=path)
    gui = local_execution_profile(host_surface="desktop_gui", owner_id="gui", approved_roots=(), tool_permissions=(), allow_external_plugins=False)
    assert [row["run_id"] for row in service.history(execution_profile=gui)] == ["new", "old"]

def test_shutdown_marks_queued_future_cancelled_and_flushes_history(blocking_tool, tmp_path):
    path = tmp_path / "h.json"
    profile = local_execution_profile(host_surface="test", owner_id="unit:shutdown", approved_roots=(), tool_permissions=(), allow_external_plugins=False)
    service = ToolRunnerService(_registry(blocking_tool), history_path=path, max_workers=1)
    service.run("blocking", {"slot": 1}, execution_profile=profile)
    queued = service.run("blocking", {"slot": 2}, execution_profile=profile)
    service.shutdown(wait=False)
    persisted = {row["run_id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}
    assert persisted[queued["run_id"]]["status"] == "cancelled"
    assert persisted[queued["run_id"]]["finished_at"] is not None
```

Run: `python -m pytest tests/unit/app/services/test_tool_runner_service.py -q`

Expected: FAIL because submission is unbounded, owner_id is absent, loaded order is reversed by repeated `insert(0, ...)`, and queued futures can disappear without terminal records.

- [ ] **Step 2: Define exact profile-bound operation signatures**

```python
def run(self, tool_id: str, params: Mapping[str, Any] | None, *, execution_profile: ExecutionProfile) -> dict[str, Any]:
def cancel(self, run_id: str, *, execution_profile: ExecutionProfile) -> dict[str, Any]:
def get_run(self, run_id: str, *, execution_profile: ExecutionProfile) -> dict[str, Any] | None:
def history(self, *, execution_profile: ExecutionProfile, tool_id: str | None = None, status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
def wait_for_run(self, run_id: str, *, execution_profile: ExecutionProfile, timeout: float | None = None) -> dict[str, Any]:
```

Set constructor defaults `max_pending=32` and `max_pending_per_owner=8`. Reject a profile with blank `host_surface` or `owner_id`. Derive host identity, permissions, and roots exclusively from the profile. Count `_futures` globally and records matching `execution_profile.owner_id` while holding `_lock`; return `{ "status": "busy", "code": "tool_capacity_reached", "message": "tool runner capacity reached" }` before recording or submitting excess work. `wait_for_run` returns the terminal public row or `{ "status": "timeout", "run_id": run_id }` after its deadline.

- [ ] **Step 3: Load and merge history before serving operations**

Wait on `_history_loaded` in `history`, `run`, and `clear_history`. Load the on-disk oldest-to-newest list with `append`, merge by `run_id`, sort by `(created_at, run_id)`, and trim only terminal oldest records. API history reverses that stable list once.

- [ ] **Step 4: Finalize every queued future during cancellation and shutdown**

Factor `_mark_cancelled_locked(run_id, message)` so both `cancel` and `shutdown` set `status=CANCELLED`, `finished_at`, `result`, remove token/future, emit one terminal event, and schedule persistence. On shutdown: set closed, cancel tokens, call `future.cancel()` for queued work, mark successfully cancelled futures terminal, shut down worker executor, wait for running work only when requested, persist synchronously, then shut down the I/O executor.

- [ ] **Step 5: Run race-focused tests repeatedly**

Run: `python -m pytest tests/unit/app/services/test_tool_runner_service.py -q --count=10`

If `pytest-repeat` is unavailable, run: `1..10 | ForEach-Object { python -m pytest tests/unit/app/services/test_tool_runner_service.py -q; if ($LASTEXITCODE) { exit $LASTEXITCODE } }`

Expected: all ten runs PASS with no leaked `tool-runner` or `tool-history` threads.

- [ ] **Step 6: Commit bounded owner_id-aware execution**

```bash
git add app/services/tool_runner_service.py tests/unit/app/services/test_tool_runner_service.py
git commit -m "fix: bound and isolate tool runner jobs"
```

### Task 6: Prevent Download-Residue Cleanup from Touching Active Recovery State

**Files:**
- Modify: `app/core/tools/builtin/download_residue.py`
- Modify: `tests/integration/app/core/tools/test_download_residue_tool.py`

**Interfaces:**
- Consumes: `_LedgerSnapshot.records`, where `state == "active"` represents `download_task_paths`.
- Produces: `_active_save_roots(ledger)`, protected artifact filtering, and cleanup that mutates only stale pending-cleanup/frontier rows.

- [ ] **Step 1: Write failing dynamic-grant, active-ledger, and workspace tests**

```python
def test_read_only_host_grant_allows_diagnose_but_denies_cleanup(tmp_path):
    artifact = tmp_path / ".hls_workspace"
    artifact.mkdir()
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:residue",
        approved_roots=(tmp_path,),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    service = ToolRunnerService(ToolRegistry([DOWNLOAD_RESIDUE_TOOL]), history_path=tmp_path / "history.json")
    assert service.validate("download_residue", {"mode": "diagnose"}, execution_profile=profile)["status"] == "ok"
    denied = service.run("download_residue", {"mode": "cleanup"}, execution_profile=profile)
    assert denied["status"] == "forbidden"
    assert denied["code"] == "tool_permission_denied"
    assert artifact.is_dir()

def test_cleanup_never_deletes_active_ledger_row_or_active_workspace(tmp_path, tool):
    active_root = tmp_path / "downloads" / "video-a"
    workspace = active_root / ".hls_workspace"
    workspace.mkdir(parents=True)
    ledger = _create_recovery_ledger(tmp_path, active=[("video-a", str(active_root), "gen-1")])
    result = tool.run(_context(tmp_path, mode="cleanup", ledger_path=ledger))
    assert workspace.is_dir()
    assert _active_rows(ledger) == [("video-a", str(active_root), "gen-1")]
    assert str(workspace) in _data(result)["protected"]

def test_cleanup_does_not_consume_unrelated_active_row(tmp_path, tool):
    active_root = tmp_path / "active"
    stale_root = tmp_path / "stale"
    artifact = stale_root / ".hls_workspace"
    artifact.mkdir(parents=True)
    ledger = _create_recovery_ledger(tmp_path, active=[("video-a", str(active_root), "gen-1")])
    result = tool.run(_context(stale_root, mode="cleanup", ledger_path=ledger))
    assert _status(result) == "succeeded"
    assert not artifact.exists()
    assert _active_rows(ledger) == [("video-a", str(active_root), "gen-1")]
```

Run: `python -m pytest tests/integration/app/core/tools/test_download_residue_tool.py -q`

Expected: FAIL because `_consume_matching_ledger_records` deletes matching `download_task_paths` rows and the artifact scan does not exclude active save directories.

- [ ] **Step 2: Fail closed around every active save directory**

```python
def _active_save_roots(ledger: _LedgerSnapshot) -> tuple[Path, ...]:
    return tuple(
        Path(record.save_directory).expanduser().resolve(strict=False)
        for record in ledger.records
        if record.state == "active"
    )

def _is_protected_artifact(path: Path, active_roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve(strict=False)
    return any(_within(resolved, root) or _within(root, resolved) for root in active_roots)
```

Read the ledger before selecting cleanup candidates. Exclude every candidate that is inside, equal to, or an ancestor of an active save root. Return protected paths in diagnostic data without renaming them.

- [ ] **Step 3: Remove active-row deletion from ledger cleanup**

Delete the `record.state == "active"` branch from `_consume_matching_ledger_records`. The function may compare-and-delete matching `pending_cleanup_directories` and `legacy_sweep_frontier` rows only. If the ledger changes between scan and commit, roll back staged stale artifacts exactly as today.

- [ ] **Step 4: Verify cancellation, rollback, and active protection together**

Run: `python -m pytest tests/integration/app/core/tools/test_download_residue_tool.py -q`

Expected: PASS for read-only diagnose, host denial of cleanup under a read-only grant, cleanup under a profile granted `read_file`, `write_file`, and `destructive`, symlink rejection, generation race rollback, cancellation rollback, stale cleanup, and active protection.

- [ ] **Step 5: Commit recovery-safe residue cleanup**

```bash
git add app/core/tools/builtin/download_residue.py tests/integration/app/core/tools/test_download_residue_tool.py
git commit -m "fix: preserve active recovery workspaces during cleanup"
```

### Task 7: Give CLI and SDK Truthful Synchronous Lifecycles

**Files:**
- Modify: `ucrawl/tools.py`
- Modify: `shared/sdk_runtime.py`
- Modify: `cli/commands/tools.py`
- Modify: `tests/contract/python/test_tools_api.py`
- Modify: `tests/contract/cli/test_tools_command.py`
- Modify: `tests/unit/shared/test_sdk_runtime.py`

**Interfaces:**
- Consumes: profile-bound `ToolRunnerService.run`, `wait_for_run`, `cancel`, and `shutdown`.
- Produces: `ToolsAPI(execution_profile)`, `run_sync`, `close`, context manager support, and CLI Ctrl+C cancellation in the same process.

- [ ] **Step 1: Write failing CLI completion and close-propagation tests**

```python
def test_cli_run_waits_for_terminal_result_and_closes_service(capsys):
    service = RecordingToolRunnerService(final={"status": "succeeded", "run_id": "run-1"})
    assert handle_tools_command(_run_args(), api_factory=lambda: ToolsAPI(service)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"
    assert service.waited[0][0] == "run-1"
    assert service.waited[0][1].host_surface == "cli"
    assert service.waited[0][1].owner_id.startswith("cli:")
    assert service.shutdown_calls == 1

def test_sdk_close_shuts_down_cached_tools_api():
    sdk = UcrawlSDK()
    api = Mock()
    sdk._tools_api = api
    sdk.close()
    api.close.assert_called_once_with()
```

```python
def test_cli_interrupt_cancels_the_same_process_owned_run(api):
    api.wait_for_run.side_effect = KeyboardInterrupt
    assert handle_tools_command(_run_args(), api_factory=lambda: api) == int(CliExitCode.CANCELLED)
    api.cancel.assert_called_once_with("run-1")
    api.close.assert_called_once_with()

def test_standalone_cancel_reports_process_scope(capsys):
    assert handle_tools_command(_cancel_args("run-1")) == int(CliExitCode.USAGE)
    assert "cancellation is process-scoped" in capsys.readouterr().err
```

Run: `python -m pytest tests/contract/cli/test_tools_command.py tests/contract/python/test_tools_api.py tests/unit/shared/test_sdk_runtime.py -q`

Expected: FAIL because CLI prints the queued record, service ownership is implicit, and neither `ToolsAPI` nor `UcrawlSDK.close()` owns runner shutdown.

- [ ] **Step 2: Extend the SDK facade with lifecycle methods**

```python
class ToolsAPI:
    def run_sync(self, tool_id: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        queued = self.run(tool_id, params)
        if queued.get("status") != "queued":
            return queued
        return self._get_service().wait_for_run(
            queued["run_id"],
            execution_profile=self._execution_profile,
            timeout=timeout,
        )

    def close(self) -> None:
        service, self._service = self._service, None
        if service is not None:
            service.shutdown(wait=True)

    def __enter__(self) -> "ToolsAPI":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
```

Extend `ToolRunnerServiceContract` with profile-bound `run`, `wait_for_run`, `cancel`, `history`, and `shutdown(wait=True)` signatures. `ToolsAPI.__init__` requires an `execution_profile`; `UcrawlSDK.tools` calls `local_execution_profile(host_surface="sdk", owner_id=f"sdk:{uuid.uuid4().hex}", approved_roots=(Path(self.save_dir),), tool_permissions=("read_file", "write_file", "network", "process", "destructive"), allow_external_plugins=False)`. Make `close()` idempotent; when the lazy service exists, detach it and call `shutdown(wait=True)` once.

- [ ] **Step 3: Make CLI run synchronous and cancellation process-scoped**

Construct `ToolsAPI(execution_profile=local_execution_profile(host_surface="cli", owner_id=f"cli:{os.getpid()}", approved_roots=(Path(get_default_save_dir()),), tool_permissions=("read_file", "write_file", "network", "process", "destructive"), allow_external_plugins=False))` in a `with` block. `tools run` calls `run`, then `wait_for_run`; on `KeyboardInterrupt`, call `cancel` on that same API and wait briefly for a terminal cancelled record. Retain `tools cancel` only as a compatibility error returning `CliExitCode.USAGE` with `tool cancellation is process-scoped; interrupt the active tools run command`.

- [ ] **Step 4: Close cached SDK tools**

In `UcrawlSDK.close()`, atomically detach `_tools_api`, call `close()` once when present, and remain safe on repeated SDK close and context-manager exit.

- [ ] **Step 5: Run CLI/SDK contract regressions**

Run: `python -m pytest tests/contract/cli/test_tools_command.py tests/contract/python/test_tools_api.py tests/unit/shared/test_sdk_runtime.py tests/contract/cross_interface/test_cli_sdk_api.py -q`

Expected: PASS; CLI emits one terminal JSON document and the process exits with no tool executor threads.

- [ ] **Step 6: Commit lifecycle semantics**

```bash
git add ucrawl/tools.py shared/sdk_runtime.py cli/commands/tools.py tests/contract/python/test_tools_api.py tests/contract/cli/test_tools_command.py tests/unit/shared/test_sdk_runtime.py
git commit -m "fix: make tool CLI and SDK lifecycles explicit"
```

### Task 8: Connect Real Tool Actions to GUI and Safe Denials to Public WebUI

**Files:**
- Create: `app/services/frontend_tool_runtime.py`
- Modify: `app/services/frontend_toolbox_adapter.py`
- Modify: `app/services/frontend_state_service.py`
- Modify: `app/ui/layout/app_shell.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/web/controller.py`
- Modify: `app/web/static/toolbox_contract.js`
- Modify: `app/web/static/toolbox_controller.js`
- Modify: `tests/unit/app/services/test_frontend_state_service.py`
- Modify: `tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py`
- Modify: `tests/unit/app/ui/test_main_window.py`
- Modify: `tests/contract/frontend/test_toolbox.py`
- Modify: `tests/contract/web/test_fastapi_endpoints.py`

**Interfaces:**
- Consumes: `ToolRunnerService.snapshot`, shared-profile-bound actions, runner events, `ToolboxPage.action_requested`, and browser `requestAction`.
- Produces: `FrontendToolRuntime.snapshot()`, `handle_action(action, payload)`, six real frontend action names, and public Web execution denial without invoking plugin code.

- [ ] **Step 1: Write failing GUI single-dispatch and public-Web denial tests**

```python
def test_gui_start_dispatches_once_to_real_runner(qtbot, fake_tool_runtime):
    window = MainWindow(tool_runtime=fake_tool_runtime)
    window.app_shell.pages["toolbox"].action_requested.emit("tool_start", {"tool_id": "media_health", "parameters": {"path": "x.mp4"}})
    assert fake_tool_runtime.calls == [("tool_start", {"tool_id": "media_health", "parameters": {"path": "x.mp4"}})]

def test_public_web_start_is_denied_without_running_plugin(fake_tool):
    profile = public_web_profile(owner_id="web:session-1", approved_roots=())
    service = FrontendStateService(execution_profile=profile, tool_registry=_registry(fake_tool))
    result = service.handle_action("tool_start", {"tool_id": fake_tool.manifest.id, "parameters": {}})
    assert result["status"] == "forbidden"
    assert fake_tool.run_calls == 0
```

In `test_frontend_state_service.py`, assert forged `tool_start`, `tool_cancel`, `tool_open_result`, and `tool_clear_history` under the public profile each return `status == "forbidden"`; assert a second Web owner_id cannot see the first owner_id's run in snapshot/delta output. In `test_toolbox_page_lifecycle.py`, assert `_emit_start()` emits one `action_requested` event and zero `tool_requested` events. In `test_toolbox.py`, assert the public projection disables start/cancel/open/clear while client-side schema validation remains available.

Run: `python -m pytest tests/unit/app/services/test_frontend_state_service.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py tests/unit/app/ui/test_main_window.py tests/contract/frontend/test_toolbox.py tests/contract/web/test_fastapi_endpoints.py -q`

Expected: FAIL because current frontend state returns a synthetic `tool queued`, AppShell connects only the legacy signal, GUI emits both signals, and Web actions are not backed by the runner/profile.

- [ ] **Step 2: Create the profile-bound frontend runtime adapter**

```python
class FrontendToolRuntime:
    ACTIONS = frozenset({
        "tool_validate", "tool_start", "tool_cancel",
        "tool_open_result", "tool_clear_history", "tool_reload",
    })

    def handle_action(self, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if action not in self.ACTIONS:
            return {"status": "error", "message": "unknown toolbox action"}
        return self._handlers[action](payload)

    def snapshot(self) -> dict[str, Any]:
        profile = self._execution_profile_provider()
        return build_toolbox_snapshot(
            self._runner.list(),
            self._runner.history(execution_profile=profile, limit=20),
            execution_profile=profile,
        )

    def shutdown(self) -> None:
        self._runner.shutdown(wait=True)
```

The constructor signature is `FrontendToolRuntime(runner: ToolRunnerService, *, execution_profile_provider: Callable[[], ExecutionProfile], emit: Callable[[str, Mapping[str, Any]], None], open_result: Callable[[Path], None])`. It builds `_handlers` for every name in `ACTIONS`; each handler calls the provider and passes that host-owned profile rather than accepting profile fields from the frontend payload. The adapter owns runner callbacks, maps them to `toolbox_items`, `toolbox_recent_items`, `toolbox_display_projection`, and emits `tools.*` changes. `tool_open_result` resolves the path through a `ToolContext` bound to the current profile before calling `open_result`.

- [ ] **Step 3: Replace static/synthetic frontend state with the adapter**

Inject `FrontendToolRuntime` into `FrontendStateService`. Route all six action names through it, include its snapshot in full/delta state, and shut it down from `FrontendStateService.destroy()`. Keep `frontend_toolbox_adapter.py` as pure manifest/run-to-display conversion; remove its static fake history and use service data.

- [ ] **Step 4: Wire GUI only through `action_requested`**

Expose `AppShell.tool_action_requested = pyqtSignal(str, dict)`, connect `ToolboxPage.action_requested` to it, and connect MainWindow once to `_submit_frontend_action(action, payload)`. Stop emitting or subscribing to `tool_requested` for modern toolbox actions; if the legacy signal must remain for compatibility, never emit it from `_emit_start`.

Construct the GUI provider with `local_execution_profile(host_surface="desktop_gui", owner_id=f"gui:{os.getpid()}", approved_roots=(Path(current_download_directory),), tool_permissions=("read_file", "write_file", "network", "process", "destructive"), allow_external_plugins=False)`; keep the owner_id stable for the process while recomputing the current root per action. Render runner deltas through the normal frontend state refresh path; never mutate widgets from runner threads.

- [ ] **Step 5: Give WebUI a real but execution-disabled profile**

Construct each Web session provider with `public_web_profile(owner_id=f"web:{session_id}", approved_roots=())`. Return real built-in manifests and safe owner_id history, but project `tool_start`, `tool_cancel`, `tool_open_result`, `tool_clear_history`, and `tool_reload` as disabled. A direct forged request receives `{ "status": "forbidden", "code": "tool_run_disabled", "message": "tool execution is disabled for this host" }` before plugin validation or execution. Browser schema validation remains client-side; `tool_validate` never calls a plugin validator under this profile.

- [ ] **Step 6: Verify GUI/Web state-machine closure**

Run: `python -m pytest tests/unit/app/services/test_frontend_state_service.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py tests/unit/app/ui/test_main_window.py tests/contract/frontend/test_toolbox.py tests/contract/web/test_fastapi_endpoints.py -q`

Expected: PASS; GUI transitions `idle → validating → ready → starting → running → terminal`, public Web remains inspectable but disabled, and neither host duplicates a start request.

- [ ] **Step 7: Commit frontend integration**

```bash
git add app/services/frontend_tool_runtime.py app/services/frontend_toolbox_adapter.py app/services/frontend_state_service.py app/ui/layout/app_shell.py app/ui/main_window.py app/web/controller.py app/web/static/toolbox_contract.js app/web/static/toolbox_controller.js tests/unit/app/services/test_frontend_state_service.py tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py tests/unit/app/ui/test_main_window.py tests/contract/frontend/test_toolbox.py tests/contract/web/test_fastapi_endpoints.py
git commit -m "feat: connect toolbox actions with safe frontend profiles"
```

### Task 9: Run the Complete Tool Runtime Acceptance Gate

**Files:**
- Test: all canonical toolbox tests plus architecture, packaging, CLI, SDK, GUI, and Web contracts

**Interfaces:**
- Consumes: every interface produced by Tasks 1–8.
- Produces: one verified, push-ready toolbox batch with no out-of-suite tests, unbounded work, cross-owner_id state, or public-Web execution.

- [ ] **Step 1: Run static and architecture checks**

Run: `python -m compileall app/core/tools app/services/tool_runner_service.py app/services/tool_history_projection.py app/services/frontend_tool_runtime.py app/ui/pages/toolbox_page.py app/ui/pages/toolbox_models.py app/ui/pages/toolbox_widgets.py ucrawl/tools.py cli/commands/tools.py`

Run: `python -m ruff check app/core/tools app/services/tool_runner_service.py app/services/tool_history_projection.py app/services/frontend_tool_runtime.py app/services/frontend_toolbox_adapter.py app/ui/pages/toolbox_page.py app/ui/pages/toolbox_models.py app/ui/pages/toolbox_widgets.py ucrawl/tools.py cli/commands/tools.py tests/unit/app/core/tools tests/unit/app/services/test_tool_runner_service.py tests/integration/app/core/tools tests/contract/cli/test_tools_command.py tests/contract/python/test_tools_api.py tests/contract/frontend/test_toolbox.py`

Run: `python -m pytest tests/architecture -q`

Expected: all commands exit 0.

- [ ] **Step 2: Run focused Python behavior suites**

Run: `python -m pytest tests/unit/app/core/tools tests/unit/app/services/test_tool_runner_service.py tests/integration/app/core/tools tests/contract/cli/test_tools_command.py tests/contract/python/test_tools_api.py tests/unit/shared/test_sdk_runtime.py -q`

Expected: PASS with no pending executor thread warnings.

- [ ] **Step 3: Run GUI and Web contract suites**

Run: `python -m pytest tests/unit/app/ui/pages/test_toolbox_page_lifecycle.py tests/unit/app/ui/test_main_window.py tests/unit/app/services/test_frontend_state_service.py tests/contract/frontend/test_toolbox.py tests/contract/web/test_fastapi_endpoints.py -q`

Run: `node --check app/web/static/toolbox_contract.js; node --check app/web/static/toolbox_view.js; node --check app/web/static/toolbox_controller.js`

Expected: all commands exit 0.

- [ ] **Step 4: Run release/packaging regression**

Run: `python -m pytest tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_assets.py tests/release/ci/test_workflow.py -q`

Expected: PASS and packaged assets include all toolbox Python, CSS, and JavaScript modules.

- [ ] **Step 5: Run the full non-browser gate**

Run: `python -m pytest tests/unit tests/integration tests/contract tests/architecture tests/performance tests/release tests/testkit -q`

Expected: PASS with the repository coverage floor preserved.

- [ ] **Step 6: Push the completed batch only after every gate is green**

```bash
git status --short
git log --oneline --decorate -9
git push origin main
```

Expected: only the reviewed toolbox commits are pushed; unrelated working-tree changes remain unstaged.
