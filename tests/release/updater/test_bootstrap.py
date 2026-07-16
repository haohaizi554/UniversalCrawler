from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from Crypto.PublicKey import ECC

from scripts import update_bootstrap as bootstrap


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True, shell=False)


def _minimal_update_trust(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '"""Test trust config."""\n\n'
        'UPDATE_PUBLIC_KEY_PEM = ""\n'
        'UPDATE_TRUSTED_PUBLISHERS: tuple[str, ...] = ()\n'
        'UPDATE_TRUSTED_THUMBPRINTS: tuple[str, ...] = ()\n',
        encoding="utf-8",
    )


def test_generate_manifest_key_writes_private_key_outside_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside" / "release-secrets"
    monkeypatch.setenv("UCRAWL_RELEASE_SECRETS_DIR", str(outside))

    result = bootstrap.generate_manifest_key(project_root=repo)

    assert result.private_key_path.parent == outside.resolve()
    assert not bootstrap._path_is_inside(result.private_key_path, repo)
    assert result.public_key_path.exists()
    assert "BEGIN PUBLIC KEY" in result.public_key_path.read_text(encoding="utf-8")


def test_inject_public_key_only_writes_public_material(tmp_path):
    key = ECC.generate(curve="Ed25519")
    public_path = tmp_path / "public.pem"
    public_path.write_text(key.public_key().export_key(format="PEM"), encoding="utf-8")
    config = tmp_path / "app" / "config" / "update_trust.py"
    _minimal_update_trust(config)

    bootstrap.inject_public_key(public_key_path=public_path, config_path=config)

    source = config.read_text(encoding="utf-8")
    assert "BEGIN PUBLIC KEY" in source
    assert "PRIVATE KEY" not in source
    assert "UPDATE_TRUSTED_PUBLISHERS: tuple[str, ...] = ()" in source


def test_scan_secrets_detects_private_key_marker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    monkeypatch.setenv("UCRAWL_RELEASE_SECRETS_DIR", str(tmp_path / "outside"))
    marker = "-----" + "BEGIN " + "PRIVATE KEY" + "-----"
    leak = repo / "leak.py"
    leak.write_text(marker, encoding="utf-8")
    subprocess.run(["git", "add", "leak.py"], cwd=repo, check=True, shell=False)

    findings = bootstrap.scan_repository_for_secrets(project_root=repo)

    assert any("private key" in finding.reason for finding in findings)


def test_scan_secrets_detects_dangerous_untracked_signing_file(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    monkeypatch.setenv("UCRAWL_RELEASE_SECRETS_DIR", str(tmp_path / "outside"))
    (repo / "local-signing.pfx").write_bytes(b"certificate bundle")

    findings = bootstrap.scan_repository_for_secrets(project_root=repo)

    assert any("dangerous untracked" in finding.reason for finding in findings)


def test_scan_secrets_allows_public_key_in_update_trust(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    config = repo / "app" / "config" / "update_trust.py"
    _minimal_update_trust(config)
    source = config.read_text(encoding="utf-8").replace(
        'UPDATE_PUBLIC_KEY_PEM = ""',
        'UPDATE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----\\nabc\\n-----END PUBLIC KEY-----"""',
    )
    config.write_text(source, encoding="utf-8")
    _git_init(repo)
    monkeypatch.setenv("UCRAWL_RELEASE_SECRETS_DIR", str(tmp_path / "outside"))
    subprocess.run(["git", "add", "app/config/update_trust.py"], cwd=repo, check=True, shell=False)

    findings = bootstrap.scan_repository_for_secrets(project_root=repo)

    assert findings == []


def test_scan_secrets_fails_closed_when_git_command_fails(tmp_path, monkeypatch):
    repo = tmp_path / "not-a-repository"
    repo.mkdir()

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 128, stdout="", stderr="fatal: not a git repository")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    assert bootstrap.main(["scan-secrets", "--project-root", str(repo)]) == 1


def test_scan_secrets_console_entry_defaults_to_current_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    captured: dict[str, Path] = {}

    def fake_scan(*, project_root):
        captured["project_root"] = Path(project_root)
        return []

    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["scan-secrets"])
    monkeypatch.setattr(bootstrap, "scan_repository_for_secrets", fake_scan)

    assert bootstrap.scan_secrets_main() == 0
    assert captured["project_root"] == repo


def test_extract_windows_trust_parses_and_normalizes_powershell_json(tmp_path):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "Status": "Valid",
                    "Subject": "CN=UCrawl",
                    "Issuer": "CN=Issuer",
                    "SHA1Thumbprint": "aa bb cc",
                    "SHA256Fingerprint": "dd:ee:ff",
                    "NotBefore": "2026-01-01T00:00:00Z",
                    "NotAfter": "2027-01-01T00:00:00Z",
                }
            ),
            stderr="",
        )

    info = bootstrap.extract_windows_trust(installer=installer, run_func=fake_run)

    assert info.sha1_thumbprint == "AABBCC"
    assert info.sha256_fingerprint == "DDEEFF"
    assert calls[0]["kwargs"]["shell"] is False


def test_sign_windows_installer_uses_argv_lists_and_shell_false(tmp_path, monkeypatch):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        if "powershell" in Path(str(argv[0])).name.lower():
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "Status": "Valid",
                        "Subject": "CN=UCrawl",
                        "Issuer": "CN=Issuer",
                        "SHA1Thumbprint": "AABB",
                        "SHA256Fingerprint": "CCDD",
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.delenv("UCRAWL_SIGN_PFX_PATH", raising=False)
    info = bootstrap.sign_windows_installer(
        installer=installer,
        cert_sha1="AA BB",
        timestamp_url="https://timestamp.example.test",
        signtool_path=tmp_path / "signtool.exe",
        run_func=fake_run,
    )

    assert info.subject == "CN=UCrawl"
    assert calls[0]["argv"][1] == "sign"
    assert calls[1]["argv"][1:4] == ["verify", "/pa", "/v"]
    assert all(isinstance(call["argv"], list) for call in calls)
    assert all(call["kwargs"]["shell"] is False for call in calls)


def test_generate_dev_windows_cert_writes_only_dev_trust_config(tmp_path):
    dev_config = tmp_path / "update_trust_dev.py"

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "Status": "Valid",
                    "Subject": "CN=UCrawl Development Updater",
                    "Issuer": "CN=UCrawl Development Updater",
                    "SHA1Thumbprint": "1122",
                    "SHA256Fingerprint": "3344",
                }
            ),
            stderr="",
        )

    info = bootstrap.generate_dev_windows_cert(write_dev_trust=True, dev_config_path=dev_config, run_func=fake_run)

    assert info.subject == "CN=UCrawl Development Updater"
    assert dev_config.exists()
    assert "UPDATE_TRUSTED_THUMBPRINTS" in dev_config.read_text(encoding="utf-8")
