"""Bounded, read-only GitHub release metadata lookups."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, _parse_proxy, build_opener

from .events import redact_release_text
from .models import RemoteReleaseInfo
from shared.release_identity import parse_release_tag


GITHUB_API_ACCEPT = "application/vnd.github+json"
GITHUB_API_USER_AGENT = "UniversalCrawlerReleaseBuilder/1.0"
MAX_RESPONSE_BYTES = 1_000_000
MAX_RELEASE_PAGE_BYTES = 256_000
MAX_RELEASE_RESULTS = 30
MAX_GIT_TAG_RESULTS = 512
MAX_GIT_OUTPUT_CHARS = 512_000
_READ_RETRY_DELAYS_SECONDS = (1.0, 2.0)
_TRANSIENT_HTTP_CODES = frozenset({408, 425, 500, 502, 503, 504})
_TRANSIENT_NETWORK_FRAGMENTS = (
    "connection refused",
    "connection reset",
    "connection was forcibly closed",
    "i/o timeout",
    "temporary failure",
    "timed out",
    "tls handshake timeout",
    "unexpected eof",
    "wsarecv",
)
_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def fetch_latest_release(
    repository: str,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float = 10.0,
) -> RemoteReleaseInfo:
    """Return a bounded snapshot of public protocol-compatible releases."""

    try:
        owner, name = _repository_components(repository)
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        request = Request(
            f"https://api.github.com/repos/{owner}/{name}/releases"
            f"?per_page={MAX_RELEASE_RESULTS}&page=1",
            headers={
                "Accept": GITHUB_API_ACCEPT,
                "User-Agent": GITHUB_API_USER_AGENT,
            },
            method="GET",
        )
        payload = _open_json(
            request,
            environment=dict(environment),
            timeout_seconds=timeout,
        )
    except HTTPError as api_error:
        if api_error.code not in {403, 429}:
            return RemoteReleaseInfo.unavailable(redact_release_text(str(api_error)))
        try:
            tag = _open_latest_release_tag(
                owner,
                name,
                environment=dict(environment),
                timeout_seconds=timeout,
            )
        except Exception as page_error:
            message = f"{api_error}; release page fallback failed: {page_error}"
            return RemoteReleaseInfo.unavailable(redact_release_text(message))
        return RemoteReleaseInfo.available(tag)
    except Exception as error:
        return RemoteReleaseInfo.unavailable(redact_release_text(str(error)))

    try:
        tags = _public_release_tags(payload)
        if not tags:
            raise ValueError("release response has no protocol-compatible public tag")
        return RemoteReleaseInfo.available(tags[0], release_tags=tags)
    except Exception as error:
        return RemoteReleaseInfo.unavailable(redact_release_text(str(error)))


def fetch_release_inventory(
    repository: str,
    *,
    environment: Mapping[str, str],
    project_root: str | Path,
    timeout_seconds: float = 10.0,
) -> RemoteReleaseInfo:
    """Combine public Releases with local and remote immutable tag refs.

    GitHub's Releases endpoint omits a tag created immediately before a failed
    ``gh release create`` or asset upload. Reading both Git namespaces prevents
    the panel from trying to reuse that revision for different source code.
    """

    release_info = fetch_latest_release(
        repository,
        environment=environment,
        timeout_seconds=timeout_seconds,
    )
    if not release_info.is_available:
        return release_info
    try:
        occupied, resumable = _git_release_tag_inventory(
            repository,
            project_root=project_root,
            environment=environment,
            timeout_seconds=timeout_seconds,
            published_tags=release_info.release_tags,
        )
    except Exception as error:
        message = f"release tag inventory failed: {error}"
        return RemoteReleaseInfo.unavailable(redact_release_text(message))
    return RemoteReleaseInfo.available(
        release_info.identity.tag,
        release_tags=release_info.release_tags,
        occupied_tags=occupied,
        resumable_tags=resumable,
    )


def _git_release_tag_inventory(
    repository: str,
    *,
    project_root: str | Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    published_tags: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return all occupied tags and bare tags that safely match current HEAD."""

    owner, name = _repository_components(repository)
    root = Path(project_root).resolve()
    head = _git_output(
        ("rev-parse", "--verify", "HEAD"),
        project_root=root,
        environment=environment,
        timeout_seconds=timeout_seconds,
    ).strip().lower()
    if not _COMMIT_PATTERN.fullmatch(head):
        raise ValueError("Git HEAD is not a full commit SHA")

    local = _parse_local_tag_refs(
        _git_output(
            (
                "for-each-ref",
                "--format=%(refname:strip=2)%09%(objecttype)%09%(objectname)%09%(*objecttype)%09%(*objectname)",
                "refs/tags",
            ),
            project_root=root,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    )
    remote_url = f"https://github.com/{owner}/{name}.git"
    remote = _parse_remote_tag_refs(
        _git_output(
            ("ls-remote", "--tags", remote_url),
            project_root=root,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    )
    return _merge_release_tag_inventory(
        published_tags=published_tags,
        head_commit=head,
        local_tags=local,
        remote_tags=remote,
    )


def _git_output(
    arguments: tuple[str, ...],
    *,
    project_root: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> str:
    process_environment = dict(environment) if environment else dict(os.environ)
    process_environment["GIT_TERMINAL_PROMPT"] = "0"
    run_options: dict[str, object] = {
        "cwd": str(project_root),
        "env": process_environment,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout_seconds,
        "check": False,
    }
    if os.name == "nt":
        run_options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(["git", *arguments], **run_options)
    if completed.returncode != 0:
        raise RuntimeError("Git tag inventory command failed")
    output = str(completed.stdout or "")
    if len(output) > MAX_GIT_OUTPUT_CHARS:
        raise ValueError("Git tag inventory exceeds the configured size limit")
    return output


def _parse_local_tag_refs(output: str) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for line in _bounded_git_lines(output):
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        tag, object_type, object_sha, peeled_type, peeled_sha = parts
        canonical = _canonical_release_tag(tag)
        if not canonical:
            continue
        commit = object_sha if object_type == "commit" else peeled_sha
        if object_type != "commit" and peeled_type != "commit":
            commit = ""
        refs[canonical] = commit.lower() if _COMMIT_PATTERN.fullmatch(commit) else None
    return refs


def _parse_remote_tag_refs(output: str) -> dict[str, str | None]:
    direct: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in _bounded_git_lines(output):
        parts = line.split()
        if len(parts) != 2 or not _COMMIT_PATTERN.fullmatch(parts[0]):
            continue
        sha, ref = parts
        prefix = "refs/tags/"
        if not ref.startswith(prefix):
            continue
        raw_tag = ref[len(prefix) :]
        is_peeled = raw_tag.endswith("^{}")
        if is_peeled:
            raw_tag = raw_tag[:-3]
        canonical = _canonical_release_tag(raw_tag)
        if not canonical:
            continue
        (peeled if is_peeled else direct)[canonical] = sha.lower()
    return {
        tag: peeled.get(tag, direct.get(tag))
        for tag in set(direct) | set(peeled)
    }


def _bounded_git_lines(output: str) -> tuple[str, ...]:
    lines = tuple(line for line in str(output).splitlines() if line.strip())
    if len(lines) > MAX_GIT_TAG_RESULTS * 2:
        raise ValueError("Git tag inventory contains too many refs")
    return lines


def _canonical_release_tag(value: str) -> str:
    try:
        identity = parse_release_tag(str(value).strip())
    except ValueError:
        return ""
    return identity.tag


def _merge_release_tag_inventory(
    *,
    published_tags: tuple[str, ...],
    head_commit: str,
    local_tags: Mapping[str, str | None],
    remote_tags: Mapping[str, str | None],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    published = {_canonical_release_tag(tag) for tag in published_tags}
    published.discard("")
    occupied = published | set(local_tags) | set(remote_tags)
    resumable: set[str] = set()
    for tag in occupied - published:
        commits = {
            commit.lower()
            for commit in (local_tags.get(tag), remote_tags.get(tag))
            if commit
        }
        if commits == {head_commit.lower()}:
            resumable.add(tag)
    def order(tag: str):
        return parse_release_tag(tag)

    return (
        tuple(sorted(occupied, key=order, reverse=True)),
        tuple(sorted(resumable, key=order, reverse=True)),
    )


def _public_release_tags(payload: object) -> tuple[str, ...]:
    """Filter GitHub metadata before it reaches revision planning."""

    items: list[object]
    if isinstance(payload, Mapping):
        items = [payload]
    elif isinstance(payload, list):
        items = payload[:MAX_RELEASE_RESULTS]
    else:
        return ()

    identities = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("draft") is True or item.get("prerelease") is True:
            continue
        tag = item.get("tag_name")
        if not isinstance(tag, str):
            continue
        try:
            identities.add(parse_release_tag(tag.strip()))
        except ValueError:
            continue
    return tuple(identity.tag for identity in sorted(identities, reverse=True))


def _open_json(
    request: Request,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> object:
    values = {str(key).casefold(): str(value) for key, value in environment.items()}
    no_proxy = values.get("no_proxy", "")
    handler = _EnvironmentProxyHandler(
        _proxy_settings(values, host=request.host or ""),
        no_proxy=no_proxy,
    )
    opener = build_opener(handler)
    with _open_with_retry(opener, request, timeout_seconds=timeout_seconds) as response:
        content = response.read(MAX_RESPONSE_BYTES + 1)
    if len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("GitHub response exceeds the configured size limit")
    return json.loads(content.decode("utf-8"))


def _open_latest_release_tag(
    owner: str,
    name: str,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> str:
    page_url = f"https://github.com/{owner}/{name}/releases/latest"
    request = Request(
        page_url,
        headers={"User-Agent": GITHUB_API_USER_AGENT},
        method="GET",
    )
    values = {str(key).casefold(): str(value) for key, value in environment.items()}
    handler = _EnvironmentProxyHandler(
        _proxy_settings(values, host=request.host or ""),
        no_proxy=values.get("no_proxy", ""),
    )
    opener = build_opener(handler, _TrustedGitHubRedirectHandler({"github.com"}))
    with _open_with_retry(opener, request, timeout_seconds=timeout_seconds) as response:
        final_url = str(response.geturl() or page_url)
        tag = _release_tag_from_url(final_url, owner=owner, name=name)
        if tag:
            return tag
        content = response.read(MAX_RELEASE_PAGE_BYTES + 1)
    if len(content) > MAX_RELEASE_PAGE_BYTES:
        raise ValueError("GitHub release page exceeds the configured size limit")
    tag = _release_tag_from_html(content.decode("utf-8", errors="ignore"), owner=owner, name=name)
    if not tag:
        raise ValueError("GitHub release page has no release tag")
    return tag


def _open_with_retry(opener, request: Request, *, timeout_seconds: float):
    """为只读 GitHub 请求吸收代理瞬断，不重试鉴权或限流响应。"""

    for attempt in range(len(_READ_RETRY_DELAYS_SECONDS) + 1):
        try:
            return opener.open(request, timeout=timeout_seconds)
        except Exception as error:
            if (
                attempt >= len(_READ_RETRY_DELAYS_SECONDS)
                or not _is_transient_read_error(error)
            ):
                raise
            time.sleep(_READ_RETRY_DELAYS_SECONDS[attempt])
    raise AssertionError("unreachable")


def _is_transient_read_error(error: Exception) -> bool:
    if isinstance(error, HTTPError):
        return error.code in _TRANSIENT_HTTP_CODES
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    if isinstance(error, URLError) and isinstance(error.reason, Exception):
        return _is_transient_read_error(error.reason)
    message = str(getattr(error, "reason", error)).casefold()
    return any(fragment in message for fragment in _TRANSIENT_NETWORK_FRAGMENTS)


def _release_tag_from_url(url: str, *, owner: str, name: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() != "github.com":
        return ""
    prefix = f"/{owner}/{name}/releases/tag/"
    if not parsed.path.startswith(prefix):
        return ""
    tag = parsed.path[len(prefix) :].split("/", 1)[0]
    return unquote(tag)


def _release_tag_from_html(html: str, *, owner: str, name: str) -> str:
    repository_path = re.escape(f"/{owner}/{name}/releases/tag/")
    match = re.search(rf'href="(?:https://github\.com)?{repository_path}([^"/?#]+)', html)
    return unquote(match.group(1)) if match else ""


def _proxy_settings(environment: Mapping[str, str], *, host: str = "api.github.com") -> dict[str, str]:
    """Return only proxy settings selected from the supplied environment."""

    values = {str(key).casefold(): str(value) for key, value in environment.items()}
    if _matches_no_proxy(host, values.get("no_proxy", "")):
        return {}
    fallback = values.get("all_proxy", "")
    return {
        scheme: values.get(f"{scheme}_proxy", fallback)
        for scheme in ("http", "https")
        if values.get(f"{scheme}_proxy", fallback)
    }


def _matches_no_proxy(host: str, entries: str) -> bool:
    hostname = str(host).split(":", 1)[0].casefold().rstrip(".")
    for raw_entry in str(entries).split(","):
        entry = raw_entry.strip().casefold().lstrip(".").rstrip(".")
        if not entry:
            continue
        if entry == "*":
            return True
        if hostname == entry or hostname.endswith(f".{entry}"):
            return True
    return False


class _EnvironmentProxyHandler(ProxyHandler):
    """A ProxyHandler that never asks urllib to consult ambient environment state."""

    def __init__(self, proxies: Mapping[str, str], *, no_proxy: str) -> None:
        super().__init__(dict(proxies))
        self._no_proxy = str(no_proxy)

    def proxy_open(self, request: Request, proxy: str, request_type: str):
        original_type = request.type
        proxy_type, user, password, hostport = _parse_proxy(proxy)
        if proxy_type is None:
            proxy_type = original_type
        if request.host and _matches_no_proxy(request.host, self._no_proxy):
            return None
        if user and password:
            user_pass = f"{unquote(user)}:{unquote(password)}"
            encoded = base64.b64encode(user_pass.encode()).decode("ascii")
            request.add_header("Proxy-authorization", f"Basic {encoded}")
        request.set_proxy(unquote(hostport), proxy_type)
        if original_type == proxy_type or original_type == "https":
            return None
        return self.parent.open(request, timeout=request.timeout)


class _TrustedGitHubRedirectHandler(HTTPRedirectHandler):
    """Reject redirects outside the explicitly trusted GitHub hosts."""

    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self._allowed_hosts = {host.casefold() for host in allowed_hosts}

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        parsed = urlparse(new_url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() not in self._allowed_hosts
        ):
            raise ValueError("GitHub release redirect left the trusted host")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _repository_components(repository: str) -> tuple[str, str]:
    parts = str(repository).split("/")
    if len(parts) != 2 or not all(_is_safe_component(part) for part in parts):
        raise ValueError("invalid GitHub repository")
    return parts[0], parts[1]


def _is_safe_component(value: str) -> bool:
    return bool(
        _COMPONENT_PATTERN.fullmatch(value)
        and value not in {".", ".."}
        and not value.startswith("-")
        and not value.endswith(".")
    )


__all__ = [
    "GITHUB_API_ACCEPT",
    "GITHUB_API_USER_AGENT",
    "MAX_RELEASE_RESULTS",
    "fetch_release_inventory",
    "fetch_latest_release",
]
