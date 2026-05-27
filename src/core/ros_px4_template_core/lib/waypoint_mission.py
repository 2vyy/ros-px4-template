"""Load and evaluate waypoint missions (ENU, x/y/z only)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EnuPoint:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class MissionDefaults:
    tolerance_m: float = 0.4
    hold_s: float = 2.0


@dataclass(frozen=True)
class MarkerConfig:
    hold_offset_enu: EnuPoint
    hold_duration_s: float = 30.0
    lost_timeout_s: float = 1.0
    acquire_frames: int = 5


@dataclass(frozen=True)
class WaypointMission:
    frame_id: str
    defaults: MissionDefaults
    waypoints: tuple[EnuPoint, ...]
    marker: MarkerConfig | None = None


def _point_from_dict(d: dict[str, Any]) -> EnuPoint:
    return EnuPoint(float(d["x"]), float(d["y"]), float(d["z"]))


def load_mission_yaml(path: str | Path) -> WaypointMission:
    """Load a mission YAML file."""
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        msg = "mission file must be a mapping"
        raise ValueError(msg)

    defaults_raw = data.get("defaults", {})
    defaults = MissionDefaults(
        tolerance_m=float(defaults_raw.get("tolerance_m", 0.4)),
        hold_s=float(defaults_raw.get("hold_s", 2.0)),
    )

    wps_raw = data.get("waypoints")
    if not wps_raw:
        msg = "mission must contain waypoints"
        raise ValueError(msg)
    waypoints = tuple(_point_from_dict(wp) for wp in wps_raw)

    marker = None
    if "marker" in data:
        m = data["marker"]
        off = m.get("hold_offset_enu", {"x": 0.0, "y": 0.0, "z": 1.5})
        marker = MarkerConfig(
            hold_offset_enu=_point_from_dict(off),
            hold_duration_s=float(m.get("hold_duration_s", 30.0)),
            lost_timeout_s=float(m.get("lost_timeout_s", 1.0)),
            acquire_frames=int(m.get("acquire_frames", 5)),
        )

    return WaypointMission(
        frame_id=str(data.get("frame_id", "map")),
        defaults=defaults,
        waypoints=waypoints,
        marker=marker,
    )


def reached(
    current: tuple[float, float, float],
    target: EnuPoint,
    tolerance_m: float,
) -> bool:
    """True when horizontal+vertical distance is within tolerance."""
    dx = current[0] - target.x
    dy = current[1] - target.y
    dz = current[2] - target.z
    return math.sqrt(dx * dx + dy * dy + dz * dz) <= tolerance_m


def current_waypoint(mission: WaypointMission, index: int) -> EnuPoint | None:
    if index < 0 or index >= len(mission.waypoints):
        return None
    return mission.waypoints[index]
