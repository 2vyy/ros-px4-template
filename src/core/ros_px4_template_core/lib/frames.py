"""Pure coordinate-frame math for ROS 2 / PX4 — the single frame core.

All project code works in ENU (East-North-Up) per ROS REP-103; conversion to
PX4 NED happens only at the PX4 boundary. This module is the one authoritative
home for the *pure* frame transforms: it imports only ``math`` and ``numpy`` —
never ``rclpy``, ``cv2``, or ``scipy`` — so it is trivially unit-testable.

Frames
------
- **ENU** world: X=East, Y=North, Z=Up (right-handed). Project-internal frame.
- **NED** (PX4): X=North, Y=East, Z=Down. Only on the ``/fmu/*`` boundary.
- **Body FLU**: X=Forward, Y=Left, Z=Up (REP-103 body).
- **Camera optical**: X=Right, Y=Down, Z=Forward (into the scene).

Yaw
---
PX4 heading is NED yaw (0 = North, clockwise positive). ENU yaw is 0 = East,
counter-clockwise positive: ``yaw_enu = pi/2 - heading_ned`` (wrapped to [-pi, pi]).

Assumption — yaw-only / level flight
------------------------------------
The body<->world offset helpers use the drone *yaw* only; roll and pitch are
neglected (vehicle treated as level, camera as nadir). This is valid because the
vehicle never tilts fast or far enough for the residual offset error to matter
for these tasks. It is a stated limitation, not an oversight: a fork needing
tilt-accurate localization must extend the offset rotation to full attitude.

Reference: ROS REP-103 https://www.ros.org/reps/rep-0103.html
"""

from __future__ import annotations

import math

import numpy as np


def ned_to_enu(x_ned: float, y_ned: float, z_ned: float) -> tuple[float, float, float]:
    """Convert an NED position to ENU. Example: (1, 2, -3) -> (2, 1, 3)."""
    return y_ned, x_ned, -z_ned


def enu_to_ned(x_enu: float, y_enu: float, z_enu: float) -> tuple[float, float, float]:
    """Convert an ENU position to NED. Example: (2, 1, 3) -> (1, 2, -3)."""
    return y_enu, x_enu, -z_enu


def enu_yaw_from_heading(heading_ned: float) -> float:
    """PX4 heading (NED yaw: 0=North, CW+) -> ENU yaw (0=East, CCW+), wrapped."""
    yaw = math.pi / 2.0 - heading_ned
    return math.atan2(math.sin(yaw), math.cos(yaw))


def enu_yaw_from_quaternion(q_w: float, q_x: float, q_y: float, q_z: float) -> float:
    """Extract ENU yaw from an ENU quaternion."""
    return math.atan2(2.0 * (q_w * q_z + q_x * q_y), 1.0 - 2.0 * (q_y * q_y + q_z * q_z))


def enu_quaternion_from_yaw(yaw_enu: float) -> tuple[float, float, float, float]:
    """Create an ENU quaternion (w, x, y, z) from an ENU yaw angle."""
    return (math.cos(yaw_enu / 2.0), 0.0, 0.0, math.sin(yaw_enu / 2.0))


def px4_local_z_ned(
    z_ned: float,
    *,
    z_global: bool,
    origin_z_ned: float | None,
) -> tuple[float, float | None]:
    """Normalize PX4 ``VehicleLocalPosition.z`` to local NED (zero at boot).

    When an origin is latched, always express altitude relative to it so read and
    write paths stay consistent even if ``z_global`` toggles mid-flight.
    """
    if origin_z_ned is not None:
        return z_ned - origin_z_ned, origin_z_ned
    if z_global:
        return 0.0, z_ned
    return z_ned, None


def enu_setpoint_to_px4_ned(
    x_enu: float,
    y_enu: float,
    z_enu: float,
    *,
    origin_x_ned: float = 0.0,
    origin_y_ned: float = 0.0,
    origin_z_ned: float | None = None,
    z_ekf_adjust_ned: float = 0.0,
) -> tuple[float, float, float]:
    """Convert an anchored-ENU setpoint to PX4 local NED for ``TrajectorySetpoint``.

    ``origin_*_ned`` shift the anchored frame back onto PX4's EKF-local frame. When
    ``origin_z_ned`` is set (``VehicleLocalPosition.z_global``), the boot altitude is
    added so setpoints match PX4's fused ``z``. ``z_ekf_adjust_ned`` mirrors
    ``MulticopterPositionControl::adjustSetpointForEKFResets`` for streamed setpoints.
    """
    x_ned, y_ned, z_local = enu_to_ned(x_enu, y_enu, z_enu)
    if origin_z_ned is not None:
        z_ned = origin_z_ned + z_local + z_ekf_adjust_ned
    else:
        z_ned = z_local + z_ekf_adjust_ned
    return origin_x_ned + x_ned, origin_y_ned + y_ned, z_ned


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


def enu_offset_to_body_flu(
    offset_enu: tuple[float, float, float], yaw_enu: float
) -> tuple[float, float]:
    """Rotate a world-ENU horizontal offset into a body-FLU offset using the drone yaw.
    Exact complement of :func:`body_flu_to_enu_offset`."""
    east, north, _up = offset_enu
    cos_y = math.cos(yaw_enu)
    sin_y = math.sin(yaw_enu)
    forward = east * cos_y + north * sin_y
    left = -east * sin_y + north * cos_y
    return (forward, left)


def marker_world_from_drone(
    drone_world: tuple[float, float, float],
    offset_body_flu: tuple[float, float, float],
    yaw_enu: float,
) -> tuple[float, float, float]:
    """Forward localization: drone world pose + body-FLU offset -> marker world pose."""
    east, north = body_flu_to_enu_offset(offset_body_flu, yaw_enu)
    up = offset_body_flu[2]
    return (drone_world[0] + east, drone_world[1] + north, drone_world[2] + up)


def drone_pose_from_marker(
    marker_world: tuple[float, float, float],
    offset_body_flu: tuple[float, float, float],
    yaw_enu: float,
) -> tuple[float, float, float]:
    """Inverse (relocalization): known marker world pose + body-FLU offset -> drone world pose.

    Exact complement of :func:`marker_world_from_drone`.
    """
    east, north = body_flu_to_enu_offset(offset_body_flu, yaw_enu)
    up = offset_body_flu[2]
    return (marker_world[0] - east, marker_world[1] - north, marker_world[2] - up)


def camera_to_body(
    tvec_cam: np.ndarray | list[float] | tuple[float, ...],
    cam_ext_r: np.ndarray | list[list[float]],
    cam_ext_t: np.ndarray | list[float] | tuple[float, ...],
) -> tuple[float, float, float]:
    """Map a point from the camera optical frame to body FLU: ``R_ext @ t + t_ext``.

    Args:
        tvec_cam: Point in camera frame (array-like, 3 elements).
        cam_ext_r: Camera->body extrinsic rotation (array-like 3x3).
        cam_ext_t: Camera translation relative to body CG (array-like, 3 elements).

    Returns:
        ``(x, y, z)`` in body FLU metres.
    """
    t = np.asarray(tvec_cam, dtype=float).reshape(3, 1)
    r = np.asarray(cam_ext_r, dtype=float).reshape(3, 3)
    t0 = np.asarray(cam_ext_t, dtype=float).reshape(3, 1)
    body = (r @ t) + t0
    return (float(body[0, 0]), float(body[1, 0]), float(body[2, 0]))
