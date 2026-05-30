"""Assemble WaypointMission from path geometry and profile params."""

from __future__ import annotations

from dataclasses import dataclass

from ros_px4_template_core.lib.waypoint_mission import (
    EnuPoint,
    MissionDefaults,
    WaypointMission,
)


@dataclass(frozen=True)
class MissionProfileParams:
    tolerance_m: float = 0.4
    hold_s: float = 2.0
    z_tolerance_m: float | None = None  # None → 3D distance mode


def build_mission_profile(
    waypoints: tuple[EnuPoint, ...],
    params: MissionProfileParams,
    *,
    frame_id: str = "map",
) -> WaypointMission:
    """Build runtime mission state from loaded path points and profile flags."""
    return WaypointMission(
        frame_id=frame_id,
        defaults=MissionDefaults(
            tolerance_m=params.tolerance_m,
            hold_s=params.hold_s,
            z_tolerance_m=params.z_tolerance_m,
        ),
        waypoints=waypoints,
    )
