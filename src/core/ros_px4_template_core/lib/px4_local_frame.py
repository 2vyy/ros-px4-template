"""Stateful PX4 local-frame tracker: latch the takeoff origin (NED) and track EKF resets.

Read path (``observe``): PX4 local NED minus accumulated EKF-reset deltas ->
takeoff-anchored ENU (no yaw rotation; the pose stays continuous across resets).
Write path (``setpoint_origin_ned``): latched origin + accumulated EKF-reset deltas,
so streamed setpoints stay on the same physical point across resets.
"""

from __future__ import annotations

from dataclasses import dataclass

from ros_px4_template_core.lib.frames import ned_to_enu, px4_local_z_ned


@dataclass
class Px4LocalFrame:
    """Latch the takeoff origin in NED and track EKF resets."""

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
        # Subtract accumulated EKF-reset deltas so the anchored pose is continuous
        # across resets (write path adds them back via setpoint_origin_ned). On the
        # first sample all adjusts are 0.0, so this is a no-op then.
        local_x = x_ned - (self.home_x_ned or 0.0) - self.x_adjust_ned
        local_y = y_ned - (self.home_y_ned or 0.0) - self.y_adjust_ned
        local_z = local_z - self.z_adjust_ned
        return ned_to_enu(local_x, local_y, local_z)

    @property
    def setpoint_origin_ned(self) -> tuple[float, float, float]:
        return (
            (self.home_x_ned or 0.0) + self.x_adjust_ned,
            (self.home_y_ned or 0.0) + self.y_adjust_ned,
            (self.home_z_ned or 0.0) + self.z_adjust_ned,
        )
