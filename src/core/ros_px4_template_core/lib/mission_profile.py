"""Assemble WaypointMission from path geometry and profile params."""

from __future__ import annotations

from dataclasses import dataclass

from ros_px4_template_core.lib.waypoint_mission import (
    EnuPoint,
    MarkerConfig,
    MissionDefaults,
    WaypointMission,
)


@dataclass(frozen=True)
class MissionProfileParams:
    tolerance_m: float = 0.4
    hold_s: float = 2.0
    enable_marker_hover: bool = False
    marker_hold_offset_z: float = 1.5
    marker_hold_duration_s: float = 30.0
    marker_lost_timeout_s: float = 1.0
    marker_acquire_frames: int = 5


def build_mission_profile(
    waypoints: tuple[EnuPoint, ...],
    params: MissionProfileParams,
    *,
    frame_id: str = "map",
) -> WaypointMission:
    """Build runtime mission state from loaded path points and profile flags."""
    marker = None
    if params.enable_marker_hover:
        marker = MarkerConfig(
            hold_offset_enu=EnuPoint(0.0, 0.0, params.marker_hold_offset_z),
            hold_duration_s=params.marker_hold_duration_s,
            lost_timeout_s=params.marker_lost_timeout_s,
            acquire_frames=params.marker_acquire_frames,
        )
    return WaypointMission(
        frame_id=frame_id,
        defaults=MissionDefaults(tolerance_m=params.tolerance_m, hold_s=params.hold_s),
        waypoints=waypoints,
        marker=marker,
    )
