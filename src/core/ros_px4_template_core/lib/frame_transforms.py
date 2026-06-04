"""Frame transformation utilities for ROS 2 / PX4 projects.

All project code works in ENU (East-North-Up) / REP-103.
These utilities convert at the PX4 boundary (NED ↔ ENU).

Reference:
    ROS REP-103: https://www.ros.org/reps/rep-0103.html
    PX4 frames: https://docs.px4.io/main/en/ros/ros2_comm.html
"""

from __future__ import annotations

import math
from dataclasses import dataclass


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


def enu_yaw_from_heading(heading_ned: float) -> float:
    """Convert PX4 heading (NED yaw: 0=North, clockwise+) to ENU yaw (0=East, CCW+)."""
    yaw = math.pi / 2.0 - heading_ned
    return math.atan2(math.sin(yaw), math.cos(yaw))  # wrap to [-pi, pi]


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


@dataclass
class Px4LocalFrame:
    """Latch the takeoff origin in NED and track EKF resets.

    Read path (``observe``): PX4 local NED -> takeoff-anchored ENU (no yaw
    rotation). Write path (``setpoint_origin_ned``): the effective NED setpoint
    origin = latched origin + accumulated EKF-reset deltas, so streamed setpoints
    stay on the same physical point across resets.
    """

    home_x_ned: float | None = None
    home_y_ned: float | None = None
    home_z_ned: float | None = None
    x_adjust_ned: float = 0.0
    y_adjust_ned: float = 0.0
    z_adjust_ned: float = 0.0
    _xy_reset_counter: int = -1
    _z_reset_counter: int = -1

    @property
    def ready(self) -> bool:
        return self.home_z_ned is not None

    def observe(
        self,
        x_ned: float,
        y_ned: float,
        z_ned: float,
        *,
        z_global: bool,
        xy_reset_counter: int,
        delta_x: float,
        delta_y: float,
        z_reset_counter: int,
        delta_z: float,
    ) -> tuple[float, float, float]:
        """Update reset state, latch origin if needed, return anchored ENU (x, y, z)."""
        if self._xy_reset_counter >= 0 and xy_reset_counter != self._xy_reset_counter:
            self.x_adjust_ned += float(delta_x)
            self.y_adjust_ned += float(delta_y)
        self._xy_reset_counter = int(xy_reset_counter)
        if self._z_reset_counter >= 0 and z_reset_counter != self._z_reset_counter:
            self.z_adjust_ned += float(delta_z)
        self._z_reset_counter = int(z_reset_counter)

        local_z, origin_z = px4_local_z_ned(z_ned, z_global=z_global, origin_z_ned=self.home_z_ned)
        if self.home_z_ned is None:
            self.home_x_ned = x_ned
            self.home_y_ned = y_ned
            if origin_z is not None:
                self.home_z_ned = origin_z
            else:
                self.home_z_ned = z_ned
                local_z = 0.0
        local_x = x_ned - (self.home_x_ned or 0.0)
        local_y = y_ned - (self.home_y_ned or 0.0)
        return ned_to_enu(local_x, local_y, local_z)

    @property
    def setpoint_origin_ned(self) -> tuple[float, float, float]:
        return (
            (self.home_x_ned or 0.0) + self.x_adjust_ned,
            (self.home_y_ned or 0.0) + self.y_adjust_ned,
            (self.home_z_ned or 0.0) + self.z_adjust_ned,
        )
