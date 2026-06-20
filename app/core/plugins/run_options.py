"""Pure run-option helpers shared by GUI, CLI, and Web."""

from __future__ import annotations

def build_missav_proxy_url(proxy_str: str) -> str:
    """Normalize preset labels and custom host:port values into URLs."""
    normalized = proxy_str.strip()
    if normalized == "Clash (7890)":
        return "http://127.0.0.1:7890"
    if normalized == "v2rayN (10809)":
        return "http://127.0.0.1:10809"
    if ":" in normalized:
        return normalized if normalized.startswith("http") else f"http://{normalized}"
    return "http://127.0.0.1:7890"
