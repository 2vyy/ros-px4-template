"""Load ENU path geometry."""

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
