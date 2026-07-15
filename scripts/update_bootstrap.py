"""生产更新信任引导与签名自动化。

更新客户端可以携带公开信任锚，但签名材料必须存放在仓库外。本模块隔离这两
个边界：创建或读取本地发布密钥，只向 ``app/config/update_trust.py`` 注入
公开值，通过外部工具签名 Windows 安装器，并在敏感文件进入提交前让仓库
扫描失败。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

# ``Crypto`` 来自仍在维护的 PyCryptodome 包，而非已废弃的 PyCrypto。
from Crypto.PublicKey import ECC  # nosec B413


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIVATE_KEY_NAME = "update_manifest_ed25519_private.pem"
DEFAULT_PUBLIC_KEY_NAME = "update_manifest_ed25519_public.pem"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "app" / "config" / "update_trust.py"
DEFAULT_DEV_CONFIG_PATH = PROJECT_ROOT / "app" / "config" / "update_trust_dev.py"
CODE_SIGNING_OID = "1.3.6.1.5.5.7.3.3"
SECRET_ENV_DIR = "UCRAWL_RELEASE_SECRETS_DIR"


class BootstrapError(RuntimeError):
    """发布引导无法安全继续时抛出。"""


@dataclass(frozen=True)
class ManifestKeyResult:
    private_key_path: Path
    public_key_path: Path
    public_key_fingerprint_sha256: str
    rotated_private_key_path: Path | None = None


@dataclass(frozen=True)
class WindowsTrustInfo:
    status: str
    subject: str
    issuer: str
    sha1_thumbprint: str
    sha256_fingerprint: str
    not_before: str = ""
    not_after: str = ""
    store_location: str = ""
    store_name: str = ""
    has_private_key: bool = False
    enhanced_key_usages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecretFinding:
    path: str
    reason: str


RunFunc = Callable[..., subprocess.CompletedProcess]


def _resolve_no_strict(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _path_is_inside(child: Path, parent: Path) -> bool:
    try:
        _resolve_no_strict(child).relative_to(_resolve_no_strict(parent))
        return True
    except ValueError:
        return False


def release_secrets_dir(*, project_root: Path = PROJECT_ROOT, create: bool = True) -> Path:
    """返回本地发布密钥根目录，并拒绝仓库内部路径。"""

    raw = os.environ.get(SECRET_ENV_DIR)
    root = Path(raw).expanduser() if raw else Path.home() / ".ucrawl" / "release-secrets"
    root = _resolve_no_strict(root)
    project = _resolve_no_strict(project_root)
    if _path_is_inside(root, project):
        raise BootstrapError(
            f"{SECRET_ENV_DIR} must not point inside the git working tree: {root}"
        )
    if create:
        root.mkdir(parents=True, exist_ok=True)
        try:
            root.chmod(0o700)
        except OSError:
            pass
    return root


def default_manifest_private_key_path(*, project_root: Path = PROJECT_ROOT) -> Path:
    return release_secrets_dir(project_root=project_root, create=True) / DEFAULT_PRIVATE_KEY_NAME


def default_manifest_public_key_path(*, project_root: Path = PROJECT_ROOT) -> Path:
    return release_secrets_dir(project_root=project_root, create=True) / DEFAULT_PUBLIC_KEY_NAME


def _public_key_fingerprint(public_pem: str) -> str:
    return hashlib.sha256(public_pem.encode("utf-8")).hexdigest().upper()


def generate_manifest_key(
    *,
    project_root: Path = PROJECT_ROOT,
    rotate: bool = False,
    write_public_key_to_config: bool = False,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> ManifestKeyResult:
    """在仓库外创建 Ed25519 清单密钥对。

    除非设置 ``rotate``，否则刻意保留现有私钥。公钥缺失时可重新派生，既能
    恢复发布流程，也不会在日志中暴露私钥内容。
    """

    secret_root = release_secrets_dir(project_root=project_root, create=True)
    private_path = secret_root / DEFAULT_PRIVATE_KEY_NAME
    public_path = secret_root / DEFAULT_PUBLIC_KEY_NAME
    rotated_private: Path | None = None

    if private_path.exists() and rotate:
        suffix = time.strftime("%Y%m%d-%H%M%S")
        rotated_private = private_path.with_name(f"{private_path.stem}.{suffix}.bak{private_path.suffix}")
        private_path.replace(rotated_private)
        if public_path.exists():
            public_path.replace(public_path.with_name(f"{public_path.stem}.{suffix}.bak{public_path.suffix}"))
    elif private_path.exists() and not rotate:
        key = ECC.import_key(private_path.read_text(encoding="utf-8"))
        public_pem = key.public_key().export_key(format="PEM")
        if not public_path.exists():
            public_path.write_text(public_pem, encoding="utf-8")
        if write_public_key_to_config:
            inject_public_key(public_key_path=public_path, config_path=config_path)
        return ManifestKeyResult(private_path, public_path, _public_key_fingerprint(public_pem))

    key = ECC.generate(curve="Ed25519")
    private_pem = key.export_key(format="PEM")
    public_pem = key.public_key().export_key(format="PEM")
    private_path.write_text(private_pem, encoding="utf-8")
    public_path.write_text(public_pem, encoding="utf-8")
    try:
        private_path.chmod(0o600)
    except OSError:
        pass
    if write_public_key_to_config:
        inject_public_key(public_key_path=public_path, config_path=config_path)
    return ManifestKeyResult(private_path, public_path, _public_key_fingerprint(public_pem), rotated_private)


def _replace_top_level_assignment(source: str, name: str, replacement: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        target_name = ""
        if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
        if target_name != name:
            continue
        if node.end_lineno is None:
            raise BootstrapError(f"cannot locate end of assignment: {name}")
        lines = source.splitlines(keepends=True)
        if not replacement.endswith("\n"):
            replacement += "\n"
        lines[node.lineno - 1 : node.end_lineno] = replacement.splitlines(keepends=True)
        return "".join(lines)
    raise BootstrapError(f"assignment not found in config: {name}")


def _format_pem_assignment(name: str, pem: str) -> str:
    value = pem.strip()
    if '"""' in value:
        raise BootstrapError("public key contains unsupported triple quote sequence")
    return f'{name} = """{value}"""\n'


def _format_tuple_assignment(name: str, values: Sequence[str]) -> str:
    cleaned = tuple(str(value).strip() for value in values if str(value).strip())
    if not cleaned:
        return f"{name}: tuple[str, ...] = ()\n"
    body = "".join(f"    {value!r},\n" for value in cleaned)
    return f"{name}: tuple[str, ...] = (\n{body})\n"


def _compile_python_file(path: Path) -> None:
    subprocess.run([sys.executable, "-m", "py_compile", str(path)], check=True)


def _assert_update_trust_config_safe(path: Path) -> None:
    source = Path(path).read_text(encoding="utf-8")
    if re.search(r"BEGIN\s+(?:EC\s+|RSA\s+|ENCRYPTED\s+)?PRIVATE\s+KEY", source):
        raise BootstrapError("update trust config contains a private key marker")
    forbidden = (".pfx", ".p12", "UCRAWL_SIGN_PFX_PASSWORD")
    for marker in forbidden:
        if marker.lower() in source.lower():
            raise BootstrapError(f"update trust config contains forbidden marker: {marker}")


def inject_public_key(*, public_key_path: Path, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """只把 Ed25519 公钥写入生产信任配置。"""

    public_pem = Path(public_key_path).read_text(encoding="utf-8").strip()
    if "BEGIN PUBLIC KEY" not in public_pem or "PRIVATE KEY" in public_pem:
        raise BootstrapError("expected a PEM public key, not private signing material")
    config = Path(config_path)
    source = config.read_text(encoding="utf-8")
    source = _replace_top_level_assignment(source, "UPDATE_PUBLIC_KEY_PEM", _format_pem_assignment("UPDATE_PUBLIC_KEY_PEM", public_pem))
    config.write_text(source, encoding="utf-8")
    _compile_python_file(config)
    _assert_update_trust_config_safe(config)


def normalize_fingerprint(value: Any) -> str:
    """归一化 SHA1/SHA256 证书指纹，供允许列表匹配。"""

    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()


def _json_payload(stdout: str) -> Any:
    payload = json.loads(stdout or "{}")
    if isinstance(payload, list):
        return payload
    return payload


def _powershell_exe() -> str:
    return "powershell.exe" if os.name == "nt" else "powershell"


def _default_run_func(run_func: RunFunc) -> bool:
    return run_func is subprocess.run


def _windows_required(run_func: RunFunc) -> None:
    if platform.system().lower() != "windows" and _default_run_func(run_func):
        raise BootstrapError("Windows signing commands require a Windows release machine")


def _powershell_cert_discovery_script() -> str:
    return r"""
$ErrorActionPreference = "Stop"
$sha1 = $args[0]
$subjectFilter = $args[1]
$stores = @(
  @{ Location = "CurrentUser"; Name = "My"; Path = "Cert:\CurrentUser\My" },
  @{ Location = "LocalMachine"; Name = "My"; Path = "Cert:\LocalMachine\My" }
)
$items = @()
foreach ($store in $stores) {
  if (-not (Test-Path $store.Path)) { continue }
  Get-ChildItem $store.Path | ForEach-Object {
    $cert = $_
    $eku = @($cert.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
    $ekuNames = @($cert.EnhancedKeyUsageList | ForEach-Object { $_.FriendlyName })
    $isCodeSigning = ($eku -contains "1.3.6.1.5.5.7.3.3") -or ($ekuNames -contains "Code Signing")
    if (-not $isCodeSigning) { return }
    if (-not $cert.HasPrivateKey) { return }
    if ($cert.NotAfter -le (Get-Date)) { return }
    if ([string]::IsNullOrWhiteSpace($cert.Subject)) { return }
    $thumb = ([string]$cert.Thumbprint).Replace(" ", "").ToUpperInvariant()
    if ($sha1 -and $thumb -ne $sha1.Replace(" ", "").ToUpperInvariant()) { return }
    if ($subjectFilter -and $cert.Subject -notlike "*$subjectFilter*") { return }
    $sha256 = [System.BitConverter]::ToString(
      [System.Security.Cryptography.SHA256]::Create().ComputeHash($cert.RawData)
    ).Replace("-", "")
    $items += [pscustomobject]@{
      subject = [string]$cert.Subject
      issuer = [string]$cert.Issuer
      sha1_thumbprint = $thumb
      sha256_fingerprint = $sha256
      not_before = $cert.NotBefore.ToUniversalTime().ToString("o")
      not_after = $cert.NotAfter.ToUniversalTime().ToString("o")
      store_location = [string]$store.Location
      store_name = [string]$store.Name
      has_private_key = [bool]$cert.HasPrivateKey
      enhanced_key_usages = @($ekuNames)
    }
  }
}
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$items | ConvertTo-Json -Depth 5
""".strip()


def _trust_info_from_mapping(data: dict[str, Any]) -> WindowsTrustInfo:
    return WindowsTrustInfo(
        status=str(data.get("Status") or data.get("status") or ""),
        subject=str(data.get("Subject") or data.get("subject") or ""),
        issuer=str(data.get("Issuer") or data.get("issuer") or ""),
        sha1_thumbprint=normalize_fingerprint(data.get("SHA1Thumbprint") or data.get("Thumbprint") or data.get("sha1_thumbprint")),
        sha256_fingerprint=normalize_fingerprint(data.get("SHA256Fingerprint") or data.get("sha256_fingerprint")),
        not_before=str(data.get("NotBefore") or data.get("not_before") or ""),
        not_after=str(data.get("NotAfter") or data.get("not_after") or ""),
        store_location=str(data.get("store_location") or ""),
        store_name=str(data.get("store_name") or ""),
        has_private_key=bool(data.get("has_private_key")),
        enhanced_key_usages=tuple(str(item) for item in data.get("enhanced_key_usages") or ()),
    )


def discover_windows_cert(
    *,
    cert_sha1: str | None = None,
    cert_subject: str | None = None,
    run_func: RunFunc = subprocess.run,
) -> WindowsTrustInfo:
    """从 Windows 证书存储中发现可用的生产代码签名证书。"""

    _windows_required(run_func)
    sha1 = normalize_fingerprint(cert_sha1 or os.environ.get("UCRAWL_SIGN_CERT_SHA1") or "")
    subject = cert_subject or os.environ.get("UCRAWL_SIGN_CERT_SUBJECT") or ""
    result = run_func(
        [_powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", _powershell_cert_discovery_script(), sha1, subject],
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise BootstrapError("certificate discovery command failed")
    payload = _json_payload(result.stdout)
    candidates = payload if isinstance(payload, list) else ([payload] if payload else [])
    candidates = [item for item in candidates if isinstance(item, dict)]
    if not candidates:
        raise BootstrapError("no valid production code signing certificate was found")
    if len(candidates) > 1 and not (sha1 or subject):
        summary = [
            {
                "subject": item.get("subject"),
                "sha1_thumbprint": item.get("sha1_thumbprint"),
                "not_after": item.get("not_after"),
                "store_location": item.get("store_location"),
            }
            for item in candidates
        ]
        raise BootstrapError("multiple code signing certificates found; choose one with --cert-sha1:\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    return _trust_info_from_mapping(candidates[0])


def _powershell_trust_extract_script() -> str:
    return r"""
$ErrorActionPreference = "Stop"
$s = Get-AuthenticodeSignature -LiteralPath $args[0]
$cert = $s.SignerCertificate
if ($null -eq $cert) {
  [Console]::OutputEncoding = [Text.Encoding]::UTF8
  @{ Status = [string]$s.Status; Subject = ""; Issuer = ""; SHA1Thumbprint = ""; SHA256Fingerprint = "" } | ConvertTo-Json
  exit 0
}
$sha256 = [System.BitConverter]::ToString(
  [System.Security.Cryptography.SHA256]::Create().ComputeHash($cert.RawData)
).Replace("-", "")
[Console]::OutputEncoding = [Text.Encoding]::UTF8
@{
  Status = [string]$s.Status
  Subject = [string]$cert.Subject
  Issuer = [string]$cert.Issuer
  SHA1Thumbprint = [string]$cert.Thumbprint
  SHA256Fingerprint = $sha256
  NotBefore = $cert.NotBefore.ToUniversalTime().ToString("o")
  NotAfter = $cert.NotAfter.ToUniversalTime().ToString("o")
} | ConvertTo-Json -Depth 4
""".strip()


def extract_windows_trust(
    *,
    installer: Path,
    run_func: RunFunc = subprocess.run,
) -> WindowsTrustInfo:
    """读取 Authenticode 签名者身份及归一化的 SHA1/SHA256 指纹。"""

    _windows_required(run_func)
    result = run_func(
        [_powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", _powershell_trust_extract_script(), str(installer)],
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise BootstrapError("Authenticode trust extraction command failed")
    payload = _json_payload(result.stdout)
    if not isinstance(payload, dict):
        raise BootstrapError("Authenticode trust extraction returned invalid JSON")
    info = _trust_info_from_mapping(payload)
    if info.status != "Valid":
        raise BootstrapError(f"installer Authenticode status is not valid: {info.status or 'Unknown'}")
    if not info.subject or not info.sha1_thumbprint:
        raise BootstrapError("installer signature did not include a signer certificate")
    return info


def resolve_signtool() -> Path:
    configured = os.environ.get("UCRAWL_SIGNTOOL_PATH")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    found = shutil.which("signtool.exe") or shutil.which("signtool")
    if found:
        candidates.append(Path(found))
    sdk_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    if sdk_root.exists():
        candidates.extend(sorted(sdk_root.glob(r"*\x64\signtool.exe"), reverse=True))
        candidates.extend(sorted(sdk_root.glob(r"*\arm64\signtool.exe"), reverse=True))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise BootstrapError("signtool.exe was not found; set UCRAWL_SIGNTOOL_PATH")


def _pfx_path_from_env(project_root: Path) -> Path | None:
    raw = os.environ.get("UCRAWL_SIGN_PFX_PATH")
    if not raw:
        return None
    path = _resolve_no_strict(Path(raw))
    if _path_is_inside(path, project_root):
        raise BootstrapError("PFX path must not be inside the git working tree")
    if not path.is_file():
        raise BootstrapError("configured PFX file does not exist")
    return path


def _sign_argv(
    *,
    signtool: Path,
    installer: Path,
    timestamp_url: str,
    cert_sha1: str,
    cert_subject: str,
    pfx_path: Path | None,
) -> list[str]:
    argv = [str(signtool), "sign", "/fd", "SHA256", "/td", "SHA256", "/tr", timestamp_url]
    if pfx_path is not None:
        argv.extend(["/f", str(pfx_path)])
        passphrase = os.environ.get("UCRAWL_SIGN_PFX_PASSWORD")
        if passphrase:
            argv.extend(["/p", passphrase])
    elif cert_sha1:
        argv.extend(["/sha1", cert_sha1])
    elif cert_subject:
        argv.extend(["/n", cert_subject])
    else:
        raise BootstrapError("missing certificate selector for signtool")
    argv.append(str(installer))
    return argv


def sign_windows_installer(
    *,
    installer: Path,
    project_root: Path = PROJECT_ROOT,
    cert_sha1: str | None = None,
    cert_subject: str | None = None,
    timestamp_url: str | None = None,
    signtool_path: Path | None = None,
    run_func: RunFunc = subprocess.run,
) -> WindowsTrustInfo:
    """使用 argv 列表调用 signtool，对 Windows 安装器签名并验证。"""

    _windows_required(run_func)
    installer = Path(installer)
    if not installer.is_file():
        raise BootstrapError(f"installer does not exist: {installer}")
    timestamp = timestamp_url or os.environ.get("UCRAWL_TIMESTAMP_URL") or ""
    if not timestamp:
        raise BootstrapError("set UCRAWL_TIMESTAMP_URL before production signing")
    pfx_path = _pfx_path_from_env(project_root)
    selected_sha1 = normalize_fingerprint(cert_sha1 or os.environ.get("UCRAWL_SIGN_CERT_SHA1") or "")
    selected_subject = cert_subject or os.environ.get("UCRAWL_SIGN_CERT_SUBJECT") or ""
    if pfx_path is None and not (selected_sha1 or selected_subject):
        discovered = discover_windows_cert(run_func=run_func)
        selected_sha1 = discovered.sha1_thumbprint
    signtool = Path(signtool_path) if signtool_path else resolve_signtool()
    sign_argv = _sign_argv(
        signtool=signtool,
        installer=installer,
        timestamp_url=timestamp,
        cert_sha1=selected_sha1,
        cert_subject=selected_subject,
        pfx_path=pfx_path,
    )
    signed = run_func(sign_argv, capture_output=True, text=True, shell=False, timeout=120)
    if signed.returncode != 0:
        raise BootstrapError("signtool sign failed")
    verified = run_func(
        [str(signtool), "verify", "/pa", "/v", str(installer)],
        capture_output=True,
        text=True,
        shell=False,
        timeout=60,
    )
    if verified.returncode != 0:
        raise BootstrapError("signtool verify failed")
    return extract_windows_trust(installer=installer, run_func=run_func)


def inject_windows_trust(
    *,
    installer: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
    run_func: RunFunc = subprocess.run,
) -> WindowsTrustInfo:
    """注入已签名安装器的公开 Windows 信任锚。"""

    info = extract_windows_trust(installer=installer, run_func=run_func)
    config = Path(config_path)
    source = config.read_text(encoding="utf-8")
    source = _replace_top_level_assignment(
        source,
        "UPDATE_TRUSTED_PUBLISHERS",
        _format_tuple_assignment("UPDATE_TRUSTED_PUBLISHERS", (info.subject,)),
    )
    thumbprints = tuple(value for value in (info.sha1_thumbprint, info.sha256_fingerprint) if value)
    source = _replace_top_level_assignment(
        source,
        "UPDATE_TRUSTED_THUMBPRINTS",
        _format_tuple_assignment("UPDATE_TRUSTED_THUMBPRINTS", thumbprints),
    )
    config.write_text(source, encoding="utf-8")
    _compile_python_file(config)
    _assert_update_trust_config_safe(config)
    return info


_PRIVATE_KEY_PATTERN = re.compile(r"BEGIN\s+(?:EC\s+|RSA\s+|OPENSSH\s+|ENCRYPTED\s+)?PRIVATE\s+KEY", re.IGNORECASE)
_PFX_ENV_ASSIGNMENT_PATTERN = re.compile(r"UCRAWL_SIGN_PFX_PASSWORD\s*=\s*\S+", re.IGNORECASE)
_PFX_PASSPHRASE_PATTERN = re.compile(r"PFX\s+pass(?:word|phrase)\s*[:=]\s*\S+", re.IGNORECASE)
_DANGEROUS_SUFFIXES = (
    ".pfx",
    ".p12",
    ".key",
    ".pem",
    ".pvk",
    ".spc",
    ".snk",
    ".cer.private",
    ".password",
    ".secret",
)


def _git_stdout(args: Sequence[str], *, project_root: Path, text: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="ignore" if text else None,
        shell=False,
        check=False,
    )
    if result.returncode != 0:
        stderr = str(result.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise BootstrapError(f"git {' '.join(args)} failed with exit code {result.returncode}{detail}")
    return result.stdout or ""


def _git_paths(args: Sequence[str], *, project_root: Path) -> list[Path]:
    stdout = _git_stdout(args, project_root=project_root)
    if not stdout:
        return []
    return [project_root / item for item in stdout.split("\0") if item]


def _is_dangerous_secret_path(path: Path) -> bool:
    lower = str(path).replace("\\", "/").lower()
    return any(lower.endswith(suffix) for suffix in _DANGEROUS_SUFFIXES)


def _read_small_text(path: Path) -> str:
    try:
        if path.stat().st_size > 5_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _scan_text_for_sensitive_markers(text: str, *, label: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    if _PRIVATE_KEY_PATTERN.search(text):
        findings.append(SecretFinding(label, "private key PEM marker"))
    if _PFX_ENV_ASSIGNMENT_PATTERN.search(text):
        findings.append(SecretFinding(label, "PFX passphrase environment assignment"))
    if _PFX_PASSPHRASE_PATTERN.search(text):
        findings.append(SecretFinding(label, "PFX passphrase text"))
    return findings


def scan_repository_for_secrets(*, project_root: Path = PROJECT_ROOT) -> list[SecretFinding]:
    """扫描已跟踪文件、差异和未跟踪路径，但不打印敏感值。"""

    project_root = _resolve_no_strict(project_root)
    findings: list[SecretFinding] = []

    for path in _git_paths(["ls-files", "-z"], project_root=project_root):
        rel = path.relative_to(project_root).as_posix()
        parts = {part.lower() for part in Path(rel).parts}
        if "release-secrets" in parts or ".release-secrets" in parts:
            findings.append(SecretFinding(rel, "release secret directory is tracked"))
        if _is_dangerous_secret_path(path):
            findings.append(SecretFinding(rel, "dangerous signing file is tracked"))
        findings.extend(_scan_text_for_sensitive_markers(_read_small_text(path), label=rel))

    for label, diff_args, name_args in (
        ("staged diff", ["diff", "--cached", "--no-ext-diff", "--unified=0"], ["diff", "--cached", "--name-only", "-z"]),
        ("working tree diff", ["diff", "--no-ext-diff", "--unified=0"], ["diff", "--name-only", "-z"]),
    ):
        findings.extend(_scan_text_for_sensitive_markers(_git_stdout(diff_args, project_root=project_root), label=label))
        for path in _git_paths(name_args, project_root=project_root):
            if _is_dangerous_secret_path(path):
                findings.append(SecretFinding(path.relative_to(project_root).as_posix(), f"dangerous signing file in {label}"))

    for path in _git_paths(["ls-files", "--others", "--exclude-standard", "-z"], project_root=project_root):
        if _is_dangerous_secret_path(path):
            findings.append(SecretFinding(path.relative_to(project_root).as_posix(), "dangerous untracked signing file"))
        findings.extend(_scan_text_for_sensitive_markers(_read_small_text(path), label=path.relative_to(project_root).as_posix()))

    try:
        secret_root = release_secrets_dir(project_root=project_root, create=False)
    except BootstrapError as exc:
        findings.append(SecretFinding(str(project_root), str(exc)))
    else:
        secret_text = str(secret_root)
        for label, diff_args in (
            ("staged diff", ["diff", "--cached", "--no-ext-diff", "--unified=0"]),
            ("working tree diff", ["diff", "--no-ext-diff", "--unified=0"]),
        ):
            if secret_text and secret_text in _git_stdout(diff_args, project_root=project_root):
                findings.append(SecretFinding(label, "local release secret path appears in git diff"))
    return findings


def scan_secrets_or_raise(*, project_root: Path = PROJECT_ROOT) -> None:
    findings = scan_repository_for_secrets(project_root=project_root)
    if findings:
        lines = "\n".join(f"- {finding.path}: {finding.reason}" for finding in findings)
        raise BootstrapError("secret scan failed:\n" + lines)


def generate_dev_windows_cert(
    *,
    write_dev_trust: bool = False,
    dev_config_path: Path = DEFAULT_DEV_CONFIG_PATH,
    run_func: RunFunc = subprocess.run,
) -> WindowsTrustInfo:
    """创建自签名开发证书，不触碰生产信任配置。"""

    _windows_required(run_func)
    script = r"""
$ErrorActionPreference = "Stop"
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=UCrawl Development Updater" -CertStoreLocation "Cert:\CurrentUser\My" -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears(1)
$sha256 = [System.BitConverter]::ToString(
  [System.Security.Cryptography.SHA256]::Create().ComputeHash($cert.RawData)
).Replace("-", "")
[Console]::OutputEncoding = [Text.Encoding]::UTF8
@{
  Status = "Valid"
  Subject = [string]$cert.Subject
  Issuer = [string]$cert.Issuer
  SHA1Thumbprint = [string]$cert.Thumbprint
  SHA256Fingerprint = $sha256
  NotBefore = $cert.NotBefore.ToUniversalTime().ToString("o")
  NotAfter = $cert.NotAfter.ToUniversalTime().ToString("o")
} | ConvertTo-Json -Depth 4
""".strip()
    result = run_func([_powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, shell=False, timeout=60)
    if result.returncode != 0:
        raise BootstrapError("development certificate generation failed")
    payload = _json_payload(result.stdout)
    if not isinstance(payload, dict):
        raise BootstrapError("development certificate command returned invalid JSON")
    info = _trust_info_from_mapping(payload)
    if write_dev_trust:
        dev_source = (
            '"""Development-only updater trust anchors.\n\n'
            "This file is never imported by production update verification.  Use it\n"
            'only with UCRAWL_UPDATE_ENV=development during local smoke tests.\n'
            '"""\n\n'
            "UPDATE_PUBLIC_KEY_PEM = \"\"\n"
            + _format_tuple_assignment("UPDATE_TRUSTED_PUBLISHERS", (info.subject,))
            + _format_tuple_assignment("UPDATE_TRUSTED_THUMBPRINTS", (info.sha1_thumbprint, info.sha256_fingerprint))
        )
        Path(dev_config_path).write_text(dev_source, encoding="utf-8")
        _compile_python_file(Path(dev_config_path))
    return info


def production_bootstrap(*, installer: Path, project_root: Path = PROJECT_ROOT) -> None:
    """执行发布机引导流程；缺少证书时按失败关闭原则终止。"""

    release_secrets_dir(project_root=project_root, create=True)
    result = generate_manifest_key(project_root=project_root, write_public_key_to_config=True)
    print(f"manifest private key: {result.private_key_path}")
    print(f"manifest public key: {result.public_key_path}")
    print(f"public key sha256: {result.public_key_fingerprint_sha256}")
    trust_info = sign_windows_installer(installer=installer, project_root=project_root)
    inject_windows_trust(installer=installer)
    scan_secrets_or_raise(project_root=project_root)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_secure_updater.py",
            "tests/test_update_check_service.py",
            "tests/test_packaging.py",
            "-q",
        ],
        cwd=project_root,
        check=True,
        shell=False,
    )
    print(json.dumps(asdict(trust_info), ensure_ascii=False, indent=2))
    print("next: python packaging/update_manifest.py --output-dir dist/release-assets --version <version> --tag v<version> --asset-spec <asset-spec>")


def _cmd_generate_manifest_key(args: argparse.Namespace) -> int:
    result = generate_manifest_key(
        rotate=bool(args.rotate),
        write_public_key_to_config=bool(args.write_public_key_to_config),
        config_path=Path(args.config),
    )
    print(f"private key path: {result.private_key_path}")
    print(f"public key path: {result.public_key_path}")
    print(f"public key sha256: {result.public_key_fingerprint_sha256}")
    if result.rotated_private_key_path:
        print(f"rotated previous private key to: {result.rotated_private_key_path}")
    print("private signing material remains outside git")
    return 0


def _cmd_inject_public_key(args: argparse.Namespace) -> int:
    public_key_path = Path(args.public_key) if args.public_key else default_manifest_public_key_path()
    inject_public_key(public_key_path=public_key_path, config_path=Path(args.config))
    print(f"injected public key into {args.config}")
    return 0


def _cmd_discover_windows_cert(args: argparse.Namespace) -> int:
    info = discover_windows_cert(cert_sha1=args.cert_sha1, cert_subject=args.cert_subject)
    print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    return 0


def _cmd_sign_windows_installer(args: argparse.Namespace) -> int:
    info = sign_windows_installer(
        installer=Path(args.installer),
        cert_sha1=args.cert_sha1,
        cert_subject=args.cert_subject,
        timestamp_url=args.timestamp_url,
        signtool_path=Path(args.signtool) if args.signtool else None,
    )
    print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    return 0


def _cmd_extract_windows_trust(args: argparse.Namespace) -> int:
    info = extract_windows_trust(installer=Path(args.installer))
    print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    return 0


def _cmd_inject_windows_trust(args: argparse.Namespace) -> int:
    info = inject_windows_trust(installer=Path(args.installer), config_path=Path(args.config))
    print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    return 0


def _cmd_production_bootstrap(args: argparse.Namespace) -> int:
    production_bootstrap(installer=Path(args.installer))
    return 0


def _cmd_scan_secrets(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root) if args.project_root else Path.cwd()
    findings = scan_repository_for_secrets(project_root=project_root)
    if findings:
        print("scan-secrets failed:")
        for finding in findings:
            print(f"- {finding.path}: {finding.reason}")
        return 1
    print("scan-secrets passed")
    return 0


def _cmd_generate_dev_windows_cert(args: argparse.Namespace) -> int:
    info = generate_dev_windows_cert(write_dev_trust=bool(args.write_dev_trust), dev_config_path=Path(args.dev_config))
    print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ucrawl-update-bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate-manifest-key")
    generate.add_argument("--rotate", action="store_true")
    generate.add_argument("--write-public-key-to-config", action="store_true")
    generate.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    generate.set_defaults(func=_cmd_generate_manifest_key)

    inject_key = sub.add_parser("inject-public-key")
    inject_key.add_argument("--public-key", default="")
    inject_key.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    inject_key.set_defaults(func=_cmd_inject_public_key)

    discover = sub.add_parser("discover-windows-cert")
    discover.add_argument("--cert-sha1", default="")
    discover.add_argument("--cert-subject", default="")
    discover.set_defaults(func=_cmd_discover_windows_cert)

    sign = sub.add_parser("sign-windows-installer")
    sign.add_argument("--installer", required=True)
    sign.add_argument("--cert-sha1", default="")
    sign.add_argument("--cert-subject", default="")
    sign.add_argument("--timestamp-url", default="")
    sign.add_argument("--signtool", default="")
    sign.set_defaults(func=_cmd_sign_windows_installer)

    extract = sub.add_parser("extract-windows-trust")
    extract.add_argument("--installer", required=True)
    extract.set_defaults(func=_cmd_extract_windows_trust)

    inject_trust = sub.add_parser("inject-windows-trust")
    inject_trust.add_argument("--installer", required=True)
    inject_trust.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    inject_trust.set_defaults(func=_cmd_inject_windows_trust)

    bootstrap = sub.add_parser("production-bootstrap")
    bootstrap.add_argument("--installer", required=True)
    bootstrap.set_defaults(func=_cmd_production_bootstrap)

    scan = sub.add_parser("scan-secrets")
    scan.add_argument("--project-root", default=None)
    scan.set_defaults(func=_cmd_scan_secrets)

    dev = sub.add_parser("generate-dev-windows-cert")
    dev.add_argument("--write-dev-trust", action="store_true")
    dev.add_argument("--dev-config", default=str(DEFAULT_DEV_CONFIG_PATH))
    dev.set_defaults(func=_cmd_generate_dev_windows_cert)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def scan_secrets_main() -> int:
    return main(["scan-secrets", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
