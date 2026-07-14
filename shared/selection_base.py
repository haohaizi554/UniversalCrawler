"""Host-neutral secondary-selection protocol."""

from __future__ import annotations

from typing import Protocol


class SelectionStrategy(Protocol):
    """Choose item indices without depending on a GUI, CLI, or Web host."""

    @property
    def strategy_name(self) -> str:
        """Stable strategy identifier used for diagnostics."""
        ...

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """Return selected indices, or ``None`` when the user cancels."""
        ...


def is_selection_strategy(obj: object) -> bool:
    """Return whether *obj* satisfies the selection strategy protocol."""
    return (
        obj is not None
        and hasattr(obj, "select")
        and hasattr(obj, "strategy_name")
        and callable(getattr(obj, "select", None))
    )
