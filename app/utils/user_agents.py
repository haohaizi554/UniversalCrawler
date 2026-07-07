"""User-Agent rotation helpers backed by fake-useragent."""

from __future__ import annotations

from threading import RLock
from typing import Any, Mapping

from app.config import DEFAULT_USER_AGENT

try:
    from fake_useragent import UserAgent
except Exception:  # pragma: no cover - import-time guard for optional installs
    UserAgent = None  # type: ignore[assignment]

RANDOM_USER_AGENT_SENTINELS = {"random", "rotate", "rotating", "fake", "fake-useragent", "fake_useragent"}


class UserAgentRotator:
    """Return browser-like User-Agent strings with a safe deterministic fallback."""

    def __init__(self, fallback_user_agent: str = DEFAULT_USER_AGENT):
        self.fallback_user_agent = fallback_user_agent
        self._lock = RLock()
        self._provider: Any | None = None

    def random(self, fallback_user_agent: str | None = None) -> str:
        fallback = str(fallback_user_agent or self.fallback_user_agent)
        if UserAgent is None:
            return fallback
        try:
            with self._lock:
                if self._provider is None:
                    try:
                        self._provider = UserAgent(
                            browsers=["Chrome", "Edge"],
                            platforms=["desktop"],
                            fallback=fallback,
                        )
                    except TypeError:
                        self._provider = UserAgent()
                user_agent = str(self._provider.random or "").strip()
            return user_agent or fallback
        except Exception:
            return fallback


user_agent_rotator = UserAgentRotator()


def _clean_user_agent(value: object) -> str:
    return str(value or "").strip()


def should_rotate_user_agent(configured_user_agent: object, default_user_agent: str = DEFAULT_USER_AGENT) -> bool:
    configured = _clean_user_agent(configured_user_agent)
    if not configured:
        return True
    if configured.lower() in RANDOM_USER_AGENT_SENTINELS:
        return True
    return configured == _clean_user_agent(default_user_agent)


def resolve_user_agent(
    source: str,
    config: Mapping[str, Any] | None = None,
    *,
    configured_user_agent: object = None,
    default_user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    del source
    runtime_user_agent = _clean_user_agent((config or {}).get("ua") if isinstance(config, Mapping) else None)
    if runtime_user_agent and runtime_user_agent.lower() not in RANDOM_USER_AGENT_SENTINELS:
        return runtime_user_agent
    if runtime_user_agent.lower() in RANDOM_USER_AGENT_SENTINELS or should_rotate_user_agent(
        configured_user_agent,
        default_user_agent,
    ):
        return user_agent_rotator.random(default_user_agent)
    return _clean_user_agent(configured_user_agent) or default_user_agent
