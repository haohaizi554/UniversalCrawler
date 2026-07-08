"""Playwright stealth script loading and injection helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

STEALTH_SCRIPT_PATH = Path(__file__).with_name("stealth.js")


@lru_cache(maxsize=1)
def load_stealth_script() -> str:
    """Load the bundled stealth init script once per process."""
    return STEALTH_SCRIPT_PATH.read_text(encoding="utf-8")


def apply_stealth_to_context(context: Any) -> None:
    """Inject stealth JavaScript before any page script runs."""
    if context is None or not hasattr(context, "add_init_script"):
        return
    context.add_init_script(load_stealth_script())
