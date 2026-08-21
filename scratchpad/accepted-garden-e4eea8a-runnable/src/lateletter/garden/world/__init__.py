"""Internal deterministic Garden world core.

This package is intentionally not connected to the terminal or browser runtime
yet.  It becomes live only when both renderer-local gameplay owners are removed
and replaced atomically by adapters around this core.
"""

from .commands import CommandKind, GardenCommand, command
from .engine import CommandResult, dispatch
from .model import WorldState, new_world

LIVE_RUNTIME_WIRED = False

__all__ = [
    "CommandKind",
    "CommandResult",
    "GardenCommand",
    "LIVE_RUNTIME_WIRED",
    "WorldState",
    "command",
    "dispatch",
    "new_world",
]
