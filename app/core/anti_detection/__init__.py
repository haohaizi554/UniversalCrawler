"""Shared anti-detection strategy seam for crawler runtime setup."""

from .factory import build_browser_anti_detection
from .models import AntiDetectionContext
from .strategies import BrowserAntiDetectionStrategy
from .user_agents import UserAgentRotator, resolve_user_agent, should_rotate_user_agent, user_agent_rotator

__all__ = (
    "AntiDetectionContext",
    "BrowserAntiDetectionStrategy",
    "UserAgentRotator",
    "build_browser_anti_detection",
    "resolve_user_agent",
    "should_rotate_user_agent",
    "user_agent_rotator",
)
