"""Compatibility exports for shared User-Agent rotation helpers."""

from app.utils.user_agents import (
    UserAgentRotator,
    resolve_user_agent,
    should_rotate_user_agent,
    user_agent_rotator,
)

__all__ = (
    "UserAgentRotator",
    "resolve_user_agent",
    "should_rotate_user_agent",
    "user_agent_rotator",
)
