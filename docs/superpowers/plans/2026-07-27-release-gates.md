# Release Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CI inspect every production package and prove that real Windows portable and installed artifacts launch with the expected product and signer identity.

**Architecture:** Workflow contracts derive coverage and Docker inputs from production configuration rather than filename whitelists. A dedicated Windows job builds both artifacts, verifies PE/product metadata, enforces Authenticode signer identity on signed release runs, installs into an isolated directory, and performs bounded process smoke checks.

**Tech Stack:** GitHub Actions, Python 3.10-3.13, Coverage.py branch coverage, Ruff, Bandit, Docker Buildx, PyInstaller, Inno Setup, PowerShell, Authenticode, pytest.

## Global Constraints

- Follow `tests/AGENTS.md`; workflow, packaging, installation, updater, and release-asset tests stay under `tests/release/`.
- Keep the configured 75 percent branch-coverage threshold.
- Include `app`, `cli`, `entry`, `shared`, and `ucrawl` in compile, Ruff, Bandit, and coverage gates.
- Docker workflow path filters cover every local source consumed by Dockerfile `COPY` instructions and the workflow/build configuration itself.
- Build and smoke both portable and installer outputs on `windows-latest`; mocks do not satisfy the artifact gate.
- Bound every artifact launch to 30 seconds and terminate timed-out processes.
- Verify PE format plus fixed product/company metadata on all Windows artifacts.
- Signed release runs require Authenticode status `Valid`, the configured publisher subject, and the configured certificate SHA-256 thumbprint.
- Stage and push each task with exact file paths.

## Explicit Non-Goal

Version monotonicity is outside this work. Acceptance of an older signed version remains the user-required hot-update validation window. Do not change updater version comparison or rollback behavior. The unchanged rollback path remains constrained by signed manifest verification, artifact SHA-256 verification, publisher identity, and certificate thumbprint verification; run those security tests as regression evidence.

---

## File Structure

- Modify `.github/workflows/python-tests.yml`: complete production source-set gates.
- Modify `pyproject.toml`: add `ucrawl` to coverage sources while retaining branch coverage and threshold 75.
- Modify `.github/workflows/docker-build.yml`: complete Docker input triggers.
- Create `.github/workflows/windows-artifact-smoke.yml`: real portable/install build and smoke.
- Create `packaging/smoke_windows_artifact.ps1`: PE, product identity, Authenticode identity, launch, timeout, and report checks.
- Modify `tests/release/ci/test_workflow.py`: parsed workflow/source-set and Docker-input contracts.
- Modify `tests/release/packaging/test_assets.py`: script/workflow asset presence.
- Create `tests/release/packaging/test_windows_artifact_smoke.py`: execute negative verifier cases on Windows.

---

### Task 1: Complete Python Quality Sources and Docker Triggers

**Files:**
- Modify: `.github/workflows/python-tests.yml`
- Modify: `.github/workflows/docker-build.yml`
- Modify: `pyproject.toml`
- Modify: `tests/release/ci/test_workflow.py`

**Interfaces:**
- Produces coverage source set `app, cli, entry, shared, ucrawl` with `branch = true` and `fail_under = 75`.
- Produces workflow path filters whose normalized roots contain every local Dockerfile `COPY` source.
- Test helpers parse YAML with `yaml.safe_load`, collect every scalar `run` value, parse shell arguments with `shlex`, and parse Dockerfile `COPY` sources in shell and JSON forms while ignoring remote URLs and `--from` stages.

- [ ] **Step 1: Write parsed workflow and Dockerfile-derived tests**

```python
def test_quality_steps_cover_configured_production_sources():
    workflow = load_workflow(PYTHON_WORKFLOW)
    commands = workflow_run_commands(workflow)
    required = {"app", "cli", "entry", "shared", "ucrawl"}
    assert command_sources(commands, tool="compileall") >= required
    assert command_sources(commands, tool="ruff") >= required
    assert command_sources(commands, tool="bandit") >= required
    assert set(PYPROJECT["tool"]["coverage"]["run"]["source"]) == required
    assert PYPROJECT["tool"]["coverage"]["run"]["branch"] is True
    assert PYPROJECT["tool"]["coverage"]["report"]["fail_under"] == 75

def test_docker_filters_cover_every_local_copy_source():
    workflow = load_workflow(DOCKER_WORKFLOW)
    filters = normalized_path_filters(workflow)
    copied_sources = local_copy_sources(DOCKERFILE)
    uncovered = sorted(source for source in copied_sources if not path_filter_covers(filters, source))
    assert uncovered == []
```

- [ ] **Step 2: Run focused release-CI tests and confirm RED**

Run: `python -m pytest tests/release/ci/test_workflow.py -q -k "configured_production_sources or every_local_copy_source"`

Expected: assertions report missing `ucrawl` quality/coverage participation and omitted Docker inputs.

- [ ] **Step 3: Update source commands, coverage configuration, and filters**

Set Coverage.py sources to:

```toml
[tool.coverage.run]
branch = true
source = ["app", "cli", "entry", "shared", "ucrawl"]
```

Use the same production roots in compile, Ruff, and Bandit steps. Add Docker path filters for uncovered Dockerfile sources such as `ucrawl/**`, `main.py`, root README files, icons, and manifests reported by the derived test. Apply identical source filters to push and pull-request triggers.

- [ ] **Step 4: Run workflow, local quality, and coverage-config checks**

Run: `python -m pytest tests/release/ci/test_workflow.py -q`

Expected: all tests pass.

Run: `python -m compileall -q app cli entry shared ucrawl main.py`

Expected: exit code 0.

Run: `python -m ruff check app cli entry shared ucrawl main.py tests`

Expected: exit code 0.

Run: `python -m bandit -q -r app cli entry shared ucrawl`

Expected: exit code 0 with no high-severity finding.

- [ ] **Step 5: Commit and push Task 1**

```bash
git add .github/workflows/python-tests.yml .github/workflows/docker-build.yml pyproject.toml tests/release/ci/test_workflow.py
git commit -m "ci: cover all production and docker inputs"
git push origin main
```

### Task 2: Windows Artifact Identity and Launch Verifier

**Files:**
- Create: `packaging/smoke_windows_artifact.ps1`
- Modify: `tests/release/packaging/test_assets.py`
- Create: `tests/release/packaging/test_windows_artifact_smoke.py`

**Interfaces:**
- Produces PowerShell parameters `Executable`, `ExpectedVersion`, `ExpectedProductName`, `ExpectedCompanyName`, `TimeoutSeconds`, `RequireAuthenticode`, `ExpectedPublisher`, `ExpectedThumbprint`, and `ReportPath`.
- Returns exit code 0 after identity and bounded launch success; every mismatch or timeout returns nonzero and writes a JSON report.
- Test helper `run_verifier()` invokes `pwsh -NoProfile -File packaging/smoke_windows_artifact.ps1` with an argument list; `windows_python_exe` resolves `Path(sys.executable)` as a real unsigned PE fixture.

- [ ] **Step 1: Write executable negative-case tests**

```python
@pytest.mark.windows
def test_verifier_rejects_non_pe_file(tmp_path):
    fake = tmp_path / "fake.exe"
    fake.write_bytes(b"not-pe")
    result = run_verifier(fake, expected_version="3.6.21")
    assert result.returncode != 0
    assert read_report(result)["failure_code"] == "PE_HEADER_INVALID"

@pytest.mark.windows
def test_verifier_rejects_product_identity_mismatch(windows_python_exe):
    result = run_verifier(windows_python_exe, expected_product="Wrong Product")
    assert result.returncode != 0
    assert read_report(result)["failure_code"] == "PRODUCT_IDENTITY_MISMATCH"

@pytest.mark.windows
def test_verifier_rejects_unsigned_binary_when_signature_is_required(windows_python_exe):
    result = run_verifier(windows_python_exe, require_authenticode=True, thumbprint="00")
    assert result.returncode != 0
    assert read_report(result)["failure_code"] == "AUTHENTICODE_INVALID"
```

- [ ] **Step 2: Run verifier tests and confirm RED**

Run: `python -m pytest tests/release/packaging/test_assets.py tests/release/packaging/test_windows_artifact_smoke.py -q -m windows`

Expected: collection fails because the verifier and test fixture do not exist.

- [ ] **Step 3: Write PE, product, signer, launch, and report checks**

The script reads the first two bytes and requires `MZ`; reads `VersionInfo.ProductVersion`, `ProductName`, and `CompanyName`; then, when `RequireAuthenticode` is set, requires:

```powershell
$signature = Get-AuthenticodeSignature -LiteralPath $Executable
if ($signature.Status -ne 'Valid') { throw 'AUTHENTICODE_INVALID' }
$actualThumbprint = $signature.SignerCertificate.Thumbprint.Replace(' ', '').ToUpperInvariant()
if ($actualThumbprint -ne $ExpectedThumbprint.Replace(' ', '').ToUpperInvariant()) { throw 'SIGNER_THUMBPRINT_MISMATCH' }
if ($signature.SignerCertificate.Subject -notlike "*$ExpectedPublisher*") { throw 'SIGNER_PUBLISHER_MISMATCH' }
```

Launch the executable with the product's non-interactive `--version` argument, wait for at most `TimeoutSeconds`, kill after timeout, require exit code 0 and exact normalized version output, and write a JSON report through a unique temporary file plus `Move-Item` to the final path.

- [ ] **Step 4: Run packaging verifier tests**

Run: `python -m pytest tests/release/packaging/test_assets.py tests/release/packaging/test_windows_artifact_smoke.py -q -m windows`

Expected: all tests pass on Windows.

- [ ] **Step 5: Commit and push Task 2**

```bash
git add packaging/smoke_windows_artifact.ps1 tests/release/packaging/test_assets.py tests/release/packaging/test_windows_artifact_smoke.py
git commit -m "ci: verify windows artifact identity and launch"
git push origin main
```

### Task 3: Real Portable and Installer Workflow

**Files:**
- Create: `.github/workflows/windows-artifact-smoke.yml`
- Modify: `tests/release/ci/test_workflow.py`
- Modify: `tests/release/packaging/test_assets.py`

**Interfaces:**
- Produces one `windows-latest` job with a 45-minute job timeout.
- Produces reports `portable-smoke-report` and `installer-smoke-report` with `if: always()`.
- Release-tag runs pass `RequireAuthenticode`, publisher, and thumbprint to the verifier; pull requests run PE/product/launch checks without claiming signature validity.

- [ ] **Step 1: Write parsed workflow contract tests**

```python
def test_windows_job_builds_and_smokes_real_portable_and_installed_outputs():
    workflow = load_workflow(WINDOWS_ARTIFACT_WORKFLOW)
    job = workflow["jobs"]["windows-artifacts"]
    assert job["runs-on"] == "windows-latest"
    assert job["timeout-minutes"] == 45
    commands = workflow_run_commands({"jobs": {"windows-artifacts": job}})
    assert has_python_script(commands, "packaging/build_portable.py")
    assert has_python_script(commands, "packaging/build_installer.py")
    assert has_installer_execution(commands, silent=True, isolated_directory=True)
    assert verifier_targets(commands) == {"portable", "installed"}

def test_release_tag_signature_gate_passes_publisher_and_thumbprint():
    workflow = load_workflow(WINDOWS_ARTIFACT_WORKFLOW)
    signature_step = named_step(workflow, "Verify signed release identity")
    assert signature_step["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert powershell_parameters(signature_step) >= {
        "RequireAuthenticode",
        "ExpectedPublisher",
        "ExpectedThumbprint",
    }
```

- [ ] **Step 2: Run workflow contracts and confirm RED**

Run: `python -m pytest tests/release/ci/test_workflow.py tests/release/packaging/test_assets.py -q -k "windows_job or release_tag_signature_gate"`

Expected: tests fail because the Windows artifact workflow does not exist.

- [ ] **Step 3: Write the bounded Windows build/install/smoke job**

The job checks out source, installs Python 3.13 and locked dependencies, builds portable output, runs the verifier, builds the Inno installer, installs with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` into `$env:RUNNER_TEMP\ucrawl-installed`, verifies the installed executable, and uninstalls/removes the isolated directory in an `if: always()` cleanup step. Tag builds sign through the existing release signing path and execute the Authenticode identity gate using protected secrets.

Upload both JSON reports with compression disabled. Failure logs include build output, installer log, executable stdout/stderr, signature status, publisher subject, and certificate thumbprint.

- [ ] **Step 4: Run release contracts and existing identity-signature regressions**

Run: `python -m pytest tests/release/ci/test_workflow.py tests/release/packaging/test_assets.py -q`

Expected: all tests pass.

Run: `python -m pytest tests/release/updater/test_secure_updater.py -q -k "manifest_signature_failure_is_rejected or windows_verifier_rejects_publisher or windows_verifier_rejects_publisher_match_when_thumbprint_mismatches"`

Expected: all selected identity/signature tests pass; updater rollback behavior is unchanged.

Run: `python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q`

Expected: all tests pass.

Run: `python -m pytest tests --collect-only -q`

Expected: collection succeeds.

- [ ] **Step 5: Commit and push Task 3**

```bash
git add .github/workflows/windows-artifact-smoke.yml tests/release/ci/test_workflow.py tests/release/packaging/test_assets.py
git commit -m "ci: smoke portable and installed windows artifacts"
git push origin main
```
