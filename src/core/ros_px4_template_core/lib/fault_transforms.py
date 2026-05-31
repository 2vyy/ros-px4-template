# src/core/ros_px4_template_core/lib/fault_transforms.py
"""Pure fault-injection transforms for position telemetry — no ROS.

All functions accept and return raw NED values matching VehicleLocalPosition.
The caller (tools/fault_inject.py) is responsible for subscribing/publishing.
"""

from __future__ import annotations


def apply_gps_dropout(
    xy_valid: bool, z_valid: bool, x: float, y: float, z: float
) -> tuple[bool, bool, float, float, float]:
    """Mark position as invalid (GPS dropout). Position values pass through unchanged."""
    return False, False, x, y, z


def apply_position_noise(
    xy_valid: bool,
    z_valid: bool,
    x: float,
    y: float,
    z: float,
    sigma_m: float,
    rand_x: float,
    rand_y: float,
) -> tuple[bool, bool, float, float, float]:
    """Add Gaussian noise to XY. rand_x/rand_y are pre-drawn N(0,1) samples."""
    return xy_valid, z_valid, x + rand_x * sigma_m, y + rand_y * sigma_m, z


def apply_altitude_spike(
    xy_valid: bool, z_valid: bool, x: float, y: float, z: float, spike_m: float
) -> tuple[bool, bool, float, float, float]:
    """Shift NED z by spike_m (positive = drone appears to dive in NED)."""
    return xy_valid, z_valid, x, y, z + spike_m
