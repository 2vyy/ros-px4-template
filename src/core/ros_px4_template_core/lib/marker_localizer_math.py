"""Recover the drone's anchored-ENU pose from a known marker world pose."""

from __future__ import annotations

from ros_px4_template_core.lib.mission.detection import body_flu_to_enu_offset


def drone_pose_from_marker(
    marker_world: tuple[float, float, float],
    offset_body_flu: tuple[float, float, float],
    yaw_enu: float,
) -> tuple[float, float, float]:
    """drone_enu = marker_enu - rotate(offset_horizontal) ; z = marker_z - up_offset."""
    east, north = body_flu_to_enu_offset(offset_body_flu, yaw_enu)
    up = offset_body_flu[2]
    return (marker_world[0] - east, marker_world[1] - north, marker_world[2] - up)
