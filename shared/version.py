"""无 UI 依赖的项目版本契约。"""

__version__ = "3.6.21"


def format_version_label(value: object, *, fallback: str = "v?") -> str:
    """Return a display label with exactly one leading ``v``."""

    text = str(value or "").strip()
    normalized = text.lstrip("vV")
    return f"v{normalized}" if normalized else fallback


__all__ = ["__version__", "format_version_label"]
