from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

__all__ = [
    "RuntimeStateConfig",
    "ScheduledAiBriefRequest",
    "ScheduledAiBriefRunner",
    "SupabaseRuntimeStateClient",
    "run_scheduled_ai_brief",
]

_RUNNER_EXPORTS = {
    "ScheduledAiBriefRequest",
    "ScheduledAiBriefRunner",
    "run_scheduled_ai_brief",
}
_STATE_EXPORTS = {
    "RuntimeStateConfig",
    "SupabaseRuntimeStateClient",
}

if TYPE_CHECKING:
    from .runner import (
        ScheduledAiBriefRequest,
        ScheduledAiBriefRunner,
        run_scheduled_ai_brief,
    )
    from .state import RuntimeStateConfig, SupabaseRuntimeStateClient


def __getattr__(name: str) -> Any:
    if name in _RUNNER_EXPORTS:
        module = import_module(".runner", __name__)
    elif name in _STATE_EXPORTS:
        module = import_module(".state", __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(module, name)
    globals()[name] = value
    return value
