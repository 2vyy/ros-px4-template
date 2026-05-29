"""Setpoint hold helpers for offboard_controller."""

from __future__ import annotations


def effective_target_setpoint(
    commanded_enu: tuple[float, float, float],
    current_enu: tuple[float, float, float],
    last_command_monotonic: float | None,
    now_monotonic: float,
    timeout_s: float,
) -> tuple[float, float, float]:
    """Return commanded setpoint, or hold at *current_enu* if the command stream is stale.

    When *last_command_monotonic* is None (no ``/drone/target_pose`` yet), hold in place
    instead of flying toward the boot-time default (0, 0, target_alt).
    """
    if last_command_monotonic is None:
        return current_enu
    if now_monotonic - last_command_monotonic > timeout_s:
        return current_enu
    return commanded_enu
