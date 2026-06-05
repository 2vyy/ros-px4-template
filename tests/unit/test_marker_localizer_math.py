"""Unit tests for relocalization math."""

from __future__ import annotations

import math

from ros_px4_template_core.lib.marker_localizer_math import drone_pose_from_marker


def test_recovers_drone_position_yaw_zero() -> None:
    # Marker at world (8,0,0). Drone sees it 8 m forward, 0 left, 3 m down (up=-3).
    # yaw 0 -> forward is East. Drone must be at (0,0,3).
    x, y, z = drone_pose_from_marker(
        marker_world=(8.0, 0.0, 0.0), offset_body_flu=(8.0, 0.0, -3.0), yaw_enu=0.0
    )
    assert math.isclose(x, 0.0, abs_tol=1e-6)
    assert math.isclose(y, 0.0, abs_tol=1e-6)
    assert math.isclose(z, 3.0, abs_tol=1e-6)


def test_recovers_drone_position_yaw_90() -> None:
    # yaw pi/2 -> forward is North. Marker 5 m forward => 5 m North of drone.
    # Marker at (0,5,0), offset forward 5, up -3 -> drone at (0,0,3).
    x, y, z = drone_pose_from_marker(
        marker_world=(0.0, 5.0, 0.0), offset_body_flu=(5.0, 0.0, -3.0), yaw_enu=math.pi / 2
    )
    assert math.isclose(x, 0.0, abs_tol=1e-6)
    assert math.isclose(y, 0.0, abs_tol=1e-6)
    assert math.isclose(z, 3.0, abs_tol=1e-6)
