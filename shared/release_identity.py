"""产品版本与发布修订组成的稳定身份协议。

产品版本仍由 :mod:`shared.version` 维护；这里的修订号描述同一产品版本下
不可变发布物的先后次序。模块刻意不依赖 GUI 或更新服务，供运行时与构建工具共用。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from functools import total_ordering
from pathlib import Path
from typing import Any, Mapping


RELEASE_IDENTITY_FILENAME = "release_identity.json"
_SEMVER_PATTERN = re.compile(
    r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?"
)
_REVISION_TAG_PATTERN = re.compile(r"v(.+)-r([1-9]\d*)")
_MALFORMED_REVISION_TAG_PATTERN = re.compile(r"v.+-r(?:0\d*|-\d+|x.*)", re.IGNORECASE)


@dataclass(frozen=True)
class SemVer:
    """足以完成更新排序的 SemVer 值对象。"""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: str = ""

    @classmethod
    def parse(cls, value: Any) -> "SemVer":
        raw = str(value or "").strip()
        if raw.lower().startswith("v"):
            raw = raw[1:]
        match = _SEMVER_PATTERN.fullmatch(raw)
        if not match:
            raise ValueError(f"invalid semver: {value!r}")
        prerelease = tuple(part for part in (match.group(4) or "").split(".") if part)
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
            build=match.group(5) or "",
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + self.build
        return value


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left and not right:
        return 0
    if not left:
        return 1
    if not right:
        return -1
    for left_part, right_part in zip(left, right, strict=False):
        left_num = left_part.isdigit()
        right_num = right_part.isdigit()
        if left_num and right_num:
            left_number, right_number = int(left_part), int(right_part)
            if left_number != right_number:
                return -1 if left_number < right_number else 1
            continue
        if left_num != right_num:
            return -1 if left_num else 1
        if left_part != right_part:
            return -1 if left_part < right_part else 1
    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


def compare_semver(left: Any, right: Any) -> int:
    """按 SemVer 优先级比较；构建元数据不参与先后排序。"""

    left_version = SemVer.parse(left)
    right_version = SemVer.parse(right)
    left_core = (left_version.major, left_version.minor, left_version.patch)
    right_core = (right_version.major, right_version.minor, right_version.patch)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    return _compare_prerelease(left_version.prerelease, right_version.prerelease)


def _validate_revision(value: Any) -> int:
    # ``bool`` 是 ``int`` 的子类；显式排除可避免 JSON true 被解释为修订 1。
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("release revision must be a non-negative integer")
    return value


@total_ordering
@dataclass(frozen=True, eq=False)
class ReleaseIdentity:
    """一个可排序、可哈希且不可变的产品发布身份。"""

    version: str
    revision: int = 0
    _parsed_version: SemVer = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        parsed = SemVer.parse(self.version)
        object.__setattr__(self, "version", str(parsed))
        object.__setattr__(self, "revision", _validate_revision(self.revision))
        object.__setattr__(self, "_parsed_version", parsed)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ReleaseIdentity):
            return NotImplemented
        return compare_semver(self.version, other.version) == 0 and self.revision == other.revision

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ReleaseIdentity):
            return NotImplemented
        version_order = compare_semver(self.version, other.version)
        if version_order:
            return version_order < 0
        return self.revision < other.revision

    def __hash__(self) -> int:
        parsed = self._parsed_version
        return hash((parsed.major, parsed.minor, parsed.patch, parsed.prerelease, self.revision))

    @property
    def tag(self) -> str:
        return format_release_tag(self.version, self.revision)

    @property
    def candidate_id(self) -> str:
        """返回可跨 GUI/Web 往返、不会混淆同版本修订的稳定标识。"""

        return self.tag

    def display_label(self) -> str:
        if self.revision == 0:
            return f"{self.version} 初始版"
        return f"{self.version} 修订 {self.revision}"


def format_release_tag(version: Any, revision: int = 0) -> str:
    """把发布身份编码为唯一且规范的 Git/GitHub tag。"""

    parsed_version = str(SemVer.parse(version))
    normalized_revision = _validate_revision(revision)
    if normalized_revision == 0:
        return f"v{parsed_version}"
    return f"v{parsed_version}-r{normalized_revision}"


def parse_release_tag(value: Any) -> ReleaseIdentity:
    """解析规范发布 tag；不接受省略 ``v`` 或显式 ``-r0`` 的别名。"""

    raw = str(value or "").strip()
    if not raw.startswith("v"):
        raise ValueError(f"invalid release tag: {value!r}")
    revision_match = _REVISION_TAG_PATTERN.fullmatch(raw)
    if revision_match:
        try:
            identity = ReleaseIdentity(revision_match.group(1), int(revision_match.group(2)))
        except ValueError as exc:
            raise ValueError(f"invalid release tag: {value!r}") from exc
    else:
        if _MALFORMED_REVISION_TAG_PATTERN.fullmatch(raw):
            raise ValueError(f"invalid release tag: {value!r}")
        try:
            identity = ReleaseIdentity(raw[1:], 0)
        except ValueError as exc:
            raise ValueError(f"invalid release tag: {value!r}") from exc
    if identity.tag != raw:
        raise ValueError(f"invalid release tag: {value!r}")
    return identity


def _fallback_identity(version: Any) -> ReleaseIdentity:
    return ReleaseIdentity(version, 0)


def load_runtime_release_identity(
    install_root: str | Path | None = None,
    *,
    fallback_version: Any | None = None,
) -> ReleaseIdentity:
    """读取打包时写入的身份文件，缺失或损坏时兼容为初始修订。

    身份文件不是信任根；安装前仍由签名清单校验。这里的容错只保证旧安装和
    源码开发态可以启动，同时绝不采纳部分有效、部分冲突的元数据。
    """

    if fallback_version is None:
        from shared.version import __version__

        fallback_version = __version__
    fallback = _fallback_identity(fallback_version)
    root = Path(install_root) if install_root is not None else _default_install_root()
    try:
        payload = json.loads((root / RELEASE_IDENTITY_FILENAME).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            return fallback
        revision = payload.get("revision", payload.get("releaseRevision", 0))
        identity = ReleaseIdentity(str(payload.get("version") or ""), revision)
        if str(payload.get("tag") or "") != identity.tag:
            return fallback
        return identity
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return fallback


def _default_install_root() -> Path:
    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


__all__ = [
    "RELEASE_IDENTITY_FILENAME",
    "ReleaseIdentity",
    "SemVer",
    "compare_semver",
    "format_release_tag",
    "load_runtime_release_identity",
    "parse_release_tag",
]
