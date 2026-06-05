"""Immutable FSM inputs + mission-graph data types."""

from __future__ import annotations

from dataclasses import dataclass, field

from ros_px4_template_core.lib.mission.detection import Detection


@dataclass(frozen=True)
class Inputs:
    """Immutable per-tick snapshot the engine and all behaviors/guards read."""

    now: float
    pose_enu: tuple[float, float, float]
    yaw_enu: float
    armed: bool
    altitude_ok: bool
    estimate_ok: bool
    detections: tuple[Detection, ...] = ()
    detection_stability: dict[int, int] = field(default_factory=dict)
    input_ages: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StateDef:
    name: str
    behavior: str
    params: dict


@dataclass(frozen=True)
class TransitionDef:
    src: str | None  # None == safety tier (any state)
    guard: str
    params: dict
    dst: str


@dataclass(frozen=True)
class Mission:
    initial: str
    states: dict[str, StateDef]
    safety: tuple[TransitionDef, ...]
    transitions: tuple[TransitionDef, ...]
    terminal: frozenset[str]
