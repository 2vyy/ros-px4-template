"""Frame transformation utilities for ROS 2 / PX4 projects.

All project code works in ENU (East-North-Up) / REP-103.
These utilities convert at the PX4 boundary (NED ↔ ENU).

Reference:
    ROS REP-103: https://www.ros.org/reps/rep-0103.html
    PX4 frames: https://docs.px4.io/main/en/ros/ros2_comm.html
"""

from __future__ import annotations

import math

# Rotation quaternion (w,x,y,z) that transforms NED-expressed vectors to ENU.
# Represents 180° rotation about the (1/√2, 1/√2, 0) axis:
#   maps North→y_ENU, East→x_ENU, Down→−z_ENU.
_SQRT2_2 = math.sqrt(2.0) / 2.0
_Q_NED_TO_ENU = (0.0, _SQRT2_2, _SQRT2_2, 0.0)
_Q_ENU_TO_NED = (0.0, -_SQRT2_2, -_SQRT2_2, 0.0)


def ned_to_enu(x_ned: float, y_ned: float, z_ned: float) -> tuple[float, float, float]:
    """Convert NED position to ENU position.

    Args:
        x_ned: North component (meters).
        y_ned: East component (meters).
        z_ned: Down component (meters, positive downward).

    Returns:
        Tuple of (x_enu, y_enu, z_enu) in meters.

    Example:
        >>> ned_to_enu(1.0, 2.0, -3.0)
        (2.0, 1.0, 3.0)
    """
    return y_ned, x_ned, -z_ned


def enu_to_ned(x_enu: float, y_enu: float, z_enu: float) -> tuple[float, float, float]:
    """Convert ENU position to NED for PX4 trajectory setpoints.

    Args:
        x_enu: East component (meters).
        y_enu: North component (meters).
        z_enu: Up component (meters, positive upward).

    Returns:
        Tuple of (x_ned, y_ned, z_ned) in meters.

    Example:
        >>> enu_to_ned(2.0, 1.0, 3.0)
        (1.0, 2.0, -3.0)
    """
    return y_enu, x_enu, -z_enu


def velocity_ned_to_enu(vx_ned: float, vy_ned: float, vz_ned: float) -> tuple[float, float, float]:
    """Convert NED velocity to ENU velocity.

    Identical axis swap as positions: (vN, vE, vD) → (vE, vN, −vD).
    """
    return vy_ned, vx_ned, -vz_ned


def velocity_enu_to_ned(vx_enu: float, vy_enu: float, vz_enu: float) -> tuple[float, float, float]:
    """Convert ENU velocity to NED velocity for PX4 TrajectorySetpoint."""
    return vy_enu, vx_enu, -vz_enu


def yaw_ned_to_enu(yaw_ned: float) -> float:
    """Convert NED yaw (CW from North, radians) to ENU yaw (CCW from East, radians).

    Relationship: yaw_enu = π/2 − yaw_ned, wrapped to [−π, π].

    Examples:
        yaw_ned=0   (North) → yaw_enu=π/2  (North)
        yaw_ned=π/2 (East)  → yaw_enu=0    (East)
    """
    raw = math.pi / 2.0 - yaw_ned
    return (raw + math.pi) % (2.0 * math.pi) - math.pi


def yaw_enu_to_ned(yaw_enu: float) -> float:
    """Convert ENU yaw (CCW from East, radians) to NED yaw (CW from North, radians).

    Symmetric with yaw_ned_to_enu: yaw_ned = π/2 − yaw_enu, wrapped to [−π, π].
    """
    raw = math.pi / 2.0 - yaw_enu
    return (raw + math.pi) % (2.0 * math.pi) - math.pi


def _quat_mul(
    q1: tuple[float, float, float, float],
    q2: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Hamilton product of two unit quaternions (w, x, y, z)."""
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def quaternion_ned_to_enu(
    w: float, x: float, y: float, z: float
) -> tuple[float, float, float, float]:
    """Convert a body-to-NED quaternion (PX4 VehicleAttitude convention) to body-to-ENU.

    q_body_enu = Q_NED_TO_ENU ⊗ q_body_ned

    Args:
        w, x, y, z: unit quaternion components (body-to-NED, PX4 convention).

    Returns:
        (w, x, y, z) body-to-ENU unit quaternion.
    """
    return _quat_mul(_Q_NED_TO_ENU, (w, x, y, z))


def quaternion_enu_to_ned(
    w: float, x: float, y: float, z: float
) -> tuple[float, float, float, float]:
    """Convert a body-to-ENU quaternion to body-to-NED (PX4 VehicleAttitude convention).

    q_body_ned = Q_ENU_TO_NED ⊗ q_body_enu

    Args:
        w, x, y, z: unit quaternion components (body-to-ENU).

    Returns:
        (w, x, y, z) body-to-NED unit quaternion.
    """
    return _quat_mul(_Q_ENU_TO_NED, (w, x, y, z))
