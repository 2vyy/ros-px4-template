"""Load ENU path geometry and evaluate waypoint reachability."""

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
    z_tolerance_m: float | None = None  # None → 3D distance fallback


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
    x, y, z = float(d["x"]), float(d["y"]), float(d["z"])
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        raise ValueError(f"waypoint coordinates must be finite: x={x}, y={y}, z={z}")
    return EnuPoint(x, y, z)


def _waypoints_from_raw(wps_raw: list[Any]) -> tuple[EnuPoint, ...]:
    if not wps_raw:
        msg = "path must contain at least one waypoint"
        raise ValueError(msg)
    return tuple(_point_from_dict(wp) for wp in wps_raw)


def load_path_yaml(path: str | Path) -> tuple[EnuPoint, ...]:
    """Load ENU waypoints from a path file (YAML list or waypoints: mapping)."""
    data = yaml.safe_load(Path(path).read_text())
    if isinstance(data, list):
        return _waypoints_from_raw(data)
    if isinstance(data, dict) and data.get("waypoints"):
        return _waypoints_from_raw(data["waypoints"])
    msg = f"path file must be a waypoint list or contain waypoints: {path}"
    raise ValueError(msg)


def reached(
    current: tuple[float, float, float],
    target: EnuPoint,
    tolerance_m: float,
    *,
    z_tolerance_m: float | None = None,
) -> bool:
    """True when position is within tolerance of target.

    If z_tolerance_m is None, uses 3D Euclidean distance (backward-compatible).
    If set, enforces separate horizontal (XY) and vertical (Z) tolerances.
    """
    dx = current[0] - target.x
    dy = current[1] - target.y
    dz = current[2] - target.z
    if z_tolerance_m is None:
        return math.sqrt(dx * dx + dy * dy + dz * dz) <= tolerance_m
    return math.sqrt(dx * dx + dy * dy) <= tolerance_m and abs(dz) <= z_tolerance_m


def current_waypoint(mission: WaypointMission, index: int) -> EnuPoint | None:
    if index < 0 or index >= len(mission.waypoints):
        return None
    return mission.waypoints[index]
