"""Frame transformation utilities for ROS 2 / PX4 projects.

All project code works in ENU (East-North-Up) / REP-103.
These utilities convert at the PX4 boundary (NED ↔ ENU).

Reference:
    ROS REP-103: https://www.ros.org/reps/rep-0103.html
    PX4 frames: https://docs.px4.io/main/en/ros/ros2_comm.html
"""

from __future__ import annotations

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
    origin_z_ned: float | None = None,
    z_ekf_adjust_ned: float = 0.0,
) -> tuple[float, float, float]:
    """Convert an ENU mission setpoint to NED for ``TrajectorySetpoint``.

    When ``origin_z_ned`` is set (``VehicleLocalPosition.z_global``), add the boot
    altitude so setpoints match PX4's fused ``z``. ``z_ekf_adjust_ned`` mirrors
    ``MulticopterPositionControl::adjustSetpointForEKFResets`` for streamed setpoints.
    """
    x_ned, y_ned, z_local = enu_to_ned(x_enu, y_enu, z_enu)
    if origin_z_ned is not None:
        z_ned = origin_z_ned + z_local + z_ekf_adjust_ned
    else:
        z_ned = z_local + z_ekf_adjust_ned
    return x_ned, y_ned, z_ned


@dataclass
class Px4ZFrameTracker:
    """Track PX4 vertical frame for telemetry and offboard setpoints."""

    home_z_ned: float | None = None
    setpoint_z_adjust_ned: float = 0.0
    _z_reset_counter: int = -1

    def observe(
        self,
        z_ned: float,
        *,
        z_global: bool,
        z_reset_counter: int,
        delta_z: float,
    ) -> float:
        """Update EKF reset state and return local NED z (meters, down-positive)."""
        if self._z_reset_counter >= 0 and z_reset_counter != self._z_reset_counter:
            self.setpoint_z_adjust_ned += float(delta_z)
        self._z_reset_counter = int(z_reset_counter)

        local_z, origin = px4_local_z_ned(
            z_ned,
            z_global=z_global,
            origin_z_ned=self.home_z_ned,
        )
        if self.home_z_ned is None:
            if origin is not None:
                self.home_z_ned = origin
            else:
                self.home_z_ned = z_ned
                local_z = 0.0
        return local_z
