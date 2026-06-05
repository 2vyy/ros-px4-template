"""Command vocabulary: the only things a node executes for the FSM."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoTo:
    x: float
    y: float
    z: float
    yaw: float | None = None


@dataclass(frozen=True)
class Hold:
    """Hold the current/last commanded position."""


@dataclass(frozen=True)
class Land:
    """Reserved for the center_land follow-on; not emitted by v1 behaviors."""


Command = GoTo | Hold | Land


@dataclass(frozen=True)
class BehaviorResult:
    command: Command
    signals: dict[str, object]
