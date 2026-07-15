"""Resolve the exact Playwright Chromium runtime owned by this build."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_BROWSER_ORDER = (
    "chromium",
    "chromium-headless-shell",
    "ffmpeg",
    "winldd",
)
_REQUIRED_BROWSERS = frozenset(("chromium", "ffmpeg"))
_CACHE_PREFIX = {
    "chromium": "chromium",
    "chromium-headless-shell": "chromium_headless_shell",
    "ffmpeg": "ffmpeg",
    "winldd": "winldd",
}


def installed_browser_manifest_path() -> Path:
    import playwright

    return Path(playwright.__file__).resolve().parent / "driver" / "package" / "browsers.json"


def resolve_playwright_browser_directories(
    browser_root: Path,
    *,
    browser_manifest_path: Path | None = None,
) -> tuple[Path, ...]:
    """Return only browser revisions required by the installed Playwright package.

    The shared Playwright cache accumulates old Chromium, Firefox and WebKit
    revisions over time. Packaging that whole directory makes release size
    depend on machine history and can exceed the updater's safety limit.
    """

    root = Path(browser_root)
    manifest_path = Path(browser_manifest_path or installed_browser_manifest_path())
    try:
        payload: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read Playwright browser manifest: {manifest_path}") from exc
    entries = payload.get("browsers") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError(f"invalid Playwright browser manifest: {manifest_path}")

    revisions: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        revision = str(entry.get("revision") or "").strip()
        if name in _CACHE_PREFIX and revision:
            revisions[name] = revision

    missing_metadata = sorted(_REQUIRED_BROWSERS - revisions.keys())
    if missing_metadata:
        raise RuntimeError(
            "Playwright browser manifest is missing required entries: " + ", ".join(missing_metadata)
        )

    selected: list[Path] = []
    missing_directories: list[Path] = []
    for name in _BROWSER_ORDER:
        revision = revisions.get(name)
        if not revision:
            continue
        path = root / f"{_CACHE_PREFIX[name]}-{revision}"
        if path.is_dir():
            selected.append(path)
        else:
            missing_directories.append(path)
    if missing_directories:
        missing = "\n- ".join(str(path) for path in missing_directories)
        raise FileNotFoundError(
            "Playwright Chromium runtime is incomplete. Run `python -m playwright install chromium`.\n"
            f"- {missing}"
        )
    return tuple(selected)


__all__ = ["installed_browser_manifest_path", "resolve_playwright_browser_directories"]
