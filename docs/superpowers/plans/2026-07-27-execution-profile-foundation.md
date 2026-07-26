# Execution Profile Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the repository's single host-owned execution-capability contract before any tool-runtime or public-network implementation begins.

**Architecture:** `shared/execution_profile.py` owns the immutable profile, its two factories, monotonic restriction, and recursive payload-escalation rejection. Host code creates profiles from authenticated owner and approved-root state; downstream adapters consume a required profile and may only reduce its capabilities, never rebuild or widen it from request payloads.

**Tech Stack:** Python 3.10-3.13, dataclasses, pathlib, typing, FastAPI, pytest.

## Global Constraints

- This entire plan is the first code batch and must pass and be pushed before either `2026-07-27-tool-runtime-hardening.md` or `2026-07-27-public-network-boundary.md` is implemented.
- `shared/execution_profile.py` is the only production module allowed to define `ExecutionProfile` or its factories.
- Every profile has an explicit host surface and non-empty owner ID; there is no implicit trusted default.
- Payloads are data, never authority: no REST, WebSocket, CLI-config, SDK-config, plugin, or tool payload may set or widen profile fields.
- Restriction is monotonic: booleans can change only from allowed to denied, tool permissions and approved roots can only become subsets, and owner/surface never change.
- Normalize approved roots with `Path.resolve()` at factory time; an empty public root set remains empty and is fail closed.
- Do not add a runtime dependency.

---

## File Structure

- Create `shared/execution_profile.py`: sole model, factories, restriction API, and recursive payload-authority validator.
- Modify `shared/runtime_options.py`: require a host-created profile when reading credentials, accepting proxies, or enforcing public-network policy.
- Modify `shared/cli_runner_runtime.py`: store and pass the required profile without reconstructing it from config.
- Modify `shared/runtime_adapters.py`: make `execution_profile` a required argument to shared search execution.
- Modify `app/web/search_service.py`: create a session-owned public profile and reject payload authority fields before executor scheduling.
- Modify `app/web/workflows.py`: consume the same session-owned profile for crawl/download config merging.
- Modify `app/web/server.py`: inject the public-profile factory into Web composition without a global mutable profile.
- Test `tests/unit/shared/test_execution_profile.py`: model, factories, monotonic restriction, root normalization, and payload escalation.
- Test `tests/contract/web/test_security_hardening.py`: host ownership and pre-executor rejection.

### Task 1: Define the sole immutable execution-capability model

**Files:**
- Create: `shared/execution_profile.py`
- Test: `tests/unit/shared/test_execution_profile.py`

**Interfaces:**
- Produces: `HostSurface = Literal["desktop_gui", "public_web", "cli", "sdk", "test"]`.
- Produces: `ExecutionProfile(host_surface: HostSurface, owner_id: str, allow_machine_credentials: bool, allow_caller_proxy: bool, require_public_network: bool, allow_tool_execution: bool, tool_permissions: frozenset[str], approved_roots: frozenset[Path], allow_external_plugins: bool)`.
- Produces: `public_web_profile(*, owner_id: str, approved_roots: Iterable[Path]) -> ExecutionProfile`.
- Produces: `local_execution_profile(*, host_surface: Literal["desktop_gui", "cli", "sdk", "test"], owner_id: str, approved_roots: Iterable[Path], tool_permissions: Iterable[str], allow_external_plugins: bool) -> ExecutionProfile`.
- Produces: `ExecutionProfile.restrict(*, allow_machine_credentials: bool | None = None, allow_caller_proxy: bool | None = None, require_public_network: bool | None = None, allow_tool_execution: bool | None = None, tool_permissions: Iterable[str] | None = None, approved_roots: Iterable[Path] | None = None, allow_external_plugins: bool | None = None) -> ExecutionProfile`.

- [ ] **Step 1: Write failing model and factory tests**

```python
def test_public_factory_is_session_owned_and_fail_closed(tmp_path):
    root = tmp_path / "downloads"
    profile = public_web_profile(owner_id="session-a", approved_roots=(root,))
    assert profile.host_surface == "public_web"
    assert profile.owner_id == "session-a"
    assert not profile.allow_machine_credentials
    assert not profile.allow_caller_proxy
    assert profile.require_public_network
    assert not profile.allow_tool_execution
    assert profile.tool_permissions == frozenset()
    assert profile.approved_roots == frozenset({root.resolve()})
    assert not profile.allow_external_plugins

def test_local_factory_requires_real_owner_and_surface(tmp_path):
    profile = local_execution_profile(
        host_surface="cli",
        owner_id="pid-123",
        approved_roots=(tmp_path,),
        tool_permissions=("diagnose", "read"),
        allow_external_plugins=False,
    )
    assert profile.host_surface == "cli"
    assert profile.owner_id == "pid-123"
    assert profile.allow_machine_credentials
    assert profile.allow_caller_proxy
    assert not profile.require_public_network
    assert profile.allow_tool_execution
    assert profile.tool_permissions == frozenset({"diagnose", "read"})
    assert profile.approved_roots == frozenset({tmp_path.resolve()})

@pytest.mark.parametrize("owner_id", ["", " ", "\t"])
def test_factories_reject_empty_owner(owner_id, tmp_path):
    with pytest.raises(ValueError, match="owner_id"):
        public_web_profile(owner_id=owner_id, approved_roots=(tmp_path,))
```

- [ ] **Step 2: Run RED model tests**

Run: `python -m pytest tests/unit/shared/test_execution_profile.py -q`

Expected: FAIL because `shared.execution_profile` does not exist.

- [ ] **Step 3: Create the immutable model and two factories**

```python
HostSurface = Literal["desktop_gui", "public_web", "cli", "sdk", "test"]

@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    host_surface: HostSurface
    owner_id: str
    allow_machine_credentials: bool
    allow_caller_proxy: bool
    require_public_network: bool
    allow_tool_execution: bool
    tool_permissions: frozenset[str]
    approved_roots: frozenset[Path]
    allow_external_plugins: bool

    def restrict(
        self,
        *,
        allow_machine_credentials: bool | None = None,
        allow_caller_proxy: bool | None = None,
        require_public_network: bool | None = None,
        allow_tool_execution: bool | None = None,
        tool_permissions: Iterable[str] | None = None,
        approved_roots: Iterable[Path] | None = None,
        allow_external_plugins: bool | None = None,
    ) -> "ExecutionProfile":
        return _restrict_profile(
            self,
            allow_machine_credentials=allow_machine_credentials,
            allow_caller_proxy=allow_caller_proxy,
            require_public_network=require_public_network,
            allow_tool_execution=allow_tool_execution,
            tool_permissions=tool_permissions,
            approved_roots=approved_roots,
            allow_external_plugins=allow_external_plugins,
        )
```

Validate `owner_id.strip()` in `__post_init__`, freeze permission/root collections, and implement both factories with the exact values asserted above. `_restrict_profile` raises `ExecutionProfileEscalation` if a denied boolean is requested as true, `require_public_network=True` is weakened to false, requested permissions/roots are not subsets, or external plugins are widened. It returns `self` for an identical restriction and uses `dataclasses.replace` only after all monotonic checks pass.

- [ ] **Step 4: Write and run restriction tests**

```python
def test_restrict_can_only_remove_local_capabilities(local_profile, tmp_path):
    child = local_profile.restrict(
        allow_machine_credentials=False,
        allow_caller_proxy=False,
        allow_tool_execution=True,
        tool_permissions=("read",),
        approved_roots=(tmp_path / "downloads",),
        allow_external_plugins=False,
    )
    assert child.owner_id == local_profile.owner_id
    assert child.host_surface == local_profile.host_surface
    assert child.tool_permissions == frozenset({"read"})
    assert child.approved_roots == frozenset({(tmp_path / "downloads").resolve()})
    assert not child.allow_machine_credentials
    assert not child.allow_caller_proxy
    assert not child.allow_external_plugins

@pytest.mark.parametrize("field,value", [
    ("allow_machine_credentials", True),
    ("allow_caller_proxy", True),
    ("allow_tool_execution", True),
    ("allow_external_plugins", True),
    ("require_public_network", False),
])
def test_public_profile_rejects_boolean_escalation(public_profile, field, value):
    with pytest.raises(ExecutionProfileEscalation):
        public_profile.restrict(**{field: value})

def test_restrict_rejects_permission_or_root_expansion(local_profile, tmp_path):
    with pytest.raises(ExecutionProfileEscalation):
        local_profile.restrict(tool_permissions=("read", "admin"))
    with pytest.raises(ExecutionProfileEscalation):
        local_profile.restrict(approved_roots=(tmp_path.parent,))
```

Run: `python -m pytest tests/unit/shared/test_execution_profile.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the unique profile model**

```bash
git add shared/execution_profile.py tests/unit/shared/test_execution_profile.py
git commit -m "feat: establish execution profile foundation"
```

### Task 2: Make payload authority impossible and require profiles at adapters

**Files:**
- Modify: `shared/execution_profile.py`
- Modify: `shared/runtime_options.py:430-771`
- Modify: `shared/cli_runner_runtime.py:403-590`
- Modify: `shared/runtime_adapters.py:7-31`
- Modify: `app/web/search_service.py:15-123`
- Modify: `app/web/workflows.py:35-82`
- Modify: `app/web/server.py:72-129`
- Test: `tests/unit/shared/test_execution_profile.py`
- Test: `tests/unit/shared/test_cli_runner_runtime.py`
- Test: `tests/unit/shared/test_runtime_helpers.py`
- Test: `tests/contract/web/test_security_hardening.py`
- Test: `tests/contract/web/test_fastapi_endpoints.py`

**Interfaces:**
- Produces: `reject_execution_profile_overrides(payload: Mapping[str, Any]) -> None`.
- Changes: `run_cli_search(*, source: str, keyword: str, save_dir: str, selection_strategy: Any, config: dict[str, Any], timeout: float | None, download: bool, execution_profile: ExecutionProfile) -> dict[str, Any]`.
- Changes: `merge_convenience_params(body: Mapping[str, Any], config: dict[str, Any], source: str, *, execution_profile: ExecutionProfile, proxy_normalizer: Callable[[str], str] | None = None) -> None`.
- Invariant: `CLIRunner` stores the exact object identity supplied by its host and passes it downward; it never creates a profile from `config`.

- [ ] **Step 1: Write failing recursive payload-escalation tests**

```python
@pytest.mark.parametrize("payload", [
    {"execution_profile": {"allow_tool_execution": True}},
    {"config": {"owner_id": "attacker"}},
    {"config": {"approved_roots": ["C:/"]}},
    {"nested": [{"tool_permissions": ["admin"]}]},
    {"allow_machine_credentials": True},
    {"allow_caller_proxy": True},
    {"allow_external_plugins": True},
])
def test_payload_cannot_supply_execution_authority(payload):
    with pytest.raises(ExecutionProfileEscalation, match="payload"):
        reject_execution_profile_overrides(payload)

def test_ordinary_payload_fields_remain_valid():
    reject_execution_profile_overrides({
        "source": "douyin",
        "keyword": "cats",
        "config": {"timeout": 30, "max_items": 20},
    })

def test_public_profile_prevents_machine_cookie_loading_and_caller_proxy(monkeypatch, tmp_path):
    profile = public_web_profile(owner_id="session-a", approved_roots=(tmp_path,))
    monkeypatch.setattr(runtime_options, "_try_load_cookie", lambda source: "session=machine-secret")
    defaults = runtime_options.get_direct_download_defaults("douyin", execution_profile=profile)
    assert "cookie" not in defaults
    with pytest.raises(ExecutionProfileEscalation, match="proxy"):
        merge_convenience_params(
            {"proxy": "http://127.0.0.1:7890"},
            {},
            "douyin",
            execution_profile=profile,
        )

def test_cli_runner_preserves_host_profile_identity(local_profile):
    runner = CLIRunner(
        source="douyin",
        keyword="cats",
        save_dir="downloads",
        selection_strategy=FirstSelectionStrategy(),
        config={},
        timeout=30,
        download=False,
        execution_profile=local_profile,
    )
    assert runner.execution_profile is local_profile
```

- [ ] **Step 2: Run RED boundary tests**

Run: `python -m pytest tests/unit/shared/test_execution_profile.py tests/unit/shared/test_cli_runner_runtime.py tests/unit/shared/test_runtime_helpers.py tests/contract/web/test_security_hardening.py -q`

Expected: FAIL because payload authority fields are not recursively rejected and adapters do not require a profile.

- [ ] **Step 3: Reject authority keys before config merge or executor scheduling**

```python
PROFILE_AUTHORITY_KEYS = frozenset({
    "execution_profile",
    "host_surface",
    "owner_id",
    "allow_machine_credentials",
    "allow_caller_proxy",
    "require_public_network",
    "allow_tool_execution",
    "tool_permissions",
    "approved_roots",
    "allow_external_plugins",
})

def reject_execution_profile_overrides(payload: Mapping[str, Any]) -> None:
    pending: list[Any] = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            forbidden = PROFILE_AUTHORITY_KEYS.intersection(str(key) for key in value)
            if forbidden:
                raise ExecutionProfileEscalation(
                    "payload cannot set execution authority: " + ", ".join(sorted(forbidden))
                )
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
```

Call this validator before `merge_default_config`, `merge_convenience_params`, plugin lookup side effects, or `run_in_executor`. Make `execution_profile` required in shared adapter/runner signatures. Credential loading checks `allow_machine_credentials`; caller `proxy` checks `allow_caller_proxy`; public URL paths check `require_public_network`. None of these functions accepts a dictionary in place of `ExecutionProfile`.

- [ ] **Step 4: Prove Web creates authority from session state, not JSON**

```python
@pytest.mark.parametrize("forbidden", [
    {"execution_profile": {"allow_machine_credentials": True}},
    {"config": {"tool_permissions": ["admin"]}},
    {"config": {"approved_roots": ["C:/"]}},
    {"cookie": "session=secret"},
    {"cookies": {"session": "secret"}},
    {"proxy": "http://127.0.0.1:7890"},
    {"config": {"douyin_cookie_file": "C:/machine/cookies.json"}},
])
def test_search_rejects_authority_before_executor(client, run_cli_search, forbidden):
    response = client.post(
        "/api/search",
        json={"source": "douyin", "keyword": "cats", "download": False, **forbidden},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "EXECUTION_PROFILE_ESCALATION"
    run_cli_search.assert_not_called()

def test_search_builds_profile_from_authenticated_session(client, run_cli_search, approved_download_root):
    run_cli_search.return_value = {"status": "success", "items": []}
    response = client.post(
        "/api/search",
        json={"source": "douyin", "keyword": "cats", "download": False},
    )
    assert response.status_code == 200
    profile = run_cli_search.call_args.kwargs["execution_profile"]
    assert profile.host_surface == "public_web"
    assert profile.owner_id
    assert profile.approved_roots == frozenset({approved_download_root.resolve()})
```

Run: `python -m pytest tests/unit/shared/test_execution_profile.py tests/unit/shared/test_cli_runner_runtime.py tests/unit/shared/test_runtime_helpers.py tests/contract/web/test_security_hardening.py tests/contract/web/test_fastapi_endpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit and push the foundation batch**

```bash
git add shared/execution_profile.py shared/runtime_options.py shared/cli_runner_runtime.py shared/runtime_adapters.py app/web/search_service.py app/web/workflows.py app/web/server.py tests/unit/shared/test_execution_profile.py tests/unit/shared/test_cli_runner_runtime.py tests/unit/shared/test_runtime_helpers.py tests/contract/web/test_security_hardening.py tests/contract/web/test_fastapi_endpoints.py
git commit -m "security: enforce host-owned execution profiles"
git push origin main
```
