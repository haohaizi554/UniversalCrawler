"""抓取运行时统一使用的反检测策略接口。"""

from .factory import build_browser_anti_detection
from .models import AntiDetectionContext
from .stealth import apply_stealth_to_context, load_stealth_script
from .strategies import BrowserAntiDetectionStrategy
from .user_agents import UserAgentRotator, resolve_user_agent, should_rotate_user_agent, user_agent_rotator

__all__ = (
    "AntiDetectionContext",
    "BrowserAntiDetectionStrategy",
    "UserAgentRotator",
    "apply_stealth_to_context",
    "build_browser_anti_detection",
    "load_stealth_script",
    "resolve_user_agent",
    "should_rotate_user_agent",
    "user_agent_rotator",
)
