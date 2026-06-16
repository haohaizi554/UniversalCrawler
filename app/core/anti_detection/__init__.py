"""Shared anti-detection strategy seam for crawler runtime setup."""

from .factory import build_browser_anti_detection
from .models import AntiDetectionContext
from .strategies import BrowserAntiDetectionStrategy

__all__ = (
    "AntiDetectionContext",
    "BrowserAntiDetectionStrategy",
    "build_browser_anti_detection",
)
