"""Detector-agnostic metric detection + body→ENU offset helper."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """One metric marker detection.

    ``offset_body_flu`` is the marker position relative to the drone in body
    Forward-Left-Up metres. ``pose_world`` is an optional detector-supplied world
    pose (unused by ArUco; resolved by ``marker_localizer`` from the marker map).
    """

    id: int
    offset_body_flu: tuple[float, float, float]
    stamp: float
    pose_world: tuple[float, float, float] | None = None


def body_flu_to_enu_offset(
    offset_body_flu: tuple[float, float, float], yaw_enu: float
) -> tuple[float, float]:
    """Rotate a body-FLU horizontal offset into world ENU using the drone yaw."""
    forward, left, _up = offset_body_flu
    cos_y = math.cos(yaw_enu)
    sin_y = math.sin(yaw_enu)
    east = forward * cos_y - left * sin_y
    north = forward * sin_y + left * cos_y
    return (east, north)
