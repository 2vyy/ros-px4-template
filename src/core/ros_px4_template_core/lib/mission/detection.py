"""Detector-agnostic metric detection."""

from __future__ import annotations

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
